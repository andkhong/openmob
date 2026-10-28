"""The lost-command race (perf/launch-latency, 2026-10-21). bench/load_server.py lost 1 of 80 tasks: a command sent
within milliseconds of the previous task's result, while that task was still wrapping up (agent.run had returned,
current_task wasn't cleared yet), was taken as a correction to the finished task, then dropped with "send it
again". Now: once agent.run returns, the task is wrapping up, and submit(mode=auto) queues new text as a task.
Leftover corrections from before are still not re-queued (a late "no, the other one" would run out of context)."""

import threading
import time

from openmob.agent.loop import AgentResult
from openmob.runner import Coordinator


def wait_until(check, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if check():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met")


class Speaker:
    """Speaks the result inside the wrap-up window (after agent.run returned, before current_task clears): the hook
    the test uses to send the next command at exactly that moment."""

    def __init__(self):
        self.on_summary = None

    def say(self, text):
        if self.on_summary is not None and text.startswith("Done"):
            hook, self.on_summary = self.on_summary, None
            hook()


class Agent:
    def __init__(self):
        self.ran: list[str] = []

    def run(self, text, cancel, go_home=False):
        self.ran.append(text)
        return AgentResult(True, f"Done: {text}", 1)


def make():
    speaker = Speaker()
    c = Coordinator(speaker)
    c.agent = Agent()
    return c, speaker


def test_a_command_sent_while_the_last_task_wraps_up_is_queued_not_lost():
    c, speaker = make()
    outcomes = []
    speaker.on_summary = lambda: outcomes.append(c.submit("open settings", "phone"))
    c.start()
    first = c.submit("open gmail", "phone")
    assert first == "queued"
    wait_until(lambda: c.agent.ran == ["open gmail", "open settings"])
    assert outcomes == ["queued"]
    assert not any("send it again" in (e.get("message") or "") for e in c.log)


def test_steer_refuses_while_wrapping_up_so_api_callers_queue_instead():
    c, speaker = make()
    steered = []
    speaker.on_summary = lambda: steered.append(c.steer("no, the other one"))
    c.start()
    c.submit("open gmail", "phone")
    wait_until(lambda: steered)
    assert steered == [False]  # nothing left to correct: the task already finished


def test_a_correction_sent_before_the_task_ended_is_not_requeued():
    c = Coordinator(Speaker())

    class Late:
        ran: list[str] = []

        def run(self, text, cancel, go_home=False):
            self.ran.append(text)
            if text == "open gmail":
                assert c.submit("no, the other one", "phone") == "steered"  # mid-task: a correction
            return AgentResult(True, f"Done: {text}", 1)

    c.agent = Late()
    c.start()
    c.submit("open gmail", "phone")
    wait_until(lambda: any("send it again" in (e.get("message") or "") for e in c.log))
    time.sleep(0.05)
    assert Late.ran == ["open gmail"]  # never run as a task of its own


def test_the_flag_clears_before_the_next_task_so_it_can_be_steered():
    c, _ = make()
    started = threading.Event()
    release = threading.Event()

    class Slow:
        ran: list[str] = []

        def run(self, text, cancel, go_home=False):
            self.ran.append(text)
            if text == "second":
                started.set()
                release.wait(3)
            return AgentResult(True, f"Done: {text}", 1)

    c.agent = Slow()
    c.start()
    c.submit("first", "phone")
    wait_until(lambda: c.current_task is None and Slow.ran == ["first"])
    c.submit("second", "phone")
    assert started.wait(3)
    assert c.submit("a bit lower", "phone") == "steered"
    release.set()
