"""Security review 4 on the server (2026-10-18, at c3941fd), fixed.

M1: request bodies are capped (413) by Content-Length and by counting a chunked body; WebSocket messages are capped
below uvicorn's 16 MiB. M2: a sign-in hashes outside the account store's lock, every sign-in attempt is rate-limited
per email and per address, and sessions are cleaned and capped per account. L2: an unknown email costs the same hash.
L3: the session cookie is Secure over HTTPS, security headers on every response, HSTS over HTTPS. L4: the pairing
page's QR library has SRI. L8: ASCII look-alike emails are refused at sign-up. L9: the card and SSN detector (here
and on the phone) reads other dashes, "|", bullets and direction marks as separators. Also from the cleanup's findings: a stale answer never answers a
later question; the phone's own unpair removes the phone before closing its sockets; cancelling a typed code is
same-site only; webhook addresses in CGNAT and other non-public ranges are refused; a refused key PATCH changes
nothing.
"""

import queue
import re
import threading
import time

import httpx
import pytest
import websockets.sync.client
from fastapi.testclient import TestClient
from test_easy_connect import _manager, srv  # noqa: F401 (the fixture)

from openmob import accounts, server
from openmob.accounts import AccountLookAlike, AccountStore, AuthError, email_skeleton
from openmob.agent import sensitive
from openmob.platform.service import is_public_address, public_ip
from openmob.runner import Coordinator
from openmob.server import MAX_BODY, WS_MAX_SIZE, create_app, serve_in_background
from openmob.voice.tts import Speaker


@pytest.fixture
def app_store(tmp_path):
    store = AccountStore(tmp_path / "accounts.json")
    return create_app(_manager(tmp_path), store=store), store


def _login(client, email, password="password123"):
    return client.post("/api/auth/login", json={"email": email, "password": password})


# --- M1: request bodies and WebSocket messages are capped --------------------------------------------------------


def test_a_body_over_the_limit_is_refused_by_its_length_before_the_route_runs(srv, monkeypatch):  # noqa: F811
    called = []
    monkeypatch.setattr(srv.store, "verify_login", lambda *a: called.append(a))
    r = httpx.post(f"{srv.base}/api/auth/login", content=b"x" * (MAX_BODY + 1),
                   headers={"content-type": "application/json"})
    assert r.status_code == 413 and not called
    assert MAX_BODY == 1024 * 1024


def test_a_chunked_body_is_counted_as_it_arrives(srv, monkeypatch):  # noqa: F811
    called = []
    monkeypatch.setattr(srv.store, "verify_login", lambda *a: called.append(a))

    def chunks():  # no Content-Length: Transfer-Encoding chunked
        for _ in range(MAX_BODY // 65536 + 2):
            yield b" " * 65536

    r = httpx.post(f"{srv.base}/api/auth/login", content=chunks(), headers={"content-type": "application/json"})
    assert r.status_code == 413 and not called


def test_a_normal_request_still_works(srv):  # noqa: F811
    user = srv.user("normal@example.com")  # sign-up and sign-in: small JSON
    assert user.get("/api/devices").status_code == 200
    padded = {"email": "normal@example.com", "password": "password123", "pad": " " * (MAX_BODY // 2)}
    assert httpx.post(f"{srv.base}/api/auth/login", json=padded).status_code == 200


def test_websocket_messages_are_capped_below_uvicorns_16_mib(srv):  # noqa: F811
    assert 2 * 1024 * 1024 <= WS_MAX_SIZE <= 4 * 1024 * 1024  # a phone's biggest screenshot is about 1.5 MB
    with websockets.sync.client.connect(f"{srv.ws}/phone/ws", max_size=None) as ws:
        ws.send("x" * (WS_MAX_SIZE + 1))
        with pytest.raises(websockets.exceptions.ConnectionClosed) as closed:
            ws.recv(timeout=5)
    assert closed.value.rcvd is not None and closed.value.rcvd.code == 1009  # message too big


def test_serve_in_background_passes_the_websocket_cap(tmp_path):
    from test_remote import free_port

    s = serve_in_background(create_app(_manager(tmp_path)), "127.0.0.1", free_port())
    try:
        assert s.config.ws_max_size == WS_MAX_SIZE
    finally:
        s.should_exit = True


# --- M2: the hash runs outside the lock; every sign-in is rate-limited; sessions are cleaned ------------------------


def test_a_sign_in_hashes_outside_the_lock_every_request_takes(tmp_path, monkeypatch):
    store = AccountStore(tmp_path / "accounts.json")
    other = store.create_account("other@example.com", "password123")
    token = store.create_session(other)
    store.create_account("hasher@example.com", "password123")
    real = accounts._hash_password
    seen = []

    def slow_hash(password, salt):
        done = threading.Event()

        def look():  # another user's request, while this sign-in hashes
            seen.append(store.account_for_session(token))
            done.set()

        threading.Thread(target=look, daemon=True).start()
        assert done.wait(2), "account_for_session waited for the sign-in's hash"
        return real(password, salt)

    monkeypatch.setattr(accounts, "_hash_password", slow_hash)
    assert store.verify_login("hasher@example.com", "password123")
    assert seen == [other]


def test_a_password_changed_during_the_hash_wins(tmp_path, monkeypatch):
    store = AccountStore(tmp_path / "accounts.json")
    account_id = store.create_account("change@example.com", "password123")
    real = accounts._hash_password

    def changing(password, salt):
        out = real(password, salt)
        with store._lock:  # the password changes while the old one is being checked
            store._data["accounts"][account_id]["pw_hash"] = real("newpassword1", salt)
        return out

    monkeypatch.setattr(accounts, "_hash_password", changing)
    with pytest.raises(AuthError):
        store.verify_login("change@example.com", "password123")


def test_correct_sign_ins_are_rate_limited_per_email(app_store, monkeypatch):
    app, store = app_store
    store.create_account("busy@example.com", "password123")
    monkeypatch.setattr(server, "LOGIN_MAX_ATTEMPTS_EMAIL", 3)
    for i in range(3):
        assert _login(TestClient(app, client=(f"10.0.0.{i}", 1)), "busy@example.com").status_code == 200
    r = _login(TestClient(app, client=("10.0.0.9", 1)), "busy@example.com")
    assert r.status_code == 429 and r.headers["retry-after"]


def test_correct_sign_ins_are_rate_limited_per_address(app_store, monkeypatch):
    app, store = app_store
    monkeypatch.setattr(server, "LOGIN_MAX_ATTEMPTS_IP", 3)
    client = TestClient(app, client=("10.1.0.1", 1))
    for i in range(4):
        store.create_account(f"user{i}x@example.com", "password123")
    assert all(_login(client, f"user{i}x@example.com").status_code == 200 for i in range(3))
    assert _login(client, "user3x@example.com").status_code == 429
    assert _login(TestClient(app, client=("10.1.0.2", 1)), "user3x@example.com").status_code == 200


def test_the_attempt_limits_are_generous():
    assert server.LOGIN_MAX_ATTEMPTS_EMAIL >= 30 and server.LOGIN_MAX_ATTEMPTS_IP >= 60
    assert server.LOGIN_MAX_ATTEMPTS_IP < server.FailureWindow.KEEP  # the window keeps enough hits to count


def test_sessions_are_capped_per_account_oldest_first(tmp_path):
    store = AccountStore(tmp_path / "accounts.json")
    a = store.create_account("many@example.com", "password123")
    b = store.create_account("few@example.com", "password123")
    theirs = store.create_session(b)
    tokens = [store.create_session(a) for _ in range(accounts.SESSIONS_PER_ACCOUNT + 2)]
    assert accounts.SESSIONS_PER_ACCOUNT == 50
    assert store.account_for_session(tokens[0]) is None and store.account_for_session(tokens[1]) is None
    assert all(store.account_for_session(t) == a for t in tokens[2:])
    assert sum(s["account_id"] == a for s in store._data["sessions"].values()) == 50
    assert store.account_for_session(theirs) == b  # another account's sessions are untouched


def test_expired_sessions_are_dropped_when_a_new_one_is_made(tmp_path):
    store = AccountStore(tmp_path / "accounts.json")
    a = store.create_account("old@example.com", "password123")
    store._data["sessions"]["stale"] = {"account_id": "someone", "expires": time.time() - 1}
    store.create_session(a)
    assert "stale" not in store._data["sessions"] and len(store._data["sessions"]) == 1


# --- L2: an unknown email costs a hash too -------------------------------------------------------------------------


def test_an_unknown_email_hashes_like_a_known_one(tmp_path, monkeypatch):
    store = AccountStore(tmp_path / "accounts.json")
    store.create_account("known@example.com", "password123")
    calls = []
    real = accounts._hash_password
    monkeypatch.setattr(accounts, "_hash_password", lambda p, s: (calls.append(s), real(p, s))[1])
    for email in ("known@example.com", "nobody@example.com"):
        with pytest.raises(AuthError) as exc:
            store.verify_login(email, "wrongpassword")
        assert str(exc.value) == "Wrong email or password."
    assert len(calls) == 2


# --- L3: Secure cookie over HTTPS, security headers -----------------------------------------------------------------


def _cookie(r) -> str:
    return next(v for k, v in r.headers.multi_items() if k == "set-cookie" and v.startswith("openmob_session="))


def test_the_session_cookie_is_secure_only_over_https(app_store, monkeypatch):
    app, store = app_store
    store.create_account("cookie@example.com", "password123")
    monkeypatch.delenv("FLY_APP_NAME", raising=False)
    plain = _login(TestClient(app), "cookie@example.com")
    assert plain.status_code == 200 and "secure" not in _cookie(plain).lower()
    assert "strict-transport-security" not in plain.headers
    https = _login(TestClient(app, base_url="https://testserver"), "cookie@example.com")
    assert "secure" in _cookie(https).lower().split("; ") and https.headers["strict-transport-security"]


def test_on_fly_the_forwarded_proto_is_trusted_and_nowhere_else(app_store, monkeypatch):
    app, store = app_store
    store.create_account("fly@example.com", "password123")
    forwarded = {"x-forwarded-proto": "https"}
    monkeypatch.delenv("FLY_APP_NAME", raising=False)
    r = TestClient(app, client=("203.0.113.5", 1)).post(
        "/api/auth/login", json={"email": "fly@example.com", "password": "password123"}, headers=forwarded)
    assert "secure" not in _cookie(r).lower() and "strict-transport-security" not in r.headers
    monkeypatch.setenv("FLY_APP_NAME", "openmob")
    r = TestClient(app, client=("203.0.113.5", 1)).post(
        "/api/auth/login", json={"email": "fly@example.com", "password": "password123"}, headers=forwarded)
    assert "secure" in _cookie(r).lower().split("; ") and r.headers["strict-transport-security"].startswith("max-age=")


@pytest.mark.parametrize("path", ["/", "/connect", "/api/auth/me", "/no-such-page"])
def test_every_response_has_the_security_headers(app_store, path):
    app, _ = app_store
    r = TestClient(app).get(path)
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "same-origin"
    assert r.headers["x-frame-options"] == "DENY"
    # The signed-out landing page has its own, stricter policy, with frame-ancestors 'none' in it (test_landing.py).
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"].split("; ")
    if path != "/":
        assert r.headers["content-security-policy"] == "frame-ancestors 'none'"


def test_a_413_has_the_security_headers_too(app_store):
    app, _ = app_store
    r = TestClient(app).post("/api/auth/login", content=b"x" * (MAX_BODY + 1))
    assert r.status_code == 413 and r.headers["x-frame-options"] == "DENY"


# --- L4: SRI on the pairing page's QR library ----------------------------------------------------------------------


def test_every_cdn_script_has_sri():
    for page in server.STATIC.glob("*.html"):
        for tag in re.findall(r"<script[^>]*src=\"https://[^\"]+\"[^>]*>", page.read_text()):
            assert 'integrity="sha512-' in tag and 'crossorigin="anonymous"' in tag, (page.name, tag)
    connect = (server.STATIC / "connect.html").read_text()
    assert ("qrcode.min.js\" integrity=\"sha512-CNgIRecGo7nphbeZ04Sc13ka07paqdeTu0WR1IM4kNcpmBAUSHSQX0FslNhTDadL4O5SAGa"
            "pGt4FodqL8My0mA==\"") in connect


# --- L8: ASCII look-alikes ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("existing,lookalike", [
    ("jordan@mail.example.com", "j0rdan@mail.example.com"), ("alice@example.com", "a1ice@example.com"),
    ("mary@example.com", "rnary@example.com"), ("will@example.com", "vvill@example.com"),
    ("greg@example.com", "qreg@example.com"), ("jordan@mail.example.com", "jor.dan@mail.example.com"),
    ("jordan@mail.example.com", "jordan@mai1.example.com"),
])
def test_an_ascii_look_alike_is_refused_at_sign_up(tmp_path, existing, lookalike):
    store = AccountStore(tmp_path / "accounts.json")
    store.create_account(existing, "password123")
    with pytest.raises(AccountLookAlike):
        store.create_account(lookalike, "password123")
    assert email_skeleton(existing) == email_skeleton(lookalike)


def test_different_emails_still_sign_up(tmp_path):
    store = AccountStore(tmp_path / "accounts.json")
    for email in ("bob@example.com", "rob@example.com", "user2@example.com", "user3@example.com", "bob@example.org"):
        store.create_account(email, "password123")
    assert email_skeleton("first.last@example.com") == "firstlast@example.com"  # dots dropped in the local part only


# --- L9: other dashes, "|", bullets and direction marks are separators (the shared detector: server and phone) -------
# The full set of cases, positive and negative, is in tests/fixtures/gatekeeper/build.py (review 4 L9), which pins
# sensitive.py, gatekeeper_ref.py and SensitiveNumbers.kt to the same answers. These check the outward redaction.


@pytest.mark.parametrize("text", [
    "SSN 123–45–6789", "123—45—6789", "123−45−6789", "123|45|6789",
    "card 4111–1111–1111–1111", "4111 | 1111 | 1111 | 1111", "4111•1111•1111•1111",
    "4111‎-1111‏-1111‪-1111", "123⁦-⁩45⁦-⁩6789",
    "4111‐1111‑1111―1111",
])
def test_redaction_catches_other_separators(text):
    out = sensitive.redact(text)
    assert sensitive.REDACTED in out and not re.search(r"[0-9]", out), out
    assert sensitive.find(text) in (sensitive.CARD, sensitive.SSN)  # the gate asks too


def test_redaction_still_catches_what_it_did_and_keeps_the_rest():
    assert sensitive.redact("SSN|123-45-6789 ok") == f"SSN|{sensitive.REDACTED} ok"  # "|" before it isn't a dash
    assert sensitive.redact("pay 4111 1111 1111 1111 now") == f"pay {sensitive.REDACTED} now"
    assert sensitive.redact("call 555–123–4567 | room 12") == "call 555–123–4567 | room 12"
    assert sensitive.redact("pages 10–20 • 2026–10–18") == "pages 10–20 • 2026–10–18"
    assert sensitive.redact("a 4111-1111-1111-1111 b 123–45–6789 c") == (
        f"a {sensitive.REDACTED} b {sensitive.REDACTED} c")


# --- a stale answer never answers a later question ----------------------------------------------------------------


class _HeldQueue(queue.Queue):
    """Hands out answers only once `release` is set, so two answers can land before the question takes one."""

    def __init__(self):
        super().__init__()
        self.release = threading.Event()

    def get(self, block=True, timeout=None):
        if block:  # the question's wait (draining with get_nowait isn't held)
            self.release.wait(5)
        return super().get(block, timeout)


def _asking(c, fn, *args):
    out = []
    t = threading.Thread(target=lambda: out.append(fn(*args)), daemon=True)
    t.start()
    deadline = time.monotonic() + 5
    while c.question is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert c.question is not None
    return t, out


def test_a_second_quick_yes_never_approves_the_next_confirm():
    c = Coordinator(Speaker(enabled=False))
    c.current_task = "t1"
    c.question_timeout = 0
    c.answers = held = _HeldQueue()
    t, out = _asking(c, c.ask, "Which one?")
    assert c.answer("t1", "yes") and c.answer("t1", "yes")  # two quick answers to one question
    held.release.set()
    t.join(5)
    assert out == ["yes"]
    t, out = _asking(c, c.confirm, "Buy it for $500?")
    t.join(0.5)
    assert t.is_alive() and out == [], "the leftover yes approved the purchase"
    assert c.answer("t1", "no")
    t.join(5)
    assert out == ["no"]


def test_a_typed_answer_is_for_its_own_question_only():
    c = Coordinator(Speaker(enabled=False))
    c.current_task = "t1"
    c.question_timeout = 0
    c.answers = held = _HeldQueue()
    t, out = _asking(c, c.ask, "Which one?")
    assert c.submit("the first", "dashboard") == "answered" and c.submit("yes", "dashboard") == "answered"
    held.release.set()
    t.join(5)
    assert out == ["the first"]
    t, out = _asking(c, c.ask, "And then?")
    t.join(0.5)
    assert t.is_alive() and out == []
    c.submit("the second", "dashboard")
    t.join(5)
    assert out == ["the second"]


# --- the phone's own unpair: removed first, then its sockets closed -------------------------------------------------


def test_the_phones_unpair_removes_it_before_closing_its_sockets(srv, monkeypatch):  # noqa: F811
    user = srv.user("unpair@example.com")
    key = srv.claim(user.post("/api/pairing").json()["code"], "phone-u").json()["key"]
    order = []
    remove, close = srv.manager.remove, srv.manager.close_links
    monkeypatch.setattr(srv.manager, "remove", lambda *a, **k: (order.append("remove"), remove(*a, **k))[1])
    monkeypatch.setattr(srv.manager, "close_links", lambda *a, **k: (order.append("close"), close(*a, **k))[1])
    r = httpx.post(f"{srv.base}/api/phone/unpair", json={"device_id": "phone-u"}, headers={"x-openmob-device-key": key})
    assert r.status_code == 200 and order == ["remove", "close"]


# --- cancelling a typed code is same-site only, like minting one ----------------------------------------------------


def test_cancelling_a_typed_code_from_another_site_is_refused(srv):  # noqa: F811
    user = srv.user("cancel@example.com")
    assert user.post("/api/pairing/code").status_code == 200
    r = user.delete("/api/pairing/code", headers={"sec-fetch-site": "cross-site", "origin": "https://evil.example"})
    assert r.status_code == 403
    assert user.get("/api/pairing/code").json()["status"] == "waiting"  # still live
    assert user.delete("/api/pairing/code", headers={"sec-fetch-site": "same-origin"}).status_code == 200


# --- webhook addresses: CGNAT and the other non-public ranges -------------------------------------------------------


@pytest.mark.parametrize("address", [
    "100.64.0.1", "100.127.255.254", "0.1.2.3", "192.0.0.8", "198.18.0.1", "198.19.255.1", "240.0.0.1",
    "fd00::1", "fe80::1", "::ffff:127.0.0.1", "::ffff:10.0.0.1", "::ffff:100.64.0.1", "64:ff9b::7f00:1",
    "64:ff9b::a00:1", "64:ff9b::808:808", "127.0.0.1", "10.0.0.1", "169.254.169.254", "::1",
])
def test_non_public_addresses_are_refused(address, monkeypatch):
    import ipaddress

    assert not public_ip(ipaddress.ip_address(address))
    monkeypatch.setattr("socket.getaddrinfo", lambda host, port: [(None, None, None, "", (address, 0))])
    assert not is_public_address("hook.example.com")


@pytest.mark.parametrize("address", ["8.8.8.8", "1.1.1.1", "2001:4860:4860::8888", "::ffff:8.8.8.8"])
def test_public_addresses_are_allowed(address, monkeypatch):
    monkeypatch.setattr("socket.getaddrinfo", lambda host, port: [(None, None, None, "", (address, 0))])
    assert is_public_address("hook.example.com")


# --- a refused key PATCH changes nothing ---------------------------------------------------------------------------


def test_a_refused_key_patch_changes_nothing(srv):  # noqa: F811
    user = srv.user("keys@example.com")
    key = user.post("/api/developer/keys", json={"password": "password123", "name": "k", "scopes": ["devices:read"]}).json()
    before = next(k for k in user.get("/api/developer/keys").json() if k["id"] == key["id"])
    r = user.patch(f"/api/developer/keys/{key['id']}",
                   json={"max_mode": "trusted", "confirm_approve": not before["confirm_approve"], "faster_drive": True})
    assert r.status_code == 403
    after = next(k for k in user.get("/api/developer/keys").json() if k["id"] == key["id"])
    assert after["max_mode"] == before["max_mode"] and after["confirm_approve"] == before["confirm_approve"]
