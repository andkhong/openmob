"""Verified landings finish without the vision `done` (perf/launch-latency, 2026-10-21; latency review rec. #4).

Measured on the owner's Samsung, 2026-10-20: 53 of 55 done steps went through the vision model at 2.7-3.0 s each,
40-55% of a short task's wall time; the one warm-up that skipped it ran 1.5 s end to end against a 5.4 s median.
A plain navigation request ("Open Settings and go to Display", "open the battery page") whose helper steps landed
on a screen titled after the request's target now ends there. Conservative: only pure navigation (no action, read,
condition, count or order, no correction, nothing typed or risky, no approval, no vision step, no relevant saved
preference), and only on a title or selected tab named after the target, not a list row; any doubt is the vision
check, as before.
"""

import pytest
from conftest import FakeDriver, RecordingIO, ScriptedClient, tool_use
from test_fast_path import Judge

from openmob import permissions as perm
from openmob.agent.loop import Agent
from openmob.config import Config, load_config
from openmob.phone.adb import UIElement
from openmob.phone.apps import AppResolver

SETTINGS, CHROME = "com.android.settings", "com.android.chrome"
LABELS = {SETTINGS: "Settings", CHROME: "Chrome"}
DONE = [tool_use("done", "z", summary="Display is open.", success=True)]


def el(i, text, clickable=True, top=None, cls="TextView", **kw):
    y = 300 + 150 * i if top is None else top
    return UIElement(i, text, "", "", cls, clickable, None, (0, y, 1000, y + 100), **kw)


HOME = [el(0, "Chrome"), el(1, "Settings"), el(2, "Phone"), el(9, "spacer", clickable=False, top=2200)]
# The Display page: its title at the top (not tappable, not inside a row), then its rows.
DISPLAY_PAGE = [el(0, "Display", clickable=False, top=150), el(1, "Brightness level"), el(2, "Dark theme"),
                el(3, "Screen timeout"), el(9, "spacer", clickable=False, top=2200)]
# A page that only lists "Display" as a row: a way there, not the place.
SETTINGS_MAIN = [el(0, "Settings", clickable=False, top=150), el(1, "Display"), el(2, "Sound"), el(3, "Battery"),
                 el(9, "spacer", clickable=False, top=2200)]
SOUND_PAGE = [el(0, "Sound", clickable=False, top=150), el(1, "Volume"), el(9, "spacer", clickable=False, top=2200)]


class Phone(FakeDriver):
    """Opens Settings pages directly; each page key or tapped label shows its screen."""

    can_open_settings = True

    def __init__(self, pages=None, screens=None, **kw):
        super().__init__(packages=list(LABELS), labels=LABELS, elements=list(HOME), **kw)
        self.pages = pages or {"display": DISPLAY_PAGE, "sound": SOUND_PAGE}
        self.screens = screens or {}

    def open_settings(self, page, package=None):
        out = super().open_settings(page, package)
        self.elements = list(self.pages.get(page, SETTINGS_MAIN))
        return out

    def launch(self, package):
        out = super().launch(package)
        if package == SETTINGS:
            self.elements = list(SETTINGS_MAIN)
        return out

    def tap(self, x, y):
        super().tap(x, y)
        for e in self.elements:
            x1, y1, x2, y2 = e.bounds
            if x1 <= x < x2 and y1 <= y < y2 and e.text in self.screens:
                self.elements = list(self.screens[e.text])
                return


def run(task, responses=(DONE,), judge=None, driver=None, tmp_path=None, mode=None, **cfg):
    config = Config(**{"settle_delay": 0, "launch_settle_delay": 0, "fast_path": "on", "fast_path_done": False,
                       **cfg})
    driver = driver or Phone()
    resolver = AppResolver(driver, {"settings": SETTINGS}, label_cache=tmp_path / "l.json")
    resolver.ensure_labels()
    io = RecordingIO()
    steps = []
    io.record_step = steps.append
    client = ScriptedClient([list(r) for r in responses])
    agent = Agent(client, driver, resolver, config, io, judge=judge, use_ocr=False)
    perms = perm.TaskPermissions(mode or "auto", lambda: perm.normalize(perm.default_settings()))
    result = agent.run(task, permissions=perms)
    return agent, client, driver, steps, result


# --- it fires --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("task", ["Open Settings and go to Display", "go to display in settings",
                                  "open the display settings"])
def test_a_direct_settings_landing_ends_without_the_vision_model(task, tmp_path):
    agent, client, driver, steps, result = run(task, tmp_path=tmp_path)
    assert ("open_settings", "display", None) in driver.actions
    assert result.success and result.done_via == "landing" and result.summary == "Display is open."
    assert client.requests == []  # no vision call at all
    assert steps[-1]["tool"] == "done" and steps[-1]["fast"] is True


@pytest.mark.parametrize("task", ["show me Display", "Go to Settings > Display"])
def test_a_fast_path_tap_landing_ends_without_the_vision_model(task, tmp_path):
    driver = Phone(screens={"Display": DISPLAY_PAGE})
    driver.package = SETTINGS
    driver.elements = list(SETTINGS_MAIN)
    judge = Judge([("TAP", 1, 0.95), ("ESCALATE", None, 0.5)])
    agent, client, driver, steps, result = run(task, judge=judge, driver=driver, tmp_path=tmp_path,
                                               deep_links_fast=False)
    assert [a[0] for a in driver.actions if a[0] == "tap"] == ["tap"]
    assert result.success and result.done_via == "landing" and client.requests == []


# --- it doesn't ------------------------------------------------------------------------------------------------


def test_a_row_named_after_the_target_is_not_a_landing(tmp_path):
    driver = Phone(pages={"display": SETTINGS_MAIN})  # the page didn't open: Display is only a row
    agent, client, driver, steps, result = run("Open Settings and go to Display", driver=driver, tmp_path=tmp_path)
    assert result.done_via == "vision" and len(client.requests) == 1


def test_a_different_page_is_not_a_landing(tmp_path):
    driver = Phone(pages={"display": SOUND_PAGE})
    agent, client, _, _, result = run("Open Settings and go to Display", driver=driver, tmp_path=tmp_path)
    assert result.done_via == "vision" and len(client.requests) == 1


@pytest.mark.parametrize("task", [
    "Open Settings and go to Display and tell me the brightness",  # a read
    "open the display settings and turn on dark theme",  # an action
    "Open Settings, wait 10 seconds, then go to Display",  # a wait and an order
    "if wifi is off, open the display settings",  # a condition
    "Open Settings and go to Display\nUser correction: go to Sound instead",  # a correction
    "what's on the display settings page",  # a question
])
def test_anything_beyond_plain_navigation_keeps_the_vision_check(task, tmp_path):
    agent, client, _, _, result = run(task, tmp_path=tmp_path)
    assert result.done_via != "landing"
    assert len(client.requests) >= 1


def test_the_switch_turns_it_off(tmp_path, monkeypatch):
    agent, client, _, _, result = run("Open Settings and go to Display", tmp_path=tmp_path, landing_done=False)
    assert result.done_via == "vision" and len(client.requests) == 1
    path = tmp_path / "c.yaml"
    path.write_text("landing_done: true\n")
    monkeypatch.setenv("OPENMOB_LANDING_DONE", "off")
    assert load_config(path).landing_done is False


def test_ask_every_step_mode_keeps_the_vision_check(tmp_path):
    agent, client, _, _, result = run("Open Settings and go to Display", tmp_path=tmp_path, mode="ask",
                                      responses=[DONE, DONE])
    assert result.done_via != "landing"


def fast_landing(task, tmp_path, responses=(DONE,), judge_script=(("TAP", 1, 0.95), ("ESCALATE", None, 0.5))):
    """The fast path taps the Display row on Settings' main page and lands on the Display page, whatever the request
    says (a scripted classifier), so only the request and task checks decide."""
    driver = Phone(screens={"Display": DISPLAY_PAGE})
    driver.package = SETTINGS
    driver.elements = list(SETTINGS_MAIN)
    return run(task, responses=responses, judge=Judge(list(judge_script)), driver=driver, tmp_path=tmp_path,
               deep_links_fast=False)


@pytest.mark.parametrize("task", [
    "Turn on dark theme and show me Display",  # an action before the navigation
    "Tell me the brightness and show me Display",  # a read
    "Send a screenshot to Sam and show me Display",  # a send
])
def test_a_landing_on_the_target_of_a_request_that_does_more_keeps_the_vision_check(task, tmp_path):
    agent, client, driver, _, result = fast_landing(task, tmp_path)
    assert result.done_via != "landing" and len(client.requests) >= 1


def test_a_task_the_vision_model_already_stepped_in_keeps_the_vision_check(tmp_path):
    driver = Phone(screens={"Display": DISPLAY_PAGE})
    driver.package = SETTINGS
    driver.elements = list(SETTINGS_MAIN)
    agent, client, driver, _, result = run(
        "show me Display", responses=[[tool_use("tap_element", "t", index=1, target="Display")], DONE],
        judge=Judge([("ESCALATE", None, 0.5)]), driver=driver, tmp_path=tmp_path, deep_links_fast=False)
    assert result.done_via == "vision" and len(client.requests) == 2


# --- fix round 1 (review of 2026-10-21): C1, the landing's own strict request check; I1, the named app in front ----

from openmob.agent import fast  # noqa: E402

CLOCK = "com.google.android.deskclock"
FILES = "com.google.android.documentsui"
CLOCK_MAIN = [el(0, "Clock", clickable=False, top=150), el(1, "Stopwatch"), el(2, "Timer"),
              el(9, "spacer", clickable=False, top=2200)]
STOPWATCH = [el(0, "Stopwatch", clickable=False, top=150), el(1, "Start"), el(2, "Reset"),
             el(9, "spacer", clickable=False, top=2200)]
AIRPLANE = [el(0, "Airplane mode", clickable=False, top=150), el(1, "Use airplane mode"),
            el(9, "spacer", clickable=False, top=2200)]

ACTIONS_WITH_A_NAVIGATION_VERB = [
    "Start the stopwatch", "Open Clock and start the stopwatch", "Switch to airplane mode", "Start a timer",
    "Start recording in Voice Recorder", "Launch the camera and start video", "Switch to dark mode",
    "Start battery saver", "Start Focus mode", "Open Spotify and start my Discover Weekly", "Display the stopwatch",
    "View my timer", "Turn to the Display page", "Set up Display", "Enable airplane mode", "Disable Focus mode",
    "Play my Discover Weekly", "Record a video", "Launch the camera in video mode", "Open dark mode",
    "Go to airplane mode", "Open battery saver", "Navigate to home", "Navigate to Display",
    "Open the camera to take a selfie", "Go to the stopwatch to start it",
]


@pytest.mark.parametrize("task", ACTIONS_WITH_A_NAVIGATION_VERB)
def test_a_landing_request_needs_a_plain_navigation_verb_in_every_clause(task):
    is_app = lambda name: name.lower() in {"clock", "camera", "spotify", "settings", "voice recorder"}  # noqa: E731
    assert not fast.landing_request(task, [], is_app)


@pytest.mark.parametrize("task", [
    "Open Settings and go to Display", "go to display in settings", "open the display settings", "show me Display",
    "Go to Settings > Display", "take me to the Sound settings", "bring up Display",
    "pull up the Battery page", "open up Display", "go into Display", "Launch Settings and go to Display",
    "Launch Clock", "Open the stopwatch", "open the battery saver settings",
])
def test_plain_navigation_is_a_landing_request(task):
    is_app = lambda name: name.lower() in {"clock", "settings"}  # noqa: E731
    assert fast.landing_request(task, [], is_app)


def test_launch_needs_an_app_name_for_a_landing():
    assert not fast.landing_request("Launch the stopwatch", [], lambda name: False)




@pytest.mark.parametrize("task", ["Start the stopwatch", "Open Clock and start the stopwatch"])
def test_starting_the_stopwatch_never_ends_as_a_landing(task, tmp_path):
    driver = Phone(screens={"Stopwatch": STOPWATCH})
    driver.package = CLOCK
    driver.elements = list(CLOCK_MAIN)
    agent, client, driver, _, result = run(task, judge=Judge([("TAP", 1, 0.95), ("ESCALATE", None, 0.5)]),
                                           driver=driver, tmp_path=tmp_path, deep_links_fast=False)
    assert result.done_via != "landing" and len(client.requests) >= 1


def test_switching_to_airplane_mode_never_ends_as_a_landing(tmp_path):
    driver = Phone(pages={"airplane_mode": AIRPLANE})
    agent, client, driver, _, result = run("Switch to airplane mode", driver=driver, tmp_path=tmp_path)
    assert result.done_via != "landing" and len(client.requests) >= 1


DOWNLOADS = [el(0, "Downloads", clickable=False, top=150), el(1, "report.pdf"),
             el(9, "spacer", clickable=False, top=2200)]


def test_a_landing_needs_the_named_app_in_front(tmp_path):
    """I1: "Open Chrome and go to Downloads" on the Files app's Downloads page is not a landing."""
    driver = Phone(screens={"Downloads": DOWNLOADS})
    driver.package = FILES  # a stray tap left Files in front
    driver.elements = [el(0, "Files", clickable=False, top=150), el(1, "Downloads"),
                       el(9, "spacer", clickable=False, top=2200)]
    agent, client, driver, _, result = run("Open Chrome and go to Downloads", tmp_path=tmp_path, driver=driver,
                                           judge=Judge([("TAP", 1, 0.95), ("ESCALATE", None, 0.5)]),
                                           deep_links_fast=False)
    assert result.done_via != "landing" and len(client.requests) >= 1


def test_the_named_app_in_front_still_lands(tmp_path):
    driver = Phone(screens={"Downloads": DOWNLOADS})
    driver.package = CHROME
    driver.elements = [el(0, "Chrome", clickable=False, top=150), el(1, "Downloads"),
                       el(9, "spacer", clickable=False, top=2200)]
    agent, client, driver, _, result = run("Open Chrome and go to Downloads", tmp_path=tmp_path, driver=driver,
                                           judge=Judge([("TAP", 1, 0.95), ("ESCALATE", None, 0.5)]),
                                           deep_links_fast=False)
    assert result.done_via == "landing" and client.requests == []
