from pathlib import Path

from conftest import make_png

from openmob.phone.adb import PhoneDriver, Screenshot, format_elements, parse_ui_xml

FIXTURE = Path(__file__).parent / "fixtures" / "settings_ui.xml"


def test_parse_ui_xml_keeps_labelled_and_clickable_nodes():
    elements = parse_ui_xml("UI hierchary dumped\n" + FIXTURE.read_text())
    assert [e.label for e in elements] == ["Settings", "Search settings", "Dark theme"]
    search = elements[1]
    assert search.clickable and search.resource_id == "search"
    assert search.center == (966, 266)
    assert elements[2].checked is False


def test_autocomplete_fields_are_text_fields():
    """Samsung Calendar's event title and location are AutoCompleteTextViews (2026-10-27): over adb they were not text
    fields, so a form of them got one action a turn and typing checks didn't see them as fields."""
    from openmob.agent import fast

    node = ('<node index="{i}" text="{t}" resource-id="app:id/{t}" class="android.widget.{c}" clickable="true" '
            'focused="{f}" password="false" bounds="[0,{y}][1000,{y2}]" />')
    xml = "<hierarchy>" + "".join(node.format(i=i, t=t, c=c, f=f, y=200 * i, y2=200 * i + 100) for i, (t, c, f) in
                                  enumerate([("Title", "AutoCompleteTextView", "true"),
                                             ("Location", "MultiAutoCompleteTextView", "false"),
                                             ("Search", "SearchView$SearchAutoComplete", "false"),
                                             ("Notes", "EditText", "false"),
                                             ("Label", "TextView", "false")])) + "</hierarchy>"
    elements = parse_ui_xml(xml)
    assert [e.editable for e in elements] == [True, True, True, True, False]
    assert [e.focused for e in elements] == [True, False, False, False, False]
    assert fast.is_form(elements)


def test_parse_ui_xml_handles_garbage():
    assert parse_ui_xml("ERROR: could not get idle state.") == []
    assert parse_ui_xml("") == []


def test_format_elements_uses_screenshot_coordinates():
    shot = Screenshot(b"", 540, 1200, 1080, 2400)
    text = format_elements(parse_ui_xml(FIXTURE.read_text()), shot)
    assert "[1] ImageButton desc='Search settings' id=search @ (483,133)" in text
    assert "unchecked" in text
    assert "(not clickable)" in text.splitlines()[0]


def test_screenshot_coordinate_mapping_round_trips_and_clamps():
    shot = Screenshot(b"", 576, 1280, 1080, 2400)
    assert shot.to_device(288, 640) == (540, 1200)
    assert shot.to_device(-5, 99999) == (0, 2399)
    assert shot.to_image(540, 1200) == (288, 640)


class RecordingDriver(PhoneDriver):
    def __init__(self, outputs=None, **kw):
        super().__init__(**kw)
        self.calls = []
        self.outputs = outputs or {}

    def _exec(self, args, timeout=30, device=True):
        self.calls.append(args)
        for key, value in self.outputs.items():
            if key in " ".join(args):
                return value
        return b""


def test_screenshot_is_downscaled_to_max_side():
    driver = RecordingDriver({"screencap": make_png(1080, 2400)}, max_side=1280)
    shot = driver.screenshot()
    assert (shot.width, shot.height) == (576, 1280)
    assert (shot.device_width, shot.device_height) == (1080, 2400)
    assert shot.jpeg[:2] == b"\xff\xd8"


def test_preview_frames_are_small_and_never_given_to_the_agent():
    driver = RecordingDriver({"screencap": make_png(1080, 2400)}, max_side=1280)
    taken, preview = driver.preview(720, 55)
    assert (preview.width, preview.height) == (324, 720)
    assert driver.preview(720, 55, max_age=60, newer_than=0)[1] is preview  # shared between viewers
    assert driver.preview(720, 55, max_age=60, newer_than=taken)[1] is not preview  # but a viewer wants newer
    shot = driver.screenshot(max_age=60)  # the agent: a fresh full-size capture, not the cached preview
    assert (shot.width, shot.height) == (576, 1280)
    assert driver.preview(720, 55, max_age=60, newer_than=taken)[1] is shot  # the live view may reuse it


def test_landscape_screenshot_keeps_orientation():
    driver = RecordingDriver({"screencap": make_png(2400, 1080)}, max_side=1280)
    shot = driver.screenshot()
    assert (shot.width, shot.height) == (1280, 576)


def test_type_text_escapes_spaces_and_shell_characters():
    driver = RecordingDriver()
    driver.type_text("it's a test")
    assert driver.calls[-1] == ["shell", "input text 'it'\"'\"'s%sa%stest'"]


def test_current_app_parses_dumpsys():
    out = b"  mCurrentFocus=Window{1a2b u0 com.netease.wwm/com.netease.MainActivity}\n"
    driver = RecordingDriver({"dumpsys": out})
    assert driver.current_app() == "com.netease.wwm"


def test_launchable_packages_from_query_activities():
    out = b"com.android.settings/.Settings\ncom.netease.wwm/.Main\ncom.netease.wwm/.Other\n"
    driver = RecordingDriver({"query-activities": out})
    assert driver.launchable_packages() == ["com.android.settings", "com.netease.wwm"]
