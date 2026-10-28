"""OpenMob web dashboard: live phone screens, text commands, agent activity.

Serve it on the LAN, or publicly over HTTPS with `openmob run --public`.
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import re
import socket
import subprocess
import sys
import threading
import time
import weakref
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

from . import blocked_apps as blocked_apps_mod
from . import permissions as perm
from . import phone_chats, phone_memory, phone_models
from .agent.models import model_listing
from .devices import DeviceManager, Session
from .memory import NoteError, render_events
from .phone.base import DeviceError
from .phone.protocol import PROTOCOL_VERSION, decode_message
from .phone.remote import PhoneLink
from .screencast import ScreenFeed, View, live_frame, preview_params

STATIC = Path(__file__).parent / "static"
PHONE_CHAT_KINDS = ("chats_list", "chat_read", "chat_open", "chat_new", "chat_rename", "chat_delete")  # §3.6
# Public developer docs served to the /developer console, by name. Only these files, nothing else
# from docs/ (architecture notes and research stay out). Found next to the package (a source checkout)
# or in the working directory (the Docker image copies docs/ to /app/docs).
PUBLIC_DOCS = {"quickstart": "quickstart.md", "concepts": "concepts.md", "phone-setup": "phone-setup.md",
               "api": "api.md", "mcp": "mcp.md", "examples": "examples.md",
               "webhooks": "webhooks.md", "safety": "safety.md", "conventions": "conventions.md",
               "errors": "errors.md", "testing": "testing.md", "self-hosting": "self-hosting.md"}
DOCS_DIRS = [Path(os.environ["OPENMOB_DOCS_DIR"])] if os.environ.get("OPENMOB_DOCS_DIR") else []
DOCS_DIRS += [Path(__file__).parent.parent / "docs", Path.cwd() / "docs"]
PAGE = STATIC / "index.html"
OLD_APP_APPROVALS = ("This phone's OpenMob app is out of date: it signs approvals in an older format "
                     "this server no longer accepts. Install the latest app to approve; until then it "
                     "can only decline.")
LOGIN_MAX_FAILURES = 10  # failed sign-ins per address or email…
LOGIN_WINDOW = 600  # …in this many seconds, then 429
# Every sign-in attempt, right or wrong, in LOGIN_WINDOW (security review 4, M2: each one costs a PBKDF2 hash).
# Generous: a person signs in a few times a day, and an office or a phone carrier shares one address.
LOGIN_MAX_ATTEMPTS_EMAIL = 30
LOGIN_MAX_ATTEMPTS_IP = 60
# Request bodies (security review 4, M1): every route takes small JSON (an instruction is at most 2,000
# characters, a whole orchestration a few tens of KB), and nothing is uploaded over HTTP, so 1 MiB is plenty.
MAX_BODY = 1024 * 1024
# One WebSocket message (uvicorn's default is 16 MiB). The biggest a phone sends is a screenshot: long side at
# most 1280 px (PhoneActions.MAX_SIDE), JPEG at quality 80 for the agent and at most 82 for the live view,
# base64 in JSON. Even pure noise on a square 1280 x 1280 screen at quality 80 is 1.46 MB in base64; a real
# screen is a few hundred KB. Live-view video (at most 8 Mbit/s) comes a frame at a time, far smaller.
WS_MAX_SIZE = 4 * 1024 * 1024
HSTS_MAX_AGE = 365 * 24 * 3600
SIGNUP_MAX_PER_IP = 20  # sign-up attempts per address in LOGIN_WINDOW
PAIR_MAX_FAILURES_IP = 10  # wrong pairing codes per address in LOGIN_WINDOW, then 429
PAIR_MAX_FAILURES_ACCOUNT = 10  # wrong secrets for one account's codes in LOGIN_WINDOW, then 429
SIGNUP_REPLY = "If this email can be used, your account is ready: sign in with it and your password."
# The companion app phones download: OPENMOB_APK, else the debug build from android/ in this repo.
# A server with OPENMOB_REQUIRE_RELEASE_APK=1 (the Docker image) serves only a release build: apk_refusal.
APK = Path(
    os.environ.get("OPENMOB_APK")
    or Path(__file__).resolve().parent.parent / "android" / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
)
HELLO_TIMEOUT = 10
LINK_RECHECK = 5.0  # seconds between re-checks of a phone socket's pairing against the account store


PermissionMode = Literal["ask", "plan", "auto", "trusted", "never"]


class CommandIn(BaseModel):
    text: str
    mode: Literal["auto", "queue"] = "auto"  # auto: corrects a running task; queue: always a new task
    permission_mode: PermissionMode | None = None  # this chat's mode; None: the phone's default


class PermissionsIn(BaseModel):
    """A change to a phone's permission settings. Tightening applies at once; loosening asks the phone."""
    default_mode: PermissionMode | None = None
    ceiling: Literal["ask", "plan", "auto", "trusted"] | None = None
    trusted: list[dict] | None = None  # the whole new list: [{app | category, kinds, expires_at}]
    never: Literal["1h", "24h", "7d", "off"] | None = None
    allow_money: bool | None = None  # "Also allow purchases" with never (off by default; the phone approves)
    task_approval: bool | None = None  # one phone approval per task covers its non-money risky steps
    everyday: bool | None = None  # don't confirm everyday actions (turning it on is approved on the phone)
    permission_prompts: dict[str, str] | None = None  # Android permission dialogs: {type: setting} (loosening asks)
    # Faster mode: the dashboard can only turn it off. Turning it on is done in the phone's OpenMob app.
    faster_mode: Literal["off"] | None = None


class FasterDriveIn(BaseModel):
    key_id: str
    on: bool = True


class Credentials(BaseModel):
    email: str
    password: str


class SignupIn(Credentials):
    invite: str = ""  # one-time code from `openmob account invite`


class ModelIn(BaseModel):
    model: str


class ChatOpenIn(BaseModel):
    chat_id: str


class RenameIn(BaseModel):
    title: str


class FeedbackIn(BaseModel):
    value: int  # 1 = 👍, -1 = 👎, 0 = clear
    note: str = ""


class RedeemIn(BaseModel):
    code: str
    device_id: str
    model: str = ""
    approval_key: str | None = None  # the app's screen-lock-bound public key (see phone/approval_keys.py)


class CodeIn(BaseModel):
    code: str
    device_id: str | None = None  # needed for a typed code: the phone that checks it is the one that may claim it
    model: str = ""  # shown on the owner's dashboard while a typed code waits for this phone


class PhoneUnpairIn(BaseModel):
    device_id: str


class StepUpIn(BaseModel):
    password: str = Field(default="", max_length=1024)  # the account's password again (review 5 H1)


class PhoneTrustIn(BaseModel):
    device_id: str  # the trusted phone signing
    target: str  # the phone to trust (raw id or "app-<id>")
    timestamp: int
    signature: str


class EnrollIn(BaseModel):
    device_id: str | None = None  # the app's id, when the CLI could read it: already paired → no new code


class FailureWindow:
    """Recent failures per key (address, email, account) within `window` seconds, for 429s.

    Memory stays bounded however many keys a sprayer makes up: keys with no hit in the window are swept
    once a window, and a key keeps only its latest KEEP hits (every limit is below that)."""

    KEEP = 100

    def __init__(self, window: float = LOGIN_WINDOW):
        self.window = window
        self.hits: dict[str, list[float]] = {}
        self.lock = threading.Lock()
        self.swept = time.time()

    def count(self, key: str) -> int:
        now = time.time()
        with self.lock:
            recent = [t for t in self.hits.get(key, []) if now - t < self.window]
            if recent:
                self.hits[key] = recent
            else:
                self.hits.pop(key, None)
            return len(recent)

    def add(self, *keys: str) -> None:
        now = time.time()
        with self.lock:
            if now - self.swept >= self.window:
                self.hits = {k: v for k, v in self.hits.items() if v and now - v[-1] < self.window}
                self.swept = now
            for key in keys:
                hits = self.hits.setdefault(key, [])
                hits.append(now)
                del hits[:-self.KEEP]


def client_ip(request) -> str:
    """The visitor's address. On Fly every request arrives from Fly's proxy, so per-IP limits would lump everyone
    together (one visitor could lock out sign-in for all): Fly's own Fly-Client-IP header is used there. It's
    trusted only when FLY_APP_NAME is set, i.e. behind Fly's proxy, which overwrites any value a client sends."""
    if os.environ.get("FLY_APP_NAME") and (fly := request.headers.get("fly-client-ip", "").strip()):
        return fly
    return request.client.host if request.client else "?"


def client_bucket(request) -> str:
    """The address as rate limits count it: an IPv6 address by its /64, since one subscriber is handed a whole
    /64 (2^64 addresses to rotate through). IPv4 addresses (and IPv4-mapped IPv6) count one by one."""
    ip = client_ip(request)
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if addr.version == 4:
        return str(addr)
    if addr.ipv4_mapped is not None:
        return str(addr.ipv4_mapped)
    return str(ipaddress.ip_network(f"{addr}/64", strict=False))


_apk_verdict: dict[tuple, str | None] = {}
_ON, _OFF = ("1", "true", "on", "yes"), ("", "0", "false", "off", "no")


def require_release_apk() -> bool:
    """OPENMOB_REQUIRE_RELEASE_APK, read like the other switches. Any other value stops the server rather than
    quietly serving an unchecked APK (security review 6: "true" turned the check off)."""
    value = os.environ.get("OPENMOB_REQUIRE_RELEASE_APK", "").strip().lower()
    if value in _ON:
        return True
    if value in _OFF:
        return False
    raise SystemExit("OPENMOB_REQUIRE_RELEASE_APK must be 1 or 0 (or true/false, on/off, yes/no).")


require_release_apk()  # a bad value stops the server as it starts, not at the first download


def apk_refusal() -> str | None:
    """Why this server won't hand out APK, or None. Only servers built from the Dockerfile ask
    (OPENMOB_REQUIRE_RELEASE_APK=1): their download must be a release build (openmob/apk_check.py).
    Local servers (om run, self-hosters' debug builds) serve whatever APK they have. Checked once
    per file version; a refusal is logged loudly."""
    if not require_release_apk() or not APK.is_file():
        return None
    st = APK.stat()
    key = (str(APK), st.st_mtime_ns, st.st_size)
    if key not in _apk_verdict:
        from .apk_check import FIX, check_apk

        problems = check_apk(APK).problems
        _apk_verdict.clear()
        _apk_verdict[key] = "; ".join(problems) or None
        if problems:
            print(f"openmob: ERROR: not serving {APK} to phones: {'; '.join(problems)}. {FIX}",
                  file=sys.stderr, flush=True)
    return _apk_verdict[key]


_apk_versions: dict[tuple, str] = {}


def apk_version() -> str:
    """The served APK's build, as the first 12 hex digits of its SHA-256. Download links carry it
    (?v=…) and so does the file name, so a phone or browser never reuses a copy of an older build.
    Hashed once per file version."""
    st = APK.stat()
    key = (str(APK), st.st_mtime_ns, st.st_size)
    if key not in _apk_versions:
        import hashlib

        digest = hashlib.sha256()
        with APK.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                digest.update(chunk)
        _apk_versions.clear()
        _apk_versions[key] = digest.hexdigest()[:12]
    return _apk_versions[key]


_apk_codes: dict[tuple, int | None] = {}


def apk_version_code() -> int | None:
    """The served APK's android:versionCode (openmob/apk_check.py), or None when there is no APK or it can't be
    read. Read once per file version, like apk_version()."""
    if not APK.is_file():
        return None
    st = APK.stat()
    key = (str(APK), st.st_mtime_ns, st.st_size)
    if key not in _apk_codes:
        from .apk_check import version_code

        _apk_codes.clear()
        _apk_codes[key] = version_code(APK)
    return _apk_codes[key]


def hello_version_code(device: dict) -> int:
    """The app's versionCode from its hello (`device.app_version_code`). Apps from before 2026-10-18 send none:
    they are version 1, as is anything that isn't a positive whole number."""
    code = device.get("app_version_code") if isinstance(device, dict) else None
    if isinstance(code, bool) or not isinstance(code, int) or code < 1:
        return 1
    return code


def app_update(base: str, minimum: int) -> dict:
    """The welcome's `app_update` (docs/phone-protocol.md §3.7): the newest app this server hands out, the oldest it
    accepts tasks for, and where to download it. `latest` and `url` are null when there is no APK fit to serve."""
    fit = APK.is_file() and not apk_refusal()
    latest = apk_version_code() if fit else None
    return {"latest": latest, "minimum": max(0, int(minimum or 0)),
            "url": f"{base}/download/openmob.apk?v={apk_version()}" if fit and latest is not None else None}


def is_https(scope) -> bool:
    """The visitor reached us over HTTPS. Behind a local tunnel uvicorn already sets the scheme from the
    forwarded headers (it trusts them from 127.0.0.1 only). On Fly, TLS ends at Fly's proxy: its
    X-Forwarded-Proto is trusted only when FLY_APP_NAME is set, the same way client_ip trusts Fly-Client-IP."""
    if scope.get("scheme") in ("https", "wss"):
        return True
    if os.environ.get("FLY_APP_NAME"):
        proto = next((v for k, v in scope.get("headers", []) if k == b"x-forwarded-proto"), b"")
        return proto.decode("latin-1").strip().lower() == "https"
    return False


class BodyLimit:
    """Refuses a request body over `limit` bytes with 413 (security review 4, M1): by its Content-Length before
    reading anything, and by counting the bytes of a chunked body as they arrive, so no route ever buffers more."""

    def __init__(self, app, limit: int = MAX_BODY):
        self.app = app
        self.limit = limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        length = next((v for k, v in scope.get("headers", []) if k == b"content-length"), None)
        if length is not None and (not length.strip().isdigit() or int(length) > self.limit):
            return await self._refuse(scope, receive, send)
        received = 0
        started = False

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.limit:
                    raise HTTPException(status_code=413, detail="Request body too large.")
            return message

        async def tracked_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except HTTPException as exc:
            if exc.status_code != 413 or started:
                raise
            await self._refuse(scope, receive, send)

    @staticmethod
    async def _refuse(scope, receive, send) -> None:
        await JSONResponse({"detail": "Request body too large."}, status_code=413,
                           headers={"Connection": "close"})(scope, receive, send)


# The signed-out landing page runs under this policy: no inline script or style, nothing from another site.
LANDING_CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:; "
               "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
# Files the landing page loads besides ds.css, by their path under /static/. Only these are served.
LANDING_TYPES = {".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".woff2": "font/woff2",
                 ".webp": "image/webp", ".txt": "text/plain; charset=utf-8"}
LANDING_ASSETS = ["landing.css", "landing.js", "fonts/*.woff2", "fonts/OFL.txt", "img/*.webp"]
LANDING_HOST = re.compile(r"(?:[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?|\[[0-9A-Fa-f:.]{2,45}\])(?::[0-9]{1,5})?")
LANDING_BLOCK = re.compile(r"<!--if ([a-z-]+)-->(.*?)<!--end \1-->", re.S)
INVITE_SUBJECT = "OpenMob invite request"


def landing_assets() -> dict[str, Path]:
    """The landing page's own static files: published path -> file."""
    found: dict[str, Path] = {}
    for pattern in LANDING_ASSETS:
        for path in sorted(STATIC.glob(pattern)):
            if path.is_file() and path.suffix in LANDING_TYPES:
                found[path.relative_to(STATIC).as_posix()] = path
    return found


def render_landing(base: str, invite_email: str | None, hosted: bool, privacy: bool, terms: bool) -> str:
    """static/landing.html with its blocks kept or dropped and its two values filled in, HTML-escaped.
    `base` is the server's own address for the code samples; a value that isn't a plain http(s) host is replaced
    by a placeholder, so a forged Host header can't put anything else on the page."""
    from html import escape
    from urllib.parse import quote

    proto, sep, host = base.partition("://")
    if not sep or proto not in ("http", "https") or not LANDING_HOST.fullmatch(host):
        base = "https://your-openmob-server"
    shown = {"invite": bool(invite_email), "no-invite": not invite_email, "operator": not hosted,
             "privacy": privacy, "terms": terms}
    page = (STATIC / "landing.html").read_text()
    page = LANDING_BLOCK.sub(lambda m: m.group(2) if shown.get(m.group(1)) else "", page)
    href = f"mailto:{quote(invite_email, safe='@')}?subject={quote(INVITE_SUBJECT)}" if invite_email else ""
    return page.replace("{{base}}", escape(base, quote=True)).replace("{{invite_href}}", escape(href, quote=True))


class SecurityHeaders:
    """Headers on every response (security review 4, L3): no MIME sniffing, no referrer to other sites, never
    framed by another page, and HSTS when the visitor came over HTTPS. Only frame-ancestors in the CSP: the
    pages' inline scripts and styles would need a fuller policy written and checked page by page. A response that
    sets its own CSP keeps it (the signed-out landing page: LANDING_CSP)."""

    HEADERS = [(b"x-content-type-options", b"nosniff"), (b"referrer-policy", b"same-origin"),
               (b"x-frame-options", b"DENY"), (b"content-security-policy", b"frame-ancestors 'none'")]

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        extra = list(self.HEADERS)
        if is_https(scope):
            extra.append((b"strict-transport-security", f"max-age={HSTS_MAX_AGE}".encode()))

        async def with_headers(message):
            if message["type"] == "http.response.start":
                present = {k.lower() for k, _ in message.get("headers", [])}
                message["headers"] = list(message.get("headers", [])) + [h for h in extra if h[0] not in present]
            await send(message)

        await self.app(scope, receive, with_headers)


def create_app(manager: DeviceManager, token: str | None = None, store=None,
               ledger=None, webhook_allow_private: bool = False) -> FastAPI:
    """Two modes. Without `store`: one shared token guards everything (local/demo).
    With an AccountStore: users sign in, phones carry their own key, and everyone sees only
    their own phones — a pairing code works only for the account that made it. Accounts mode
    also serves the developer API (/v1) and its console (/developer)."""
    app = FastAPI(title="OpenMob", docs_url=None, redoc_url=None)
    apk_refusal()  # a hosted server says at start if its download is unfit
    app.add_middleware(BodyLimit)
    app.add_middleware(SecurityHeaders)  # outermost: a 413 gets the headers too

    def session_token(request: Request) -> str | None:
        # Cookie (browsers) or header (phone app, bridge). Never the URL: links get copied and logged.
        return request.cookies.get("openmob_session") or request.headers.get("x-openmob-session")

    def account(request: Request) -> str | None:
        """Logged-in account, or None in token mode."""
        return store.account_for_session(session_token(request)) if store else None

    def require_auth(request: Request) -> None:
        """Dashboard/API guard for both modes."""
        if store is not None:
            if account(request) is None:
                raise HTTPException(status_code=401, detail="Sign in to OpenMob first.")
            return
        if token and token not in (request.headers.get("x-openmob-token"), request.query_params.get("t")):
            raise HTTPException(status_code=401, detail="Bad or missing token")

    def owned_session(device_id: str, request: Request) -> Session:
        found = manager.get(device_id)
        acct = account(request)
        # In hosted mode, hide phones that aren't yours (404, not 403, so existence stays private).
        if not found or (store is not None and found.account_id != acct):
            raise HTTPException(status_code=404, detail=f"Unknown device {device_id}")
        return found

    def socket_base(ws: WebSocket) -> str:
        """The http(s) address a phone's socket came in on: the host it paired with (behind the tunnel, the
        forwarded one). The phone opens a download link only when it matches its own server exactly."""
        proto = ws.headers.get("x-forwarded-proto") or ws.url.scheme
        proto = {"ws": "http", "wss": "https"}.get(proto, proto)
        host = ws.headers.get("x-forwarded-host") or ws.headers.get("host") or ws.url.netloc
        return f"{proto}://{host}"

    def public_base(request: Request) -> str:
        # Behind the HTTPS tunnel the request arrives as http://localhost; trust the forwarded headers.
        proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
        return f"{proto}://{host}"

    # --- pages -----------------------------------------------------------

    def landing_page(request: Request) -> HTMLResponse:
        """The signed-out landing page, under its strict CSP. Never cached: the same address is the dashboard
        once signed in. The invite buttons need `invite_email`; the operator's note shows only on a server that
        isn't the hosted one (no invite address and not on Fly)."""
        invite_email = manager.cfg.invite_email
        hosted = bool(invite_email) or bool(os.environ.get("FLY_APP_NAME"))
        page = render_landing(public_base(request), invite_email, hosted,
                              (STATIC / "privacy.html").is_file(), (STATIC / "terms.html").is_file())
        return HTMLResponse(page, headers={"Content-Security-Policy": LANDING_CSP, "Cache-Control": "no-store"})

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        # Signed-out visitors in account mode get the landing page; everyone else the dashboard.
        if store is not None and account(request) is None:
            return landing_page(request)
        return PAGE.read_text()  # re-read so page tweaks show up without a restart

    def legal_page(name: str) -> HTMLResponse:
        # The owner's own policy text, dropped in as static/privacy.html or static/terms.html; 404 until then.
        path = STATIC / f"{name}.html"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Not found.")
        return HTMLResponse(path.read_text())

    @app.get("/privacy", response_class=HTMLResponse)
    def privacy_page() -> HTMLResponse:
        return legal_page("privacy")

    @app.get("/terms", response_class=HTMLResponse)
    def terms_page() -> HTMLResponse:
        return legal_page("terms")

    @app.get("/static/ds.css")
    def design_system() -> Response:
        """The design system every page links (public: the phone's /pair page uses it too)."""
        css = (STATIC / "ds.css").read_text()
        return Response(css, media_type="text/css", headers={"Cache-Control": "public, max-age=300"})

    assets = landing_assets()

    @app.get("/static/{path:path}")
    def landing_asset(path: str) -> FileResponse:
        """The landing page's stylesheet, script, fonts and app screenshots (public; an allowlist, nothing else)."""
        file = assets.get(path)
        if file is None:
            raise HTTPException(status_code=404, detail="Not found.")
        long = file.suffix in (".woff2", ".webp")
        return FileResponse(file, media_type=LANDING_TYPES[file.suffix],
                            headers={"Cache-Control": f"public, max-age={86400 if long else 300}"})

    @app.get("/docs/{name}")
    def public_doc(name: str) -> Response:
        """A public developer doc as Markdown (rendered, sanitized, by /developer). Allowlisted names only."""
        filename = PUBLIC_DOCS.get(name.removesuffix(".md"))
        path = next((d / filename for d in DOCS_DIRS if filename and (d / filename).is_file()), None)
        if path is None:
            raise HTTPException(status_code=404, detail="Unknown doc.")
        return Response(path.read_text(), media_type="text/markdown; charset=utf-8",
                        headers={"Cache-Control": "public, max-age=300"})

    @app.get("/safety", response_class=HTMLResponse)
    def safety_page() -> str:
        """Public: what Faster mode sends and never sends (the phone app's "What is sent" link points here)."""
        return (STATIC / "safety.html").read_text()

    @app.get("/connect", response_class=HTMLResponse)
    def connect_page() -> str:
        return (STATIC / "connect.html").read_text()

    @app.get("/phones", response_class=HTMLResponse)
    def phones_page() -> str:
        return (STATIC / "phones.html").read_text()  # all data comes from /api/devices

    def memory_on() -> bool:
        return bool(getattr(getattr(manager, "cfg", None), "memory", False)) and getattr(manager, "memory", None) is not None

    @app.get("/memory", response_class=HTMLResponse)
    def memory_page() -> str:
        if not memory_on():
            raise HTTPException(status_code=404, detail="Not found")
        return (STATIC / "memory.html").read_text()  # all data comes from /api/memory

    @app.get("/pair", response_class=HTMLResponse)
    def pair_page() -> str:
        return (STATIC / "pair.html").read_text()

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request):
        # A dedicated sign-in page can be dropped in as static/login.html; until then the landing
        # page explains how to sign in with an invite.
        path = STATIC / "login.html"
        return path.read_text() if path.exists() else landing_page(request)

    @app.api_route("/download/openmob.apk", methods=["GET", "HEAD"])  # HEAD: /pair checks it exists
    def download_apk() -> FileResponse:
        if not APK.exists():
            raise HTTPException(status_code=404, detail="The app hasn't been built yet: cd android && ./gradlew assembleDebug")
        if apk_refusal():
            raise HTTPException(status_code=503, detail="The app download is unavailable on this server right now: "
                                "its build isn't a signed release. Ask whoever runs the server.")
        # Never reuse a cached copy: revalidate every time (the ETag makes that cheap), and name the
        # file after its build so a new download doesn't sit beside an old one as "OpenMob (1).apk".
        version = apk_version()
        return FileResponse(APK, media_type="application/vnd.android.package-archive",
                            filename=f"OpenMob-{version}.apk",
                            headers={"Cache-Control": "no-cache", "X-OpenMob-Apk-Version": version})

    # --- accounts (hosted mode only) -------------------------------------

    def _set_session(response: Response, account_id: str, request: Request) -> str:
        tok = store.create_session(account_id)
        response.set_cookie("openmob_session", tok, httponly=True, samesite="lax", max_age=30 * 24 * 3600,
                            secure=is_https(request.scope))  # over HTTPS, never sent over plain HTTP (review 4, L3)
        return tok

    signups = FailureWindow()

    @app.post("/api/auth/signup")
    def signup(body: SignupIn, request: Request) -> dict:
        """Create an account with a one-time invite code. The reply is the same whether or not the
        email already had one (there's no email sending yet to tell the owner instead), and it never
        signs in: the client signs in next with /api/auth/login, whose failures are rate-limited.
        A 400 judges only the request itself (the email, the password, the invite), never other
        accounts; a valid invite is used up either way."""
        if store is None:
            raise HTTPException(status_code=404, detail="Accounts are not enabled.")
        from .accounts import AccountExists, AuthError

        ip = f"ip:{client_bucket(request)}"
        if signups.count(ip) >= SIGNUP_MAX_PER_IP:
            raise HTTPException(status_code=429, detail="Too many sign-ups from this address. Try again in a few minutes.",
                                headers={"Retry-After": str(LOGIN_WINDOW)})
        signups.add(ip)
        try:
            store.create_account_with_invite(body.email, body.password, body.invite)
        except AccountExists:
            pass  # same reply as a new account
        except AuthError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        return {"ok": True, "message": SIGNUP_REPLY}

    # Failed sign-ins per client address and per email, in the last LOGIN_WINDOW seconds: the
    # password form mustn't be a free password-guessing oracle.
    login_failures = FailureWindow()
    # Every attempt, right or wrong, per address and per email: each one costs a PBKDF2 hash (review 4, M2).
    login_attempts = FailureWindow()

    @app.post("/api/auth/login")
    def login(body: Credentials, request: Request, response: Response) -> dict:
        if store is None:
            raise HTTPException(status_code=404, detail="Accounts are not enabled.")
        from .accounts import AuthError

        keys = (f"ip:{client_bucket(request)}", f"email:{body.email.strip().lower()}")
        if (any(login_failures.count(k) >= LOGIN_MAX_FAILURES for k in keys)
                or login_attempts.count(keys[0]) >= LOGIN_MAX_ATTEMPTS_IP
                or login_attempts.count(keys[1]) >= LOGIN_MAX_ATTEMPTS_EMAIL):
            raise HTTPException(status_code=429, detail="Too many sign-in attempts. Try again in a few minutes.",
                                headers={"Retry-After": str(LOGIN_WINDOW)})
        login_attempts.add(*keys)
        try:
            account_id = store.verify_login(body.email, body.password)
        except AuthError as exc:
            login_failures.add(*keys)
            raise HTTPException(status_code=401, detail=str(exc)) from None
        return {"email": store.account_email(account_id), "session": _set_session(response, account_id, request)}

    def step_up(request: Request, password: str | None) -> None:
        """The account's password again, for what an agent driving the phone's browser must never do with the
        owner's cookie alone: mint or rotate an API key, trust a phone (security review 5 H1). Counted with sign-in's
        limits (a wrong one is a failed sign-in). Token mode (no accounts): the server's token already sufficed."""
        if store is None:
            return
        from .accounts import AuthError

        account_id = account(request)
        email = (store.account_email(account_id) or "") if account_id else ""
        if not email:
            raise HTTPException(status_code=401, detail="Sign in to OpenMob first.")
        if not password:
            raise HTTPException(status_code=403, detail="Enter your OpenMob password to confirm this.")
        keys = (f"ip:{client_bucket(request)}", f"email:{email.strip().lower()}")
        if (any(login_failures.count(k) >= LOGIN_MAX_FAILURES for k in keys)
                or login_attempts.count(keys[0]) >= LOGIN_MAX_ATTEMPTS_IP
                or login_attempts.count(keys[1]) >= LOGIN_MAX_ATTEMPTS_EMAIL):
            raise HTTPException(status_code=429, detail="Too many password attempts. Try again in a few minutes.",
                                headers={"Retry-After": str(LOGIN_WINDOW)})
        login_attempts.add(*keys)
        try:
            ok = store.verify_login(email, password) == account_id
        except AuthError:
            ok = False
        if not ok:
            login_failures.add(*keys)
            raise HTTPException(status_code=403, detail="Wrong password.")

    @app.get("/auth/link")
    def login_link(request: Request, code: str = "") -> Response:
        """One-time sign-in link printed by `openmob account link EMAIL` on the server."""
        if store is None:
            raise HTTPException(status_code=404, detail="Accounts are not enabled.")
        from .accounts import AuthError

        try:
            account_id = store.redeem_login_link(code)
        except AuthError as exc:
            return HTMLResponse(f"<p>{exc}</p>", status_code=400)
        response = RedirectResponse("/", status_code=303)  # drops the code from the address bar
        _set_session(response, account_id, request)
        return response

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response) -> dict:
        if store is not None:
            store.end_session(session_token(request))
        response.delete_cookie("openmob_session")
        return {"ok": True}

    @app.get("/api/auth/me")
    def me(request: Request) -> dict:
        if store is None:
            return {"accounts": False, "memory": memory_on()}  # token mode: the link carries the token (R16)
        acct = account(request)
        info = {
            "accounts": True,
            "email": store.account_email(acct) if acct else None,
            "admin": bool(acct and store.is_admin(acct)),
        }
        if acct:
            info["memory"] = memory_on()  # shows the "What OpenMob remembers" link
        return info

    def audit(action: str, account_id: str | None, **fields) -> None:
        """Into the account's audit log (/developer › Logs), when the ledger is on (accounts mode)."""
        service = getattr(app.state, "v1_service", None)
        if service is not None and account_id:
            service.ledger.audit(action, account_id, **fields)

    # Wrong pairing codes per client address and per account the code's id belongs to: a code has
    # 128 bits of secret, so this is defense in depth, and it voids itself after a few wrong tries.
    # The account counts are kept apart for QR and typed codes (review 3, K3-H2): typed slots can be
    # sprayed blind, so wrong typed codes may lock the account's typed codes, never its QR code. They
    # live in memory: a restart clears them, as it voids every typed code (accounts.py, _typed_fails).
    pair_failures = FailureWindow()

    def account_key(account_id: str, code: str) -> str:
        from .accounts import looks_typed

        return f"{'typed' if looks_typed(code) else 'acct'}:{account_id}"

    def pairing_guard(request: Request) -> str:
        ip = f"ip:{client_bucket(request)}"
        if pair_failures.count(ip) >= PAIR_MAX_FAILURES_IP:
            raise HTTPException(status_code=429, detail="Too many pairing attempts. Try again in a few minutes.",
                                headers={"Retry-After": str(LOGIN_WINDOW)})
        return ip

    def pairing_failed(ip: str, exc, code: str) -> None:
        from .accounts import PairingMalformed, PairingRefused

        if isinstance(exc, PairingMalformed):
            return  # not a code at all (wrong length or characters): it can't hit one, so it isn't a guess
        pair_failures.add(ip)
        if isinstance(exc, PairingRefused) and exc.account_id:
            pair_failures.add(account_key(exc.account_id, code))

    def pairing_refused(exc) -> HTTPException:
        """A 400 for a refused code. Messages never echo the code, and a wrong typed code gets one reply
        whether or not it hit a live code (its tries left show only on the owner's dashboard)."""
        return HTTPException(status_code=400, detail=str(exc))

    def locked_out() -> HTTPException:
        return HTTPException(status_code=429, detail="Too many pairing attempts for this account. "
                             "Try again in a few minutes.", headers={"Retry-After": str(LOGIN_WINDOW)})

    def account_locked(account_id: str, code: str) -> bool:
        return pair_failures.count(account_key(account_id, code)) >= PAIR_MAX_FAILURES_ACCOUNT

    def finish_pairing(body: RedeemIn, request: Request, acct: str | None) -> dict:
        """Redeem a code for this phone's own device key. `acct`: the signed-in account (older apps)
        or None (the code is the credential). The phone gets a device key, never a session."""
        from .accounts import AuthError
        from .phone.approval_keys import valid_public_key

        ip = pairing_guard(request)
        if body.approval_key and not valid_public_key(body.approval_key):
            raise HTTPException(status_code=400, detail="approval_key must be a base64 EC P-256 public key.")
        try:
            owner = store.check_pairing_code(body.code, body.device_id, record=False)["account_id"]
            if account_locked(owner, body.code):
                raise locked_out()
            # A phone that's paired now proves it with its current key to pair again (review 3, K3-L2).
            key = store.redeem_pairing_code(body.code, acct, body.device_id, body.model, body.approval_key,
                                            old_key=request.headers.get("x-openmob-device-key"))
        except AuthError as exc:
            pairing_failed(ip, exc, body.code)
            raise pairing_refused(exc) from None
        raw_id = body.device_id.strip()
        # A new key for this phone: any socket still using the old one is cut off now.
        manager.close_links(f"app-{raw_id}", 4401, "This phone was paired again. Reconnect with its new key.")
        audit("device.paired", owner, device_id=raw_id, outcome=" ".join(body.model.split())[:80] or None)
        print(f"📱 New phone paired: {body.model or raw_id}", flush=True)
        return {"key": key, "server": public_base(request), "email": store.account_email(owner),
                "device_id": raw_id, "trusted_for_approvals": store.trusted_for_approvals(raw_id)}

    @app.post("/api/pair/check")
    def pair_check(body: CodeIn, request: Request) -> dict:
        """Before the phone asks its owner to confirm: which account this code would pair it to. The
        code isn't used up. Wrong codes count toward the same limits as redeeming. A typed code also
        needs `device_id` (and `model`): it's bound to the first phone that checks it, and the owner's
        dashboard shows that phone's model while it waits."""
        if store is None:
            raise HTTPException(status_code=404, detail="Accounts are not enabled.")
        from .accounts import AuthError, looks_typed

        ip = pairing_guard(request)
        try:
            if looks_typed(body.code):
                # Peek first, so a locked account's code isn't bound to a phone it then can't claim.
                owner = store.check_pairing_code(body.code, body.device_id, record=False)["account_id"]
                if account_locked(owner, body.code):
                    raise locked_out()
            info = store.check_pairing_code(body.code, body.device_id, body.model)
        except AuthError as exc:
            pairing_failed(ip, exc, body.code)
            raise pairing_refused(exc) from None
        return {"email": info["email"], "expires": info["expires"], "server": public_base(request)}

    @app.post("/api/pair/claim")
    def pair_claim(body: RedeemIn, request: Request) -> dict:
        """The phone, after its owner confirmed with the screen lock: the code is the credential."""
        if store is None:
            raise HTTPException(status_code=404, detail="Accounts are not enabled.")
        return finish_pairing(body, request, None)

    @app.post("/api/pair/redeem")
    def redeem(body: RedeemIn, request: Request) -> dict:
        """Older apps and `openmob bridge --email`: the same, from a signed-in session of the code's account."""
        if store is None:
            raise HTTPException(status_code=404, detail="Accounts are not enabled.")
        acct = account(request)
        if acct is None:
            raise HTTPException(status_code=401, detail="Sign in on the phone first.")
        return finish_pairing(body, request, acct)

    @app.post("/api/phone/unpair")
    def phone_unpair(body: PhoneUnpairIn, request: Request) -> dict:
        """The phone unpairs itself with its own device key (X-OpenMob-Device-Key), no session needed."""
        if store is None:
            raise HTTPException(status_code=404, detail="Accounts are not enabled.")
        from .accounts import AuthError

        raw_id = body.device_id.strip()
        try:
            owner = store.unpair_by_key(raw_id, request.headers.get("x-openmob-device-key") or "")
        except AuthError:
            raise HTTPException(status_code=401, detail="This phone isn't paired, or its key is wrong.") from None
        # Removed first, as on every other revoke path: its tasks stop as device_revoked, not as a phone error.
        manager.remove(f"app-{raw_id}")
        manager.close_links(f"app-{raw_id}", 4401, "This phone was unpaired.")
        audit("device.unpaired", owner, device_id=raw_id, outcome="from the phone")
        return {"ok": True}

    def trusted(account_id: str, raw_id: str, how: str) -> dict:
        audit("device.trusted", account_id, device_id=raw_id, outcome=how)
        s = manager.get(f"app-{raw_id}")
        if s is not None and s.link is not None:
            manager.resume(s)  # it can answer the approvals still waiting on the other phones now
        return {"ok": True, "trusted_for_approvals": True}

    @app.post("/api/devices/{device_id}/trust", dependencies=[Depends(require_auth)])
    def trust(device_id: str, request: Request, body: StepUpIn | None = None) -> dict:
        """The owner, signed in on the dashboard, trusts a phone for approvals on their other phones.
        Only a dashboard session can do this (an API key can't reach /api), with the account's password again
        (review 5 H1: the cookie alone could be an agent in the phone's browser), or a trusted phone's
        screen-lock signature (/api/phone/trust)."""
        if store is None:
            raise HTTPException(status_code=404, detail="Accounts are not enabled.")
        step_up(request, body.password if body else None)
        raw_id = device_id.removeprefix("app-")
        if not store.trust_device(account(request), raw_id):
            raise HTTPException(status_code=404, detail="Not your phone.")
        return trusted(account(request), raw_id, "from the dashboard")

    @app.post("/api/phone/trust")
    def phone_trust(body: PhoneTrustIn, request: Request) -> dict:
        """A trusted phone vouches for another of the owner's phones, signing
        "openmob-trust-1|trust|<target>|<time>" (approval_keys.trust_message: never valid as an approval)
        with its screen-lock approval key (X-OpenMob-Device-Key authenticates the phone itself)."""
        if store is None:
            raise HTTPException(status_code=404, detail="Accounts are not enabled.")
        from .accounts import AuthError
        from .phone.approval_keys import verify_trust

        signer = body.device_id.strip()
        target = body.target.removeprefix("app-").strip()
        try:
            owner = store.verify_device(signer, request.headers.get("x-openmob-device-key") or "")
        except AuthError:
            raise HTTPException(status_code=401, detail="This phone isn't paired, or its key is wrong.") from None
        auth = store.device_auth(signer)
        if not store.trusted_for_approvals(signer) or not auth or not auth["approval_key"]:
            raise HTTPException(status_code=403, detail="Only a phone trusted for approvals can trust another.")
        if not verify_trust(auth["approval_key"], target, body.timestamp, body.signature):
            raise HTTPException(status_code=403, detail="The trust wasn't signed with this phone's screen lock.")
        if not store.trust_device(owner, target):
            raise HTTPException(status_code=404, detail="Not your phone.")
        return trusted(owner, target, f"by phone {signer}")

    @app.post("/api/devices/{device_id}/revoke", dependencies=[Depends(require_auth)])
    def revoke(device_id: str, request: Request) -> dict:
        if store is None:
            raise HTTPException(status_code=404, detail="Accounts are not enabled.")
        # The dashboard knows phones by session id ("app-<device id>"); the store by device id.
        raw_id = device_id.removeprefix("app-")
        if not store.revoke_device(account(request), raw_id):
            raise HTTPException(status_code=404, detail="Not your phone.")
        # Drop it from the phone lists first: that stops its tasks as device_revoked, before the closed socket can
        # fail the running one as a phone error.
        manager.remove(f"app-{raw_id}")
        manager.close_links(f"app-{raw_id}", 4401, "This phone was unpaired from its account.")  # every socket
        audit("device.removed", account(request), device_id=raw_id, outcome="from the dashboard")
        return {"ok": True}

    # --- pairing / device lists ------------------------------------------

    def phone_base(request: Request) -> str:
        """The server address a phone should use. A phone can't reach "localhost": pair it with this
        computer's network name instead, which also keeps working when the computer's IP changes.
        (Not behind a tunnel: that's public.)"""
        base = public_base(request)
        tunneled = "x-forwarded-host" in request.headers
        if base.startswith(("http://localhost", "http://127.0.0.1")) and not tunneled and local_hostname():
            base = f"http://{local_hostname()}:{request.url.port or 80}"
        return base

    def same_site_only(request: Request) -> None:
        """Refuse a request another site's page made (security review 3, K3-L1). Minting a code voids the
        live one and spends the account's hourly quota, so a page elsewhere mustn't trigger it with the
        owner's cookie. Browsers say where a request came from (Sec-Fetch-Site, Origin); the phone app,
        the CLI and the bridge send neither, and they carry their session in a header, not a cookie."""
        from urllib.parse import urlsplit

        site = request.headers.get("sec-fetch-site")
        origin = request.headers.get("origin")
        host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
        if (site is not None and site not in ("same-origin", "none")) or (
                origin is not None and urlsplit(origin).netloc.lower() != host.lower()):
            raise HTTPException(status_code=403, detail="Open Connect a phone on this server's own dashboard.")

    def mint_pairing(account_id: str, base: str, purpose: str) -> dict:
        from urllib.parse import quote

        from .accounts import PairingLimit

        try:
            code, expires = store.create_pairing_code(account_id, purpose)
        except PairingLimit as exc:
            raise HTTPException(status_code=429, detail=str(exc), headers={"Retry-After": "600"}) from None
        audit("pairing.code_created", account_id, outcome=purpose)
        return {
            "pair_url": f"{base}/pair?code={quote(code)}",
            "app_link": f"openmob://connect?server={quote(base, safe='')}&code={quote(code)}",
            "code": code,
            "enrollment_id": code[:8],
            "expires": expires,
            "ttl": round(expires - time.time()),
            "email": store.account_email(account_id),
        }

    @app.post("/api/pairing", dependencies=[Depends(same_site_only), Depends(require_auth)])
    def pairing(request: Request) -> dict:
        """Data for the QR code on /connect, made when the owner opens "Connect a phone". Accounts
        mode issues a single-use, account-bound code that works for 2 minutes. POST only, from this
        server's own pages: a GET could be a link or an image on any site (review 3, K3-L1)."""
        from urllib.parse import quote

        base = phone_base(request)
        common = {
            "server": base,
            "apk_url": f"{base}/download/openmob.apk?v={apk_version()}" if APK.exists() and not apk_refusal() else None,
            "local": base.startswith(("http://localhost", "http://127.0.0.1")),
        }
        if store is None:
            tok = token or ""
            return {
                **common,
                "pair_url": f"{base}/pair?t={quote(tok)}",
                "app_link": f"openmob://connect?server={quote(base, safe='')}&t={quote(tok)}",
                "accounts": False,
            }
        return {**common, **mint_pairing(account(request), base, "dashboard"), "accounts": True}

    def hosted_only() -> None:
        if store is None:
            raise HTTPException(status_code=404, detail="Accounts are not enabled.")

    @app.post("/api/pairing/code", dependencies=[Depends(same_site_only), Depends(require_auth)])
    def typed_code(request: Request) -> dict:
        """A 6-character code for the owner to type on the phone (the fallback to the QR code), made
        only by a signed-in dashboard session: an API key can't reach /api. It works once, for 5
        minutes, and replaces the account's previous typed code. Shown once: it's never sent again,
        logged, or written anywhere but as a keyed hash."""
        hosted_only()
        from .accounts import TYPED_MAX_FAILURES, PairingLimit, display_typed_code

        acct = account(request)
        try:
            code, expires = store.create_typed_code(acct)
        except PairingLimit as exc:
            raise HTTPException(status_code=429, detail=str(exc), headers={"Retry-After": "600"}) from None
        audit("pairing.code_created", acct, outcome="typed")
        return {"code": display_typed_code(code), "expires": expires, "ttl": round(expires - time.time()),
                "tries": TYPED_MAX_FAILURES, "email": store.account_email(acct), "server": phone_base(request)}

    @app.get("/api/pairing/code", dependencies=[Depends(require_auth)])
    def typed_code_status(request: Request) -> dict:
        """The account's latest typed code: waiting, confirming (with the phone's model), paired (with
        its id, for Undo), expired or cancelled. Never the code."""
        hosted_only()
        return store.typed_code_status(account(request))

    @app.delete("/api/pairing/code", dependencies=[Depends(same_site_only), Depends(require_auth)])  # as minting (review 4)
    def cancel_typed_code(request: Request) -> dict:
        """The owner cancels a waiting typed code, e.g. when the dashboard names a phone that isn't theirs."""
        hosted_only()
        acct = account(request)
        if store.cancel_typed_code(acct):
            audit("pairing.code_cancelled", acct, outcome="typed")
        return {"ok": True}

    def paired_phones(account_id: str) -> list[dict]:
        """Every phone paired to the account, from the store, with its live state when connected:
        offline and never-connected phones are listed too, so a leaked pairing can't hide."""
        rows = []
        for d in store.list_devices(account_id):
            s = manager.get(f"app-{d.id}")
            live = s is not None and s.account_id == account_id
            row = s.describe() if live else {
                "id": f"app-{d.id}", "model": d.model, "connection": "app", "platform": "android",
                "online": False, "reconnecting": False, "state": "offline", "current": None,
            }
            rows.append({**row, "paired": True, "session": live, "name": d.model, "last_seen": d.last_seen,
                         "paired_at": d.paired_at, "trusted_for_approvals": d.trusted, "paired_via": d.paired_via})
        return rows

    @app.get("/api/devices", dependencies=[Depends(require_auth)])
    def devices(request: Request, rescan: bool = False) -> list[dict]:
        if store is None:
            if rescan or not manager.sessions:
                manager.refresh()
            return [s.describe() for s in manager.sessions_for(None)]
        acct = account(request)
        rows = paired_phones(acct)
        listed = {r["id"] for r in rows}
        # Phones with a live session but no stored pairing (none in practice) still show.
        rows += [s.describe() for s in manager.sessions_for(acct) if s.info.id not in listed]
        return rows

    @app.get("/api/devices/{device_id}/screen.jpg")
    def screen(device_id: str, request: Request, after: float = 0.0, side: int = 0, quality: str = "") -> Response:
        """One live-view frame (polling fallback for screen/ws). `after`: the X-Frame-Time already shown;
        `side`, `quality`: the viewer's panel size in device pixels and its preference (see screencast)."""
        require_auth(request)
        try:
            taken, shot = live_frame(owned_session(device_id, request).driver, after,
                                     *preview_params([View.parse(side, quality)]))
        except DeviceError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from None
        headers = {"Cache-Control": "no-store", "X-Frame-Time": repr(taken)}
        return Response(shot.jpeg, media_type="image/jpeg", headers=headers)

    screen_feeds: weakref.WeakKeyDictionary[Session, ScreenFeed] = weakref.WeakKeyDictionary()

    @app.websocket("/api/devices/{device_id}/screen/ws")
    async def screen_socket(ws: WebSocket, device_id: str) -> None:
        """Live view, pushed: H.264 packets or JPEG preview frames (and JSON texts) while the viewer is
        open; ?side=&quality= size them for the viewer's panel (see screencast). Same auth as
        screen.jpg: cookie or header session, or ?t= in token mode."""
        await ws.accept()  # accept first: a close before accepting reaches clients as a bare HTTP 403
        try:
            require_auth(ws)
            session = owned_session(device_id, ws)
        except HTTPException as exc:
            await ws.close(code=4000 + exc.status_code, reason=str(exc.detail)[:100])  # 4401 or 4404, nothing sent
            return

        def allowed() -> bool:
            try:
                require_auth(ws)
                return owned_session(device_id, ws) is session
            except HTTPException:
                return False

        # Screen sharing isn't asked for at setup: the first time someone opens the live view of a phone
        # without it, the phone offers it once (a notification), and the view uses screenshots meanwhile.
        link = getattr(session, "link", None)
        if link is not None and not getattr(session.driver, "video_available", True) \
                and not getattr(link, "live_view_offered", False):
            link.live_view_offered = True
            link.notify("live_view", "Your dashboard opened the live view.")
        feed = screen_feeds.get(session) or screen_feeds.setdefault(session, ScreenFeed(session.driver))
        await feed.serve(ws, allowed, View.parse(ws.query_params.get("side"), ws.query_params.get("quality")))

    def mode_error(exc: Exception) -> JSONResponse:
        if isinstance(exc, perm.ModeNotAllowed):
            return JSONResponse({"detail": str(exc), "code": "mode_not_allowed"}, status_code=403)
        if isinstance(exc, perm.PhoneUnavailable):
            return JSONResponse({"detail": str(exc), "code": "phone_offline"}, status_code=409)
        return JSONResponse({"detail": str(exc), "code": "invalid_permissions"}, status_code=400)

    @app.post("/api/devices/{device_id}/command")
    def command(device_id: str, body: CommandIn, request: Request) -> Response:
        require_auth(request)
        session = owned_session(device_id, request)
        mode = None
        if body.permission_mode is not None:
            try:  # a chat's mode can't be looser than the phone allows ("Approve on your phone" first)
                mode = manager.check_mode(session.info.id, body.permission_mode)
            except (perm.ModeNotAllowed, perm.PermissionsInvalid) as exc:
                return mode_error(exc)
        result = session.coordinator.submit(body.text, "dashboard", mode=body.mode, permission_mode=mode)
        if result == "update_required":  # the phone's app is below min_app_version (§3.7)
            from .runner import UPDATE_REQUIRED

            return JSONResponse({"detail": UPDATE_REQUIRED, "code": "app_update_required"}, status_code=409)
        return {"result": result}

    def faster_view(session) -> dict:
        """Faster mode for the dashboard: on (and which scope) and, when on, whether this server can act on it at
        all (no TypeSafe key, or no OCR to check a screen's words first: then nothing is ever sent)."""
        active = manager.faster_scope(session.info.id) if hasattr(manager, "faster_scope") else "off"
        agent = getattr(session.coordinator, "agent", None)
        inactive = None
        if active != "off":
            if agent is None or getattr(agent, "images", None) is None:
                inactive = "no TypeSafe key on this server"
            elif not getattr(agent, "use_ocr", False):
                inactive = "no OCR on this server, so no screen's words can be checked and nothing is sent"
        return {"faster_active": active, "faster_inactive": inactive}

    def permissions_view(session) -> dict:
        settings = manager.permission_settings(session.info.id)
        return {**perm.public(settings), "labels": perm.LABELS, "descriptions": perm.DESCRIPTIONS,
                "categories": sorted(manager.cfg.app_categories), "never_durations": list(perm.NEVER_DURATIONS),
                "can_loosen": manager._may_loosen(session), "online": bool(session.online),
                # Whether Faster mode is on for this phone now. The dashboard can only turn it off.
                **faster_view(session)}

    @app.get("/api/devices/{device_id}/permissions")
    def get_permissions(device_id: str, request: Request) -> dict:
        require_auth(request)
        return permissions_view(owned_session(device_id, request))

    @app.patch("/api/devices/{device_id}/permissions")
    def patch_permissions(device_id: str, body: PermissionsIn, request: Request) -> Response:
        """Tightening applies now (200). Loosening (a looser default or ceiling, trusted entries, never)
        asks the phone for its screen lock: 202 {status: needs_phone_approval, approval_id}; poll
        .../permissions/approvals/{approval_id}."""
        require_auth(request)
        session = owned_session(device_id, request)
        patch = body.model_dump(exclude_none=True)
        try:
            result = manager.change_permissions(session, patch, requester="Your dashboard")
        except (perm.ModeNotAllowed, perm.PhoneUnavailable, perm.PermissionsInvalid) as exc:
            return mode_error(exc)
        if result["status"] == "applied":
            return JSONResponse({**result, "settings": permissions_view(session)})
        return JSONResponse({**result, "code": "needs_phone_approval",
                             "detail": "Approve this on the phone, with its screen lock."}, status_code=202)

    @app.post("/api/devices/{device_id}/faster-drive")
    def faster_drive(device_id: str, body: FasterDriveIn, request: Request) -> Response:
        """The owner asks to let one of their API keys' drive sessions use Faster mode on this phone. Applied only
        after the phone's screen-lock approval (202 needs_phone_approval). Off: {on: false}, applied at once."""
        require_auth(request)
        session = owned_session(device_id, request)
        if store is None:
            raise HTTPException(status_code=400, detail="API keys (and drive sessions) exist only in accounts mode.")
        key = next((k for k in store.list_api_keys(account(request)) if k["id"] == body.key_id), None)
        if key is None:
            raise HTTPException(status_code=404, detail="Unknown key.")
        try:
            result = (manager.request_faster_drive(session, key["id"], key["name"], requester="Your dashboard")
                      if body.on else manager.change_permissions(
                          session, {"faster_drive": {"key": key["id"], "on": False}}, requester="Your dashboard"))
        except (perm.ModeNotAllowed, perm.PhoneUnavailable, perm.PermissionsInvalid) as exc:
            return mode_error(exc)
        if result["status"] == "applied":
            return JSONResponse({**result, "settings": permissions_view(session)})
        return JSONResponse({**result, "code": "needs_phone_approval",
                             "detail": "Approve this on the phone, with its screen lock."}, status_code=202)

    @app.get("/api/devices/{device_id}/permissions/approvals/{approval_id}")
    def permission_approval(device_id: str, approval_id: str, request: Request) -> dict:
        require_auth(request)
        session = owned_session(device_id, request)
        row = manager.permission_request(account(request), session.info.id, approval_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Unknown approval.")
        return {**row, "settings": permissions_view(session)}

    # --- the owner's preferences memory (openmob/memory.py): the dashboard session only, ids in the audit log ---

    def memory_owner(request: Request, write: bool = False):
        """The signed-in owner's store and account (token mode: the server's token, local account). Switch off: 404.
        HTTP carries no phone identity: a phone reaches the notes only over its socket (phone_memory, trust checked
        per message), and an untrusted phone's threads get the placeholder (render_events trusted=False)."""
        if not memory_on():
            raise HTTPException(status_code=404, detail="Not found")
        require_auth(request)
        if write:
            same_site_only(request)
        return manager.memory, account(request)

    def note_or_404(note):
        if note is None:
            raise HTTPException(status_code=404, detail="Unknown note.")
        return note

    async def note_body(request: Request) -> dict:
        try:
            body = await request.json()
        except ValueError:
            body = None
        return body if isinstance(body, dict) else {}

    @app.get("/api/memory")
    def memory_list(request: Request) -> dict:
        mem, acct = memory_owner(request)
        notes = mem.list(acct)
        return {"notes": [n for n in notes if n["status"] == "active"],
                "proposed": [n for n in notes if n["status"] == "proposed"]}

    @app.post("/api/memory")
    async def memory_add(request: Request):
        mem, acct = memory_owner(request, write=True)
        body = await note_body(request)
        try:
            # The owner typing it here is the tap: it is active at once.
            note = mem.add(acct, str(body.get("text") or ""), str(body.get("kind") or "about_you"),
                           package=body.get("package"), relation=body.get("relation"),
                           contact_name=body.get("contact_name"), status="active", source="user")
        except NoteError as exc:
            return JSONResponse({"detail": str(exc), "code": "bad_note"}, status_code=400)
        audit("memory.added", acct, outcome=f"note {note['id']}")
        return note

    @app.patch("/api/memory/{note_id}")
    async def memory_edit(note_id: str, request: Request):
        mem, acct = memory_owner(request, write=True)
        body = await note_body(request)
        try:
            note = note_or_404(mem.update(acct, note_id, text=body.get("text"), contact_name=body.get("contact_name")))
        except NoteError as exc:
            return JSONResponse({"detail": str(exc), "code": "bad_note"}, status_code=400)
        audit("memory.edited", acct, outcome=f"note {note_id}")
        return note

    @app.delete("/api/memory/{note_id}")
    def memory_delete(note_id: str, request: Request) -> dict:
        mem, acct = memory_owner(request, write=True)
        if not mem.delete(acct, note_id):
            raise HTTPException(status_code=404, detail="Unknown note.")
        audit("memory.deleted", acct, outcome=f"note {note_id}")
        return {"ok": True}

    @app.post("/api/memory/{note_id}/confirm")
    def memory_confirm(note_id: str, request: Request):
        mem, acct = memory_owner(request, write=True)
        note = note_or_404(mem.confirm(acct, note_id))
        audit("memory.confirmed", acct, outcome=f"note {note_id}")
        return note

    @app.post("/api/memory/{note_id}/dismiss")
    def memory_dismiss(note_id: str, request: Request) -> dict:
        mem, acct = memory_owner(request, write=True)
        done = mem.dismiss(acct, note_id)
        if done is None:
            raise HTTPException(status_code=404, detail="Unknown note.")
        if not done:  # a stale tap: already saved, so it stays
            return JSONResponse({"detail": "That note is already saved.", "code": "not_proposed"}, status_code=409)
        audit("memory.deleted", acct, outcome=f"note {note_id} (not now)")
        return {"ok": True}

    @app.get("/api/devices/{device_id}/blocked-apps")
    def get_blocked_apps(device_id: str, request: Request) -> dict:
        """The phone's blocked apps as it last reported them (a copy: the phone holds and enforces the list), and
        the dashboard's requests it hasn't reported yet. docs/design/blocked-apps.md."""
        require_auth(request)
        return manager.blocked_view(owned_session(device_id, request))

    @app.post("/api/devices/{device_id}/blocked-apps")
    async def block_apps(device_id: str, request: Request) -> Response:
        """Ask the phone to block more apps: {"packages": ["com.example.app", …]}. Only ever adds (there is no
        unblock here or anywhere on the server: only the phone, with its screen lock). Sent now if the phone is
        online, else when it next connects."""
        require_auth(request)
        same_site_only(request)  # a page elsewhere mustn't add blocks with the owner's cookie
        session = owned_session(device_id, request)
        try:
            body = await request.json()
        except ValueError:
            body = None
        try:
            add = blocked_apps_mod.packages(body.get("packages") if isinstance(body, dict) else None)
            view = await run_in_threadpool(manager.request_block, session, add)
        except blocked_apps_mod.InvalidPackages as exc:
            return JSONResponse({"detail": str(exc), "code": "invalid_packages"}, status_code=400)
        audit("device.block_apps", account(request), outcome=f"{len(add)} requested")
        return JSONResponse(view)

    @app.post("/api/devices/{device_id}/stop")
    def stop(device_id: str, request: Request) -> dict:
        require_auth(request)
        owned_session(device_id, request).coordinator.stop()
        return {"result": "stopped"}

    @app.get("/api/models", dependencies=[Depends(require_auth)])
    def models() -> dict:
        return model_listing(manager.cfg)

    @app.post("/api/devices/{device_id}/model")
    def set_model(device_id: str, body: ModelIn, request: Request) -> dict:
        """Choose the model for this phone's next tasks (allowlisted models whose provider is set up)."""
        require_auth(request)
        session = owned_session(device_id, request)
        allowed = {m["id"] for m in manager.cfg.models}
        if body.model not in allowed:
            raise HTTPException(status_code=400, detail=f"Model not allowed. Choose one of: {', '.join(sorted(allowed))}")
        if not session.coordinator.agent.model_available(body.model):
            raise HTTPException(status_code=400, detail="That model isn't available on this server (no API key for its provider).")
        session.coordinator.agent.model = body.model
        # The phone's model chip follows (§3.5). Display only on the phone.
        link = getattr(session, "link", None)
        if link is not None and (state := phone_models.model_state(manager.cfg, session.coordinator.agent)):
            link.post(state)
        running = session.coordinator.snapshot()["state"] != "idle"
        return {"model": body.model, "applies": "next task" if running else "now"}

    # --- chats (history) ----------------------------------------------------

    history = manager.history

    def need_history():
        if history is None:
            raise HTTPException(status_code=501, detail="Chat history isn't enabled on this server.")
        return history

    @app.post("/api/devices/{device_id}/log/clear")  # older name for "New chat"
    @app.post("/api/devices/{device_id}/chat/new")
    def new_chat(device_id: str, request: Request) -> dict:
        require_auth(request)
        session = owned_session(device_id, request)
        try:
            session.coordinator.clear_log()
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        tell_phone(session, {"type": "chat_opened", "ok": True, "chat_id": None})  # Home switches live (§3.6)
        return {"ok": True}

    @app.post("/api/devices/{device_id}/chat/open")
    def open_chat(device_id: str, body: ChatOpenIn, request: Request) -> dict:
        require_auth(request)
        session = owned_session(device_id, request)
        chat = need_history().chat(account(request), body.chat_id)
        if not chat:
            raise HTTPException(status_code=404, detail="Unknown chat.")
        if chat["device_id"] != session.info.id:
            raise HTTPException(status_code=400, detail="That chat was with a different phone.")
        try:
            session.coordinator.open_chat(body.chat_id)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        tell_phone(session, {"type": "chat_opened", "ok": True, "chat_id": body.chat_id})
        return {"ok": True, "chat_id": body.chat_id}

    @app.get("/api/chats", dependencies=[Depends(require_auth)])
    def list_chats(request: Request) -> list[dict]:
        if history is None:
            return []
        return need_history().list_chats(account(request))

    @app.get("/api/chats/{chat_id}", dependencies=[Depends(require_auth)])
    def get_chat(chat_id: str, request: Request) -> dict:
        h = need_history()
        chat = h.chat(account(request), chat_id)
        if not chat:
            raise HTTPException(status_code=404, detail="Unknown chat.")
        return {**chat, "turns": h.turns(account(request), chat_id)}

    def tell_phone(session, message: dict) -> None:
        """The dashboard switched this phone's chat: its Home follows (§3.6)."""
        link = getattr(session, "link", None)
        if link is not None:
            link.post(dict(message))

    def sees_all_chats(session) -> bool:
        """The phone sees all of its account's chats only once trusted for the account (the device record's trust
        flag, as for approvals on the owner's other phones); until then only chats with itself (review 3 K3-M3,
        owner 2026-10-18 "own chats until trusted"). Without accounts there is only the one owner."""
        return store is None or store.trusted_for_approvals(session.info.id.removeprefix("app-"))

    def tell_phones(acct, message: dict, skip=None, chat_device: str | None = None) -> None:
        """A chat renamed or deleted (on the web or on one phone): the account's connected phones update their drawer
        and, for the chat they show, Home (§3.6). An untrusted phone hears only of its own chats ([chat_device]: the
        phone the chat is with)."""
        for other in manager.sessions_for(acct):
            if other is not skip and getattr(other, "link", None) is not None:
                if chat_device is not None and other.info.id != chat_device and not sees_all_chats(other):
                    continue
                other.link.post(dict(message))

    @app.patch("/api/chats/{chat_id}", dependencies=[Depends(require_auth)])
    def rename_chat(chat_id: str, body: RenameIn, request: Request) -> dict:
        acct = account(request)
        if not need_history().rename_chat(acct, chat_id, body.title):
            raise HTTPException(status_code=404, detail="Unknown chat, or empty title.")
        chat = need_history().chat(acct, chat_id) or {}
        tell_phones(acct, {"type": "chat_renamed", "ok": True, "chat_id": chat_id, "title": chat.get("title") or ""},
                    chat_device=chat.get("device_id") or "")
        return {"ok": True}

    @app.delete("/api/chats/{chat_id}", dependencies=[Depends(require_auth)])
    def delete_chat(chat_id: str, request: Request) -> dict:
        acct = account(request)
        chat = need_history().chat(acct, chat_id) or {}  # who it was with: only they (and trusted phones) are told
        result = phone_chats.delete_chat(need_history(), manager.sessions_for(acct), acct, chat_id)
        if result == "unknown":
            raise HTTPException(status_code=404, detail="Unknown chat.")
        if result == "busy":  # a task is running in it: it would keep recording into a deleted chat
            raise HTTPException(status_code=409, detail="Stop the task first.")
        tell_phones(acct, {"type": "chat_deleted", "ok": True, "chat_id": chat_id}, chat_device=chat.get("device_id") or "")
        return {"ok": True}

    @app.post("/api/turns/{turn_id}/feedback", dependencies=[Depends(require_auth)])
    def feedback(turn_id: str, body: FeedbackIn, request: Request) -> dict:
        try:
            ok = need_history().set_feedback(account(request), turn_id, body.value, body.note)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        if not ok:
            raise HTTPException(status_code=404, detail="Unknown turn.")
        return {"ok": True}

    @app.get("/api/devices/{device_id}/status")
    def status(device_id: str, request: Request) -> dict:
        require_auth(request)
        s = owned_session(device_id, request)
        snap = s.coordinator.snapshot()
        # The preferences lines are filled in now, from the notes' current text (the owner is signed in here).
        snap["log"] = render_events(getattr(manager, "memory", None), account(request), snap["log"], trusted=True,
                                    enabled=bool(getattr(getattr(manager, "cfg", None), "memory", False)))
        feedback = history.feedback_map(account(request), snap["chat_id"]) if history and snap.get("chat_id") else {}
        # confirm_on_phone: only the phone may approve the pending risky action (the dashboard hides its buttons)
        on_phone = getattr(manager, "confirm_on_phone", None)
        settings = manager.permission_settings(s.info.id) if hasattr(manager, "permission_settings") else None
        # A system dialog the phone can't read is waiting for the owner (owner_dialog): the live view says so.
        owner_dialog = getattr(s.driver, "owner_dialog", None)
        return {**snap, "device": s.describe(), "feedback": feedback, "confirm_on_phone": bool(on_phone and on_phone(s)),
                "owner_dialog": owner_dialog if isinstance(owner_dialog, str) else None,
                "permissions": {**perm.public(settings), **faster_view(s)} if settings else None}

    # --- admin (accounts mode; admin is granted only via `openmob account admin EMAIL`) ---

    def require_admin(request: Request) -> None:
        if store is None:
            raise HTTPException(status_code=404, detail="Accounts are not enabled.")
        acct = account(request)
        if acct is None:
            raise HTTPException(status_code=401, detail="Sign in to OpenMob first.")
        if not store.is_admin(acct):
            raise HTTPException(status_code=403, detail="You're not an admin.")

    @app.get("/admin", response_class=HTMLResponse)
    def admin_page() -> str:
        return (STATIC / "admin.html").read_text()  # all data comes from the guarded API below

    @app.get("/api/admin/users", dependencies=[Depends(require_admin)])
    def admin_users() -> list[dict]:
        return store.admin_list_accounts()

    @app.get("/api/admin/devices", dependencies=[Depends(require_admin)])
    def admin_devices() -> list[dict]:
        rows = []
        for d in store.admin_list_devices():
            if d["revoked"]:
                continue  # revoked phones are kept in the account store, but not shown
            s = manager.get(f"app-{d['id']}")
            snap = s.coordinator.snapshot() if s else {}
            rows.append({
                **d,
                "session_id": f"app-{d['id']}",
                "online": bool(s and s.online and not d["revoked"]),
                "state": snap.get("state"),
                "current": snap.get("current"),
            })
        rows.sort(key=lambda r: (r["revoked"], not r["online"], -(r["last_seen"] or 0)))
        return rows

    @app.post("/api/admin/devices/{device_id}/revoke", dependencies=[Depends(require_admin)])
    def admin_revoke(device_id: str) -> dict:
        raw_id = device_id.removeprefix("app-")
        if not store.admin_revoke_device(raw_id):
            raise HTTPException(status_code=404, detail=f"Unknown device {device_id}")
        # Drop it from the phone lists first: that stops its tasks as device_revoked, before the closed socket can
        # fail the running one as a phone error.
        manager.remove(f"app-{raw_id}")
        manager.close_links(f"app-{raw_id}", 4401, "This phone was unpaired by an administrator.")  # every socket
        return {"ok": True}

    # --- developer API (accounts mode only: keys belong to accounts) -------------

    if store is not None:
        from .ledger import Ledger
        from .platform.errors import ServiceError
        from .platform.rest import DeveloperApi, service_error_response
        from .platform.service import V1Service

        service = V1Service(manager, store, ledger or Ledger(store.path.with_name("ledger.sqlite")),
                            webhook_allow_private=webhook_allow_private)
        developer_api = DeveloperApi(service, account, require_admin, step_up=step_up)
        app.add_exception_handler(ServiceError, service_error_response)
        app.state.v1_service = service
        app.state.developer_api = developer_api

        from .platform import mcp
        from .platform.orchestrator import Orchestrator, routes as orchestration_routes

        service.orchestrator = Orchestrator(service)  # multi-phone runs, /v1/orchestrations
        app.include_router(orchestration_routes(service.orchestrator, developer_api.need))
        app.state.mcp = mcp.mount(app, service)  # the remote MCP server at /mcp, same rules as /v1
        app.include_router(developer_api.router)
        app.include_router(developer_api.console)
        app.include_router(developer_api.admin)

        @app.post("/v1/enrollments", status_code=201)
        def enroll(request: Request, body: EnrollIn | None = None,
                   p=Depends(developer_api.need("devices:add"))) -> dict:
            """`openmob phone add`: a pairing code for a phone on the developer's USB cable. The phone
            still has to confirm on its own screen (host and account, with the screen lock) before
            it's paired. Already paired to this account (the app's id is known): no new code."""
            device_id = ((body.device_id if body else None) or "").strip()
            if device_id and store.is_paired(p.account_id, device_id):
                s = manager.get(f"app-{device_id}")
                return {"already_paired": True, "device_id": f"app-{device_id}",
                        "online": bool(s and s.account_id == p.account_id and s.online),
                        "email": store.account_email(p.account_id)}
            out = mint_pairing(p.account_id, phone_base(request), "cli")
            return {"already_paired": False, "server": phone_base(request), **out}

        @app.get("/v1/enrollments/{enrollment_id}")
        def enrollment(enrollment_id: str, p=Depends(developer_api.need("devices:add"))) -> dict:
            """pending → paired (the owner confirmed on the phone) → online (its app connected)."""
            status = store.pairing_status(p.account_id, enrollment_id)
            if status is None:
                raise HTTPException(status_code=404, detail="Unknown enrollment.")
            device_id = status["device_id"]
            s = manager.get(f"app-{device_id}") if device_id else None
            online = bool(s and s.account_id == p.account_id and s.online)
            return {"status": status["status"], "device_id": f"app-{device_id}" if device_id else None,
                    "online": online, "model": s.info.model if s else None,
                    # devices:add can't change this: trusting needs the dashboard or a trusted phone.
                    "trusted_for_approvals": bool(device_id and store.trusted_for_approvals(device_id))}

        @app.get("/developer", response_class=HTMLResponse)
        def developer_page() -> str:
            return (STATIC / "developer.html").read_text()  # all data comes from /api/developer

    v1_ledger = getattr(getattr(app.state, "v1_service", None), "ledger", None)
    if (history is not None or v1_ledger is not None) and manager.cfg.history_retention_days > 0:
        def purge_forever() -> None:
            while True:
                try:
                    purge_task_text(manager.cfg.history_retention_days, history, v1_ledger)
                except Exception as exc:  # retention must never take the server down
                    print(f"⚠️  Retention failed: {exc}", flush=True)
                threading.Event().wait(6 * 3600)

        threading.Thread(target=purge_forever, name="openmob-retention", daemon=True).start()

    # --- phone connection ------------------------------------------------

    def pairing_still_valid(raw_id: str, account_id: str | None, key_hash: str | None) -> bool:
        """The phone is still paired to this account, with the key this socket used."""
        auth = store.device_auth(raw_id)
        return bool(auth and not auth["revoked"] and auth["account_id"] == account_id and auth["key_hash"] == key_hash)

    def phone_chat_reply(session, message: dict) -> dict:
        """The app's chat messages (§3.6): always this session's own account and device. An untrusted phone acts only
        on chats with itself; any other chat answers like a missing one (review 3 K3-M3)."""
        kind, acct, dev = message.get("type"), session.account_id, session.info.id
        coordinator = session.coordinator
        own = not sees_all_chats(session)
        if kind == "chats_list":
            return phone_chats.list_chats(manager.history, acct, dev, message, coordinator.chat_id, own_only=own)
        if kind == "chat_read":
            active = set()
            for other in manager.sessions_for(acct):  # queued or running tasks: still going, not cut off
                info = getattr(other.coordinator, "task_info", {}) or {}
                active |= {tid for tid, t in list(info.items()) if t.get("status") in ("queued", "running")}
                if getattr(other.coordinator, "current_task", None):
                    active.add(other.coordinator.current_task)
            return phone_chats.read_chat(manager.history, acct, dev, message, active, own_only=own,
                                         memory=getattr(manager, "memory", None),
                                         memory_on=bool(getattr(getattr(manager, "cfg", None), "memory", False)))
        if kind == "chat_open":
            return phone_chats.open_chat(manager.history, coordinator, acct, dev, message, own_only=own)
        if kind in ("chat_rename", "chat_delete"):
            chat_id = str(message.get("chat_id") or "")
            chat = (manager.history.chat(acct, chat_id) if manager.history is not None and chat_id else None) or {}
            reply = (phone_chats.rename_message(manager.history, acct, message, dev, own) if kind == "chat_rename"
                     else phone_chats.delete_message(manager.history, manager.sessions_for(acct), acct, message, dev, own))
            if reply.get("ok"):  # the account's other phones learn it too (their drawer; untrusted ones: their own chats)
                tell_phones(acct, reply, skip=session, chat_device=chat.get("device_id") or "")
            return reply
        return phone_chats.new_chat(coordinator)

    def safe_chat_reply(session, message: dict) -> dict:
        """[phone_chat_reply], with input it can't use answered `bad_request` instead of ending the socket's loop (review
        3 S3-L2: an exception there dropped the phone as if its network had gone)."""
        try:
            return phone_chat_reply(session, message)
        except Exception as exc:  # noqa: BLE001 (an answer, never a dropped phone; the error is logged)
            print(f"⚠️  Bad chat message from {session.info.id}: {type(exc).__name__}", flush=True)
            return phone_chats.error_reply(message.get("type"), "bad_request")

    def phone_memory_reply(session, message: dict) -> dict:
        """The phone's memory page (§3.9): the switch and this phone's trust for approvals are checked on every
        message (trust can be lost mid-session); off or untrusted answers `denied`, nothing read or changed. Input it
        can't use is answered `bad_request`, never a dropped phone."""
        if not memory_on() or not sees_all_chats(session):
            return phone_memory.DENIED
        device = session.info.id.removeprefix("app-")
        try:
            return phone_memory.reply(manager.memory, session.account_id, message,
                                      lambda action, acct, **f: audit(action, acct, device_id=device, **f))
        except Exception as exc:  # noqa: BLE001 (an answer, never a dropped phone; no note text in the log)
            print(f"⚠️  Bad memory message from {session.info.id}: {type(exc).__name__}", flush=True)
            return phone_memory.error("bad_request")

    def register_approval_key(raw_id: str, key_hash: str, public_key, device: dict) -> None:
        """Phones paired before approval keys existed register theirs on first connect (once)."""
        from .phone.approval_keys import valid_public_key

        if isinstance(public_key, str) and valid_public_key(public_key):
            if store.register_approval_key(raw_id, key_hash, public_key):
                print(f"🔐 Approval key registered for {device.get('model') or raw_id}.", flush=True)

    def verify_phone_approval(session, approval_id: str, record: dict, message: dict) -> bool:
        """A yes counts only if the answering phone signed it with its screen-lock key, over the
        digest of this very action (phone/approval_keys.py). An app phone without a registered key
        can't approve at all: it registers one on its next connect, and until then can only decline.
        (Token/dev mode has no keys, so it trusts the phone as before.)"""
        if store is None:
            return True
        from .phone.approval_keys import verify_approval

        auth = store.device_auth(session.info.id.removeprefix("app-"))
        if not auth or auth["revoked"] or auth["account_id"] != session.account_id or not auth["approval_key"]:
            return False
        return verify_approval(auth["approval_key"], str(approval_id), record["task_id"], True,
                               message.get("timestamp"), message.get("signature"),
                               extra="always" if message.get("always") is True else None,
                               digest=record.get("digest"))

    def signs_action_digests(session) -> bool:
        """Whether this phone's app signs approvals over the action digest (the only format accepted).
        Apps from before it don't say so; the release that added it is the one that also added
        `resolve_url`, so either capability marks a current app."""
        caps = getattr(session.driver, "capabilities", None) or set()
        return bool({"approval_digest", "resolve_url"} & set(caps))

    def approval_blocker(session) -> str | None:
        """Why this phone can't approve yet: hosted app phones need a registered approval key and an app
        that signs the current format. Such a phone is still asked, so it can decline."""
        if not session.info.id.startswith("app-"):
            return None
        auth = store.device_auth(session.info.id.removeprefix("app-"))
        if not (auth and not auth["revoked"] and auth["approval_key"]):
            return ("This phone can't approve yet: its OpenMob app hasn't registered a screen-lock key. Update the "
                    "app and reconnect (it registers on connect). Until then it can only decline.")
        if not signs_action_digests(session):
            return OLD_APP_APPROVALS
        return None

    def phone_can_loosen(session) -> bool:
        if not session.info.id.startswith("app-"):
            return False
        auth = store.device_auth(session.info.id.removeprefix("app-"))
        return bool(auth and not auth["revoked"] and auth["approval_key"]) and signs_action_digests(session)

    def may_approve_for_others(session) -> bool:
        return store.trusted_for_approvals(session.info.id.removeprefix("app-"))

    def verify_faster_grant(session, grant: dict) -> bool:
        """A re-presented Faster mode grant: the phone's own screen-lock signature over the recorded approval (its
        id, task and the change's digest). Its age doesn't matter here: the grant's own signed limits do."""
        if store is None:
            return True
        from .phone.approval_keys import verify_approval

        auth = store.device_auth(session.info.id.removeprefix("app-"))
        if not auth or auth["revoked"] or auth["account_id"] != session.account_id or not auth["approval_key"]:
            return False
        ts = grant.get("timestamp")
        return isinstance(ts, (int, float)) and verify_approval(
            auth["approval_key"], str(grant.get("approval_id") or ""), str(grant.get("task_id") or ""), True, ts,
            grant.get("signature"), now=ts, digest=grant.get("digest"))

    if hasattr(manager, "replaced_listeners"):  # (test doubles may not have these)
        manager.approval_verifier = verify_phone_approval
        manager.faster_grant_verifier = verify_faster_grant
        if store is not None:  # hosted: settings live on each phone's pairing; loosening needs its key
            manager.permissions = perm.AccountPermissions(store)
            manager.can_loosen = phone_can_loosen
            manager.approval_blocker = approval_blocker  # approving at all needs the key
            manager.requires_signature = lambda session: session.info.id.startswith("app-")
            # Approvals for the owner's OTHER phones go only to (and are taken only from) trusted ones.
            # A trusted phone still signs each yes over the action digest with its own key; a permission
            # change is only ever answered by the phone being loosened (DeviceManager.resolve_approval).
            manager.approval_trust = may_approve_for_others

    def phone_reconnected_elsewhere(session, old, new) -> None:
        service = getattr(app.state, "v1_service", None)
        if service is not None:
            service.ledger.audit("device.connection_replaced", session.account_id,
                                 device_id=session.info.id.removeprefix("app-"),
                                 outcome=f"{getattr(old, 'peer', None)} → {getattr(new, 'peer', None)}")

    if hasattr(manager, "replaced_listeners"):
        manager.replaced_listeners.append(phone_reconnected_elsewhere)

    def faster_mode_changed(session, on: bool, scope, by: str) -> None:
        """Every Faster mode change in the hosted audit log: which phone, on (which scope) or off, and who."""
        service = getattr(app.state, "v1_service", None)
        if service is not None:
            service.ledger.audit("device.faster_mode", session.account_id,
                                 device_id=session.info.id.removeprefix("app-"),
                                 outcome=f"{'on:' + str(scope) if on else 'off'} by {by}"[:120])

    if hasattr(manager, "faster_listeners"):
        manager.faster_listeners.append(faster_mode_changed)

    @app.websocket("/phone/ws")
    async def phone_socket(ws: WebSocket) -> None:
        """Phones (OpenMob app or `openmob bridge`) connect here. See openmob/phone/protocol.py."""
        await ws.accept()  # accept first: a close before accepting reaches clients as a bare HTTP 403
        if store is None and token and token not in (ws.query_params.get("t"), ws.headers.get("x-openmob-token")):
            await ws.close(code=4401, reason="Bad or missing token")
            return
        try:
            hello = await asyncio.wait_for(ws.receive_json(), HELLO_TIMEOUT)
        except (asyncio.TimeoutError, WebSocketDisconnect, ValueError):
            await ws.close(code=4400, reason="Expected hello")
            return
        if hello.get("type") != "hello" or hello.get("protocol") != PROTOCOL_VERSION:
            await ws.close(code=4400, reason=f"Expected hello with protocol {PROTOCOL_VERSION}")
            return

        account_id = None
        device = hello.get("device") or {}
        raw_id = str(device.get("id") or "")
        key_hash = None
        if store is not None:
            from .accounts import AuthError

            try:
                account_id = await run_in_threadpool(store.verify_device, raw_id, hello.get("key") or "")
            except AuthError as exc:
                await ws.close(code=4401, reason=str(exc))
                return
            key_hash = store.key_fingerprint(hello.get("key") or "")
            await run_in_threadpool(register_approval_key, raw_id, key_hash, hello.get("approval_key"), device)

        version_code = hello_version_code(device)
        minimum = int(getattr(getattr(manager, "cfg", None), "min_app_version", 0) or 0)

        link = PhoneLink(ws, asyncio.get_running_loop())
        link.peer = ws.client.host if ws.client else None  # to tell the owner about a connection from elsewhere
        link.key_hash = key_hash  # the device key this socket proved; a re-pair makes it stale
        # Creating a session builds an agent (API clients etc.), so keep it off the event loop.
        session = await run_in_threadpool(manager.attach_remote, hello.get("device") or {}, link, account_id)
        # The app's version (§3.7): below the server's minimum it stays connected but no task starts on it.
        session.app_version = str(device.get("app_version") or "")[:40] if isinstance(device, dict) else ""
        session.app_version_code = version_code
        session.coordinator.update_required = version_code < minimum
        # task_state: this server sends the running task as task_state (docs/phone-protocol.md §3.4).
        welcome = {"type": "welcome", "session": session.info.id, "task_state": True}
        # chats: this server answers the app's chat messages (§3.6); chat: the chat new tasks go into now.
        if manager.history is not None:
            welcome.update(chats=True, chat=session.coordinator.chat_id)
        # models: what this phone may pick in its model sheet (§3.5); absent when nothing can run here.
        if (models := await run_in_threadpool(phone_models.model_state, manager.cfg, session.coordinator.agent)):
            welcome["models"] = models
        # app_update: the newest app here, the oldest that may act, and its download (§3.7). Same host as this socket,
        # so it matches the server the phone paired with (the phone opens it only then).
        welcome["app_update"] = await run_in_threadpool(app_update, socket_base(ws), minimum)
        # memory: this phone may open "What OpenMob remembers" (§3.9): the switch on and the phone trusted for approvals.
        welcome["memory"] = await run_in_threadpool(lambda: memory_on() and sees_all_chats(session))
        await link.send(welcome)
        session.coordinator.event("status", f"{session.info.model} connected over the OpenMob app protocol.")
        if session.coordinator.update_required:
            session.coordinator.event("status", f"{session.info.model} has app version {version_code}; this server "
                                                f"needs {minimum} or newer, so no task runs on it until it updates.",
                                      task=None)
        await run_in_threadpool(manager.resume, session)  # pending approvals, "who is using it"
        close_code = None
        checked = time.monotonic()
        chat_rate = phone_chats.RateLimit()  # this socket's chat messages (review 3 S3-L1)
        try:
            while True:
                raw = await ws.receive()
                if raw["type"] == "websocket.disconnect":
                    close_code = raw.get("code")  # 1000: the user disconnected on purpose
                    break
                # A replaced, unpaired or re-paired socket can't act: drop what it sends and cut it off.
                if not manager.is_live(session, link):
                    link.disconnect(4409, "Replaced by a newer connection from this phone.")
                    break
                if store is not None and time.monotonic() - checked > LINK_RECHECK:
                    checked = time.monotonic()
                    if not await run_in_threadpool(pairing_still_valid, raw_id, account_id, key_hash):
                        manager.close_links(session.info.id, 4401, "This phone's pairing changed. Pair it again.")
                        break
                try:
                    message = decode_message(raw.get("text"), raw.get("bytes"))  # binary: a screenshot result
                except ValueError as exc:  # one bad frame (NaN, Infinity, not an object…) is dropped, not the phone
                    print(f"⚠️  Dropped a malformed message from {session.info.id}: {exc}", flush=True)
                    continue
                kind = message.get("type")
                if kind == "result":
                    link.resolve(message)
                elif kind == "video":
                    link.on_video(message)
                elif kind == "video_state":
                    session.driver.video_available = bool(message.get("available"))
                elif kind == "approval":  # the owner approved or denied a risky action, with screen lock
                    await run_in_threadpool(manager.resolve_approval, session, message.get("id"),
                                            message.get("approved") is True, message)
                elif kind == "gate_event":  # the phone's own approval prompt: pending, approved, denied, expired
                    await run_in_threadpool(manager.gate_event, session, message)
                elif kind == "owner_dialog":  # a system dialog the phone can't read waits for the owner, or closed
                    await run_in_threadpool(manager.owner_dialog, session, message)
                elif kind == "device_lock":  # a secure lock came up mid-task, or the owner unlocked
                    await run_in_threadpool(manager.device_lock, session, message)
                elif kind == "task_stop":  # the owner tapped Stop on the phone's agent indicator: stop, stay connected
                    # (reason blocked_app: the phone's gatekeeper stopped a task that reached a blocked app)
                    await run_in_threadpool(manager.phone_task_stop, session, message)
                elif kind == "blocked_apps":  # the phone's own list of blocked apps: the dashboard's copy
                    await run_in_threadpool(manager.phone_blocked_report, session, message)
                elif kind == "permissions_off":  # "Turn off" in the never banner: an unsigned tightening
                    await run_in_threadpool(manager.phone_turned_off_never, session)
                elif kind == "faster_mode_request":  # the owner turns Faster mode on in the app: a signed approval
                    await run_in_threadpool(manager.phone_faster_request, session, str(message.get("scope") or ""))
                elif kind == "faster_mode_resume":  # after a reconnect: the phone re-presents its signed grant
                    await run_in_threadpool(manager.phone_faster_resume, session, message)
                elif kind == "faster_mode_off":  # one tap in the app or its notification: an unsigned tightening
                    await run_in_threadpool(manager.faster_off, session, "the phone's notification"
                                            if message.get("via") == "notification" else "the phone app")
                elif kind in PHONE_CHAT_KINDS:  # the app's chat list and thread (§3.6, docs/design/phone-chats.md)
                    # This account's task history: re-check the pairing first, not only every LINK_RECHECK seconds.
                    if store is not None and not await run_in_threadpool(pairing_still_valid, raw_id, account_id, key_hash):
                        manager.close_links(session.info.id, 4401, "This phone's pairing changed. Pair it again.")
                        break
                    if not chat_rate.allow():  # answered, not cut off: the app's own bursts stay well under it
                        await link.send(phone_chats.error_reply(kind, "rate_limited"))
                        continue
                    await link.send(await run_in_threadpool(safe_chat_reply, session, message))
                elif kind in phone_memory.KINDS:  # the "What OpenMob remembers" page (§3.9): as the chats, re-checked
                    if store is not None and not await run_in_threadpool(pairing_still_valid, raw_id, account_id, key_hash):
                        manager.close_links(session.info.id, 4401, "This phone's pairing changed. Pair it again.")
                        break
                    if not chat_rate.allow():  # one bucket with the chat messages
                        await link.send(phone_memory.error("rate_limited"))
                        continue
                    await link.send(await run_in_threadpool(phone_memory_reply, session, message))
                elif kind == "set_model":  # the owner picked a model or effort in the app's model sheet (§3.5)
                    running = session.coordinator.snapshot()["state"] != "idle"
                    reply = await run_in_threadpool(phone_models.set_model, manager.cfg, session.coordinator.agent,
                                                    message, running)
                    await link.send(reply)
                    if reply.get("ok"):
                        session.coordinator.event("status", f"Model set on the phone: {reply['model']}, effort "
                                                            f"{reply['effort']} (applies to the {reply['applies']}).")
                        if (state := phone_models.model_state(manager.cfg, session.coordinator.agent)):
                            await link.send(state)
                elif kind == "command" and str(message.get("text", "")).strip():
                    targets = manager.phone_stop_targets(session)
                    result = await run_in_threadpool(session.coordinator.submit, message["text"], "phone")
                    if result == "stopped":  # "stop" said or typed on the phone: the owner's call
                        await run_in_threadpool(manager.phone_stopped, session, targets, "stop")
        except (WebSocketDisconnect, ValueError, RuntimeError):  # RuntimeError: we closed it ourselves
            pass
        finally:
            # Decide about the reconnect wait first, then fail the calls still in flight.
            manager.detach_remote(session, link, close_code)
            link.close()
            session.coordinator.event("status", f"{session.info.model} disconnected.")

    return app


def purge_task_text(days: float, history=None, ledger=None) -> dict:
    """The one retention job: every stored copy of task text and screen summaries older than `days`
    goes (chats with their turns, events and steps; orchestration plans and results; delivered or
    dead webhook bodies; idempotency replays). Billing totals and the hashed audit log stay. 0: keep all."""
    out = {}
    if history is not None:
        out["chats"] = history.purge(days)
    if ledger is not None:
        out.update(ledger.purge_text(days))
    return out


def serve_in_background(app: FastAPI, host: str, port: int):
    import uvicorn

    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning", ws_max_size=WS_MAX_SIZE))
    threading.Thread(target=server.run, name="openmob-http", daemon=True).start()
    return server


def lan_ip() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))  # no packets are sent; this just picks the LAN interface
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


_local_name: list[str | None] = []


def local_hostname() -> str | None:
    """This computer's Bonjour name (e.g. "my-mac.local"), which phones and browsers on the
    same network can reach. Unlike lan_ip() it survives the IP changing (sleep, another Wi-Fi)."""
    if not _local_name:
        name = None
        if sys.platform == "darwin":
            try:
                out = subprocess.run(["scutil", "--get", "LocalHostName"], capture_output=True, text=True, timeout=2)
                name = out.stdout.strip() or None
            except (OSError, subprocess.SubprocessError):
                name = None
        if not name:
            host = socket.gethostname()
            name = host.removesuffix(".local") if host.endswith(".local") else None
        _local_name.append(f"{name}.local" if name else None)
    return _local_name[0]
