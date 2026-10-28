"""Security review 3 (2026-10-18), the Stop races (reviewer F's PoCs, turned into regression tests).

F3-L3: a Stop that lands after the owner's yes on the phone (or while another prompt was open) must not let the
approved act be re-sent. F3-L4: a Stop or cancel_task between the worker dequeuing a task and the task becoming
current must cancel it (no run, ends cancelled). F3-I1: a stopped model stream's helper thread ends even after the
next task clears the shared cancel."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from openmob.agent.loop import Agent, stoppable_events
from openmob.phone.base import GateRefused, TaskStopped
from openmob.phone.remote import RemoteDriver
from openmob.runner import Coordinator
from openmob.voice.tts import Speaker


# --- F3-L3: a Stop after the owner's yes ---------------------------------------------------------------------------

class GateLink:
    """The phone: the first act is refused with `first_code`, any later one goes through. Records what was sent."""

    closed = False

    def __init__(self, first_code):
        self.sent, self.first = [], first_code

    def call(self, method, params):
        self.sent.append(method)
        if len(self.sent) == 1:
            raise GateRefused(self.first, "needs", approval_id="a1")
        return {}

    def call_until(self, method, params, abort):
        return self.call(method, params)


def _gate_driver(code):
    link = GateLink(code)
    driver = RemoteDriver(link)
    driver.capabilities = {"gatekeeper"}
    cancel = threading.Event()
    driver.abort = (cancel, threading.get_ident())
    return driver, link, cancel


def test_a_stop_after_the_owners_yes_does_not_send_the_act():
    driver, link, cancel = _gate_driver("gate_needs_approval")
    driver.gate_approver = lambda exc: (cancel.set(), "yes")[1]  # the owner's yes came in, then Stop was pressed
    with pytest.raises(TaskStopped):
        driver.tap(540, 1200)
    assert link.sent == ["tap"]


def test_a_stop_while_another_prompt_was_open_does_not_resend_the_act():
    driver, link, cancel = _gate_driver("gate_prompt_open")
    driver.prompt_waiter = lambda exc, waited: (cancel.set(), waited < 1)[1]  # Stop pressed while it waited
    driver.prompt_recheck = lambda: None
    with pytest.raises(TaskStopped):
        driver.tap(540, 1200)
    assert link.sent == ["tap"]


def test_the_owners_yes_still_sends_the_act_once_without_a_stop():
    driver, link, _ = _gate_driver("gate_needs_approval")
    driver.gate_approver = lambda exc: "yes"
    driver.tap(540, 1200)
    assert link.sent == ["tap", "tap"]


def test_gate_approval_reports_a_stop_even_when_the_answer_was_yes():
    agent = Agent.__new__(Agent)
    cancel = threading.Event()
    agent._gate_state = SimpleNamespace(cancel=cancel)

    def ask_owner(state, question, details):
        cancel.set()  # Stop pressed as the yes arrived
        return "yes"

    agent._ask_owner = ask_owner
    refusal = SimpleNamespace(question="Tap Buy?", kind="act", approval_id="a1", package="com.shop")
    assert agent._gate_approval(refusal) == "cancelled"
    cancel.clear()
    agent._ask_owner = lambda state, question, details: "yes"
    assert agent._gate_approval(refusal) == "yes"


# --- F3-L4: a Stop between dequeue and the task becoming current ---------------------------------------------------

class FakeResult:
    success, steps, summary = True, 1, "did it"


class FakeAgent:
    def __init__(self):
        self.ran = []

    def run(self, text, cancel, go_home=False, **kw):
        self.ran.append((text, cancel.is_set()))
        return FakeResult()


def _wait_final(c, task_id, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        info = c.task(task_id)
        if info["status"] in ("succeeded", "failed", "cancelled"):
            return info
        time.sleep(0.01)
    return c.task(task_id)


@pytest.mark.parametrize("which", ["stop", "cancel_task"])
def test_a_stop_after_dequeue_cancels_the_task(which):
    """The window is hit deterministically: the Stop fires from take_corrections(), which the worker calls after it
    dequeued the task and before the task is current."""
    c = Coordinator(Speaker(enabled=False))
    c.agent = FakeAgent()
    c._own_app_in_front = lambda: False
    fired = {}
    take = c.take_corrections

    def hook():
        if not fired and c.current_task is None and c.tasks.empty() and c.agent.ran == []:
            fired["x"] = None  # set before the call (no re-entry), its return value after it
            ret = c.stop() if which == "stop" else c.cancel_task(task_id)
            fired["ret"] = ret
        return take()

    c.take_corrections = hook
    task_id = c.enqueue("buy the thing", "api")
    c.start()
    info = _wait_final(c, task_id)
    end = time.monotonic() + 3
    while "ret" not in fired and time.monotonic() < end:  # the Stop's own call returns after the task's record ends
        time.sleep(0.01)
    assert "ret" in fired
    if which == "cancel_task":
        assert fired["ret"] is True
    assert c.agent.ran == []
    assert info["status"] == "cancelled"
    assert sum(e["message"] == "Cancelled before it started." for e in info["events"]) == 1

    # The worker goes on: the next task runs, and nothing is left in the skip set.
    later = c.enqueue("open settings", "api")
    assert _wait_final(c, later)["status"] == "succeeded"
    assert c.agent.ran == [("open settings", False)]
    assert c._skip == set()


def test_stop_still_cancels_queued_tasks_and_the_running_one():
    c = Coordinator(Speaker(enabled=False))

    class Busy(FakeAgent):
        def run(self, text, cancel, go_home=False, **kw):
            self.ran.append((text, cancel.is_set()))
            cancel.wait(3)
            return SimpleNamespace(success=False, steps=0, summary="Stopped.")

    c.agent = Busy()
    c._own_app_in_front = lambda: False
    first = c.enqueue("first", "api")
    second = c.enqueue("second", "api")
    c.start()
    end = time.monotonic() + 3
    while c.current_task != first and time.monotonic() < end:
        time.sleep(0.01)
    c.stop()
    assert _wait_final(c, first)["status"] == "cancelled"
    assert _wait_final(c, second)["status"] == "cancelled"
    assert [text for text, _ in c.agent.ran] == ["first"]
    assert c._skip == set()


# --- F3-I1: a stopped stream ends after the next task clears the cancel --------------------------------------------

def test_a_stopped_stream_closes_even_after_the_cancel_is_cleared():
    cancel = threading.Event()
    gate = threading.Event()
    closed = threading.Event()

    class Events:
        def __iter__(self):
            yield "first"
            gate.wait(3)  # the model is slow: the helper thread is inside next() when Stop is pressed
            yield "second"
            yield "third"

        def close(self):
            closed.set()

    abort = threading.Event()
    stream = stoppable_events(cancel, Events(), abort=abort)
    assert next(stream) == "first"
    cancel.set()
    with pytest.raises(TaskStopped):
        next(stream)
    assert abort.is_set()  # the adapter's own stop (ModelRequest.abort) stays set
    cancel.clear()  # the next task starts and clears the shared cancel
    gate.set()  # the stopped reply's next item arrives
    assert closed.wait(2), "the stopped stream's helper thread kept it open"
