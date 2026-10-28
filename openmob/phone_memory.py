"""The phone's "What OpenMob remembers" page over the socket (docs/phone-protocol.md §3.9). The server checks the
switch, the pairing and the phone's trust before it calls [reply]; this only reads and changes the account's notes,
with the same rules as the dashboard's /api/memory (openmob/memory.py). Audit rows carry note ids, never text."""

from .memory import NoteError

KINDS = ("memory_list", "memory_edit", "memory_delete", "memory_confirm", "memory_dismiss")
DENIED = {"type": "memory", "denied": True}
FIELDS = ("id", "kind", "package", "relation", "contact_name", "text", "status")  # what the page shows, no more


def error(code: str) -> dict:
    """A message that can't be answered with the list (`rate_limited`, `bad_request`): the phone keeps what it shows."""
    return {"type": "memory", "ok": False, "error": code}


def listing(mem, account_id) -> dict:
    notes = [{k: n.get(k) for k in FIELDS} for n in mem.list(account_id)]
    return {"type": "memory", "notes": [n for n in notes if n["status"] == "active"],
            "proposed": [n for n in notes if n["status"] == "proposed"]}


def reply(mem, account_id, message: dict, audit) -> dict:
    """One page message: the account's notes, after the change it asks for. A write answers `ok`, or `ok: false` with
    `error` bad_note | unknown (missing or another account's) | not_proposed (Dismiss on a note saved since)."""
    kind = message.get("type")
    if kind == "memory_list":
        return listing(mem, account_id)
    note_id, text, contact = message.get("id"), message.get("text"), message.get("contact_name")
    if not isinstance(note_id, str) or not note_id or not all(v is None or isinstance(v, str) for v in (text, contact)):
        return error("bad_request")
    if kind == "memory_edit" and text is None and contact is None:
        return error("bad_request")  # nothing to change: no write, no audit row
    suffix, problem = "", None
    try:
        if kind == "memory_edit":
            found, action = mem.update(account_id, note_id, text=text, contact_name=contact) is not None, "memory.edited"
        elif kind == "memory_delete":
            found, action = mem.delete(account_id, note_id), "memory.deleted"
        elif kind == "memory_confirm":
            found, action = mem.confirm(account_id, note_id) is not None, "memory.confirmed"
        else:  # memory_dismiss: only while still a proposal (a stale tap can't delete a saved note)
            result = mem.dismiss(account_id, note_id)
            found, action, suffix = result is not None, "memory.deleted", " (not now)"
            problem = "not_proposed" if result is False else None
        if not found:
            problem = "unknown"
    except NoteError:
        problem = "bad_note"
    out = listing(mem, account_id)
    if problem:
        return {**out, "ok": False, "error": problem}
    audit(action, account_id, outcome=f"note {note_id}{suffix}")
    return {**out, "ok": True}
