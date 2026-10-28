"""People and the "Sending to" line (Task 5): one informational line before the first send, no extra phone ask."""

from conftest import FakeDriver, ScriptedClient, tool_use
from test_permissions import IO as PermIO, WA, el, tap, taps

from openmob import permissions as perm
from openmob.agent.loop import Agent
from openmob.config import Config
from openmob.memory import Memory
from openmob.phone.apps import AppResolver

DONE = [tool_use("done", "z", summary="ok", success=True)]


class IO(PermIO):
    def __init__(self, answers=None):
        super().__init__(answers)
        self.data = []

    def event(self, kind, message, data=None):
        self.events.append((kind, message))
        self.data.append((kind, data))


def person(mem, relation="sis", name="Ava"):
    return mem.add(None, "texts in the evening", "person", relation=relation, contact_name=name, status="active")


def make(steps, tmp_path, elements=None, answers=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    driver = FakeDriver(packages=[WA], elements=elements or [], labels={WA: "WhatsApp"})
    driver.package = WA
    io = IO(answers)
    agent = Agent(ScriptedClient([*steps, DONE, DONE]), driver,
                  AppResolver(driver, {"whatsapp": WA}, label_cache=tmp_path / "l.json"),
                  Config(settle_delay=0, launch_settle_delay=0, memory=True), io, use_ocr=False)
    agent.memory = Memory(tmp_path / "memory.sqlite")
    perms = perm.TaskPermissions("auto", lambda: perm.normalize(perm.default_settings()))
    return agent, driver, io, perms


def lines(io):
    return [d for k, d in io.data if k == "memory" and d and d.get("use") == "sending_to"]


# The chat's header: the "Sending to" line names a remembered person only when their name is on screen (review 5
# M5-L1, owner 2026-10-21).
AVA = el(9, "Ava", cls="TextView")


def test_sending_line_precedes_the_first_send(tmp_path):
    # button send
    agent, driver, io, perms = make([tap("Send")], tmp_path / "a", elements=[AVA])
    note = person(agent.memory)
    agent.run("send hi to my sis", permissions=perms, memory_allowed=True)
    assert lines(io) == [{"use": "sending_to", "note_ids": [note["id"]]}]
    assert len(taps(driver)) == 1
    # ENTER send
    field = el(0, "Message", cls="EditText", editable=True)
    agent, driver, io, perms = make([[tool_use("type_text", "a", text="hi", submit=True)]], tmp_path / "b",
                                    elements=[field, AVA])
    note = person(agent.memory)
    log = []
    real_event = io.event
    io.event = lambda k, m, data=None: (log.append((data or {}).get("use") or k), real_event(k, m, data))[1]
    driver.key = lambda n, _r=driver.key: (log.append("act:key"), _r(n))[1]
    agent.run("send hi to my sis", permissions=perms, memory_allowed=True)
    assert lines(io) == [{"use": "sending_to", "note_ids": [note["id"]]}]
    assert ("key", "ENTER") in driver.actions
    assert log.index("sending_to") < log.index("act:key")
    assert all(m == "" for k, m in io.events if k == "memory")


def test_button_send_line_comes_before_the_tap(tmp_path):
    agent, driver, io, perms = make([tap("Send")], tmp_path, elements=[AVA])
    person(agent.memory)
    log = []
    real_event = io.event
    io.event = lambda k, m, data=None: (log.append((data or {}).get("use") or k), real_event(k, m, data))[1]
    real_tap = driver.tap
    driver.tap = lambda x, y: (log.append("tap"), real_tap(x, y))[1]
    agent.run("send hi to my sis", permissions=perms, memory_allowed=True)
    assert log.index("sending_to") < log.index("tap")


def test_only_one_sending_line_per_task(tmp_path):
    agent, driver, io, perms = make([tap("Send"), tap("Send", "b")], tmp_path, elements=[AVA])
    person(agent.memory)
    agent.run("send hi to my sis", permissions=perms, memory_allowed=True)
    assert len(lines(io)) == 1


def test_no_person_note_no_sending_line(tmp_path):
    agent, driver, io, perms = make([tap("Send")], tmp_path)
    agent.memory.add(None, "likes brevity", "about_you", status="active")
    agent.run("send hi to my sis", permissions=perms, memory_allowed=True)
    assert lines(io) == [] and len(taps(driver)) == 1


def test_no_line_when_memory_is_off_or_never_mode(tmp_path):
    agent, driver, io, perms = make([tap("Send")], tmp_path / "a")
    person(agent.memory)
    agent.run("send hi to my sis", permissions=perms, memory_allowed=False)
    assert lines(io) == []
    agent, driver, io, _ = make([tap("Send")], tmp_path / "b")
    person(agent.memory)
    never = perm.TaskPermissions("never", lambda: perm.normalize(perm.default_settings()))
    agent.run("send hi to my sis", permissions=never, memory_allowed=True)
    assert lines(io) == []


def test_no_extra_phone_ask_for_people(tmp_path):
    asked = {}
    for name, remembered in (("with", True), ("without", False)):
        agent, driver, io, perms = make([tap("Send")], tmp_path / name)
        if remembered:
            person(agent.memory)
        agent.run("send hi to my sis", permissions=perms, memory_allowed=True)
        asked[name] = (len(io.questions), io.details)
    assert asked["with"] == asked["without"]


def two_people(tmp_path, steps, screen):
    agent, driver, io, perms = make([[tool_use("recall", "r", query="Emily")], *steps], tmp_path, elements=screen)
    a = person(agent.memory, "wife", "Emily Khong")
    b = person(agent.memory, "sis", "Ava")
    return agent, driver, io, perms, a, b


def test_the_person_on_screen_is_named(tmp_path):
    screen = [el(0, "Emily Khong", cls="TextView")]
    agent, driver, io, perms, a, b = two_people(tmp_path, [tap("Send")], screen)
    agent.run("text my wife and tell my sis", permissions=perms, memory_allowed=True)
    assert lines(io) == [{"use": "sending_to", "note_ids": [a["id"]]}]


def test_two_people_neither_on_screen_no_line(tmp_path):
    agent, driver, io, perms, a, b = two_people(tmp_path, [tap("Send")], [el(0, "Someone Else", cls="TextView")])
    agent.run("text my wife and tell my sis", permissions=perms, memory_allowed=True)
    assert lines(io) == []


def test_one_person_not_on_screen_is_not_named(tmp_path):
    """Review 5 M5-L1: the only person in play isn't named unless their name is on screen (the screen may be someone
    else's chat)."""
    agent, driver, io, perms = make([tap("Send")], tmp_path, elements=[el(0, "Mallory Smith", cls="TextView")])
    person(agent.memory)
    agent.run("send hi to my sis", permissions=perms, memory_allowed=True)
    assert lines(io) == []


def test_a_typed_name_in_a_field_does_not_count(tmp_path):
    field = el(0, "tell Emily Khong hi", cls="EditText", editable=True)
    agent, driver, io, perms, a, b = two_people(tmp_path, [tap("Send")], [field])
    agent.run("text my wife and tell my sis", permissions=perms, memory_allowed=True)
    assert lines(io) == []


def test_a_second_send_to_another_person_gets_its_own_line(tmp_path):
    button = [tool_use("tap", "s%d" % i, x=250, y=220, target="Send") for i in range(2)]
    agent, driver, io, perms, a, b = two_people(tmp_path, [[button[0]], [button[1]]],
                                                [el(0, "Emily Khong", cls="TextView")])
    io.answers = ["yes", "yes"]
    sent = {"n": 0}
    real_tap = driver.tap

    def tap_and_switch(x, y):
        sent["n"] += 1
        real_tap(x, y)

    driver.tap = tap_and_switch  # the chat changes once the first send has gone out
    driver.ui_elements = lambda: [el(0, "Ava" if sent["n"] else "Emily Khong", cls="TextView"), el(1, "Send")]
    agent.run("text my wife and tell my sis", permissions=perms, memory_allowed=True)
    assert sent["n"] == 2
    assert [d["note_ids"][0] for d in lines(io)] == [a["id"], b["id"]]


def test_a_send_with_no_screen_data_does_not_raise(tmp_path):
    from types import SimpleNamespace

    agent, driver, io, perms = make([], tmp_path)
    person(agent.memory)
    state = SimpleNamespace(people_used={}, memory_people=True, people_announced=set())
    note = agent.memory.list(None)[0]
    state.people_used[note["id"]] = note
    for obs in (None, SimpleNamespace(elements=None), SimpleNamespace(elements=[el(0, None, cls="TextView")])):
        state.people_announced.clear()
        io.data.clear()
        agent._sending_line(state, obs)  # one person in play, not on screen: no line (review 5 M5-L1)
        assert lines(io) == []
    state.people_used["x"] = {**note, "id": "x", "contact_name": "Zed"}
    state.people_announced.clear()
    io.data.clear()
    agent._sending_line(state, None)  # several, none on screen: no line
    assert lines(io) == []


def test_the_same_person_twice_gets_one_line(tmp_path):
    agent, driver, io, perms, a, b = two_people(tmp_path, [tap("Send"), tap("Send", "b")],
                                                [el(0, "Emily Khong", cls="TextView")])
    agent.run("text my wife and tell my sis", permissions=perms, memory_allowed=True)
    assert [d["note_ids"] for d in lines(io)] == [[a["id"]]]


def test_ambiguous_relation_makes_the_agent_ask(tmp_path):
    steps = [[tool_use("recall", "r", query="sis")], [tool_use("ask_user", "q", question="Which sister?")], tap("Send")]
    agent, driver, io, perms = make(steps, tmp_path, answers=["Ava"])
    log = []
    real_ask, real_tap = io.ask, driver.tap
    io.ask = lambda q: (log.append("ask"), real_ask(q))[1]
    driver.tap = lambda x, y: (log.append("tap"), real_tap(x, y))[1]
    a, b = person(agent.memory, "sis", "Ava"), person(agent.memory, "sis", "Zoe")
    assert len(agent.memory.people(None, "sis")) == 2
    agent.run("text my sis", permissions=perms, memory_allowed=True)
    recall_result = str(agent.client.requests[1]["messages"])
    assert "Ava" in recall_result and "Zoe" in recall_result  # recall returns both; nothing picks one
    assert "several" in str(agent.client.requests[0]["system"]) + str(agent.client.requests[0]["messages"])
    assert io.questions[0] == "Which sister?"
    assert "ask" in log and ("tap" not in log or log.index("ask") < log.index("tap"))
