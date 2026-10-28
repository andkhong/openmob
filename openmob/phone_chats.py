"""The phone reads chats (docs/design/phone-chats.md, docs/phone-protocol.md §3.6): this account's chats, one chat's
turns, opening a chat with this phone, and a new chat. The same rows the web dashboard shows, from the same History
queries; everything is scoped to the session's own account. A phone not trusted for the account (`own_only`: review 3
K3-M3, owner 2026-10-18 "own chats until trusted") lists, reads, opens, renames and deletes only chats with itself;
any other chat answers exactly like a missing one.

Text is redacted when it is recorded (the runner's `sensitive.redact`), so nothing here needs its own redaction. Sent
only: titles, times, the source, requests, results, outcomes, step lines and ask and stop lines. Never usage,
models, feedback, coordinates, anchors or packages.
"""

from __future__ import annotations

import time

from .memory import render_events
from .runner import is_stop

CHATS_PAGE = 50
TURNS_PAGE = 30
STEP_LINES = 40
TITLE_MAX, TEXT_MAX, STEP_MAX = 120, 600, 200
MESSAGES = 30  # corrections, answers and questions per turn
STOPPED_BY_OWNER = ("Stopped by the owner",)  # the owner's Stop on the phone, as its status line says
MAX_OFFSET = 1_000_000  # a page offset past any real list (SQLite takes at most 2**63 - 1)
RATE, BURST = 5.0, 20  # chat messages a socket may send: 5 a second, 20 at once (review 3 S3-L1)
# The answer each message gets, so an error reaches the same handler on the phone.
REPLY_TYPES = {"chats_list": "chats", "chat_read": "chat", "chat_open": "chat_opened", "chat_new": "chat_opened",
               "chat_rename": "chat_renamed", "chat_delete": "chat_deleted"}


def number(value, default: int, low: int, high: int) -> int:
    """A count or offset from the phone, clamped to [low, high]; anything not a finite number is [default]. (Review 3
    S3-L2: `Infinity` or `10**30` used to raise OverflowError out of the socket's loop.)"""
    try:
        n = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(low, min(high, n))


def error_reply(kind, error: str) -> dict:
    """A chat message that can't be answered (`bad_request`, `rate_limited`), in the type its answer has. No chat id:
    the phone's handlers then change nothing they show."""
    return {"type": REPLY_TYPES.get(str(kind), "chats"), "ok": False, "error": error}


class RateLimit:
    """A token bucket per socket: [rate] messages a second, [burst] at once. Excess is answered `rate_limited`."""

    def __init__(self, rate: float = RATE, burst: int = BURST, clock=time.monotonic):
        self.rate, self.burst, self.clock = rate, burst, clock
        self.tokens, self.at = float(burst), clock()

    def allow(self) -> bool:
        now = self.clock()
        self.tokens = min(self.burst, self.tokens + (now - self.at) * self.rate)
        self.at = now
        if self.tokens < 1:
            return False
        self.tokens -= 1
        return True


def _origin(source: str, this_phone: bool) -> str:
    """dashboard | api | mcp | drive (an outside agent's drive session) | local (the server's own terminal) | phone
    (this one) | other_phone | unknown. A chat's first request says where it started; only the exact source "phone"
    is a phone (review 3 S3-L3: a drive session's chat used to read as typed on this phone)."""
    if source in ("dashboard", "api", "mcp", "drive"):
        return source
    if source == "terminal":
        return "local"
    if source == "phone":
        return "phone" if this_phone else "other_phone"
    return "unknown"


def _chat(history, account_id: str | None, chat_id: str, device_id: str, own_only: bool) -> dict | None:
    """The chat this phone may see: this account's, and with an untrusted phone ([own_only]) only one with itself."""
    chat = history.chat(account_id, chat_id) if history is not None and chat_id else None
    if chat is None or (own_only and chat["device_id"] != device_id):
        return None
    return chat


def list_chats(history, account_id: str | None, device_id: str, message: dict, current: str | None,
               own_only: bool = False) -> dict:
    """`chats`: one page of this account's chats, newest first (an untrusted phone: only its own, `this_phone_only`)."""
    if history is None:
        return {"type": "chats", "chats": [], "more": False, "current": None, "available": False}
    offset = number(message.get("offset") or 0, 0, 0, MAX_OFFSET)
    limit = number(message.get("limit") or CHATS_PAGE, CHATS_PAGE, 1, CHATS_PAGE)
    q = " ".join(str(message.get("q") or "").split())[:100]  # title search over all of this account's chats
    rows = history.list_chats(account_id, limit=limit + 1, offset=offset, q=q, device_id=device_id if own_only else None)
    more, rows = len(rows) > limit, rows[:limit]
    sources = history.chat_sources(account_id, [r["id"] for r in rows])
    chats = [{
        "id": r["id"],
        "title": str(r["title"] or "")[:TITLE_MAX],
        "updated": r["updated"],
        "origin": _origin(sources.get(r["id"], ""), r["device_id"] == device_id),
        "this_phone": r["device_id"] == device_id,
    } for r in rows]
    return {"type": "chats", "chats": chats, "more": more, "offset": offset, "q": q, "current": current,
            "this_phone_only": own_only}


def _turns_from_events(events: list[dict], rows: list[dict]) -> list[dict]:
    """One chat's turns as the thread shows them, from its log (what the web replays) and its turn rows."""
    by_id = {r["id"]: r for r in rows}
    turns: dict[str, dict] = {}
    order: list[str] = []
    for e in events:
        task = e.get("task")
        if not task:
            continue
        turn = turns.get(task)
        if turn is None:
            row = by_id.get(task) or {}
            turn = turns[task] = {
                "id": task, "request": str(row.get("request") or "")[:TEXT_MAX], "started": row.get("started") or e["time"],
                "finished": row.get("finished"), "outcome": "running", "summary": "", "steps": 0, "step_lines": [],
                "asks": 0, "denied": False, "stopped_by_owner": False, "question": "",
                # The owner's corrections and answers, and the agent's questions, in order (as the web shows them).
                "messages": [], "heard": False,
            }
            order.append(task)
        kind, message, data = e.get("kind"), str(e.get("message") or ""), e.get("data") or {}
        said = message.split("] ", 1)[-1] if message.startswith("[") else message
        if kind == "heard" and not turn["heard"]:
            turn["heard"] = True  # the request itself
            if not turn["request"]:
                turn["request"] = said[:TEXT_MAX]
        elif kind == "heard":
            if not is_stop(said) and len(turn["messages"]) < MESSAGES:  # a stop shows as its own line
                turn["messages"].append({"kind": "answer", "text": said[:TEXT_MAX], "time": e["time"]})
        elif kind == "correction":
            if len(turn["messages"]) < MESSAGES:
                turn["messages"].append({"kind": "correction", "text": said[:TEXT_MAX], "time": e["time"]})
        elif kind == "action":  # the web lists actions only (Jev's classifier lines are hidden there too)
            turn["steps"] += 1
            if len(turn["step_lines"]) < STEP_LINES:
                turn["step_lines"].append(message[:STEP_MAX])
        elif kind == "memory":  # the preferences line, rendered at read time (memory.render_events)
            card = data.get("card")
            if card:  # a proposal: the card (Save / Not now while "proposed"), not a "Used your preferences" line
                if len(turn.setdefault("memory_cards", [])) < MESSAGES:
                    entry = {"note_id": str(card.get("note_id") or ""), "text": message[:TEXT_MAX],
                             "status": str(card.get("status") or "gone")}
                    if card.get("origin"):  # review 5 M5-L3: "Suggested from what the agent saw on screen", the app
                        entry["origin"] = str(card["origin"])[:TEXT_MAX]
                    turn["memory_cards"].append(entry)
            elif message and len(turn.setdefault("memory", [])) < MESSAGES:  # a key only when there is one
                turn["memory"].append(message[:TEXT_MAX])
        elif kind == "question":
            turn["question"] = message[:TEXT_MAX]
            turn["asks"] += 1
            if len(turn["messages"]) < MESSAGES:
                turn["messages"].append({"kind": "question", "text": message[:TEXT_MAX], "time": e["time"]})
        elif kind == "status" and message.startswith(STOPPED_BY_OWNER):
            turn["stopped_by_owner"] = True
        if data.get("final"):
            summary = message.rsplit(" (", 1)[0] if message.endswith(" steps)") else message
            turn["summary"] = summary[:TEXT_MAX]
            turn["outcome"] = "done" if data.get("success") else "stopped" if data.get("cancelled") else "failed"
            if data.get("reason") == "stopped_on_phone":
                turn["stopped_by_owner"] = True
            elif data.get("reason") == "blocked_app":  # the phone stopped it at a blocked app: "Stopped · blocked app"
                turn["outcome"] = "blocked"
            if "owner declined" in summary.lower():  # a denied approval ends the task (loop: task_declined)
                turn["denied"] = True
            turn["finished"] = turn["finished"] or e["time"]
            if data.get("steps") is not None:
                turn["steps"] = max(turn["steps"], int(data["steps"]))
            turn["question"] = ""
    for t in turns.values():
        t.pop("heard", None)
    return [turns[t] for t in order]


def read_chat(history, account_id: str | None, device_id: str, message: dict, active: set[str] | None = None,
              own_only: bool = False, memory=None, memory_on: bool = False) -> dict:
    """`chat`: one page of a chat's turns, newest last. Another account's chat is `unknown`, like a missing one (and,
    for an untrusted phone, another phone's). `active`: the account's queued or running task ids; a turn with no end
    that isn't one of them (the server restarted mid-task) is `interrupted`, not running."""
    chat_id = str(message.get("chat_id") or "")
    chat = _chat(history, account_id, chat_id, device_id, own_only)
    if chat is None:
        return {"type": "chat", "chat_id": chat_id, "error": "unknown"}
    # Paged in SQL (review 3 S3-L1): the turns' order from the index, then only this page's events and rows, so a
    # long chat's read no longer loads its whole log under History's lock.
    order = history.turn_order(account_id, chat_id) or []
    raw = message.get("before")
    before = len(order) if raw is None else number(raw, len(order), 0, len(order))
    start = max(0, before - TURNS_PAGE)
    events, rows = history.turn_page(account_id, chat_id, order[start:before])
    # Preferences lines: filled from the notes' current text; an untrusted phone gets the placeholder (own_only).
    events = render_events(memory, account_id, events, trusted=not own_only, enabled=memory_on)
    turns = _turns_from_events(events, rows)
    for t in turns:
        if t["outcome"] == "running" and t["id"] not in (active or set()):
            t["outcome"] = "interrupted"
            t["question"] = ""
    return {"type": "chat", "chat_id": chat_id, "title": str(chat["title"] or "")[:TITLE_MAX],
            "updated": chat["updated"], "this_phone": chat["device_id"] == device_id,
            "turns": turns, "first": start, "more": start > 0}


def open_chat(history, coordinator, account_id: str | None, device_id: str, message: dict, own_only: bool = False) -> dict:
    """`chat_opened`: new tasks from now on go into this chat (only a chat with this phone, as on the web). An untrusted
    phone isn't told that another phone's chat exists: `unknown`, not `other_phone`."""
    chat_id = str(message.get("chat_id") or "")
    chat = _chat(history, account_id, chat_id, device_id, own_only)
    if chat is None:
        return {"type": "chat_opened", "ok": False, "chat_id": chat_id, "error": "unknown"}
    if chat["device_id"] != device_id:
        return {"type": "chat_opened", "ok": False, "chat_id": chat_id, "error": "other_phone"}
    try:
        if not coordinator.open_chat(chat_id):
            return {"type": "chat_opened", "ok": False, "chat_id": chat_id, "error": "unknown"}
    except RuntimeError:  # a task is running: switching waits until it ends
        return {"type": "chat_opened", "ok": False, "chat_id": chat_id, "error": "busy"}
    return {"type": "chat_opened", "ok": True, "chat_id": chat_id}


def _running_in(sessions, chat_id: str) -> bool:
    return any(s.coordinator.chat_id == chat_id and s.coordinator.current is not None for s in sessions)


def delete_chat(history, sessions, account_id: str | None, chat_id: str, device_id: str = "", own_only: bool = False) -> str:
    """Delete one of this account's chats (the web's DELETE and the phone's `chat_delete`): "ok", "unknown" (not this
    account's, missing, or for an untrusted phone another phone's) or "busy" (a task is running in it). A session
    showing it continues as a fresh chat."""
    if _chat(history, account_id, chat_id, device_id, own_only) is None:
        return "unknown"
    sessions = list(sessions)
    if _running_in(sessions, chat_id):
        return "busy"
    if not history.delete_chat(account_id, chat_id):
        return "unknown"
    for s in sessions:
        if s.coordinator.chat_id == chat_id and s.coordinator.current is None:
            try:
                s.coordinator.clear_log()
            except RuntimeError:  # a task started in between: it has the old id, nothing to record into
                pass
    return "ok"


def rename_message(history, account_id: str | None, message: dict, device_id: str = "", own_only: bool = False) -> dict:
    """`chat_renamed`: the same rename as the web (trimmed, capped at 120)."""
    chat_id = str(message.get("chat_id") or "")
    title = " ".join(str(message.get("title") or "").split())[:TITLE_MAX]
    if _chat(history, account_id, chat_id, device_id, own_only) is None:
        return {"type": "chat_renamed", "ok": False, "chat_id": chat_id, "error": "unknown"}
    if not title:
        return {"type": "chat_renamed", "ok": False, "chat_id": chat_id, "error": "bad_title"}
    if not history.rename_chat(account_id, chat_id, title):
        return {"type": "chat_renamed", "ok": False, "chat_id": chat_id, "error": "unknown"}
    return {"type": "chat_renamed", "ok": True, "chat_id": chat_id, "title": title}


def delete_message(history, sessions, account_id: str | None, message: dict, device_id: str = "",
                   own_only: bool = False) -> dict:
    chat_id = str(message.get("chat_id") or "")
    result = delete_chat(history, sessions, account_id, chat_id, device_id, own_only)
    if result != "ok":
        return {"type": "chat_deleted", "ok": False, "chat_id": chat_id, "error": result}
    return {"type": "chat_deleted", "ok": True, "chat_id": chat_id}


def new_chat(coordinator) -> dict:
    try:
        coordinator.clear_log()
    except RuntimeError:
        return {"type": "chat_opened", "ok": False, "chat_id": None, "error": "busy"}
    return {"type": "chat_opened", "ok": True, "chat_id": None}
