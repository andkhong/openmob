"""Security review 2 (phone and gatekeeper, P2) of 2026-10-17: each proof of concept, now a test that fails to
reproduce. The decisions are also shared scenarios (tests/fixtures/gatekeeper/build.py, tagged review2_2026_10_17)
that the Kotlin gate runs too; these drive the reference engine (tests/gatekeeper_ref.py) the way the reviewer's
scripts did, and pin the server's mirrors (openmob/agent/gate.py, openmob/agent/sensitive.py)."""

import json
import random
import re
import time
from pathlib import Path

import pytest
from gatekeeper_ref import Gatekeeper, Rules, Screen, TapVerifier, find_sensitive, sensitive_in_url

from openmob.agent import gate, sensitive
from openmob.phone.adb import UIElement

ROOT = Path(__file__).parent.parent
SCREENS = json.loads((ROOT / "tests/fixtures/gatekeeper/screens.json").read_text())
SSN_LABEL = re.compile(Rules.load().d["sensitive_numbers"]["ssn_label"])
TASK = dict(task="t1", task_text="check my stuff")


def fixture(name, **extra):
    return Screen.of({**SCREENS[name], **extra})


def verdict(a):
    return a.decision, a.kind, a.rule, a.money


# --- H1: drags judged over every target under the start (poc_swipe_order.py, poc_swipe_fixtures.py) -------------------


def order_screen(label, scroll, order):
    btn = {"cls": "android.widget.Button", "text": label, "clickable": True, "bounds": [40, 2050, 1040, 2200]}
    body = {"cls": "androidx.core.widget.NestedScrollView", "bounds": [0, 200, 1080, 2400], "scroll": scroll,
            "children": [{"cls": "android.widget.TextView", "text": "Your basket: 2 items", "bounds": [0, 200, 1080, 400]}]}
    kids = [btn, body] if order == "button_first" else [body, btn]
    return Screen.of({"windows": [{"id": 1, "type": "application", "layer": 1, "package": "com.example.shop",
        "root": {"cls": "android.widget.FrameLayout", "bounds": [0, 0, 1080, 2400], "children": [
            {"cls": "android.widget.TextView", "text": "Total $49.99", "bounds": [0, 0, 1080, 200]}] + kids}}],
        "labels": {"com.example.shop": "Shop"}, "canvas_ocr": []})


@pytest.mark.parametrize("order", ["button_first", "body_first"])
@pytest.mark.parametrize("scroll", [["down", "up"], []])
@pytest.mark.parametrize("label", ["Place order", "Send", "Delete account"])
def test_h1_a_drag_inside_a_button_before_a_scrolling_layer_asks_as_the_tap(label, scroll, order):
    """poc_swipe_order.py: the PoC got allow for the button-first order (the hit path ends in the body)."""
    s = order_screen(label, scroll, order)
    tap = Gatekeeper().admit("tap", {"x": 540, "y": 2120, **TASK}, s)
    g = Gatekeeper()
    drag = g.admit("swipe", {"x1": 540, "y1": 2170, "x2": 540, "y2": 2070, "duration_ms": 200, "mode": "ask", **TASK}, s)
    assert tap.decision == "ask" and verdict(drag) == verdict(tap)


LAYERED = [("hit_buy_layered", 540, 1700, 1740), ("hit_place_order_layered", 540, 1640, 1700),
           ("hit_send_toolbar", 980, 2290, 2210), ("hit_delete_layered", 900, 2260, 2140),
           ("hit_settings_layered", 540, 450, 510), ("dialer_google_layered", 540, 2200, 2280)]


@pytest.mark.parametrize("mode", [None, "ask"])
@pytest.mark.parametrize("name,x,ya,yb", LAYERED)
def test_h1_drags_on_the_layered_fixtures_ask_as_the_tap(name, x, ya, yb, mode):
    """poc_swipe_fixtures.py (and the dialer from the report's table): every one was allow."""
    s = fixture(name)
    extra = {"mode": mode} if mode else {}
    tap = Gatekeeper().admit("tap", {"x": x, "y": (ya + yb) / 2, **TASK, **extra}, s)
    drag = Gatekeeper().admit("swipe", {"x1": x, "y1": ya, "x2": x, "y2": yb, "duration_ms": 200, **TASK, **extra}, s)
    assert tap.decision == "ask" and verdict(drag) == verdict(tap)


def test_h1_a_real_scroll_on_the_layer_itself_is_still_a_scroll():
    """A scrollable sibling layer doesn't take a drag on a control outside it, but a scroll that starts on it scrolls."""
    s = fixture("r2_place_order_scrolling_layer")
    assert Gatekeeper().admit("swipe", {"x1": 540, "y1": 1500, "x2": 540, "y2": 600, "duration_ms": 300, **TASK},
                              s).decision == "allow"
    assert Gatekeeper().admit("swipe", {"x1": 540, "y1": 2170, "x2": 540, "y2": 2070, "duration_ms": 200, **TASK},
                              s).decision == "ask"


# --- M1: a drag past the slop keeps every rule (poc_swipe_slop.py) ------------------------------------------------------

SLOP = [("permission_dialog_other", 540, 1550, 1626, dict(task="t1", task_text="play chess")),
        ("settings_dev", 400, 480, 566, {}),
        ("hit_install_layered", 540, 860, 946, dict(task="t1", task_text="check the weather")),
        ("dialer_google", 540, 2040, 2176, {}),
        ("share_sheet", 170, 1550, 1726, dict(task="t1", task_text="look at photos")),
        ("uninstall_chess", 900, 1380, 1476, dict(task="t1", task_text="play chess"))]


@pytest.mark.parametrize("past", [22, 26, 60, 400])
@pytest.mark.parametrize("name,x,y1,y2,p", SLOP)
def test_m1_a_drag_that_leaves_the_control_is_at_least_as_strict_as_the_tap(name, x, y1, y2, p, past):
    """The PoC: allow at 26 px past the edge (and refuse turned into allow for Settings)."""
    s = fixture(name)
    tap = Gatekeeper().admit("tap", {"x": x, "y": y1, **p}, s)
    end = y2 - 26 + past
    drag = Gatekeeper().admit("swipe", {"x1": x, "y1": y1, "x2": x, "y2": end, "duration_ms": 200, **p}, s)
    assert tap.decision in ("ask", "refuse") and verdict(drag) == verdict(tap), (name, past)


def test_m1_the_phones_touch_slop_counts_when_larger():
    """The mirror takes the phone's slop (Screen.touch_slop): a 55 px drag is a tap at 30 px, a scroll at 24 px."""
    p = {"x1": 540, "y1": 1100, "x2": 540, "y2": 1045, "duration_ms": 200, "task": "t1", "task_text": "read my mail"}
    assert Gatekeeper().admit("swipe", p, fixture("h1_send_in_list_at_top")).decision == "allow"
    assert Gatekeeper().admit("swipe", p, fixture("h1_send_in_list_at_top", touch_slop=30)).decision == "ask"
    assert Gatekeeper().slop(fixture("h1_send_in_list_at_top", touch_slop=12)) == 24  # rules.json's 24 px is a floor


def test_m1_the_server_mirror_takes_the_slop_as_a_parameter():
    button = UIElement(0, "Send", "", "", "Button", True, None, (100, 1000, 980, 1144))
    assert not gate.swipe_is_tap([button], 540, 1100, 540, 940, 200)  # 160 px, ending 60 px off: a drag at 24 px
    assert gate.swipe_is_tap([button], 540, 1100, 540, 940, 200, slop=90)  # within 2 x 90 px: a tap
    assert gate.swipe_is_tap([button], 540, 1100, 540, 940, 200, slop=12) is False  # 24 px is the floor
    assert gate.swipe_is_tap([button], 540, 1100, 540, 1172, 300, slop=30)  # ends within 30 px of the button
    assert not gate.swipe_is_tap([button], 540, 1100, 540, 1172, 300)


# --- M2: the server's task id never names the app (poc_install_taskid.py) -----------------------------------------------


@pytest.mark.parametrize("task_id", ["t1", "t1-torchlight", "torchlight"])
def test_m2_a_task_id_naming_the_app_doesnt_make_the_install_run(task_id):
    g = Gatekeeper()
    a = g.request_task({"task": task_id, "text": "check the weather"})
    assert a.decision == "ask"
    m = g.approval_message(a.approval_id)
    assert g.approve(a.approval_id, m, TapVerifier.sign(m))
    g.clock.elapsed += 10_000
    g.clock.wall += 10_000
    adm = g.admit("tap", {"x": 540, "y": 860, "task": task_id, "task_text": "check the weather"},
                  fixture("hit_install_layered"))
    assert (adm.decision, adm.rule) == ("ask", "risk:install:unnamed")


def test_m2_the_attested_text_still_names_the_app():
    g = Gatekeeper()
    g.note_instruction("install the torchlight app")
    adm = g.admit("tap", {"x": 540, "y": 860, "task": "t9", "task_text": "install the torchlight app"},
                  fixture("hit_install_layered"))
    assert adm.decision == "allow"


# --- M3: drawn spots ---------------------------------------------------------------------------------------------------


def canvas(drawn, cls="android.view.SurfaceView", extra=(), pkg="com.example.brickdrop"):
    return Screen.of({"windows": [{"id": 1, "type": "application", "layer": 1, "package": pkg,
        "root": {"cls": "android.widget.FrameLayout", "bounds": [0, 0, 1080, 2400],
                 "children": [{"cls": cls, "bounds": [0, 0, 1080, 2400]}] + list(extra)}}],
        "labels": {pkg: "Brick Drop"}, "canvas_ocr": drawn})


def line(text, box):
    return {"text": text, "bounds": list(box), "conf": 0.9}


@pytest.mark.parametrize("text,decision,kind", [
    ("PLAY", "allow", ""), ("Buy 500 gems $4.99", "ask", "pay"), ("Delete save", "ask", "delete"),
    ("Send gift", "ask", "send"), ("Transfer", "ask", "pay"), ("CONTINUE", "allow", "")])
def test_m3_drawn_words_at_the_point_are_judged_as_its_label(text, decision, kind):
    s = canvas([line(text, (380, 1100, 700, 1180))])
    a = Gatekeeper().admit("tap", {"x": 540, "y": 1140}, s)
    assert (a.decision, a.kind) == (decision, kind)


def test_m3_an_unread_canvas_asks_and_an_empty_read_doesnt():
    assert Gatekeeper().admit("tap", {"x": 540, "y": 1140}, canvas(None)).rule == "risk:canvas_unread"
    assert Gatekeeper().admit("tap", {"x": 540, "y": 1140}, canvas([])).decision == "allow"


def test_m3_the_reach_is_the_row_and_a_price_just_below():
    """S2 F3's numbers on the phone: about one row up and down, 0.12 of the width each side, a price within 0.1 of
    the height below. A price 0.08 of the height below is seen; a neighbour 0.2 of the width away isn't."""
    below = canvas([line("UNLOCK", (440, 1100, 640, 1180)), line("$4.99", (470, 1180 + 192, 610, 1180 + 252))])
    assert Gatekeeper().admit("tap", {"x": 540, "y": 1140}, below).kind == "pay"
    side = canvas([line("PLAY", (300, 1100, 500, 1180)), line("REMOVE ADS", (720, 1100, 1000, 1180))])
    assert Gatekeeper().admit("tap", {"x": 400, "y": 1140}, side).decision == "allow"
    far = canvas([line("PLAY", (440, 1100, 640, 1180)), line("Delete save", (440, 1500, 680, 1560))])
    assert Gatekeeper().admit("tap", {"x": 540, "y": 1140}, far).decision == "allow"


def test_m3_a_tiny_label_over_a_drawn_view_cant_vouch_for_it():
    """S2 F3's lie (<button aria-label="Play"> over a drawn "Buy 500 gems $4.99"), on the phone."""
    tiny = {"cls": "android.view.View", "desc": "Play", "clickable": True, "bounds": [500, 1120, 580, 1160]}
    s = canvas([line("Buy 500 gems $4.99", (380, 1100, 700, 1180))], cls="android.view.View", extra=[tiny])
    g = Gatekeeper()
    assert g.canvas_spot(s, 540, 1140)
    assert g.admit("tap", {"x": 540, "y": 1140}, s).kind == "pay"
    big = dict(tiny, bounds=[100, 1000, 980, 1300])  # a real, full-size labeled button: the label is the target
    assert not g.canvas_spot(canvas([], cls="android.view.View", extra=[big]), 540, 1140)


def test_m3_a_swapped_drawn_button_is_refused_at_the_recheck():
    g = Gatekeeper()
    a = g.admit("tap", {"x": 540, "y": 1140}, canvas([line("PLAY", (440, 1100, 640, 1180))]))
    assert a.decision == "allow"
    again = g.reverify(a, canvas([line("Buy 500 gems $4.99", (380, 1100, 700, 1180))]))
    assert (again.decision, again.rule) == ("refuse", "builtin:toctou")


def test_m3_an_approval_binds_the_drawn_words():
    from gatekeeper_ref import binding  # noqa: F401  (the binding includes the drawn words through strict_fp)
    g = Gatekeeper()
    j1 = g.judge("tap", {"x": 540, "y": 1140}, canvas([line("Buy 500 gems $4.99", (380, 1100, 700, 1180))]))
    j2 = g.judge("tap", {"x": 540, "y": 1140}, canvas([line("Buy 900 gems $9.99", (380, 1100, 700, 1180))]))
    assert j1.money_fp != j2.money_fp and "drawn:" in j1.strict_fp


def test_m3_a_scroll_from_an_unlabeled_spot_in_an_ordinary_app_isnt_a_press():
    s = Screen.of({**SCREENS["amazon_product"], "canvas_ocr": None})
    assert Gatekeeper().admit("swipe", {"x1": 540, "y1": 2200, "x2": 540, "y2": 700, "duration_ms": 300},
                              s).decision == "allow"


# --- L2: typing judged as the phone inserts it (poc_typing_cursor.py) ---------------------------------------------------


def notes(text, sel=(-1, -1)):
    return Screen.of({"windows": [{"id": 1, "type": "application", "layer": 1, "package": "com.example.notes",
        "root": {"cls": "android.widget.FrameLayout", "bounds": [0, 0, 1080, 2400], "children": [
            {"text": text, "id": "com.example.notes:id/body", "cls": "android.widget.EditText", "editable": True,
             "focused": True, "bounds": [0, 200, 1080, 400], "sel_start": sel[0], "sel_end": sel[1]}]}}],
        "labels": {}, "canvas_ocr": []})


def test_l2_the_tail_then_the_head_at_the_cursor_asks():
    P = dict(task="t1", task_text="write a note")
    assert Gatekeeper().admit("type_text", {"text": "1111", **P}, notes("")).decision == "allow"
    a = Gatekeeper().admit("type_text", {"text": "4111 1111 1111 ", **P}, notes("1111", (0, 0)))
    assert (a.decision, a.kind) == ("ask", "sensitive_number")
    # Over a selection: "4111 1111 XXXX 1111" with XXXX selected, typed "1111".
    a = Gatekeeper().admit("type_text", {"text": "1111", **P}, notes("4111 1111 XXXX 1111", (10, 14)))
    assert a.kind == "sensitive_number"


def test_l2_a_second_number_in_a_field_that_holds_one_asks():
    P = dict(task="t1", task_text="write a note")
    owner = "Card 4111 1111 1111 1111 and "
    a = Gatekeeper().admit("type_text", {"text": "5555 5555 5555 4444", **P}, notes(owner, (len(owner), len(owner))))
    assert a.kind == "sensitive_number"
    assert Gatekeeper().admit("type_text", {"text": " thanks", **P}, notes(owner)).decision == "allow"


# --- L3: strict numbers and flags ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("params", [
    {"x1": 540, "y1": 2075, "x2": 540, "y2": 1500, "duration_ms": "NaN"},
    {"x1": 540, "y1": 2075, "x2": 540, "y2": 1500, "duration_ms": float("nan")},
    {"x1": 540, "y1": 2075, "x2": 540, "y2": 1500, "duration_ms": float("inf")},
    {"x1": 540, "y1": 2075, "x2": 540, "y2": 1500, "duration_ms": -1},
    {"x1": "540", "y1": 2075, "x2": 540, "y2": 1500, "duration_ms": 300},
    {"x1": True, "y1": 2075, "x2": 540, "y2": 1500, "duration_ms": 300}])
def test_l3_a_swipe_with_a_bad_number_is_refused(params):
    """The PoC: "NaN" was neither under tap_ms nor over max_ms to the gate, and 0 (a 1 ms stroke) to the phone."""
    a = Gatekeeper().admit("swipe", params, fixture("dialer_google"))
    assert (a.decision, a.code, a.rule) == ("refuse", "gate_bad_params", "builtin:bad_params")


def test_l3_a_string_flag_is_refused_and_real_values_pass():
    a = Gatekeeper().admit("type_text", {"text": "hi", "replace": "true"}, fixture("m4_notes_empty"))
    assert a.code == "gate_bad_params"
    assert Gatekeeper().admit("type_text", {"text": "hi", "replace": True}, fixture("m4_notes_empty")).decision == "allow"
    assert Gatekeeper().admit("swipe", {"x1": 540.0, "y1": 2075, "x2": 540, "y2": 1500, "duration_ms": 100},
                              fixture("dialer_google")).decision == "ask"


# --- L4: the detector's separators (poc_detector.py) --------------------------------------------------------------------

CARD = "4111111111111111"
GROUPS = [CARD[i:i + 4] for i in range(0, 16, 4)]
SEPARATORS = {"tab": "\t", "newline": "\n", "comma": ",", "colon": ":", "space-dash-space": " - ",
              "comma-space": ", ", "zero-width space": "​", "word joiner": "⁠", "NBSP": " ",
              "ideographic space": "　", "soft hyphen": "­"}


@pytest.mark.parametrize("sep", list(SEPARATORS))
def test_l4_cards_split_by_any_separator_are_caught_on_both_sides(sep):
    text = SEPARATORS[sep].join(GROUPS)
    assert find_sensitive(text) == "card"
    assert sensitive.find(text) == "card"
    assert "4111" not in sensitive.redact(f"pay {text} now") and "1111" not in sensitive.redact(f"pay {text} now")


@pytest.mark.parametrize("text", ["+" + " ".join(GROUPS), "+" + CARD, "+" + "-".join(GROUPS)])
def test_l4_a_plus_prefix_doesnt_hide_a_card(text):
    assert find_sensitive(text) == "card" and sensitive.find(text) == "card"


@pytest.mark.parametrize("text", ["123\t45\t6789", "123 - 45 - 6789", "123​45​6789", "SSN:123-45-6789"])
def test_l4_ssns_with_the_new_separators(text):
    assert find_sensitive(text) == "ssn" and sensitive.find(text) == "ssn"


def test_l4_links_with_the_new_separators():
    for url in ["https://x.example/?c=4111%091111%091111%091111", "https://x.example/#4111,1111,1111,1111",
                "https://x.example/?c=4111%3A1111%3A1111%3A1111"]:
        assert sensitive_in_url(url, SSN_LABEL) == "card" and sensitive.in_url(url) == "card"


def test_l4_no_redos():
    for s in (("1 " * 200_000) + "x", "1" + " " * 200_000 + "x", ("1" + " - " * 3) * 50_000, ("1,​" * 100_000)):
        t0 = time.monotonic()
        find_sensitive(s)
        sensitive.find(s)
        assert time.monotonic() - t0 < 2.0


def test_l4_the_new_separators_add_no_false_positives():
    """Ordinary numbers written with the separators the detector now reads (tabs, newlines, commas, colons, " - ",
    invisible characters, a "+" prefix): none counts. A generated set (24,000 samples), not a measurement of real use."""
    rng = random.Random(1017)
    samples = []
    for _ in range(2000):
        h, m, s = rng.randint(0, 23), rng.randint(0, 59), rng.randint(0, 59)
        y, mo, d = rng.randint(1990, 2030), rng.randint(1, 12), rng.randint(1, 28)
        samples += [
            f"{h:02d}:{m:02d}:{s:02d}", f"{h}:{m:02d} - {rng.randint(0, 23)}:{m:02d}",
            f"{rng.randint(1, 999)},{rng.randint(0, 999):03d},{rng.randint(0, 999):03d}",
            f"{rng.uniform(-90, 90):.4f}, {rng.uniform(-180, 180):.4f}",
            # A table row after its label. (Known residuals, as with spaces before: a row that is only 4-digit
            # numbers can pass Luhn, and 3, 2 and 4 digits in a row read as an SSN.)
            f"Row {rng.randint(1, 99)}:\t" + "\t".join(str(rng.randint(1000, 99999)) for _ in range(rng.randint(2, 6))),
            "\n".join(f"{rng.randint(1, 99)} x {rng.randint(1, 9999)}" for _ in range(3)),
            f"+{rng.randint(1, 99)} {rng.randint(100, 999)} {rng.randint(1000000, 9999999)}",
            f"+{rng.randint(10, 99)}{rng.randint(10**9, 10**12)}",  # E.164: at most 15 digits
            f"{y}-{mo:02d}-{d:02d} - {y}-{mo:02d}-{rng.randint(1, 28):02d}",
            f"Order #{rng.randint(1000, 9999)}, {rng.randint(1, 9)} items, ${rng.randint(1, 999)}.{rng.randint(0, 99):02d}",
            f"{rng.randint(1000, 9999)}​{rng.randint(100, 999)}",
            f"Score {rng.randint(0, 99999)}: level {rng.randint(1, 99)}, {rng.randint(0, 999)} coins"]
    hits = [t for t in samples if sensitive.find(t) or find_sensitive(t)]
    assert len(samples) == 24000 and hits == [], hits[:10]


# --- I-3: on a tie, the prompt names the labeled target -----------------------------------------------------------------


def test_i3_a_tie_prefers_the_labeled_target():
    a = Gatekeeper().admit("tap", {"x": 540, "y": 2120, **TASK}, fixture("r2_tie_send_over_unlabeled"))
    assert (a.decision, a.rule) == ("ask", "risk:words:send") and "Send" in a.wording
