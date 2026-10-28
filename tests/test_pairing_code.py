"""The typed pairing code (docs/design/pairing-code.md): the fallback to the QR code.

6 characters made by the signed-in dashboard, typed on the phone. Covered here: the alphabet and
normalizing, the same result as a QR pairing, expiry, the 5-try lockout, single use, a replay, the
check-then-claim binding to one phone, rate limits per address and per account, the wrong
account, the code never in logs, history or the store, the dashboard status and Undo.
"""

import logging
import time

import pytest
from fastapi.testclient import TestClient
from test_easy_connect import _manager
from test_remote import new_signer, public_key_b64

from openmob import accounts
from openmob.accounts import (TYPED_ALPHABET, WRONG_TYPED_CODE, AccountStore, AuthError, PairingLimit, PairingMalformed,
                              PairingRefused, normalize_typed_code)
from openmob.ledger import Ledger
from openmob.server import create_app


class Env:
    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.store = AccountStore(tmp_path / "accounts.json")
        self.ledger = Ledger(tmp_path / "ledger.sqlite")
        self.manager = _manager(tmp_path)
        self.app = create_app(self.manager, store=self.store, ledger=self.ledger)

    def client(self, ip="10.9.0.1"):
        return TestClient(self.app, client=(ip, 1))

    def user(self, email, ip="10.0.0.1"):
        c = self.client(ip)
        c.post("/api/auth/signup", json={"email": email, "password": "password123", "invite": self.store.create_invite()})
        assert c.post("/api/auth/login", json={"email": email, "password": "password123"}).status_code == 200
        return c

    def check(self, code, device_id="phone-1", model="SM-S948U1", ip="10.9.0.1"):
        return self.client(ip).post("/api/pair/check", json={"code": code, "device_id": device_id, "model": model})

    def claim(self, code, device_id="phone-1", model="SM-S948U1", ip="10.9.0.1", **extra):
        return self.client(ip).post("/api/pair/claim",
                                    json={"code": code, "device_id": device_id, "model": model, **extra})

    def pair(self, code, device_id="phone-1", ip="10.9.0.1", **extra):
        assert self.check(code, device_id, ip=ip).status_code == 200
        return self.claim(code, device_id, ip=ip, **extra)


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def wrong_secret(code):
    """Same slot (first 2 characters), a different secret: a guess that hits this code."""
    norm = normalize_typed_code(code)
    tail = "".join(TYPED_ALPHABET[(TYPED_ALPHABET.index(ch) + 1) % len(TYPED_ALPHABET)] for ch in norm[2:])
    return norm[:2] + tail


# --- the code itself ------------------------------------------------------------------------------


def test_codes_use_no_look_alikes_and_any_case_and_dash(env):
    assert not set("01OIL") & set(TYPED_ALPHABET) and len(TYPED_ALPHABET) == 31
    alice = env.user("alice@example.com")
    for _ in range(20):
        p = alice.post("/api/pairing/code").json()
        assert len(p["code"]) == 7 and p["code"][3] == "-"
        assert set(p["code"].replace("-", "")) <= set(TYPED_ALPHABET)
    code = p["code"]
    for typed in (code, code.lower(), code.replace("-", ""), f"  {code[:3]} {code[4:]} ", code.replace("-", "–")):
        assert normalize_typed_code(typed) == code.replace("-", "")
    assert normalize_typed_code("K7P-2Q") is None and normalize_typed_code("K7P-2Q0") is None  # length, a zero


def test_mint_reply_and_only_a_signed_in_dashboard_can_make_one(env):
    assert env.client().post("/api/pairing/code").status_code == 401  # no session
    alice = env.user("alice@example.com")
    p = alice.post("/api/pairing/code").json()
    assert set(p) == {"code", "expires", "ttl", "tries", "email", "server"}
    assert 290 <= p["ttl"] <= 300 and p["tries"] == 5 and p["email"] == "alice@example.com"


def test_token_mode_has_no_typed_codes(tmp_path):
    app = create_app(_manager(tmp_path), token="t0k")
    c = TestClient(app)
    assert c.post("/api/pairing/code", headers={"X-OpenMob-Token": "t0k"}).status_code == 404
    assert c.post("/api/pair/check", json={"code": "ABC-DEF"}).status_code == 404


# --- the same result as a QR pairing ------------------------------------------------------------


def test_typed_pairing_gives_exactly_what_a_qr_pairing_gives(env):
    alice = env.user("alice@example.com")
    acct = env.store.account_id_for("alice@example.com")
    signer = public_key_b64(new_signer())
    qr = env.claim(alice.post("/api/pairing").json()["code"], "qr-phone", approval_key=signer)
    code = alice.post("/api/pairing/code").json()["code"]
    check = env.check(code.lower(), "typed-phone")
    assert check.status_code == 200 and check.json()["email"] == "alice@example.com" and check.json()["server"]
    typed = env.claim(code.lower(), "typed-phone", approval_key=signer)
    assert typed.status_code == 200, typed.text
    assert set(typed.json()) == set(qr.json()) == {"key", "server", "email", "device_id", "trusted_for_approvals"}
    assert "set-cookie" not in typed.headers
    assert env.store.verify_device("typed-phone", typed.json()["key"]) == acct
    # Same device record: same fields, same trust rule (the account's second phone isn't trusted).
    devs = env.store._data["devices"]
    assert set(devs["typed-phone"]) == set(devs["qr-phone"])
    assert devs["typed-phone"]["approval_key"] == signer and typed.json()["trusted_for_approvals"] is False
    actions = [r["action"] for r in env.ledger.audit_log(account_id=acct)]
    assert actions.count("device.paired") == 2


def test_a_phone_paired_to_another_account_stays_theirs(env):
    alice, bob = env.user("alice@example.com"), env.user("bob@example.com", ip="10.0.0.2")
    assert env.pair(bob.post("/api/pairing/code").json()["code"], "phone-1").status_code == 200
    r = env.pair(alice.post("/api/pairing/code").json()["code"], "phone-1")
    assert r.status_code == 400 and "another account" in r.json()["detail"]
    assert env.store.is_paired(env.store.account_id_for("bob@example.com"), "phone-1")


# --- expiry, single use, replay ------------------------------------------------------------------


def test_a_code_expires_after_5_minutes(env, monkeypatch):
    alice = env.user("alice@example.com")
    code = alice.post("/api/pairing/code").json()["code"]
    now = time.time()
    monkeypatch.setattr(accounts.time, "time", lambda: now + accounts.TYPED_TTL + 1)
    assert env.check(code).status_code == 400
    assert alice.get("/api/pairing/code").json()["status"] == "expired"


def test_single_use_and_a_replay_is_refused(env):
    alice = env.user("alice@example.com")
    code = alice.post("/api/pairing/code").json()["code"]
    assert env.pair(code, "phone-1").status_code == 200
    # The same code again: on the same phone, on another phone, by check or by claim.
    assert env.claim(code, "phone-1").status_code == 400
    assert env.check(code, "phone-2").status_code == 400
    assert env.claim(code, "phone-2").status_code == 400
    assert [d.id for d in env.store.list_devices(env.store.account_id_for("alice@example.com"))] == ["phone-1"]


def test_one_typed_code_per_account_a_new_one_voids_the_old(env):
    alice = env.user("alice@example.com")
    old = alice.post("/api/pairing/code").json()["code"]
    new = alice.post("/api/pairing/code").json()["code"]
    assert env.check(old).status_code == 400
    assert env.pair(new).status_code == 200


def test_a_qr_code_and_a_typed_code_are_independent(env):
    alice = env.user("alice@example.com")
    typed = alice.post("/api/pairing/code").json()["code"]
    qr = alice.post("/api/pairing").json()["code"]
    assert env.pair(typed, "phone-1").status_code == 200
    assert env.claim(qr, "phone-2").status_code == 200


# --- the binding to one phone --------------------------------------------------------------------


def test_claim_needs_a_check_from_the_same_phone_first(env):
    alice = env.user("alice@example.com")
    code = alice.post("/api/pairing/code").json()["code"]
    r = env.claim(code, "phone-1")  # no check: the owner never saw the confirm screen
    assert r.status_code == 400 and "confirm" in r.json()["detail"]
    assert env.check(code, "phone-1").status_code == 200
    assert env.claim(code, "phone-1").status_code == 200


def test_a_check_needs_the_phones_id(env):
    alice = env.user("alice@example.com")
    code = alice.post("/api/pairing/code").json()["code"]
    assert env.client().post("/api/pair/check", json={"code": code}).status_code == 400
    assert env.check(code).status_code == 200  # the code wasn't spent


def test_a_code_entered_on_a_second_phone_is_cancelled_for_both(env):
    alice = env.user("alice@example.com")
    code = alice.post("/api/pairing/code").json()["code"]
    assert env.check(code, "owners-phone").status_code == 200
    r = env.check(code, "attackers-phone")
    assert r.status_code == 400 and "another phone" in r.json()["detail"]
    assert env.claim(code, "owners-phone").status_code == 400
    assert env.claim(code, "attackers-phone").status_code == 400
    assert alice.get("/api/pairing/code").json()["status"] == "cancelled"


def test_the_dashboard_sees_which_phone_is_confirming_and_can_cancel(env):
    alice, bob = env.user("alice@example.com"), env.user("bob@example.com", ip="10.0.0.2")
    assert alice.get("/api/pairing/code").json() == {"status": "none"}
    code = alice.post("/api/pairing/code").json()["code"]
    s = alice.get("/api/pairing/code").json()
    assert s["status"] == "waiting" and s["tries_left"] == 5 and s["model"] is None
    assert env.check(code, "intruder", model="Pixel 9 Pro").status_code == 200
    s = alice.get("/api/pairing/code").json()
    assert s["status"] == "confirming" and s["model"] == "Pixel 9 Pro" and s["device_id"] == "app-intruder"
    assert bob.get("/api/pairing/code").json() == {"status": "none"}  # another account sees nothing of it
    bob.delete("/api/pairing/code")  # …and can't cancel it
    assert alice.get("/api/pairing/code").json()["status"] == "confirming"
    assert alice.delete("/api/pairing/code").json() == {"ok": True}
    assert env.claim(code, "intruder").status_code == 400
    assert alice.get("/api/pairing/code").json()["status"] == "cancelled"
    assert "code" not in s and code not in str(s)


# --- guessing ------------------------------------------------------------------------------------


def test_five_wrong_tries_void_the_code_and_only_the_dashboard_counts_them(env):
    alice = env.user("alice@example.com")
    code = alice.post("/api/pairing/code").json()["code"]
    wrong = wrong_secret(code)
    lefts = []
    for i in range(accounts.TYPED_MAX_FAILURES):
        r = env.check(wrong, "thief", ip=f"10.5.0.{i}")  # a new address each time: the code still dies
        assert r.status_code == 400 and r.json() == {"detail": WRONG_TYPED_CODE}
        assert not any("tries" in h.lower() for h in r.headers)  # the phone never learns the tries left
        lefts.append(alice.get("/api/pairing/code").json()["tries_left"])
    assert lefts == [4, 3, 2, 1, 0]
    assert env.check(code, "phone-1", ip="10.6.0.2").status_code == 400  # voided: the right code no longer works
    s = alice.get("/api/pairing/code").json()
    assert s["status"] == "cancelled" and s["tries_left"] == 0


def test_a_hit_and_a_miss_look_the_same_from_the_phone(env, monkeypatch):
    """A wrong secret in a live slot, an empty slot, a wrong secret for a spent code and the spent code
    itself: the same status, body and headers on check and claim, and the same work on the server
    (HMACs computed, store writes), so no timing tell either."""
    alice, bob = env.user("alice@example.com"), env.user("bob@example.com", ip="10.0.0.2")
    live = alice.post("/api/pairing/code").json()["code"]
    spent = bob.post("/api/pairing/code").json()["code"]
    assert env.pair(spent, "bobs-phone").status_code == 200
    taken = set(env.store._data["typed_codes"])
    empty = next(a + b for a in TYPED_ALPHABET for b in TYPED_ALPHABET if a + b not in taken) + "2345"
    work = {"hash": 0, "save": 0}
    real_hash, real_save = env.store._typed_hash, env.store._save

    def counted_hash(c):
        work["hash"] += 1
        return real_hash(c)

    def counted_save():
        work["save"] += 1
        return real_save()

    monkeypatch.setattr(env.store, "_typed_hash", counted_hash)
    monkeypatch.setattr(env.store, "_save", counted_save)
    replies, costs = [], []
    for i, guess in enumerate([wrong_secret(live), empty, wrong_secret(spent), spent]):
        work.update(hash=0, save=0)
        for j, call in enumerate((env.check, env.claim)):
            r = call(guess, "thief", ip=f"10.4.{i}.{j}")
            headers = tuple(sorted((k, v) for k, v in r.headers.items() if k.lower() != "date"))
            replies.append((r.status_code, r.text, headers))
        costs.append(tuple(work.items()))
    assert len(set(replies)) == 1, replies
    assert replies[0][0] == 400 and replies[0][1] == '{"detail":"%s"}' % WRONG_TYPED_CODE
    assert len(set(costs)) == 1, costs


def test_wrong_tries_on_check_and_claim_share_the_count(env):
    alice = env.user("alice@example.com")
    code = alice.post("/api/pairing/code").json()["code"]
    for i in range(4):
        (env.check if i % 2 else env.claim)(wrong_secret(code), ip=f"10.5.1.{i}")
    assert alice.get("/api/pairing/code").json()["tries_left"] == 1
    env.check(wrong_secret(code), ip="10.5.1.9")
    assert alice.get("/api/pairing/code").json()["status"] == "cancelled"


def test_a_malformed_code_is_not_counted_as_a_guess(env):
    alice = env.user("alice@example.com")
    code = alice.post("/api/pairing/code").json()["code"]
    for _ in range(15):  # more than the per-address limit
        r = env.check("K7P-2Q")
        assert r.status_code == 400 and "6 letters and numbers" in r.json()["detail"]
    assert env.pair(code).status_code == 200


def test_guesses_are_limited_per_address(env):
    alice = env.user("alice@example.com")
    statuses = [env.check("ABC-DEF", ip="10.7.0.1").status_code for _ in range(10)]  # an empty slot
    assert set(statuses) == {400}
    assert env.check("ABC-DEF", ip="10.7.0.1").status_code == 429
    code = alice.post("/api/pairing/code").json()["code"]
    assert env.check(code, ip="10.7.0.1").status_code == 429  # even the right code, from that address
    assert env.pair(code, ip="10.7.0.2").status_code == 200


def test_guesses_are_limited_per_account_across_addresses(env):
    alice = env.user("alice@example.com")
    for i in range(10):  # two codes' worth of wrong tries, each from a new address
        if i % 5 == 0:
            code = alice.post("/api/pairing/code").json()["code"]
        env.check(wrong_secret(code), "thief", ip=f"10.8.0.{i}")
    fresh = alice.post("/api/pairing/code").json()["code"]
    r = env.check(fresh, ip="10.8.1.1")
    assert r.status_code == 429 and "this account" in r.json()["detail"]
    assert alice.get("/api/pairing/code").json()["status"] == "waiting"  # not bound to the locked-out phone


def test_an_empty_slot_tells_nothing_and_hits_no_account(env):
    env.user("alice@example.com")
    with pytest.raises(PairingRefused) as exc:
        env.store.check_pairing_code("ABC-DEF", "x")
    assert exc.value.account_id is None and str(exc.value) == WRONG_TYPED_CODE
    with pytest.raises(PairingMalformed):
        env.store.check_pairing_code("ABC-DE0", "x")


def test_minting_shares_the_hourly_limit_and_the_server_wide_cap(env, monkeypatch):
    acct = env.store.create_account("o@example.com", "password123")
    monkeypatch.setattr(accounts, "PAIRING_MINTS_PER_HOUR", 3)
    env.store.create_pairing_code(acct)
    env.store.create_typed_code(acct)
    env.store.create_typed_code(acct)
    with pytest.raises(PairingLimit):
        env.store.create_typed_code(acct)
    monkeypatch.setattr(accounts, "PAIRING_MINTS_PER_HOUR", 30)
    monkeypatch.setattr(accounts, "TYPED_MAX_LIVE", 2)
    other = env.store.create_account("p@example.com", "password123")
    env.store.create_typed_code(other)
    with pytest.raises(PairingLimit):
        env.store.create_typed_code(env.store.create_account("q@example.com", "password123"))


def test_slots_never_collide(env):
    ids = [env.store.create_account(f"u{i}@example.com", "password123") for i in range(60)]
    codes = [env.store.create_typed_code(a)[0] for a in ids]
    assert len({c[:2] for c in codes}) == 60


# --- the wrong account ---------------------------------------------------------------------------


def test_the_wrong_accounts_session_cant_redeem_it(env):
    alice, bob = env.user("alice@example.com"), env.user("bob@example.com", ip="10.0.0.2")
    code = alice.post("/api/pairing/code").json()["code"]
    assert env.check(code).status_code == 200
    r = env.client().post("/api/pair/redeem", headers={"X-OpenMob-Session": bob.cookies["openmob_session"]},
                          json={"code": code, "device_id": "phone-1", "model": "x"})
    assert r.status_code == 400 and "different account" in r.json()["detail"]
    # The code, claimed, pairs the phone to Alice, never to whoever claims it.
    assert env.claim(code).status_code == 200
    assert env.store.is_paired(env.store.account_id_for("alice@example.com"), "phone-1")


# --- nothing logged ------------------------------------------------------------------------------


def test_the_code_never_appears_in_logs_history_or_the_store(env, capfd, caplog):
    caplog.set_level(logging.DEBUG)
    alice = env.user("alice@example.com")
    code = alice.post("/api/pairing/code").json()["code"]
    norm = code.replace("-", "")
    env.check(wrong_secret(code))
    env.check(code)
    env.claim(code)
    replies = [env.check(code, "p2").text, env.claim(code, "p2").text, alice.get("/api/pairing/code").text]
    out, err = capfd.readouterr()
    logged = out + err + caplog.text + "".join(replies)
    for form in (code, norm, norm.lower()):
        assert form not in logged
    stored = (env.tmp / "accounts.json").read_text()
    assert norm not in stored and code not in stored
    audit = str(env.ledger.audit_log(account_id=env.store.account_id_for("alice@example.com")))
    assert norm not in audit and code not in audit
    for path in env.tmp.glob("*.sqlite*"):
        assert norm.encode() not in path.read_bytes() and code.encode() not in path.read_bytes()


def test_a_copied_store_cant_be_checked_offline(env):
    """The stored hash is keyed by a secret held in memory: another process can't confirm a guess."""
    acct = env.store.create_account("o@example.com", "password123")
    code, _ = env.store.create_typed_code(acct)
    copy = AccountStore(env.tmp / "accounts.json")
    with pytest.raises(PairingRefused):
        copy.check_pairing_code(code, "phone-1")
    assert env.store.check_pairing_code(code, "phone-1")["account_id"] == acct


# --- Undo ----------------------------------------------------------------------------------------


def test_undo_from_the_phone_needs_only_its_device_key(env):
    alice = env.user("alice@example.com")
    code = alice.post("/api/pairing/code").json()["code"]
    key = env.pair(code).json()["key"]
    assert alice.get("/api/pairing/code").json()["status"] == "paired"
    r = env.client().post("/api/phone/unpair", json={"device_id": "phone-1"}, headers={"X-OpenMob-Device-Key": key})
    assert r.status_code == 200
    with pytest.raises(AuthError):
        env.store.verify_device("phone-1", key)
    assert alice.get("/api/devices").json() == []


def test_undo_from_the_dashboard_removes_the_phone_it_names(env):
    alice = env.user("alice@example.com")
    code = alice.post("/api/pairing/code").json()["code"]
    key = env.pair(code, "phone-1").json()["key"]
    s = alice.get("/api/pairing/code").json()
    assert s["status"] == "paired" and s["device_id"] == "app-phone-1" and s["model"] == "SM-S948U1"
    assert alice.post(f"/api/devices/{s['device_id']}/revoke").status_code == 200
    with pytest.raises(AuthError):
        env.store.verify_device("phone-1", key)
    actions = [r["action"] for r in env.ledger.audit_log(account_id=env.store.account_id_for("alice@example.com"))]
    assert "device.removed" in actions


# --- the QR code isn't marked used by a typed pairing ---------------------------------------------


def test_devices_say_which_code_paired_them_so_the_qr_code_stays_live(env):
    alice = env.user("alice@example.com")
    qr = alice.post("/api/pairing").json()["code"]
    assert env.pair(alice.post("/api/pairing/code").json()["code"], "typed-phone").status_code == 200
    rows = {d["id"]: d for d in alice.get("/api/devices").json()}
    assert rows["app-typed-phone"]["paired_via"] == "typed"
    # The Connect page marks its QR code used only for a phone that wasn't paired with a typed code.
    assert 'd.paired_via !== "typed"' in env.client().get("/connect").text
    assert env.claim(qr, "qr-phone").status_code == 200  # and the QR code really is still live
    rows = {d["id"]: d for d in alice.get("/api/devices").json()}
    assert rows["app-qr-phone"]["paired_via"] == "qr"
