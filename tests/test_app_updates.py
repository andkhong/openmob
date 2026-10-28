"""App updates (docs/phone-protocol.md §3.7): the server reads the served APK's versionCode, tells each phone in its
welcome what is newest and what is required, and refuses tasks (app_update_required) to a phone below
min_app_version while it stays connected: Stop, answers and Disconnect still work."""
import time

import pytest
from test_api_v1 import api  # noqa: F401  (a fixture)
from test_orchestrator import B, orc, start, step, wait_status  # noqa: F401  (orc: a fixture)
from test_release_apk_check import CLEAN, axml, make_apk, pin_fake_signer  # noqa: F401 (autouse)
from test_remote import FakePhone, new_signer, wait_for

from openmob import server
from openmob.apk_check import ATTR_VERSION_CODE, check_apk, manifest_version_code, version_code
from openmob.config import load_config
from openmob.runner import UPDATE_REQUIRED, Coordinator
from openmob.voice.tts import Speaker

INT_DEC, INT_HEX = 0x10, 0x11


def manifest(code=52, by_name=False, dtype=INT_DEC):
    """A binary manifest with android:versionCode on <manifest>, found by its resource id (or by name only)."""
    attrs = [("versionCode", None if by_name else ATTR_VERSION_CODE, dtype, code)]
    return axml(app_attrs=CLEAN, manifest_attrs=attrs)


# --- reading the versionCode ------------------------------------------------------------------

def test_the_version_code_is_read_by_resource_id_by_name_and_in_hex():
    assert manifest_version_code(manifest(52)) == 52
    assert manifest_version_code(manifest(7, by_name=True)) == 7
    assert manifest_version_code(manifest(0x40, dtype=INT_HEX)) == 0x40


def test_no_version_code_or_one_that_isnt_a_number_is_none(tmp_path):
    assert manifest_version_code(axml(app_attrs=CLEAN)) is None
    assert manifest_version_code(manifest(0x7F050001, dtype=0x01)) is None  # a resource reference
    junk = tmp_path / "junk.apk"
    junk.write_bytes(b"not a zip")
    assert version_code(junk) is None
    assert version_code(tmp_path / "missing.apk") is None


def test_the_release_check_still_passes_with_a_version_code(tmp_path):
    apk = make_apk(tmp_path / "ok.apk", manifest(52))
    assert check_apk(apk).ok and version_code(apk) == 52


def test_the_served_apks_code_is_cached_per_file_version(tmp_path, monkeypatch):
    apk = make_apk(tmp_path / "a.apk", manifest(52))
    monkeypatch.setattr(server, "APK", apk)
    assert server.apk_version_code() == 52
    calls = []
    monkeypatch.setattr("openmob.apk_check.version_code", lambda p: calls.append(p) or 99)
    assert server.apk_version_code() == 52 and not calls  # same file: cached
    make_apk(apk, manifest(53, dtype=INT_HEX))  # a new build in place (size changes)
    time.sleep(0.01)
    assert server.apk_version_code() == 99 and calls


# --- the hello and the welcome ---------------------------------------------------------------

def test_an_old_hello_without_a_code_is_version_1():
    assert server.hello_version_code({}) == 1
    assert server.hello_version_code({"app_version": "0.1.0"}) == 1
    for bad in (True, "52", 0, -3, 5.5, None):
        assert server.hello_version_code({"app_version_code": bad}) == 1
    assert server.hello_version_code({"app_version_code": 52}) == 52


def test_app_update_names_latest_minimum_and_the_download(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENMOB_REQUIRE_RELEASE_APK", raising=False)
    apk = make_apk(tmp_path / "a.apk", manifest(52))
    monkeypatch.setattr(server, "APK", apk)
    out = server.app_update("https://openmob.example", 50)
    assert out == {"latest": 52, "minimum": 50,
                   "url": f"https://openmob.example/download/openmob.apk?v={server.apk_version()}"}


def test_no_apk_means_no_latest_and_no_url(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "APK", tmp_path / "none.apk")
    assert server.app_update("https://x.example", 0) == {"latest": None, "minimum": 0, "url": None}


def test_a_refused_apk_is_never_offered(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OPENMOB_REQUIRE_RELEASE_APK", "1")
    monkeypatch.setattr(server, "APK", make_apk(tmp_path / "d.apk", manifest(52), v2_cn="Android Debug"))
    assert server.app_update("https://x.example", 3) == {"latest": None, "minimum": 3, "url": None}


def test_an_apk_without_a_version_code_is_not_offered(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENMOB_REQUIRE_RELEASE_APK", raising=False)
    monkeypatch.setattr(server, "APK", make_apk(tmp_path / "n.apk", axml(app_attrs=CLEAN)))
    assert server.app_update("https://x.example", 0) == {"latest": None, "minimum": 0, "url": None}


def reconnect(api, code=None, **extra):
    """Alice's phone again, with this app version (None: an old app that sends no code)."""
    device = {"app_version": "test"} | ({} if code is None else {"app_version_code": code})
    phone = FakePhone(api.base.replace("http", "ws"), api.alice.driver, device_id="alice-phone",
                      key=api.alice.device_key, signer=new_signer(), extra_device=device, **extra)
    assert phone.welcome.wait(5)
    api.alice.phone = phone
    return phone


def welcome(phone):
    return next(m for m in phone.received if m["type"] == "welcome")


@pytest.fixture
def served(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENMOB_REQUIRE_RELEASE_APK", raising=False)
    monkeypatch.setattr(server, "APK", make_apk(tmp_path / "served.apk", manifest(52)))


def test_the_welcome_carries_app_update_with_this_sockets_host(api, served):
    api.cfg.min_app_version = 50
    phone = reconnect(api, 52)
    update = welcome(phone)["app_update"]
    assert update == {"latest": 52, "minimum": 50,
                      "url": f"{api.base}/download/openmob.apk?v={server.apk_version()}"}
    session = api.manager.get("app-alice-phone")
    assert session.app_version_code == 52 and not session.coordinator.update_required


def test_an_old_app_is_version_1_and_below_a_minimum(api, served):
    phone = reconnect(api, None)
    assert welcome(phone)["app_update"]["minimum"] == 0
    session = api.manager.get("app-alice-phone")
    assert session.app_version_code == 1 and not session.coordinator.update_required  # no minimum: fine
    api.cfg.min_app_version = 2
    reconnect(api, None)
    assert api.manager.get("app-alice-phone").coordinator.update_required


def test_below_the_minimum_tasks_are_refused_but_the_phone_stays(api, served):
    api.cfg.min_app_version = 50
    phone = reconnect(api, 47)
    session = api.manager.get("app-alice-phone")
    assert session.online and session.coordinator.update_required
    # The API: a stable code, 409 like the other "this phone can't take it" refusals.
    r = api.alice.v1.post("/v1/devices/app-alice-phone/tasks", json={"instruction": "open settings"})
    assert r.status_code == 409 and r.json()["code"] == "app_update_required"
    # The phone's own request: refused, and the phone is told why; nothing runs.
    phone.send({"type": "command", "text": "open settings"})
    assert wait_for(lambda: ("status", UPDATE_REQUIRED) in phone.events)
    # The dashboard: the same code.
    r = api.alice.console.post("/api/devices/app-alice-phone/command", json={"text": "open settings"})
    assert r.status_code == 409 and r.json()["code"] == "app_update_required"
    assert not any(m[0] == "launch_app" for m in phone.calls)
    # Stop still goes through and the socket stays up.
    phone.send({"type": "task_stop"})
    phone.send({"type": "chats_list", "offset": 0, "limit": 5})
    assert wait_for(lambda: any(m["type"] == "chats" for m in phone.received))
    assert session.online and phone.close_code is None
    # The dashboard's phone list says who is out of date.
    row = next(d for d in api.alice.console.get("/api/devices").json() if d["id"] == "app-alice-phone")
    assert row["app_version_code"] == 47 and row["app_update_required"] is True


def test_updating_the_app_lets_it_act_again(api, served):
    api.cfg.min_app_version = 50
    reconnect(api, 47)
    reconnect(api, 52)
    assert not api.manager.get("app-alice-phone").coordinator.update_required
    r = api.alice.v1.post("/v1/devices/app-alice-phone/tasks", json={"instruction": "open settings"})
    assert r.status_code == 201, r.text


def test_mcp_says_app_update_required(api, served):
    from test_mcp import call, text

    api.cfg.min_app_version = 50
    reconnect(api, 47)
    result = call(api, api.alice, "run_task", instruction="open settings", device_id="app-alice-phone")
    assert result.is_error and "app_update_required" in text(result) and "Tell the user" in text(result)


def test_an_orchestration_step_waits_for_the_update_then_fails(orc):
    orc.manager.get(B).coordinator.update_required = True
    o = start(orc.alice, [{"id": "b", "device_id": B, "instruction": "open maps"}], wait_for_phone_seconds=1)
    done = wait_status(orc.alice, o["id"], "failed")
    assert done["reason"] == "app_update_required" and step(done, "b")["task_id"] is None


# --- the coordinator ------------------------------------------------------------------------

def test_the_coordinator_refuses_new_tasks_but_takes_answers_and_stops():
    c = Coordinator(Speaker(enabled=False))
    events = []
    c.listeners.append(lambda kind, message: events.append((kind, message)))
    c.update_required = True
    assert c.submit("open maps", "phone") == "update_required" and c.tasks.empty()
    assert ("status", UPDATE_REQUIRED) in events
    c.question = "Which one?"
    assert c.submit("the first", "phone") == "answered"
    c.question = None
    assert c.submit("stop", "phone") == "ignored"  # nothing runs: a stop is a no-op, never refused


def test_a_task_queued_before_the_check_ends_with_app_update_required():
    c = Coordinator(Speaker(enabled=False))  # no agent: the worker must never get as far as running it
    task_id = c.enqueue("open maps", "api")
    c.update_required = True
    c.start()
    assert wait_for(lambda: (c.task(task_id) or {}).get("status") == "failed")
    info = c.task(task_id)
    assert info["reason"] == "app_update_required" and info["started"] is None and c.current_task is None


# --- the setting ------------------------------------------------------------------------------

def test_min_app_version_from_config_and_env(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENMOB_MIN_APP_VERSION", raising=False)
    path = tmp_path / "config.yaml"
    path.write_text("min_app_version: 7\n")
    assert load_config(path).min_app_version == 7
    path.write_text("model: claude-sonnet-5-5\n")
    assert load_config(path).min_app_version == 0  # default: no minimum
    monkeypatch.setenv("OPENMOB_MIN_APP_VERSION", "9")
    assert load_config(path).min_app_version == 9
    monkeypatch.setenv("OPENMOB_MIN_APP_VERSION", "nine")
    with pytest.raises(ValueError, match="OPENMOB_MIN_APP_VERSION"):
        load_config(path)
    monkeypatch.delenv("OPENMOB_MIN_APP_VERSION")
    for bad in ("-1", "'7'", "true"):
        path.write_text(f"min_app_version: {bad}\n")
        with pytest.raises(ValueError, match="min_app_version"):
            load_config(path)


def test_the_docs_list_the_code():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    assert "`app_update_required`" in (root / "docs" / "errors.md").read_text()
    protocol = (root / "docs" / "phone-protocol.md").read_text()
    assert "app_update" in protocol and "app_version_code" in protocol
    from openmob.phone.protocol import PROTOCOL_VERSION
    assert PROTOCOL_VERSION == 1  # the fields are additive

