"""The .env loader (openmob/envfile.py): `openmob run` reads ./.env (or --env-file), scripts/om reads
provider-keys.env. Data only, allow-listed names, private files only, never overrides, never echoes a value."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from openmob import envfile
from openmob.main import load_env_file

ROOT = Path(__file__).resolve().parent.parent
SECRET = "sk-test-DO-NOT-ECHO-1234"


def write(path, text, mode=0o600):
    path.write_text(text)
    path.chmod(mode)
    return path


def test_allowed_names_quoting_export_and_comments(tmp_path):
    f = write(tmp_path / ".env", f"""
# a comment line
ANTHROPIC_API_KEY={SECRET}
export OPENAI_API_KEY="with spaces # not a comment"
GEMINI_API_KEY='single $quoted'   # a trailing comment
OPENMOB_PUBLIC_URL=https://openmob.example.com
XAI_API_KEY=
""")
    env = {}
    loaded = envfile.load(f, environ=env)
    assert env == {"ANTHROPIC_API_KEY": SECRET, "OPENAI_API_KEY": "with spaces # not a comment",
                   "GEMINI_API_KEY": "single $quoted", "OPENMOB_PUBLIC_URL": "https://openmob.example.com"}
    assert sorted(loaded) == sorted(env)  # an empty value (XAI_API_KEY=) sets nothing


def test_the_file_is_data_never_shell(tmp_path):
    marker = tmp_path / "ran"
    f = write(tmp_path / ".env", f"ANTHROPIC_API_KEY='$(touch {marker})'\nOPENAI_API_KEY=`touch${{IFS}}{marker}`\n")
    env = {}
    envfile.load(f, environ=env)
    assert env["ANTHROPIC_API_KEY"] == f"$(touch {marker})" and not marker.exists()
    assert env["OPENAI_API_KEY"] == f"`touch${{IFS}}{marker}`"


def test_a_variable_already_set_is_never_overridden(tmp_path):
    f = write(tmp_path / ".env", f"ANTHROPIC_API_KEY={SECRET}\nOPENAI_API_KEY=from-file\n")
    env = {"ANTHROPIC_API_KEY": "from-terminal"}
    assert envfile.load(f, environ=env) == ["OPENAI_API_KEY"]
    assert env == {"ANTHROPIC_API_KEY": "from-terminal", "OPENAI_API_KEY": "from-file"}


@pytest.mark.parametrize("mode", [0o640, 0o604, 0o644, 0o660])
def test_a_file_others_can_read_is_refused_with_the_chmod_command(tmp_path, mode):
    f = write(tmp_path / ".env", f"ANTHROPIC_API_KEY={SECRET}\n", mode)
    env = {}
    with pytest.raises(envfile.EnvFileError) as e:
        envfile.load(f, environ=env)
    assert f"chmod 600 {f}" in str(e.value) and SECRET not in str(e.value) and env == {}


def test_an_unknown_name_refuses_the_whole_file_without_echoing_its_value(tmp_path):
    f = write(tmp_path / ".env", f"ANTHROPIC_API_KEY=ok\nPATH={SECRET}\n")
    env = {}
    with pytest.raises(envfile.EnvFileError) as e:
        envfile.load(f, environ=env)
    msg = str(e.value)
    assert "line 2" in msg and "PATH" in msg and SECRET not in msg
    assert env == {}  # nothing loaded, not even the good line


@pytest.mark.parametrize("name", [SECRET.replace("-", "_"), "sk_live_X", "sk_live_" + "51HxYzAbCdEf", "A" * 41,
                                  "ghp_abcdef0123456789", "lowercase_name"])
def test_a_name_that_could_be_a_secret_isnt_echoed_either(tmp_path, name):
    f = write(tmp_path / ".env", f"{name}=x\n")
    with pytest.raises(envfile.EnvFileError) as e:
        envfile.load(f, environ={})
    msg = str(e.value)
    assert name not in msg and "line 1: unsupported variable name;" in msg


def test_a_hash_is_a_comment_only_after_whitespace(tmp_path):
    f = write(tmp_path / ".env", "ANTHROPIC_API_KEY=abc#def\nOPENAI_API_KEY=abc #def\n"
                                 "GEMINI_API_KEY=a\\ #b\nXAI_API_KEY='x' #y\n#QWEN_API_KEY=z\n")
    env = {}
    envfile.load(f, environ=env)
    assert env == {"ANTHROPIC_API_KEY": "abc#def", "OPENAI_API_KEY": "abc", "GEMINI_API_KEY": "a ",
                   "XAI_API_KEY": "x"}


def test_a_file_owned_by_another_user_is_refused(tmp_path, monkeypatch):
    f = write(tmp_path / ".env", f"ANTHROPIC_API_KEY={SECRET}\n")
    other = os.geteuid() + 1
    monkeypatch.setattr(envfile.os, "geteuid", lambda: other)
    env = {}
    with pytest.raises(envfile.EnvFileError) as e:
        envfile.load(f, environ=env)
    assert "belongs to another user" in str(e.value) and SECRET not in str(e.value) and env == {}


def test_main_refuses_a_dot_env_owned_by_another_user(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write(tmp_path / ".env", f"ANTHROPIC_API_KEY={SECRET}\n")
    other = os.geteuid() + 1
    monkeypatch.setattr(envfile.os, "geteuid", lambda: other)
    with pytest.raises(SystemExit) as e:
        load_env_file(None)
    assert "belongs to another user" in str(e.value) and SECRET not in str(e.value)


def test_a_non_regular_file_is_refused(tmp_path, monkeypatch):
    fifo = tmp_path / ".env"
    os.mkfifo(fifo, 0o600)
    with pytest.raises(envfile.EnvFileError) as e:
        envfile.load(fifo, environ={})
    assert "not a regular file" in str(e.value)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as e:  # ./.env as a FIFO isn't skipped silently, nor does it hang
        load_env_file(None)
    assert "not a regular file" in str(e.value)


def test_the_checks_and_the_read_use_one_descriptor(tmp_path, monkeypatch):
    """No stat-then-open race: the file is checked with fstat on the descriptor it is read from."""
    f = write(tmp_path / ".env", "ANTHROPIC_API_KEY=x\n")
    stats = []
    real_fstat = os.fstat
    monkeypatch.setattr(envfile.os, "fstat", lambda fd: stats.append(fd) or real_fstat(fd))
    monkeypatch.setattr(envfile.os, "stat", lambda *a, **k: pytest.fail("path stat used"))
    envfile.load(f, environ={})
    assert len(stats) == 1


def test_an_unreadable_file_gives_a_clean_error(tmp_path):
    f = write(tmp_path / ".env", f"ANTHROPIC_API_KEY={SECRET}\n", 0o000)
    try:
        if os.access(f, os.R_OK):
            pytest.skip("running as root")
        with pytest.raises(envfile.EnvFileError) as e:
            envfile.load(f, environ={})
        assert "permission denied" in str(e.value) and SECRET not in str(e.value)
    finally:
        f.chmod(0o600)


def test_a_file_that_isnt_utf8_gives_a_clean_error(tmp_path):
    f = tmp_path / ".env"
    f.write_bytes(b"ANTHROPIC_API_KEY=sk-\xff\xfesecret\n")
    f.chmod(0o600)
    with pytest.raises(envfile.EnvFileError) as e:
        envfile.load(f, environ={})
    assert "not UTF-8" in str(e.value) and "secret" not in str(e.value)


@pytest.mark.parametrize("line", [f'ANTHROPIC_API_KEY="{SECRET}', f"ANTHROPIC_API_KEY {SECRET}",
                                  f"ANTHROPIC_API_KEY={SECRET} OPENAI_API_KEY=x", SECRET])
def test_malformed_lines_are_refused_without_echoing(tmp_path, line):
    f = write(tmp_path / ".env", line + "\n")
    with pytest.raises(envfile.EnvFileError) as e:
        envfile.load(f, environ={})
    assert SECRET not in str(e.value)


def test_the_example_file_lists_every_allowed_name_blank(tmp_path):
    text = (ROOT / ".env.example").read_text()
    names = {line.split("=", 1)[0] for line in text.splitlines() if line and not line.startswith("#")}
    assert names == set(envfile.ALLOWED)
    env = {}
    assert envfile.load(write(tmp_path / ".env", text), environ=env) == [] and env == {}  # every value blank


def _unset(monkeypatch, name):
    """Unset `name` for this test only. delenv(raising=False) on an unset variable registers no undo, so a value
    the test then sets would leak into later tests: set it first so monkeypatch restores (or removes) it."""
    monkeypatch.setenv(name, "placeholder")
    monkeypatch.delenv(name)


def test_openmob_loads_dot_env_from_the_current_directory(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _unset(monkeypatch, "XAI_BASE_URL")
    write(tmp_path / ".env", "XAI_BASE_URL=https://xai.example.com/v1\n")
    load_env_file(None)
    assert os.environ["XAI_BASE_URL"] == "https://xai.example.com/v1"
    err = capsys.readouterr().err
    assert f"loaded 1 setting(s) from {tmp_path.resolve() / '.env'} (XAI_BASE_URL)" in err.replace(
        str(tmp_path), str(tmp_path.resolve()))
    assert "xai.example.com" not in err  # names only, never values


def test_the_loaded_names_are_printed_for_every_command_never_the_values(tmp_path, monkeypatch, capsys):
    import openmob.main as om_main

    monkeypatch.chdir(tmp_path)
    _unset(monkeypatch, "ANTHROPIC_API_KEY")
    write(tmp_path / ".env", f"ANTHROPIC_API_KEY={SECRET}\n")
    monkeypatch.setattr(om_main, "load_env_file", load_env_file)  # undo conftest's switch-off, for this test
    monkeypatch.setattr("openmob.phone_add.phone_add", lambda server, key, **kw: None)
    om_main.main(["phone", "add", "--server", "https://openmob.example.com", "--serial", "S1"])
    err = capsys.readouterr().err
    assert "(ANTHROPIC_API_KEY)" in err and SECRET not in err


def test_the_tests_never_load_a_dot_env_through_main(tmp_path, monkeypatch):
    """conftest.py switches main()'s .env loading off, so a developer's .env in the repo root can't leak keys
    into the test run."""
    from openmob import main as om_main

    monkeypatch.chdir(tmp_path)
    _unset(monkeypatch, "ANTHROPIC_API_KEY")
    write(tmp_path / ".env", f"ANTHROPIC_API_KEY={SECRET}\n")
    monkeypatch.setattr("openmob.phone_add.phone_add", lambda server, key, **kw: None)
    om_main.main(["phone", "add", "--server", "https://openmob.example.com", "--serial", "S1"])
    assert "ANTHROPIC_API_KEY" not in os.environ


@pytest.mark.env_file
def test_the_env_file_marker_lets_main_load_it(tmp_path, monkeypatch):
    """The control for the test above: with the marker, the same call does load the file."""
    from openmob import main as om_main

    monkeypatch.chdir(tmp_path)
    _unset(monkeypatch, "ANTHROPIC_API_KEY")
    write(tmp_path / ".env", f"ANTHROPIC_API_KEY={SECRET}\n")
    monkeypatch.setattr("openmob.phone_add.phone_add", lambda server, key, **kw: None)
    om_main.main(["phone", "add", "--server", "https://openmob.example.com", "--serial", "S1"])
    assert os.environ["ANTHROPIC_API_KEY"] == SECRET


def test_env_file_overrides_the_default_path_and_must_exist(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _unset(monkeypatch, "QWEN_BASE_URL")
    write(tmp_path / ".env", "QWEN_BASE_URL=https://ignored.example.com\n")
    write(tmp_path / "other.env", "QWEN_BASE_URL=https://qwen.example.com\n")
    load_env_file(str(tmp_path / "other.env"))
    assert os.environ["QWEN_BASE_URL"] == "https://qwen.example.com"
    with pytest.raises(SystemExit) as e:
        load_env_file(str(tmp_path / "missing.env"))
    assert "no such file" in str(e.value)


def test_no_dot_env_is_fine_and_an_unsafe_one_stops_the_command(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    load_env_file(None)  # nothing to load
    write(tmp_path / ".env", f"ANTHROPIC_API_KEY={SECRET}\n", 0o644)
    with pytest.raises(SystemExit) as e:
        load_env_file(None)
    assert "chmod 600" in str(e.value) and SECRET not in str(e.value)


def test_the_cli_refuses_an_unsafe_env_file_before_doing_anything(tmp_path):
    write(tmp_path / ".env", f"ANTHROPIC_API_KEY={SECRET}\n", 0o644)
    r = subprocess.run([sys.executable, "-c", "from openmob.main import main; main(['doctor'])"], cwd=tmp_path,
                       capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(ROOT)})
    assert r.returncode != 0 and "chmod 600" in r.stderr
    assert SECRET not in r.stdout + r.stderr


def test_om_loads_provider_keys_through_this_module():
    om = (ROOT / "scripts" / "om").read_text()
    assert "openmob/envfile.py" in om and "runpy.run_path(os.environ['OM_ENVFILE'])" in om
    assert "shlex" not in om  # the parser lives in one place
