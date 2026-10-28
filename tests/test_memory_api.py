"""Preferences memory: the owner's API and page (Task 6)."""

import json

import httpx
from test_api_v1 import api  # noqa: F401 (shared fake-phone server fixture)

from openmob.memory import Memory


def on(api):
    """Turn memory on for the running server (the routes read the switch and the store per request)."""
    api.manager.cfg.memory = True
    api.manager.memory = Memory(api.tmp / "memory.sqlite")
    return api.manager.memory


def test_crud_round_trip(api):
    on(api)
    c = api.alice.console
    assert c.get("/api/memory").json() == {"notes": [], "proposed": []}
    made = c.post("/api/memory", json={"text": "I prefer dark mode", "kind": "about_you"})
    assert made.status_code == 200 and made.json()["status"] == "active"
    nid = made.json()["id"]
    person = c.post("/api/memory", json={"text": "birthday is May 3", "kind": "person", "relation": "sis",
                                         "contact_name": "Maya"}).json()
    listed = c.get("/api/memory").json()
    assert {n["id"] for n in listed["notes"]} == {nid, person["id"]} and listed["proposed"] == []
    edited = c.patch(f"/api/memory/{nid}", json={"text": "I prefer light mode"})
    assert edited.status_code == 200 and edited.json()["text"] == "I prefer light mode"
    assert c.patch(f"/api/memory/{person['id']}", json={"contact_name": "Maya K"}).json()["contact_name"] == "Maya K"
    assert c.delete(f"/api/memory/{nid}").json() == {"ok": True}
    assert [n["id"] for n in c.get("/api/memory").json()["notes"]] == [person["id"]]
    assert c.delete(f"/api/memory/{nid}").status_code == 404


def test_bad_notes_are_400_with_a_detail(api):
    on(api)
    c = api.alice.console
    for body in ({"text": "", "kind": "about_you"}, {"text": "x" * 301, "kind": "about_you"},
                 {"text": "hi", "kind": "person", "relation": "sis", "contact_name": "+1 555 0100"},
                 {"text": "hi", "kind": "bogus"}, {"text": "hi", "kind": "app"}):
        r = c.post("/api/memory", json=body)
        assert r.status_code == 400 and r.json()["detail"], body
    assert c.post("/api/memory", content=b"nope").status_code == 400


def test_confirm_and_dismiss_a_proposal(api):
    mem = on(api)
    c = api.alice.console
    acct = api.store.device_auth("alice-phone")["account_id"]
    keep = mem.add(acct, "Use the second account", "about_you")
    drop = mem.add(acct, "Likes pizza", "about_you")
    assert {n["id"] for n in c.get("/api/memory").json()["proposed"]} == {keep["id"], drop["id"]}
    assert c.post(f"/api/memory/{keep['id']}/confirm").json()["status"] == "active"
    assert c.post(f"/api/memory/{drop['id']}/dismiss").json() == {"ok": True}
    listed = c.get("/api/memory").json()
    assert [n["id"] for n in listed["notes"]] == [keep["id"]] and listed["proposed"] == []
    assert c.post(f"/api/memory/{drop['id']}/confirm").status_code == 404


def test_another_accounts_note_is_404(api):
    on(api)
    nid = api.alice.console.post("/api/memory", json={"text": "mine", "kind": "about_you"}).json()["id"]
    b = api.bob.console
    assert b.get("/api/memory").json() == {"notes": [], "proposed": []}
    assert b.patch(f"/api/memory/{nid}", json={"text": "x"}).status_code == 404
    assert b.delete(f"/api/memory/{nid}").status_code == 404
    assert b.post(f"/api/memory/{nid}/confirm").status_code == 404
    assert b.post(f"/api/memory/{nid}/dismiss").status_code == 404
    assert [n["id"] for n in api.alice.console.get("/api/memory").json()["notes"]] == [nid]


def test_signed_out_is_401_and_cross_site_writes_are_refused(api):
    on(api)
    c = api.alice.console
    assert httpx.get(f"{api.base}/api/memory").status_code == 401
    nid = c.post("/api/memory", json={"text": "mine", "kind": "about_you"}).json()["id"]
    evil = {"Sec-Fetch-Site": "cross-site", "Origin": "https://evil.example"}
    assert c.post("/api/memory", json={"text": "x", "kind": "about_you"}, headers=evil).status_code == 403
    assert c.patch(f"/api/memory/{nid}", json={"text": "x"}, headers=evil).status_code == 403
    assert c.delete(f"/api/memory/{nid}", headers=evil).status_code == 403
    assert c.post(f"/api/memory/{nid}/confirm", headers=evil).status_code == 403
    assert c.post(f"/api/memory/{nid}/dismiss", headers=evil).status_code == 403
    assert [n["text"] for n in c.get("/api/memory").json()["notes"]] == ["mine"]


def test_switch_off_is_404_and_no_nav_link(api):
    on(api)
    c = api.alice.console
    c.post("/api/memory", json={"text": "kept", "kind": "about_you"})
    assert c.get("/memory").status_code == 200
    assert "What OpenMob remembers" in c.get("/memory").text
    assert c.get("/api/auth/me").json()["memory"] is True
    assert 'id="memoryLink"' in c.get("/").text
    api.manager.cfg.memory = False
    for method, path in (("get", "/memory"), ("get", "/api/memory"), ("post", "/api/memory"),
                         ("patch", "/api/memory/x"), ("delete", "/api/memory/x"),
                         ("post", "/api/memory/x/confirm"), ("post", "/api/memory/x/dismiss")):
        assert getattr(c, method)(path).status_code == 404, path
    assert c.get("/api/auth/me").json()["memory"] is False
    api.manager.cfg.memory = True
    assert [n["text"] for n in c.get("/api/memory").json()["notes"]] == ["kept"]  # the data was kept


def test_audit_rows_carry_ids_not_text(api):
    on(api)
    c = api.alice.console
    secret = "my secret preference zebra"
    nid = c.post("/api/memory", json={"text": secret, "kind": "about_you"}).json()["id"]
    c.patch(f"/api/memory/{nid}", json={"text": secret + " edited"})
    other = api.alice.console.post("/api/memory", json={"text": "second", "kind": "about_you"}).json()["id"]
    c.delete(f"/api/memory/{other}")
    api.manager.memory.add(api.store.device_auth("alice-phone")["account_id"], "proposal zebra", "about_you")
    pid = c.get("/api/memory").json()["proposed"][0]["id"]
    c.post(f"/api/memory/{pid}/confirm")
    rows = json.dumps(api.ledger.audit_log(account_id=api.store.device_auth("alice-phone")["account_id"]))
    assert "zebra" not in rows and "second" not in rows
    for action in ("memory.added", "memory.edited", "memory.deleted", "memory.confirmed"):
        assert action in rows
    assert nid in rows


def test_person_card_shows_relation_and_contact(api):
    from openmob.memory import render_events
    mem = on(api)
    acct = api.store.device_auth("alice-phone")["account_id"]
    n = mem.add(acct, "likes lilies", "person", relation="sis", contact_name="Maya")
    ev = [{"kind": "memory", "message": "", "data": {"use": "proposed", "note_ids": [n["id"]],
                                                     "card": {"note_id": n["id"], "status": "proposed"}}}]
    [out] = render_events(mem, acct, ev, trusted=True, enabled=True)
    assert out["message"] == "Save this? your sis = Maya — likes lilies"
    # the page lists the same note with both fields for the owner to see
    [p] = api.alice.console.get("/api/memory").json()["proposed"]
    assert (p["relation"], p["contact_name"]) == ("sis", "Maya")


def test_dashboard_card_has_save_and_not_now(api):
    page = api.alice.console.get("/").text
    assert '"Not now"' in page and '"Save"' in page and 'act("confirm")' in page and 'act("dismiss")' in page and "/api/memory/" in page


def test_a_card_reflects_the_notes_state_on_the_next_read(api):
    from openmob.memory import render_events
    mem = on(api)
    c = api.alice.console
    acct = api.store.device_auth("alice-phone")["account_id"]
    n = mem.add(acct, "Use the second account", "about_you")
    ev = [{"kind": "memory", "message": "", "data": {"use": "proposed", "note_ids": [n["id"]],
                                                     "card": {"note_id": n["id"], "status": "proposed"}}}]
    status = lambda trusted=True: render_events(mem, acct, ev, trusted, True)[0]["data"]["card"]["status"]  # noqa: E731
    assert status() == "proposed" and status(trusted=False) == "gone"
    c.post(f"/api/memory/{n['id']}/confirm")
    assert status() == "active"
    c.delete(f"/api/memory/{n['id']}")
    assert status() == "gone"


def test_a_stale_not_now_cannot_delete_a_saved_note(api):
    mem = on(api)
    c = api.alice.console
    acct = api.store.device_auth("alice-phone")["account_id"]
    n = mem.add(acct, "Use the second account", "about_you")
    assert c.post(f"/api/memory/{n['id']}/confirm").status_code == 200
    r = c.post(f"/api/memory/{n['id']}/dismiss")
    assert r.status_code == 409
    assert mem.get(acct, n["id"])["status"] == "active"
    assert c.post(f"/api/memory/{n['id']}/confirm").json()["status"] == "active"  # confirming twice is a no-op
    assert mem.dismiss(acct, n["id"]) is False and mem.dismiss(acct, "nope") is None
    rows = [r["action"] for r in api.ledger.audit_log(account_id=acct)]
    assert "memory.deleted" not in rows
