"""Security review 3, pairing (reviewer K): each finding's proof of concept, now asserting the fixed behaviour.

- K3-H1: claimed typed codes held their slot for a day while the cap counted only live ones, so a full slot
  table made minting spin forever inside the store's lock (sign-in and sessions froze with it).
- K3-H2: a wrong guess into any slot record, live or dead, counted against its account, and that count also
  locked the account's QR code: a blind spray locked the owner out of all pairing.
- K3-M1: per-address limits keyed IPv6 by the whole address, failure windows never forgot a key, and every
  wrong typed guess rewrote accounts.json.
- K3-M2: any email with an "@" made an account, so a look-alike of the owner's address could name a
  stranger's code on the phone's confirm screen.
"""

import itertools
import threading
import time
from types import SimpleNamespace

import pytest
from test_pairing_code import Env, wrong_secret

from openmob import accounts
from openmob.accounts import (TYPED_ALPHABET, TYPED_MAX_FAILURES, AccountExists, AccountLookAlike, AccountStore,
                              AuthError, PairingLimit, PairingRefused, email_skeleton)
from openmob.server import FailureWindow, client_bucket


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def finishes(fn, seconds=5.0):
    """Run `fn` in a thread; (finished in time, its result or exception)."""
    out = []
    t = threading.Thread(target=lambda: out.append(_call(fn)), daemon=True)
    t.start()
    t.join(seconds)
    return (not t.is_alive()), (out[0] if out else None)


def _call(fn):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - handed back to the test
        return exc


# --- K3-H1: the slot table can't fill up and minting never spins ------------------------------------------


def test_claimed_codes_free_their_slot_so_961_claims_dont_exhaust_the_table(tmp_path, monkeypatch):
    """poc_slot_exhaustion.py: two accounts claim 961 typed codes within the hourly limit (simulated clock)."""
    clock = [time.time()]
    monkeypatch.setattr(accounts.time, "time", lambda: clock[0])
    s = AccountStore(tmp_path / "accounts.json")
    monkeypatch.setattr(s, "_save", lambda: None)  # speed only
    a, b = (s.create_account(f"a{i}@example.com", "password123") for i in (1, 2))
    victim = s.create_account("owner@example.com", "password123")
    for n in range(962):
        acct = (a, b)[n % 2]
        code, _ = s.create_typed_code(acct)
        s.check_pairing_code(code, f"fake-{n}", "x")
        s.redeem_pairing_code(code, None, f"fake-{n}", "x")
        if n % 2:
            clock[0] += 121  # 2 mints per 121 s per account: under 30 an hour
        assert len(s._data["typed_codes"]) == 0  # a claimed code leaves its slot at once
    done, got = finishes(lambda: s.create_typed_code(victim))
    assert done and isinstance(got, tuple), got
    assert finishes(lambda: s.account_for_session("whatever"))[0]  # the store's lock isn't held
    assert s.typed_code_status(a)["status"] == "paired"  # the dashboard still sees the last claim


def test_a_full_slot_table_refuses_a_mint_instead_of_spinning(tmp_path, monkeypatch):
    s = AccountStore(tmp_path / "accounts.json")
    monkeypatch.setattr(s, "_save", lambda: None)
    monkeypatch.setattr(accounts, "TYPED_MAX_LIVE", 10_000)  # take the cap away: only the free-slot check is left
    now = time.time()
    s._data["typed_codes"] = {
        x + y: {"account_id": "someone", "hash": f"h{x}{y}", "created": now, "expires": now + 300, "used": False,
                "voided": False, "checked_by": None, "checked_model": None, "device_id": None,
                "epoch": s._typed_epoch}
        for x in TYPED_ALPHABET for y in TYPED_ALPHABET
    }
    acct = s.create_account("owner@example.com", "password123")
    done, got = finishes(lambda: s.create_typed_code(acct))
    assert done and isinstance(got, PairingLimit)


def test_the_cap_counts_every_record_that_holds_a_slot(env, monkeypatch):
    """Voided and cancelled codes hold their slot until they expire, so they count against the cap too."""
    monkeypatch.setattr(accounts, "TYPED_MAX_LIVE", 2)
    one, two, three = (env.store.create_account(f"u{i}@example.com", "password123") for i in range(3))
    env.store.create_typed_code(one)
    env.store.create_typed_code(two)
    env.store.cancel_typed_code(one)
    env.store.cancel_typed_code(two)
    with pytest.raises(PairingLimit):
        env.store.create_typed_code(three)


# --- K3-H2: blind guessing locks nobody out ----------------------------------------------------------------


def test_a_blind_spray_of_every_slot_doesnt_lock_the_owners_pairing(env, monkeypatch):
    """poc_blind_lockout.py: 961 slots x 10 wrong secrets, each 10 from a fresh /64. Before, every slot record
    (live or dead) named its account, the account count hit 10, and the owner's QR code got 429."""
    monkeypatch.setenv("FLY_APP_NAME", "openmob")
    owner = env.user("owner@example.com")
    owner.post("/api/pairing/code")  # a live typed code somewhere in the 961 slots
    saves = [0]
    real_save = env.store._save
    monkeypatch.setattr(env.store, "_save", lambda: (saves.__setitem__(0, saves[0] + 1), real_save())[1])
    c = env.client()
    nets = (f"2001:db8:{i:x}::1" for i in itertools.count())
    for x, y in itertools.product(TYPED_ALPHABET, TYPED_ALPHABET):
        ip = next(nets)  # 10 guesses per /64: just under the per-address limit
        for _ in range(10):
            r = c.post("/api/pair/check", json={"code": x + y + "2222", "device_id": "x", "model": "x"},
                       headers={"fly-client-ip": ip})
            assert r.status_code == 400, r.text
    assert saves[0] == 0  # wrong guesses no longer rewrite accounts.json
    # The owner's typed code may have been killed (5 tries), but nothing is locked: QR and a new typed code work.
    qr = owner.post("/api/pairing").json()["code"]
    assert env.check(qr, ip="198.51.100.7").status_code == 200
    assert env.claim(qr, "owner-phone", ip="198.51.100.7").status_code == 200
    fresh = owner.post("/api/pairing/code").json()["code"]
    assert env.check(fresh, "owner-phone-2", ip="198.51.100.8").status_code == 200


def test_one_ipv6_64_counts_as_one_address(env, monkeypatch):
    """The PoC's addresses were all inside one /64 (2001:db8:1:2::/64): they now share one limit."""
    monkeypatch.setenv("FLY_APP_NAME", "openmob")
    c = env.client()
    statuses = [c.post("/api/pair/check", json={"code": "ABC-DEF", "device_id": "x"},
                       headers={"fly-client-ip": f"2001:db8:1:2:{i:x}::1"}).status_code for i in range(11)]
    assert statuses == [400] * 10 + [429]
    other = c.post("/api/pair/check", json={"code": "ABC-DEF", "device_id": "x"},
                   headers={"fly-client-ip": "2001:db8:1:3::1"})
    assert other.status_code == 400  # the next /64 is someone else


def test_only_a_guess_into_a_live_code_names_its_account(env, monkeypatch):
    acct = env.store.create_account("o@example.com", "password123")
    live, _ = env.store.create_typed_code(acct)
    with pytest.raises(PairingRefused) as exc:
        env.store.check_pairing_code(wrong_secret(live), "x")
    assert exc.value.account_id == acct
    env.store.cancel_typed_code(acct)  # voided: still in its slot, but dead
    with pytest.raises(PairingRefused) as exc:
        env.store.check_pairing_code(wrong_secret(live), "x")
    assert exc.value.account_id is None
    expired, _ = env.store.create_typed_code(acct)
    now = time.time()
    monkeypatch.setattr(accounts.time, "time", lambda: now + accounts.TYPED_TTL + 1)
    for guess in (wrong_secret(expired), expired):
        with pytest.raises(PairingRefused) as exc:
            env.store.check_pairing_code(guess, "x")
        assert exc.value.account_id is None


def test_wrong_typed_codes_lock_typed_codes_only_never_the_qr_code(env):
    """Two live codes' worth of wrong tries (10) lock the account's typed codes; its QR code still pairs."""
    owner = env.user("owner@example.com")
    for i in range(10):
        if i % TYPED_MAX_FAILURES == 0:
            code = owner.post("/api/pairing/code").json()["code"]
        assert env.check(wrong_secret(code), "thief", ip=f"10.8.0.{i}").status_code == 400
    fresh = owner.post("/api/pairing/code").json()["code"]
    assert env.check(fresh, ip="10.8.1.1").status_code == 429
    qr = owner.post("/api/pairing").json()["code"]
    assert env.check(qr, ip="10.8.1.2").status_code == 200
    assert env.claim(qr, "owner-phone", ip="10.8.1.2").status_code == 200


def test_the_five_tries_live_in_memory_and_a_restart_voids_the_code_anyway(env):
    """Tries aren't written to accounts.json; a new process (a restart) can't use the code at all, so the
    5-tries cap can't be reset by restarting."""
    acct = env.store.create_account("o@example.com", "password123")
    code, _ = env.store.create_typed_code(acct)
    for _ in range(3):
        with pytest.raises(PairingRefused):
            env.store.check_pairing_code(wrong_secret(code), "x")
    assert env.store.typed_code_status(acct)["tries_left"] == 2
    restarted = AccountStore(env.tmp / "accounts.json")
    with pytest.raises(PairingRefused) as exc:
        restarted.check_pairing_code(code, "phone-1")
    assert exc.value.account_id is None


# --- K3-M1: bounded failure windows, /64 buckets ------------------------------------------------------------


def test_failure_windows_forget_stale_keys_and_cap_each_key(monkeypatch):
    clock = [1000.0]
    import openmob.server as server

    monkeypatch.setattr(server.time, "time", lambda: clock[0])
    w = FailureWindow(window=600)
    for i in range(5000):
        w.add(f"ip:{i}")
    for _ in range(500):
        w.add("acct:x")
    assert len(w.hits["acct:x"]) == FailureWindow.KEEP and w.count("acct:x") == FailureWindow.KEEP
    clock[0] += 601
    w.add("ip:new")
    assert set(w.hits) == {"ip:new"}


def test_client_bucket_groups_ipv6_by_64():
    def req(ip):
        return SimpleNamespace(headers={}, client=SimpleNamespace(host=ip))

    assert client_bucket(req("2001:db8:1:2:aaaa::1")) == client_bucket(req("2001:db8:1:2:ffff::9")) == "2001:db8:1:2::/64"
    assert client_bucket(req("2001:db8:1:3::1")) != client_bucket(req("2001:db8:1:2::1"))
    assert client_bucket(req("203.0.113.9")) == "203.0.113.9" != client_bucket(req("203.0.113.10"))
    assert client_bucket(req("::ffff:203.0.113.9")) == "203.0.113.9"
    assert client_bucket(req("testclient")) == "testclient"


# --- K3-M2: look-alike emails -------------------------------------------------------------------------------


LOOK_ALIKES = ("jordan@mai\u0456.example.com",  # Cyrillic i
               "j\u043erdan@mail.example.com",  # Cyrillic o
               "jordan@mail.example.com\u200b",  # a zero-width space
               "jordan+phone@mail.example.com")  # a +tag


def test_look_alikes_of_an_account_cant_sign_up(env):
    """poc_lookalike_email.py: each look-alike got its own account and its email on the confirm screen."""
    env.user("jordan@mail.example.com")
    for fake in LOOK_ALIKES:
        c = env.client("10.0.0.9")
        r = c.post("/api/auth/signup", json={"email": fake, "password": "password123",
                                             "invite": env.store.create_invite()})
        assert r.status_code in (200, 400), r.text  # 200 is the same reply as for an existing account
        assert c.post("/api/auth/login", json={"email": fake, "password": "password123"}).status_code == 401
    assert env.store.list_accounts() == ["jordan@mail.example.com"]


def test_new_emails_must_be_plain_ascii(env):
    for bad in ("j\u043erdan@mail.example.com", "a\u200b@example.com", "a\u00a0b@example.com", "a b@example.com",
                "\u00e9@example.com", "a@b", "@example.com", "a@@example.com", "a@example.com."):
        with pytest.raises(AuthError) as exc:
            env.store.create_account(bad, "password123")
        assert not isinstance(exc.value, AccountExists), bad
    # NFKC first: full-width letters are plain ones, so this is alice's own address.
    assert env.store.create_account("\uff41lice@example.com", "password123")
    assert env.store.list_accounts() == ["alice@example.com"]


def test_an_email_that_reads_like_an_old_account_is_refused(env):
    """Accounts made before the ASCII rule may hold look-alike letters; a new plain email is checked against them."""
    env.store._data["accounts"]["old"] = {"email": "j\u043erdan@mail.example.com", "salt": "s", "pw_hash": "h",
                                          "created": 0}
    with pytest.raises(AccountLookAlike):
        env.store.create_account("jordan@mail.example.com", "password123")
    with pytest.raises(AccountLookAlike):
        env.store.create_account("JORDAN+x@mail.example.com", "password123")
    assert env.store.create_account("jordan2@mail.example.com", "password123")
    assert email_skeleton("J\u043erdan+phone@M\u0430\u0456l.Example.com\u200b") == "jordan@mail.example.com"


# --- K3-L1: minting a QR code is POST-only, from this server's own pages ---------------------------------------


def test_a_qr_code_is_never_minted_by_a_get(env):
    owner = env.user("owner@example.com")
    acct = env.store.account_id_for("owner@example.com")
    assert owner.get("/api/pairing").status_code == 405  # a link or an <img> on any site can't mint one
    assert env.store._data["accounts"][acct].get("pairing_mints", []) == []
    assert owner.post("/api/pairing").status_code == 200


def test_another_sites_page_cant_mint_either_code(env):
    owner = env.user("owner@example.com")
    for path in ("/api/pairing", "/api/pairing/code"):
        for headers in ({"origin": "https://evil.example"}, {"sec-fetch-site": "cross-site"},
                        {"sec-fetch-site": "same-site"}, {"origin": "null"}):
            r = owner.post(path, headers=headers)
            assert r.status_code == 403, (path, headers, r.text)
        ok = owner.post(path, headers={"origin": "http://testserver", "sec-fetch-site": "same-origin"})
        assert ok.status_code == 200, (path, ok.text)
    acct = env.store.account_id_for("owner@example.com")
    assert len(env.store._data["accounts"][acct]["pairing_mints"]) == 2  # only the two same-origin mints


def test_the_connect_page_and_the_bridge_mint_with_post():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    assert 'api("/api/pairing", { method: "POST" })' in (root / "openmob/static/connect.html").read_text()
    assert 'client.post("/api/pairing"' in (root / "openmob/bridge.py").read_text()


# --- K3-L2: a code alone can't replace a phone that's paired now ---------------------------------------------


def test_a_code_and_a_known_device_id_cant_take_over_a_paired_phone(env):
    owner = env.user("owner@example.com")
    real = env.claim(owner.post("/api/pairing").json()["code"], "owners-phone")
    assert real.status_code == 200 and real.json()["trusted_for_approvals"] is True
    real_key = real.json()["key"]
    for code in (owner.post("/api/pairing").json()["code"], owner.post("/api/pairing/code").json()["code"]):
        if len(code) == 7:
            assert env.check(code, "owners-phone", ip="10.3.0.1").status_code == 200
        r = env.claim(code, "owners-phone", ip="10.3.0.1")  # the leaked code, the owner's phone's id
        assert r.status_code == 400 and "already paired with this account" in r.json()["detail"]
    assert env.store.verify_device("owners-phone", real_key)  # the real phone keeps its key
    assert env.store.trusted_for_approvals("owners-phone") is True


def test_the_paired_phone_itself_can_pair_again_with_its_key_and_gains_no_trust(env):
    owner = env.user("owner@example.com")
    first = env.claim(owner.post("/api/pairing").json()["code"], "phone-a").json()["key"]
    second = env.claim(owner.post("/api/pairing").json()["code"], "phone-b").json()["key"]
    assert env.store.trusted_for_approvals("phone-b") is False
    r = env.client().post("/api/pair/claim", json={"code": owner.post("/api/pairing").json()["code"],
                                                    "device_id": "phone-b", "model": "x"},
                          headers={"X-OpenMob-Device-Key": second})
    assert r.status_code == 200 and r.json()["trusted_for_approvals"] is False  # kept as it was
    assert owner.post("/api/devices/app-phone-a/revoke").status_code == 200
    # Phone b is now the only phone, but a key-proven re-pair keeps its own trust: never "first" again.
    r = env.client().post("/api/pair/claim", json={"code": owner.post("/api/pairing").json()["code"],
                                                    "device_id": "phone-b", "model": "x"},
                          headers={"X-OpenMob-Device-Key": r.json()["key"]})
    assert r.status_code == 200 and r.json()["trusted_for_approvals"] is False
    wrong = env.client().post("/api/pair/claim", json={"code": owner.post("/api/pairing").json()["code"],
                                                        "device_id": "phone-b", "model": "x"},
                              headers={"X-OpenMob-Device-Key": first})  # another phone's key proves nothing
    assert wrong.status_code == 400
    assert first  # phone a's key was real, just not phone b's


def test_a_removed_phone_pairs_again_with_a_code_alone(env):
    owner = env.user("owner@example.com")
    env.claim(owner.post("/api/pairing").json()["code"], "phone-a")
    assert owner.post("/api/devices/app-phone-a/revoke").status_code == 200
    assert env.claim(owner.post("/api/pairing").json()["code"], "phone-a").status_code == 200


# --- K3-L3: the phone's list of server sentences matches what the server says --------------------------------


def test_the_phones_known_sentences_are_the_servers_own():
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    kotlin = (root / "android/app/src/main/java/dev/openmob/companion/PairingFlow.kt").read_text()
    block = kotlin.split("KNOWN_SENTENCES = setOf(", 1)[1].split("\n    )", 1)[0]
    known = set(re.findall(r'"((?:[^"\\]|\\.)*)"', block))
    server = (root / "openmob/accounts.py").read_text() + (root / "openmob/server.py").read_text()
    server = server.replace('"\n                                 "', "").replace('" "', "")  # join split literals
    for sentence in known:
        assert sentence.replace("'", "\\'") in server or sentence in server, sentence
    assert accounts.WRONG_TYPED_CODE in known
