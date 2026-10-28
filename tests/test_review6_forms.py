"""Security review 6 (2026-10-27), the form batch (up to 4 actions a turn on a form, 144e96c). A batch's later actions
were judged against the screen the model decided on: typing reached a password field that took focus mid-batch (F1),
a Subscribe tap ran before the price the typing revealed was seen (F2), and a batch could end with the send (F3).
Now only taps on text fields and typing without submit share a turn, typing judges the field focused now, and the
allowance is capped at 4 (F5). The drivers are adb/USB phones: the server's checks are the only ones."""
from dataclasses import replace

from conftest import FakeDriver, RecordingIO, ScriptedClient, tool_use

from openmob.agent import fast
from openmob.agent.loop import Agent
from openmob.config import Config
from openmob.phone.adb import UIElement
from openmob.phone.apps import AppResolver


def ed(hint, top, password=False):
    return UIElement(0, "", "", f"app:id/{hint.lower()}", "android.widget.EditText", True, None,
                     (0, top, 1000, top + 100), editable=True, password=password, hint=hint)


def label(text, top):
    return UIElement(0, text, "", "", "android.widget.TextView", False, None, (0, top, 1000, top + 80))


class RevealDriver(FakeDriver):
    """'Continue with email' sign-in, no gatekeeper (an adb/USB phone, where the server's checks are the only ones):
    Name + Email on screen, no password field. Typing an email reveals the password field below it and moves input
    focus there (a page's passwordInput.focus(); the same for an app's requestFocus())."""

    def __init__(self, keyboard_changes=True):
        super().__init__()
        self.package = "com.example.signin"
        self.focus = None
        self.revealed = False
        self.texts = {}
        self.typed_into = []

    def _all(self):
        els = [label("Sign in or create an account", 100), ed("Name", 300), ed("Email", 500),
               label("We'll never share your email", 620)]
        if self.revealed:
            els.append(ed("Password", 720, password=True))
        els.append(UIElement(0, "Continue", "", "app:id/go", "android.widget.Button", True, None, (0, 900, 1000, 1000)))
        if not self.focus:
            els.append(label("Terms and privacy", 1800))  # hidden behind the keyboard once a field has focus
        return [replace(e, index=i, text=self.texts.get(e.resource_id, e.text), focused=e.resource_id == self.focus)
                for i, e in enumerate(els)]

    def ui_elements(self):
        return self._all()

    @property
    def elements(self):
        return self._all()

    @elements.setter
    def elements(self, v):
        pass

    def tap(self, x, y):
        super().tap(x, y)
        for e in self._all():
            if e.editable and e.bounds[0] <= x < e.bounds[2] and e.bounds[1] <= y < e.bounds[3]:
                self.focus = e.resource_id

    def type_text(self, text, replace=False):
        super().type_text(text, replace)
        self.typed_into.append((self.focus, text))
        if self.focus:
            self.texts[self.focus] = self.texts.get(self.focus, "") + text
        if self.focus == "app:id/email" and "@" in text:
            self.revealed, self.focus = True, "app:id/password"


def run(replies, tmp_path, driver, **cfg):
    config = Config(settle_delay=0, launch_settle_delay=0, **cfg)
    resolver = AppResolver(driver, {}, label_cache=tmp_path / "l.json")
    client = ScriptedClient(replies)
    agent = Agent(client, driver, resolver, config, RecordingIO(), use_ocr=False)
    return agent.run("sign in as ann@example.com with password hunter2"), client, driver


def done():
    return tool_use("done", "z", summary="ok", success=True)


BATCH = [tool_use("tap_element", "a", index=2), tool_use("type_text", "b", text="ann@example.com"),
         tool_use("type_text", "c", text="hunter2")]


class JoinDriver(RevealDriver):
    """A sign-up form with a Join button and no price; typing the name shows the price ('$49.99 a month')."""

    def __init__(self):
        super().__init__()
        self.package = "com.example.club"
        self.priced = False

    def _all(self):
        els = [label("Join the club", 100), ed("Name", 300), ed("Email", 500), label("Members get the newsletter", 620)]
        if self.priced:
            els.append(label("$49.99 a month", 700))
        els.append(UIElement(0, "Subscribe", "", "app:id/subscribe", "android.widget.Button", True, None, (0, 900, 1000, 1000)))
        if not self.focus:
            els.append(label("Terms and privacy", 1800))
        return [replace(e, index=i, text=self.texts.get(e.resource_id, e.text), focused=e.resource_id == self.focus)
                for i, e in enumerate(els)]

    def type_text(self, text, replace=False):
        FakeDriver.type_text(self, text, replace)
        self.typed_into.append((self.focus, text))
        if self.focus:
            self.texts[self.focus] = self.texts.get(self.focus, "") + text
        self.priced = True


def run_join(replies, tmp_path, **cfg):
    config = Config(settle_delay=0, launch_settle_delay=0, **cfg)
    driver = JoinDriver()
    resolver = AppResolver(driver, {}, label_cache=tmp_path / "l.json")
    client = ScriptedClient(replies)
    io = RecordingIO()
    agent = Agent(client, driver, resolver, config, io, use_ocr=False)
    result = agent.run("subscribe to the club as Ann")
    return result, client, driver, io


JOIN_INDEX = 4  # 'Subscribe' on the decision screen (before the price shows)
JOIN = [tool_use("tap_element", "a", index=1), tool_use("type_text", "b", text="Ann"),
        tool_use("tap_element", "c", index=JOIN_INDEX)]


def test_it_is_a_form_at_decision_time():
    assert fast.is_form(RevealDriver().ui_elements())


def test_a_batch_never_types_into_a_password_field_that_took_focus(tmp_path):
    """F1: typing the email reveals and focuses the password field; the third call is judged on that field."""
    result, client, driver = run([BATCH, [done()]], tmp_path, RevealDriver())
    assert driver.typed_into == [("app:id/email", "ann@example.com")], driver.typed_into
    assert all(t != "hunter2" for _, t in driver.typed_into)


def test_one_action_a_turn_still_refuses(tmp_path):
    replies = [[c] for c in BATCH] + [[done()]]
    result, client, driver = run(replies, tmp_path, RevealDriver(), form_actions_per_turn=1)
    assert ("app:id/password", "hunter2") not in driver.typed_into, driver.typed_into


def test_a_button_tap_gets_its_own_turn(tmp_path):
    """F2/F3: Subscribe after typing doesn't run in the batch; one turn later it is judged with the price and asks."""
    result, client, driver, io = run_join([JOIN, [done()]], tmp_path)
    assert ("tap", 500, 950) not in driver.actions, driver.actions
    assert ("app:id/name", "Ann") in driver.typed_into
    skipped = [r for r in client.requests[1]["messages"][-1]["content"] if r.get("tool_use_id") == "c"][0]
    assert skipped["is_error"] and "only taps on text fields and typing" in skipped["content"][0]["text"]


def test_one_action_a_turn_asks_before_subscribing(tmp_path):
    replies = [[JOIN[0]], [JOIN[1]], [tool_use("tap_element", "c", index=5)], [done()]]
    result, client, driver, io = run_join(replies, tmp_path, form_actions_per_turn=1)
    assert io.questions and ("tap", 500, 950) not in driver.actions, (io.questions, driver.actions)


def test_typing_with_submit_ends_the_batch(tmp_path):
    calls = [tool_use("tap_element", "a", index=1), tool_use("type_text", "b", text="Ann", submit=True),
             tool_use("tap_element", "c", index=2)]
    result, client, driver, io = run_join([calls, [done()]], tmp_path)
    assert [a[0] for a in driver.actions if a[0] != "wake"] == ["tap"]


def test_a_button_first_ends_the_batch(tmp_path):
    calls = [tool_use("tap_element", "a", index=4), tool_use("tap_element", "b", index=1)]
    result, client, driver, io = run_join([calls, [done()]], tmp_path, confirm_actions="never")
    assert [a for a in driver.actions if a[0] == "tap"] == [("tap", 500, 950)]


def test_the_allowance_is_capped_at_four(tmp_path):
    calls = [tool_use("tap_element", "a", index=1), tool_use("type_text", "b", text="A"),
             tool_use("type_text", "c", text="n"), tool_use("type_text", "d", text="n"),
             tool_use("type_text", "e", text="!")]
    result, client, driver, io = run_join([calls, [done()]], tmp_path, form_actions_per_turn=50)
    assert [t for _, t in driver.typed_into] == ["A", "n", "n"]
