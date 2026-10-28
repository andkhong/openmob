"""Preferences memory on the phone (Task 7, docs/phone-protocol.md §3.9): the "What OpenMob remembers" page talks to
the server over the device-authenticated socket. Only a phone trusted for approvals sees or changes notes, trust is
re-checked on every message, and the switch off answers `denied` like an untrusted phone."""

import json

from conftest import FakeDriver
from test_easy_connect import srv  # noqa: F401 (the fixture)
from test_remote import FakePhone, wait_for

from openmob.memory import Memory


def _on(srv, tmp_path):  # noqa: F811
    srv.manager.cfg.memory = True
    srv.manager.memory = Memory(tmp_path / "memory.sqlite")
    return srv.manager.memory


def _pair(srv, user, device):  # noqa: F811
    key = srv.claim(user.post("/api/pairing").json()["code"], device).json()["key"]
    phone = FakePhone(srv.ws, FakeDriver(), device_id=device, key=key)
    assert phone.welcome.wait(5)
    return phone, srv.manager.sessions[f"app-{device}"]


def _welcome(phone) -> dict:
    return next(m for m in phone.received if m["type"] == "welcome")


def _ask(phone, message) -> dict:
    before = sum(m["type"] == "memory" for m in phone.received)
    phone.send(message)
    assert wait_for(lambda: sum(m["type"] == "memory" for m in phone.received) > before)
    return [m for m in phone.received if m["type"] == "memory"][-1]


def _untrust(store, device_id):
    """The phone loses its trust for approvals (as a re-pair without proving its key leaves it)."""
    with store._lock:
        store._refresh()
        store._data["devices"][device_id]["trusted"] = False
        store._save()


def test_a_trusted_phone_lists_edits_confirms_dismisses_and_deletes(srv, tmp_path):  # noqa: F811
    mem = _on(srv, tmp_path)
    user = srv.user("tia@example.com")
    phone, session = _pair(srv, user, "phone-t")  # the account's first phone: trusted
    assert _welcome(phone)["memory"] is True
    acct = session.account_id
    soda = mem.add(acct, "My favorite soda is Diet Coke", "about_you", status="active")
    wife = mem.add(acct, "texts in the evening", "person", relation="wife", contact_name="Sam", status="active")
    idea = mem.add(acct, "Prefers the app over the browser", "about_you")  # a proposal
    stale = mem.add(acct, "Likes window seats", "about_you")

    listed = _ask(phone, {"type": "memory_list"})
    assert {n["id"] for n in listed["notes"]} == {soda["id"], wife["id"]}
    assert {n["id"] for n in listed["proposed"]} == {idea["id"], stale["id"]}
    person = next(n for n in listed["notes"] if n["id"] == wife["id"])
    assert set(person) == {"id", "kind", "package", "relation", "contact_name", "text", "status"}
    assert (person["relation"], person["contact_name"]) == ("wife", "Sam")

    edited = _ask(phone, {"type": "memory_edit", "id": soda["id"], "text": "My favorite soda is Coke Zero"})
    assert edited["ok"] is True
    assert next(n for n in edited["notes"] if n["id"] == soda["id"])["text"] == "My favorite soda is Coke Zero"
    renamed = _ask(phone, {"type": "memory_edit", "id": wife["id"], "contact_name": "Sam K"})
    assert next(n for n in renamed["notes"] if n["id"] == wife["id"])["contact_name"] == "Sam K"
    # A number as a contact name is refused; the note stays as it was.
    bad = _ask(phone, {"type": "memory_edit", "id": wife["id"], "contact_name": "+1 555 0100"})
    assert bad["ok"] is False and bad["error"] == "bad_note"
    assert mem.get(acct, wife["id"])["contact_name"] == "Sam K"

    saved = _ask(phone, {"type": "memory_confirm", "id": idea["id"]})
    assert saved["ok"] is True and idea["id"] in {n["id"] for n in saved["notes"]}
    # A stale Dismiss on a note saved since leaves it saved.
    late = _ask(phone, {"type": "memory_dismiss", "id": idea["id"]})
    assert late["ok"] is False and late["error"] == "not_proposed"
    assert mem.get(acct, idea["id"])["status"] == "active"
    gone = _ask(phone, {"type": "memory_dismiss", "id": stale["id"]})
    assert gone["ok"] is True and gone["proposed"] == [] and mem.get(acct, stale["id"]) is None

    deleted = _ask(phone, {"type": "memory_delete", "id": soda["id"]})
    assert deleted["ok"] is True and soda["id"] not in {n["id"] for n in deleted["notes"]}
    assert _ask(phone, {"type": "memory_delete", "id": soda["id"]})["error"] == "unknown"
    assert _ask(phone, {"type": "memory_edit", "id": {"x": 1}})["error"] == "bad_request"

    # Another account's note answers like a missing one and is not touched.
    bob = srv.user("bob-m@example.com")
    b_phone, b_session = _pair(srv, bob, "phone-bm")
    theirs = mem.add(b_session.account_id, "Bob likes tea", "about_you", status="active")
    for kind in ("memory_edit", "memory_delete", "memory_confirm", "memory_dismiss"):
        assert _ask(phone, {"type": kind, "id": theirs["id"], "text": "mine now"})["error"] == "unknown", kind
    assert mem.get(b_session.account_id, theirs["id"])["text"] == "Bob likes tea"
    assert _ask(b_phone, {"type": "memory_list"})["notes"][0]["id"] == theirs["id"]

    # The audit log names notes by id only.
    rows = json.dumps(srv.ledger.audit_log(account_id=acct))
    assert f"note {soda['id']}" in rows and "memory.confirmed" in rows
    for text in ("Coke", "Sam", "window", "browser", "evening"):
        assert text not in rows
    phone.disconnect(); b_phone.disconnect()


def test_an_untrusted_phone_is_denied_and_its_welcome_says_no_memory(srv, tmp_path):  # noqa: F811
    mem = _on(srv, tmp_path)
    user = srv.user("uma@example.com")
    first, session = _pair(srv, user, "phone-u1")
    second, _ = _pair(srv, user, "phone-u2")  # paired later: not trusted
    assert not srv.store.trusted_for_approvals("phone-u2")
    assert _welcome(first)["memory"] is True and _welcome(second)["memory"] is False
    note = mem.add(session.account_id, "My favorite soda is Diet Coke", "about_you", status="active")
    idea = mem.add(session.account_id, "Likes window seats", "about_you")
    for message in ({"type": "memory_list"}, {"type": "memory_edit", "id": note["id"], "text": "changed"},
                    {"type": "memory_delete", "id": note["id"]}, {"type": "memory_confirm", "id": idea["id"]},
                    {"type": "memory_dismiss", "id": idea["id"]}):
        assert _ask(second, message) == {"type": "memory", "denied": True}, message
    assert mem.get(session.account_id, note["id"])["text"] == "My favorite soda is Diet Coke"
    assert mem.get(session.account_id, idea["id"])["status"] == "proposed"
    assert "Diet Coke" not in json.dumps(second.received)
    first.disconnect(); second.disconnect()


def test_trust_lost_mid_session_denies_the_next_message(srv, tmp_path):  # noqa: F811
    mem = _on(srv, tmp_path)
    user = srv.user("val@example.com")
    phone, session = _pair(srv, user, "phone-v")
    note = mem.add(session.account_id, "Use the second account", "about_you", status="active")
    assert _ask(phone, {"type": "memory_list"})["notes"][0]["id"] == note["id"]
    _untrust(srv.store, "phone-v")
    assert _ask(phone, {"type": "memory_list"}) == {"type": "memory", "denied": True}
    assert _ask(phone, {"type": "memory_delete", "id": note["id"]}) == {"type": "memory", "denied": True}
    assert mem.get(session.account_id, note["id"]) is not None
    phone.disconnect()


def test_switch_off_denies_and_the_welcome_says_no_memory(srv, tmp_path):  # noqa: F811
    mem = _on(srv, tmp_path)
    user = srv.user("wes@example.com")
    phone, session = _pair(srv, user, "phone-w")
    note = mem.add(session.account_id, "Use the second account", "about_you", status="active")
    srv.manager.cfg.memory = False  # switched off while connected
    assert _ask(phone, {"type": "memory_list"}) == {"type": "memory", "denied": True}
    assert _ask(phone, {"type": "memory_delete", "id": note["id"]}) == {"type": "memory", "denied": True}
    assert mem.get(session.account_id, note["id"]) is not None  # data kept
    phone.disconnect()
    again, _ = _pair(srv, user, "phone-w2")
    assert _welcome(again)["memory"] is False
    again.disconnect()


def test_a_revoked_phone_is_cut_off_before_memory_is_read(srv, tmp_path):  # noqa: F811
    mem = _on(srv, tmp_path)
    user = srv.user("xia@example.com")
    phone, session = _pair(srv, user, "phone-x")
    mem.add(session.account_id, "Use the second account", "about_you", status="active")
    assert srv.store.revoke_device(session.account_id, "phone-x")
    seen = len(phone.received)
    try:
        phone.send({"type": "memory_list"})
    except Exception:
        pass  # already cut off
    phone.task.result(5)
    assert phone.close_code in (4401, None)
    assert not any(m["type"] == "memory" for m in phone.received[seen:])


def test_memory_messages_share_the_sockets_rate_limit(srv, tmp_path):  # noqa: F811
    _on(srv, tmp_path)
    user = srv.user("yan@example.com")
    phone, _ = _pair(srv, user, "phone-y")
    for _ in range(60):
        phone.send({"type": "memory_list"})
    assert wait_for(lambda: any(m.get("error") == "rate_limited" for m in phone.received if m["type"] == "memory"))
    limited = next(m for m in phone.received if m.get("error") == "rate_limited")
    assert limited == {"type": "memory", "ok": False, "error": "rate_limited"}
    phone.disconnect()
