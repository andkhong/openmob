"""2026-10-18 (owner): the phone's mode is per device, set on the dashboard, for every task source and never above
the phone's ceiling; plus the chat fixes (live switch from the web, search over all chats, the owner's corrections and
answers in the thread, real origins, interrupted turns)."""

import time

from test_api_v1 import api, run_task, wait_status  # noqa: F401 (the fixture)
from test_remote import wait_for

from openmob import phone_chats


def _turn_mode(api, user, request):  # noqa: F811
    history = api.manager.history
    acct = api.manager.get(user.device).account_id

    def find():
        for chat in history.list_chats(acct):
            for t in history.turns(acct, chat["id"]):
                if t["request"] == request and t.get("finished"):
                    return t
        return None
    assert wait_for(find, timeout=8)
    return find()["mode"]


def test_the_dashboards_mode_applies_to_phone_web_and_api_tasks(api):  # noqa: F811
    a = api.alice
    r = a.console.patch(f"/api/devices/{a.device}/permissions", json={"default_mode": "ask"})  # a tightening: applied
    assert r.status_code == 200 and r.json()["status"] == "applied"
    a.phone.send({"type": "command", "text": "from the phone"})
    assert _turn_mode(api, a, "from the phone") == "ask"
    a.console.post(f"/api/devices/{a.device}/command", json={"text": "from the web"})
    assert _turn_mode(api, a, "from the web") == "ask"
    task = run_task(a, "from the api")
    wait_status(a, task["id"], "succeeded", "failed")
    assert _turn_mode(api, a, "from the api") == "ask"


def test_the_mode_never_goes_above_the_phones_ceiling_without_its_approval(api):  # noqa: F811
    a = api.alice
    before = a.console.get(f"/api/devices/{a.device}/permissions").json()
    r = a.console.patch(f"/api/devices/{a.device}/permissions", json={"default_mode": "trusted", "ceiling": "trusted"})
    assert r.status_code == 202 and r.json()["code"] == "needs_phone_approval"  # signed on the phone, or nothing
    after = a.console.get(f"/api/devices/{a.device}/permissions").json()
    assert after["ceiling"] == before["ceiling"] and after["default_mode"] == before["default_mode"]
    # A task asking for more than the ceiling is refused, from any source.
    assert a.console.post(f"/api/devices/{a.device}/command",
                          json={"text": "x", "permission_mode": "trusted"}).status_code == 403


def test_a_web_new_chat_or_open_chat_reaches_the_phone(api):  # noqa: F811
    a = api.alice
    a.phone.send({"type": "command", "text": "first"})
    assert _turn_mode(api, a, "first")
    first = api.manager.get(a.device).coordinator.chat_id
    assert a.console.post(f"/api/devices/{a.device}/chat/new").status_code == 200
    assert wait_for(lambda: any(m["type"] == "chat_opened" and m["chat_id"] is None for m in a.phone.received))
    assert a.console.post(f"/api/devices/{a.device}/chat/open", json={"chat_id": first}).status_code == 200
    assert wait_for(lambda: any(m["type"] == "chat_opened" and m["chat_id"] == first for m in a.phone.received))


def test_search_covers_all_chats_and_only_this_accounts(api):  # noqa: F811
    history, a, b = api.manager.history, api.alice, api.bob
    acct_a = api.manager.get(a.device).account_id
    acct_b = api.manager.get(b.device).account_id
    for i in range(70):
        history.create_chat(acct_a, a.device, "Pixel", f"chat {i}")
    history.create_chat(acct_a, a.device, "Pixel", "Pharmacy 50% off_today")
    history.create_chat(acct_b, b.device, "Pixel", "pharmacy for bob")
    found = phone_chats.list_chats(history, acct_a, a.device, {"q": "PHARMACY"}, None)
    assert [c["title"] for c in found["chats"]] == ["Pharmacy 50% off_today"]  # case-insensitive, not Bob's
    assert phone_chats.list_chats(history, acct_a, a.device, {"q": "50%"}, None)["chats"][0]["title"].startswith("Pharmacy")
    assert phone_chats.list_chats(history, acct_a, a.device, {"q": "%"}, None)["chats"][0]["title"].startswith("Pharmacy")
    assert phone_chats.list_chats(history, acct_a, a.device, {"q": "_t"}, None)["chats"][0]["title"].startswith("Pharmacy")
    old = phone_chats.list_chats(history, acct_a, a.device, {"q": "chat 1"}, None)["chats"]
    assert {c["title"] for c in old} >= {"chat 1", "chat 10", "chat 19"}  # deep in the history, past page one
    assert len(phone_chats.list_chats(history, acct_a, a.device, {"q": "x" * 500}, None)["chats"]) == 0
    # Over the socket too.
    a.phone.send({"type": "chats_list", "q": "pharmacy"})
    assert wait_for(lambda: any(m["type"] == "chats" and m.get("q") == "pharmacy" for m in a.phone.received))
    reply = [m for m in a.phone.received if m["type"] == "chats" and m.get("q") == "pharmacy"][-1]
    assert [c["title"] for c in reply["chats"]] == ["Pharmacy 50% off_today"]


def test_the_thread_has_the_owners_corrections_and_answers_and_past_questions(api):  # noqa: F811
    history, a = api.manager.history, api.alice
    acct = api.manager.get(a.device).account_id
    chat = history.create_chat(acct, a.device, "Pixel", "play jazz")
    t = 1000.0
    for kind, message, data in [
        ("heard", "[phone] play jazz", None),
        ("action", "launch_app: Spotify", None),
        ("jev", "jev: tapped Play", None),
        ("correction", "[phone] the second playlist", None),
        ("question", "Kind of Blue or a playlist?", None),
        ("heard", "[phone] the playlist", None),
        ("result", "Playing (2 steps)", {"final": True, "success": True, "steps": 2}),
    ]:
        t += 1
        history.record(chat, {"kind": kind, "message": message, "task": "t1", "time": t, **({"data": data} if data else {})})
    turn = phone_chats.read_chat(history, acct, a.device, {"chat_id": chat})["turns"][0]
    assert [m["kind"] for m in turn["messages"]] == ["correction", "question", "answer"]
    assert [m["text"] for m in turn["messages"]] == ["the second playlist", "Kind of Blue or a playlist?", "the playlist"]
    assert turn["step_lines"] == ["launch_app: Spotify"]  # the web hides Jev's lines; so does the phone
    assert turn["question"] == "" and turn["outcome"] == "done"


def test_a_turn_cut_off_by_a_restart_is_interrupted_not_running(api):  # noqa: F811
    history, a = api.manager.history, api.alice
    acct = api.manager.get(a.device).account_id
    chat = history.create_chat(acct, a.device, "Pixel", "half done")
    history.record(chat, {"kind": "heard", "message": "[phone] half done", "task": "t-gone", "time": time.time()})
    history.record(chat, {"kind": "action", "message": "tap: Next", "task": "t-gone", "time": time.time()})
    assert phone_chats.read_chat(history, acct, a.device, {"chat_id": chat})["turns"][0]["outcome"] == "interrupted"
    still = phone_chats.read_chat(history, acct, a.device, {"chat_id": chat}, active={"t-gone"})
    assert still["turns"][0]["outcome"] == "running"


def test_api_and_mcp_chats_carry_their_origin(api):  # noqa: F811
    history, a = api.manager.history, api.alice
    acct = api.manager.get(a.device).account_id
    for source in ("api", "mcp", "dashboard", "phone"):
        chat = history.create_chat(acct, a.device, "Pixel", f"from {source}")
        history.record(chat, {"kind": "heard", "message": f"[{source}] from {source}", "task": f"t-{source}", "time": time.time()})
    other = history.create_chat(acct, "app-other", "Pixel", "other phone")
    history.record(other, {"kind": "heard", "message": "[phone] other phone", "task": "t-o", "time": time.time()})
    listed = {c["title"]: c for c in phone_chats.list_chats(history, acct, a.device, {}, None)["chats"]}
    assert listed["from api"]["origin"] == "api" and listed["from mcp"]["origin"] == "mcp"
    assert listed["from dashboard"]["origin"] == "dashboard" and listed["from phone"]["origin"] == "phone"
    assert listed["other phone"]["origin"] == "other_phone" and listed["other phone"]["this_phone"] is False
    # A real API task records the source "api".
    task = run_task(a, "an api task")
    wait_status(a, task["id"], "succeeded", "failed")
    listed = {c["title"]: c for c in phone_chats.list_chats(history, acct, a.device, {}, None)["chats"]}
    assert any(c["origin"] == "api" for c in listed.values())
