"""After a Stop, an abandoned non-streamed model call is not tried again (review 2026-10-21, M4). The Stop returns
at once (call_stoppable), but the call's helper thread used to wait up to 5 s and retry, one paid call nobody reads.
The request now carries an abort that the Stop sets, and _call checks it before any retry."""

import threading
from types import SimpleNamespace

import pytest
from conftest import FakeDriver, RecordingIO, ScriptedClient

from openmob.agent import models
from openmob.agent.loop import Agent
from openmob.agent.models import AnthropicAdapter, CallPolicy
from openmob.config import Config
from openmob.phone.apps import AppResolver
from openmob.phone.base import TaskStopped

REPLY = {"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn", "model": "m", "usage": None}


class APITimeoutError(Exception):
    pass


def test_a_stopped_vision_call_is_not_tried_again(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_sleep", lambda s: None)
    driver = FakeDriver()
    resolver = AppResolver(driver, {}, label_cache=tmp_path / "l.json")
    agent = Agent(ScriptedClient([]), driver, resolver, Config(settle_delay=0), RecordingIO(), use_ocr=False)
    cancel = threading.Event()
    agent._gate_state = SimpleNamespace(cancel=cancel)

    release, finished, calls = threading.Event(), threading.Event(), []

    def create(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            release.wait(5)
            raise APITimeoutError("timed out")
        return REPLY

    adapter = AnthropicAdapter(SimpleNamespace(messages=SimpleNamespace(create=create)))
    adapter.policy = CallPolicy(20, 60, 1, 5)
    complete = adapter.complete

    def tracked(request):
        try:
            return complete(request)
        finally:
            finished.set()

    adapter.complete = tracked
    route = SimpleNamespace(adapter=adapter, spec=SimpleNamespace(max_tokens=512, options={}, provider="anthropic"))
    threading.Timer(0.1, cancel.set).start()
    with pytest.raises(TaskStopped):
        agent._vision_call(route, "s", [{"role": "user", "content": "hi"}])
    release.set()
    assert finished.wait(5)
    assert len(calls) == 1  # no retry after the Stop


def test_a_stop_during_the_retry_wait_sends_no_retry(monkeypatch):
    """Review N4: the abort was checked before the back-off, so a Stop during the wait still sent one paid retry."""
    abort, calls = threading.Event(), []
    monkeypatch.setattr(models, "_sleep", lambda s: abort.set())  # the Stop lands during the wait

    def fn(**kwargs):
        calls.append(kwargs)
        raise APITimeoutError("timed out")

    with pytest.raises(Exception):
        models._call("anthropic", fn, policy=CallPolicy(20, 60, 1, 5), timeout_s=20, abort=abort)
    assert len(calls) == 1
