"""The owner's saved preferences as the model sees them (docs/superpowers/specs/2026-10-20-preferences-memory-design.md §5.3).

Once per task, a small block follows the request in the first user message: about-you notes plus the app and
people notes the request is about. When the task brings an app to the front for the first time, that app's
notes join the next observation. Local SQLite only: no phone call, no model call. Each note gets a per-task
alias ([m1], [m2]…) so the model can cite it without the note id leaving the server.

Note text goes only into the model request built from these blocks: never into events, logs or history.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..phone.apps import normalize
from . import gate

HEADER = ("Your owner's saved preferences (they confirmed these; the current request wins if they conflict). "
          "Cite [mN] when you rely on one. Don't repeat their text word for word unless asked. "
          "Use recall only for a person or app the request names that isn't listed here.")
PEOPLE_RULE = ("Find people by their contact name in the app. If none or several match, ask the owner; "
               "never type a number from memory.")
APP_HEADER = "Your owner's saved preferences for this app (cite [mN] when you rely on one):"

MAX_ABOUT = 10  # about-you notes in the start block
MAX_RELEVANT = 5  # app and people notes the request is about
MAX_BLOCK = 1600  # characters in the start block
MAX_APP = 5  # notes per app entered
MAX_RECALL = 5  # notes one recall returns
MAX_APP_BLOCK = 600  # characters per app block
SYSTEM_UI = "com.android.systemui"
MIN_LABEL = 3  # an installed app's name shorter than this is too likely to be a stray word


@dataclass
class Block:
    text: str = ""
    ids: list[str] = field(default_factory=list)  # every note in the block, in order
    aliases: dict[str, str] = field(default_factory=dict)  # "m1" -> note id (the task's whole mapping)
    relevant_ids: list[str] = field(default_factory=list)  # app and people matches (not about-you)


def packages_for(request: str, catalog, app_index: dict | None) -> list[str]:
    """Packages the request names: apps of the in-app links catalog (by their names) and installed apps whose
    display name appears in it as whole words. From cached data only: never asks the phone."""
    out: list[str] = []
    named = getattr(catalog, "_named_apps", None)
    if named is not None:
        for app_id in sorted(named(request)):
            out.extend(catalog.APPS[app_id].packages)
    text = f" {normalize(request)} "
    # A snapshot: the phone's app index is filled on a background thread (DeviceManager._index_apps) while the first
    # task may already be reading it; dict() copies in one step, iterating the live dict could raise.
    for package, label in dict(app_index or {}).items():
        name = normalize(label or "")
        if len(name) >= MIN_LABEL and f" {name} " in text:
            out.append(package)
    return list(dict.fromkeys(out))


def _alias(aliases: dict[str, str], note_id: str) -> str:
    for alias, nid in aliases.items():
        if nid == note_id:
            return alias
    alias = f"m{len(aliases) + 1}"
    aliases[alias] = note_id
    return alias


def _line(alias: str, note: dict) -> str:
    if note["kind"] == "person":
        return (f"- [{alias}] your {note['relation']}: {note['contact_name']} (a contact in their phone) — "
                f"{note['text']}")
    if note["kind"] == "app":
        return f"- [{alias}] in {note['package']}: {note['text']}"
    return f"- [{alias}] {note['text']}"


def _phrase_in(phrase: str | None, text: str) -> bool:
    phrase = normalize(phrase or "")
    return bool(phrase) and f" {phrase} " in text


def _render(header: str, notes: list[dict], aliases: dict[str, str], limit: int) -> tuple[str, list[dict]]:
    """The block for `notes` (best first), dropping the lowest-ranked until it fits `limit` characters."""
    notes = list(notes)
    while notes:
        trial = dict(aliases)
        lines = [_line(_alias(trial, n["id"]), n) for n in notes]
        if any(n["kind"] == "person" for n in notes):
            lines.append(PEOPLE_RULE)
        text = "\n".join([header, *lines])
        if len(text) <= limit:
            for n in notes:
                _alias(aliases, n["id"])
            return text, notes
        notes.pop()
    return "", []


def task_block(store, account_id: str | None, request: str, packages: list[str], people_ok: bool) -> Block:
    """The start block: relevant app and people notes first (≤ 5), then about-you notes (≤ 10), ≤ 1,600
    characters, trimmed from the lowest-ranked. People notes only when `people_ok` (not in "Don't ask" mode)."""
    text = f" {normalize(request)} "
    active = store.list(account_id, status="active")
    relevant: list[dict] = []
    for package in packages:  # the apps the request names
        relevant.extend(n for n in active if n["kind"] == "app" and n["package"] == package)
    if people_ok:  # people the request names, by relation or contact name
        relevant.extend(n for n in active if n["kind"] == "person"
                        and (_phrase_in(n["relation"], text) or _phrase_in(n["contact_name"], text)))
    found = store.search(account_id, request, limit=MAX_RELEVANT * 2)  # the request's words
    relevant.extend(n for n in found if n["kind"] == "app" or (n["kind"] == "person" and people_ok))
    seen: set[str] = set()
    relevant = [n for n in relevant if not (n["id"] in seen or seen.add(n["id"]))][:MAX_RELEVANT]
    # About-you notes: the request's search hits first, then the newest-used, capped together.
    about = [n for n in found if n["kind"] == "about_you"] + store.about_you(account_id, limit=MAX_ABOUT)
    about = [n for n in about if not (n["id"] in seen or seen.add(n["id"]))][:MAX_ABOUT]
    aliases: dict[str, str] = {}
    body, kept = _render(HEADER, relevant + about, aliases, MAX_BLOCK)
    kept_ids = [n["id"] for n in kept]
    return Block(body, kept_ids, aliases, [i for i in kept_ids if i in {n["id"] for n in relevant}])


def app_block(store, account_id: str | None, package: str | None, aliases: dict[str, str]) -> Block:
    """An app's notes the first time the task brings it to the front (≤ 5, ≤ 600 characters), leaving out
    notes already given this task. Nothing for the launcher or the system UI. Adds to `aliases`."""
    if not package or package == SYSTEM_UI or gate.is_launcher(package):
        return Block(aliases=aliases)
    given = set(aliases.values())
    notes = [n for n in store.for_app(account_id, package, limit=MAX_APP) if n["id"] not in given]
    body, kept = _render(APP_HEADER, notes, aliases, MAX_APP_BLOCK)
    return Block(body, [n["id"] for n in kept], aliases, [n["id"] for n in kept])


def texts(store, account_id: str | None, block: Block | None) -> list[str]:
    """The relevant notes' texts, for the fast text model and the classifier (read once, at task start)."""
    if block is None or not block.relevant_ids:
        return []
    notes = store.get_many(account_id, block.relevant_ids)
    return [_plain(notes[i]) for i in block.relevant_ids if i in notes]


def _plain(note: dict) -> str:
    if note["kind"] == "person":
        return f"your {note['relation']}: {note['contact_name']} (a contact) — {note['text']}"
    return note["text"]



def recall_text(notes: list[dict], aliases: dict[str, str]) -> str:
    """`recall`'s answer for the model: the notes with fresh per-task aliases (appended to `aliases`)."""
    if not notes:
        return "No saved preferences match that."
    lines = [_line(_alias(aliases, n["id"]), n) for n in notes]
    if any(n["kind"] == "person" for n in notes):
        lines.append(PEOPLE_RULE)
    return "\n".join(["Saved preferences (cite [mN] when you rely on one):", *lines])
