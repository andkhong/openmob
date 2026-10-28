"""Security review 5 (2026-10-21, at 0893b19): regression tests for the server-side fixes (fix/review5-server)."""
from __future__ import annotations

import pytest

from openmob.agent import fast


# A5-L2: a condition or order word inside a message body or a lookup still governs a step.
@pytest.mark.parametrize("request_text", [
    "Text Sam saying hi and if he replies call him",
    "Open WhatsApp and message Mom: on my way, delete the chat after",
    "Text Sam: see you at 8, and after that text Alex",
    "Search for flights to NYC if under 300 book the cheapest",
    "Message Bob: hi. If he answers, call him",
    "Text Sam saying hi then call him if he replies",
    "Text Sam: running late! When you see it call me",
])
def test_a5_l2_a_condition_after_a_message_body_or_lookup_is_model_only(request_text):
    assert fast.model_only(request_text) is True


@pytest.mark.parametrize("request_text", [
    "Text Sam saying hi then call him",
    "Message Bob: see you when you get here",
    "Text Sam: I'll call you if I'm late",
    "Text Mom saying on my way. Then open Maps",
])
def test_a5_l2_a_message_body_alone_is_still_not_a_step(request_text):
    assert fast.model_only(request_text) is False


# W5-M1: /login?next= and the landing page's signed-in redirect refuse a same-origin path that resolves to "//host"
# ("/.//evil.example", "/..//evil.example", "/%2e//evil.example" all resolve to the pathname "//evil.example", which
# location.replace reads as protocol-relative). The repo runs no JS tests; checked with node by hand (2026-10-21).
NEXT_GUARD = r"!/^\/[\/\\]/.test("


@pytest.fixture
def web(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from test_easy_connect import _manager

    from openmob.accounts import AccountStore
    from openmob.server import create_app

    monkeypatch.delenv("FLY_APP_NAME", raising=False)
    manager = _manager(tmp_path)
    manager.cfg.invite_email = None
    store = AccountStore(tmp_path / "accounts.json")
    return TestClient(create_app(manager, store=store)), store, manager


@pytest.mark.parametrize("payload", ["/.//evil.example", "/..//evil.example", "/%2e//evil.example"])
def test_w5_m1_the_login_page_refuses_a_next_that_resolves_to_another_host(web, payload):
    client = web[0]
    page = client.get("/login", params={"next": payload}).text
    assert NEXT_GUARD + "u.pathname)" in page
    assert "u.origin === location.origin && " + NEXT_GUARD in page


def test_w5_m1_the_landing_redirect_refuses_a_next_that_resolves_to_another_host(web):
    js = web[0].get("/static/landing.js").text
    assert "target.origin === location.origin && " + NEXT_GUARD + "target.pathname)" in js


# M5-L1 (owner, 2026-10-21): the "Sending to" line names a remembered person only when their name is on screen.
def test_m5_l1_no_sending_line_while_the_screen_shows_someone_else(tmp_path):
    from test_memory_people import lines, make, person
    from test_permissions import el, tap

    agent, driver, io, perms = make([tap("Send")], tmp_path, elements=[el(0, "Mallory Smith", cls="TextView")])
    person(agent.memory, "sis", "Maya Lee")
    agent.run("text my sis I'm late", permissions=perms, memory_allowed=True)
    assert lines(io) == []


# M5-L2: recall answers only for a query that shares a word with the owner's request (or the notes already given),
# and at most twice per task.
def test_m5_l2_recall_refuses_a_query_the_request_never_named(tmp_path):
    from conftest import tool_use
    from test_memory_people import make

    # About-you notes already ride every task's start block; a person or app note comes only when the request (or
    # the app in front) names it, and text on the screen must not pull one in.
    agent, driver, io, perms = make([[tool_use("recall", "r", query="boss bank")]], tmp_path)
    agent.memory.add(None, "work only, her PIN hint is 4411", "person", relation="boss", contact_name="Priya Raman",
                     status="active")
    agent.memory.add(None, "the bank app's login is under Profile", "app", package="com.chase", status="active")
    agent.run("read my messages", permissions=perms, memory_allowed=True)
    sent = str(agent.client.requests[-1]["messages"])
    assert "No saved preferences match that" in sent
    assert "Priya" not in sent and "4411" not in sent and "Profile" not in sent


def test_m5_l2_recall_still_answers_what_the_request_names(tmp_path):
    from conftest import tool_use
    from test_memory_people import make

    agent, driver, io, perms = make([[tool_use("recall", "r", query="bank")]], tmp_path)
    agent.memory.add(None, "My bank is Chase, account ends 4411", "about_you", status="active")
    agent.run("open my bank app", permissions=perms, memory_allowed=True)
    assert "Chase" in str(agent.client.requests[-1]["messages"][-1])


def test_m5_l2_recall_searches_only_the_words_the_owner_said(tmp_path):
    """Re-review 1: one shared word used to open an OR search over every query word."""
    from conftest import tool_use
    from test_memory_people import make

    agent, driver, io, perms = make([[tool_use("recall", "r", query="dinner bank password")]], tmp_path)
    agent.memory.add(None, "the bank app's password hint is blue horse", "app", package="com.chase", status="active")
    agent.memory.add(None, "books dinner tables on OpenTable", "app", package="com.opentable", status="active")
    agent.run("book a table for dinner tonight", permissions=perms, memory_allowed=True)
    answer = str(agent.client.requests[-1]["messages"][-1])
    assert "blue horse" not in answer
    assert "OpenTable" in answer


def test_m5_l2_recall_is_capped_at_two_calls_per_task(tmp_path):
    from conftest import tool_use
    from test_memory_people import make

    steps = [[tool_use("recall", f"r{i}", query="sis")] for i in range(3)]
    agent, driver, io, perms = make(steps, tmp_path)
    agent.memory.add(None, "likes voice notes", "person", relation="sis", contact_name="Maya Lee", status="active")
    agent.run("text my sis", permissions=perms, memory_allowed=True)
    assert "twice in this task" in str(agent.client.requests[3]["messages"][-1])
    assert "twice" not in str(agent.client.requests[2]["messages"][-1])


# M5-L3: a suggestion card says where it came from: the screen (agent-sourced) and the app an app note is about.
def test_m5_l3_suggestion_cards_name_their_source_and_app(tmp_path):
    from openmob import memory as memory_module
    from openmob.memory import Memory

    mem = Memory(tmp_path / "m.sqlite")
    agent_app = mem.add(None, "the bank's login is under Profile", "app", package="com.chase", source="agent")
    owner = mem.add(None, "I prefer dark mode", "about_you", source="user")
    events = [{"kind": "memory", "message": "", "data": {"use": "proposed", "note_ids": [n["id"]]}}
              for n in (agent_app, owner)]
    cards = [e["data"]["card"] for e in memory_module.render_events(mem, None, events, trusted=True, enabled=True)]
    assert cards[0]["origin"] == "Suggested from what the agent saw on screen · About the app com.chase"
    assert "origin" not in cards[1]
    rendered = memory_module.render_events(mem, None, events, trusted=True, enabled=True)
    from openmob.phone_chats import _turns_from_events
    heard = {"kind": "heard", "message": "x", "data": {}, "time": 1, "task": "t"}
    turn = _turns_from_events([heard, *[{**e, "time": 1, "task": "t"} for e in rendered]], [])[0]
    assert turn["memory_cards"][0]["origin"] == cards[0]["origin"]  # the phone's payload carries it too
    assert "origin" not in turn["memory_cards"][1]
    untrusted = memory_module.render_events(mem, None, events, trusted=False, enabled=True)
    assert all("origin" not in e["data"]["card"] for e in untrusted)  # an untrusted phone learns nothing
    mem.confirm(None, agent_app["id"])
    saved = memory_module.render_events(mem, None, events[:1], trusted=True, enabled=True)[0]["data"]["card"]
    assert "origin" not in saved


# --- H1: the agent never reaches OpenMob's own dashboard in the phone's browser ----------------------------------

from openmob import own_hosts  # noqa: E402
from openmob.agent import gate  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_hosts(monkeypatch):
    monkeypatch.setenv("OPENMOB_PUBLIC_URL", "https://openmob.fly.dev")  # as fly.toml sets it
    monkeypatch.delenv("FLY_APP_NAME", raising=False)
    own_hosts._reset_for_tests()
    yield
    own_hosts._reset_for_tests()


OWN = ["https://openmob.fly.dev/developer", "openmob.fly.dev/developer#/keys/new", "HTTPS://OpenMob.Fly.Dev.:443/memory",
       "http://localhost:8765/", "http://127.0.0.1:8765/phones", "http://[::1]:8765/", "http://10.0.2.2:8765/developer",
       "https://www.openmob.fly.dev/", "https://user@openmob.fly.dev/"]
NOT_OWN = ["https://example.com/", "https://openmob.fly.dev.evil.example/", "https://evil.example/?u=openmob.fly.dev",
           "tel:+15551234567", "https://fly.dev/"]


@pytest.mark.parametrize("url", OWN)
def test_h1_links_to_the_server_itself_are_refused(url):
    assert "OpenMob's own dashboard" in (gate.url_refusal(gate.web_url(url)) or "")


@pytest.mark.parametrize("url", NOT_OWN)
def test_h1_other_links_are_not(url):
    assert gate.url_refusal(gate.web_url(url)) is None


def test_h1_configured_and_tunnel_hosts_count(monkeypatch):
    assert gate.url_refusal("https://phone.example.org/developer") is None
    monkeypatch.setenv("OPENMOB_PUBLIC_URL", "https://phone.example.org, mob.example.net")
    assert gate.url_refusal("https://phone.example.org/developer")
    assert gate.url_refusal("https://mob.example.net/")
    monkeypatch.setenv("FLY_APP_NAME", "my-openmob")
    assert gate.url_refusal("https://my-openmob.fly.dev/")
    assert gate.url_refusal("https://abc123.trycloudflare.com/") is None
    own_hosts.add("https://abc123.trycloudflare.com")  # the tunnel `openmob run --public` opened
    assert gate.url_refusal("https://abc123.trycloudflare.com/developer")


def test_n1_our_domain_is_configuration_not_code(monkeypatch):
    """A self-hoster isn't affected by the hosted service's domain; the hosted one sets it in fly.toml (or Fly's
    FLY_APP_NAME covers it)."""
    monkeypatch.delenv("OPENMOB_PUBLIC_URL")
    assert gate.url_refusal("https://openmob.fly.dev/developer") is None
    monkeypatch.setenv("FLY_APP_NAME", "openmob")
    assert gate.url_refusal("https://openmob.fly.dev/developer")
    import tomllib
    from pathlib import Path

    env = tomllib.loads((Path(__file__).parents[1] / "fly.toml").read_text())["env"]
    assert own_hosts.host_of(env["OPENMOB_PUBLIC_URL"]) == "openmob.fly.dev"


def test_n1_a_phones_handshake_headers_never_make_a_site_the_servers_own(api):
    """Review 5 N1: a customer's phone connecting with X-Forwarded-Host: google.com (or Host: google.com) must not make
    google.com refused, for another account or at all."""
    from conftest import FakeDriver
    from test_remote import FakePhone

    for headers in ({"X-Forwarded-Host": "google.com"}, {"X-Forwarded-Host": "www.wikipedia.org", "X-Forwarded-Proto": "https"}):
        phone = FakePhone(api.base.replace("http", "ws"), FakeDriver(), device_id="alice-phone", key=api.alice.device_key,
                          headers=headers)
        try:
            assert phone.welcome.wait(5)
        finally:
            phone.disconnect()
    for url in ("https://google.com/", "https://mail.google.com/", "https://wikipedia.org/"):
        assert gate.url_refusal(url) is None, url
    assert not ({"google.com", "wikipedia.org", "www.wikipedia.org"} & own_hosts.hosts())


H1_NORMALISED = ["https://%6Fpenmob.fly.dev/", "https://%6f%70%65%6e%6d%6f%62.fly.dev/developer",
                 "https://openmob.fly.dev\\@evil.com/",  # a browser reads the backslash as a slash: our host
                 "https://openmob%2Efly%2Edev/", "https://openmob%2efly.dev/", "https://openmob\u3002fly\u3002dev/",
                 "https://openmob\uff0efly\uff61dev/", "https://OpenMob.FLY.dev./", "https://openmob.fly.dev:443/x",
                 "https://openmob.fly.dev.:8443/", "https://ｏｐｅｎｍｏｂ.fly.dev/", "https://evil.com@openmob.fly.dev/",
                 "https://open\u00admob.fly.dev/",  # a soft hyphen: IDNA drops it, so does the browser
                 "http:/openmob.fly.dev/", "https:\\\\openmob.fly.dev\\developer", "http://2130706433:8765/",
                 "http://0x7f.1/", "http://0177.0.0.1:8765/", "http://127.1/"]
H1_STILL_OTHER = ["https://openmob.fly.dev%2Eevil.com/", "https://evil.com\\@openmob.fly.dev/",
                  "https://openmob.fly.dev.evil.com/", "https://xn--openmob-xyz.fly.dev.example/", "http://128.0.0.1/"]


@pytest.mark.parametrize("url", H1_NORMALISED)
def test_h1_hosts_are_read_as_a_browser_reads_them(url):
    assert "OpenMob's own dashboard" in (gate.url_refusal(gate.web_url(url)) or ""), (url, own_hosts.host_of(url))


@pytest.mark.parametrize("url", H1_STILL_OTHER)
def test_h1_normalising_doesnt_make_other_sites_ours(url):
    assert gate.url_refusal(gate.web_url(url)) is None, (url, own_hosts.host_of(url))


def _loop(tmp_path, steps, elements, mode="trusted"):
    from conftest import FakeDriver, ScriptedClient, tool_use
    from test_financial_safeguards import CHROME, RecordingIO

    from openmob import permissions as perm
    from openmob.agent.loop import Agent
    from openmob.config import Config
    from openmob.phone.apps import AppResolver

    driver = FakeDriver(elements=list(elements), packages=[CHROME])
    driver.package = CHROME
    io = RecordingIO([])
    client = ScriptedClient(steps + [[tool_use("done", "z", summary="ok", success=True)]] * 2)
    agent = Agent(client, driver, AppResolver(driver, {}, label_cache=tmp_path / "l.json"),
                  Config(settle_delay=0, launch_settle_delay=0), io, use_ocr=False)
    store = {"s": perm.normalize(perm.default_settings())}
    result = agent.run("check the page", permissions=perm.TaskPermissions(mode, lambda: store["s"]))
    return result, driver, client


@pytest.mark.parametrize("mode", ["ask", "auto", "trusted"])
def test_h1_open_url_and_open_link_to_the_dashboard_are_refused_in_every_mode(tmp_path, mode):
    from conftest import tool_use
    from test_financial_safeguards import label, last_tool_result

    result, driver, client = _loop(tmp_path, [[tool_use("open_url", "u", url="openmob.fly.dev/developer")]],
                                   [label("Home")], mode=mode)
    assert not any(a[0] == "url" for a in driver.actions)
    assert "OpenMob's own dashboard" in last_tool_result(client)


def test_h1_typing_the_dashboard_into_the_address_bar_is_refused(tmp_path):
    from conftest import tool_use
    from test_financial_safeguards import last_tool_result

    from openmob.phone.adb import UIElement

    bar = UIElement(0, "", "", "com.android.chrome:id/url_bar", "android.widget.EditText", True, None,
                    (100, 100, 1000, 200), editable=True, focused=True)
    for text in ("https://openmob.fly.dev/developer", "localhost:8765/developer"):
        result, driver, client = _loop(tmp_path, [[tool_use("type_text", "t", text=text, submit=True)]], [bar])
        assert not any(a[0] in ("type", "key") for a in driver.actions), driver.actions
        assert "OpenMob's own dashboard" in last_tool_result(client)


def test_h1_a_browser_showing_the_dashboard_stops_the_task(tmp_path):
    from conftest import tool_use

    from openmob.agent.loop import OWN_DASHBOARD_MESSAGE
    from openmob.phone.adb import UIElement

    bar = UIElement(0, "openmob.fly.dev/developer", "", "com.android.chrome:id/url_bar", "android.widget.EditText",
                    True, None, (100, 100, 1000, 200), editable=True)
    create = UIElement(1, "Create key", "", "", "android.widget.Button", True, None, (100, 600, 600, 700))
    result, driver, client = _loop(tmp_path, [[tool_use("tap", "t", x=300, y=650, target="Create key")]],
                                   [bar, create])
    assert result.success is False and result.summary == OWN_DASHBOARD_MESSAGE
    assert not any(a[0] == "tap" for a in driver.actions)


def test_h1_a_browser_on_another_site_carries_on(tmp_path):
    from conftest import tool_use

    from openmob.phone.adb import UIElement

    bar = UIElement(0, "example.com/keys", "", "com.android.chrome:id/url_bar", "android.widget.EditText",
                    True, None, (100, 100, 1000, 200), editable=True)
    create = UIElement(1, "Create key", "", "", "android.widget.Button", True, None, (100, 600, 600, 700))
    result, driver, _ = _loop(tmp_path, [[tool_use("tap", "t", x=300, y=650, target="Create key")]], [bar, create])
    assert any(a[0] == "tap" for a in driver.actions)


def _gmail_loop(tmp_path, elements, package):
    from conftest import FakeDriver, ScriptedClient, tool_use
    from test_financial_safeguards import RecordingIO

    from openmob import permissions as perm
    from openmob.agent.loop import Agent
    from openmob.config import Config
    from openmob.phone.apps import AppResolver

    driver = FakeDriver(elements=list(elements), packages=[package])
    driver.package = package
    client = ScriptedClient([[tool_use("tap", "t", x=300, y=1650, target="Reply")]] +
                            [[tool_use("done", "z", summary="ok", success=True)]] * 2)
    agent = Agent(client, driver, AppResolver(driver, {}, label_cache=tmp_path / "l.json"),
                  Config(settle_delay=0, launch_settle_delay=0), RecordingIO([]), use_ocr=False)
    store = {"s": perm.normalize(perm.default_settings())}
    return agent.run("reply to the email", permissions=perm.TaskPermissions("trusted", lambda: store["s"])), driver


@pytest.mark.parametrize("package", ["com.google.android.gm", "com.android.chrome"])
def test_n2_a_page_or_an_email_naming_the_server_doesnt_stop_the_task(tmp_path, package):
    """Review 5 N2: only the address bar counts. An email (Gmail draws it in a web view) or a web page that names the
    server, localhost, 10.0.2.2 or this machine's name is anyone's text."""
    from openmob.phone.adb import UIElement

    machine = sorted(own_hosts._machine_hosts())[0] if own_hosts._machine_hosts() else "localhost"
    page = UIElement(0, "", "", "", "android.webkit.WebView", False, None, (0, 300, 1080, 1500))
    words = [UIElement(i + 1, t, "", "", "android.view.View", False, None, (40, 320 + 60 * i, 1000, 370 + 60 * i))
             for i, t in enumerate(["openmob.fly.dev", "https://openmob.fly.dev/developer", "localhost", "localhost:8765",
                                    "10.0.2.2", "http://10.0.2.2:8765/", machine, f"http://{machine}:8765/"])]
    subject = UIElement(20, "openmob.fly.dev", "openmob.fly.dev", "com.google.android.gm:id/subject_and_folder_view",
                        "android.widget.TextView", False, None, (40, 200, 1000, 260))
    reply = UIElement(21, "Reply", "", "", "android.widget.Button", True, None, (100, 1600, 600, 1700))
    elements = [page, *words, reply] + ([subject] if package.endswith(".gm") else [])
    result, driver = _gmail_loop(tmp_path, elements, package)
    assert any(a[0] == "tap" for a in driver.actions), result.summary


def test_n2_the_address_bar_still_stops_it(tmp_path):
    from openmob.agent.loop import OWN_DASHBOARD_MESSAGE
    from openmob.phone.adb import UIElement

    for bar in (UIElement(0, "openmob.fly.dev/developer", "", "com.android.chrome:id/url_bar", "android.widget.EditText",
                          True, None, (100, 100, 1000, 200)),
                # a browser's own control outside the page, without a known id (Samsung Internet's toolbar text)
                UIElement(0, "https://openmob.fly.dev/memory", "", "", "android.widget.TextView", True, None,
                          (100, 100, 1000, 200))):
        page = UIElement(1, "", "", "", "android.webkit.WebView", False, None, (0, 300, 1080, 2000))
        reply = UIElement(2, "Reply", "", "", "android.widget.Button", True, None, (100, 1600, 600, 1700))
        result, driver = _gmail_loop(tmp_path, [bar, page, reply], "com.android.chrome")
        assert result.summary == OWN_DASHBOARD_MESSAGE and not any(a[0] == "tap" for a in driver.actions)


def test_n2_the_address_bar_ids_match_the_phones_rules():
    import json
    from pathlib import Path

    rules = json.loads((Path(__file__).parents[1] / "android/app/src/main/resources/gatekeeper/rules.json").read_text())
    assert gate.ADDRESS_BAR_ID.pattern == rules["server_page"]["url_ids"]


# H1 step-up: minting or rotating a key and trusting a phone need the account's password, not just the cookie.
from test_api_v1 import api  # noqa: E402,F401  (the fixture: two signed-in accounts, each with a paired phone)


def test_h1_creating_a_key_needs_the_password(api):
    console = api.alice.console
    for body in ({"name": "x"}, {"name": "x", "password": "wrong-password"}):
        r = console.post("/api/developer/keys", json=body)
        assert r.status_code == 403 and "key" not in r.json()
    r = console.post("/api/developer/keys", json={"name": "x", "password": "password123"})
    assert r.status_code == 200 and r.json()["key"]


def test_h1_rotating_a_key_needs_the_password(api):
    path = f"/api/developer/keys/{api.alice.key_id}/rotate"
    assert api.alice.console.post(path).status_code == 403
    assert api.alice.console.post(path, json={"password": "nope-nope"}).status_code == 403
    assert api.alice.console.post(path, json={"password": "password123"}).json()["key"]


def test_h1_trusting_a_phone_needs_the_password(api):
    path = f"/api/devices/{api.alice.device}/trust"
    assert api.alice.console.post(path).status_code == 403
    assert api.alice.console.post(path, json={"password": "nope-nope"}).status_code == 403
    assert api.alice.console.post(path, json={"password": "password123"}).json()["trusted_for_approvals"] is True
    # Bob's right password doesn't trust Alice's phone.
    assert api.bob.console.post(path, json={"password": "password123"}).status_code == 404


def test_h1_wrong_step_up_passwords_count_as_failed_sign_ins(api):
    for _ in range(10):
        assert api.alice.console.post("/api/developer/keys", json={"password": "wrong-password"}).status_code == 403
    assert api.alice.console.post("/api/developer/keys", json={"password": "password123"}).status_code == 429
    login = httpx_post(api.base + "/api/auth/login", json={"email": "alice@example.com", "password": "password123"})
    assert login.status_code == 429  # the same limiter as sign-in


def httpx_post(url, **kw):
    import httpx

    return httpx.post(url, timeout=10, **kw)


# Re-review 1: loosening a key, allowing sensitive apps and setting a webhook need the password too; tightening doesn't.


def test_rr1_loosening_a_key_needs_the_password(api):
    path = f"/api/developer/keys/{api.alice.key_id}"
    c = api.alice.console
    for body in ({"confirm_approve": True}, {"max_mode": "trusted"}, {"max_mode": "never"},
                 {"confirm_approve": True, "password": "wrong-password"}):
        assert c.patch(path, json=body).status_code == 403, body
    key = next(k for k in c.get("/api/developer/keys").json() if k["id"] == api.alice.key_id)
    assert key["confirm_approve"] is False and key["max_mode"] == "auto"  # nothing applied
    # Tightening, and leaving a setting as it is, need nothing.
    assert c.patch(path, json={"max_mode": "ask"}).json()["max_mode"] == "ask"
    assert c.patch(path, json={"confirm_approve": False}).status_code == 200
    assert c.patch(path, json={"max_mode": "ask"}).status_code == 200
    r = c.patch(path, json={"confirm_approve": True, "max_mode": "trusted", "password": "password123"}).json()
    assert r["confirm_approve"] is True and r["max_mode"] == "trusted"
    assert c.patch(path, json={"confirm_approve": True}).status_code == 200  # already on: not a loosening
    # Bob's password doesn't loosen Alice's key, and Bob can't reach it at all.
    assert api.bob.console.patch(path, json={"max_mode": "never", "password": "password123"}).status_code == 404


def test_rr1_allowing_sensitive_apps_needs_the_password(api):
    c = api.alice.console
    assert c.post("/api/developer/settings", json={"allow_sensitive_apps": True}).status_code == 403
    assert c.post("/api/developer/settings", json={"allow_sensitive_apps": True, "password": "nope-nope"}).status_code == 403
    assert c.get("/api/developer/overview").json()["settings"]["allow_sensitive_apps"] is False
    assert c.post("/api/developer/settings",
                  json={"allow_sensitive_apps": True, "password": "password123"}).json()["allow_sensitive_apps"] is True
    assert c.post("/api/developer/settings", json={"allow_sensitive_apps": False}).json()["allow_sensitive_apps"] is False


def test_rr1_setting_a_webhook_needs_the_password(api):
    c = api.alice.console
    for body in ({"url": "https://hooks.example.com/x"}, {"url": "https://hooks.example.com/x", "password": "nope-nope"}):
        assert c.post("/api/developer/webhook", json=body).status_code == 403
    assert c.get("/api/developer/overview").json()["settings"]["webhook_url"] is None
    r = c.post("/api/developer/webhook", json={"url": "https://hooks.example.com/x", "password": "password123"})
    assert r.status_code == 200 and r.json()["secret"]
    assert c.delete("/api/developer/webhook").status_code == 200  # removing it is a tightening


def test_rr1_the_password_dialog_is_never_autofilled():
    from pathlib import Path

    static = Path(__file__).parents[1] / "openmob/static"
    for page in ("developer.html", "index.html", "phones.html"):
        text = (static / page).read_text()
        start = text.index("function askPassword(")
        body = text[start:text.index("\n}\n", start)]
        assert "current-password" not in body and 'name: "openmob-confirm"' in body, page
        # A real password field (hidden from accessibility services and keyboard learning), never autofilled.
        assert 'type: "password"' in body and 'autocomplete: "new-password"' in body, page
        assert 'type: "text"' not in body and "webkitTextSecurity" not in body, page
