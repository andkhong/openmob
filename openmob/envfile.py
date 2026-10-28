"""Load a private settings file (`.env`, or `provider-keys.env` for `scripts/om`) into the environment.

The file is read as data, never run as shell: each line is `NAME=value` or `export NAME=value`, quoted the way a
shell would (parsed with shlex). A `#` starts a comment only at the start of a line or after whitespace, outside
quotes, as in most dotenv parsers: `KEY=abc#def` keeps `abc#def`, `KEY=abc #def` keeps `abc`. Only the names in
ALLOWED are accepted; one unknown name, bad quoting or a malformed line refuses the whole file (an unknown name is
shown only when it looks like a plain setting name, since a pasted secret can land where a name goes). The file
must be a regular file owned by the current user that other users can't read (it holds API keys); the checks run
on the same open descriptor the file is read from. A variable already set in the environment is never overridden,
and values are never printed.

Standard library only: `scripts/om` loads this file by path, so it also works for checkouts that predate it.
"""
from __future__ import annotations

import os
import re
import shlex
import stat
from pathlib import Path

# Model providers (at least one is needed to run tasks), the optional Jev classifier, and the server settings a
# self-hoster sets. .env.example documents each one.
MODEL_KEYS = frozenset({
    "ANTHROPIC_API_KEY", "ANTHROPIC_WORKSPACE_ID",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY", "GOOGLE_API_KEY",
    "QWEN_API_KEY", "DASHSCOPE_API_KEY", "QWEN_BASE_URL",
    "XAI_API_KEY", "XAI_BASE_URL",
    "OPENAI_COMPATIBLE_API_KEY", "OPENAI_COMPATIBLE_BASE_URL",
})
ALLOWED = MODEL_KEYS | frozenset({
    "TYPESAFE_API_KEY",
    "OPENMOB_PUBLIC_URL", "OPENMOB_DATA_DIR", "OPENMOB_APK", "OPENMOB_MEMORY", "OPENMOB_JEV",
    "OPENMOB_INVITE_EMAIL", "OPENMOB_MIN_APP_VERSION", "OPENMOB_MODEL_TIMEOUT_S",
    "OPENMOB_RELEASE_SIGNERS", "OPENMOB_REQUIRE_RELEASE_APK",
})
# A base URL from the file never goes with a key from the terminal (security review 6, 2026-10-27): a .env in a
# downloaded folder could otherwise send the key already exported in this shell, and every screenshot, elsewhere.
BASE_URL_KEYS = {
    "XAI_BASE_URL": ("XAI_API_KEY",),
    "QWEN_BASE_URL": ("QWEN_API_KEY", "DASHSCOPE_API_KEY"),
    "OPENAI_COMPATIBLE_BASE_URL": ("OPENAI_COMPATIBLE_API_KEY",),
}
# An unknown name is echoed only if it looks like a setting name: anything else might be a secret pasted in its place.
_SHOWABLE_NAME = re.compile(r"[A-Z][A-Z0-9_]{0,39}")


class EnvFileError(Exception):
    """The file was refused; nothing from it was loaded. The message never contains a value."""


def _strip_comment(line: str) -> str:
    """`line` up to its comment: a `#` outside quotes at the start or after whitespace. Quoting follows shlex's
    posix rules (backslash escapes outside single quotes); bad quoting is left for shlex to report."""
    quote = None
    i = 0
    while i < len(line):
        c = line[i]
        if quote == "'":
            if c == "'":
                quote = None
        elif c == "\\":
            i += 1  # the next character is escaped (inside double quotes too, near enough for a comment scan)
        elif quote == '"':
            if c == '"':
                quote = None
        elif c in "'\"":
            quote = c
        elif c == "#" and (i == 0 or line[i - 1].isspace()):
            return line[:i]
        i += 1
    return line


def parse(text: str, allowed: frozenset[str] = ALLOWED, label: str = ".env") -> dict[str, str]:
    """The file's non-empty assignments, {name: value}. Raises EnvFileError (naming the line, never a value)."""
    out: dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), 1):
        try:
            parts = shlex.split(_strip_comment(line))
        except ValueError:
            raise EnvFileError(f"{label} line {number}: invalid quoting; nothing was loaded.") from None
        if parts and parts[0] == "export":
            parts = parts[1:]
        if not parts:
            continue
        if len(parts) != 1 or "=" not in parts[0]:
            raise EnvFileError(f"{label} line {number}: expected NAME=value or export NAME=value; nothing was loaded.")
        name, value = parts[0].split("=", 1)
        if name not in allowed:
            shown = f" ({name})" if _SHOWABLE_NAME.fullmatch(name) else ""
            raise EnvFileError(f"{label} line {number}: unsupported variable name{shown}; nothing was loaded. "
                               "The supported names are listed in .env.example.")
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise EnvFileError(f"{label} line {number}: {name} has a control character in it; nothing was loaded.")
        if value:
            out[name] = value
    return out


def load(path, allowed: frozenset[str] = ALLOWED, environ=None) -> list[str]:
    """Load `path` into `environ` (os.environ by default) without overriding what's already set. Returns the
    names it set (no values). Raises EnvFileError if the file is unsafe, unreadable or malformed;
    FileNotFoundError if it's missing."""
    path = Path(path)
    environ = os.environ if environ is None else environ
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))  # a FIFO must not hang the open
    except FileNotFoundError:
        raise
    except PermissionError:
        raise EnvFileError(f"{path}: permission denied; nothing was loaded.") from None
    except OSError as e:
        raise EnvFileError(f"{path}: can't be opened ({e.strerror}); nothing was loaded.") from None
    with os.fdopen(fd, "rb") as f:
        st = os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode):
            raise EnvFileError(f"{path} is not a regular file; nothing was loaded.")
        if os.name == "posix":
            if st.st_uid != os.geteuid():
                raise EnvFileError(f"{path} belongs to another user, and it would set API keys and settings for "
                                   "this one; nothing was loaded. Use a file you own.")
            if st.st_mode & 0o077:
                raise EnvFileError(f"{path} can be read by other users, and it holds API keys; nothing was loaded. "
                                   f"Run: chmod 600 {path}")
        try:
            data = f.read()
        except OSError as e:
            raise EnvFileError(f"{path}: can't be read ({e.strerror}); nothing was loaded.") from None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise EnvFileError(f"{path}: not UTF-8 text (at byte {e.start}); nothing was loaded.") from None
    values = parse(text, allowed, label=path.name)
    for url, keys in BASE_URL_KEYS.items():
        if url in values and url not in environ and any(k in environ and k not in values for k in keys):
            raise EnvFileError(f"{path} sets {url}, but this terminal already has the key it would be sent with; "
                               f"nothing was loaded. Put the key and {url} in the same place.")
    loaded = [name for name in values if name not in environ]
    for name in loaded:
        environ[name] = values[name]
    return loaded
