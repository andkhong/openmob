"""The answer check (perf/prelaunch-1-4, 2026-10-20). Measured that day: "read me the names of the first 30 apps"
returned 29 names and then "and OpenMob", out of order (likely padding); the done summary went out unchecked. The
prompt now says answers come only from the screen, in screen order, saying so when fewer were found; and list items
and names in a done summary that no screen showed get the model one note to correct them, then are reported as
unverified. No extra model call unless something doesn't match; never a loop."""

import json

from conftest import FakeDriver, RecordingIO, ScriptedClient, tool_use

from openmob.agent import answer_check
from openmob.agent.loop import Agent
from openmob.agent.tools import TOOL_SPECS, system_prompt
from openmob.config import Config, load_config
from openmob.phone.adb import UIElement
from openmob.phone.apps import AppResolver

APPS = ["Calculator", "Calendar", "Camera", "Chrome", "Clock", "Files by Google", "Gmail", "Maps", "YouTube Music"]


def el(i, text, cls="android.widget.TextView"):
    return UIElement(i, text, "", "", cls, True, None, (0, 100 * i, 1000, 100 * i + 80))


def seen(*labels):
    s = answer_check.Seen()
    for label in labels:
        s.add(label)
    return s


# --- the pure check ---------------------------------------------------------------------------------------------


def test_a_padded_list_item_is_caught():
    summary = "The first apps are: Calculator, Calendar, Camera, Chrome, and OpenMob."
    assert answer_check.unseen(summary, seen(*APPS)) == ["OpenMob"]


def test_a_list_read_off_the_screen_passes():
    assert answer_check.unseen("Calculator, Calendar, Camera and Files by Google.", seen(*APPS)) == []
    assert answer_check.unseen("1. Calculator\n2. Calendar\n3. YouTube Music", seen(*APPS)) == []


def test_numbered_lists_and_names_are_checked():
    assert answer_check.unseen("1. Calculator\n2. Calendar\n3. Netflix", seen(*APPS)) == ["Netflix"]
    assert answer_check.unseen("Opened Calendar and checked Spotify.", seen(*APPS)) == ["Spotify"]


def test_wording_and_status_words_dont_count():
    labels = seen("Wi‑Fi", "Bluetooth", "Airplane mode", "Battery", "87%")
    assert answer_check.unseen("Wi-Fi is on, Bluetooth is off, and airplane mode is off.", labels) == []
    assert answer_check.unseen("Your battery is at 87%.", labels) == []
    assert answer_check.unseen("Done. Bluetooth settings are open.", labels) == []
    assert answer_check.unseen("I found only 4 apps, not 30.", labels) == []


def test_an_unreadable_screen_turns_the_check_off():
    labels = seen(*APPS)
    labels.unreadable = True
    assert answer_check.unseen("Calculator, Calendar, Camera and Netflix.", labels) == []


def test_the_note_names_what_wasnt_seen_and_asks_once():
    note = answer_check.note(["OpenMob"])
    assert '"OpenMob"' in note and "order they appeared" in note and "fewer than asked" in note
    assert "Call done again" in note


# --- in the loop ------------------------------------------------------------------------------------------------


def make(responses, tmp_path, elements=None, **cfg):
    config = Config(settle_delay=0, launch_settle_delay=0, **cfg)
    driver = FakeDriver(elements=[el(i, t) for i, t in enumerate(APPS)] if elements is None else elements)
    driver.package = "com.android.launcher3"
    io = RecordingIO()
    client = ScriptedClient(responses)
    agent = Agent(client, driver, AppResolver(driver, label_cache=tmp_path / "l.json"), config, io, use_ocr=False)
    return agent, client, io


PADDED = "The first apps are Calculator, Calendar, Camera, Chrome and OpenMob."
FIXED = "I found these apps: Calculator, Calendar, Camera and Chrome."


def test_the_model_gets_one_note_and_corrects_the_answer(tmp_path):
    agent, client, io = make([[tool_use("done", "d1", summary=PADDED, success=True)],
                              [tool_use("done", "d2", summary=FIXED, success=True)]], tmp_path)
    result = agent.run("read me the names of the first apps")
    assert result.success and result.summary == FIXED and result.unverified == 0
    assert len(client.requests) == 2
    last = client.requests[1]["messages"][-1]["content"]
    assert last[0]["type"] == "tool_result"  # the done's result first, then the note
    assert '"OpenMob"' in last[-1]["text"] and last[-1]["text"].startswith("Answer check")
    assert any("Answer check" in m for k, m in io.events if k == "status")


def test_a_repeated_answer_ends_the_task_marked_unverified(tmp_path):
    agent, client, io = make([[tool_use("done", "d1", summary=PADDED, success=True)],
                              [tool_use("done", "d2", summary=PADDED, success=True)]], tmp_path)
    result = agent.run("read me the names of the first apps")
    assert result.success and result.summary == PADDED  # never blocked
    assert result.unverified == 1
    assert len(client.requests) == 2  # one note, no loop


def test_a_right_answer_costs_no_extra_call(tmp_path):
    agent, client, _ = make([[tool_use("done", "d1", summary=FIXED, success=True)]], tmp_path)
    result = agent.run("read me the names of the first apps")
    assert result.success and result.unverified == 0 and len(client.requests) == 1


def test_names_from_the_request_and_the_tool_calls_count_as_seen(tmp_path):
    agent, client, _ = make([[tool_use("launch_app", "a", app="Settings")],
                             [tool_use("done", "d1", summary="Opened Settings for Priya.", success=True)]],
                            tmp_path)
    agent.driver.packages = ["com.android.settings"]
    agent.driver.labels = {"com.android.settings": "Settings"}
    result = agent.run("open settings for Priya")
    assert result.success and result.unverified == 0 and len(client.requests) == 2


def test_a_failure_summary_is_not_checked(tmp_path):
    agent, client, _ = make([[tool_use("done", "d1", summary="Couldn't find Netflix or Hulu.", success=False)]],
                            tmp_path)
    result = agent.run("open netflix")
    assert not result.success and len(client.requests) == 1


def test_the_switch_turns_it_off(tmp_path, monkeypatch):
    agent, client, _ = make([[tool_use("done", "d1", summary=PADDED, success=True)]], tmp_path, answer_check=False)
    result = agent.run("read me the names of the first apps")
    assert result.success and result.unverified == 0 and len(client.requests) == 1
    path = tmp_path / "c.yaml"
    path.write_text("answer_check: true\n")
    monkeypatch.setenv("OPENMOB_ANSWER_CHECK", "off")
    assert load_config(path).answer_check is False


def test_a_screen_without_text_skips_the_check(tmp_path):
    agent, client, _ = make([[tool_use("done", "d1", summary=PADDED, success=True)]], tmp_path, elements=[])
    result = agent.run("read me the names of the first apps")
    assert result.success and result.unverified == 0 and len(client.requests) == 1


def test_the_prompt_says_answers_come_from_the_screen_in_order():
    prompt = system_prompt("android", 1)
    assert "only from what" in prompt and "order they appeared on screen" in prompt and "fewer than asked" in prompt
    done = next(t for t in TOOL_SPECS if t["name"] == "done")
    assert "taken only from the screen" in done["description"]


def test_the_outcome_event_carries_only_the_unverified_count(tmp_path):
    import time

    from openmob.agent.loop import AgentResult
    from openmob.runner import Coordinator
    from openmob.voice.tts import Speaker

    class Answering:
        def run(self, text, cancel, go_home=False, **options):
            return AgentResult(True, "Calculator and 4111 1111 1111 1111.", 2, unverified=2)

    c = Coordinator(Speaker(enabled=False))
    c.agent = Answering()
    c.start()
    c.submit("read me my apps", "dashboard")
    deadline = time.time() + 5
    while time.time() < deadline and not any((e.get("data") or {}).get("final") for e in c.log):
        time.sleep(0.01)
    final = next(e for e in c.log if (e.get("data") or {}).get("final"))
    assert final["data"]["unverified"] == 2  # the count only (2026-10-21), never the strings
    assert "4111 1111 1111 1111" not in json.dumps(final)  # a card number never goes out, here either


def test_no_note_on_the_last_allowed_step(tmp_path):
    """Review 2026-10-21, M2: a note at step == max_steps left no step to answer it, so a right (or nearly right)
    answer ended as "I gave up after N steps". On the last step the answer stands, with its unverified count."""
    agent, client, _ = make([[tool_use("done", "d1", summary=PADDED, success=True)]], tmp_path)
    result = agent.run("read me the names of the first apps", max_steps=1)
    assert result.success and result.summary == PADDED and result.unverified == 1
    assert len(client.requests) == 1
    agent, client, _ = make([[tool_use("done", "d1", summary=FIXED, success=True)]], tmp_path)
    result = agent.run("read me the names of the first apps", max_steps=1)
    assert result.success and result.summary == FIXED and result.unverified == 0
