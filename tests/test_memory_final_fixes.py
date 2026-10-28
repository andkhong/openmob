"""Preferences memory, the final fix wave of the whole-branch review: the Save / Not now card end to end (C1), the
live line on the phone (I1), note text to Jev only in Faster mode (I2), the app index read while it fills (I3),
token-mode dashboards (I4), and the promoted minors (M3-M6)."""

import json
import threading

import pytest
from conftest import tool_use
from fastapi.testclient import TestClient
from test_easy_connect import srv  # noqa: F401 (the fixture)
from test_memory_agent import DONE, make, store
from test_memory_phone import _untrust
from test_phone_chats import _ask, _paired, _run
from test_remote import wait_for
from test_runner_server import FakeManager, coordinator

from openmob import phone_memory
from openmob.agent import memory_context
from openmob.agent.loop import _TaskState
from openmob.config import Config
from openmob.memory import Memory, NoteError, render_events
from openmob.server import create_app


def _memory_on(srv, tmp_path):  # noqa: F811
    srv.manager.cfg.memory = True
    srv.manager.memory = Memory(tmp_path / "memory.sqlite")
    return srv.manager.memory


def _remembers(session, text="I prefer dark mode"):
    """The phone's agent, scripted: suggest one preference, then finish."""
    from conftest import ScriptedClient
    session.coordinator.agent.client = ScriptedClient([[tool_use("remember", "r", text=text)], DONE, DONE])


def _status_memory(user, session):
    return [e for e in user.get(f"/api/devices/{session.info.id}/status").json()["log"] if e["kind"] == "memory"]


# --- C1: the card from a real remember, through the Coordinator and History ---------------------------------------

def test_a_remember_shows_the_card_on_the_phone_and_the_dashboard(srv, tmp_path):  # noqa: F811
    mem = _memory_on(srv, tmp_path)
    user, phone, session = _paired(srv, "cara@example.com", "phone-c")  # the account's first phone: trusted
    _remembers(session)
    _run(phone, "turn on dark mode and remember I like it")
    [note] = mem.list(session.account_id, status="proposed")
    c = session.coordinator
    # Stored: the id only, no card key and no text (the card is built when the thread is read).
    [stored] = [e for e in srv.manager.history.events(c.account_id, c.chat_id) if e["kind"] == "memory"]
    assert stored["message"] == "" and stored["data"] == {"use": "proposed", "note_ids": [note["id"]]}
    # The phone's chat carries the card, with Save / Not now (status "proposed").
    chat = _ask(phone, {"type": "chat_read", "chat_id": c.chat_id}, "chat")
    assert chat["turns"][0]["memory_cards"] == [
        {"note_id": note["id"], "text": "Save this? I prefer dark mode", "status": "proposed",
         "origin": "Suggested from what the agent saw on screen"}]  # not the owner's exact words (review 5 M5-L3)
    # The dashboard's /status carries data.card, which index.html's renderTurn keys off.
    [line] = _status_memory(user, session)
    assert line["data"]["card"] == {"note_id": note["id"], "status": "proposed",
                                    "origin": "Suggested from what the agent saw on screen"}
    assert line["message"] == "Save this? I prefer dark mode"
    # Saved: both read "Saved: …" and the buttons go (status "active").
    mem.confirm(session.account_id, note["id"])
    chat = _ask(phone, {"type": "chat_read", "chat_id": c.chat_id}, "chat")
    assert chat["turns"][0]["memory_cards"][0] == {"note_id": note["id"], "text": "Saved: I prefer dark mode",
                                                   "status": "active"}
    assert _status_memory(user, session)[0]["data"]["card"]["status"] == "active"
    phone.disconnect()


def test_an_untrusted_phone_gets_the_placeholder_card_without_buttons(srv, tmp_path):  # noqa: F811
    mem = _memory_on(srv, tmp_path)
    _, phone, session = _paired(srv, "uli@example.com", "phone-ul")
    _remembers(session, "Zorblax is my nickname")
    _run(phone, "remember my nickname")
    [note] = mem.list(session.account_id, status="proposed")
    _untrust(srv.store, "phone-ul")  # as a re-pair without proving its key leaves it
    chat = _ask(phone, {"type": "chat_read", "chat_id": session.coordinator.chat_id}, "chat")
    assert chat["turns"][0]["memory_cards"] == [{"note_id": note["id"], "text": "a saved preference", "status": "gone"}]
    assert "Zorblax" not in json.dumps(chat)
    phone.disconnect()


def test_a_stored_id_only_proposal_renders_a_card(tmp_path):
    mem = store(tmp_path)
    nid = mem.add(None, "Likes tea", "about_you")["id"]
    event = {"kind": "memory", "message": "", "task": "t", "time": 1, "data": {"use": "proposed", "note_ids": [nid]}}
    [out] = render_events(mem, None, [event], trusted=True, enabled=True)
    assert out["data"]["card"] == {"note_id": nid, "status": "proposed"} and "card" not in event["data"]
    used = {**event, "data": {"use": "used", "note_ids": [nid]}}
    assert "card" not in render_events(mem, None, [used], True, True)[0]["data"]  # only a proposal is a card


# --- I1: the live line, rendered for the phone it goes to ---------------------------------------------------------

def _live_memory(phone):
    return [m for k, m in phone.events if k == "memory"]


def test_the_live_push_carries_the_rendered_line(srv, tmp_path):  # noqa: F811
    mem = _memory_on(srv, tmp_path)
    user, phone, session = _paired(srv, "liv@example.com", "phone-l1")
    acct = session.account_id
    person = mem.add(acct, "she likes voice notes", "person", relation="sis", contact_name="Maya Lee", status="active")
    _run(phone, "open settings")
    c = session.coordinator
    task = srv.manager.history.turn_order(c.account_id, c.chat_id)[0]
    c.event("memory", "", task=task, data={"use": "sending_to", "note_ids": [person["id"]]})
    want = "Sending to Maya Lee — your sis, from your saved preferences"
    assert wait_for(lambda: _live_memory(phone) == [want])
    # The stored event stays id-only.
    assert all(e["message"] == "" for e in srv.manager.history.events(c.account_id, c.chat_id) if e["kind"] == "memory")

    # An untrusted phone (the same account's second phone) gets the placeholder, never the name.
    second = _paired_second(srv, user, "phone-l2")
    s2 = srv.manager.sessions["app-phone-l2"]
    assert not srv.store.trusted_for_approvals("phone-l2")
    _run(second, "open settings")
    t2 = srv.manager.history.turn_order(s2.coordinator.account_id, s2.coordinator.chat_id)[0]
    s2.coordinator.event("memory", "", task=t2, data={"use": "sending_to", "note_ids": [person["id"]]})
    assert wait_for(lambda: _live_memory(second) == ["Sending to a saved preference"])
    assert "Maya" not in json.dumps(second.received)

    # The switch off: nothing at all (not even an empty event).
    srv.manager.cfg.memory = False
    c.event("memory", "", task=task, data={"use": "used", "note_ids": [person["id"]]})
    c.event("status", "marker", task=task)
    assert wait_for(lambda: ("status", "marker") in phone.events)
    assert _live_memory(phone) == [want]
    phone.disconnect(); second.disconnect()


def _paired_second(srv, user, device):  # noqa: F811
    from conftest import FakeDriver
    from test_remote import FakePhone
    key = srv.claim(user.post("/api/pairing").json()["code"], device).json()["key"]
    phone = FakePhone(srv.ws, FakeDriver(), device_id=device, key=key)
    assert phone.welcome.wait(5)
    return phone


# --- I2: note text reaches Jev only with Faster mode on (ruling R15) ----------------------------------------------

def test_note_text_rides_the_jev_request_only_in_faster_mode(tmp_path):
    agent, _, _, _ = make([DONE], tmp_path, store(tmp_path))
    state = _TaskState(task="text my sis", cancel=threading.Event())
    state.memory_texts = ["your sis: Maya (a contact) — she likes voice notes"]
    agent.faster_mode = lambda: False  # Jev on, Faster mode off
    assert agent._jev_request(state) == "text my sis"
    agent.faster_mode = None  # no Faster mode setting at all (not an app phone)
    assert agent._jev_request(state) == "text my sis"
    agent.faster_mode = lambda: True
    assert "she likes voice notes" in agent._jev_request(state)
    agent.config.faster_mode = "disabled"  # the server turned Faster mode off
    assert agent._jev_request(state) == "text my sis"


# --- I3: the app index is read while the background thread fills it ----------------------------------------------

class _FillingIndex(dict):
    """An app index that grows while it is iterated, as DeviceManager._index_apps fills resolver.labels."""

    def items(self):
        for i, kv in enumerate(super().items()):
            if i == 0:
                self["com.example.late"] = "Late App"  # the writer thread lands mid-iteration
            yield kv


def test_packages_for_reads_a_snapshot_of_the_app_index():
    index = _FillingIndex({"com.netease.wwm": "Where Winds Meet", "com.android.settings": "Settings"})
    with pytest.raises(RuntimeError):  # what iterating the live dict did
        for _ in index.items():
            pass
    index = _FillingIndex({"com.netease.wwm": "Where Winds Meet", "com.android.settings": "Settings"})
    assert memory_context.packages_for("open where winds meet", None, index) == ["com.netease.wwm"]


def test_packages_for_survives_a_concurrent_writer():
    index = {f"com.example.app{i}": f"App {i}" for i in range(200)}
    stop = threading.Event()

    def writer():
        n = 0
        while not stop.is_set():  # the size keeps changing, but stays small
            index[f"com.example.new{n % 50}"] = f"New {n}"
            index.pop(f"com.example.new{(n + 25) % 50}", None)
            n += 1

    t = threading.Thread(target=writer, daemon=True)
    t.start()
    try:
        for _ in range(300):
            memory_context.packages_for("open app 7", None, index)
    finally:
        stop.set()
        t.join(2)


# --- I4: token mode (no accounts store): the memory routes take the server's token (ruling R16) ------------------

def test_token_mode_dashboards_can_save_edit_and_delete(tmp_path):
    manager = FakeManager(coordinator())
    manager.cfg = Config(memory=True)
    manager.memory = mem = Memory(tmp_path / "memory.sqlite")
    client = TestClient(create_app(manager, token="secret"))
    auth = {"X-OpenMob-Token": "secret"}
    assert client.get("/api/memory").status_code == 401  # no token: refused
    assert client.get("/api/auth/me").json() == {"accounts": False, "memory": True}  # shows the nav link
    made = client.post("/api/memory", json={"text": "I prefer dark mode", "kind": "about_you"}, headers=auth)
    assert made.status_code == 200, made.text
    nid = made.json()["id"]
    assert client.patch(f"/api/memory/{nid}", json={"text": "I prefer light mode"}, headers=auth).status_code == 200
    proposal = mem.add(None, "Likes tea", "about_you")["id"]
    assert client.post(f"/api/memory/{proposal}/confirm", headers=auth).json()["status"] == "active"
    assert client.delete(f"/api/memory/{nid}", headers=auth).json() == {"ok": True}
    assert [n["text"] for n in client.get("/api/memory?t=secret").json()["notes"]] == ["Likes tea"]
    # The pages carry the token: the card's buttons go through api() (X-OpenMob-Token), memory.html sends it too.
    page = client.get("/").text
    assert "await api(`/api/memory/${encodeURIComponent(card.note_id)}/${path}`" in page
    assert '"X-OpenMob-Token": token' in client.get("/memory").text


# --- M3: an edit that changes nothing is a bad request -----------------------------------------------------------

def test_a_phone_edit_with_no_field_is_bad_request_without_a_write_or_audit(tmp_path):
    mem = store(tmp_path)
    nid = mem.add(None, "I prefer dark mode", "about_you", status="active")["id"]
    before = mem.get(None, nid)["updated"]
    rows = []
    reply = phone_memory.reply(mem, None, {"type": "memory_edit", "id": nid}, lambda *a, **k: rows.append(a))
    assert reply == {"type": "memory", "ok": False, "error": "bad_request"}
    assert rows == [] and mem.get(None, nid)["updated"] == before
    ok = phone_memory.reply(mem, None, {"type": "memory_edit", "id": nid, "text": "I prefer light mode"},
                            lambda *a, **k: rows.append(a))
    assert ok["ok"] is True and len(rows) == 1


# --- M4 / M5: saved cards and deleted people ---------------------------------------------------------------------

def test_a_saved_card_reads_saved(tmp_path):
    mem = store(tmp_path)
    a = mem.add(None, "Likes tea", "about_you")["id"]
    p = mem.add(None, "she likes voice notes", "person", relation="sis", contact_name="Maya")["id"]
    events = [{"kind": "memory", "message": "", "task": "t", "time": 1, "data": {"use": "proposed", "note_ids": [i]}}
              for i in (a, p)]
    mem.confirm(None, a)
    mem.confirm(None, p)
    out = render_events(mem, None, events, trusted=True, enabled=True)
    assert [e["message"] for e in out] == ["Saved: Likes tea", "Saved: your sis = Maya — she likes voice notes"]


def test_a_sending_to_line_for_a_deleted_note(tmp_path):
    mem = store(tmp_path)
    p = mem.add(None, "she likes voice notes", "person", relation="sis", contact_name="Maya", status="active")["id"]
    event = {"kind": "memory", "message": "", "task": "t", "time": 1, "data": {"use": "sending_to", "note_ids": [p]}}
    mem.delete(None, p)
    [out] = render_events(mem, None, [event], trusted=True, enabled=True)
    assert out["message"] == "Sending to a deleted preference"
    mem2 = store(tmp_path / "b")
    q = mem2.add(None, "x", "person", relation="sis", contact_name="Maya", status="active")["id"]
    untrusted = {**event, "data": {"use": "sending_to", "note_ids": [q]}}
    assert render_events(mem2, None, [untrusted], trusted=False, enabled=True)[0]["message"] == \
        "Sending to a saved preference"


# --- M6: caps on model-supplied fields ---------------------------------------------------------------------------

def test_relation_package_and_contact_name_are_capped(tmp_path):
    mem = store(tmp_path)
    with pytest.raises(NoteError):
        mem.add(None, "hi", "person", relation="r" * 41, contact_name="Maya")
    with pytest.raises(NoteError):
        mem.add(None, "hi", "person", relation="sis", contact_name="M" * 101)
    with pytest.raises(NoteError):
        mem.add(None, "hi", "app", package="p" * 201)
    assert mem.add(None, "hi", "person", relation="r" * 40, contact_name="M" * 100)["relation"] == "r" * 40
    assert mem.add(None, "hi", "app", package="p" * 200)["package"] == "p" * 200
    nid = mem.add(None, "hi there", "person", relation="sis", contact_name="Maya")["id"]
    with pytest.raises(NoteError):
        mem.update(None, nid, contact_name="M" * 101)
    assert mem.list(None) and not [n for n in mem.list(None) if len(n["contact_name"] or "") > 100]
