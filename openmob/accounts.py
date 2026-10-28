"""Accounts, device keys, and one-time pairing codes.

Pairing: the signed-in dashboard (or `openmob phone add`, with a `devices:add` API key) mints a
pairing code. The code itself is the credential: single use, valid for 2 minutes, bound to the
account that made it, 128 bits of secret, and stored only as a hash. The phone redeems it (after
its owner confirms with the screen lock) for its own revocable device key, and never holds a
dashboard session. Wrong guesses void a code after a few tries, and the server rate-limits
redemption per client address and per account. One phone can be revoked without touching the others.

Typed codes (the fallback when the camera can't scan, docs/design/pairing-code.md): 6 characters
the owner reads off the dashboard and types on the phone, like K7P-2QX. The first 2 characters
pick the code's slot, the last 4 are its secret, so a wrong guess counts against the code it hit:
5 wrong tries void it, which caps any guesser at 5 chances in 923,521 per code, however many
addresses they use. A typed code lives 5 minutes, works once, and must be checked by the phone
(which shows the account) before that same phone can claim it. It's stored as an HMAC under a key
held only in this process's memory, so a copy of accounts.json can't be brute-forced back into
live codes (a restart voids them). Claiming one gives a phone exactly what a QR code gives, and
frees its slot at once. Only a wrong try at a live code names its account (security review 3).

New accounts need a plain-ASCII email (after NFKC) that doesn't read like an existing account's:
the phone's confirm screen names the account by its email.

Developer API keys live here too: `om_live_<id>_<secret>`, shown once, stored as a hash, each
with its own scopes. An admin can switch off one key or a whole account's API access.

Storage is a single JSON file guarded by a lock — fine for one host. Only hashes of passwords,
session tokens, device keys and API keys are stored, never the secrets themselves. (Webhook
signing secrets are the exception: signing needs the secret itself.)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

PBKDF2_ROUNDS = 200_000
SESSION_TTL = 30 * 24 * 3600  # dashboard login lasts 30 days
SESSIONS_PER_ACCOUNT = 50  # live sign-ins one account keeps; a new one past this ends the oldest
PAIRING_TTL = 2 * 60  # a pairing code is valid for 2 minutes, once
PAIRING_ID_LEN = 8  # a code is <8 hex id><secret>: the id finds the record, the secret is checked as a hash
PAIRING_MAX_FAILURES = 5  # wrong secrets for one code before it's voided
PAIRING_MINTS_PER_HOUR = 30  # codes one account may make in an hour
# Typed codes: no look-alikes (0/O, 1/I/L), so 31 characters (log2(31^6) = 29.7 bits in all).
TYPED_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
TYPED_LEN = 6
TYPED_SLOT_LEN = 2  # 31^2 = 961 slots; the other 4 characters (31^4 = 923,521) are the secret
TYPED_TTL = 5 * 60  # a typed code works for 5 minutes, once
TYPED_MAX_FAILURES = 5  # wrong tries for one typed code before it's voided
TYPED_MAX_LIVE = len(TYPED_ALPHABET) ** TYPED_SLOT_LEN // 2  # live typed codes server-wide, then QR only
WRONG_TYPED_CODE = "Wrong code. Check it on your dashboard, or make a new one there."
_DASHES = "-\u2010\u2011\u2012\u2013\u2014\u2212"  # an optional dash, as phones' keyboards type it
LOGIN_LINK_TTL = 10 * 60  # a sign-in link from `openmob account link` works once, for 10 minutes
INVITE_TTL = 7 * 24 * 3600  # an invite code from `openmob account invite` works once, for 7 days
KEY_PREFIX = "om_live_"  # easy to grep for in leaked code and logs
# What an API key may do. screen:read (see the phone's screen) is sensitive, so it's never a default.
# devices:add (enroll phones with `openmob phone add`) is sensitive too, so it's never a default either.
# devices:drive (an outside agent operates the phone step by step over MCP, reading each screen's text) is
# sensitive too: never a default (docs/design/mcp-drive.md).
SCOPES = ("devices:read", "tasks:run", "tasks:read", "screen:read", "history:read",
          "devices:add", "devices:drive")
DEFAULT_SCOPES = ("devices:read", "tasks:run", "tasks:read")
KEY_MODES = ("ask", "plan", "auto", "trusted", "never")  # an API key's max_mode (permissions.MODES)
LAST_USED_EVERY = 60  # seconds between saves of a key's last-used time
WEBHOOK_SECRET_OVERLAP = 24 * 3600  # a replaced webhook secret still signs deliveries this long
# OPENMOB_DATA_DIR points at persistent storage when hosted (e.g. a Fly volume at /data).
DATA_DIR = Path(os.environ.get("OPENMOB_DATA_DIR") or Path.home() / ".config" / "openmob")
DEFAULT_STORE = DATA_DIR / "accounts.json"


class AuthError(RuntimeError):
    """Login failed, or a pairing code was wrong, expired, used, or for another account."""


class AccessDisabled(AuthError):
    """A valid API key whose key or account has been switched off by an admin."""


class InviteInvalid(AuthError):
    """The invite code is missing, unknown, already used or expired."""


class AccountExists(AuthError):
    """Sign-up with an email that already has an account (the server never tells the client)."""


class AccountLookAlike(AccountExists):
    """Sign-up with an email that reads like an existing account's (another letter case, a +tag, a Cyrillic or
    Greek look-alike letter). The phone's confirm screen names the account by its email, so two accounts that
    read the same would let a stranger's code pass for the owner's. Told apart from AccountExists only on the
    server's command line."""


class PairingRefused(AuthError):
    """A pairing code was wrong, expired, used or voided. `account_id` is the account the code's id
    belongs to, when the id matched one (so the server can rate-limit guesses per account). For a typed
    code, only when the guess hit a live code: a dead slot names nobody (security review 3)."""

    def __init__(self, message: str, account_id: str | None = None):
        super().__init__(message)
        self.account_id = account_id


class PairingMalformed(AuthError):
    """Not a pairing code at all (a typed code of the wrong length or characters). It can't hit any
    code, so it doesn't count as a guess."""


class PairingLimit(AuthError):
    """Too many pairing codes made by one account in the last hour."""


@dataclass
class Device:
    id: str
    account_id: str
    model: str
    created: float
    last_seen: float
    revoked: bool
    paired_at: float = 0.0  # the latest pairing (a re-pair moves it; `created` stays the first)
    paired_via: str | None = None  # "qr" or "typed" (None: paired before this was recorded)
    trusted: bool = True  # may answer approvals for the owner's other phones (see trust_device)


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ROUNDS).hex()


_DUMMY_SALT = secrets.token_hex(16)  # an unknown email's sign-in hashes under this, for the same work


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def normalize_email(email: str) -> str:
    return unicodedata.normalize("NFKC", email or "").strip().lower()


# Cyrillic and Greek letters that read as Latin ones (lowercase: emails are compared lowercased). Only
# accounts made before plain-ASCII emails were required can hold them; a new email is checked against those.
_CONFUSABLES = str.maketrans({
    "а": "a", "в": "b", "е": "e", "ё": "e", "һ": "h", "і": "i", "ї": "i", "ј": "j", "к": "k", "м": "m",
    "н": "h", "о": "o", "р": "p", "с": "c", "ѕ": "s", "т": "t", "у": "y", "х": "x", "ԁ": "d", "ԛ": "q",
    "ԝ": "w", "ӏ": "l", "α": "a", "β": "b", "ε": "e", "η": "n", "ι": "i", "κ": "k", "ν": "v", "ο": "o",
    "ρ": "p", "τ": "t", "υ": "u", "χ": "x", "ω": "w", "ϲ": "c", "ϳ": "j",
})


def plain_email(email: str) -> bool:
    """A new account's email: printable ASCII after NFKC (no spaces, no zero-width or other format characters,
    no look-alike letters from other scripts), one @, something on each side."""
    local, _, domain = email.partition("@")
    return (email.isascii() and email.isprintable() and " " not in email and bool(local) and "." in domain
            and "@" not in domain and not domain.startswith(".") and not domain.endswith("."))


# ASCII look-alikes, folded after the letters above (security review 4, L8): "rn" reads as "m", "vv" as "w".
_ASCII_LOOKALIKES = (("rn", "m"), ("vv", "w"), ("0", "o"), ("1", "l"), ("q", "g"))


def email_skeleton(email: str) -> str:
    """What an email reads as, for spotting look-alike accounts: lowercased, look-alike letters folded to
    Latin, ASCII look-alikes folded (0/o, 1/l, rn/m, vv/w, q/g), invisible characters dropped, and the local
    part's +tag and dots left off.

    Only for refusing a new sign-up that reads like an existing account, never for identity: an email is still
    its own account. Dropping dots is right for Gmail but not for most other domains, so a.b@example.com and
    ab@example.com (two real people) can't both sign up: a false positive only refuses a sign-up."""
    folded = "".join(ch for ch in normalize_email(email).translate(_CONFUSABLES)
                     if unicodedata.category(ch) not in ("Cf", "Cc", "Zs", "Mn"))
    for seen, reads in _ASCII_LOOKALIKES:
        folded = folded.replace(seen, reads)
    local, _, domain = folded.rpartition("@")
    return f"{local.split('+', 1)[0].replace('.', '')}@{domain}"


def _strip_typed(code: str | None) -> str:
    return "".join(ch for ch in (code or "") if not ch.isspace() and ch not in _DASHES)


def normalize_typed_code(code: str | None) -> str | None:
    """A typed code in its stored form (capitals, no spaces or dashes), or None if it isn't one."""
    s = _strip_typed(code).upper()
    return s if len(s) == TYPED_LEN and all(ch in TYPED_ALPHABET for ch in s) else None


def looks_typed(code: str | None) -> bool:
    """Meant as a typed code, not a QR code (30 characters), so a typo gets the typed code's message."""
    return 0 < len(_strip_typed(code)) <= 12


def display_typed_code(code: str) -> str:
    """K7P2QX → K7P-2QX: the dashboard shows it in two halves."""
    return f"{code[:3]}-{code[3:]}"


class AccountStore:
    def __init__(self, path: Path | str = DEFAULT_STORE):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._mtime = 0.0
        # Typed codes are hashed under this key, which never leaves memory: 4 secret characters are too
        # few to survive a plain hash in a copied file. A restart voids live typed codes (5 minutes).
        self._typed_key = secrets.token_bytes(32)
        # Wrong tries per typed code (by its hash), kept here rather than in accounts.json, so a wrong guess
        # doesn't rewrite the file. A restart loses them, but it also voids every typed code (the key above
        # goes with it), so the 5-tries-per-code cap holds across restarts.
        self._typed_fails: dict[str, int] = {}
        # Marks the codes this process made: an older process's codes can't be checked (their key is gone),
        # so they're dead here, and a guess into one names no account.
        self._typed_epoch = secrets.token_hex(4)
        self._data = self._load()

    def _load(self) -> dict:
        try:
            self._mtime = self.path.stat().st_mtime
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            data = {}
        for section in ("accounts", "devices", "sessions", "pairings", "logins", "api_keys", "invites",
                        "typed_codes", "typed_paired"):
            data.setdefault(section, {})
        return data

    def _refresh(self) -> None:
        """Pick up changes made by another process (e.g. `openmob account add` while the server runs)."""
        try:
            if self.path.stat().st_mtime != self._mtime:
                self._data = self._load()
        except OSError:
            pass

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2))
        tmp.chmod(0o600)  # password hashes and key hashes: owner-only
        tmp.replace(self.path)
        self._mtime = self.path.stat().st_mtime

    # --- accounts --------------------------------------------------------

    def create_account(self, email: str, password: str) -> str:
        email = normalize_email(email)
        if not plain_email(email) or len(password) < 8:
            raise AuthError("Enter a valid email and a password of at least 8 characters.")
        with self._lock:
            self._refresh()
            skeleton = email_skeleton(email)
            emails = [a["email"] for a in self._data["accounts"].values()]
            if email in emails or any(email_skeleton(e) == skeleton for e in emails):
                _hash_password(password, secrets.token_hex(16))  # same work as a new account: no timing tell
                if email in emails:
                    raise AccountExists("An account with that email already exists.")
                raise AccountLookAlike("An account with an email that reads the same already exists.")
            account_id = secrets.token_hex(8)
            salt = secrets.token_hex(16)
            self._data["accounts"][account_id] = {
                "email": email,
                "salt": salt,
                "pw_hash": _hash_password(password, salt),
                "created": time.time(),
            }
            self._save()
            return account_id

    def verify_login(self, email: str, password: str) -> str:
        """The account for this email and password. The hash (PBKDF2, tens of milliseconds) runs outside the lock
        every request takes, then the stored hash is read again: a password changed meanwhile wins (security
        review 4, M2). An unknown email costs the same hash, so timing doesn't tell which emails exist (L2)."""
        email = normalize_email(email)
        with self._lock:
            self._refresh()
            found = next(((i, a["salt"], a["pw_hash"]) for i, a in self._data["accounts"].items()
                          if a["email"] == email), None)
        if found is None:
            _hash_password(password, _DUMMY_SALT)
            raise AuthError("Wrong email or password.")
        account_id, salt, expected = found
        good = hmac.compare_digest(expected, _hash_password(password, salt))
        with self._lock:
            self._refresh()
            account = self._data["accounts"].get(account_id)
            same = (account is not None and account["email"] == email and account["salt"] == salt
                    and account["pw_hash"] == expected)
        if good and same:
            return account_id
        raise AuthError("Wrong email or password.")

    def account_id_for(self, email: str) -> str | None:
        email = normalize_email(email)
        with self._lock:
            self._refresh()
            return next((i for i, a in self._data["accounts"].items() if a["email"] == email), None)

    def list_accounts(self) -> list[str]:
        with self._lock:
            self._refresh()
            return sorted(a["email"] for a in self._data["accounts"].values())

    # --- invite codes: sign-up needs one ------------------------------------

    def create_invite(self, ttl: float = INVITE_TTL) -> str:
        """A one-time invite code. Only its hash is stored, like sign-in links."""
        code = secrets.token_urlsafe(12)
        with self._lock:
            self._refresh()
            now = time.time()
            self._data["invites"] = {h: i for h, i in self._data["invites"].items() if i["expires"] > now}
            self._data["invites"][_hash_token(code)] = {"created": now, "expires": now + ttl}
            self._save()
        return code

    def create_account_with_invite(self, email: str, password: str, invite: str) -> str:
        """Sign-up: the invite is checked first and used up whether or not the email already has an
        account, so a valid code can't be replayed to test which emails exist."""
        if not plain_email(normalize_email(email)) or len(password) < 8:
            raise AuthError("Enter a valid email and a password of at least 8 characters.")
        with self._lock:
            self._refresh()
            found = self._data["invites"].pop(_hash_token((invite or "").strip()), None)
            if not found or found["expires"] < time.time():
                if found:
                    self._save()  # forget the expired code
                raise InviteInvalid("This invite code is invalid, already used or expired. Ask for a new one.")
            self._save()
            return self.create_account(email, password)

    # --- one-time sign-in links (for the server operator; there's no web sign-up page yet) -------

    def create_login_link(self, account_id: str) -> str:
        code = secrets.token_urlsafe(18)
        with self._lock:
            self._refresh()
            self._data["logins"][_hash_token(code)] = {"account_id": account_id, "expires": time.time() + LOGIN_LINK_TTL}
            self._save()
        return code

    def redeem_login_link(self, code: str) -> str:
        """Single use: returns the account and forgets the code."""
        with self._lock:
            self._refresh()
            login = self._data["logins"].pop(_hash_token(code or ""), None)
            self._save()
        if not login or login["expires"] < time.time():
            raise AuthError("This sign-in link is invalid or expired. Ask for a new one.")
        return login["account_id"]

    def account_email(self, account_id: str) -> str | None:
        with self._lock:
            self._refresh()
            account = self._data["accounts"].get(account_id)
            return account["email"] if account else None

    # --- sessions (dashboard + app login) --------------------------------

    def create_session(self, account_id: str) -> str:
        """A new sign-in. Expired sessions go, and an account keeps at most SESSIONS_PER_ACCOUNT: its oldest
        goes first (security review 4, M2)."""
        token = secrets.token_urlsafe(24)
        with self._lock:
            self._refresh()
            now = time.time()
            sessions = {h: s for h, s in self._data["sessions"].items() if s["expires"] >= now}
            own = sorted((s["expires"], h) for h, s in sessions.items() if s["account_id"] == account_id)
            for _, h in own[:max(0, len(own) - SESSIONS_PER_ACCOUNT + 1)]:
                del sessions[h]
            sessions[_hash_token(token)] = {"account_id": account_id, "expires": now + SESSION_TTL}
            self._data["sessions"] = sessions
            self._save()
        return token

    def account_for_session(self, token: str | None) -> str | None:
        if not token:
            return None
        with self._lock:
            self._refresh()
            session = self._data["sessions"].get(_hash_token(token))
            if not session or session["expires"] < time.time():
                return None
            return session["account_id"]

    def end_session(self, token: str | None) -> None:
        if not token:
            return
        with self._lock:
            self._refresh()
            if self._data["sessions"].pop(_hash_token(token), None):
                self._save()

    # --- pairing ---------------------------------------------------------

    def create_pairing_code(self, account_id: str, purpose: str = "dashboard") -> tuple[str, float]:
        """A single-use code bound to this account, valid for PAIRING_TTL. Returns (code, expiry).
        Only the code's id and a hash of its secret are stored. `purpose`: "dashboard" or "cli"."""
        code_id = secrets.token_hex(PAIRING_ID_LEN // 2)
        secret = secrets.token_urlsafe(16)  # 128 bits
        now = time.time()
        expires = now + PAIRING_TTL
        with self._lock:
            self._refresh()
            account = self._data["accounts"].get(account_id)
            if account is None:
                raise AuthError("Unknown account.")
            mints = [t for t in account.get("pairing_mints", []) if now - t < 3600]
            if len(mints) >= PAIRING_MINTS_PER_HOUR:
                raise PairingLimit("Too many pairing codes in the last hour. Try again later.")
            account["pairing_mints"] = mints + [now]
            # One live code per account: a new one voids the old. Spent and stale records go too (a
            # redeemed one is kept for a day, so `openmob phone add` can see which phone took it).
            self._data["pairings"] = {
                i: p for i, p in self._data["pairings"].items()
                if "secret_hash" in p and (p["account_id"] != account_id or p.get("device_id"))
                and now - p["expires"] < 86400
            }
            self._data["pairings"][code_id] = {
                "account_id": account_id, "secret_hash": _hash_token(secret), "expires": expires,
                "used": False, "failures": 0, "purpose": purpose, "device_id": None,
            }
            self._save()
        return code_id + secret, expires

    def _live_pairing(self, code: str) -> tuple[str, dict]:
        """(code id, record) for a valid, unused, unexpired code; the lock is held by the caller. A
        wrong secret for a known id counts against that code, voided after PAIRING_MAX_FAILURES."""
        code = (code or "").strip()
        code_id, secret = code[:PAIRING_ID_LEN], code[PAIRING_ID_LEN:]
        pairing = self._data["pairings"].get(code_id) if secret else None
        if pairing is not None and "secret_hash" not in pairing:
            pairing = None  # a record from before codes were hashed
        # Always compare a hash, even for unknown ids, so timing doesn't reveal which ids exist.
        expected = pairing["secret_hash"] if pairing else _hash_token(secrets.token_hex(8))
        good = hmac.compare_digest(expected, _hash_token(secret))
        invalid = "This pairing code is invalid or has expired. Make a new one on your dashboard."
        if pairing is None:
            raise PairingRefused(invalid)
        if not good:
            pairing["failures"] = pairing.get("failures", 0) + 1
            if pairing["failures"] >= PAIRING_MAX_FAILURES:
                pairing["used"] = True  # voided: too many wrong guesses
            self._save()
            raise PairingRefused(invalid, pairing["account_id"])
        if pairing["used"] or pairing["expires"] < time.time():
            raise PairingRefused(invalid, pairing["account_id"])
        return code_id, pairing

    def check_pairing_code(self, code: str, device_id: str | None = None, model: str = "",
                           record: bool = True) -> dict:
        """What a phone shows before its owner confirms: {account_id, email, expires}. Doesn't use the code.

        A typed code needs the phone's `device_id`: the first phone to check it is the only one that
        may claim it, and its model is what the owner's dashboard shows while it waits (`record`)."""
        with self._lock:
            self._refresh()
            if looks_typed(code):
                device_id = (device_id or "").strip()
                if not device_id or len(device_id) > 128:
                    raise AuthError("A device id is required.")
                _, pairing = self._live_typed(code, device_id)
                if record and pairing["checked_by"] is None:
                    pairing["checked_by"] = device_id
                    pairing["checked_model"] = " ".join((model or "").split())[:80] or "Android phone"
                    self._save()
            else:
                _, pairing = self._live_pairing(code)
            account = self._data["accounts"].get(pairing["account_id"], {})
            return {"account_id": pairing["account_id"], "email": account.get("email"), "expires": pairing["expires"]}

    def redeem_pairing_code(self, code: str, account_id: str | None, device_id: str, model: str,
                            approval_key: str | None = None, old_key: str | None = None) -> str:
        """Bind a phone to the code's account and return its own device key.

        The code is the credential. `account_id`, when given (the older signed-in route), must be
        the code's own account: a different account is refused even with a valid code. A typed code
        must have been checked by this same phone first (see check_pairing_code).

        A phone already paired to the code's account pairs again only with proof: its current device key
        (`old_key`), or the signed-in route (see _bind_device).
        """
        device_id = (device_id or "").strip()
        if not device_id or len(device_id) > 128:
            raise AuthError("A device id is required.")
        with self._lock:
            self._refresh()
            if looks_typed(code):
                _, pairing = self._live_typed(code, device_id)
                if pairing["checked_by"] != device_id:
                    raise PairingRefused("Enter the code on this phone and confirm it first.", pairing["account_id"])
            else:
                _, pairing = self._live_pairing(code)
            owner = pairing["account_id"]
            if account_id is not None and owner != account_id:
                raise PairingRefused("This pairing code belongs to a different account.", owner)
            key = self._bind_device(owner, device_id, model, approval_key, "typed" if looks_typed(code) else "qr",
                                    old_key=old_key, signed_in=account_id is not None)
            pairing["used"] = True
            pairing["device_id"] = device_id
            if looks_typed(code):
                # A claimed typed code frees its slot at once; the dashboard's "Paired" status (a day) reads the
                # account's last claimed code from typed_paired instead, without its hash.
                self._data["typed_codes"].pop(normalize_typed_code(code)[:TYPED_SLOT_LEN], None)
                self._typed_fails.pop(pairing["hash"], None)
                self._data["typed_paired"][owner] = {k: v for k, v in pairing.items() if k != "hash"}
            self._save()
            return key

    def _bind_device(self, owner: str, device_id: str, model: str, approval_key: str | None, via: str,
                     old_key: str | None = None, signed_in: bool = False) -> str:
        """The phone's new device record and key, the same for every way of pairing. The lock is held
        and the caller saves. Raises if the phone belongs to another account, or if it's already paired
        to this one and the claim proves neither its current key (`old_key`) nor a signed-in session."""
        existing = self._data["devices"].get(device_id)
        # A phone registered to someone else stays theirs until they revoke it.
        if existing and not existing["revoked"] and existing["account_id"] != owner:
            raise AuthError("This phone is registered to another account. Its owner must remove it first.")
        if existing and existing["account_id"] != owner:
            existing = None  # previously revoked by another account: start a fresh record
        # Device ids aren't secret, so a code alone mustn't replace a phone that is paired now: that would
        # cut off the real phone and hand its record to whoever holds the code (security review 3, K3-L2).
        active = existing is not None and not existing["revoked"]
        proven = active and bool(old_key) and hmac.compare_digest(existing["key_hash"], _hash_token(old_key))
        if active and not proven and not signed_in:
            raise PairingRefused("This phone is already paired with this account. Unpair it in the app, or "
                                 "remove it on your dashboard, then pair again.")
        # A new pairing may approve only its own actions until the owner trusts it, since a leaked
        # code or devices:add key mustn't yield a phone that approves purchases on the others.
        # The account's first phone has nothing to compare against, so it's trusted. A re-pair
        # starts over: device ids aren't secret, so trust can't ride along with one. A phone paired now
        # is never "first" again: proven by its own key it keeps the trust it had, and on the signed-in
        # route it starts untrusted.
        first = not any(i != device_id and d["account_id"] == owner and not d["revoked"]
                        for i, d in self._data["devices"].items())
        trusted = existing.get("trusted", True) if proven else (False if active else first)

        key = secrets.token_urlsafe(32)
        now = time.time()
        self._data["devices"][device_id] = {
            "account_id": owner,
            "model": " ".join((model or "").split())[:80] or (existing or {}).get("model", "Android phone"),
            "key_hash": _hash_token(key),
            "created": (existing or {}).get("created", now),
            "paired_at": now,
            "last_seen": now,
            "revoked": False,
            # The phone's screen-lock-bound public key: its approvals must be signed with it.
            # Pairing again replaces it (or clears it, for an app too old to send one).
            "approval_key": approval_key or None,
            "trusted": trusted,
            "paired_via": via,  # "qr" or "typed": which code was used (the Connect page tells them apart)
        }
        return key

    # --- typed codes (the fallback to the QR code) -------------------------

    def _typed_hash(self, code: str) -> str:
        return hmac.new(self._typed_key, code.encode(), hashlib.sha256).hexdigest()

    def create_typed_code(self, account_id: str) -> tuple[str, float]:
        """A 6-character code bound to this account, for TYPED_TTL, once. Returns (code, expiry), the
        code in its stored form (display_typed_code adds the dash). Making one voids the account's
        previous typed code. Shares the account's hourly limit with QR codes."""
        now = time.time()
        with self._lock:
            self._refresh()
            account = self._data["accounts"].get(account_id)
            if account is None:
                raise AuthError("Unknown account.")
            mints = [t for t in account.get("pairing_mints", []) if now - t < 3600]
            if len(mints) >= PAIRING_MINTS_PER_HOUR:
                raise PairingLimit("Too many pairing codes in the last hour. Try again later.")
            # One typed code per account: its old one goes, and so do expired ones, freeing their slots. A
            # claimed code has already left its slot (for typed_paired), so every record left here holds a
            # slot for at most TYPED_TTL, and all of them count against the cap.
            self._data["typed_codes"] = {
                slot: c for slot, c in self._data["typed_codes"].items()
                if c["account_id"] != account_id and c["expires"] > now and not c.get("device_id")
                and c.get("epoch") == self._typed_epoch
            }
            self._data["typed_paired"] = {a: c for a, c in self._data["typed_paired"].items()
                                          if now - c["expires"] < 86400}
            self._typed_fails = {h: n for h, n in self._typed_fails.items()
                                 if any(c["hash"] == h for c in self._data["typed_codes"].values())}
            free = sorted({a + b for a in TYPED_ALPHABET for b in TYPED_ALPHABET} - set(self._data["typed_codes"]))
            if len(self._data["typed_codes"]) >= TYPED_MAX_LIVE or not free:
                raise PairingLimit("Too many pairing codes are waiting right now. Scan the QR code instead.")
            code = secrets.choice(free) + "".join(secrets.choice(TYPED_ALPHABET)
                                                  for _ in range(TYPED_LEN - TYPED_SLOT_LEN))
            account["pairing_mints"] = mints + [now]
            self._data["typed_codes"][code[:TYPED_SLOT_LEN]] = {
                "account_id": account_id, "hash": self._typed_hash(code), "created": now,
                "expires": now + TYPED_TTL, "used": False, "voided": False,
                "checked_by": None, "checked_model": None, "device_id": None, "epoch": self._typed_epoch,
            }
            self._save()
        return code, now + TYPED_TTL

    def _live_typed(self, code: str, device_id: str | None) -> tuple[str, dict]:
        """(slot, record) for a valid, unused, unexpired typed code; the lock is held by the caller. A
        wrong secret in a live slot counts against that code (voided after TYPED_MAX_FAILURES), and only
        then names its account (for the per-account limit): a guess into an empty, spent, voided or
        expired slot names none, so blind guessing can't lock anyone out. Once a phone has checked the
        code it's that phone's: another phone entering it voids it."""
        norm = normalize_typed_code(code)
        if norm is None:
            raise PairingMalformed("A pairing code is 6 letters and numbers, like K7P-2QX. Check it on your dashboard.")
        slot = norm[:TYPED_SLOT_LEN]
        rec = self._data["typed_codes"].get(slot)
        # The phone can't tell a hit from a miss: every refused code (an empty slot, a wrong secret in a
        # live slot, a spent or expired code) computes the same HMACs, writes nothing (the tries are
        # counted in memory, see __init__) and gets the same reply. The tries left show only on the
        # owner's dashboard (typed_code_status).
        dummy = self._typed_hash(secrets.token_hex(8))  # computed every time, used for an empty slot
        expected = rec["hash"] if rec else dummy
        good = hmac.compare_digest(expected, self._typed_hash(norm))
        live = rec is not None and not self._typed_dead(rec) and rec["expires"] >= time.time()
        if not (good and live):
            if live:
                self._typed_fails[rec["hash"]] = self._typed_fails.get(rec["hash"], 0) + 1  # voided at the cap
            raise PairingRefused(WRONG_TYPED_CODE, rec["account_id"] if live else None)
        if device_id is not None and rec["checked_by"] not in (None, device_id):
            rec["voided"] = True  # the code reached two phones: neither gets it
            self._save()
            raise PairingRefused("This code was already entered on another phone, so it's been cancelled. "
                                 "Make a new one on your dashboard.", rec["account_id"])
        return slot, rec

    def _typed_dead(self, rec: dict) -> bool:
        """Claimed, cancelled, reached two phones, out of tries, or made before a restart."""
        return bool(rec["used"] or rec["voided"] or rec.get("epoch") != self._typed_epoch
                    or self._typed_fails.get(rec["hash"], 0) >= TYPED_MAX_FAILURES)

    def typed_code_status(self, account_id: str) -> dict:
        """For the dashboard while it shows a typed code: {status, expires, tries_left, model, device_id}.
        status: none, waiting (no phone yet), confirming (a phone checked it), paired, expired or
        cancelled (voided by wrong tries, a second phone, or the owner). Never the code itself."""
        with self._lock:
            self._refresh()
            mine = [c for c in self._data["typed_codes"].values() if c["account_id"] == account_id]
            mine += [self._data["typed_paired"][account_id]] if account_id in self._data["typed_paired"] else []
            if not mine:
                return {"status": "none"}
            c = max(mine, key=lambda c: c["created"])
            if c.get("device_id"):
                status = "paired"
            elif self._typed_dead(c):
                status = "cancelled"
            elif c["expires"] < time.time():
                status = "expired"
            else:
                status = "confirming" if c["checked_by"] else "waiting"
            phone = c["device_id"] or c["checked_by"]
            return {"status": status, "expires": c["expires"],
                    "tries_left": max(0, TYPED_MAX_FAILURES - self._typed_fails.get(c.get("hash"), 0)),
                    "model": c["checked_model"], "device_id": f"app-{phone}" if phone else None}

    def cancel_typed_code(self, account_id: str) -> bool:
        """The owner cancels their waiting typed code (e.g. the dashboard names a phone that isn't theirs)."""
        with self._lock:
            self._refresh()
            hit = False
            for c in self._data["typed_codes"].values():
                if c["account_id"] == account_id and not c["used"] and not c["voided"]:
                    c["voided"] = hit = True
            if hit:
                self._save()
            return hit

    def pairing_status(self, account_id: str, code_id: str) -> dict | None:
        """For `openmob phone add`: {status: pending|paired|expired, device_id}. None if not this account's."""
        with self._lock:
            self._refresh()
            p = self._data["pairings"].get((code_id or "")[:PAIRING_ID_LEN])
            if not p or p["account_id"] != account_id:
                return None
            if p.get("device_id"):
                return {"status": "paired", "device_id": p["device_id"]}
            if p["used"] or p["expires"] < time.time():
                return {"status": "expired", "device_id": None}
            return {"status": "pending", "device_id": None}

    def trusted_for_approvals(self, device_id: str) -> bool:
        """May this phone answer approvals for its owner's other phones? Pairings from before trust
        existed count as trusted (they were paired with a signed-in session)."""
        with self._lock:
            self._refresh()
            d = self._data["devices"].get(device_id or "")
            return bool(d and not d["revoked"] and d.get("trusted", True))

    def trust_device(self, account_id: str, device_id: str) -> bool:
        """The owner trusts one of their phones for approvals. False if not theirs (or revoked)."""
        with self._lock:
            self._refresh()
            d = self._data["devices"].get(device_id or "")
            if not d or d["revoked"] or d["account_id"] != account_id:
                return False
            if not d.get("trusted", True):
                d["trusted"] = True
                d["trusted_at"] = time.time()
                self._save()
            return True

    def is_paired(self, account_id: str, device_id: str) -> bool:
        """This phone is paired (and not revoked) to this account."""
        with self._lock:
            self._refresh()
            d = self._data["devices"].get(device_id or "")
            return bool(d and not d["revoked"] and d["account_id"] == account_id)

    # --- device auth -----------------------------------------------------

    def verify_device(self, device_id: str, key: str) -> str:
        """Return the owning account for a phone's key, or raise. Updates last-seen."""
        with self._lock:
            self._refresh()
            device = self._data["devices"].get(device_id)
            if not device or device["revoked"]:
                raise AuthError("This phone is not paired. Pair it again from your dashboard.")
            if not hmac.compare_digest(device["key_hash"], _hash_token(key)):
                raise AuthError("This phone's key is wrong. Pair it again from your dashboard.")
            device["last_seen"] = time.time()
            self._save()
            return device["account_id"]

    @staticmethod
    def key_fingerprint(key: str) -> str:
        """What a phone's key is stored as; a socket remembers it to notice a re-pair."""
        return _hash_token(key or "")

    def device_auth(self, device_id: str) -> dict | None:
        """A phone's pairing as it stands now: {account_id, revoked, key_hash, approval_key}."""
        with self._lock:
            self._refresh()
            d = self._data["devices"].get(device_id)
            if d is None:
                return None
            return {"account_id": d["account_id"], "revoked": bool(d["revoked"]), "key_hash": d["key_hash"],
                    "approval_key": d.get("approval_key")}

    def register_approval_key(self, device_id: str, key_hash: str, public_key: str) -> bool:
        """First connect of an already-paired phone whose app now has an approval key: keep it, once.
        Never replaces a registered key (only pairing again does) and only for the current device key."""
        with self._lock:
            self._refresh()
            d = self._data["devices"].get(device_id)
            if not d or d["revoked"] or d.get("approval_key") or d["key_hash"] != key_hash or not public_key:
                return False
            d["approval_key"] = public_key
            self._save()
            return True

    def device_permissions(self, device_id: str) -> dict | None:
        """The phone's permission settings (openmob/permissions.py), or None. Pairing again resets them."""
        with self._lock:
            self._refresh()
            d = self._data["devices"].get(device_id)
            return dict(d["permissions"]) if d and not d["revoked"] and isinstance(d.get("permissions"), dict) else None

    def set_device_permissions(self, device_id: str, settings: dict) -> bool:
        with self._lock:
            self._refresh()
            d = self._data["devices"].get(device_id)
            if not d or d["revoked"]:
                return False
            d["permissions"] = settings
            self._save()
            return True

    def list_devices(self, account_id: str) -> list[Device]:
        """Every phone paired to this account, online or not (revoked ones are left out)."""
        with self._lock:
            self._refresh()
            return [
                Device(id=device_id, paired_at=d.get("paired_at") or d["created"], trusted=d.get("trusted", True),
                       paired_via=d.get("paired_via"),
                       **{k: d[k] for k in ("account_id", "model", "created", "last_seen", "revoked")})
                for device_id, d in self._data["devices"].items()
                if d["account_id"] == account_id and not d["revoked"]
            ]

    def revoke_device(self, account_id: str, device_id: str) -> bool:
        """Mark a phone as unpaired. Only the owning account may do this."""
        with self._lock:
            self._refresh()
            device = self._data["devices"].get(device_id)
            if not device or device["account_id"] != account_id:
                return False
            device["revoked"] = True
            self._save()
            return True

    def unpair_by_key(self, device_id: str, key: str) -> str:
        """The phone unpairs itself, proving it with its own device key. Returns its account, or raises."""
        with self._lock:
            account_id = self.verify_device(device_id, key)
            self._data["devices"][device_id]["revoked"] = True
            self._save()
            return account_id

    # --- admin (granted only from the server's command line) --------------

    def set_admin(self, email: str, on: bool) -> bool:
        """Grant or remove the admin role. False if there's no such account."""
        email = normalize_email(email)
        with self._lock:
            self._refresh()
            account = next((a for a in self._data["accounts"].values() if a["email"] == email), None)
            if account is None:
                return False
            account["is_admin"] = bool(on)
            self._save()
            return True

    def is_admin(self, account_id: str | None) -> bool:
        if not account_id:
            return False
        with self._lock:
            self._refresh()
            return bool(self._data["accounts"].get(account_id, {}).get("is_admin", False))

    def admin_list_accounts(self) -> list[dict]:
        """Every account, without any secret (no salt or password hash)."""
        with self._lock:
            self._refresh()
            counts: dict[str, int] = {}
            for d in self._data["devices"].values():
                if not d["revoked"]:
                    counts[d["account_id"]] = counts.get(d["account_id"], 0) + 1
            accounts = [
                {"id": account_id, "email": a["email"], "created": a.get("created"),
                 "is_admin": bool(a.get("is_admin", False)), "device_count": counts.get(account_id, 0),
                 "api_disabled": bool(a.get("api_disabled", False))}
                for account_id, a in self._data["accounts"].items()
            ]
        return sorted(accounts, key=lambda a: a["email"])

    def admin_list_devices(self) -> list[dict]:
        """Every paired phone (revoked ones included), without key hashes."""
        with self._lock:
            self._refresh()
            accounts = self._data["accounts"]
            return [
                {"id": device_id, "account_id": d["account_id"],
                 "email": accounts.get(d["account_id"], {}).get("email"),
                 **{k: d[k] for k in ("model", "created", "last_seen", "revoked")}}
                for device_id, d in self._data["devices"].items()
            ]

    def admin_revoke_device(self, device_id: str) -> bool:
        """Unpair a phone regardless of owner. False if unknown."""
        with self._lock:
            self._refresh()
            device = self._data["devices"].get(device_id)
            if not device:
                return False
            device["revoked"] = True
            self._save()
            return True

    # --- developer API keys --------------------------------------------------

    def create_api_key(self, account_id: str, name: str, scopes=DEFAULT_SCOPES,
                       confirm_approve: bool = False, max_mode: str = "auto") -> tuple[str, str]:
        """Returns (key id, key). The key is shown once; only its hash is kept.
        `confirm_approve`: the key may approve risky actions itself (else only the owner can).
        `max_mode`: the loosest permission mode its tasks may ask for (the phone's ceiling still applies)."""
        if max_mode not in KEY_MODES:
            raise AuthError(f"max_mode must be one of: {', '.join(KEY_MODES)}")
        scopes = sorted(set(scopes))
        unknown = [sc for sc in scopes if sc not in SCOPES]
        if unknown or not scopes:
            raise AuthError(f"Unknown or missing scopes: {', '.join(unknown) or 'none'}. Choose from: {', '.join(SCOPES)}")
        name = " ".join((name or "").split())[:60] or "API key"
        key_id = secrets.token_hex(4)
        key = f"{KEY_PREFIX}{key_id}_{secrets.token_urlsafe(24)}"
        with self._lock:
            self._refresh()
            if account_id not in self._data["accounts"]:
                raise AuthError("Unknown account.")
            self._data["api_keys"][key_id] = {
                "account_id": account_id, "name": name, "scopes": scopes, "hash": _hash_token(key),
                "created": time.time(), "last_used": None, "revoked": False, "disabled": False,
                "confirm_approve": bool(confirm_approve), "max_mode": max_mode,
            }
            self._save()
        return key_id, key

    def verify_api_key(self, key: str | None) -> dict:
        """The key's {id, account_id, scopes, name}, or raise AuthError (AccessDisabled when switched off)."""
        parts = (key or "").split("_", 3)
        if len(parts) != 4 or f"{parts[0]}_{parts[1]}_" != KEY_PREFIX:
            raise AuthError("Invalid API key.")
        key_id = parts[2]
        with self._lock:
            self._refresh()
            record = self._data["api_keys"].get(key_id)
            # Always compare a hash, even for unknown ids, so timing doesn't reveal which ids exist.
            expected = record["hash"] if record else _hash_token(secrets.token_hex(8))
            if not hmac.compare_digest(expected, _hash_token(key)) or not record or record["revoked"]:
                raise AuthError("Invalid API key.")
            account = self._data["accounts"].get(record["account_id"])
            if account is None:
                raise AuthError("Invalid API key.")
            if record.get("disabled") or account.get("api_disabled"):
                raise AccessDisabled("API access for this key has been disabled. Contact support.")
            now = time.time()
            if not record["last_used"] or now - record["last_used"] > LAST_USED_EVERY:
                record["last_used"] = now
                self._save()
            return {"id": key_id, "account_id": record["account_id"], "scopes": list(record["scopes"]),
                    "name": record["name"], "confirm_approve": bool(record.get("confirm_approve")),
                    "max_mode": record.get("max_mode") or "auto"}

    @staticmethod
    def _public_key(key_id: str, k: dict) -> dict:
        return {"id": key_id, "prefix": f"{KEY_PREFIX}{key_id}", "name": k["name"], "scopes": list(k["scopes"]),
                "created": k["created"], "last_used": k["last_used"], "disabled": bool(k.get("disabled")),
                "confirm_approve": bool(k.get("confirm_approve")), "max_mode": k.get("max_mode") or "auto"}

    def list_api_keys(self, account_id: str) -> list[dict]:
        """This account's live keys (never the hash)."""
        with self._lock:
            self._refresh()
            keys = [self._public_key(i, k) for i, k in self._data["api_keys"].items()
                    if k["account_id"] == account_id and not k["revoked"]]
        return sorted(keys, key=lambda k: k["created"], reverse=True)

    def api_key_count(self, account_id: str) -> int:
        return len(self.list_api_keys(account_id))

    def revoke_api_key(self, account_id: str, key_id: str) -> bool:
        """Only the owning account may revoke its key. False if unknown or not theirs."""
        with self._lock:
            self._refresh()
            k = self._data["api_keys"].get(key_id)
            if not k or k["account_id"] != account_id or k["revoked"]:
                return False
            k["revoked"] = True
            self._save()
            return True

    def rotate_api_key(self, account_id: str, key_id: str) -> tuple[str, str] | None:
        """Give a key a new secret; the old secret stops working now. It stays the same key (same
        id, name, scopes and settings), so its limits, tasks and running work carry on unchanged."""
        with self._lock:
            self._refresh()
            k = self._data["api_keys"].get(key_id)
            if not k or k["account_id"] != account_id or k["revoked"]:
                return None
            key = f"{KEY_PREFIX}{key_id}_{secrets.token_urlsafe(24)}"
            k["hash"] = _hash_token(key)
            k["rotated"] = time.time()
            self._save()
            return key_id, key

    def set_key_confirm_approve(self, account_id: str, key_id: str, on: bool) -> bool:
        """Let one of the owner's keys approve risky actions itself (or take that back)."""
        with self._lock:
            self._refresh()
            k = self._data["api_keys"].get(key_id)
            if not k or k["account_id"] != account_id or k["revoked"]:
                return False
            k["confirm_approve"] = bool(on)
            self._save()
            return True

    def set_key_max_mode(self, account_id: str, key_id: str, mode: str) -> bool:
        """The loosest permission mode this key's tasks may ask for."""
        if mode not in KEY_MODES:
            raise AuthError(f"max_mode must be one of: {', '.join(KEY_MODES)}")
        with self._lock:
            self._refresh()
            k = self._data["api_keys"].get(key_id)
            if not k or k["account_id"] != account_id or k["revoked"]:
                return False
            k["max_mode"] = mode
            self._save()
            return True

    # --- per-account developer settings ------------------------------------------

    def settings(self, account_id: str) -> dict:
        with self._lock:
            self._refresh()
            a = self._data["accounts"].get(account_id, {})
            hook = a.get("webhook") or {}
            return {"allow_sensitive_apps": bool(a.get("allow_sensitive_apps", False)),
                    "webhook_url": hook.get("url"), "api_disabled": bool(a.get("api_disabled", False))}

    def set_allow_sensitive_apps(self, account_id: str, on: bool) -> None:
        with self._lock:
            self._refresh()
            self._data["accounts"][account_id]["allow_sensitive_apps"] = bool(on)
            self._save()

    def set_webhook(self, account_id: str, url: str | None) -> str | None:
        """Set (returns the new signing secret, shown once) or clear (url=None) the task webhook."""
        with self._lock:
            self._refresh()
            account = self._data["accounts"][account_id]
            if not url:
                account.pop("webhook", None)
                self._save()
                return None
            secret = "whsec_" + secrets.token_urlsafe(24)
            old = account.get("webhook") or {}
            account["webhook"] = {"url": url, "secret": secret}
            if old.get("secret"):  # the previous secret keeps verifying for a day, so receivers can switch over
                account["webhook"].update(previous_secret=old["secret"], previous_until=time.time() + WEBHOOK_SECRET_OVERLAP)
            self._save()
            return secret

    def webhook(self, account_id: str) -> tuple[str, str] | None:
        """(url, signing secret) for delivering task events, or None."""
        with self._lock:
            self._refresh()
            hook = self._data["accounts"].get(account_id, {}).get("webhook")
            return (hook["url"], hook["secret"]) if hook else None

    def webhook_secrets(self, account_id: str) -> list[str]:
        """Secrets to sign with now: the current one, plus the previous one during its 24 h overlap."""
        with self._lock:
            self._refresh()
            hook = self._data["accounts"].get(account_id, {}).get("webhook")
            if not hook:
                return []
            out = [hook["secret"]]
            if hook.get("previous_secret") and hook.get("previous_until", 0) > time.time():
                out.append(hook["previous_secret"])
            return out

    # --- admin: API kill switches -----------------------------------------------

    def admin_list_api_keys(self) -> list[dict]:
        with self._lock:
            self._refresh()
            accounts = self._data["accounts"]
            keys = [{**self._public_key(i, k), "account_id": k["account_id"],
                     "email": accounts.get(k["account_id"], {}).get("email")}
                    for i, k in self._data["api_keys"].items() if not k["revoked"]]
        return sorted(keys, key=lambda k: k["created"], reverse=True)

    def api_key_principal(self, key_id: str) -> dict | None:
        """A key's current standing, read fresh (no secret needed): for re-checking long-running work
        such as orchestrations. {id, account_id, scopes, name, confirm_approve, revoked, disabled,
        api_disabled}, or None if the key or its account doesn't exist."""
        with self._lock:
            self._refresh()
            k = self._data["api_keys"].get(key_id)
            account = self._data["accounts"].get(k["account_id"]) if k else None
            if not k or account is None:
                return None
            return {"id": key_id, "account_id": k["account_id"], "scopes": list(k["scopes"]), "name": k["name"],
                    "confirm_approve": bool(k.get("confirm_approve")), "max_mode": k.get("max_mode") or "auto",
                    "revoked": bool(k["revoked"]),
                    "disabled": bool(k.get("disabled")), "api_disabled": bool(account.get("api_disabled"))}

    def admin_set_key_disabled(self, key_id: str, on: bool) -> str | None:
        """Switch one key off or on. Returns its account, or None if unknown."""
        with self._lock:
            self._refresh()
            k = self._data["api_keys"].get(key_id)
            if not k or k["revoked"]:
                return None
            k["disabled"] = bool(on)
            self._save()
            return k["account_id"]

    def admin_set_api_disabled(self, account_id: str, on: bool) -> bool:
        """Switch off (or back on) every API key of one account."""
        with self._lock:
            self._refresh()
            account = self._data["accounts"].get(account_id)
            if account is None:
                return False
            account["api_disabled"] = bool(on)
            self._save()
            return True
