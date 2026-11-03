"""The phone reads chats (docs/design/phone-chats.md, docs/phone-protocol.md §3.6): this account's chats only, over
the device-authenticated socket, paginated, with the same (redacted) text the web shows; switching waits for a task."""

import httpx
from conftest import FakeDriver
from test_easy_connect import srv  # noqa: F401 (the fixture)
from test_remote import FakePhone, wait_for

from openmob import phone_chats


def _paired(srv, email, device):  # noqa: F811
    user = srv.user(email)
    key = srv.claim(user.post("/api/pairing").json()["code"], device).json()["key"]
    phone = FakePhone(srv.ws, FakeDriver(), device_id=device, key=key)
    assert phone.welcome.wait(5)
    session = srv.manager.sessions[f"app-{device}"]
    phone.session = session
    return user, phone, session


def _ask(phone, message, reply_type, count=None):
    before = sum(m["type"] == reply_type for m in phone.received)
    phone.send(message)
    assert wait_for(lambda: sum(m["type"] == reply_type for m in phone.received) > before)
    return [m for m in phone.received if m["type"] == reply_type][-1]


def _run(phone, text):
    phone.send({"type": "command", "text": text})
    assert wait_for(lambda: any(k == "result" and "ok" in m for k, m in phone.events))
    # The phone hears the result a moment before the server lets the task go (CI saw "busy" in between).
    session = getattr(phone, "session", None)  # set by _paired and _paired_same
    assert session is None or wait_for(lambda: session.coordinator.current is None)
    phone.events.clear()


def test_the_welcome_says_chats_and_lists_only_this_accounts_chats(srv):  # noqa: F811
    _, alice, a_session = _paired(srv, "alice@example.com", "phone-a")
    _, bob, b_session = _paired(srv, "bob@example.com", "phone-b")
    welcome = next(m for m in alice.received if m["type"] == "welcome")
    assert welcome["chats"] is True and welcome["chat"] is None
    _run(alice, "open settings")
    _run(bob, "open the camera")
    mine = _ask(alice, {"type": "chats_list"}, "chats")
    assert [c["title"] for c in mine["chats"]] == ["open settings"]
    assert mine["chats"][0]["origin"] == "phone" and mine["chats"][0]["this_phone"] is True
    assert mine["current"] == a_session.coordinator.chat_id
    bobs_chat = b_session.coordinator.chat_id
    # Another account's chat id answers exactly like a missing one.
    assert _ask(alice, {"type": "chat_read", "chat_id": bobs_chat}, "chat") == \
        {"type": "chat", "chat_id": bobs_chat, "error": "unknown"}
    assert _ask(alice, {"type": "chat_read", "chat_id": "nope"}, "chat")["error"] == "unknown"
    assert _ask(alice, {"type": "chat_open", "chat_id": bobs_chat}, "chat_opened")["error"] == "unknown"
    assert b_session.coordinator.chat_id == bobs_chat  # nothing changed for Bob
    alice.disconnect(); bob.disconnect()


def test_a_chat_reads_as_the_web_shows_it_redacted_the_same(srv):  # noqa: F811
    user, phone, session = _paired(srv, "carol@example.com", "phone-c")
    _run(phone, "pay with card 4111 1111 1111 1111 please")
    chat_id = session.coordinator.chat_id
    chat = _ask(phone, {"type": "chat_read", "chat_id": chat_id}, "chat")
    web = user.get(f"/api/chats/{chat_id}").json()
    assert len(chat["turns"]) == len(web["turns"]) == 1
    turn, web_turn = chat["turns"][0], web["turns"][0]
    assert turn["request"] == web_turn["request"]  # the same stored, redacted text
    assert "4111 1111 1111 1111" not in turn["request"]
    assert turn["outcome"] == "done" and turn["summary"] == web_turn["summary"]
    assert set(turn) == {"id", "request", "started", "finished", "outcome", "summary", "steps", "step_lines",
                         "asks", "denied", "stopped_by_owner", "question", "messages"}  # no usage, model, feedback, package
    phone.disconnect()


def test_chats_and_turns_are_paginated(srv):  # noqa: F811
    _, phone, session = _paired(srv, "dan@example.com", "phone-d")
    history, account = srv.manager.history, session.account_id
    for i in range(60):
        history.create_chat(account, session.info.id, "Pixel", f"chat {i}")
    first = _ask(phone, {"type": "chats_list"}, "chats")
    assert len(first["chats"]) == 50 and first["more"] is True
    rest = _ask(phone, {"type": "chats_list", "offset": 50, "limit": 500}, "chats")
    assert len(rest["chats"]) == 10 and rest["more"] is False
    # One chat's turns: 30 a page, newest last; `before` pages back.
    chat_id = history.create_chat(account, session.info.id, "Pixel", "many")
    for i in range(35):
        history.record(chat_id, {"kind": "heard", "message": f"[phone] task {i}", "task": f"t{i:02}", "time": 1000 + i})
    page = phone_chats.read_chat(history, account, session.info.id, {"chat_id": chat_id})
    assert len(page["turns"]) == 30 and page["more"] is True and page["turns"][-1]["request"] == "task 34"
    older = phone_chats.read_chat(history, account, session.info.id, {"chat_id": chat_id, "before": page["first"]})
    assert [t["request"] for t in older["turns"]] == [f"task {i}" for i in range(5)] and older["more"] is False
    phone.disconnect()


def test_a_revoked_phone_gets_nothing(srv):  # noqa: F811
    user, phone, session = _paired(srv, "erin@example.com", "phone-e")
    _run(phone, "open settings")
    assert srv.store.revoke_device(session.account_id, "phone-e") or user.post("/api/devices/app-phone-e/revoke").json()
    seen = len(phone.received)
    try:
        phone.send({"type": "chats_list"})
    except Exception:
        pass  # already cut off
    phone.task.result(5)  # the server cut the socket off (4401, or closed before the code arrived)
    assert phone.close_code in (4401, None)
    assert not any(m["type"] == "chats" for m in phone.received[seen:])


def test_switching_chats_waits_while_a_task_runs_and_another_phones_chat_is_read_only(srv):  # noqa: F811
    _, phone, session = _paired(srv, "fay@example.com", "phone-f")
    _run(phone, "first task")
    first = session.coordinator.chat_id
    assert _ask(phone, {"type": "chat_new"}, "chat_opened") == {"type": "chat_opened", "ok": True, "chat_id": None}
    _run(phone, "second task")
    second = session.coordinator.chat_id
    assert second != first
    session.coordinator.current = {"task": "t-running"}  # a task is running
    try:
        assert _ask(phone, {"type": "chat_open", "chat_id": first}, "chat_opened")["error"] == "busy"
        assert _ask(phone, {"type": "chat_new"}, "chat_opened")["error"] == "busy"
        assert session.coordinator.chat_id == second  # refused: nothing switched
    finally:
        session.coordinator.current = None
    assert _ask(phone, {"type": "chat_open", "chat_id": first}, "chat_opened") == \
        {"type": "chat_opened", "ok": True, "chat_id": first}
    assert session.coordinator.chat_id == first
    # A chat with the account's other phone can be read, not continued here.
    other = srv.manager.history.create_chat(session.account_id, "app-other", "Pixel", "on the tablet")
    srv.manager.history.record(other, {"kind": "heard", "message": "[phone] on the tablet", "task": "t-other", "time": 1})
    assert _ask(phone, {"type": "chat_read", "chat_id": other}, "chat")["this_phone"] is False
    assert _ask(phone, {"type": "chat_open", "chat_id": other}, "chat_opened")["error"] == "other_phone"
    listed = {c["id"]: c for c in _ask(phone, {"type": "chats_list"}, "chats")["chats"]}
    assert listed[other]["origin"] == "other_phone"
    phone.disconnect()


def test_a_dashboard_chat_is_labelled_so(srv):  # noqa: F811
    user, phone, session = _paired(srv, "gil@example.com", "phone-g")
    r = user.post(f"/api/devices/{session.info.id}/command", json={"text": "from the web"})
    assert r.status_code == 200, r.text
    assert wait_for(lambda: session.coordinator.chat_id is not None)
    chats = _ask(phone, {"type": "chats_list"}, "chats")["chats"]
    assert chats[0]["origin"] == "dashboard"
    phone.disconnect()
    httpx.Client  # noqa: B018


# --- rename and delete (owner, 2026-10-17) ------------------------------------------------------------------------


def _paired_same(srv, user, device):  # noqa: F811
    key = srv.claim(user.post("/api/pairing").json()["code"], device).json()["key"]
    phone = FakePhone(srv.ws, FakeDriver(), device_id=device, key=key)
    assert phone.welcome.wait(5)
    phone.session = srv.manager.sessions[f"app-{device}"]
    return phone


def test_rename_and_delete_are_this_accounts_only_and_reach_the_accounts_other_phones(srv):  # noqa: F811
    user, phone, session = _paired(srv, "hal@example.com", "phone-h")
    other_phone = _paired_same(srv, user, "phone-h2")
    assert srv.store.trust_device(session.account_id, "phone-h2")  # a trusted phone hears of every chat
    _, bob, b_session = _paired(srv, "bob2@example.com", "phone-b2")
    _run(phone, "open settings")
    chat_id = session.coordinator.chat_id
    _run(bob, "open the camera")
    bobs = b_session.coordinator.chat_id
    # Another account's chat answers like a missing one; nothing of Bob's changes.
    assert _ask(phone, {"type": "chat_rename", "chat_id": bobs, "title": "mine now"}, "chat_renamed")["error"] == "unknown"
    assert _ask(phone, {"type": "chat_delete", "chat_id": bobs}, "chat_deleted")["error"] == "unknown"
    assert srv.manager.history.chat(b_session.account_id, bobs)["title"] == "open the camera"
    assert _ask(phone, {"type": "chat_rename", "chat_id": chat_id, "title": "   "}, "chat_renamed")["error"] == "bad_title"
    renamed = _ask(phone, {"type": "chat_rename", "chat_id": chat_id, "title": "  Settings  " + "x" * 200}, "chat_renamed")
    assert renamed["ok"] and renamed["title"].startswith("Settings x") and len(renamed["title"]) == 120
    assert user.get(f"/api/chats/{chat_id}").json()["title"] == renamed["title"]  # the same as the web's
    assert wait_for(lambda: any(m["type"] == "chat_renamed" for m in other_phone.received))  # pushed to the other phone
    deleted = _ask(phone, {"type": "chat_delete", "chat_id": chat_id}, "chat_deleted")
    assert deleted == {"type": "chat_deleted", "ok": True, "chat_id": chat_id}
    assert session.coordinator.chat_id is None  # Home's chat gone: a fresh chat
    assert user.get(f"/api/chats/{chat_id}").status_code == 404
    assert wait_for(lambda: any(m["type"] == "chat_deleted" for m in other_phone.received))
    phone.disconnect(); other_phone.disconnect(); bob.disconnect()


def test_a_chat_with_a_running_task_cant_be_deleted_on_the_web_or_the_phone(srv):  # noqa: F811
    user, phone, session = _paired(srv, "ivy@example.com", "phone-i")
    _run(phone, "open settings")
    chat_id = session.coordinator.chat_id
    session.coordinator.current = {"task": "t-running"}
    try:
        r = user.delete(f"/api/chats/{chat_id}")
        assert r.status_code == 409 and r.json()["detail"] == "Stop the task first."
        assert _ask(phone, {"type": "chat_delete", "chat_id": chat_id}, "chat_deleted")["error"] == "busy"
        assert srv.manager.history.chat(session.account_id, chat_id) is not None
    finally:
        session.coordinator.current = None
    assert user.delete(f"/api/chats/{chat_id}").json() == {"ok": True}
    phone.disconnect()


def test_rename_and_delete_recheck_the_pairing(srv):  # noqa: F811
    user, phone, session = _paired(srv, "jo@example.com", "phone-j")
    _run(phone, "open settings")
    chat_id = session.coordinator.chat_id
    srv.store.revoke_device(session.account_id, "phone-j")
    seen = len(phone.received)
    try:
        phone.send({"type": "chat_delete", "chat_id": chat_id})
    except Exception:
        pass
    phone.task.result(5)
    assert not any(m["type"] == "chat_deleted" for m in phone.received[seen:])
    assert srv.manager.history.chat(session.account_id, chat_id) is not None


def test_a_rename_or_delete_on_the_web_reaches_the_accounts_phones_and_no_one_elses(srv):  # noqa: F811
    user, phone, session = _paired(srv, "kim@example.com", "phone-k")
    _, bob, _ = _paired(srv, "bob3@example.com", "phone-b3")
    _run(phone, "open settings")
    chat_id = session.coordinator.chat_id
    assert user.patch(f"/api/chats/{chat_id}", json={"title": "  Morning   settings "}).json() == {"ok": True}
    assert wait_for(lambda: {"type": "chat_renamed", "ok": True, "chat_id": chat_id, "title": "Morning settings"}
                    in phone.received)
    assert user.delete(f"/api/chats/{chat_id}").json() == {"ok": True}
    assert wait_for(lambda: {"type": "chat_deleted", "ok": True, "chat_id": chat_id} in phone.received)
    assert session.coordinator.chat_id is None  # the phone's Home was showing it: a fresh chat
    assert not any(m["type"] in ("chat_renamed", "chat_deleted") for m in bob.received)  # another account's phone
    phone.disconnect(); bob.disconnect()


# --- an untrusted phone sees only its own chats (review 3 K3-M3; owner 2026-10-18 "own chats until trusted") -------


def test_an_untrusted_phone_lists_reads_opens_renames_and_deletes_only_its_own_chats(srv):  # noqa: F811
    user, first, f_session = _paired(srv, "lee@example.com", "phone-l")  # the account's first phone: trusted
    second = _paired_same(srv, user, "phone-l2")  # paired later: not trusted
    s_session = srv.manager.sessions["app-phone-l2"]
    acct, history = f_session.account_id, srv.manager.history
    assert not srv.store.trusted_for_approvals("phone-l2")
    _run(first, "message the bank")
    theirs = f_session.coordinator.chat_id
    web = history.create_chat(acct, "", "", "from an API key")  # with no phone
    _run(second, "open settings")
    mine = s_session.coordinator.chat_id
    listed = _ask(second, {"type": "chats_list"}, "chats")
    assert [c["id"] for c in listed["chats"]] == [mine] and listed["this_phone_only"] is True
    # Search covers only its own chats too.
    assert _ask(second, {"type": "chats_list", "q": "bank"}, "chats")["chats"] == []
    # Another phone's chat (and one with no phone) answers exactly like a missing chat, for every message.
    for other in (theirs, web):
        assert _ask(second, {"type": "chat_read", "chat_id": other}, "chat") == \
            _ask(second, {"type": "chat_read", "chat_id": "missing"}, "chat") | {"chat_id": other}
        assert _ask(second, {"type": "chat_open", "chat_id": other}, "chat_opened") == \
            {"type": "chat_opened", "ok": False, "chat_id": other, "error": "unknown"}
        assert _ask(second, {"type": "chat_rename", "chat_id": other, "title": "mine"}, "chat_renamed") == \
            {"type": "chat_renamed", "ok": False, "chat_id": other, "error": "unknown"}
        assert _ask(second, {"type": "chat_delete", "chat_id": other}, "chat_deleted") == \
            {"type": "chat_deleted", "ok": False, "chat_id": other, "error": "unknown"}
    assert history.chat(acct, theirs)["title"] == "message the bank" and history.chat(acct, web) is not None
    # Its own chat: all of it works.
    assert _ask(second, {"type": "chat_read", "chat_id": mine}, "chat")["this_phone"] is True
    assert _ask(second, {"type": "chat_rename", "chat_id": mine, "title": "Mine"}, "chat_renamed")["ok"] is True
    # The trusted phone keeps the account's whole view (and hears of the rename); the dashboard too.
    full = _ask(first, {"type": "chats_list"}, "chats")
    assert {theirs, web, mine} <= {c["id"] for c in full["chats"]} and full["this_phone_only"] is False
    assert _ask(first, {"type": "chat_read", "chat_id": mine}, "chat")["title"] == "Mine"
    assert wait_for(lambda: any(m.get("chat_id") == mine for m in first.received if m["type"] == "chat_renamed"))
    assert {theirs, web, mine} <= {c["id"] for c in user.get("/api/chats").json()}
    assert _ask(second, {"type": "chat_delete", "chat_id": mine}, "chat_deleted")["ok"] is True
    # Once the owner trusts it, it sees the account's chats.
    assert srv.store.trust_device(acct, "phone-l2")
    after = _ask(second, {"type": "chats_list"}, "chats")
    assert {theirs, web} <= {c["id"] for c in after["chats"]} and after["this_phone_only"] is False
    first.disconnect(); second.disconnect()


def test_an_untrusted_phone_hears_of_renames_and_deletes_only_for_its_own_chats(srv):  # noqa: F811
    user, first, f_session = _paired(srv, "max@example.com", "phone-m")
    second = _paired_same(srv, user, "phone-m2")
    s_session = srv.manager.sessions["app-phone-m2"]
    _run(first, "message the bank")
    theirs = f_session.coordinator.chat_id
    _run(second, "open settings")
    mine = s_session.coordinator.chat_id
    assert user.patch(f"/api/chats/{theirs}", json={"title": "Bank secrets"}).json() == {"ok": True}
    assert user.patch(f"/api/chats/{mine}", json={"title": "My settings"}).json() == {"ok": True}
    assert wait_for(lambda: {"type": "chat_renamed", "ok": True, "chat_id": mine, "title": "My settings"} in second.received)
    assert user.delete(f"/api/chats/{theirs}").json() == {"ok": True}
    assert user.delete(f"/api/chats/{mine}").json() == {"ok": True}
    assert wait_for(lambda: {"type": "chat_deleted", "ok": True, "chat_id": mine} in second.received)
    assert not any(m.get("chat_id") == theirs for m in second.received)  # not its chat: nothing, not even the id
    assert {"type": "chat_renamed", "ok": True, "chat_id": theirs, "title": "Bank secrets"} in first.received
    first.disconnect(); second.disconnect()
