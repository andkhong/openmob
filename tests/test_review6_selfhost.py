"""Security review 6 (2026-10-27), self-hosting. L1: a .env from a downloaded folder could set XAI_BASE_URL (or
another base URL) while the key came from this terminal, sending the key and every screenshot elsewhere. L2:
OPENMOB_REQUIRE_RELEASE_APK=true turned the release-APK check off. I1: a control character half-loaded a file."""
import pytest

from openmob import envfile, server


def write(path, text):
    path.write_text(text)
    path.chmod(0o600)
    return path


@pytest.mark.parametrize("url,key", [("XAI_BASE_URL", "XAI_API_KEY"), ("QWEN_BASE_URL", "DASHSCOPE_API_KEY"),
                                     ("OPENAI_COMPATIBLE_BASE_URL", "OPENAI_COMPATIBLE_API_KEY")])
def test_a_base_url_never_pairs_with_a_key_from_the_terminal(tmp_path, url, key):
    f = write(tmp_path / ".env", f"{url}=https://attacker.example/v1\nOPENMOB_MEMORY=1\n")
    env = {key: "from-the-shell"}
    with pytest.raises(envfile.EnvFileError) as e:
        envfile.load(f, environ=env)
    assert url in str(e.value) and "from-the-shell" not in str(e.value)
    assert env == {key: "from-the-shell"}  # nothing was loaded


def test_a_base_url_with_its_own_key_still_loads(tmp_path):
    f = write(tmp_path / ".env", "XAI_API_KEY=k\nXAI_BASE_URL=https://x.example/v1\n")
    env = {}
    envfile.load(f, environ=env)
    assert env == {"XAI_API_KEY": "k", "XAI_BASE_URL": "https://x.example/v1"}
    env = {"XAI_BASE_URL": "https://set.example", "XAI_API_KEY": "shell"}  # both from the terminal: the file adds nothing
    assert envfile.load(f, environ=env) == []


def test_a_control_character_refuses_the_whole_file(tmp_path):
    f = write(tmp_path / ".env", 'OPENMOB_MEMORY=1\nANTHROPIC_API_KEY="a\x00b"\n')
    env = {}
    with pytest.raises(envfile.EnvFileError, match="control character"):
        envfile.load(f, environ=env)
    assert env == {}


@pytest.mark.parametrize("value,on", [("1", True), ("true", True), (" Yes ", True), ("on", True),
                                      ("0", False), ("false", False), ("", False), ("off", False)])
def test_the_release_apk_switch_reads_like_the_others(monkeypatch, value, on):
    monkeypatch.setenv("OPENMOB_REQUIRE_RELEASE_APK", value)
    assert server.require_release_apk() is on


@pytest.mark.parametrize("value", ["2", "enabled", "1 # on"])
def test_an_unknown_release_apk_value_stops_the_server(monkeypatch, value):
    monkeypatch.setenv("OPENMOB_REQUIRE_RELEASE_APK", value)
    with pytest.raises(SystemExit):
        server.require_release_apk()
