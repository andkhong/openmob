"""The addresses this OpenMob server answers at, so the agent never opens its own dashboard on the phone (security
review 5 H1, 2026-10-21).

With the owner's dashboard cookie in the phone's browser, text on a screen could steer the agent to the developer
console (mint an API key), to "Trust for approvals", or to the memory page. The agent refuses a link, an in-app link
or an address typed into a browser whose host is one of these (in every mode, never asked), and a task that finds a
browser showing one of them is stopped (runner.py, like the app's own package).

Known hosts, all from the server's own configuration, never from a request (review 5 N1: a client's Host or
X-Forwarded-Host would let one account make every account's agent refuse any site): `OPENMOB_PUBLIC_URL` (one or more
URLs or hosts, comma-separated: the hosted service sets it in fly.toml, a self-hoster to their own domain),
`<FLY_APP_NAME>.fly.dev` on Fly, the `openmob run --public` tunnel (added by the server process that opened it), and
this machine: loopback, localhost, its hostname and its LAN address (a phone on the LAN, `adb reverse`, or the
emulator's 10.0.2.2 reach the server there).

Hosts are read as a browser reads them (host_of): backslashes are slashes, user info and port go, the host is
percent-decoded, NFKC-normalised (full-width and ideographic dots are dots), lower-cased, IDNA-encoded and loses a
trailing dot; IPv4 written as one number, in hex or in octal is the address it names.
"""

from __future__ import annotations

import ipaddress
import os
import re
import socket
import threading
import unicodedata
from urllib.parse import unquote

# 10.0.2.2: the Android emulator's address for the computer it runs on.
LOCAL = frozenset({"localhost", "localhost.localdomain", "ip6-localhost", "0.0.0.0", "10.0.2.2"})
MAX_EXTRA = 8

_lock = threading.Lock()
_extra: set[str] = set()
_machine: frozenset[str] | None = None
_DOTS = re.compile("[\u3002\uff0e\uff61]")
_NON_HOST_SCHEME = re.compile(r"^[a-z][a-z0-9+.\-]*:[^0-9]")


def _normal(s: str) -> str:
    return _DOTS.sub(".", unicodedata.normalize("NFKC", s)).lower()


def host_of(value: str) -> str:
    """The host a URL, a bare host or a host:port names, as a browser would navigate to it ("" when there is none):
    "https://openmob.example\\@evil.com/" is openmob.example (a backslash is a slash), "https://%6Fpenmob.example"
    and "openmob\u3002example." are openmob.example."""
    s = _normal(re.sub(r"[\t\n\r]", "", value or "").strip()).replace("\\", "/")
    if not s or " " in s:
        return ""
    if s.startswith(("http:", "https:", "ws:", "wss:")):
        s = s.split(":", 1)[1]  # "https:/host" opens host too
    elif "://" in s:
        s = s.split("://", 1)[1]
    elif _NON_HOST_SCHEME.search(s):
        return ""  # mailto:, tel:, javascript: ... ("localhost:8765" is a host and a port)
    s = re.split(r"[/?#]", s.lstrip("/"), maxsplit=1)[0].rsplit("@", 1)[-1]
    s = _normal(unquote(s, errors="replace"))
    if s.startswith("["):
        host = s[1:].split("]", 1)[0]
    else:
        host = s.split(":", 1)[0].rstrip(".")
        if any(c in host for c in "/\\@?# %"):
            return ""  # a browser won't navigate to it
        try:
            host = host.encode("idna").decode("ascii").lower()
        except UnicodeError:
            pass
        host = _ipv4(host) or host
    return host


def _ipv4(host: str) -> str | None:
    """A browser's reading of an IPv4 address ("2130706433", "0x7f.1", "0177.0.0.1" are 127.0.0.1), or None."""
    parts = host.split(".")
    if not parts or len(parts) > 4 or not all(re.fullmatch(r"0[xX][0-9a-fA-F]*|[0-9]+", p) for p in parts):
        return None
    try:
        nums = [int(p, 16) if p[:2].lower() == "0x" else int(p, 8) if len(p) > 1 and p[0] == "0" else int(p)
                for p in (p if p.lower() != "0x" else "0x0" for p in parts)]
    except ValueError:
        return None
    if any(n > 255 for n in nums[:-1]) or nums[-1] >= 256 ** (5 - len(nums)):
        return None
    value = nums[-1]
    for i, n in enumerate(nums[:-1]):
        value += n << (8 * (3 - i))
    return str(ipaddress.IPv4Address(value))


def add(host_or_url: str) -> None:
    """A host this server process itself publishes at (the `openmob run --public` tunnel). Never a request's header."""
    host = host_of(host_or_url)
    if not host:
        return
    with _lock:
        if host not in _extra and len(_extra) < MAX_EXTRA:
            _extra.add(host)


def _machine_hosts() -> frozenset[str]:
    global _machine
    if _machine is None:
        found: set[str] = set()
        try:  # no name lookup: it can stall for seconds on a Mac
            name = socket.gethostname().lower()
            found.update({name, f"{name.split('.')[0]}.local"})
        except OSError:
            pass
        try:  # the address used to reach the outside: the LAN address on a home network (no packet is sent)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("192.0.2.1", 9))
                found.add(s.getsockname()[0])
        except OSError:
            pass
        _machine = frozenset(h for h in found if h)
    return _machine


def _configured() -> set[str]:
    hosts: set[str] = set()
    if app := os.environ.get("FLY_APP_NAME", "").strip():
        hosts.add(f"{app.lower()}.fly.dev")
    for part in os.environ.get("OPENMOB_PUBLIC_URL", "").split(","):
        if host := host_of(part):
            hosts.add(host)
    return hosts


def hosts() -> set[str]:
    """Every host this server is known to answer at."""
    with _lock:
        extra = set(_extra)
    return _configured() | extra | LOCAL | _machine_hosts()


def is_own(url_or_host: str) -> bool:
    """`url_or_host` points at this server: a known host (or a subdomain of a hosted one), or a loopback address."""
    host = host_of(url_or_host)
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_loopback or ip.is_unspecified:
            return True
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            return is_own(str(ip.ipv4_mapped))
    except ValueError:
        pass
    known = hosts()
    return host in known or any(host.endswith("." + h) for h in known if "." in h and not _is_ip(h))


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


REFUSAL = ("that address is OpenMob's own dashboard, which the agent never opens on the phone (it could change the "
           "owner's account), so it's never opened.")


def refusal(url: str) -> str | None:
    """Why a link may not be opened (it reaches this server), or None."""
    return REFUSAL if is_own(url) else None


def _reset_for_tests() -> None:
    global _machine
    with _lock:
        _extra.clear()
    _machine = None
