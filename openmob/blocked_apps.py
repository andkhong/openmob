"""The owner's blocked apps, as the server knows them (owner, 2026-10-20; docs/design/blocked-apps.md).

The phone is the authority: it keeps the list, enforces it in its gatekeeper and is the only place an app can be
unblocked (with the screen lock). The server holds two things per phone, for the dashboard:

- `reported`: the phone's own list from its last `blocked_apps` report (a copy, shown as such);
- `pending`: packages the owner asked to block from the dashboard that the phone hasn't reported yet. Each is sent
  as a `block_apps` request when the phone is online, and again on every connection until a report includes it.

Nothing here can remove an entry from the phone: there is no unblock request, and the phone ignores anything but
additions. A malformed or oversized list is refused whole.
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

MAX_APPS = 200  # the phone's cap too (BlockedList.MAX)
PACKAGE = re.compile(r"[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+")
LABEL_MAX = 60


class InvalidPackages(ValueError):
    """Not a list of 1–200 Android package names."""


def valid_package(value: object) -> bool:
    return isinstance(value, str) and len(value) <= 255 and PACKAGE.fullmatch(value) is not None


def packages(raw: object, allow_empty: bool = False) -> list[str]:
    """`raw` as a list of distinct package names, in order. InvalidPackages unless every entry is a well-formed
    package name and there are at most MAX_APPS (and at least one, unless `allow_empty`)."""
    if not isinstance(raw, list) or len(raw) > MAX_APPS or (not raw and not allow_empty):
        raise InvalidPackages(f"packages must be a list of 1 to {MAX_APPS} Android package names.")
    bad = [p for p in raw if not valid_package(p)]
    if bad:
        raise InvalidPackages("Not an Android package name (like com.example.app): "
                              f"{str(bad[0])[:80]!r}.")
    return list(dict.fromkeys(raw))


def label(raw: object) -> str:
    """A phone-reported app label for display: printable, one line, at most LABEL_MAX characters ("" if none)."""
    if not isinstance(raw, str):
        return ""
    text = "".join(ch if ch.isprintable() else " " if ch.isspace() else "" for ch in raw)
    return " ".join(text.split())[:LABEL_MAX]


def report(message: dict) -> tuple[list[str], dict[str, str]]:
    """A phone's `blocked_apps` report: (packages, {package: label}). A current app sends `apps` ([{package, label}]);
    an older one only `packages` (strings), which still parses. Labels are display text, cleaned like the stop label;
    nothing matches on them. InvalidPackages for a malformed report (it is dropped whole)."""
    apps = message.get("apps")
    if isinstance(apps, list):
        if len(apps) > MAX_APPS or not all(isinstance(a, dict) for a in apps):
            raise InvalidPackages("apps must be a list of {package, label} objects.")
        names = packages([a.get("package") for a in apps], allow_empty=True)
        labels = {}
        for a in apps:
            if (text := label(a.get("label"))) and a["package"] not in labels:
                labels[a["package"]] = text
        return names, labels
    return packages(message.get("packages"), allow_empty=True), {}


class BlockedAppsStore:
    """Per phone (by account and session id): {reported, reported_at, pending}. In memory, or a JSON file."""

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else None
        self._lock = threading.Lock()
        self._data: dict[str, dict] = {}
        if self.path and self.path.is_file():
            try:
                self._data = json.loads(self.path.read_text())
            except (OSError, ValueError):
                self._data = {}

    @staticmethod
    def _key(account_id: str | None, session_id: str) -> str:
        return f"{account_id or ''}|{session_id}"

    def _save(self) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, indent=1))
            tmp.replace(self.path)

    def view(self, account_id: str | None, session_id: str) -> dict:
        with self._lock:
            row = self._data.get(self._key(account_id, session_id)) or {}
            reported = list(row.get("reported") or [])
            labels = row.get("labels") or {}
            return {"packages": reported, "reported_at": row.get("reported_at"),
                    "pending": list(row.get("pending") or []),
                    # The phone's own names for them (display only; "" when it sent none, e.g. an older app).
                    "apps": [{"package": p, "label": labels.get(p, "")} for p in reported]}

    def request(self, account_id: str | None, session_id: str, add: list[str]) -> list[str]:
        """The owner asked to block `add` from the dashboard: pending until the phone reports it. Returns what is still
        pending. InvalidPackages if the pending list would pass MAX_APPS."""
        with self._lock:
            row = self._data.setdefault(self._key(account_id, session_id), {})
            reported = set(row.get("reported") or [])
            pending = list(dict.fromkeys([*(row.get("pending") or []), *(p for p in add if p not in reported)]))
            if len(pending) + len(reported) > MAX_APPS:
                raise InvalidPackages(f"A phone holds at most {MAX_APPS} blocked apps.")
            row["pending"] = pending
            self._save()
            return list(pending)

    def report(self, account_id: str | None, session_id: str, reported: list[str],
               labels: dict[str, str] | None = None) -> list[str]:
        """The phone's own list (and its labels): stored as its copy; pending requests it now holds are done. Returns
        what is still pending (to send again on the next connection)."""
        with self._lock:
            row = self._data.setdefault(self._key(account_id, session_id), {})
            row["reported"], row["reported_at"] = list(reported), time.time()
            row["labels"] = {p: t for p, t in (labels or {}).items() if p in set(reported)}
            row["pending"] = [p for p in row.get("pending") or [] if p not in set(reported)]
            self._save()
            return list(row["pending"])

    def forget(self, account_id: str | None, session_id: str) -> None:
        """The phone was unpaired: its copy and requests go (a re-pair starts from the phone's own report)."""
        with self._lock:
            if self._data.pop(self._key(account_id, session_id), None) is not None:
                self._save()
