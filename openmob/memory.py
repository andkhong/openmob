"""Owner-confirmed preferences memory: short notes about the user, an app or a person.

Three kinds of note:
- `about_you` ("I prefer dark mode"): offered at the start of a task;
- `app` ("In Where Winds Meet the quests are under the scroll icon"): offered when that package is in front;
- `person` (relation + contact name: "sis" = "Maya"): looked up by relation or name, never by number or email.

A note is `active` (used) or `proposed` (waiting for the owner's tap). Nothing here makes a note active on its
own authority: callers decide, and screen text can at most become a proposal.

Rows are scoped to the owning account. SQLite in the data dir, owner-only, WAL, `secure_delete` on so a deleted
note's text is overwritten in the file. Note text is never logged by this module.
"""

from __future__ import annotations

import os
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from .history import LOCAL_ACCOUNT

DEFAULT_PATH = Path(os.environ.get("OPENMOB_DATA_DIR") or Path.home() / ".config" / "openmob") / "memory.sqlite"
KINDS = ("about_you", "app", "person")
STATUSES = ("active", "proposed")
MAX_TEXT = 300  # characters per note: a note, not a document
MAX_NOTES = 200  # per account
MAX_PROPOSED = 20  # pending proposals per account
MAX_RELATION = 40  # "sis", "my manager": model-supplied, so capped
MAX_PACKAGE = 200  # an Android package name
MAX_CONTACT = 100  # a name in the phone's contacts

STOPWORDS = frozenset("a an the my me i to of in on for and or with please can you add open".split())
_NUMBERISH = re.compile(r"^[+\d\s().-]{5,}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    kind TEXT NOT NULL,               -- about_you | app | person
    package TEXT,                     -- app notes only
    relation TEXT,                    -- person notes only ("sis")
    contact_name TEXT,                -- person notes only ("Maya")
    text TEXT NOT NULL,
    norm TEXT NOT NULL,               -- lowercase, punctuation and spaces collapsed, for duplicate checks
    status TEXT NOT NULL,             -- active | proposed
    source TEXT NOT NULL,
    task_id TEXT,
    created REAL NOT NULL,
    updated REAL NOT NULL,
    last_used REAL,
    uses INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS notes_by_account ON notes (account_id, kind, status);
CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(text, content='notes', content_rowid='rowid');
CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
    INSERT INTO notes_fts(rowid, text) VALUES (new.rowid, new.text);
END;
CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, text) VALUES ('delete', old.rowid, old.text);
END;
CREATE TRIGGER IF NOT EXISTS notes_au AFTER UPDATE OF text ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, text) VALUES ('delete', old.rowid, old.text);
    INSERT INTO notes_fts(rowid, text) VALUES (new.rowid, new.text);
END;
"""


class NoteError(ValueError):
    """A note was empty, too long, malformed, or over the account's limit."""


def clean_text(text: str) -> str:
    text = " ".join((text or "").split())
    if not text:
        raise NoteError("A note can't be empty.")
    if len(text) > MAX_TEXT:
        raise NoteError(f"Keep a note under {MAX_TEXT} characters.")
    return text


def clean_contact_name(name: str | None) -> str:
    name = " ".join((name or "").split())
    if not name:
        raise NoteError("A person note needs a contact name.")
    if len(name) > MAX_CONTACT:
        raise NoteError(f"Keep a contact name under {MAX_CONTACT} characters.")
    if "@" in name or _NUMBERISH.match(name):
        raise NoteError("A contact name is a name in the phone's contacts, not a number or an email.")
    return name


def _norm(text: str) -> str:
    return " ".join(re.sub(r"\W+", " ", text.lower()).split())


class Memory:
    def __init__(self, path: Path | str = DEFAULT_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA busy_timeout = 2000")
        self._db.execute("PRAGMA secure_delete = ON")
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.executescript(SCHEMA)
        try:
            os.chmod(self.path, 0o600)  # personal facts: owner-only
        except OSError:
            pass

    def _scrub(self) -> None:
        """Overwrite what a delete or edit left behind: merge the FTS index, then empty the WAL into the file.
        Caller holds the lock."""
        self._db.execute("INSERT INTO notes_fts(notes_fts) VALUES ('optimize')")
        self._db.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _q(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    # --- writing ---------------------------------------------------------------------

    def add(self, account_id: str | None, text: str, kind: str, package: str | None = None,
            relation: str | None = None, contact_name: str | None = None, status: str = "proposed",
            source: str = "user", task_id: str | None = None) -> dict:
        if kind not in KINDS:
            raise NoteError(f"kind must be one of: {', '.join(KINDS)}")
        if status not in STATUSES:
            raise NoteError(f"status must be one of: {', '.join(STATUSES)}")
        account = account_id or LOCAL_ACCOUNT
        text = clean_text(text)
        package = (package or "").strip() or None
        relation = " ".join((relation or "").split()) or None
        if package and len(package) > MAX_PACKAGE:
            raise NoteError(f"Keep a package name under {MAX_PACKAGE} characters.")
        if relation and len(relation) > MAX_RELATION:
            raise NoteError(f"Keep a relation under {MAX_RELATION} characters.")
        if kind == "app":
            if not package:
                raise NoteError("An app note needs the app's package.")
            relation = contact_name = None
        elif kind == "person":
            if not relation:
                raise NoteError("A person note needs a relation.")
            contact_name = clean_contact_name(contact_name)
            package = None
        else:
            package = relation = contact_name = None
        norm = _norm(text)
        with self._lock:
            db = self._db
            db.execute("BEGIN IMMEDIATE")
            try:
                same = db.execute(
                    "SELECT id, status FROM notes WHERE account_id = ? AND kind = ? AND package IS ? "
                    "AND relation IS ? AND lower(contact_name) IS ? AND norm = ?",
                    (account, kind, package, relation, contact_name.lower() if contact_name else None,
                     norm)).fetchone()
                if same:
                    if status == "active" and same["status"] != "active":
                        db.execute("UPDATE notes SET status = 'active', updated = ? WHERE id = ?",
                                   (time.time(), same["id"]))
                    note_id = same["id"]
                else:
                    if db.execute("SELECT COUNT(*) FROM notes WHERE account_id = ?", (account,)).fetchone()[0] >= MAX_NOTES:
                        raise NoteError(f"You have {MAX_NOTES} notes, the most allowed. Delete some first.")
                    if status == "proposed" and db.execute(
                            "SELECT COUNT(*) FROM notes WHERE account_id = ? AND status = 'proposed'",
                            (account,)).fetchone()[0] >= MAX_PROPOSED:
                        raise NoteError(f"{MAX_PROPOSED} suggestions are waiting. Save or dismiss some first.")
                    note_id = uuid.uuid4().hex[:12]
                    now = time.time()
                    db.execute(
                        "INSERT INTO notes (id, account_id, kind, package, relation, contact_name, text, norm, "
                        "status, source, task_id, created, updated) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (note_id, account, kind, package, relation, contact_name, text, norm, status, source,
                         task_id, now, now))
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise
        return self.get(account, note_id)

    def confirm(self, account_id: str | None, note_id: str) -> dict | None:
        """The owner's tap: a proposal becomes active. None if not this account's."""
        if self.get(account_id, note_id) is None:
            return None
        self._q("UPDATE notes SET status = 'active', updated = ? WHERE id = ?", (time.time(), note_id))
        return self.get(account_id, note_id)

    def update(self, account_id: str | None, note_id: str, text: str | None = None,
               contact_name: str | None = None) -> dict | None:
        """Edit a note's text and/or a person note's contact name. None if not this account's."""
        note = self.get(account_id, note_id)
        if note is None:
            return None
        new_text = clean_text(text) if text is not None else note["text"]
        new_contact = note["contact_name"]
        if contact_name is not None:
            if note["kind"] != "person":
                raise NoteError("Only a person note has a contact name.")
            new_contact = clean_contact_name(contact_name)
        with self._lock:
            self._db.execute("UPDATE notes SET text = ?, norm = ?, contact_name = ?, updated = ? WHERE id = ?",
                             (new_text, _norm(new_text), new_contact, time.time(), note_id))
            if new_text != note["text"] or new_contact != note["contact_name"]:
                self._scrub()
        return self.get(account_id, note_id)

    def delete(self, account_id: str | None, note_id: str) -> bool:
        """Delete (or dismiss, for a proposal) one note. False if not this account's."""
        if self.get(account_id, note_id) is None:
            return False
        with self._lock:
            self._db.execute("DELETE FROM notes WHERE id = ?", (note_id,))
            self._scrub()
        return True

    def dismiss(self, account_id: str | None, note_id: str) -> bool | None:
        """"Not now": delete a note only while it is still a proposal (one atomic statement, so a stale tap can't
        delete a note the owner has saved since). True: dismissed. False: it is no longer a proposal. None: not
        this account's."""
        if self.get(account_id, note_id) is None:
            return None
        with self._lock:
            n = self._db.execute("DELETE FROM notes WHERE id = ? AND account_id = ? AND status = 'proposed'",
                                 (note_id, account_id or LOCAL_ACCOUNT)).rowcount
            if n:
                self._scrub()
        return bool(n)

    def delete_all(self, account_id: str | None) -> int:
        with self._lock:
            n = self._db.execute("DELETE FROM notes WHERE account_id = ?", (account_id or LOCAL_ACCOUNT,)).rowcount
            self._scrub()
            return n

    # --- reading ---------------------------------------------------------------------

    def get(self, account_id: str | None, note_id: str) -> dict | None:
        rows = self._q("SELECT * FROM notes WHERE id = ? AND account_id = ?", (note_id, account_id or LOCAL_ACCOUNT))
        return self._public(rows[0]) if rows else None

    def get_many(self, account_id: str | None, ids: list[str]) -> dict[str, dict]:
        ids = list(dict.fromkeys(ids))
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        rows = self._q(f"SELECT * FROM notes WHERE account_id = ? AND id IN ({marks})",
                       (account_id or LOCAL_ACCOUNT, *ids))
        return {r["id"]: self._public(r) for r in rows}

    def list(self, account_id: str | None, status: str | None = None) -> list[dict]:
        sql, args = "SELECT * FROM notes WHERE account_id = ?", [account_id or LOCAL_ACCOUNT]
        if status:
            sql += " AND status = ?"
            args.append(status)
        rows = self._q(sql + " ORDER BY kind, package, created", tuple(args))
        return [self._public(r) for r in rows]

    def about_you(self, account_id: str | None, limit: int = 10) -> list[dict]:
        rows = self._q("SELECT * FROM notes WHERE account_id = ? AND kind = 'about_you' AND status = 'active' "
                       "ORDER BY COALESCE(last_used, created) DESC, created DESC LIMIT ?",
                       (account_id or LOCAL_ACCOUNT, limit))  # newest-used first (spec §5.3)
        return [self._public(r) for r in rows]

    def for_app(self, account_id: str | None, package: str, limit: int = 5) -> list[dict]:
        rows = self._q("SELECT * FROM notes WHERE account_id = ? AND kind = 'app' AND package = ? "
                       "AND status = 'active' ORDER BY created LIMIT ?", (account_id or LOCAL_ACCOUNT, package, limit))
        return [self._public(r) for r in rows]

    def search(self, account_id: str | None, query: str, limit: int = 5) -> list[dict]:
        """Active notes matching any meaningful word of `query`, best match first."""
        terms = [t for t in re.split(r"\W+", (query or "").lower()) if t and t not in STOPWORDS]
        if not terms:
            return []
        match = " OR ".join(f'"{t}"' for t in dict.fromkeys(terms))
        rows = self._q(
            "SELECT n.* FROM notes_fts JOIN notes n ON n.rowid = notes_fts.rowid "
            "WHERE notes_fts MATCH ? AND n.account_id = ? AND n.status = 'active' "
            "ORDER BY bm25(notes_fts) LIMIT ?", (match, account_id or LOCAL_ACCOUNT, limit))
        return [self._public(r) for r in rows]

    def people(self, account_id: str | None, relation_or_name: str) -> list[dict]:
        key = " ".join((relation_or_name or "").split()).lower()
        if not key:
            return []
        rows = self._q("SELECT * FROM notes WHERE account_id = ? AND kind = 'person' AND status = 'active' "
                       "AND (lower(relation) = ? OR lower(contact_name) = ?) ORDER BY created",
                       (account_id or LOCAL_ACCOUNT, key, key))
        return [self._public(r) for r in rows]

    def mark_used(self, note_ids: list[str]) -> None:
        if note_ids:
            now = time.time()
            with self._lock:
                self._db.executemany("UPDATE notes SET uses = uses + 1, last_used = ? WHERE id = ?",
                                     [(now, i) for i in note_ids])

    @staticmethod
    def _public(row: sqlite3.Row) -> dict:
        note = dict(row)
        note.pop("account_id", None)
        note.pop("norm", None)
        return note


# --- thread lines ------------------------------------------------------------------------------------
# Events carry note ids only (kind "memory", message "", data {"use", "note_ids"}). The owner-facing line is
# built here, at read time, from the note's current text: an edit shows at once, a deletion shows a placeholder,
# and an untrusted phone never gets note text. A "proposed" event is a Save / Not now card (its card is built here
# from the note id, so the stored event stays id-only); once saved, the card reads "Saved: <note>". A "sending_to"
# line whose note was deleted reads "Sending to a deleted preference".

DELETED = "a deleted preference"
UNTRUSTED = "a saved preference"
AGENT_ORIGIN = "Suggested from what the agent saw on screen"


def card_origin(note: dict) -> str:
    """Where a suggestion came from, shown under its card (review 5 M5-L3): words the agent read on the screen (not
    the owner's), and the app an app note is about. Empty for the owner's own words about no app."""
    parts = [AGENT_ORIGIN] if note.get("source") == "agent" else []
    if note.get("kind") == "app" and note.get("package"):
        parts.append(f"About the app {note['package']}")
    return " · ".join(parts)


def _person_card(note: dict) -> str:
    return f"your {note['relation']} = {note['contact_name']} — {note['text']}"


def _line(use: str | None, notes: list[dict | None], placeholder: str | None) -> str:
    """The line for one event. `notes` are in event order (None: deleted); `placeholder` replaces all text."""
    if use == "proposed":
        note = notes[0] if notes else None
        if placeholder or note is None:
            return placeholder or DELETED
        prefix = "Saved: " if note["status"] == "active" else "Save this? "
        return prefix + (_person_card(note) if note["kind"] == "person" else note["text"])
    if use == "sending_to":
        note = notes[0] if notes else None
        if placeholder:
            return f"Sending to {placeholder}"
        if note is None:
            return f"Sending to {DELETED}"
        return f"Sending to {note['contact_name']} — your {note['relation']}, from your saved preferences"
    texts = [placeholder or (n["text"] if n else DELETED) for n in notes]
    return "Used your preferences: " + "; ".join(dict.fromkeys(texts) if placeholder else texts)


def render_events(store, account_id: str | None, events: list[dict], trusted: bool, enabled: bool) -> list[dict]:
    """`events` with each "memory" event's message filled in (copies; the inputs are untouched). One lookup for
    all of them. Memory off (or no store): the memory events are removed. `trusted` False: the placeholder."""
    if not enabled or store is None:
        return [e for e in events if e.get("kind") != "memory"]
    ids = [i for e in events if e.get("kind") == "memory" for i in (e.get("data") or {}).get("note_ids") or []]
    notes = store.get_many(account_id, ids) if ids and trusted else {}
    out = []
    for e in events:
        if e.get("kind") != "memory":
            out.append(e)
            continue
        data = e.get("data") or {}
        found = [notes.get(i) for i in data.get("note_ids") or []]
        message = _line(data.get("use"), found, None if trusted else UNTRUSTED)
        ids_ = data.get("note_ids") or []
        card = data.get("card") or ({"note_id": ids_[0]} if data.get("use") == "proposed" and ids_ else None)
        if card:  # the card's state is the note's state now: a tap on Save or Not now shows on the next read
            note = found[0] if found else None
            card = {**card, "status": note["status"] if note and trusted else "gone"}
            origin = card_origin(note) if note and trusted and note["status"] == "proposed" else ""
            if origin:
                card["origin"] = origin
            else:
                card.pop("origin", None)
            data = {**data, "card": card}
        out.append({**e, "message": message, "data": data})
    return out
