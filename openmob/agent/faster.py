"""Faster mode: what may go to TypeSafe as an image, and when (docs/design/faster-mode.md).

Faster mode is the phone owner's opt-in (signed on the phone with its screen lock, DeviceManager). While it is on, the
loop may send a small screenshot (jev_image_side, 768 px) of a screen *without usable text* (a canvas game, a web
canvas, an app that draws its own UI) to Jev, to tell a loading screen from a ready one (J3) and to name the screen's
state (J1). Step 2 (Jev taps, agent/loop.py _jev_tap_step): on a routine game screen it may tap a routine control
(start, continue, dismiss) through every check a model tap goes through; the word checks for that are at the end.

`refusal` is the one check every image passes before any request, on the server. It answers why an image is NOT sent
(a short reason, recorded on the step as `jev_image_skip`), or None when it may be. The order is cheapest first; the
black-frame check runs on the prepared image (`black_frame`).
"""

from __future__ import annotations

import re

from ..phone.adb import UIElement
from . import permission_dialogs, sensitive, waiting
from .fast import OCR_CLASS

# Reasons an image isn't sent (the steps table's jev_image_skip). Only the first that applies is recorded.
OFF = "off"  # Faster mode is off for this phone (or this server disabled it)
DRIVE = "drive"  # a drive session whose key the owner didn't allow images for
NO_JEV = "no_jev"  # no TypeSafe key on this server
LABELED = "labeled"  # the screen has usable text: Jev text reads it, no image needed (not a refusal)
UNKNOWN_WINDOW = "unknown_window"  # no app identified in front
BLOCKED_APP = "blocked_app"  # an app this task may not touch
SENSITIVE_APP = "sensitive_app"  # banking, payments, wallets, password managers (config.sensitive_apps), always
SYSTEM_DIALOG = "system_dialog"  # a permission controller or other hidden system dialog
LOCKED = "locked"  # the lock screen is up
PASSWORD_FIELD = "password_field"  # a password field is on screen
SENSITIVE_NUMBER = "sensitive_number"  # a card number or SSN in the screen's text (agent/sensitive.py)
NO_TEXT_CHECK = "no_text_check"  # no OCR on this server, so the screen's words couldn't be checked first
BLACK_FRAME = "black_frame"  # the screenshot is black: a secure window or a blacked-out read
NO_FRAME = "no_frame"  # no screenshot could be taken
OTP_TEXT = "otp_text"  # a one-time code (4-8 digits near "code", "verification", "OTP", "passcode", "PIN")
NOTIFICATION = "notification"  # the notification shade, a heads-up or another System UI window is showing
APP_CHANGED = "app_changed"  # the app in front changed between the package check and the frame (review S L2)

SYSTEMUI = "com.android.systemui"
# Any run of 8 or more digits (single separators allowed), whatever Luhn says: a misread or partly read card or
# account number still never leaves (review S M1). \d also matches other scripts' digits.
_LONG_DIGITS = re.compile(r"\d(?:[ .\-_/]?\d){7,}")
# A one-time code: 4-8 digits within 60 characters of a code word (review S M2). Plain game scores ("Score 1200")
# don't count; "Your code is 482913" does.
_OTP_NUMBER = re.compile(r"(?<!\d)\d{4,8}(?!\d)")
# Digit groups split by one space or dash ("482 913", "123-456", "48-29-13") are joined before that test (review S2
# F2). The code words include common Spanish, French, German and Portuguese ones (and Russian "код"), and compounds
# that end in "code"/"código" ("Bestätigungscode"). A letter on either side (any script) breaks a word.
_OTP_SPLIT = re.compile(r"(?<=\d)[ \- ](?=\d)")
_OTP_WORDS = re.compile(
    r"(?i)(?<![^\W\d_])(\w*codes?|\w*c[oó]digos?|verification|v[ée]rification|verifica[cç][aã]o|verificaci[oó]n|"
    r"verify|verifizierung\w*|otp|passcode|pin|tan|one[- ]?time|2fa|authenticat\w*|authentifizierung\w*|"
    r"security code|log ?in|sign[- ]?in|confirm\w*|best[aä]tigung\w*|clave|contrase[nñ]a|senha|"
    r"mot de passe|anmelde\w*|connexion|код\w*|пароль)(?![^\W\d_])|(?<![A-Za-z])G-\d")


def labeled(elements: list[UIElement]) -> bool:
    """Accessibility elements with text: the screen Jev text can read (Faster mode leaves it alone unless sparse)."""
    return any(el.cls != OCR_CLASS and (el.text or el.desc) for el in elements)


# A sparse screen (2026-10-17): a few labels around a large area none of them describes, a game's board or play field
# (Tetris's one element is "Game view"; Chess.com's game shows "Back" and "Chess.com" around its board). Jev text reads
# the labels, not the area, so the screen may be sent like a treeless one. Text-heavy screens never are:
# - at most SPARSE_MAX_LABELS labeled elements (text fields count) and SPARSE_MAX_CHARS characters of labels in all
#   (Settings, Maps, YouTube and a Chrome page show dozens; a game's menu or board a handful);
# - no password field and no focused text field (someone is typing: not a game);
# - the play area: waiting.canvas_region, the same definition screen_changes compares (at least 30% of the screen);
# - and, checked on the frame itself (agent/loop.py), something is drawn there (`SPARSE_MIN_DETAIL`): a blank
#   area under a few labels is an empty screen, not a canvas.
SPARSE_MAX_LABELS = 10
SPARSE_MAX_CHARS = 200
SPARSE_MIN_DETAIL = 8.0  # the area's cells' standard deviation (waiting.region_detail; a blank area is ~0)


# Review S2 F1 (2026-10-17): "sparse" alone also matched a full-screen photo, a camera viewfinder and a Google account
# sheet over a game. So a sparse screen also needs:
# - a canvas-type view under the play area (`canvas_view`): a SurfaceView, TextureView, a GLSurfaceView-like class, a
#   WebView, a game engine's view (Unity, Unreal, Godot, Cocos, Flutter), or a plain View that is unlabeled (a custom
#   game board) or labeled as a game view, covering at least SPARSE_CANVAS_COVER of the play area;
# - an app that isn't in SPARSE_NEVER (camera, photos and gallery, messaging, email, social, Google Play services and
#   account sheets, contacts, files, documents and PDF viewers), by package pattern and by the owner's app categories
#   (config.app_categories: messaging, email, social, photos);
# - no email address and no account words among the labels (a sign-in or account chooser sheet).
# A treeless screen (no labels at all) is unchanged: it was never "sparse".
#
# Review 3 F3-M1 (owner decision 2026-10-18, "games only"): SPARSE_NEVER is a denylist, so a video call (Meet, Zoom),
# a photo editor (Snapseed, Lightroom, VSCO), a handwritten note (Keep, Samsung Notes), a browser page, Google Lens
# and a video player still counted. A screen is now sparse only in a game (`game_screen`), on top of the rules above:
# - the app is a game by its package (SPARSE_GAME_APPS: "game" anywhere in it, a known game name such as chess,
#   tetris, sudoku or solitaire, or a known game publisher as a whole package part such as supercell or king), or by
#   the owner's app categories (an `app_categories` entry named "games": none by default, add one to name more);
# - or a game engine's view (SPARSE_ENGINE_CLASS: Unity, Unreal, Godot, Cocos, or a class named GameView or
#   GameSurface) covers at least SPARSE_CANVAS_COVER of the play area, whatever the package.
# Everything else is never sparse: a canvas outside a game (a browser game, a drawing app) gets no Faster mode images.
# The phone doesn't report an app's Play category (ApplicationInfo.category) today, so the package and the views are
# what the server has. SPARSE_NEVER still applies on top.
SPARSE_CANVAS_COVER = 0.5
CANVAS_CLASS = re.compile(r"(?i)(SurfaceView|TextureView|GLSurfaceView|GLView|GLTextureView|WebView|UnityPlayer|"
                          r"Unreal|Godot|Cocos|Flutter|GameView|GameSurface|Canvas|BoardView)")
_PLAIN_VIEW = re.compile(r"^(android\.view\.)?(View|ViewGroup)$")
_GAME_LABEL = re.compile(r"(?i)(?<![a-z])(game|board|canvas|play ?field)(?![a-z])")
SPARSE_NEVER = re.compile(
    r"(?i)(camera|gcam|(^|\.)photos?(\.|$)|gallery|(^|\.)mms(\.|$)|messag|whatsapp|telegram|signal|viber|"
    r"(^|\.)gm(\.|$)|email|mail|outlook|instagram|facebook|snapchat|twitter|tiktok|zhiliaoapp|reddit|"
    r"^com\.google\.android\.gms(\.|$)|^com\.google\.android\.gsf|account|contacts|dialer|(^|\.)files(\.|$)|"
    r"filemanager|myfiles|documentsui|(^|\.)docs(\.|$)|(^|\.)drive(\.|$)|pdf|acrobat|adobe\.reader|office|wps|scanner)")
SPARSE_NEVER_CATEGORIES = {"messaging", "email", "social", "photos"}
SPARSE_GAME_APPS = re.compile(
    r"(?i)(game|chess|tetris|sudoku|solitaire|minecraft|roblox|mahjong|"
    r"(^|\.)(supercell|king|rovio|zynga|gameloft|playrix|miniclip|mihoyo|hoyoverse|mojang|ketchapp|voodoo|"
    r"halfbrick|outfit7|imangi|kiloo|nianticlabs|innersloth|garena|tencent\.ig|pubg)(\.|$))")
SPARSE_GAME_CATEGORIES = {"games"}
SPARSE_ENGINE_CLASS = re.compile(r"(?i)(UnityPlayer|Unreal|Godot|Cocos|GameView|GameSurface)")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_ACCOUNT_WORDS = re.compile(r"(?i)(?<![a-z])(sign in|sign-in|log in|login|continue as|choose an account|accounts?|"
                            r"password|e-?mail)(?![a-z])")


def canvas_view(elements: list[UIElement], region: tuple[int, int, int, int], engine: bool = False) -> bool:
    """A canvas-type view under the play area (see SPARSE_CANVAS_COVER): one covering that share of it. `engine`:
    only a game engine's view counts (SPARSE_ENGINE_CLASS)."""
    rx1, ry1, rx2, ry2 = region
    area = max((rx2 - rx1) * (ry2 - ry1), 1)
    for el in elements:
        if el.cls == OCR_CLASS:
            continue
        label = el.text or el.desc
        if engine:
            canvas = bool(SPARSE_ENGINE_CLASS.search(el.cls or ""))
        else:
            canvas = bool(CANVAS_CLASS.search(el.cls or "")) or (
                bool(_PLAIN_VIEW.search(el.cls or "")) and (not label or bool(_GAME_LABEL.search(label))))
        if not canvas:
            continue
        x1, y1, x2, y2 = el.bounds
        w, h = min(x2, rx2) - max(x1, rx1), min(y2, ry2) - max(y1, ry1)
        if w > 0 and h > 0 and w * h >= SPARSE_CANVAS_COVER * area:
            return True
    return False


def never_sparse(package: str | None, categories: dict | None = None) -> bool:
    """An app whose screens are never "sparse" (photos, camera, messages, accounts...): see SPARSE_NEVER."""
    if not package:
        return True
    if SPARSE_NEVER.search(package):
        return True
    if categories:
        from ..permissions import category_of

        return bool(category_of(package, categories) & SPARSE_NEVER_CATEGORIES)
    return False


def game_app(package: str | None, categories: dict | None = None) -> bool:
    """A game by its package: SPARSE_GAME_APPS, or the owner's "games" app category (review 3 F3-M1)."""
    if not package:
        return False
    if SPARSE_GAME_APPS.search(package):
        return True
    if categories:
        from ..permissions import category_of

        return bool(category_of(package, categories) & SPARSE_GAME_CATEGORIES)
    return False


def game_screen(elements: list[UIElement], region: tuple[int, int, int, int], package: str | None,
                categories: dict | None = None) -> bool:
    """A game's screen (review 3 F3-M1, "games only"): a game app, or a game engine's view under the play area."""
    return game_app(package, categories) or canvas_view(elements, region, engine=True)


def sparse_region(elements: list[UIElement], screen: tuple[int, int] | None, package: str | None,
                  categories: dict | None = None) -> tuple[int, int, int, int] | None:
    """The play area of a sparse labeled screen (see above), or None: not sparse, or not labeled at all.
    `package` (None: unknown, never sparse) and `categories` (config.app_categories) rule out SPARSE_NEVER apps; and
    the screen must be a game's (`game_screen`)."""
    real = [el for el in elements if el.cls != OCR_CLASS]
    if any(el.password or (el.focused and el.editable) for el in real):
        return None
    labels = [el.text or el.desc or el.hint for el in real if el.text or el.desc or el.editable]
    if not any(el.text or el.desc for el in real):
        return None  # treeless: eligible as before, not "sparse"
    if len(labels) > SPARSE_MAX_LABELS or sum(len(s) for s in labels) > SPARSE_MAX_CHARS:
        return None
    if never_sparse(package, categories):
        return None
    if any(_EMAIL.search(s) or _ACCOUNT_WORDS.search(s) for s in labels):
        return None  # an account chooser or sign-in sheet: the owner's name and email
    region = waiting.canvas_region(real, screen)
    if region is None or not canvas_view(real, region):
        return None
    if not game_screen(real, region, package, categories):
        return None  # games only (review 3 F3-M1): a call, a photo editor, a note or a web page never is
    return region


def eligible(elements: list[UIElement], screen: tuple[int, int] | None, package: str | None,
             categories: dict | None = None) -> bool:
    """A screen Faster mode may look at (before the never-sent checks): no usable text, or sparse."""
    return not labeled(elements) or sparse_region(elements, screen, package, categories) is not None


def screen_text(elements: list[UIElement]) -> list[str]:
    return [s for el in elements for s in (el.text, el.desc, el.hint) if s]


def long_digits(text: str | None) -> bool:
    """A run of 8 or more digits (single separators allowed)."""
    return bool(text and _LONG_DIGITS.search(text))


def otp_text(text: str | None) -> bool:
    """A 4-8 digit number within 60 characters of a code word (a one-time code, a PIN)."""
    if not text:
        return False
    text = _OTP_SPLIT.sub("", text)
    for m in _OTP_NUMBER.finditer(text):
        near = text[max(0, m.start() - 60):m.end() + 60]
        if _OTP_WORDS.search(near):
            return True
    return False


def system_ui(package: str | None, elements: list[UIElement]) -> bool:
    """The notification shade, a heads-up or another System UI window: the foreground is System UI, or the element
    list holds a System UI node (the server has no window list; what it can see is the package and the ids)."""
    if package == SYSTEMUI:
        return True
    return any((el.resource_id or "").startswith(SYSTEMUI + ":") for el in elements)


def refusal(package: str | None, elements: list[UIElement], *, blocked, sensitive_apps: list[str],
            locked: bool, ocr_ran: bool, sparse: bool = False) -> str | None:
    """Why this screen's image may not go to TypeSafe, or None. `elements`: the screen's accessibility elements and
    its OCR words (OCRText); `blocked(package)`: this task's blocked apps; `ocr_ran`: the words were read from this
    very screenshot (without them a treeless screen can't be checked for sensitive numbers, so nothing is sent);
    `sparse`: a sparse labeled screen, whose play area holds words the labels don't, so it needs them too."""
    if not package:
        return UNKNOWN_WINDOW
    if permission_dialogs.PACKAGES.search(package):
        return SYSTEM_DIALOG
    if blocked is not None and blocked(package):
        return BLOCKED_APP
    if any(re.search(p, package, re.IGNORECASE) for p in sensitive_apps):
        return SENSITIVE_APP
    if locked:
        return LOCKED
    if system_ui(package, elements):
        return NOTIFICATION
    if any(el.password for el in elements if el.cls != OCR_CLASS):
        return PASSWORD_FIELD
    # Hidden or covered windows the phone can't read: every labeled element covered by a higher window.
    real = [el for el in elements if el.cls != OCR_CLASS and (el.text or el.desc)]
    if real and all(el.covered for el in real):
        return SYSTEM_DIALOG
    texts = screen_text(elements)
    ssn_context = any(sensitive.ssn_label(t) for t in texts)
    for el in elements:
        card_field = sensitive.card_label(f"{el.text} {el.desc} {el.hint} {el.resource_id}") and el.editable
        for text in (el.text, el.desc, el.hint):
            if text and (sensitive.find(text, ssn_context=ssn_context, card_field=card_field) or long_digits(text)):
                return SENSITIVE_NUMBER
    # The words across elements, joined: a card number split over OCR boxes ("4111 1111" "1111 1111").
    joined = " ".join(texts)
    if sensitive.find(joined, ssn_context=ssn_context) or long_digits(joined):
        return SENSITIVE_NUMBER
    if any(otp_text(t) for t in texts) or otp_text(joined):
        return OTP_TEXT
    if not ocr_ran and (sparse or not labeled(elements)):
        return NO_TEXT_CHECK
    return None


# --- Jev taps (step 2, docs/design/faster-mode.md §3.1) -----------------------------------------------------------

# Words that keep a Jev tap from happening (the main model decides instead), in the tapped box or anywhere on the
# screen: money, offers and ads. A Jev tap is for free routine controls only; the gate's own money and confirm words
# are checked too (agent/loop.py), and the gate still judges any tap that does go.
TAP_SCREEN_WORDS = re.compile(
    r"(?i)(?<![a-z])(buy|purchase|pay|price|offer|sale|deal|bundle|pack|shop|store|subscri\w*|premium|vip|trial|"
    r"gems?|coins?|diamonds?|gold|crystals?|watch|ads?|advert\w*|video|reward\w*|claim|unlock|upgrade|"
    r"remove ads|no ads|in-app)(?![a-z])")
TAP_PRICE = re.compile(r"[$€£¥₹]\s?\d|\d\s?[$€£¥₹]|\d[.,]\d{2}(?!\d)|(?i:\b(usd|eur|gbp)\b)")
TAP_MAX_BOX_SHARE = 0.5  # a Box over half the image isn't one control


def _overlaps(a: tuple, b: tuple) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def tap_words(elements: list[UIElement], box: tuple[int, int, int, int] | None = None) -> str:
    """The words on screen (every element and OCR word), or only those overlapping `box` (device pixels)."""
    out = []
    for el in elements:
        if box is not None and not _overlaps(tuple(el.bounds), box):
            continue
        out += [s for s in (el.text, el.desc, el.hint) if s]
    return " ".join(out)


def tap_words_refusal(words: str) -> str | None:
    """Why the words around a Jev tap rule it out (money, an offer, an ad), or None."""
    if TAP_PRICE.search(words):
        return "price"
    m = TAP_SCREEN_WORDS.search(words)
    return f"word:{m.group(1).lower()}" if m else None


def safe_tap(box_conf: float, visible: float, floor: float) -> bool:
    """The benchmark's safe tap rule: min(Box confidence, "visible?") >= floor (0.5 gave 1 false tap in 340)."""
    return min(box_conf, visible) >= floor
