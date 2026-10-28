"""Chat history, and the foundation for agents that learn from past interactions.

Every request is stored as a structured *turn*: what was asked, each step the agent took, how it
ended, which model ran it, its tokens, and the user's feedback (👍/👎). Each step is also a
structured *steps* row (tool, redacted args, normalized coordinates, app, element anchor, outcome,
latency), the raw material for learning skills, app notes and per-model success rates.

Text only: screenshots are never stored, and typed text is redacted. Rows are scoped to the owning
account, and deleting a chat deletes its turns, events and steps. SQLite in the data directory (a
Fly volume when hosted).
"""

from __future__ import annotations

import atexit
import json
import os
import queue
import sqlite3
import threading
import time
import uuid
from pathlib import Path

DEFAULT_PATH = Path(os.environ.get("OPENMOB_DATA_DIR") or Path.home() / ".config" / "openmob") / "history.sqlite"
LOCAL_ACCOUNT = "local"  # owner of chats on servers without accounts (token mode)
TITLE_LENGTH = 60

SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    device_model TEXT,
    title TEXT NOT NULL,
    created REAL NOT NULL,
    updated REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS chats_by_account ON chats (account_id, updated DESC);

CREATE TABLE IF NOT EXISTS turns (
    id TEXT PRIMARY KEY,              -- the task id used in the live log
    chat_id TEXT NOT NULL REFERENCES chats (id) ON DELETE CASCADE,
    request TEXT NOT NULL,
    model TEXT,
    started REAL NOT NULL,
    finished REAL,
    success INTEGER,                  -- 1 / 0, NULL while running
    summary TEXT,
    steps INTEGER,
    usage TEXT,                       -- JSON token counts
    feedback INTEGER,                 -- 1 = 👍, -1 = 👎, NULL = none
    feedback_note TEXT,
    package TEXT                      -- the last foreground app
);
CREATE INDEX IF NOT EXISTS turns_by_chat ON turns (chat_id, started);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL REFERENCES chats (id) ON DELETE CASCADE,
    turn_id TEXT,
    time REAL NOT NULL,
    kind TEXT NOT NULL,
    message TEXT NOT NULL,
    data TEXT                         -- JSON details (final outcome, token counts)
);
CREATE INDEX IF NOT EXISTS events_by_chat ON events (chat_id, id);
CREATE INDEX IF NOT EXISTS events_by_turn ON events (chat_id, turn_id, id);

-- One row per tool call the agent made (the trajectory). Never a screenshot; typed text redacted.
CREATE TABLE IF NOT EXISTS steps (
    turn_id TEXT NOT NULL,
    idx INTEGER NOT NULL,             -- 1, 2, … within the turn
    chat_id TEXT NOT NULL REFERENCES chats (id) ON DELETE CASCADE,
    account_id TEXT NOT NULL,
    device_id TEXT,
    t REAL NOT NULL,
    tool TEXT NOT NULL,
    args TEXT NOT NULL,               -- JSON, redacted
    norm_xy TEXT,                     -- JSON [x, y, …]: each point as 0-1 fractions of the device screen
    package TEXT,                     -- foreground app when the step was taken
    screen_w INTEGER,
    screen_h INTEGER,
    anchor TEXT,                      -- JSON {text, desc, resource_id, class, bounds, index} for tap_element
    outcome TEXT,
    is_error INTEGER NOT NULL,
    latency_ms INTEGER,               -- the tool call itself: risk check, approval/answer waits, phone action (no settle, no model)
    source TEXT NOT NULL DEFAULT 'agent',  -- agent | replay (a stored path, no main model) | user_demo | macro | routine
    -- Where the step's time went, in ms (see agent/timing.py; NULL on rows from before timings).
    -- A step runs from the end of the previous step's action to the end of its own.
    observe_ms INTEGER,
    jev_ms INTEGER,                   -- the screen classifier (0 when it was off)
    wait_ms INTEGER,                  -- human / loading-screen time, kept out of agent time
    model_ms INTEGER,
    action_ms INTEGER,
    settle_ms INTEGER,
    total_ms INTEGER,
    jev INTEGER,                      -- 1 / 0: whether the classifier was on for this step
    model TEXT,                       -- the model that decided this step
    settle_idle INTEGER,              -- 1 / 0: the adaptive settle before it saw the screen go quiet / hit its cap (NULL: fixed sleep)
    fast INTEGER,                     -- 1: decided by the fast path (classifier + small text model), 0: by the main model
    variant TEXT,                     -- the latency features the agent ran with: fixed | adaptive | adaptive+fast …
    done_via TEXT,                    -- on a done step: vision (the main model) | classifier (fast_path_done)
    handled_by TEXT,                  -- a step no model decided: permission_rule (agent/permission_dialogs.py)
    -- The main model call(s) that decided this step (NULL on fast steps without one, and older rows).
    input_tokens INTEGER,             -- uncached input
    output_tokens INTEGER,
    cache_read_tokens INTEGER,        -- input read from the provider's prompt cache
    cache_write_tokens INTEGER,       -- input written to it (Anthropic)
    vision_image_side INTEGER,        -- the long side in px of the screenshot the model saw (NULL: none)
    PRIMARY KEY (turn_id, idx)
);
CREATE INDEX IF NOT EXISTS steps_by_chat ON steps (chat_id);

-- Per-model outcomes of finished tasks (no content), for success rates by model. Kept when a chat
-- is deleted, since it holds only the model, the outcome and the step count.
CREATE TABLE IF NOT EXISTS model_runs (
    turn_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    model TEXT NOT NULL,
    success INTEGER NOT NULL,
    steps INTEGER,
    finished REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS model_runs_by_model ON model_runs (model, account_id);

-- One row per approval prompt the owner saw (permission telemetry, `openmob prompts`). No text: the
-- prompt's kind, the mode, the decision and how long the owner took from shown to answered.
CREATE TABLE IF NOT EXISTS prompts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    device_id TEXT,
    t REAL NOT NULL,
    kind TEXT,                        -- action | step (ask mode) | plan
    action_kind TEXT,                 -- send | delete | post | pay | fill | settings | NULL
    mode TEXT,                        -- the permission mode then
    decision TEXT,                    -- approved | always | denied | changes
    latency_ms INTEGER,
    package TEXT
);
CREATE INDEX IF NOT EXISTS prompts_by_time ON prompts (t);
"""

# Columns added after the first release, for databases created before them.
TIMING_COLUMNS = ("observe_ms", "jev_ms", "wait_ms", "model_ms", "action_ms", "settle_ms", "total_ms")
TOKEN_COLUMNS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "vision_image_side")
MIGRATIONS = [("turns", "package", "TEXT")] + [
    ("steps", column, "INTEGER") for column in TIMING_COLUMNS + ("jev",)
] + [("steps", "model", "TEXT"), ("steps", "settle_idle", "INTEGER"), ("steps", "fast", "INTEGER"),
      ("steps", "variant", "TEXT"), ("steps", "done_via", "TEXT"), ("steps", "handled_by", "TEXT"),
      ("turns", "prompts", "INTEGER"), ("turns", "mode", "TEXT")] + [
    ("steps", column, "INTEGER") for column in TOKEN_COLUMNS
] + [("steps", column, kind) for column, kind in (
    # A wait (agent/waiting.py) on this step: the wait_until tool's, the `wait` tool's sleep, or the loop's own
    # ("auto:…", after a launch or an Install tap). wait_cond: e.g. text_appears:Open|Play, sleep, auto:loading_done.
    ("wait_cond", "TEXT"), ("wait_met", "INTEGER"), ("wait_via", "TEXT"), ("waited_ms", "INTEGER"))] + [
    # Faster mode (docs/design/faster-mode.md): faster 1/0 = on for this phone at this step; jev_images = screenshots
    # sent to TypeSafe on this step and jev_image_ms their wall time (part of jev_ms); jev_state = the screen state
    # an image check named (J1); jev_image_skip = why an image wasn't sent while it was on (agent/faster.py).
    ("steps", column, kind) for column, kind in (
        ("faster", "INTEGER"), ("jev_images", "INTEGER"), ("jev_image_ms", "INTEGER"), ("jev_state", "TEXT"),
        ("jev_image_skip", "TEXT"),
        # Jev taps (step 2): JSON {state, choice, p, conf, box, box_conf, visible, rule, tap, verify} or {skip}.
        ("jev_tap", "TEXT"))]
WAIT_COLUMNS = ("wait_cond", "wait_met", "wait_via", "waited_ms")
FASTER_COLUMNS = ("faster", "jev_images", "jev_image_ms", "jev_state", "jev_image_skip", "jev_tap")


# The background writer's queue: past this many pending writes, a writer waits (backpressure, never a dropped row).
WRITE_QUEUE_MAX = 10_000
WRITE_BATCH_MAX = 256  # writes committed together in one transaction (one fsync instead of one per row)
FLUSH_TIMEOUT_S = 10.0


class _Writer:
    """One thread that runs the per-step and per-event writes in the order they were queued (perf/prelaunch-1-4,
    2026-10-20). Before, each step's and each event's INSERT ran on the agent's thread (and the event loop's) under
    the one connection's lock, so a slow disk or a busy neighbour's write held up the next phone action. Readers
    call flush() first (History._q), so anything read back sees every write queued before it."""

    def __init__(self, history: History, maxsize: int = WRITE_QUEUE_MAX):
        self.history = history
        self.queue: queue.Queue = queue.Queue(maxsize)
        self._put_lock = threading.Lock()  # seq order == queue order
        self._done = threading.Condition()
        self.queued = 0
        self.done = 0
        self.closed = False
        self.thread = threading.Thread(target=self._run, name="history-writer", daemon=True)
        self.thread.start()

    def put(self, write) -> None:
        if threading.current_thread() is self.thread:  # a write from inside a write: run it now (no deadlock)
            write(self.history._db)
            return
        with self._put_lock:
            if self.closed:
                raise RuntimeError("history is closed")
            self.queued += 1
            self.queue.put(write)  # blocks while the queue is full

    def flush(self, timeout: float = FLUSH_TIMEOUT_S) -> bool:
        """Wait until every write queued so far is in the database. False on timeout (the writer is stuck)."""
        if threading.current_thread() is self.thread:
            return True
        with self._put_lock:
            target = self.queued
        with self._done:
            return self._done.wait_for(lambda: self.done >= target, timeout)

    def close(self) -> None:
        with self._put_lock:
            if self.closed:
                return
            self.closed = True
            self.queue.put(None)
        self.thread.join(FLUSH_TIMEOUT_S)

    def _run(self) -> None:
        db = self.history._db
        while True:
            batch = [self.queue.get()]
            while len(batch) < WRITE_BATCH_MAX:
                try:
                    batch.append(self.queue.get_nowait())
                except queue.Empty:
                    break
            stop = None in batch
            writes = [w for w in batch if w is not None]
            with self.history._lock:
                try:
                    db.execute("BEGIN")
                except sqlite3.Error:
                    pass
                for write in writes:
                    try:
                        write(db)
                    except Exception as exc:  # history must never break the agent (as when writes were inline)
                        print(f"⚠️  History not saved: {exc!r}", flush=True)
                try:
                    db.execute("COMMIT")
                except sqlite3.Error:
                    pass
            with self._done:
                self.done += len(writes)
                self._done.notify_all()
            if stop:
                return


class History:
    def __init__(self, path: Path | str = DEFAULT_PATH, background: bool | None = None):
        """`background` (default off for launch, 2026-10-21; OPENMOB_HISTORY_WRITER=on turns it on): step, event,
        prompt and model-run writes go to one writer thread instead of running on the caller's thread (_Writer).
        Off by default because it measured no task-time gain and adds a crash-loss window (atexit doesn't run on
        SIGKILL)."""
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.executescript(SCHEMA)
        for table, column, kind in MIGRATIONS:
            have = {r["name"] for r in self._db.execute(f"PRAGMA table_info({table})")}
            if column not in have:
                self._db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
        try:
            os.chmod(self.path, 0o600)  # private conversations: owner-only
        except OSError:
            pass
        if background is None:
            background = os.environ.get("OPENMOB_HISTORY_WRITER", "").strip().lower() in ("1", "on", "true", "yes")
        self._writer = _Writer(self) if background else None
        if self._writer is not None:
            atexit.register(self.close)  # flush on shutdown (the server exits normally on SIGTERM)

    def _write(self, write) -> None:
        """Run `write(db)` on the writer thread, after every write queued before it (inline without one)."""
        if self._writer is None:
            with self._lock:
                write(self._db)
        else:
            self._writer.put(write)

    def flush(self) -> bool:
        """Every write queued so far is in the database (readers do this first)."""
        return self._writer.flush() if self._writer is not None else True

    def close(self) -> None:
        """Flush the queued writes and stop the writer (the connection stays usable inline)."""
        writer, self._writer = self._writer, None
        if writer is not None:
            writer.flush()
            writer.close()

    def _q(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        self.flush()  # read-your-writes: a step or event queued before this read is in the database
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    # --- chats -------------------------------------------------------------

    def create_chat(self, account_id: str | None, device_id: str, device_model: str, first_request: str) -> str:
        chat_id = uuid.uuid4().hex[:16]
        now = time.time()
        title = " ".join(first_request.split())[:TITLE_LENGTH] or "New chat"
        self._q(
            "INSERT INTO chats (id, account_id, device_id, device_model, title, created, updated) VALUES (?,?,?,?,?,?,?)",
            (chat_id, account_id or LOCAL_ACCOUNT, device_id, device_model, title, now, now),
        )
        return chat_id

    def chat(self, account_id: str | None, chat_id: str) -> dict | None:
        """The chat if this account owns it, else None (callers answer 404)."""
        rows = self._q("SELECT * FROM chats WHERE id = ? AND account_id = ?", (chat_id, account_id or LOCAL_ACCOUNT))
        return dict(rows[0]) if rows else None

    def list_chats(self, account_id: str | None, limit: int = 100, offset: int = 0, q: str = "",
                   device_id: str | None = None) -> list[dict]:
        """This account's chats, newest first. `q`: only titles containing it (case-insensitive, as typed).
        `device_id`: only chats with that phone (an untrusted phone's own view, docs/design/phone-chats.md)."""
        q = (q or "")[:100]
        like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        rows = self._q(
            """SELECT c.*, (SELECT COUNT(*) FROM turns t WHERE t.chat_id = c.id) AS turns
               FROM chats c WHERE c.account_id = ? AND (? = '' OR c.title LIKE ? ESCAPE '\\')
               AND (? IS NULL OR c.device_id = ?)
               ORDER BY c.updated DESC LIMIT ? OFFSET ?""",
            (account_id or LOCAL_ACCOUNT, q, like, device_id, device_id, limit, max(0, offset)),
        )
        return [dict(r) for r in rows]

    def chat_sources(self, account_id: str | None, chat_ids: list[str]) -> dict[str, str]:
        """Where each of this account's chats started: the source of its first request ("phone", "web", "api", …)."""
        if not chat_ids:
            return {}
        marks = ",".join("?" * len(chat_ids))
        rows = self._q(
            f"""SELECT e.chat_id, e.message FROM events e JOIN chats c ON c.id = e.chat_id
                WHERE c.account_id = ? AND e.chat_id IN ({marks}) AND e.kind = 'heard'
                AND e.id = (SELECT MIN(id) FROM events WHERE chat_id = e.chat_id AND kind = 'heard')""",
            (account_id or LOCAL_ACCOUNT, *chat_ids),
        )
        out = {}
        for r in rows:
            message = r["message"]
            out[r["chat_id"]] = message[1:message.index("]")] if message.startswith("[") and "]" in message else ""
        return out

    def rename_chat(self, account_id: str | None, chat_id: str, title: str) -> bool:
        title = " ".join(title.split())[:120]
        if not title or not self.chat(account_id, chat_id):
            return False
        self._q("UPDATE chats SET title = ? WHERE id = ?", (title, chat_id))
        return True

    def delete_chat(self, account_id: str | None, chat_id: str) -> bool:
        """Deletes the chat with all its turns and events (not just hidden)."""
        if not self.chat(account_id, chat_id):
            return False
        self._q("DELETE FROM chats WHERE id = ?", (chat_id,))
        return True

    # --- recording (called by the Coordinator as events happen) ------------

    def record(self, chat_id: str, entry: dict) -> None:
        """Store one live-log entry and keep the turn summary up to date."""
        kind, task, data = entry["kind"], entry.get("task"), entry.get("data") or {}
        now = entry.get("time", time.time())
        message = entry["message"]
        data_json = json.dumps(data) if data else None  # serialized now: the caller may change `data` later
        data = json.loads(data_json) if data_json else {}
        self._write(lambda db: self._record(db, chat_id, kind, task, now, message, data, data_json))

    @staticmethod
    def _record(db, chat_id: str, kind: str, task, now: float, message: str, data: dict, data_json) -> None:
        db.execute(
            "INSERT INTO events (chat_id, turn_id, time, kind, message, data) VALUES (?,?,?,?,?,?)",
            (chat_id, task, now, kind, message, data_json),
        )
        db.execute("UPDATE chats SET updated = ? WHERE id = ?", (now, chat_id))
        if task is None:
            return
        if kind == "heard" and not db.execute("SELECT 1 FROM turns WHERE id = ?", (task,)).fetchone():
            request = message.split("] ", 1)[-1] if message.startswith("[") else message
            db.execute(
                "INSERT INTO turns (id, chat_id, request, model, started) VALUES (?,?,?,?,?)",
                (task, chat_id, request, data.get("model"), now),
            )
        elif data.get("final"):
            summary = message.rsplit(" (", 1)[0] if message.endswith(" steps)") else message
            db.execute(
                "UPDATE turns SET finished = ?, success = ?, summary = ?, steps = ?, prompts = ?, mode = ? "
                "WHERE id = ?",
                (now, 1 if data.get("success") else 0, summary, data.get("steps"), data.get("prompts"),
                 data.get("mode"), task),
            )
        elif kind == "usage":
            models = list((data.get("by_model") or {}).keys())
            db.execute(
                "UPDATE turns SET usage = ?, model = COALESCE(?, model) WHERE id = ?",
                (json.dumps(data), models[0] if len(models) == 1 else None, task),
            )

    def record_step(self, chat_id: str, turn_id: str, step: dict, account_id: str | None = None, device_id: str = "") -> None:
        """Store one structured step (from Agent._record_step) and the turn's latest foreground app."""
        def js(value):
            return json.dumps(value) if value is not None else None

        step = dict(step)  # the agent may update its record later (a streamed reply's tokens): this write keeps now's
        _ = step["idx"], step["tool"]  # a malformed step fails here, in the caller, as before
        step.setdefault("t", time.time())
        step["args"] = json.dumps(step.get("args") or {}, default=str)
        for key in ("norm_xy", "anchor", "jev_tap"):
            step[key] = js(step.get(key))
        self._write(lambda db: self._record_step(db, chat_id, turn_id, step, account_id, device_id))

    @staticmethod
    def _record_step(db, chat_id: str, turn_id: str, step: dict, account_id: str | None, device_id: str) -> None:
        db.execute(
            """INSERT OR REPLACE INTO steps (turn_id, idx, chat_id, account_id, device_id, t, tool, args, norm_xy,
               package, screen_w, screen_h, anchor, outcome, is_error, latency_ms, source,
               observe_ms, jev_ms, wait_ms, model_ms, action_ms, settle_ms, total_ms, jev, model,
               settle_idle, fast, variant, done_via, input_tokens, output_tokens, cache_read_tokens,
               cache_write_tokens, vision_image_side, handled_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (turn_id, step["idx"], chat_id, account_id or LOCAL_ACCOUNT, device_id, step.get("t", time.time()),
             step["tool"], step["args"], step.get("norm_xy"),
             step.get("package"), step.get("screen_w"), step.get("screen_h"), step.get("anchor"),
             step.get("outcome"), 1 if step.get("is_error") else 0, step.get("latency_ms"),
             step.get("source", "agent"),
             *(step.get(c) for c in TIMING_COLUMNS),
             None if step.get("jev") is None else int(bool(step["jev"])), step.get("model"),
             None if step.get("settle_idle") is None else int(bool(step["settle_idle"])),
             None if step.get("fast") is None else int(bool(step["fast"])), step.get("variant"),
             step.get("done_via"), *(step.get(c) for c in TOKEN_COLUMNS), step.get("handled_by")),
        )
        if step.get("wait_cond"):
            met = step.get("wait_met")
            db.execute("UPDATE steps SET wait_cond = ?, wait_met = ?, wait_via = ?, waited_ms = ? "
                       "WHERE turn_id = ? AND idx = ?",
                       (step["wait_cond"], None if met is None else int(bool(met)), step.get("wait_via"),
                        step.get("waited_ms"), turn_id, step["idx"]))
        if any(step.get(c) is not None for c in FASTER_COLUMNS):
            on = step.get("faster")
            db.execute("UPDATE steps SET faster = ?, jev_images = ?, jev_image_ms = ?, jev_state = ?, "
                       "jev_image_skip = ?, jev_tap = ? WHERE turn_id = ? AND idx = ?",
                       (None if on is None else int(bool(on)), step.get("jev_images"),
                        step.get("jev_image_ms"), step.get("jev_state"), step.get("jev_image_skip"),
                        step.get("jev_tap"), turn_id, step["idx"]))
        if step.get("package"):
            db.execute("UPDATE turns SET package = ? WHERE id = ?", (step["package"], turn_id))

    def record_prompt(self, turn_id: str, prompt: dict, account_id: str | None = None, device_id: str = "") -> None:
        """One approval prompt (Agent._ask_owner): its kind, mode, decision and latency. No text."""
        self._execute_later(
            "INSERT INTO prompts (turn_id, account_id, device_id, t, kind, action_kind, mode, decision, latency_ms, "
            "package) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (turn_id, account_id or LOCAL_ACCOUNT, device_id, prompt.get("t", time.time()), prompt.get("kind"),
             prompt.get("action_kind"), prompt.get("mode"), prompt.get("decision"), prompt.get("latency_ms"),
             prompt.get("package")),
        )

    def prompt_rows(self, since: float = 0.0) -> tuple[list[dict], list[dict]]:
        """(prompts since then, finished tasks since then with their prompt count and mode)."""
        prompts = [dict(r) for r in self._q("SELECT * FROM prompts WHERE t >= ? ORDER BY t", (since,))]
        tasks = [dict(r) for r in self._q(
            "SELECT id, prompts, mode, success FROM turns WHERE finished IS NOT NULL AND started >= ? "
            "AND prompts IS NOT NULL ORDER BY started", (since,))]
        return prompts, tasks

    def record_model_run(self, account_id: str | None, turn_id: str, model: str, success: bool, steps: int | None) -> None:
        self._execute_later(
            "INSERT OR REPLACE INTO model_runs (turn_id, account_id, model, success, steps, finished) VALUES (?,?,?,?,?,?)",
            (turn_id, account_id or LOCAL_ACCOUNT, model, 1 if success else 0, steps, time.time()),
        )

    def _execute_later(self, sql: str, args: tuple) -> None:
        self._write(lambda db: db.execute(sql, args))

    # --- reading back ------------------------------------------------------

    def events(self, account_id: str | None, chat_id: str) -> list[dict] | None:
        """The chat's log, in the same shape as the live log (None if not this account's chat)."""
        if not self.chat(account_id, chat_id):
            return None
        rows = self._q("SELECT * FROM events WHERE chat_id = ? ORDER BY id", (chat_id,))
        out = []
        for r in rows:
            entry = {"time": r["time"], "kind": r["kind"], "message": r["message"], "task": r["turn_id"]}
            if r["data"]:
                entry["data"] = json.loads(r["data"])
            out.append(entry)
        return out

    def turns(self, account_id: str | None, chat_id: str) -> list[dict]:
        if not self.chat(account_id, chat_id):
            return []
        return [dict(r) for r in self._q("SELECT * FROM turns WHERE chat_id = ? ORDER BY started", (chat_id,))]

    def turn_order(self, account_id: str | None, chat_id: str) -> list[str] | None:
        """The chat's turn ids in the order their first event was logged (the thread's order), from the index only;
        None if not this account's chat. With [turn_page], a page of a long chat reads only its own events."""
        if not self.chat(account_id, chat_id):
            return None
        rows = self._q(
            """SELECT turn_id FROM events WHERE chat_id = ? AND turn_id IS NOT NULL AND turn_id != ''
               GROUP BY turn_id ORDER BY MIN(id)""",
            (chat_id,),
        )
        return [r["turn_id"] for r in rows]

    def turn_page(self, account_id: str | None, chat_id: str, turn_ids: list[str]) -> tuple[list[dict], list[dict]]:
        """These turns' events (the live log's shape, in order) and their turn rows: one page of a chat's thread."""
        if not turn_ids or not self.chat(account_id, chat_id):
            return [], []
        marks = ",".join("?" * len(turn_ids))
        rows = self._q(f"SELECT * FROM events WHERE chat_id = ? AND turn_id IN ({marks}) ORDER BY id", (chat_id, *turn_ids))
        events = []
        for r in rows:
            entry = {"time": r["time"], "kind": r["kind"], "message": r["message"], "task": r["turn_id"]}
            if r["data"]:
                entry["data"] = json.loads(r["data"])
            events.append(entry)
        turns = self._q(f"SELECT * FROM turns WHERE chat_id = ? AND id IN ({marks}) ORDER BY started", (chat_id, *turn_ids))
        return events, [dict(r) for r in turns]

    def turn(self, account_id: str | None, turn_id: str) -> dict | None:
        """One turn (a task) by its id, if this account owns it, with its chat's device."""
        rows = self._q(
            """SELECT t.*, c.device_id FROM turns t JOIN chats c ON c.id = t.chat_id
               WHERE t.id = ? AND c.account_id = ?""",
            (turn_id, account_id or LOCAL_ACCOUNT),
        )
        return dict(rows[0]) if rows else None

    def steps(self, account_id: str | None, turn_id: str) -> list[dict]:
        """A turn's structured steps, in order (empty if it isn't this account's)."""
        rows = self._q("SELECT * FROM steps WHERE turn_id = ? AND account_id = ? ORDER BY idx",
                       (turn_id, account_id or LOCAL_ACCOUNT))
        out = []
        for r in rows:
            step = dict(r)
            for key in ("args", "norm_xy", "anchor"):
                step[key] = json.loads(step[key]) if step[key] else None
            step["is_error"] = bool(step["is_error"])
            for key in ("jev", "settle_idle", "fast"):
                step[key] = None if step[key] is None else bool(step[key])
            out.append(step)
        return out

    def step_timings(self, since: float = 0.0, chat_id: str | None = None, model: str | None = None) -> list[dict]:
        """Every account's agent steps that have timings (for `openmob timings`): the timing
        columns plus turn_id, jev and model (the step's, else its turn's)."""
        where, args = ["s.total_ms IS NOT NULL", "s.t >= ?", "s.source IN ('agent', 'replay')"], [since]
        if chat_id:
            where.append("s.chat_id = ?")
            args.append(chat_id)
        if model:
            where.append("COALESCE(s.model, t.model) = ?")
            args.append(model)
        rows = self._q(
            f"""SELECT s.turn_id, s.idx, s.jev, s.fast, s.variant, s.settle_idle, s.done_via, COALESCE(s.model, t.model) AS model,
                       {", ".join("s." + c for c in TIMING_COLUMNS + TOKEN_COLUMNS + WAIT_COLUMNS)}
                FROM steps s LEFT JOIN turns t ON t.id = s.turn_id WHERE {" AND ".join(where)} ORDER BY s.t""",
            tuple(args),
        )
        return [dict(r) for r in rows]

    def model_stats(self, account_id: str | None = None, since: float = 0.0) -> list[dict]:
        """Success rate per model over finished tasks (stopped tasks don't count): one account's,
        or every account's when account_id is None. Most-used model first."""
        where, args = "finished >= ?", [since]
        if account_id is not None:
            where += " AND account_id = ?"
            args.append(account_id)
        rows = self._q(
            f"""SELECT model, COUNT(*) AS tasks, SUM(success) AS succeeded, AVG(steps) AS avg_steps
                FROM model_runs WHERE {where} GROUP BY model ORDER BY tasks DESC, model""",
            tuple(args),
        )
        return [{"model": r["model"], "tasks": r["tasks"], "succeeded": r["succeeded"],
                 "success_rate": round(r["succeeded"] / r["tasks"], 3),
                 "avg_steps": round(r["avg_steps"], 1) if r["avg_steps"] is not None else None} for r in rows]

    def purge(self, older_than_days: float) -> int:
        """Retention: delete chats not updated for this many days (turns and events go with them)."""
        if older_than_days <= 0:
            return 0
        cutoff = time.time() - older_than_days * 86400
        self.flush()
        with self._lock:
            return self._db.execute("DELETE FROM chats WHERE updated < ?", (cutoff,)).rowcount

    def recent_requests(self, account_id: str | None, chat_id: str, limit: int = 5) -> list[tuple[str, str]]:
        """(request, outcome) pairs to restore the agent's memory when a chat is reopened."""
        done = [t for t in self.turns(account_id, chat_id) if t["finished"]]
        return [(t["request"], t["summary"] or "") for t in done[-limit:]]

    # --- feedback (learning signal) -----------------------------------------

    def set_feedback(self, account_id: str | None, turn_id: str, value: int, note: str = "") -> bool:
        if value not in (1, -1, 0):
            raise ValueError("feedback must be 1, -1 or 0")
        rows = self._q(
            "SELECT t.id FROM turns t JOIN chats c ON c.id = t.chat_id WHERE t.id = ? AND c.account_id = ?",
            (turn_id, account_id or LOCAL_ACCOUNT),
        )
        if not rows:
            return False
        self._q(
            "UPDATE turns SET feedback = ?, feedback_note = ? WHERE id = ?",
            (value or None, (note or "")[:1000] or None, turn_id),
        )
        return True

    def feedback_map(self, account_id: str | None, chat_id: str) -> dict[str, int]:
        return {t["id"]: t["feedback"] for t in self.turns(account_id, chat_id) if t["feedback"]}
