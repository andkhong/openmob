"""The answer check, scoped for launch (perf/launch-latency, 2026-10-21). The 2026-10-21 latency review probed the
check on realistic summaries and found false positives that each cost one more vision call plus a done (about
1.5-3 s): "started, paused and reset to zero" (an action list), "I've", the phone's own name. So:

- it runs only on requests that ask to read, list or report something, never on action requests;
- contractions, the phone's brand and model words, and word forms ("paused" for "Pause") don't count as unseen;
- the owner's saved preferences count as seen (memory's notes are not "from the model's own knowledge");
- what it flags stays internal: events and history carry the count only, never the strings (memory's rule: note
  text never appears in events or history).
"""

import json
import time

from conftest import FakeDriver, RecordingIO, ScriptedClient, tool_use

from openmob import permissions as perm
from openmob.agent import answer_check
from openmob.agent.loop import Agent, AgentResult
from openmob.agent.tools import system_prompt
from openmob.config import Config
from openmob.memory import Memory
from openmob.phone.adb import UIElement
from openmob.phone.apps import AppResolver

APPS = ["Calculator", "Calendar", "Camera", "Chrome", "Clock"]
PADDED = "The first apps are Calculator, Calendar, Camera, Chrome and OpenMob."


def el(i, text, cls="android.widget.TextView"):
    return UIElement(i, text, "", "", cls, True, None, (0, 100 * i, 1000, 100 * i + 80))


def seen(*labels):
    s = answer_check.Seen()
    for label in labels:
        s.add(label)
    return s


# --- which requests it runs on ------------------------------------------------------------------------------------


def test_read_list_and_report_requests_are_checked():
    for request in ["read me the names of the first 30 apps", "List my alarms", "What's my battery level?",
                    "Open Settings and tell me the Android version", "how many unread emails do I have",
                    "Can you find out which apps use the most battery", "Check whether Bluetooth is on",
                    "Open Chrome's notification settings and let me know if notifications are allowed",
                    "Who texted me last?", "Is wifi on", "Summarize my latest email",
                    "Turn on Wi-Fi and tell me the network name",
                    "Start the stopwatch\nUser correction: and tell me what it reads"]:
        assert answer_check.asks_to_read(request), request


def test_action_requests_are_not_checked():
    for request in ["Start the stopwatch, pause it and reset it", "Open Settings and go to Display",
                    "Text Sam: tell me what you think", "Send Maya a message saying what time is it there",
                    "Turn on Do Not Disturb until 8am", "Set a timer for 5 minutes", "Open YouTube",
                    "Search YouTube for what is a black hole", "When it loads, tap Start",
                    "Reply to Alex: is it on?", "Play some music", "Take a photo"]:
        assert not answer_check.asks_to_read(request), request


# --- false positives the review found ----------------------------------------------------------------------------


def test_an_action_list_with_word_forms_is_not_flagged():
    labels = seen("Clock", "Alarm", "Timer", "Stopwatch", "Start", "Pause", "Lap", "Reset", "00:00.00")
    assert answer_check.unseen("The stopwatch was started, paused and reset to zero.", labels) == []


def test_contractions_are_not_names():
    labels = seen("Settings", "Display", "Dark theme")
    for summary in ["OK, I've set the dark theme.", "I'm on the Display page.", "It's on, and I'll leave it.",
                    "Display settings: you're there, let's go.", "Here's Display."]:
        assert answer_check.unseen(summary, labels) == [], summary


def test_the_phones_own_name_is_not_flagged():
    labels = seen("Settings", "About phone", "Android version", "16")
    for summary in ["Your Samsung runs Android 16.", "This Galaxy is on Android version 16.",
                    "Your Pixel runs Android 16.", "The phone's Android version is 16."]:
        assert answer_check.unseen(summary, labels) == [], summary


def test_padding_is_still_caught():
    assert answer_check.unseen(PADDED, seen(*APPS)) == ["OpenMob"]


# --- in the loop -------------------------------------------------------------------------------------------------


def make(responses, tmp_path, elements=None, memory=False, **cfg):
    tmp_path.mkdir(parents=True, exist_ok=True)
    config = Config(settle_delay=0, launch_settle_delay=0, memory=memory, **cfg)
    driver = FakeDriver(elements=[el(i, t) for i, t in enumerate(APPS)] if elements is None else elements)
    driver.package = "com.android.launcher3"
    io = RecordingIO()
    client = ScriptedClient(responses)
    agent = Agent(client, driver, AppResolver(driver, label_cache=tmp_path / "l.json"), config, io, use_ocr=False)
    if memory:
        agent.memory = Memory(tmp_path / "memory.sqlite")
    return agent, client, io


def test_an_action_request_never_gets_the_note(tmp_path):
    agent, client, io = make([[tool_use("done", "d1", summary="Opened Calculator for Priya and OpenMob.",
                                        success=True)]], tmp_path)
    result = agent.run("open the calculator")
    assert result.success and result.unverified == 0 and len(client.requests) == 1
    assert not any("Answer check" in m for _, m in io.events)


def test_a_read_request_still_gets_the_note(tmp_path):
    agent, client, _ = make([[tool_use("done", "d1", summary=PADDED, success=True)],
                             [tool_use("done", "d2", summary=PADDED, success=True)]], tmp_path)
    result = agent.run("read me the names of the first apps")
    assert result.success and result.unverified == 1 and len(client.requests) == 2


def test_unverified_strings_never_reach_events(tmp_path):
    agent, client, io = make([[tool_use("done", "d1", summary=PADDED, success=True)],
                              [tool_use("done", "d2", summary=PADDED, success=True)]], tmp_path)
    agent.run("read me the names of the first apps")
    statuses = [m for k, m in io.events if k == "status" and "Answer check" in m]
    assert statuses and not any("OpenMob" in m for m in statuses)


def test_the_outcome_event_carries_only_the_count(tmp_path):
    from openmob.runner import Coordinator
    from openmob.voice.tts import Speaker

    class Answering:
        def run(self, text, cancel, go_home=False, **options):
            return AgentResult(True, "Calculator and Maya Lee.", 2, unverified=2)

    c = Coordinator(Speaker(enabled=False))
    c.agent = Answering()
    c.start()
    c.submit("read me my apps", "dashboard")
    deadline = time.time() + 5
    while time.time() < deadline and not any((e.get("data") or {}).get("final") for e in c.log):
        time.sleep(0.01)
    final = next(e for e in c.log if (e.get("data") or {}).get("final"))
    assert final["data"]["unverified"] == 2


# --- memory: saved preferences count as seen ---------------------------------------------------------------------


def test_the_prompt_allows_saved_preferences_but_not_the_models_own_knowledge():
    prompt = system_prompt("android", 1)
    assert "never from memory" not in prompt
    assert "saved preferences" in prompt and "never from your own knowledge" in prompt


def test_a_person_note_counts_as_seen(tmp_path):
    agent, client, io = make([[tool_use("done", "d1", summary="Your sis is Maya Lee.", success=True)]], tmp_path,
                             memory=True)
    agent.memory.add(None, "prefers texts after 6pm", "person", relation="sis", contact_name="Maya Lee",
                     status="active")
    perms = perm.TaskPermissions("auto", lambda: perm.normalize(perm.default_settings()))
    result = agent.run("who is my sis?", permissions=perms, memory_allowed=True)
    assert result.success and result.unverified == 0 and len(client.requests) == 1
    assert not any("Answer check" in m for _, m in io.events)


def test_an_about_you_note_counts_as_seen(tmp_path):
    agent, client, _ = make([[tool_use("done", "d1", summary="Your usual coffee order is an Oat Flat White.",
                                       success=True)]], tmp_path, memory=True)
    agent.memory.add(None, "My usual coffee order is an Oat Flat White", "about_you", status="active")
    perms = perm.TaskPermissions("auto", lambda: perm.normalize(perm.default_settings()))
    result = agent.run("what's my usual coffee order?", permissions=perms, memory_allowed=True)
    assert result.success and result.unverified == 0 and len(client.requests) == 1


def test_a_recall_result_counts_as_seen(tmp_path):
    agent, client, _ = make([[tool_use("recall", "r1", query="Priya Raman")],
                             [tool_use("done", "d1", summary="Her name is Priya Raman.", success=True)]],
                            tmp_path, memory=True)
    agent.memory.add(None, "work only", "person", relation="boss", contact_name="Priya Raman", status="active")
    perms = perm.TaskPermissions("auto", lambda: perm.normalize(perm.default_settings()))
    result = agent.run("tell me Priya's last name", permissions=perms, memory_allowed=True)
    assert result.success and result.unverified == 0 and len(client.requests) == 2
    assert not any("Answer check" in m for _, m in agent.io.events)
