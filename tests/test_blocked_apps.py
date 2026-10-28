"""Owner-added blocked apps (owner, 2026-10-20; docs/design/blocked-apps.md), the server's side.

The phone holds and enforces the list (its gatekeeper; the shared scenarios tagged blocked_apps run the rule through
both engines). The server only keeps the phone's reported copy and the dashboard's pending requests, and can only
ever ask to add: there is no unblock anywhere on the server. A task the phone stops at a blocked app ends
`cancelled` / `blocked_app` (a stopped state, not failed), and its summary names the app for the thread.
"""
import httpx
import pytest
from test_api_v1 import api, run_task, wait_status  # noqa: F401  (api: a fixture)
from test_remote import wait_for

from openmob import blocked_apps
from openmob.blocked_apps import BlockedAppsStore, InvalidPackages

GMAIL = "com.google.android.gm"


# --- validation -------------------------------------------------------------------------------


def test_package_names_are_validated_and_capped():
    assert blocked_apps.packages(["com.whatsapp", GMAIL, "com.whatsapp"]) == ["com.whatsapp", GMAIL]
    for bad in (None, "com.whatsapp", {"packages": []}, [], ["com"], ["com.what sapp"], ["../etc/passwd"],
                ["com.whatsapp", 3], ["cоm.whatsapp"],  # a Cyrillic look-alike
                ["com." + "a" * 300], ["1com.x"], ["com..x"], ["com.x."],
                [f"com.example.app{i}" for i in range(201)]):
        with pytest.raises(InvalidPackages):
            blocked_apps.packages(bad)
    assert blocked_apps.packages([], allow_empty=True) == []
    assert len(blocked_apps.packages([f"com.example.app{i}" for i in range(200)])) == 200


def test_a_phone_label_is_one_short_printable_line():
    assert blocked_apps.label("Gmail") == "Gmail"
    assert blocked_apps.label("Gm\nail‮\u0000 " + "x" * 100) == "Gm ail" + "" + " " + "x" * 53
    assert blocked_apps.label(None) == "" and blocked_apps.label(5) == ""


def test_the_store_keeps_requests_until_the_phone_reports_them(tmp_path):
    store = BlockedAppsStore(tmp_path / "b.json")
    assert store.request("acct", "app-1", ["com.whatsapp", GMAIL]) == ["com.whatsapp", GMAIL]
    assert store.report("acct", "app-1", ["com.whatsapp"]) == [GMAIL]
    again = BlockedAppsStore(tmp_path / "b.json")  # survives a restart
    view = again.view("acct", "app-1")
    assert view["packages"] == ["com.whatsapp"] and view["pending"] == [GMAIL] and view["reported_at"]
    assert again.view("other", "app-1")["packages"] == []  # per account
    with pytest.raises(InvalidPackages):
        again.request("acct", "app-1", [f"com.example.app{i}" for i in range(199)])
    again.forget("acct", "app-1")
    assert again.view("acct", "app-1") == {"packages": [], "reported_at": None, "pending": [], "apps": []}


# --- the dashboard ------------------------------------------------------------------------------


def _blocks(phone):
    return [m for m in phone.received if m.get("type") == "block_apps"]


def test_the_dashboard_can_add_a_block_and_the_phone_gets_it(api):
    alice = api.alice
    r = alice.console.post(f"/api/devices/{alice.device}/blocked-apps", json={"packages": [GMAIL]})
    assert r.status_code == 200, r.text
    assert r.json()["pending"] == [GMAIL] and r.json()["packages"] == []
    assert wait_for(lambda: _blocks(alice.phone))
    assert _blocks(alice.phone)[-1] == {"type": "block_apps", "packages": [GMAIL]}
    # The phone adds it and reports its list: the dashboard shows the phone's copy, nothing pending.
    alice.phone.send({"type": "blocked_apps", "packages": ["com.whatsapp", GMAIL]})
    assert wait_for(lambda: alice.console.get(f"/api/devices/{alice.device}/blocked-apps").json()["pending"] == [])
    view = alice.console.get(f"/api/devices/{alice.device}/blocked-apps").json()
    assert view["packages"] == ["com.whatsapp", GMAIL] and view["online"] is True


def test_the_dashboard_can_never_unblock(api):
    """Unblocking is only on the phone, with its screen lock: no route removes, a request only adds, and the
    message the server sends has no removal field."""
    alice = api.alice
    url = f"/api/devices/{alice.device}/blocked-apps"
    alice.phone.send({"type": "blocked_apps", "packages": [GMAIL]})
    assert wait_for(lambda: alice.console.get(url).json()["packages"] == [GMAIL])
    for method in ("DELETE", "PUT", "PATCH"):
        assert alice.console.request(method, url, json={"packages": [GMAIL]}).status_code == 405
    assert alice.console.request("DELETE", f"{url}/{GMAIL}").status_code in (404, 405)
    for body in ({"packages": []}, {"unblock": [GMAIL]}, {"packages": [GMAIL], "remove": [GMAIL]}):
        alice.console.post(url, json=body)
    assert all(set(m) == {"type", "packages"} and m["packages"] for m in _blocks(alice.phone))
    assert alice.console.get(url).json()["packages"] == [GMAIL]  # still the phone's own list


def test_a_malformed_or_oversized_request_is_refused_whole(api):
    alice = api.alice
    url = f"/api/devices/{alice.device}/blocked-apps"
    for body in ({"packages": "com.whatsapp"}, {"packages": [GMAIL, "not a package"]}, {"packages": []},
                 {"packages": [f"com.example.app{i}" for i in range(201)]}, [GMAIL], {}):
        r = alice.console.post(url, json=body)
        assert r.status_code == 400 and r.json()["code"] == "invalid_packages", (body, r.text)
    r = alice.console.post(url, content=b"{not json", headers={"Content-Type": "application/json"})
    assert r.status_code == 400
    assert not _blocks(alice.phone) and alice.console.get(url).json()["pending"] == []


def test_only_the_owner_and_only_from_the_dashboard_itself(api):
    url = f"/api/devices/{api.alice.device}/blocked-apps"
    assert api.bob.console.get(url).status_code == 404
    assert api.bob.console.post(url, json={"packages": [GMAIL]}).status_code == 404
    assert httpx.get(api.base + url).status_code == 401
    r = api.alice.console.post(url, json={"packages": [GMAIL]}, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    r = api.alice.console.post(url, json={"packages": [GMAIL]}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert not _blocks(api.alice.phone)
    # An API key (developer API) has no route to it either.
    assert api.alice.v1.post(f"/v1/devices/{api.alice.device}/blocked-apps", json={"packages": [GMAIL]}).status_code == 404


def test_a_pending_request_goes_again_on_the_next_connection_and_a_report_never_bounces(api):
    alice = api.alice
    session = api.manager.get(alice.device)
    url = f"/api/devices/{alice.device}/blocked-apps"
    alice.console.post(url, json={"packages": [GMAIL]})
    assert wait_for(lambda: len(_blocks(alice.phone)) == 1)
    # The phone refused it (say, its list is full) and reported without it: nothing is re-sent from the report...
    alice.phone.send({"type": "blocked_apps", "packages": []})
    assert wait_for(lambda: alice.console.get(url).json()["reported_at"])
    assert len(_blocks(alice.phone)) == 1 and alice.console.get(url).json()["pending"] == [GMAIL]
    api.manager.resume(session)  # ...only when the phone connects again
    assert wait_for(lambda: len(_blocks(alice.phone)) == 2)


def test_a_malformed_phone_report_is_dropped(api):
    alice = api.alice
    alice.phone.send({"type": "blocked_apps", "packages": ["com.whatsapp"]})
    url = f"/api/devices/{alice.device}/blocked-apps"
    assert wait_for(lambda: alice.console.get(url).json()["packages"] == ["com.whatsapp"])
    for bad in ({"packages": "x"}, {"packages": ["not a package"]},
                {"packages": [f"com.example.app{i}" for i in range(201)]}):
        alice.phone.send({"type": "blocked_apps", **bad})
    alice.phone.send({"type": "chats_list", "offset": 0, "limit": 1})  # a round trip: the reports were handled
    assert wait_for(lambda: any(m["type"] == "chats" for m in alice.phone.received))
    assert alice.console.get(url).json()["packages"] == ["com.whatsapp"]


# --- a task that reaches a blocked app -------------------------------------------------------------


def test_the_phone_stops_a_task_at_a_blocked_app_as_stopped_not_failed(api):
    alice = api.alice
    task = run_task(alice, "wait for the page")
    wait_status(alice, task["id"], "running")
    alice.phone.send({"type": "task_stop", "reason": "blocked_app", "package": GMAIL, "label": "Gmail"})
    done = wait_status(alice, task["id"], "cancelled", "failed", "succeeded")
    assert done["status"] == "cancelled" and done["outcome"]["reason"] == "blocked_app"
    assert "Gmail (com.google.android.gm) is blocked on this phone" in done["outcome"]["summary"]
    session = api.manager.get(alice.device)
    assert session.online and session.link is not None  # the connection stays up
    assert any("blocked on this phone" in e["message"] for e in session.coordinator.task(task["id"])["events"])


def test_the_phones_thread_shows_stopped_blocked_app():
    from openmob import phone_chats

    events = [{"task": "t1", "time": 1.0, "kind": "status", "message": "Working on: reply to Sam"},
              {"task": "t1", "time": 2.0, "kind": "error", "message": "Stopped: Gmail (com.google.android.gm) is "
               "blocked on this phone, so the agent stopped there. (1 steps)",
               "data": {"final": True, "success": False, "cancelled": True, "reason": "blocked_app", "steps": 1}}]
    turn = phone_chats._turns_from_events(events, [])[-1]
    assert turn["outcome"] == "blocked" and "Gmail" in turn["summary"] and not turn["stopped_by_owner"]


def test_a_blocked_app_stop_with_a_bad_package_or_label_names_nothing_it_cant_check(api):
    alice = api.alice
    task = run_task(alice, "wait for the page")
    wait_status(alice, task["id"], "running")
    alice.phone.send({"type": "task_stop", "reason": "blocked_app", "package": "<script>", "label": 7})
    done = wait_status(alice, task["id"], "cancelled", "failed", "succeeded")
    assert done["outcome"]["reason"] == "blocked_app" and "<script>" not in done["outcome"]["summary"]


def test_another_stop_reason_is_an_ordinary_owner_stop(api):
    alice = api.alice
    task = run_task(alice, "wait for the page")
    wait_status(alice, task["id"], "running")
    alice.phone.send({"type": "task_stop", "reason": "something_else"})
    done = wait_status(alice, task["id"], "cancelled", "failed", "succeeded")
    assert done["status"] == "cancelled" and done["outcome"]["reason"] == "stopped_on_phone"


def test_a_blocked_app_stop_with_nothing_running_does_nothing(api):
    alice = api.alice
    alice.phone.send({"type": "task_stop", "reason": "blocked_app", "package": GMAIL})
    alice.phone.send({"type": "chats_list", "offset": 0, "limit": 1})
    assert wait_for(lambda: any(m["type"] == "chats" for m in alice.phone.received))
    task = run_task(alice, "open settings")  # the next task runs as usual
    assert wait_status(alice, task["id"], "succeeded", "failed", "cancelled")["status"] == "succeeded"


# --- app names on the dashboard (owner, 2026-10-20) ---------------------------------------------------------


def test_a_report_carries_the_phones_labels_and_an_old_one_still_parses():
    names, labels = blocked_apps.report({"packages": [GMAIL], "apps": [
        {"package": GMAIL, "label": "Gmail"}, {"package": "com.whatsapp", "label": "Whats\nApp‮ " + "x" * 80}]})
    assert names == [GMAIL, "com.whatsapp"]
    assert labels[GMAIL] == "Gmail"
    assert labels["com.whatsapp"].startswith("Whats App") and len(labels["com.whatsapp"]) <= 60
    assert "‮" not in labels["com.whatsapp"]
    assert blocked_apps.report({"packages": [GMAIL]}) == ([GMAIL], {})  # an older app: package names only
    assert blocked_apps.report({"apps": [{"package": GMAIL}]}) == ([GMAIL], {})  # no label: none shown
    for bad in ({"apps": [{"package": "not a package", "label": "x"}]}, {"apps": ["com.whatsapp"]},
                {"apps": [{"package": f"com.example.app{i}"} for i in range(201)]}):
        with pytest.raises(InvalidPackages):
            blocked_apps.report(bad)


def test_the_dashboard_shows_names_with_the_package_and_a_pending_one_by_package(api):
    alice = api.alice
    url = f"/api/devices/{alice.device}/blocked-apps"
    alice.console.post(url, json={"packages": ["org.thoughtcrime.securesms"]})
    alice.phone.send({"type": "blocked_apps", "packages": [GMAIL, "com.whatsapp"],
                      "apps": [{"package": GMAIL, "label": "Gmail"}, {"package": "com.whatsapp", "label": ""}]})
    assert wait_for(lambda: alice.console.get(url).json()["reported_at"])
    view = alice.console.get(url).json()
    assert view["apps"] == [{"package": GMAIL, "label": "Gmail"}, {"package": "com.whatsapp", "label": ""}]
    assert view["pending"] == ["org.thoughtcrime.securesms"]  # shown by package until the phone reports its name
    # An old-style report (strings only) keeps the list, with no names.
    alice.phone.send({"type": "blocked_apps", "packages": [GMAIL]})
    assert wait_for(lambda: alice.console.get(url).json()["apps"] == [{"package": GMAIL, "label": ""}])


def test_a_stored_file_from_before_labels_still_loads(tmp_path):
    import json

    path = tmp_path / "b.json"
    path.write_text(json.dumps({"acct|app-1": {"reported": [GMAIL], "reported_at": 1.0, "pending": []}}))
    assert BlockedAppsStore(path).view("acct", "app-1")["apps"] == [{"package": GMAIL, "label": ""}]
