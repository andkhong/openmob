"""Security review S2 (2026-10-17, second round), server half: each proof of concept from the review, now asserting
the fixed behaviour (fakes only: no phone, no model, no Jev)."""

import io as iolib
import random
import threading

from PIL import Image

from conftest import FakeDriver, RecordingIO, ScriptedClient
from test_jev_taps import DONE, Scenes, make, ocr_words, routine  # noqa: F401 (ocr_words is a fixture)

from openmob import permissions as perm
from openmob.agent import faster, waiting
from openmob.agent.loop import (CANVAS_PRICE_BELOW, CANVAS_ROW_DY, CANVAS_WORDS_DX, JEV_TAP_SOURCE, Agent,
                                Observation, _TaskState)
from openmob.config import Config
from openmob.permissions import TaskPermissions
from openmob.phone.adb import Screenshot, UIElement
from openmob.phone.apps import AppResolver
from openmob.vision.ocr import TextBox


def el(text="", desc="", bounds=(0, 0, 10, 10), cls="android.widget.ImageButton", rid=""):
    return UIElement(0, text, desc, rid, cls, True, None, bounds)


def ocr(text, bounds):
    return UIElement(-1, text, "", "", "OCRText", False, None, bounds)


# --- F1: sparse needs a canvas-type view, and never covers photos, cameras or account sheets ------------------------

PHOTOS = "com.google.android.apps.photos"
PHOTO_ELEMENTS = [
    el(desc="Photo taken on Oct 17, 2026 3:12 PM", bounds=(0, 0, 1080, 2400), cls="android.widget.ImageView"),
    el(desc="Navigate up", bounds=(0, 90, 150, 240)),
    el(desc="Cast", bounds=(780, 90, 930, 240)),
    el(desc="More options", bounds=(930, 90, 1080, 240)),
    el(desc="Share", bounds=(0, 2200, 270, 2350)),
    el(desc="Edit", bounds=(270, 2200, 540, 2350)),
    el(desc="Lens", bounds=(540, 2200, 810, 2350)),
    el(desc="Delete", bounds=(810, 2200, 1080, 2350)),
]


class PhotoViewer(Scenes):
    """Google Photos showing one photo full screen: a few labels around an image with detail (a document)."""

    def __init__(self, package=PHOTOS, elements=PHOTO_ELEMENTS):
        super().__init__([((0, 0, 0), [("PASSPORT", (100, 300, 300, 330)), ("Surname DOE", (100, 340, 320, 370)),
                                       ("Nationality USA", (100, 380, 340, 410))], "content")], package=package)
        self.elements = list(elements)

    def screenshot(self, max_age=0.0, attempts=2):
        rnd = random.Random(1)
        img = Image.new("RGB", self.image)
        img.putdata([(rnd.randrange(256),) * 3 for _ in range(self.image[0] * self.image[1])])
        buf = iolib.BytesIO()
        img.save(buf, "JPEG")
        return Screenshot(buf.getvalue(), *self.image, *self.device)


def test_F1_a_full_screen_photo_is_not_sent(tmp_path, ocr_words):
    driver = PhotoViewer()
    agent, _, images, _ = make(tmp_path, ocr_words, None, [routine("none")], DONE, driver=driver)
    state = _TaskState(task="share my latest photo with Mom", cancel=threading.Event(), perms=TaskPermissions("auto"))
    agent._observe_settled(state)
    assert "state" not in images.calls
    # Even in an app that isn't on the never list, a labeled ImageView over the area isn't a canvas.
    assert faster.sparse_region(PHOTO_ELEMENTS, (1080, 2400), "com.example.viewer") is None


CAMERA_ELEMENTS = [
    el(desc="Settings", bounds=(0, 90, 150, 240)), el(desc="Flash", bounds=(150, 90, 300, 240)),
    el(desc="Gallery", bounds=(60, 2100, 260, 2300)), el(desc="Take picture", bounds=(440, 2100, 640, 2300)),
    el(desc="Switch camera", bounds=(820, 2100, 1020, 2300)),
    el(text="PHOTO", bounds=(400, 1950, 680, 2050), cls="android.widget.TextView"),
]


def test_F1_a_camera_viewfinder_is_not_sent(tmp_path, ocr_words):
    driver = PhotoViewer(package="com.sec.android.app.camera", elements=CAMERA_ELEMENTS)
    agent, _, images, _ = make(tmp_path, ocr_words, None, [routine("none")], DONE, driver=driver)
    state = _TaskState(task="take a photo", cancel=threading.Event(), perms=TaskPermissions("auto"))
    agent._observe_settled(state)
    assert "state" not in images.calls
    # The viewfinder is a TextureView: a canvas class, but the camera app is never sparse.
    finder = CAMERA_ELEMENTS + [el(bounds=(0, 240, 1080, 1940), cls="TextureView")]
    assert faster.sparse_region(finder, (1080, 2400), "com.sec.android.app.camera") is None
    assert faster.sparse_region(finder, (1080, 2400), "com.example.game") is not None  # the same layout in a game


GMS = "com.google.android.gms"
SIGN_IN = [
    el(text="Sign in to Brick Drop", bounds=(60, 1700, 1020, 1780), cls="android.widget.TextView"),
    el(text="Jordan L", bounds=(200, 1820, 900, 1880), cls="android.widget.TextView"),
    el(text="jordan@mail.example.com", bounds=(200, 1880, 900, 1930), cls="android.widget.TextView"),
    el(text="Continue as Jordan", bounds=(60, 2000, 1020, 2120), cls="android.widget.Button"),
    el(text="Cancel", bounds=(60, 2150, 1020, 2250), cls="android.widget.Button"),
]


class SignInSheet(PhotoViewer):
    def __init__(self):
        super().__init__(package=GMS, elements=SIGN_IN)
        self.scenes = [((0, 0, 0), [], "dialog"), ((0, 0, 0), [], "content")]

    def tap(self, x, y):
        self.actions.append(("tap", x, y))
        self.at += 1
        self.package, self.elements = "com.example.game", []


def test_F1_an_account_sheet_over_a_game_is_not_sent_and_not_jev_tapped(tmp_path, ocr_words):
    driver = SignInSheet()
    box = (60 / 1080, 2000 / 2400, 1020 / 1080, 2120 / 2400)
    agent, _, images, _ = make(tmp_path, ocr_words, None, [routine("continue", box=box)], DONE, driver=driver)
    agent.run("start a new game")
    assert "state" not in [c if isinstance(c, str) else c[0] for c in images.calls[:1]]
    assert not any(r.get("source") == JEV_TAP_SOURCE for r in agent.io.steps)
    # The email and account words alone rule it out, whatever the app and whatever is under the play area.
    board = SIGN_IN + [el(bounds=(0, 0, 1080, 1690), cls="SurfaceView")]
    assert faster.sparse_region(board, (1080, 2400), "com.example.game") is None
    assert faster.sparse_region(board[:1] + board[3:], (1080, 2400), "com.example.game") is None  # "Continue as"


def test_F1_the_never_list_and_the_owner_categories():
    for package in ("com.google.android.GoogleCamera", "com.sec.android.gallery3d", "com.google.android.apps.photos",
                    "com.whatsapp", "com.google.android.apps.messaging", "com.google.android.gm",
                    "com.instagram.android", "com.google.android.gms", "com.android.contacts",
                    "com.google.android.apps.docs", "com.google.android.documentsui", "com.adobe.reader",
                    "com.sec.android.app.myfiles", None):
        assert faster.never_sparse(package), package
    for package in ("com.chess", "com.n3twork.tetris", "com.android.chrome", "com.supercell.clashofclans"):
        assert not faster.never_sparse(package), package
    # A messaging app the patterns don't name, but the owner's categories do.
    assert faster.never_sparse("org.example.discord", perm.DEFAULT_APP_CATEGORIES)


# --- F2: one-time codes split in groups, and in other languages ------------------------------------------------------

def _refusal(words):
    elements = [ocr(w, (0, 100 * i, 1000, 100 * i + 80)) for i, w in enumerate(words)]
    return faster.refusal("com.example.game", elements, blocked=lambda p: False, sensitive_apps=[], locked=False,
                          ocr_ran=True)


def test_F2_split_otp_formats_are_never_sent():
    for text in ("WhatsApp code: 482913", "WhatsApp code 123-456", "Your Google code is 482 913",
                 "Telegram code 48-29-13", "G-482913"):
        assert _refusal([text]) == faster.OTP_TEXT, text


def test_F2_code_words_in_other_languages():
    for text in ("Tu clave es 482913", "Tu código de verificación: 482 913", "Votre code de vérification : 482913",
                 "Ihr Bestätigungscode lautet 482913", "Seu código é 482-913", "Sua senha temporária 4829",
                 "Ваш код 482913"):
        assert _refusal([text]) == faster.OTP_TEXT, text


def test_F2_game_numbers_still_go():
    for text in ("Score 1200", "LEVEL 12", "Best 48 291", "Coins 3 450"):
        assert _refusal([text]) is None, text


# --- F3: canvas words: the control's row, a price just below, and no switch-off by a tiny label --------------------

def _canvas_obs(words, extra=()):
    buf = iolib.BytesIO()
    Image.new("RGB", (540, 1200), (20, 20, 120)).save(buf, "JPEG")
    shot = Screenshot(buf.getvalue(), 540, 1200, 1080, 2400)
    elements = [el(desc="Game view", bounds=(0, 0, 1080, 2400), cls="android.view.SurfaceView"), *extra]
    elements += [ocr(t, b) for t, b in words]
    return Observation(shot, elements, "com.example.game")


def test_F3_the_reach_numbers():
    # Mirrored by the phone's gate: keep them in step.
    assert (CANVAS_WORDS_DX, CANVAS_ROW_DY, CANVAS_PRICE_BELOW) == (0.12, 0.035, 0.10)


def test_F3_a_price_just_below_the_button_is_seen(tmp_path, ocr_words):
    agent, *_ = make(tmp_path, ocr_words, [((0, 0, 0), [], "menu")], [routine()], DONE)
    # "PLAY" at the tap; its price line 0.08 of the screen's height below (192 px on a 2400 px phone).
    obs = _canvas_obs([("PLAY", (440, 1100, 640, 1180)), ("Buy 500 gems $4.99", (380, 1180 + 192, 700, 1180 + 252))])
    near, _ = agent._canvas_point_words(obs, 540, 1140)
    assert "PLAY" in near and "$4.99" in near
    # Further below than the band, or a line below without a price: not this button's.
    obs = _canvas_obs([("PLAY", (440, 1100, 640, 1180)), ("Buy 500 gems $4.99", (380, 1180 + 300, 700, 1180 + 360)),
                       ("Settings", (380, 1300, 700, 1360))])
    near, _ = agent._canvas_point_words(obs, 540, 1140)
    assert near == "PLAY"


def test_F3_a_menu_rows_remove_ads_doesnt_make_play_ask(tmp_path, ocr_words):
    agent, *_ = make(tmp_path, ocr_words, [((0, 0, 0), [], "menu")], [routine()], DONE)
    # A typical menu row: [PLAY] ...... [REMOVE ADS], 0.28 of the width apart.
    obs = _canvas_obs([("PLAY", (300, 1100, 500, 1180)), ("REMOVE ADS", (700, 1100, 1000, 1180))])
    near, _ = agent._canvas_point_words(obs, 400, 1140)
    assert near == "PLAY" and not agent._keyword_hits(near)
    # The same row, tapped on REMOVE ADS: its own words.
    near, _ = agent._canvas_point_words(obs, 850, 1140)
    assert "REMOVE ADS" in near


def test_F3_a_tiny_accessibility_label_over_the_point_doesnt_turn_canvas_words_off(tmp_path, ocr_words):
    agent, *_ = make(tmp_path, ocr_words, [((0, 0, 0), [], "menu")], [routine()], DONE)
    lie = el(desc="Play", bounds=(500, 1120, 580, 1160), cls="android.view.View")  # aria-label "Play"
    obs = _canvas_obs([("Buy 500 gems $4.99", (380, 1100, 700, 1180))], extra=[lie])
    near, _ = agent._canvas_point_words(obs, 540, 1140)
    assert near == "Buy 500 gems $4.99"
    # A labeled node that says the drawn words over them (a real accessible web button) adds nothing of its own.
    real = el(text="Buy 500 gems $4.99", bounds=(370, 1095, 710, 1185), cls="android.widget.Button")
    near, _ = agent._canvas_point_words(_canvas_obs([("Buy 500 gems $4.99", (380, 1100, 700, 1180))], [real]),
                                        540, 1140)
    assert near == ""


def test_F3_a_native_labeled_control_still_skips_the_ocr(tmp_path, ocr_words, monkeypatch):
    agent, *_ = make(tmp_path, ocr_words, [((0, 0, 0), [], "menu")], [routine()], DONE)
    monkeypatch.setattr(Agent, "_ocr_near", staticmethod(lambda *a: (_ for _ in ()).throw(AssertionError("OCR"))))
    buf = iolib.BytesIO()
    Image.new("RGB", (540, 1200), "white").save(buf, "JPEG")
    shot = Screenshot(buf.getvalue(), 540, 1200, 1080, 2400)
    obs = Observation(shot, [el(text="Next", bounds=(400, 1100, 680, 1180), cls="android.widget.Button")], "com.x")
    assert agent._canvas_point_words(obs, 540, 1140) == ("", [])


# --- F4: an ad or a reward anywhere on the frame stops a Jev tap ------------------------------------------------------

WATCH_FAR = ((60, 60, 60), [("Level complete", (150, 300, 390, 340)), ("Continue", (230, 700, 310, 740)),
                            ("Watch an ad: 2x coins", (150, 1000, 390, 1040))], "game_over")
CONTINUE_BOX = (230 / 540, 700 / 1200, 310 / 540, 740 / 1200)


def test_F4_ad_and_reward_words_elsewhere_stop_a_jev_tap(tmp_path, ocr_words):
    agent, driver, _, _ = make(tmp_path, ocr_words, [WATCH_FAR, ((10, 160, 60), [], "content")],
                               [routine("continue", box=CONTINUE_BOX)], DONE)
    agent.run("keep playing")
    assert not [a for a in driver.actions if a[0] == "tap"]
    assert agent.io.steps[0]["jev_tap"]["skip"] == "screen_word:watch"


# --- F5: a Jev tap that leaves the game is a miss -----------------------------------------------------------------

class AdLeaves(Scenes):
    def tap(self, x, y):
        super().tap(x, y)
        self.package = "com.android.vending"
        self.elements = [el(text=f"Label {i}", bounds=(0, 100 * i, 1080, 100 * i + 90), cls="android.widget.TextView")
                         for i in range(20)]


def test_F5_leaving_the_game_is_a_miss(tmp_path, ocr_words):
    popup = ((200, 40, 40), [("Daily bonus", (150, 300, 390, 340)), ("X", (430, 300, 460, 330))], "dialog")
    driver = AdLeaves([popup])
    agent, _, _, _ = make(tmp_path, ocr_words, None, [routine("dismiss", box=(0.79, 0.25, 0.86, 0.28))], DONE,
                          driver=driver)
    result = agent.run("start a new game")
    rows = [r for r in agent.io.steps if r.get("source") == JEV_TAP_SOURCE]
    assert rows
    final = [r for r in agent.io.steps if r["idx"] == rows[0]["idx"]][-1]
    assert final["jev_tap"]["verify"] == "left_app"
    assert (result.faster or {}).get("jev_taps", 0) == 0
    note = str(agent.client.requests[0]["messages"])
    assert "it left com.example" in note and "changed as expected" not in note


# --- F7: canvas words keep the re-read after an earlier action in the same reply -----------------------------------

WEB = "com.android.chrome"
OLD = [el(text="Brick Drop", bounds=(0, 200, 1080, 2400), cls="android.webkit.WebView")]
NEW = OLD + [el(text="Buy 500 gems for $4.99", bounds=(300, 1080, 780, 1200), cls="android.widget.Button")]


def _agent(tmp_path, monkeypatch, canvas_words):
    monkeypatch.setattr("openmob.agent.loop.ocr.recognize_text",
                        lambda data, w, h, accurate=True: [TextBox("PLAY", 0.9, 100, 60, 170, 90)])
    driver = FakeDriver(packages=[WEB])
    driver.package = WEB
    driver.elements = list(NEW)  # what the phone shows NOW, after the reply's first action
    io = RecordingIO(["no"])  # the owner says no to anything asked
    agent = Agent(ScriptedClient([]), driver, AppResolver(driver, label_cache=tmp_path / "l.json"),
                  Config(settle_delay=0, gate_canvas_words=canvas_words), io, use_ocr=True)
    state = _TaskState(task="start the game", cancel=threading.Event(), perms=TaskPermissions("auto"))
    obs = Observation(driver.screenshot(), list(OLD), WEB)
    state.acted_on = obs  # an earlier action of the same model reply changed this screen
    return agent, driver, state, obs, io


def test_F7_with_canvas_words_the_replaced_button_asks(tmp_path, monkeypatch):
    agent, driver, state, obs, io = _agent(tmp_path, monkeypatch, canvas_words=True)
    out = agent._dispatch("tap", {"x": 270, "y": 570, "target": "Play"}, obs, state)
    assert ("tap", 540, 1140) not in driver.actions and out.is_error
    assert io.questions and "4.99" in io.questions[0]
    assert state.acted_on is obs  # unchanged: a later action still re-reads


def test_F7_without_canvas_words_the_fresh_screen_asks(tmp_path, monkeypatch):
    agent, driver, state, obs, io = _agent(tmp_path, monkeypatch, canvas_words=False)
    out = agent._dispatch("tap", {"x": 270, "y": 570, "target": "Play"}, obs, state)
    assert ("tap", 540, 1140) not in driver.actions and out.is_error


# --- F8: grants approved under the older warning count as off ------------------------------------------------------

def test_F8_the_warning_names_jev_taps_and_the_request_text():
    assert "tap a start, continue or close button" in perm.FASTER_WARNING
    assert "your request's text goes with the screenshot" in perm.FASTER_WARNING


def test_F8_an_older_faster_grant_or_drive_key_is_off():
    old = {**perm.default_settings(), "faster_mode": "phone", "faster_since": 1.0,
           "faster_grant": {"approval_id": "a", "scope": "phone", "signature": "s", "timestamp": 1},
           "faster_drive_keys": ["key_1"]}
    s = perm.normalize(old)
    assert s["faster_mode"] == "off" and s["faster_grant"] is None and s["faster_drive_keys"] == []
    new = {**old, "faster_grant": {**old["faster_grant"], "v": perm.FASTER_GRANT_VERSION},
           "faster_drive_v": perm.FASTER_GRANT_VERSION}
    s = perm.normalize(new)
    assert s["faster_mode"] == "phone" and s["faster_drive_keys"] == ["key_1"]
    # A drive key already listed under the old version is a loosening again (the phone must approve it).
    _, loosens = perm.apply_patch(old, {"faster_drive": {"key": "key_1", "name": "k", "on": True}}, {})
    assert loosens == ["faster_drive:k"]


# --- F9: the app read before a parallel capture; a canvas re-send compares the play area -----------------------------

class OrderDriver(FakeDriver):
    def __init__(self):
        super().__init__(packages=["com.example.game"])
        self.package = "com.example.game"
        self.calls = []

    def screenshot(self, max_age=0.0, attempts=2):
        self.calls.append("screenshot")
        return super().screenshot()

    def current_app(self):
        self.calls.append("current_app")
        return self.package


def test_F9_parallel_observe_reads_the_app_before_the_screenshot(tmp_path):
    driver = OrderDriver()
    agent = Agent(ScriptedClient([]), driver, AppResolver(driver, label_cache=tmp_path / "l.json"),
                  Config(settle_delay=0, parallel_observe=True), RecordingIO(), use_ocr=False)
    state = _TaskState(task="play", cancel=threading.Event(), perms=TaskPermissions("auto"))
    agent._observe_untimed(state, classify=False)
    assert driver.calls.index("current_app") < driver.calls.index("screenshot")


def _board(colour):
    img = Image.new("RGB", (540, 1200), (0, 0, 0))
    img.paste(Image.new("RGB", (540, 900), colour), (0, 150))
    buf = iolib.BytesIO()
    img.save(buf, "JPEG")
    return Screenshot(buf.getvalue(), 540, 1200, 1080, 2400)


def test_F9_a_canvas_resend_compares_the_play_area(tmp_path):
    driver = FakeDriver(packages=["com.example.game"])
    driver.package = "com.example.game"
    labels = [el(desc="Back", bounds=(0, 80, 160, 240))]
    driver.elements = list(labels)
    agent = Agent(ScriptedClient([]), driver, None, Config(), RecordingIO(), use_ocr=False)
    state = _TaskState(task="play", cancel=threading.Event(), perms=TaskPermissions("auto"))
    state.dispatch_obs = Observation(_board((200, 30, 30)), list(labels), "com.example.game")
    assert waiting.canvas_region(labels, (1080, 2400)) is not None
    driver.screenshot = lambda max_age=0.0, attempts=2: _board((200, 30, 30))
    assert agent._prompt_recheck(state) is None  # the same play area: re-send
    driver.screenshot = lambda max_age=0.0, attempts=2: _board((30, 200, 30))  # the drawn button changed
    assert agent._prompt_recheck(state) == "the screen changed"


# --- Hardening: the link step's ENTER only in the link's own app, into its search box -------------------------------

def test_the_link_enter_needs_the_apps_package_and_a_search_field(tmp_path):
    from test_app_links import LABELS as LABELS_FOR_AMAZON, OPENS as OPENS_FOR_AMAZON, Phone
    from test_app_links import make as make_link
    from test_fast_path import el as fel
    from conftest import tool_use

    amz = "com.amazon.mShop.android.shopping"
    done = [[tool_use("done", "z", summary="ok", success=True)]]
    # A focused box with the query, but not a search field (no search id or hint): nothing is pressed.
    box = fel(0, "usb-c cables", cls="android.widget.EditText", editable=True, focused=True)
    phone = Phone(opens={**OPENS_FOR_AMAZON, "https://www.amazon.com": amz}, packages=[*LABELS_FOR_AMAZON, amz],
                  elements=[box])
    _, driver, _, _, _ = make_link(done, "search Amazon for usb-c cables", driver=phone, tmp_path=tmp_path)
    assert ("key", "ENTER") not in driver.actions
    # The search box, but in another app in front: nothing is pressed.
    search = fel(0, "usb-c cables", cls="android.widget.EditText", editable=True, focused=True, hint="Search Amazon")
    phone = Phone(opens={**OPENS_FOR_AMAZON, "https://www.amazon.com": "com.example.other"},
                  packages=[*LABELS_FOR_AMAZON, amz, "com.example.other"], elements=[search])
    _, driver, _, _, _ = make_link(done, "search Amazon for usb-c cables", driver=phone, tmp_path=tmp_path)
    assert ("key", "ENTER") not in driver.actions
