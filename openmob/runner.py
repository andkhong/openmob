"""Routes commands from every input (Mac mic, phone page, terminal) to one agent worker."""

from __future__ import annotations

import inspect
import itertools
import queue
import re
import uuid
import threading
import time
from collections import OrderedDict, deque

from .agent import Agent
from .agent import sensitive
from .agent.loop import DECLINE_WORDS, is_yes
from .phone.base import DeviceError, PhoneTimeout
from .usage import Usage
from .voice.tts import Speaker

_CURRENT = object()  # event(): tag with whichever task is running

# The OpenMob companion app itself: no task may operate it (it's where approvals and the kill switch
# live), so a prompt-injected agent can't approve its own purchase from inside the app.
OWN_PACKAGES = {"dev.openmob.companion"}
APPROVE_ON_PROMPT = "Approve this on the approval prompt, with your screen lock. A typed or spoken \"yes\" can't approve it."
# The phone's app is older than the server's min_app_version (docs/phone-protocol.md §3.7): its tasks are refused.
UPDATE_REQUIRED = ("This phone's OpenMob app is older than this server allows, so no task can run on it. "
                   "Update the app on the phone: Download update on its Home screen.")

STOP_PHRASES = {"stop", "cancel", "abort", "stop it", "never mind", "nevermind", "stop stop"}

ICONS = {"correction": "✏️ ", "usage": "🧮", "jev": "🔎", "status": "·", "thought": "💭", "action": "👉", "error": "⚠️ ", "question": "❓", "result": "✅", "heard": "🎙"}


FINAL_STATUSES = {"succeeded", "failed", "cancelled"}
ANSWER_POLL_S = 0.05  # how often a waiting question looks for a Stop
KEEP_TASKS = 200  # per phone: finished tasks stay readable here until they age out (then from History)
KEEP_TASK_EVENTS = 500


def format_event(kind: str, message: str) -> str:
    return f"{ICONS.get(kind, '-')} {message}"


def is_stop(text: str) -> bool:
    return " ".join(re.sub(r"[^a-z ]", " ", text.lower()).split()) in STOP_PHRASES


class ConsoleIO:
    """UserIO for one-off `openmob do` runs: questions are answered in the terminal."""

    def __init__(self, speaker: Speaker):
        self.speaker = speaker

    def ask(self, question: str) -> str:
        self.speaker.say(question)
        try:
            return input(format_event("question", question) + "\n> ")
        except EOFError:  # no terminal to answer from
            print()
            return ""

    def event(self, kind: str, message: str) -> None:
        print(format_event(kind, sensitive.redact(message)), flush=True)


class Coordinator:
    """Queues tasks, runs them one at a time, and routes answers to the agent's questions."""

    def __init__(self, speaker: Speaker, history=None):
        self.agent: Agent | None = None
        self.history = history  # History store, or None (tests, no persistence)
        self.account_id: str | None = None  # owner of this phone (hosted mode)
        self.device_id = ""
        self.device_model = ""
        self.chat_id: str | None = None  # created on the first request after "New chat"
        self.speaker = speaker
        self.tasks: queue.Queue[tuple[str, str, str, dict]] = queue.Queue()
        self.answers: queue.Queue[tuple[int, str]] = queue.Queue()  # (question id, answer)
        self._question_id = 0  # counts questions asked: an answer names the one it was given for
        self.corrections: queue.Queue[str] = queue.Queue()  # steer: what the user said mid-task
        self.cancel = threading.Event()
        self.log: deque[dict] = deque(maxlen=500)
        self.current_task: str | None = None  # id of the running task; every event is tagged with one
        # The running task's agent.run has returned and the worker is reporting its result: new text is a new task,
        # not a correction (2026-10-21: a command sent in that window was taken as a correction and dropped).
        self._wrapping_up = False
        self._seq = itertools.count(1)
        self.current: str | None = None
        self.question: str | None = None
        self.question_kind: str | None = None  # "question" (ask_user), "confirm" (risky action) or "plan"
        self.requester_for = None  # (task id) -> the API key or client name that asked, or None (DeviceManager)
        self.question_details: dict | None = None  # what a confirm is about ({"approver": "phone"} on gatekeeper phones)
        # (mode or None) -> TaskPermissions for a task on this phone (set by the DeviceManager);
        # None: the agent's default (config's mode, ceiling auto).
        self.permissions_for = None
        # () -> bool: may this phone's tasks use the owner's saved preferences (its approval trust, set by the
        # DeviceManager). Without one (a Coordinator outside a DeviceManager): no.
        self.memory_trusted = lambda: False
        self.current_mode: str | None = None  # the permission mode the running task asked for
        self.question_timeout = 300.0  # seconds a question may wait for an answer (0: forever)
        # Whether a risky action may be approved by typing or saying "yes" (submit). False for app
        # phones, which approve only through the screen-lock prompt (DeviceManager.resolve_approval).
        self.text_approvals = True
        # The digest of the action the owner's phone approved (phone/approval_keys.py), handed to the
        # agent with the yes (take_approval_digest): it runs the action only if it still matches.
        self._approval_digest: str | None = None
        self._unanswered: str | None = None  # the task stopped because nobody answered its question
        self._stop_reason: str | None = None  # why stop() cancelled the running task, if it said
        self._stop_summary: str | None = None  # the stopped task's summary in its place ("Stopped: Gmail is blocked…")
        self.listeners: list = []
        self.entry_listeners: list = []  # callables(entry): every log entry, with its task id
        # Per-task records (status, steps, outcome, events) for the developer API, newest last.
        self.task_info: OrderedDict[str, dict] = OrderedDict()
        self._skip: set[str] = set()  # queued tasks cancelled before they started
        # The phone's app is older than the server's min_app_version (§3.7): it stays connected (Stop, answers and
        # Disconnect work), but no task starts on it. The server sets it at each hello.
        self.update_required = False
        self.session_usage = Usage()  # all tasks on this phone since the server started  # callables(kind, message), e.g. forward to the phone app
        self._lock = threading.Lock()

    # --- inputs ----------------------------------------------------------

    def submit(self, text: str, source: str, mode: str = "auto", permission_mode: str | None = None) -> str:
        """Handle one utterance. Returns what happened: queued, steered, answered, stopped, or ignored.

        mode "auto": while a task runs (and isn't asking anything), anything but "stop" corrects
        that task. mode "queue": it's a new task, queued behind the running one. `permission_mode`:
        the new task's mode (checked against the phone's ceiling by the caller); None: the phone's default."""
        text = text.strip()
        if not text:
            return "ignored"
        with self._lock:
            running = self.current_task
            question_id = self._question_id  # an answer is for this question only (review 4)
            if self.question is not None:
                kind = "stop" if is_stop(text) else "answer"
                if kind == "answer" and self.question_kind == "confirm" and not self.text_approvals:
                    # Never approved by text: anyone (or the agent itself, typing into the app) could
                    # send "yes". A "no" still declines; approving takes the screen-lock prompt.
                    kind = "approval_required" if is_yes(text) else "decline"
                elif kind == "answer" and self.question_kind == "plan" and not self.text_approvals:
                    # A plan: yes takes the prompt, no rejects it, anything else is the owner's changes.
                    low = text.lower().split()
                    kind = ("approval_required" if is_yes(text)
                            else "decline" if not low or low[0] in DECLINE_WORDS else "answer")
            elif is_stop(text):
                kind = "stop" if (self.current is not None or not self.tasks.empty()) else "ignore"
            elif running is not None and mode == "auto" and not self._wrapping_up:
                kind = "steer"
            else:
                kind = "task"
        options = {"permission_mode": permission_mode} if permission_mode else None
        if kind in ("task", "steer") and self.update_required:
            self.event("status", UPDATE_REQUIRED, task=None)
            return "update_required"
        if kind == "task":
            self.enqueue(text, source, options)
            return "queued"
        if kind == "steer":
            if self.steer(text, source):
                return "steered"
            self.enqueue(text, source, options)  # the task finished in the meantime: it's a new request
            return "queued"
        if kind == "approval_required":  # not an answer: the pending approval prompt stays open
            self.event("status", APPROVE_ON_PROMPT, task=running)
            return "approval_required"
        # Answers and stops belong to the running task's turn.
        self.event("heard", f"[{source}] {text}", task=running)
        if kind == "answer":
            self.answers.put((question_id, text))
            return "answered"
        if kind == "decline":
            self.answers.put((question_id, "no"))
            return "answered"
        if kind == "stop":
            self.stop()
            return "stopped"
        return "ignored"

    @staticmethod
    def new_task_id() -> str:
        # Random, so turns stay unique in the history across server restarts.
        return uuid.uuid4().hex[:12]

    def enqueue(self, text: str, source: str, options: dict | None = None, task_id: str | None = None) -> str:
        """Queue a task as-is (never read as an answer or "stop") and return its id.

        `options` go to Agent.run for this task only: model, max_steps, blocked. Pass `task_id`
        (from new_task_id) to know the id before the task can start."""
        task_id = task_id or self.new_task_id()
        with self._lock:
            running = self.current_task
            self.task_info[task_id] = {
                "id": task_id, "status": "queued", "request": text, "source": source,
                "created": time.time(), "started": None, "finished": None, "steps": 0,
                "success": None, "summary": None, "reason": None, "question": None, "usage": None, "events": [],
            }
            while len(self.task_info) > KEEP_TASKS:
                self.task_info.popitem(last=False)
        if self.chat_id is None and self.history is not None:
            self.chat_id = self.history.create_chat(self.account_id, self.device_id, self.device_model, text)
        self.event("heard", f"[{source}] {text}", task=task_id)
        self.tasks.put((text, source, task_id, options or {}))
        if running is not None:
            self.event("status", "Queued until the current task finishes.", task=task_id)
        return task_id

    def task(self, task_id: str) -> dict | None:
        """A copy of one task's record (None once it has aged out)."""
        with self._lock:
            info = self.task_info.get(task_id)
            return {**info, "events": list(info["events"])} if info else None

    def cancel_task(self, task_id: str) -> bool:
        """Cancel one task, queued or running. False if it's unknown or already finished."""
        with self._lock:
            info = self.task_info.get(task_id)
            if not info or info["status"] in FINAL_STATUSES:
                return False
            running = self.current_task == task_id
            if not running:
                self._skip.add(task_id)
        if running:
            self.cancel.set()
            self.event("status", "Stopping…", task=task_id)
        else:
            self.event("error", "Cancelled before it started.", task=task_id,
                       data={"final": True, "success": False, "cancelled": True})
        return True

    def steer(self, text: str, source: str = "api") -> bool:
        """Correct the running task ("no, the other button"). The agent reads it before its next
        step. False when nothing is running, or a question is pending (that wants an answer)."""
        text = text.strip()
        with self._lock:
            if not text or self.current_task is None or self.question is not None or self._wrapping_up:
                return False
            self.corrections.put(text)
        self.event("correction", f"[{source}] {text}")
        return True

    def take_corrections(self) -> list[str]:
        """The agent's side of steer: everything said since its last step, oldest first."""
        out = []
        while True:
            try:
                out.append(self.corrections.get_nowait())
            except queue.Empty:
                return out

    def record_step(self, step: dict) -> None:
        """The agent's structured record of one tool call (redacted, no screenshot) → history."""
        if self.history is None or self.chat_id is None or self.current_task is None:
            return
        try:
            self.history.record_step(self.chat_id, self.current_task, step,
                                     account_id=self.account_id, device_id=self.device_id)
        except Exception as exc:  # history must never break the agent
            print(format_event("error", f"Step not saved: {exc}"), flush=True)

    def answer(self, task_id: str, text: str, digest: str | None = None) -> bool:
        """Answer the running task's pending question. False if that task isn't asking. `digest`: a yes
        signed on the owner's phone names the action it approved."""
        with self._lock:
            if self.current_task != task_id or self.question is None:
                return False
            self._approval_digest = digest
            question_id = self._question_id
        self.event("heard", f"[api] {text}", task=task_id)
        self.answers.put((question_id, text))
        return True

    def stop(self, reason: str | None = None, summary: str | None = None) -> None:
        """Cancel the running task and everything queued. `reason` is recorded on each (e.g.
        device_revoked when the phone is unpaired); `summary` replaces the running task's own (blocked_app)."""
        final = {"final": True, "success": False, "cancelled": True, **({"reason": reason} if reason else {})}
        drained = []
        while not self.tasks.empty():
            try:
                drained.append(self.tasks.get_nowait()[2])
            except queue.Empty:
                break
        with self._lock:
            pending = [task_id for task_id in drained if task_id not in self._skip]  # in _skip: cancelled on its own
            self._skip.difference_update(drained)  # these never reach the worker now
            # The task the worker has dequeued but not yet started (review 3 F3-L4): its record still says queued, so
            # it's skipped too (_work checks under the same lock before it starts).
            for task_id, info in self.task_info.items():
                if (info["status"] == "queued" and task_id != self.current_task and task_id not in self._skip
                        and task_id not in drained):
                    self._skip.add(task_id)
                    pending.append(task_id)
            running = self.current is not None
            if running:
                if not self._stop_reason:  # a later stop keeps the first one's reason and summary
                    self._stop_reason, self._stop_summary = reason, summary if reason else None
                self.cancel.set()
        for task_id in pending:
            self.event("error", "Cancelled before it started.", task=task_id, data=final)
        if running:
            self.event("status", "Stopping…")

    # --- UserIO ----------------------------------------------------------

    def ask(self, question: str, kind: str = "question", details: dict | None = None) -> str:
        with self._lock:
            # A new question: answers left from an earlier one (a second quick "yes") never answer it (review 4).
            self._question_id += 1
            question_id = self._question_id
            while True:
                try:
                    self.answers.get_nowait()
                except queue.Empty:
                    break
            self.question = question
            self.question_kind = kind
            self.question_details = details
            self._approval_digest = None
        data = None
        if kind in ("confirm", "plan"):  # both wait for the owner's approval prompt
            data = {"confirm": True, **({"approval": details} if details else {})}
        self.event("question", question, data=data)
        self.speaker.say(question)
        deadline = time.monotonic() + self.question_timeout if self.question_timeout else None
        try:
            while not self.cancel.is_set():
                try:
                    answered, text = self.answers.get(timeout=ANSWER_POLL_S)  # short: a Stop ends the wait within this
                    if answered == question_id:
                        return text
                except queue.Empty:
                    if deadline is not None and time.monotonic() >= deadline:
                        # Nobody answered: end the task rather than hold the phone (and a task slot) forever.
                        self._unanswered = self.current_task
                        self.cancel.set()
            return "no"
        finally:
            with self._lock:
                self.question = None
                self.question_kind = None
                self.question_details = None
            self._set_status(self.current_task, "running")

    def confirm(self, question: str, details: dict | None = None) -> str:
        """The agent wants approval for a risky action (buy, send, delete…), a step (ask mode) or a
        plan. `details` ({kind, action_kind, package, always, plan}) go with the phone's prompt."""
        return self.ask(question, kind="plan" if (details or {}).get("kind") == "plan" else "confirm", details=details)

    def task_source(self) -> str:
        """Who asked for the running task, for the phone's task prompt: the API key or client's name, else where it
        was typed (the dashboard, this phone)."""
        task_id = self.current_task
        name = None
        if task_id and self.requester_for is not None:
            try:
                name = self.requester_for(task_id)
            except Exception:
                name = None
        source = (self.task_info.get(task_id) or {}).get("source") if task_id else None
        return name or {"dashboard": "You, on the dashboard", "phone": "You, on this phone"}.get(source or "", "An agent")

    def take_approval_digest(self) -> str | None:
        """The digest of the action the last answer approved on a phone (once), or None."""
        with self._lock:
            digest, self._approval_digest = self._approval_digest, None
        return digest

    def record_prompt(self, prompt: dict) -> None:
        """One approval prompt's decision and latency (Agent._ask_owner) → history, for `openmob prompts`."""
        if self.history is None or self.current_task is None:
            return
        try:
            self.history.record_prompt(self.current_task, prompt, account_id=self.account_id, device_id=self.device_id)
        except Exception as exc:  # telemetry must never break the agent
            print(format_event("error", f"Prompt not saved: {exc}"), flush=True)

    def event(self, kind: str, message: str, task=_CURRENT, data: dict | None = None) -> None:
        """Log one entry. `task` defaults to the running task; `data` carries structured details
        for the dashboard (e.g. {"final": True, "steps": 4} on a task's outcome, token counts)."""
        task_id = self.current_task if task is _CURRENT else task
        # Every outward copy (the feed, /v1/tasks/{id}/events, webhooks' task, the history, the console) starts here:
        # a card number or SSN in any message (a summary, a thought, the request in "Working on: …") is redacted.
        message = sensitive.redact(message)
        entry = {"seq": next(self._seq), "time": time.time(), "kind": kind, "message": message, "task": task_id}
        if data:
            entry["data"] = data
        self.log.append(entry)
        self._track(entry)
        if self.history is not None and self.chat_id is not None:
            try:
                self.history.record(self.chat_id, entry)
            except Exception as exc:  # history must never break the agent
                print(format_event("error", f"History not saved: {exc}"), flush=True)
        print(format_event(kind, message), flush=True)
        for listener in self.listeners:
            try:
                listener(kind, message)
            except Exception:  # a broken listener must never stop the agent
                pass
        for listener in self.entry_listeners:
            try:
                listener(entry)
            except Exception:
                pass

    def _track(self, entry: dict) -> None:
        """Keep the task's record (for the developer API) in step with its log."""
        data = entry.get("data") or {}
        with self._lock:
            info = self.task_info.get(entry["task"]) if entry["task"] else None
            if info is None or entry["kind"] == "memory":  # memory lines are the owner's: not in the API's events
                return
            info["events"].append(entry)
            del info["events"][:-KEEP_TASK_EVENTS]
            kind = entry["kind"]
            if data.get("final"):
                info["status"] = "cancelled" if data.get("cancelled") else ("succeeded" if data.get("success") else "failed")
                info["success"] = bool(data.get("success"))
                info["summary"] = entry["message"].rsplit(" (", 1)[0] if entry["message"].endswith(" steps)") else entry["message"]
                info["steps"] = data.get("steps", info["steps"])
                info["finished"] = entry["time"]
                info["question"] = None
                info["reason"] = data.get("reason")  # question_timeout, phone_unresponsive, internal_error…
            elif kind == "usage":
                info["usage"] = data
            elif info["status"] in FINAL_STATUSES:
                return
            elif kind == "question":
                info["status"] = "needs_confirmation" if data.get("confirm") else "needs_input"
                info["question"] = entry["message"]
            elif kind in ("action", "error"):
                info["steps"] += 1

    def _set_status(self, task_id: str | None, status: str) -> None:
        with self._lock:
            info = self.task_info.get(task_id) if task_id else None
            if info and info["status"] not in FINAL_STATUSES:
                info["status"] = status
                info["question"] = None
                if status == "running" and info["started"] is None:
                    info["started"] = time.time()

    # --- worker ----------------------------------------------------------

    def start(self) -> None:
        threading.Thread(target=self._work, name="openmob-agent", daemon=True).start()

    def _work(self) -> None:
        while True:
            text, source, task_id, options = self.tasks.get()
            self.take_corrections()  # anything left from an earlier task isn't about this one
            # One lock from the last cancel check to the task being current (review 3 F3-L4): a Stop or cancel_task
            # before it skips the task (it's still queued: stop() and cancel_task see that), one after it stops the
            # running task (the cancel is cleared before the task is current, never after).
            with self._lock:
                info = self.task_info.get(task_id)
                if task_id in self._skip or (info is not None and info["status"] in FINAL_STATUSES):
                    self._skip.discard(task_id)  # cancelled while it waited
                    continue
                refused = self.update_required  # queued before the phone came back with a too-old app
                if not refused:
                    self.cancel.clear()
                    self.current = text
                    self.current_task = task_id
            if refused:
                self.event("error", UPDATE_REQUIRED, task=task_id,
                           data={"final": True, "success": False, "reason": "app_update_required"})
                continue
            self._set_status(task_id, "running")
            self.event("status", f"Working on: {text}")
            self.speaker.say("On it.")
            try:
                # The phone page is in the phone's browser, so get it out of the way first.
                # go_home: the phone page is in the phone's browser, so get it out of the way first;
                # orchestrated steps ask for it too, so each starts from a clean screen.
                go_home = options.pop("go_home", source == "phone") or self._own_app_in_front()
                self._block_own_app(options)
                self._permissions(options)
                self._memory(options, source)
                driven = options.get("drive") is not None  # an outside agent decided: not a model run
                try:
                    result = self.agent.run(text, self.cancel, go_home=go_home, **options)
                finally:
                    with self._lock:  # from here on, new text is a new task (submit, steer)
                        self._wrapping_up = True
                data = {"final": True, "success": result.success, "steps": result.steps}
                if isinstance(getattr(result, "mode", None), str):  # the agent ran under a permission mode
                    data["mode"] = result.mode
                    data["prompts"] = result.prompts  # approval prompts the owner saw (telemetry)
                    with self._lock:
                        if task_id in self.task_info:
                            self.task_info[task_id]["prompts_count"] = result.prompts
                if getattr(result, "done_via", None):
                    data["done_via"] = result.done_via  # internal: vision | classifier | landing (the API doesn't show it)
                if isinstance(getattr(result, "unverified", None), int) and result.unverified > 0:
                    # The answer check (agent/answer_check.py): how many names in the answer no screen showed
                    # (internal, like done_via; the API's outcome doesn't show it). Only the count, never the
                    # strings: one could be a saved preference's text, which never goes in events or history.
                    data["unverified"] = int(result.unverified)
                if isinstance(getattr(result, "faster", None), dict):
                    data["faster"] = result.faster  # Faster mode: images sent, model calls skipped, time saved
                summary = result.summary
                if getattr(result, "reason", None) and not result.success:
                    data["reason"] = result.reason  # e.g. phone_locked: the phone stayed locked past the wait
                if self._unanswered == task_id and not result.success:
                    data["reason"] = "question_timeout"
                    minutes = self.question_timeout / 60
                    summary = (f"Stopped: nobody answered the question within "
                               f"{f'{minutes:g} minutes' if minutes >= 1 else f'{self.question_timeout:g} s'}.")
                elif self.cancel.is_set() and not result.success:
                    data["cancelled"] = True
                    if self._stop_reason:
                        data["reason"] = self._stop_reason
                    if self._stop_summary:
                        summary = self._stop_summary
                self.event("result" if result.success else "error", f"{summary} ({result.steps} steps)", data=data)
                self.speaker.say(result.summary)
                if not data.get("cancelled") and not driven:  # a stop is the user's call, not the model's result
                    self._record_model_run(task_id, result.success, result.steps)
            except Exception as exc:  # keep the worker alive for the next command
                if self.cancel.is_set() and self._unanswered != task_id:
                    # Stopped (or the phone unpaired) and the stop surfaced as an error, e.g. the closed socket: the
                    # task was cancelled, with the stop's reason, not a phone failure (and not the model's result).
                    data = {"final": True, "success": False, "cancelled": True,
                            **({"reason": self._stop_reason} if self._stop_reason else {})}
                    self.event("error", self._stop_summary or "Stopped.", data=data)
                    continue
                # Why, for callers and billing: the phone stopped answering, it failed, or we did.
                reason = ("phone_unresponsive" if isinstance(exc, PhoneTimeout)
                          else "phone_error" if isinstance(exc, DeviceError) else "internal_error")
                self.event("error", f"{type(exc).__name__}: {exc}", data={"final": True, "success": False, "reason": reason})
                self.speaker.say("Sorry, something went wrong.")
                self._record_model_run(task_id, False, None)
            finally:
                if self.take_corrections():
                    self.event("status", "A correction came in as the task ended; send it again as a new request.", task=task_id)
                # Count tokens even when a task fails or is stopped part-way.
                usage = getattr(self.agent, "usage", None)
                if usage is not None:
                    self.session_usage.add(usage)
                    self.event("usage", f"Tokens this task: {usage.summary()}", data=usage.as_dict())
                with self._lock:
                    self.current = None
                    self.current_task = None
                    self._wrapping_up = False
                    self.current_mode = None
                    self._unanswered = None
                    self._stop_reason = None
                    self._stop_summary = None

    def _own_app_in_front(self) -> bool:
        """The OpenMob app is on screen (often: the user just spoke to it): start from Home instead."""
        try:
            return self.agent.driver.current_app() in OWN_PACKAGES
        except Exception:
            return False

    def _block_own_app(self, options: dict) -> None:
        """Every task, from any source: the agent may not open or operate the OpenMob app (the task
        stops if it ends up there), on top of whatever the task already blocks (sensitive apps)."""
        try:
            accepts = "blocked" in inspect.signature(self.agent.run).parameters
        except (TypeError, ValueError):
            accepts = False
        if not accepts:
            return
        other = options.get("blocked")
        options["blocked"] = lambda package, other=other: package in OWN_PACKAGES or bool(other and other(package))

    def _memory(self, options: dict, source: str) -> None:
        """Preferences memory only for the owner's own tasks (spec §4.6): memory on, started from the dashboard or
        the phone, on a phone the owner trusts. Never from a caller's options (API, MCP, drive, orchestrations)."""
        options.pop("memory_allowed", None)
        config = getattr(self.agent, "config", None)
        if not (getattr(config, "memory", False) and source in ("dashboard", "phone")):
            return
        try:
            trusted = self.memory_trusted() is True
        except Exception:
            trusted = False  # fail closed
        if trusted:  # set only when allowed: an agent without the parameter never sees it
            options["memory_allowed"] = True

    def _permissions(self, options: dict) -> None:
        """The task's permission mode → a TaskPermissions bound to this phone's live settings. The
        caller already checked the mode against the phone's ceiling (and an API key's max_mode)."""
        mode = options.pop("permission_mode", None)
        try:
            accepts = "permissions" in inspect.signature(self.agent.run).parameters
        except (TypeError, ValueError):
            accepts = False
        if not accepts:
            options.pop("permissions", None)
            return
        if "permissions" not in options and self.permissions_for is not None:
            options["permissions"] = self.permissions_for(mode)
        perms = options.get("permissions")
        with self._lock:
            self.current_mode = perms.mode() if perms is not None else None

    def _record_model_run(self, task_id: str, success: bool, steps: int | None) -> None:
        """Per-model success stats (History.model_stats): which model ran this task, and how it went."""
        model = getattr(self.agent, "task_model", None)
        if self.history is None or not model:
            return
        try:
            self.history.record_model_run(self.account_id, task_id, model, success, steps)
        except Exception as exc:
            print(format_event("error", f"Model stats not saved: {exc}"), flush=True)

    def clear_log(self) -> None:
        """New chat: empty the conversation and the agent's memory of earlier requests.
        The next request starts a new saved chat; earlier chats stay in the history."""
        with self._lock:
            if self.current is not None:
                raise RuntimeError("Stop the current task before starting a new chat.")
            self.log.clear()
            self.chat_id = None
        recent = getattr(self.agent, "recent", None)
        if recent is not None:
            recent.clear()

    def open_chat(self, chat_id: str) -> bool:
        """Show a saved chat and continue it: its log comes back, and the agent remembers its requests."""
        if self.history is None:
            return False
        events = self.history.events(self.account_id, chat_id)
        if events is None:
            return False
        with self._lock:
            if self.current is not None:
                raise RuntimeError("Stop the current task before opening another chat.")
            self.log.clear()
            for entry in events:
                self.log.append({"seq": next(self._seq), **entry})
            self.chat_id = chat_id
        recent = getattr(self.agent, "recent", None)
        if recent is not None:
            recent.clear()
            recent.extend(self.history.recent_requests(self.account_id, chat_id))
        return True

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "state": "asking" if self.question else ("running" if self.current else "idle"),
                "question_kind": self.question_kind,
                "current": self.current,
                "question": self.question,
                "queued": self.tasks.qsize(),
                "model": getattr(self.agent, "model", None),
                "task_model": getattr(self.agent, "task_model", None) if self.current else None,
                "usage": {
                    "task": self.agent.usage.as_dict() if self.current and hasattr(self.agent, "usage") else None,
                    "session": self.session_usage.as_dict(),
                },
                "task_id": self.current_task,
                # Stop was pressed and the task is winding down (the dashboard says "Stopping…" until it ends).
                # Not once the task reads finished: that comes a moment before it stops being current.
                "stopping": bool(self.current is not None and self.cancel.is_set()
                                 and not (self.task_info.get(self.current_task) or {}).get("finished")),
                "permission_mode": self.current_mode,
                "chat_id": self.chat_id,
                "log": list(self.log)[-400:],
            }
