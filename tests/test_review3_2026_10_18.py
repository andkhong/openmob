"""Security review 3 (2026-10-18), reviewer F's two Medium findings, from their PoCs (poc_sparse_apps.py,
poc_install_names.py): the fixed behaviour.

F3-M1 (owner: "games only"): a Faster mode sparse screen must be a game's; non-game canvases never are.
F3-M2 and L2 (owner: "intent + name"): a free install goes unasked only when the request asks for an install and
names the app. The phone-side half of F3-M2 is in tests/fixtures/gatekeeper/build.py (tag review3), run by both the
reference engine here and the phone's JUnit."""
import json
from pathlib import Path

import pytest

from gatekeeper_ref import Gatekeeper
from openmob import permissions as perm
from openmob.agent import faster, gate
from openmob.config import Config
from openmob.phone.adb import UIElement

RULES = Path(__file__).resolve().parents[1] / "android/app/src/main/resources/gatekeeper/rules.json"
W, H = 1080, 2400


# --- F3-M1: only games are sparse ---------------------------------------------------------------------------------

def _screen(view_cls, labels):
    els = [UIElement(0, "", "", "", view_cls, False, None, (0, 200, W, 2100))]
    for i, (t, b) in enumerate(labels, 1):
        els.append(UIElement(i, t, "", "", "android.widget.Button", True, None, b))
    return els


TOP = [("Back", (0, 60, 150, 190)), ("Share", (900, 60, 1080, 190))]
BOTTOM = [("Mute", (100, 2150, 300, 2350)), ("End call", (440, 2150, 640, 2350)),
          ("Camera", (780, 2150, 980, 2350))]
NOT_GAMES = [
    ("com.google.android.apps.tachyon", "android.view.TextureView", BOTTOM),  # Meet (Duo) video call
    ("us.zoom.videomeetings", "android.view.SurfaceView", BOTTOM),
    ("com.niksoftware.snapseed", "android.opengl.GLSurfaceView", TOP),
    ("com.adobe.lrmobile", "android.view.TextureView", TOP),
    ("com.vsco.cam", "android.view.TextureView", TOP),
    ("com.google.android.keep", "android.view.View", TOP),
    ("com.samsung.android.app.notes", "android.view.SurfaceView", TOP),
    ("com.android.chrome", "android.webkit.WebView", TOP),
    ("com.sec.android.app.sbrowser", "android.webkit.WebView", TOP),
    ("com.google.ar.lens", "android.view.TextureView", TOP),
    ("com.netflix.mediaclient", "android.view.SurfaceView", TOP),
    ("com.google.android.apps.photos", "android.view.TextureView", TOP),
    ("com.whatsapp", "android.view.SurfaceView", BOTTOM),
    ("com.example.viewer", "io.flutter.embedding.android.FlutterSurfaceView", TOP),  # Flutter isn't a game engine
]


@pytest.mark.parametrize("package,cls,labels", NOT_GAMES)
def test_f3_m1_non_game_canvases_are_never_sparse(package, cls, labels):
    elements = _screen(cls, labels)
    assert faster.sparse_region(elements, (W, H), package, Config().app_categories) is None, package
    assert not faster.eligible(elements, (W, H), package, Config().app_categories), package
    assert faster.eligible([], (W, H), package)  # a treeless screen is unchanged: eligible as before


@pytest.mark.parametrize("package", ["com.n3twork.tetris", "com.chess", "com.example.canvasgame",
                                     "com.supercell.clashofclans", "com.king.candycrushsaga", "com.ea.games.scrabble"])
def test_f3_m1_game_apps_stay_sparse(package):
    assert faster.game_app(package)
    assert faster.sparse_region(_screen("android.view.SurfaceView", TOP), (W, H), package) is not None


@pytest.mark.parametrize("cls", ["com.unity3d.player.UnityPlayer", "com.epicgames.unreal.GameActivity$UnrealView",
                                 "org.godotengine.godot.GodotView", "org.cocos2dx.lib.Cocos2dxGLSurfaceView"])
def test_f3_m1_a_game_engines_view_makes_any_package_a_game(cls):
    assert faster.sparse_region(_screen(cls, TOP), (W, H), "com.example.puzzler") is not None
    # ...but only over the play area: a small one in a corner doesn't.
    small = _screen("android.view.SurfaceView", TOP) + [UIElement(9, "", "", "", cls, False, None, (0, 2100, 200, 2140))]
    assert faster.sparse_region(small, (W, H), "com.example.puzzler") is None


def test_f3_m1_the_owners_games_category_names_more_games_and_the_never_list_still_wins():
    cats = {**perm.DEFAULT_APP_CATEGORIES, "games": ["puzzler"]}
    assert faster.sparse_region(_screen("android.view.SurfaceView", TOP), (W, H), "com.example.puzzler") is None
    assert faster.sparse_region(_screen("android.view.SurfaceView", TOP), (W, H), "com.example.puzzler", cats)
    # A "game" package the never list names (an account sheet) is still never sparse.
    assert faster.sparse_region(_screen("android.view.SurfaceView", TOP), (W, H), "com.google.android.gms.games") is None


# --- F3-M2: install intent + the app's name -------------------------------------------------------------------------

UNNAMED = [("play some music", "Music Player - MP3 Pro"), ("send a photo to mom", "Photo Editor: AI Filters"),
           ("check the weather", "Weather Live: Radar & Casino"), ("what time is my flight", "Flight Tracker Casino"),
           ("set a timer for my pizza", "Pizza Ready! Slots"), ("call my bank", "Bank Robbery Simulator"),
           ("read my email", "Email Cleaner VPN"), ("open my calendar", "Calendar Planner 2027"),
           ("install chess", "Chess Casino Slots"), ("look at photos", "Photos Lock Vault"),
           ("open spotify", "Spotify: Music and Podcasts"), ("install the weather app", "Weather Live: Radar & Casino"),
           ("get directions to the chess club", "Chess - Play and Learn"), ("download it", "Free App"),
           ("install a music app", "Spotify: Music and Podcasts"), ("install whatsapp", "WhatsApp Business Casino")]
NAMED = [("install Spotify", "Spotify: Music and Podcasts"), ("download WhatsApp", "WhatsApp Messenger"),
         ("install chess and play 5 moves against a bot", "Chess - Play and Learn"),
         ("get the Torchlight flashlight", "Torchlight: Flashlight Pro"), ("install tap titans", "Tap Titans 2: Clicker RPG"),
         ("set up whatsapp messenger", "WhatsApp Messenger"), ("get the spotify app", "Spotify: Music and Podcasts"),
         ("add chess.com from the play store", "Chess.com - Play & Learn")]


@pytest.mark.parametrize("request_text,title", UNNAMED)
def test_f3_m2_a_shared_word_without_install_intent_and_the_name_names_nothing(request_text, title):
    assert not gate.names_app(request_text, title)
    assert not Gatekeeper().names_app(request_text, title)


@pytest.mark.parametrize("request_text,title", NAMED)
def test_f3_m2_an_install_request_naming_the_app_still_names_it(request_text, title):
    assert gate.names_app(request_text, title)
    assert Gatekeeper().names_app(request_text, title)


def test_f3_m2_the_servers_intent_rules_match_the_phones():
    install = json.loads(RULES.read_text())["install"]
    assert gate._INSTALL_INTENT.pattern == install["intent"]
    assert gate._INTENT_VERBS == set(install["intent_verbs"]) and gate._INTENT_SKIP == set(install["intent_skip"])
    assert gate._INTENT_NOUNS == set(install["intent_nouns"]) and gate._GENERIC == set(install["generic"])
