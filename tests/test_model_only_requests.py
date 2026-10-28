"""Bug D (2026-10-20, the owner's Samsung): "Open Settings, wait 90 seconds on the main Settings screen, then go to
Display" had Display tapped by the fast path before any wait, and the task failed. A request with steps the helpers
can't carry out (a wait or duration, a condition, an order beyond a plain "then", a count) is decided by the main
model at every step; a plain navigation request keeps its fast path."""

import pytest

from conftest import tool_use
from test_fast_path import DISPLAY, DONE, SETTINGS, Judge, Phone, make

from openmob.agent import fast

MODEL_ONLY = [
    "Open Settings, wait 90 seconds on the main Settings screen, then go to Display",
    "wait 10 seconds then open display settings",
    "After the Settings app opens, go to Display",
    "Open Settings and stay there for a minute, then go to Display",
    "If dark theme is off, open display settings",
    "Tap Display 3 times",
    "read me the names of the first 30 apps",
]
FAST = [
    "open display settings",
    "Open Settings and go to Display",
    "Open Settings, then go to Display",
    "Open the Clock app, go to the Stopwatch, start it, then pause it and reset it to zero",
    "Install the Calculator app by Google from the Play Store",
    "Save the page as PDF",
    "open the notification settings for Chrome and tell me if they're on",
]


@pytest.mark.parametrize("request_text", MODEL_ONLY)
def test_requests_the_helpers_cant_carry_out_are_model_only(request_text):
    assert fast.model_only(request_text)


@pytest.mark.parametrize("request_text", FAST)
def test_plain_navigation_requests_keep_their_helpers(request_text):
    assert not fast.model_only(request_text)


@pytest.mark.parametrize("request_text", MODEL_ONLY[:4])
def test_the_fast_path_never_jumps_ahead_of_a_wait_or_an_order(tmp_path, request_text):
    driver = Phone(SETTINGS, {"Display": DISPLAY})
    judge = Judge([("TAP", 1, 0.95), ("DONE", None, 0.95)])
    model = [[tool_use("wait", "w", seconds=0)], [tool_use("tap_element", "t", index=1, target="Display")], DONE]
    agent, client, steps = make(model, driver, judge, tmp_path)
    result = agent.run(request_text)
    assert result.success
    assert not judge.asked  # the classifier was never asked for a step
    assert [s["tool"] for s in steps] == ["wait", "tap_element", "done"]
    assert all(s["fast"] is False for s in steps)  # every step was the main model's
    assert "+fast" not in steps[0]["variant"]


def test_a_plain_request_still_takes_the_fast_path(tmp_path):
    """No latency regression: the same screens, a plain request, the classifier's tap and no model call before it."""
    driver = Phone(SETTINGS, {"Display": DISPLAY})
    judge = Judge([("TAP", 1, 0.95), ("DONE", None, 0.95)])
    agent, client, steps = make([DONE], driver, judge, tmp_path)
    result = agent.run("Open Settings and go to Display")
    assert result.success and len(client.requests) == 1
    assert steps[0]["tool"] == "tap_element" and steps[0]["fast"] is True


def test_a_correction_with_a_wait_turns_the_helpers_off(tmp_path):
    import threading

    from openmob.agent.loop import _TaskState

    agent, _, _ = make([], Phone(SETTINGS), Judge([("DONE", None, 0.9)]), tmp_path)
    said = ["wait 30 seconds first"]
    agent.io.take_corrections = lambda: [said.pop()] if said else []
    state = _TaskState(task="open display settings", cancel=threading.Event())
    state.fast = True
    agent._apply_corrections(state, [{"role": "user", "content": []}])
    assert state.model_only and not state.fast


# perf/prelaunch-1-4: words inside what the user wants typed, sent or looked up aren't steps, and a wait, condition,
# order or count word only counts when it governs a step. Each over-match lost the fast path (est. 2-5 s per task).
OVER_MATCHES = [
    "Search YouTube for a one minute workout",
    "Open Maps and find coffee shops open after 9pm",
    "Text Sam: see you when you get here",
]
SEARCH_AND_MESSAGE = [
    "Search Google for what to do if my phone gets wet",
    "Look up when the pharmacy on Main St closes",
    "Search Amazon for a 5 minute sand timer",
    "Message Mom saying I'll call after dinner",
    "Reply to Alex: running 10 minutes late",
    "Send a WhatsApp to Jo that says wait for me at the door",
    'Text Dana "if you see this, call me"',
    "Search Spotify for songs to play while running",
    "Search for 'every breath you take' on YouTube Music",
    "Email Bob saying the meeting moved to after lunch",
    "Find restaurants open until midnight",
    "Open Chrome and look for the first 10 digits of pi",
    "Say see you once I land to Priya on WhatsApp",
    "Open Messages and reply to Kim: on my way, be there in 5 minutes",
    "Google how many times a day to feed a puppy",
    "Find flights to Tokyo before Friday",
]
VALUES_NOT_STEPS = [
    "Set a timer for 5 minutes",
    "Set the screen timeout to 30 seconds",
    "Set an alarm for 7am every weekday",
    "Tap the first one",
]
STILL_MODEL_ONLY = [
    "Wait 90 seconds then open Display",
    "after it loads, tap Start",
    "if Wi-Fi is off, turn it on",
    "read me the first 5 emails",
    "read me the first five emails",
    "Tap Start once it loads",
    "When the page loads, tap Sign in",
    "Open Settings and after that go to Display",
    "wait for it to load then tap Start",
    # A step after the searched-for or sent text still counts.
    "Open YouTube, search for cats, then wait 10 seconds",
    "Search for cats and if nothing shows, go back",
    "Find Display, wait 10 s, then tap it",
    "Text Sam hi, then wait a minute and open Settings",
    "User correction: wait 30 seconds first",
]


@pytest.mark.parametrize("request_text", OVER_MATCHES + SEARCH_AND_MESSAGE + VALUES_NOT_STEPS)
def test_searched_or_sent_words_and_values_keep_the_fast_path(request_text):
    assert not fast.model_only(request_text)


@pytest.mark.parametrize("request_text", STILL_MODEL_ONLY)
def test_a_wait_condition_order_or_count_that_governs_a_step_is_model_only(request_text):
    assert fast.model_only(request_text)


# perf/launch-latency (2026-10-21): a clock time is a value in every spelling ("8am", "8 am", "8:30pm"); before, "\d"
# followed by letters ("8am") read as an ordering word, so "until 8am" sent the request to the model at every step.
CLOCK_TIMES = [
    "Turn on Do Not Disturb until 8am",
    "Turn on Do Not Disturb until 8 am",
    "Turn on Do Not Disturb until 8:30pm",
    "Turn on Do Not Disturb until 08:30",
    "Turn on Do Not Disturb until 7 p.m.",
    "Open Maps and find bars open after 11PM",
    "Set an alarm for 6:45 am",
    "Mute notifications until 10:15 pm",
]


@pytest.mark.parametrize("request_text", CLOCK_TIMES)
def test_clock_times_are_values_not_steps(request_text):
    assert not fast.model_only(request_text)


@pytest.mark.parametrize("request_text", ["Wait until 8am then open Settings", "until it loads, wait"])
def test_an_order_word_without_a_clock_time_still_counts(request_text):
    assert fast.model_only(request_text)


# Review 2026-10-21, M5: a step after a message body or a lookup still counts.
MISSES = [
    "Text Sam: see you at 8, then wait 10 minutes and text Alex",
    "Find the stopwatch and start it once it loads",
    "Open YouTube, search cats and play the first 3 videos",
    "Reply to Alex: on my way; then wait 5 minutes and open Maps",
    "Look up the recipe and play the first 2 videos",
]


@pytest.mark.parametrize("request_text", MISSES)
def test_a_step_after_a_message_or_a_lookup_is_model_only(request_text):
    assert fast.model_only(request_text)


@pytest.mark.parametrize("request_text", [
    "Text Sam: grab milk, then come home",  # ", then" inside a body with no step word stays fast
    "Search YouTube for cats and play",
])
def test_a_plain_step_after_a_message_or_a_lookup_keeps_the_fast_path(request_text):
    assert not fast.model_only(request_text)
