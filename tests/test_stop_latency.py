"""Stop takes effect at once (2026-10-17: the owner's Stop on the dashboard took 9 s, while a 17 s model call ran).

Each test starts a task that is busy somewhere slow (a model call, the phone's wait_for, an owner prompt, a pending
phone prompt, a system dialog), presses Stop, and measures how long until the task reports stopped. The target is
about 0.5 s; these allow STOP_BUDGET_S. None of them may start a phone act after the Stop.

The phone is a real PhoneLink over a fake socket (an asyncio loop in a thread), so the server's own call path is what
gets cut short."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from types import SimpleNamespace

import pytest
from conftest import FakeDriver, RecordingIO, ScriptedClient, tool_use

from openmob.agent.loop import Agent
from openmob.config import Config
from openmob.phone.apps import AppResolver
from openmob.phone.base import TaskStopped
from openmob.phone.adb import UIElement
from openmob.phone.protocol import encode_element, encode_screenshot
from openmob.phone.remote import PhoneLink, RemoteDriver
from openmob.runner import Coordinator
from openmob.voice.tts import Speaker

STOP_BUDGET_S = 0.5
SLOW_S = 5.0
ACTS = {"tap", "long_press", "swipe", "type_text", "key", "launch_app", "open_url", "open_settings"}


# --- fakes ----------------------------------------------------------------------------------------------------------

class SlowClient(ScriptedClient):
    """A model whose every reply takes `delay` seconds (non-streaming). `started` is set when a call is in flight."""

    def __init__(self, responses, delay=SLOW_S):
        super().__init__(responses)
        self.delay = delay
        self.started = threading.Event()
        self.finished = threading.Event()

    def create(self, **kwargs):
        self.started.set()
        if kwargs.get("stream"):
            return self._stream(kwargs)
        time.sleep(self.delay)
        try:
            return super().create(**kwargs)
        finally:
            self.finished.set()

    def _stream(self, kwargs):
        """An Anthropic-shaped event stream: thinking deltas every 50 ms for `delay`, then the tool call."""
        response = super().create(**{k: v for k, v in kwargs.items() if k != "stream"})
        client = self

        class Stream:
            closed = False

            def __iter__(self):
                yield {"type": "message_start", "message": {"model": "claude-sonnet-5-5", "usage": {}}}
                yield {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": ""}}
                end = time.monotonic() + client.delay
                while time.monotonic() < end:
                    if self.closed:
                        raise RuntimeError("stream closed")
                    time.sleep(0.05)
                    yield {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "."}}
                yield {"type": "content_block_stop", "index": 0}
                for n, block in enumerate(response.content, 1):
                    yield {"type": "content_block_start", "index": n,
                           "content_block": {"type": "tool_use", "id": block.id, "name": block.name, "input": {}}}
                    yield {"type": "content_block_delta", "index": n,
                           "delta": {"type": "input_json_delta", "partial_json": json.dumps(block.input)}}
                    yield {"type": "content_block_stop", "index": n}
                yield {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 5}}
                client.finished.set()

            def close(self):
                self.closed = True
                client.stream_closed = True

        client.stream_closed = False
        return Stream()


class FakeSocket:
    """The phone's end of a PhoneLink: answers calls from a FakeDriver. `slow` maps a method to seconds before its
    reply (None: never); `replies` maps a method to a canned reply dict ({"ok": False, "code": …})."""

    def __init__(self, phone: FakeDriver, slow=None, replies=None):
        self.phone = phone
        self.slow = dict(slow or {})
        self.replies = dict(replies or {})
        self.link: PhoneLink | None = None
        self.calls: list[tuple[float, str, dict]] = []
        self.call_started: dict[str, threading.Event] = {}

    def started(self, method: str) -> threading.Event:
        return self.call_started.setdefault(method, threading.Event())

    async def send_json(self, message: dict) -> None:
        if message.get("type") != "call":
            return
        method, params = message["method"], message.get("params") or {}
        self.calls.append((time.monotonic(), method, params))
        self.started(method).set()
        delay = self.slow.get(method, 0)
        if delay is None:
            return
        loop = asyncio.get_running_loop()
        loop.call_later(delay, self._reply, message["id"], method, params)

    def _reply(self, call_id, method, params):
        canned = self.replies.get(method)
        if canned is not None:
            reply = canned(params) if callable(canned) else canned
            self.link.resolve({"id": call_id, **reply})
            return
        self.link.resolve({"id": call_id, "ok": True, "result": self._result(method, params)})

    def _result(self, method, params):
        p = self.phone
        if method == "screenshot":
            return encode_screenshot(p.screenshot())
        if method == "ui_elements":
            return [encode_element(e) for e in p.ui_elements()]
        if method == "current_app":
            return p.current_app()
        if method == "launchable_packages":
            return p.launchable_packages()
        if method == "app_labels":
            return p.app_labels(params.get("packages") or [])
        if method == "device_state":
            return {"interactive": True, "locked": False, "secure": False}
        if method == "wait_for":
            return {"met": False, "waited_ms": int(params.get("timeout_ms", 0)), "seen": "", "package": p.package}
        if method == "wait_idle":
            return {"waited_ms": 0, "idle": True}
        if method == "gate_cancel":
            return {"cancelled": True}
        if method == "tap":
            p.tap(params["x"], params["y"])
        elif method == "key":
            p.key(params["name"])
        elif method == "wake_unlock":
            p.wake_unlock()
        return None

    def acts(self, after: float = 0.0) -> list[str]:
        return [m for t, m, _ in self.calls if m in ACTS and t >= after]


@pytest.fixture
def phone_loop():
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    yield loop
    loop.call_soon_threadsafe(loop.stop)
    thread.join(2)


def remote_phone(loop, caps=(), **socket_kw):
    labels = [UIElement(i, text, "", "", "TextView", True, None, (0, 200 * i, 1080, 200 * i + 150))
              for i, text in enumerate(["Loading your game", "Please wait", "Next"])]
    sock = FakeSocket(FakeDriver(packages=["com.android.settings"], elements=labels), **socket_kw)
    link = PhoneLink(sock, loop)
    sock.link = link
    driver = RemoteDriver(link)
    driver.capabilities = set(caps)
    return driver, sock


def make_agent(client, driver, io, tmp_path, **cfg):
    config = Config(settle_delay=0, launch_settle_delay=0, **cfg)
    resolver = AppResolver(driver, {}, label_cache=tmp_path / "l.json")
    return Agent(client, driver, resolver, config, io, use_ocr=False)


def run_in_thread(fn, *args, **kwargs):
    box = {}

    def target():
        try:
            box["result"] = fn(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 (the test reports it)
            box["error"] = exc
        box["at"] = time.monotonic()

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread, box


def stop_and_time(cancel_fn, thread, box, budget=STOP_BUDGET_S):
    pressed = time.monotonic()
    cancel_fn()
    thread.join(SLOW_S + 30)
    assert "error" not in box, box.get("error")
    took = box["at"] - pressed
    print(f"stop took {took * 1000:.0f} ms")
    assert took < budget, f"the task took {took:.2f} s to stop"
    return pressed, took


# --- the model ------------------------------------------------------------------------------------------------------

def test_stop_during_a_slow_model_call(tmp_path, phone_loop):
    driver, sock = remote_phone(phone_loop)
    client = SlowClient([[tool_use("tap", "a", x=10, y=10, target="Next")]])
    agent = make_agent(client, driver, RecordingIO(), tmp_path)
    cancel = threading.Event()
    thread, box = run_in_thread(agent.run, "go next", cancel)
    assert client.started.wait(5)
    pressed, _ = stop_and_time(cancel.set, thread, box)
    assert box["result"].summary == "Stopped." and not box["result"].success
    time.sleep(0.2)
    assert sock.acts(after=pressed) == []
    assert not client.finished.is_set()  # it really was cut short, not just fast


def test_stop_during_a_streamed_model_call_closes_the_stream(tmp_path, phone_loop):
    driver, sock = remote_phone(phone_loop)
    client = SlowClient([[tool_use("tap", "a", x=10, y=10, target="Next")]])
    agent = make_agent(client, driver, RecordingIO(), tmp_path, vision_stream=True)
    cancel = threading.Event()
    thread, box = run_in_thread(agent.run, "go next", cancel)
    assert client.started.wait(5)
    time.sleep(0.2)
    pressed, _ = stop_and_time(cancel.set, thread, box)
    assert box["result"].summary == "Stopped."
    deadline = time.monotonic() + 2
    while not getattr(client, "stream_closed", False) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert client.stream_closed  # the HTTP stream is closed, so the model stops generating
    assert sock.acts(after=pressed) == []


def test_a_reply_that_arrives_after_stop_never_acts(tmp_path, phone_loop):
    """The model answers a moment after Stop with a tap: nothing reaches the phone."""
    driver, sock = remote_phone(phone_loop)
    client = SlowClient([[tool_use("tap", "a", x=10, y=10, target="Next")]], delay=0.3)
    agent = make_agent(client, driver, RecordingIO(), tmp_path)
    cancel = threading.Event()
    thread, box = run_in_thread(agent.run, "go next", cancel)
    assert client.started.wait(5)
    pressed, _ = stop_and_time(cancel.set, thread, box)
    time.sleep(0.6)  # the abandoned call returns its tap now
    assert sock.acts(after=pressed) == []


# --- the phone ------------------------------------------------------------------------------------------------------

def test_stop_during_the_phones_wait_for(tmp_path, phone_loop):
    driver, sock = remote_phone(phone_loop, caps={"wait_for", "wait_idle"}, slow={"wait_for": SLOW_S})
    client = ScriptedClient([[tool_use("wait_until", "a", until="text_appears", target="Done", timeout_s=30)],
                             [tool_use("tap", "b", x=10, y=10, target="Next")]])
    agent = make_agent(client, driver, RecordingIO(), tmp_path)
    cancel = threading.Event()
    thread, box = run_in_thread(agent.run, "wait for it", cancel)
    assert sock.started("wait_for").wait(5)
    pressed, _ = stop_and_time(cancel.set, thread, box)
    assert box["result"].summary == "Stopped."
    assert sock.acts(after=pressed) == []
    assert len(client.requests) == 1  # no model call after the stop either


def test_an_act_after_stop_never_reaches_the_phone(phone_loop):
    driver, sock = remote_phone(phone_loop)
    cancel = threading.Event()
    driver.abort = (cancel, threading.get_ident())
    cancel.set()
    with pytest.raises(TaskStopped):
        driver.tap(1, 2)
    assert sock.acts() == []


def test_another_threads_reads_are_not_cut_short(phone_loop):
    """The live view reads the phone from its own thread: a stopping task doesn't break it."""
    driver, sock = remote_phone(phone_loop, slow={"current_app": 0.2})
    cancel = threading.Event()
    driver.abort = (cancel, -1)  # the agent's thread is some other one
    cancel.set()
    assert driver.current_app() == "com.android.launcher3"


# --- prompts --------------------------------------------------------------------------------------------------------

def coordinator_with(agent_factory):
    c = Coordinator(Speaker(enabled=False))
    c.agent = agent_factory(c)
    c.start()
    return c


def wait_final(c, task_id, timeout=SLOW_S + 30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        info = c.task(task_id)
        if info and info["finished"]:
            return info
        time.sleep(0.005)
    raise AssertionError("the task never finished")


def test_stop_while_the_agent_asks_the_owner(tmp_path, phone_loop):
    driver, sock = remote_phone(phone_loop)
    client = ScriptedClient([[tool_use("ask_user", "a", question="Which one?")]])
    c = coordinator_with(lambda io: make_agent(client, driver, io, tmp_path))
    task = c.enqueue("pick one", "dashboard")
    deadline = time.monotonic() + 5
    while c.question is None and time.monotonic() < deadline:
        time.sleep(0.005)
    pressed = time.monotonic()
    c.stop()
    info = wait_final(c, task)
    took = info["finished"] - (time.time() - (time.monotonic() - pressed))
    print(f"stop took {took * 1000:.0f} ms")
    assert info["status"] == "cancelled" and took < STOP_BUDGET_S


def test_stop_while_a_phone_prompt_waits_withdraws_it(tmp_path, phone_loop):
    needs = {"ok": False, "code": "gate_needs_approval", "error": "Approve on the phone",
             "approval_id": "gk1", "gate": {"rule": "r", "question": "Allow tapping Buy?", "kind": "action"}}
    driver, sock = remote_phone(phone_loop, caps={"gatekeeper", "gate_cancel"}, replies={"tap": needs},
                                slow={"gate_cancel": 0.3})  # a phone a few hundred ms away
    client = ScriptedClient([[tool_use("tap", "a", x=10, y=10, target="Buy")]])
    c = coordinator_with(lambda io: make_agent(client, driver, io, tmp_path))
    task = c.enqueue("buy it", "dashboard")
    deadline = time.monotonic() + 5
    while c.question is None and time.monotonic() < deadline:
        time.sleep(0.005)
    assert c.question is not None
    wall = time.time()
    c.stop()
    info = wait_final(c, task)
    took = info["finished"] - wall
    print(f"stop took {took * 1000:.0f} ms")
    assert info["status"] == "cancelled" and took < STOP_BUDGET_S
    deadline = time.monotonic() + 2
    while not any(m == "gate_cancel" for _, m, _ in sock.calls) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert [p for _, m, p in sock.calls if m == "gate_cancel"] == [{"approval_id": "gk1"}]  # withdrawn
    assert sock.acts().count("tap") == 1  # the refused one; never re-sent


def test_stop_while_a_system_dialog_waits(tmp_path, phone_loop):
    driver, sock = remote_phone(phone_loop)
    driver.owner_dialog = "Kalshi is asking for location: choose on your phone."
    client = ScriptedClient([])
    agent = make_agent(client, driver, RecordingIO(), tmp_path, owner_dialog_wait_seconds=60)
    cancel = threading.Event()
    thread, box = run_in_thread(agent.run, "anything", cancel)
    time.sleep(0.3)
    stop_and_time(cancel.set, thread, box)
    assert client.requests == []


def test_stop_while_the_phone_is_locked(tmp_path, phone_loop):
    driver, sock = remote_phone(phone_loop, caps={"device_lock"})
    driver.on_device_lock({"locked": True, "secure": True})
    agent = make_agent(ScriptedClient([]), driver, RecordingIO(), tmp_path, locked_wait_seconds=60)
    cancel = threading.Event()
    thread, box = run_in_thread(agent.run, "anything", cancel)
    time.sleep(0.3)
    stop_and_time(cancel.set, thread, box)


# --- the dashboard's status ----------------------------------------------------------------------------------------

def test_the_status_says_stopping_at_once(tmp_path, phone_loop):
    driver, sock = remote_phone(phone_loop)
    client = SlowClient([[tool_use("done", "a", summary="ok", success=True)]])
    c = coordinator_with(lambda io: make_agent(client, driver, io, tmp_path))
    task = c.enqueue("anything", "dashboard")
    assert client.started.wait(5)
    assert c.snapshot()["stopping"] is False
    c.stop()
    snap = c.snapshot()
    assert snap["stopping"] is True or snap["task_id"] is None
    wait_final(c, task)
    assert c.snapshot()["stopping"] is False
