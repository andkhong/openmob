"""Security review 3 Lows on the server (2026-10-18): a chat read pages in SQL and chat messages are rate limited per
socket (S3-L1); bad numbers or JSON constants answer an error instead of dropping the phone (S3-L2); a chat's origin
is the phone only for the source "phone" (S3-L3)."""

import json
import os
import time

import pytest
from conftest import FakeDriver
from test_easy_connect import srv  # noqa: F401 (the fixture)
from test_remote import FakePhone, wait_for

from openmob import phone_chats
from openmob.history import History
from openmob.phone.protocol import decode_message


def _paired(srv, email, device):  # noqa: F811
    user = srv.user(email)
    key = srv.claim(user.post("/api/pairing").json()["code"], device).json()["key"]
    phone = FakePhone(srv.ws, FakeDriver(), device_id=device, key=key)
    assert phone.welcome.wait(5)
    return user, phone, srv.manager.sessions[f"app-{device}"]


def _ask(phone, message, reply_type):
    before = sum(m["type"] == reply_type for m in phone.received)
    phone.send(message)
    assert wait_for(lambda: sum(m["type"] == reply_type for m in phone.received) > before)
    return [m for m in phone.received if m["type"] == reply_type][-1]


def _big_chat(h, acct="a", dev="app-x", tasks=60, per=20):
    chat = h.create_chat(acct, dev, "Pixel", "big")
    for t in range(tasks):
        h.record(chat, {"kind": "heard", "message": f"[phone] task {t}", "task": f"t{t}", "time": t})
        for _ in range(per - 2):
            h.record(chat, {"kind": "action", "message": "tap x", "task": f"t{t}", "time": t})
        h.record(chat, {"kind": "result", "message": "done (5 steps)", "task": f"t{t}", "time": t,
                        "data": {"final": True, "success": True, "steps": 5}})
    return chat


# --- S3-L1 ------------------------------------------------------------------------------------------------------------


def test_a_chat_read_loads_only_its_pages_events(tmp_path):
    h = History(os.path.join(tmp_path, "h.sqlite"))
    chat = _big_chat(h)
    asked = []
    original = h._q
    h._q = lambda sql, args=(): (asked.append((sql, args)), original(sql, args))[1]
    page = phone_chats.read_chat(h, "a", "app-x", {"chat_id": chat})
    loaded = [a for s, a in asked if s.lstrip().startswith("SELECT * FROM events")]
    assert len(loaded) == 1 and set(loaded[0][1:]) == {f"t{t}" for t in range(30, 60)}  # this page's turns only
    assert not any("SELECT * FROM events WHERE chat_id = ? ORDER BY id" in s for s, _ in asked)  # never the whole log
    assert [t["id"] for t in page["turns"]] == [f"t{t}" for t in range(30, 60)]
    assert page["first"] == 30 and page["more"] is True
    older = phone_chats.read_chat(h, "a", "app-x", {"chat_id": chat, "before": 30})
    assert [t["id"] for t in older["turns"]] == [f"t{t}" for t in range(30)] and older["more"] is False
    # The same turns as the whole log gives (the thread the web replays).
    whole = phone_chats._turns_from_events(h.events("a", chat), h.turns("a", chat))
    assert whole[30:] == page["turns"] and whole[:30] == older["turns"]


def test_the_rate_limit_allows_a_burst_then_five_a_second():
    now = [0.0]
    rate = phone_chats.RateLimit(clock=lambda: now[0])
    assert all(rate.allow() for _ in range(phone_chats.BURST))
    assert not rate.allow()
    now[0] += 1.0
    assert sum(rate.allow() for _ in range(10)) == 5


def test_a_flood_of_chat_messages_is_answered_rate_limited_and_the_phone_stays(srv):  # noqa: F811
    _, phone, session = _paired(srv, "flood@example.com", "phone-fl")
    seen = len(phone.received)
    for _ in range(60):
        phone.send({"type": "chats_list"})
    assert wait_for(lambda: sum(m["type"] == "chats" for m in phone.received[seen:]) == 60)
    replies = [m for m in phone.received[seen:] if m["type"] == "chats"]
    limited = [m for m in replies if m.get("error") == "rate_limited"]
    assert limited and limited[0] == {"type": "chats", "ok": False, "error": "rate_limited"}
    assert len(replies) - len(limited) >= phone_chats.BURST  # the burst was answered
    assert session.online
    time.sleep(0.5)  # tokens come back
    assert "error" not in _ask(phone, {"type": "chats_list"}, "chats")
    phone.disconnect()


# --- S3-L2 ------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("raw", ['{"type": "chats_list", "offset": Infinity}', '{"type": "x", "n": NaN}',
                                 '{"type": "x", "n": -Infinity}', '[1, 2]', '"text"'])
def test_decode_message_refuses_json_constants_and_non_objects(raw):
    with pytest.raises(ValueError):
        decode_message(raw, None)


def test_decode_message_still_reads_normal_messages():
    assert decode_message('{"type": "chats_list", "offset": 50}', None) == {"type": "chats_list", "offset": 50}


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan"), 10**30, -(10**30), "12x", None, [1]])
def test_offsets_and_limits_are_clamped(value, tmp_path):
    h = History(os.path.join(tmp_path, "h.sqlite"))
    chat = _big_chat(h, tasks=3, per=3)
    listed = phone_chats.list_chats(h, "a", "app-x", {"offset": value, "limit": value}, None)
    assert listed["type"] == "chats" and 0 <= listed["offset"] <= phone_chats.MAX_OFFSET
    read = phone_chats.read_chat(h, "a", "app-x", {"chat_id": chat, "before": value})
    assert read["type"] == "chat" and 0 <= read["first"]


def test_the_reviewers_infinity_and_huge_numbers_no_longer_drop_the_phone(srv):  # noqa: F811
    """Review 3 S3-L2 PoC (test_s3_poc.py), fixed: the socket stays and the phone gets answers."""
    _, phone, session = _paired(srv, "inf@example.com", "phone-inf")
    phone.send({"type": "chats_list", "offset": float("inf")})  # json.dumps writes Infinity: dropped, not JSON
    phone.send({"type": "chats_list", "offset": float("nan")})
    phone.send({"type": "chat_read", "chat_id": "x", "before": 10**400})
    phone.send({"type": "chats_list", "offset": 10**30})
    assert wait_for(lambda: any(m["type"] == "chat" for m in phone.received))
    assert wait_for(lambda: any(m["type"] == "chats" for m in phone.received))
    assert [m for m in phone.received if m["type"] == "chat"][-1]["error"] == "unknown"
    assert session.online
    assert _ask(phone, {"type": "chats_list"}, "chats")["type"] == "chats"
    phone.disconnect()


def test_an_exception_in_a_chat_reply_answers_bad_request(srv, monkeypatch):  # noqa: F811
    _, phone, session = _paired(srv, "boom@example.com", "phone-boom")

    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(phone_chats, "list_chats", boom)
    assert _ask(phone, {"type": "chats_list"}, "chats") == {"type": "chats", "ok": False, "error": "bad_request"}
    assert session.online
    phone.disconnect()


# --- S3-L3 ------------------------------------------------------------------------------------------------------------


def test_only_the_source_phone_is_the_phone(tmp_path):
    """Review 3 S3-L3 PoC (poc_drive_origin.py), fixed: a drive session's chat is an outside agent's."""
    h = History(os.path.join(tmp_path, "h.sqlite"))
    origins = {}
    for source in ("drive", "terminal", "phone", "dashboard", "api", "mcp", "", "something"):
        chat = h.create_chat("a", "app-x", "Pixel", f"from {source or 'nothing'}")
        if source:
            h.record(chat, {"kind": "heard", "message": f"[{source}] go", "task": f"t-{source}", "time": 1})
        origins[source] = chat
    listed = {c["id"]: c["origin"] for c in phone_chats.list_chats(h, "a", "app-x", {}, None)["chats"]}
    assert listed[origins["drive"]] == "drive"
    assert listed[origins["terminal"]] == "local"
    assert listed[origins["phone"]] == "phone"
    assert listed[origins[""]] == "unknown" and listed[origins["something"]] == "unknown"
    assert [listed[origins[s]] for s in ("dashboard", "api", "mcp")] == ["dashboard", "api", "mcp"]
    assert phone_chats._origin("phone", False) == "other_phone" and phone_chats._origin("drive", False) == "drive"
    json.dumps(listed)
