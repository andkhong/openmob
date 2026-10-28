"""Three agent-interaction bugs seen on the owner's Samsung (2026-10-20, main a401bd6, local server).

A) "Install the Calculator app by Google": the agent tapped Install on a Play Store RESULTS list. Neither the server
   nor the phone can tell which app that button installs (several Install buttons: store_title is ""), so the phone
   asked about "an app" the request doesn't name, even after the task was approved. The tap is now not sent; the
   agent is told to open the app's own page first.
B) The task prompt was approved, the act re-sent, and the phone asked again (the unnamed install): that second
   gate_needs_approval reached the agent as "Don't retry this; pick another approach", so it pressed BACK and searched
   again, asking the owner a second time. The driver now waits for a chained prompt too, and an open prompt that does
   reach the agent says to wait for the owner.
C) gate_rate_limited ("try again in 2 min"): the agent called wait(30 s), claimed the cooldown had passed and
   retried. The phone's time (gate.retry_after_ms, or its words) is now enforced by the loop.
"""

import threading
import time

import pytest

from conftest import FakeDriver, RecordingIO, ScriptedClient, tool_use

from openmob.agent import gate
from openmob.agent.loop import INSTALL_FROM_RESULTS, Agent, Observation, _TaskState
from openmob.config import Config
from openmob.permissions import TaskPermissions
from openmob.phone.adb import UIElement as U
from openmob.phone.base import GateRefused, retry_after_from
from openmob.phone.remote import RemoteDriver

from test_gatekeeper_server import _Link

TEXT = "android.widget.TextView"
BUTTON = "android.widget.Button"
RESULTS = [U(0, "calculator", "", "com.android.vending:id/search_bar", "android.widget.EditText", True, None, (40, 120, 1040, 220)),
           U(1, "Calculator", "", "", TEXT, False, None, (200, 300, 800, 360)),
           U(2, "Google LLC", "", "", TEXT, False, None, (200, 370, 800, 420)),
           U(3, "Install", "", "", BUTTON, True, None, (820, 300, 1040, 400)),
           U(4, "Calculator Plus", "", "", TEXT, False, None, (200, 500, 800, 560)),
           U(5, "Digitalchemy", "", "", TEXT, False, None, (200, 570, 800, 620)),
           U(6, "Install", "", "", BUTTON, True, None, (820, 500, 1040, 600))]
DETAILS = [U(0, "Calculator", "", "", TEXT, False, None, (40, 300, 900, 380)),
           U(1, "Google LLC", "", "", TEXT, False, None, (40, 390, 600, 440)),
           U(2, "Install", "", "com.android.vending:id/install", BUTTON, True, None, (40, 700, 1040, 800))]


def run_tap(elements, index, task="Install the Calculator app by Google from the Play Store", answers=("yes",)):
    driver = FakeDriver(elements=elements)
    driver.package = "com.android.vending"
    io = RecordingIO(answers=list(answers))
    client = ScriptedClient([[tool_use("tap_element", "a", index=index)],
                             [tool_use("done", "z", summary="ok", success=True)]])
    agent = Agent(client, driver, None, Config(settle_delay=0, launch_settle_delay=0), io, use_ocr=False)
    agent.run(task, permissions=TaskPermissions("auto"), isolated=True)
    results = [b for r in client.requests for m in r["messages"] if m["role"] == "user" and isinstance(m["content"], list)
               for b in m["content"] if isinstance(b, dict) and b.get("type") == "tool_result"]
    return driver, io, results


# --- A: install from the app's own page ---------------------------------------------------------------------------

def test_install_on_a_results_list_is_not_tapped_and_the_agent_is_sent_to_the_apps_page():
    assert gate.install_buttons(RESULTS) == 2 and gate.store_title(RESULTS, RESULTS[3]) == ""
    driver, io, results = run_tap(RESULTS, 3)
    assert not [a for a in driver.actions if a[0] == "tap"]  # nothing tapped
    assert not io.questions  # and nobody asked about "an app"
    text = results[0]["content"][0]["text"]
    assert text == INSTALL_FROM_RESULTS and "tap the app's name" in text


def test_install_on_the_apps_own_page_still_runs_when_the_request_names_it():
    assert gate.store_title(DETAILS, DETAILS[2]) == "Calculator"
    driver, io, _ = run_tap(DETAILS, 2)
    assert ("tap", 540, 750) in driver.actions and not io.questions


def test_a_results_row_itself_can_be_tapped():
    driver, _, _ = run_tap(RESULTS, 1)  # the app's name: opens its page
    assert ("tap", 500, 330) in driver.actions


# --- B: a pending approval is waited for, never routed around ------------------------------------------------------

def test_a_second_prompt_after_the_task_approval_is_waited_for_too():
    """Task prompt approved, the re-send asks again (an unnamed install): the driver waits for that answer as well
    and the act runs; nothing reaches the agent."""
    task = GateRefused("gate_needs_approval", "Waiting for the owner's approval of this task on the phone.",
                       approval_id="gk1", kind="task")
    step = GateRefused("gate_needs_approval", "Waiting for the owner's approval on the phone.", approval_id="gk2",
                       kind="install")
    driver = RemoteDriver(_Link([task, step, None]))
    driver.capabilities = {"gatekeeper"}
    asked = []
    driver.gate_approver = lambda refusal: asked.append(refusal.approval_id) or "yes"
    driver.tap(1, 2)
    assert asked == ["gk1", "gk2"] and len(driver.link.calls) == 3


def test_a_prompt_open_right_after_a_yes_is_waited_out():
    """The 1 s cool-down after a prompt closes (gate_prompt_open) on the re-send: tried again, not reported."""
    driver = RemoteDriver(_Link([GateRefused("gate_needs_approval", "w", approval_id="gk1"),
                                 GateRefused("gate_prompt_open", "cooldown", rule="builtin:prompt_cooldown"), None]))
    driver.capabilities = {"gatekeeper"}
    driver.gate_approver = lambda refusal: "yes"
    driver.prompt_waiter = lambda exc, waited: waited < 1
    driver.tap(1, 2)
    assert len(driver.link.calls) == 3


def test_chained_prompts_are_bounded():
    from openmob.phone.remote import MAX_CHAINED_APPROVALS

    replies = [GateRefused("gate_needs_approval", "w", approval_id=f"gk{i}") for i in range(MAX_CHAINED_APPROVALS + 2)]
    driver = RemoteDriver(_Link(replies))
    driver.capabilities = {"gatekeeper"}
    driver.gate_approver = lambda refusal: "yes"
    with pytest.raises(GateRefused) as info:
        driver.tap(1, 2)
    assert info.value.code == "gate_needs_approval" and len(driver.link.calls) == MAX_CHAINED_APPROVALS + 1


def test_the_same_prompt_again_after_a_yes_is_reported_not_looped():
    driver = RemoteDriver(_Link([GateRefused("gate_needs_approval", "w", approval_id="gk1"),
                                 GateRefused("gate_needs_approval", "w", approval_id="gk1")]))
    driver.capabilities = {"gatekeeper"}
    driver.gate_approver = lambda refusal: "yes"
    with pytest.raises(GateRefused):
        driver.tap(1, 2)
    assert len(driver.link.calls) == 2


class _Refusing(FakeDriver):
    def __init__(self, *refusals):
        super().__init__(elements=DETAILS)
        self.refusals = list(refusals)

    def tap(self, x, y):
        if self.refusals:
            raise self.refusals.pop(0)
        super().tap(x, y)


def _execute(driver, cfg=None, cancel=None):
    agent = Agent(ScriptedClient([]), driver, None, cfg or Config(settle_delay=0), RecordingIO(), use_ocr=False)
    state = _TaskState(task="tap ok", cancel=cancel or threading.Event())
    obs = Observation(None, DETAILS, "com.example.app")
    return agent, agent._execute("tap_element", {"index": 0, "target": "Calculator"}, obs, state)


@pytest.mark.parametrize("code", ["gate_needs_approval", "gate_prompt_open"])
def test_an_open_prompt_that_reaches_the_agent_says_wait_not_another_way(code):
    _, out = _execute(_Refusing(GateRefused(code, "Waiting for the owner to answer a prompt on the phone.")))
    assert out.is_error and not out.done
    assert "Don't press BACK or try another way" in out.text and "Call wait" in out.text
    assert "pick another approach" not in out.text


# --- C: the phone's rate limit is enforced by the loop -------------------------------------------------------------

def test_the_retry_time_comes_from_the_phone_or_its_words():
    reply = {"ok": False, "code": "gate_rate_limited", "error": "Too many approval prompts on the phone: try again in "
             "2 min.", "gate": {"rule": "builtin:prompt_rate", "retry_after_ms": 93_000}}
    assert GateRefused.from_reply(reply).retry_after_ms == 93_000
    del reply["gate"]["retry_after_ms"]  # an older app: its words, rounded up to the minute
    assert GateRefused.from_reply(reply).retry_after_ms == 120_000
    assert retry_after_from("Too many actions: wait a second.") == 1_000
    assert retry_after_from("Paused on the phone after repeated denials. The owner can resume.") is None
    assert GateRefused("gate_denied", "try again in 2 min").retry_after_ms is None  # only for the rate limit


def test_a_short_rate_limit_is_waited_out_by_the_loop():
    refusal = GateRefused("gate_rate_limited", "Too many actions: wait a second.", retry_after_ms=300)
    started = time.monotonic()
    agent, out = _execute(_Refusing(refusal))
    assert time.monotonic() - started >= 0.3  # the loop waited the phone's time, not the model
    assert out.is_error and not out.done and "have now passed (OpenMob waited them)" in out.text
    assert out.timings["wait_ms"] >= 300


def test_a_long_or_open_ended_rate_limit_ends_the_task():
    long = GateRefused("gate_rate_limited", "Too many approval prompts on the phone: try again in 9 min.",
                       retry_after_ms=540_000)
    started = time.monotonic()
    _, out = _execute(_Refusing(long), Config(settle_delay=0, gate_rate_wait_seconds=150))
    assert time.monotonic() - started < 1 and out.done and not out.success
    assert "about 9 min" in out.text and "Ask again later" in out.text
    paused = GateRefused("gate_rate_limited", "Paused on the phone after repeated denials. The owner can resume.")
    _, out = _execute(_Refusing(paused))
    assert out.done and not out.success


def test_a_stop_during_the_rate_limit_wait_stops_the_task():
    from openmob.phone.base import TaskStopped

    cancel = threading.Event()
    threading.Timer(0.1, cancel.set).start()
    started = time.monotonic()
    with pytest.raises(TaskStopped):
        _execute(_Refusing(GateRefused("gate_rate_limited", "x", retry_after_ms=60_000)), cancel=cancel)
    assert time.monotonic() - started < 2


def test_the_model_cannot_wait_less_than_the_phone_asked():
    """End to end: the model's own wait(30) never replaces the phone's time; the loop waits it before the model
    decides again, and the act then runs."""
    driver = _Refusing(GateRefused("gate_rate_limited", "Too many actions: wait a second.", retry_after_ms=400))
    driver.package = "com.example.app"
    client = ScriptedClient([[tool_use("tap_element", "a", index=2)], [tool_use("tap_element", "b", index=2)],
                             [tool_use("done", "z", summary="ok", success=True)]])
    agent = Agent(client, driver, None, Config(settle_delay=0), RecordingIO(), use_ocr=False)
    started = time.monotonic()
    agent.run("tap install on calculator", permissions=TaskPermissions("auto"), isolated=True)
    assert time.monotonic() - started >= 0.4
    assert any(a[0] == "tap" for a in driver.actions)
