"""Preferences memory in threads: events carry note ids, never text; the line is rendered at read time (Task 3)."""

import json

from conftest import RecordingIO, text_block, tool_use
from test_easy_connect import srv  # noqa: F401 (the fixture)
from test_memory_agent import DONE, make, note, store
from test_phone_chats import _ask, _paired, _run

from openmob.history import History
from openmob.memory import render_events
from openmob.runner import Coordinator
from openmob.voice.tts import Speaker


class DataIO(RecordingIO):
    def event(self, kind, message, data=None):
        self.events.append((kind, message, data))


def memory_events(io):
    return [e for e in io.events if e[0] == "memory"]


def used(ids):
    return {"kind": "memory", "message": "", "task": "t1", "time": 1.0, "data": {"use": "used", "note_ids": ids}}


class CountingStore:
    def __init__(self, inner):
        self.inner, self.calls = inner, 0

    def get_many(self, account_id, ids):
        self.calls += 1
        return self.inner.get_many(account_id, ids)


# --- what is stored ----------------------------------------------------------------------------------

def test_events_store_ids_not_text(tmp_path):
    mem = store(tmp_path)
    nid = note(mem, "I prefer dark mode")
    agent, _, _, io = make([[text_block("Using [m1]."), *DONE]], tmp_path, mem)
    agent.io = io = DataIO()
    agent.run("open settings", memory_allowed=True)
    [event] = memory_events(io)
    assert event[1] == "" and event[2] == {"use": "used", "note_ids": [nid]}
    assert "dark mode" not in json.dumps(io.events)
    # Through a Coordinator into history: ids only, and the file holds no note text.
    history = History(tmp_path / "h.sqlite")
    c = Coordinator(Speaker(enabled=False), history=history)
    c.chat_id = history.create_chat(None, "d", "m", "open settings")
    c.event("memory", "", task="t1", data={"use": "used", "note_ids": [nid]})
    stored = [e for e in history.events(None, c.chat_id) if e["kind"] == "memory"]
    assert stored[0]["data"]["note_ids"] == [nid] and "dark mode" not in json.dumps(stored)
    assert "dark mode" not in json.dumps(list(c.log))


def test_one_used_event_per_task(tmp_path):
    mem = store(tmp_path)
    ids = [note(mem, f"About me {i}") for i in range(3)]
    steps = [[text_block("Checking [m1] and [m2]."), tool_use("press_key", "k1", key="BACK")],
             [text_block("Again [m1]."), tool_use("done", "d", summary="Done [m2].", success=True)]]
    agent, _, _, _ = make(steps, tmp_path, mem)
    agent.io = io = DataIO()
    result = agent.run("open settings", memory_allowed=True)
    [event] = memory_events(io)
    cited = {mem_id for mem_id in event[2]["note_ids"]}
    assert len(event[2]["note_ids"]) == 2 and cited <= set(ids)  # only the ones cited, once each
    assert "[m" not in result.summary and not any("[m" in str(e[1]) for e in io.events)
    row = {n["id"]: n for n in mem.list(None)}
    assert sum(row[i]["uses"] for i in ids) == 2  # mark_used once, at the end


def test_no_citation_falls_back_to_the_relevant_notes_and_nothing_without_memory(tmp_path):
    mem = store(tmp_path)
    note(mem, "About me")
    app = note(mem, "Quest tips", kind="app", package="com.netease.wwm")
    agent, _, _, _ = make([DONE], tmp_path, mem)
    agent.io = io = DataIO()
    agent.resolver.ensure_labels()
    agent.run("open Where Winds Meet", memory_allowed=True)
    [event] = memory_events(io)
    assert event[2]["note_ids"] == [app]  # about-you notes don't count without a citation
    agent, _, _, _ = make([DONE], tmp_path, mem)
    agent.io = io = DataIO()
    agent.run("open settings")  # memory not allowed
    assert memory_events(io) == []


# --- rendering ---------------------------------------------------------------------------------------

def test_thread_renders_current_text_after_edit(tmp_path):
    mem = store(tmp_path)
    a, b = note(mem, "I prefer dark mode"), note(mem, "Call me Sam")
    [e] = render_events(mem, None, [used([a, b])], trusted=True, enabled=True)
    assert e["message"] == "Used your preferences: I prefer dark mode; Call me Sam"
    mem.update(None, a, text="I prefer light mode")
    [e] = render_events(mem, None, [used([a, b])], trusted=True, enabled=True)
    assert e["message"] == "Used your preferences: I prefer light mode; Call me Sam"


def test_all_three_uses_render(tmp_path):
    mem = store(tmp_path)
    p = mem.add(None, "she likes voice notes", "person", relation="sis", contact_name="Maya Lee", status="active")["id"]
    q = mem.add(None, "Likes tea", "about_you", status="proposed")["id"]
    events = [
        {"kind": "memory", "message": "", "task": "t", "time": 1, "data": {"use": "sending_to", "note_ids": [p]}},
        {"kind": "memory", "message": "", "task": "t", "time": 2, "data": {"use": "proposed", "note_ids": [q]}},
        {"kind": "memory", "message": "", "task": "t", "time": 3, "data": {"use": "proposed", "note_ids": [p]}},
        {"kind": "status", "message": "x", "task": "t", "time": 4},
    ]
    out = render_events(mem, None, events, trusted=True, enabled=True)
    assert out[0]["message"] == "Sending to Maya Lee — your sis, from your saved preferences"
    assert out[1]["message"] == "Save this? Likes tea"
    assert out[2]["message"] == "Saved: your sis = Maya Lee — she likes voice notes"  # p is already saved
    assert out[3] == events[3]
    assert events[0]["message"] == ""  # the inputs are untouched


def test_deleting_mid_task_hides_it_from_recall_and_threads(tmp_path):
    mem = store(tmp_path)
    a = note(mem, "My secret nickname is Zorblax")
    event = used([a])
    assert "Zorblax" in render_events(mem, None, [event], True, True)[0]["message"]
    mem.delete(None, a)
    assert mem.search(None, "Zorblax") == [] and mem.get(None, a) is None  # recall can't return it
    [e] = render_events(mem, None, [event], True, True)
    assert e["message"] == "Used your preferences: a deleted preference"
    assert "Zorblax" not in json.dumps(e)
    assert b"Zorblax" not in (tmp_path / "memory.sqlite").read_bytes()


def test_untrusted_phone_sees_placeholder(tmp_path):
    mem = store(tmp_path)
    a = note(mem, "I prefer dark mode")
    [e] = render_events(mem, None, [used([a])], trusted=False, enabled=True)
    assert e["message"] == "Used your preferences: a saved preference" and "dark" not in json.dumps(e)


def test_switch_off_hides_memory_events(tmp_path):
    mem = store(tmp_path)
    a = note(mem, "I prefer dark mode")
    other = {"kind": "action", "message": "tap", "task": "t1", "time": 2}
    assert render_events(mem, None, [used([a]), other], True, False) == [other]
    assert render_events(None, None, [used([a]), other], True, True) == [other]


def test_one_lookup_per_render(tmp_path):
    mem = store(tmp_path)
    a, b = note(mem, "One"), note(mem, "Two")
    counting = CountingStore(mem)
    events = [used([a]), used([b]), {"kind": "memory", "message": "", "task": "t2", "time": 3,
                                      "data": {"use": "used", "note_ids": [a, b]}}]
    out = render_events(counting, None, events, True, True)
    assert counting.calls == 1 and len(out) == 3
    render_events(counting, None, [{"kind": "action", "message": "x", "task": "t", "time": 1}], True, True)
    assert counting.calls == 1  # nothing to look up: no read


# --- the same line everywhere ------------------------------------------------------------------------

def test_status_chats_and_phone_render_the_same_line(srv, tmp_path):  # noqa: F811
    mem = store(tmp_path)
    srv.manager.memory = mem
    srv.manager.cfg.memory = True
    user, phone, session = _paired(srv, "alice@example.com", "phone-a")
    nid = mem.add(session.account_id, "I prefer dark mode", "about_you", status="active")["id"]
    _run(phone, "open settings")
    c = session.coordinator
    task = srv.manager.history.turn_order(c.account_id, c.chat_id)[0]
    c.event("memory", "", task=task, data={"use": "used", "note_ids": [nid]})
    want = "Used your preferences: I prefer dark mode"
    status = user.get(f"/api/devices/{session.info.id}/status").json()
    assert [e["message"] for e in status["log"] if e["kind"] == "memory"] == [want]
    chat = _ask(phone, {"type": "chat_read", "chat_id": c.chat_id}, "chat")
    assert chat["turns"][0]["memory"] == [want]
    # The stored event holds the ids only; opening the chat again shows the same line on the dashboard.
    assert all(e["message"] == "" for e in srv.manager.history.events(c.account_id, c.chat_id) if e["kind"] == "memory")
    # Switch off: gone from both.
    srv.manager.cfg.memory = False
    status = user.get(f"/api/devices/{session.info.id}/status").json()
    assert not [e for e in status["log"] if e["kind"] == "memory"]
    assert _ask(phone, {"type": "chat_read", "chat_id": c.chat_id}, "chat")["turns"][0].get("memory", []) == []


# --- the proposal card in the phone's chat (Task 8) -------------------------------------------------

def _proposed(nid):
    return {"kind": "memory", "message": "", "task": "t1", "time": 1.0,
            "data": {"use": "proposed", "note_ids": [nid], "card": {"note_id": nid, "status": "proposed"}}}


def _cards(mem, events, trusted=True):
    from openmob.phone_chats import _turns_from_events
    out = render_events(mem, None, events, trusted=trusted, enabled=True)
    [turn] = _turns_from_events(out, [])
    return turn


def test_the_phone_thread_carries_the_proposal_card(tmp_path):
    mem = store(tmp_path)
    a = mem.add(None, "Likes tea", "about_you", status="proposed")["id"]
    p = mem.add(None, "she likes voice notes", "person", relation="sis", contact_name="Maya Lee", status="proposed")["id"]
    turn = _cards(mem, [_proposed(a), _proposed(p)])
    assert turn["memory_cards"] == [
        {"note_id": a, "text": "Save this? Likes tea", "status": "proposed"},
        {"note_id": p, "text": "Save this? your sis = Maya Lee — she likes voice notes", "status": "proposed"}]
    assert "memory" not in turn  # the card is not also a "Used your preferences" line
    mem.confirm(None, a)
    assert _cards(mem, [_proposed(a)])["memory_cards"][0]["status"] == "active"


def test_deleted_and_untrusted_cards_have_no_text_and_no_buttons(tmp_path):
    mem = store(tmp_path)
    a = mem.add(None, "Zorblax tea", "about_you", status="proposed")["id"]
    [c] = _cards(mem, [_proposed(a)], trusted=False)["memory_cards"]
    assert c == {"note_id": a, "text": "a saved preference", "status": "gone"}
    mem.delete(None, a)
    [c] = _cards(mem, [_proposed(a)])["memory_cards"]
    assert c == {"note_id": a, "text": "a deleted preference", "status": "gone"}


def test_no_cards_no_key(tmp_path):
    mem = store(tmp_path)
    a = note(mem, "I prefer dark mode")
    assert "memory_cards" not in _cards(mem, [used([a])])
