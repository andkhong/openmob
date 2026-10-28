"""The release-APK guard (openmob/apk_check.py, scripts/check_release_apk.py): the hosted server's
download must not be debuggable, allow cleartext, carry a debug key or no signature, or be another
package. The APKs here are tiny synthetic ones: a hand-built binary manifest and a fake signer."""
import hashlib
import io
import struct
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from openmob.apk_check import ATTR_DEBUGGABLE, ATTR_USES_CLEARTEXT, NO_SIGNERS, check_apk

ROOT = Path(__file__).resolve().parent.parent
V2, V3 = 0x7109871A, 0xF05368C0


# --- building a synthetic APK -------------------------------------------------

def axml(package="dev.openmob.companion", app_attrs=(), manifest_attrs=()):
    """A binary AndroidManifest.xml: <manifest package=… android:…=…><application android:…=…/>. `app_attrs`
    and `manifest_attrs` are (name, resource id or None, data type, value) on <application> and <manifest>; an
    attribute with no resource id gets none in the resource map (found by name only)."""
    named = [*manifest_attrs, *app_attrs]
    names = [n for n, _, _, _ in named]
    with_ids = [n for n, rid, _, _ in named if rid is not None]
    names = with_ids + [n for n in names if n not in with_ids]  # the resource map covers the first ones only
    strings = names + ["package", "manifest", "application", package]
    idx = {s: i for i, s in enumerate(strings)}

    def chunk(ctype, header, body):
        return struct.pack("<HHI", ctype, 8 + len(header), 8 + len(header) + len(body)) + header + body

    pool_body = b"".join(struct.pack("<H", len(s)) + s.encode("utf-16-le") + b"\0\0" for s in strings)
    offsets, off = [], 0
    for s in strings:
        offsets.append(off)
        off += 2 + 2 * len(s) + 2
    count = len(strings)
    pool = chunk(0x0001, struct.pack("<IIIII", count, 0, 0, 28 + 4 * count, 0),
                 struct.pack(f"<{count}I", *offsets) + pool_body)
    ids = {n: rid for n, rid, _, _ in named}
    res_map = chunk(0x0180, b"", struct.pack(f"<{len(with_ids)}I", *[ids[n] for n in with_ids]))

    def element(name, attrs):
        ext = struct.pack("<IIHHHHHH", 0xFFFFFFFF, idx[name], 20, 20, len(attrs), 0, 0, 0)
        body = b"".join(struct.pack("<IIIHBBI", 0xFFFFFFFF, n, raw, 8, 0, t, v) for n, raw, t, v in attrs)
        return chunk(0x0102, struct.pack("<II", 1, 0xFFFFFFFF), ext + body)

    manifest = element("manifest", [(idx["package"], idx[package], 0x03, idx[package]),
                                     *[(idx[n], 0xFFFFFFFF, t, v) for n, _, t, v in manifest_attrs]])
    app = element("application", [(idx[n], 0xFFFFFFFF, t, v) for n, _, t, v in app_attrs])
    body = pool + res_map + manifest + app
    return struct.pack("<HHI", 0x0003, 8, 8 + len(body)) + body


def fake_cert(cn):
    """Not a real certificate: just DER bytes carrying a commonName, which is all the guard reads."""
    value = cn.encode()
    return b"\x30\x82\x01\x00" + b"\x06\x03\x55\x04\x03\x0c" + bytes([len(value)]) + value + b"\x00" * 16


def lp(b):
    return struct.pack("<I", len(b)) + b


def signing_block(scheme, cert):
    signed_data = lp(b"") + lp(lp(cert)) + struct.pack("<II", 30, 0x7FFFFFFF) + lp(b"")
    signer = lp(signed_data) + lp(b"") + lp(b"")
    pair_value = lp(lp(signer))
    pairs = struct.pack("<QI", 4 + len(pair_value), scheme) + pair_value
    size = len(pairs) + 8 + 16
    return struct.pack("<Q", size) + pairs + struct.pack("<Q", size) + b"APK Sig Block 42"


def make_apk(path, manifest=None, v2_cn="CN OpenMob", v1_cn=None, scheme=V2):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("AndroidManifest.xml", manifest if manifest is not None else axml(app_attrs=CLEAN))
        z.writestr("classes.dex", b"dex\n035\0")
        if v1_cn:
            z.writestr("META-INF/CERT.RSA", fake_cert(v1_cn))
    data = buf.getvalue()
    if v2_cn:
        eocd = data.rfind(b"PK\x05\x06")
        cd = struct.unpack_from("<I", data, eocd + 16)[0]
        block = signing_block(scheme, fake_cert(v2_cn))
        data = (data[:cd] + block + data[cd:eocd + 16] + struct.pack("<I", cd + len(block))
                + data[eocd + 20:])
    path.write_bytes(data)
    return path


def sha(cn):
    return hashlib.sha256(fake_cert(cn)).hexdigest()


@pytest.fixture(autouse=True)
def pin_fake_signer(monkeypatch):
    """The synthetic APKs' "CN OpenMob" key stands in for the release key (the env reaches the script too)."""
    monkeypatch.setenv("OPENMOB_RELEASE_SIGNERS", sha("CN OpenMob"))


TRUE, FALSE = (0x12, 0xFFFFFFFF), (0x12, 0)
CLEAN = [("usesCleartextTraffic", ATTR_USES_CLEARTEXT, *FALSE)]


def problems(path):
    report = check_apk(path)
    assert zipfile.ZipFile(path).testzip() is None
    return report.problems


# --- the checks ---------------------------------------------------------------

def test_a_clean_release_build_passes_and_shows_its_signer(tmp_path):
    report = check_apk(make_apk(tmp_path / "ok.apk"))
    assert report.ok, report.problems
    assert [(s, cn) for s, cn, _ in report.signers] == [("v2", "CN OpenMob")]
    assert len(report.signers[0][2]) == 64  # the certificate's SHA-256, to pin later


def test_a_v3_signer_is_read_too(tmp_path):
    assert check_apk(make_apk(tmp_path / "v3.apk", scheme=V3)).signers[0][0] == "v3"
    assert problems(make_apk(tmp_path / "v3d.apk", scheme=V3, v2_cn="Android Debug"))


def test_debuggable_is_refused(tmp_path):
    m = axml(app_attrs=[("debuggable", ATTR_DEBUGGABLE, *TRUE), *CLEAN])
    assert problems(make_apk(tmp_path / "d.apk", m)) == ["the manifest has android:debuggable=true"]
    m = axml(app_attrs=[("debuggable", ATTR_DEBUGGABLE, *FALSE), *CLEAN])
    assert problems(make_apk(tmp_path / "f.apk", m)) == []


def test_debuggable_is_found_by_resource_id_not_by_its_name(tmp_path):
    m = axml(app_attrs=[("renamed", ATTR_DEBUGGABLE, *TRUE)])
    assert problems(make_apk(tmp_path / "d.apk", m)) == ["the manifest has android:debuggable=true"]


def test_cleartext_is_refused(tmp_path):
    m = axml(app_attrs=[("usesCleartextTraffic", ATTR_USES_CLEARTEXT, *TRUE)])
    assert problems(make_apk(tmp_path / "c.apk", m)) == ["the manifest has android:usesCleartextTraffic=true"]


def test_a_value_that_isnt_a_plain_boolean_is_refused(tmp_path):
    m = axml(app_attrs=[("debuggable", ATTR_DEBUGGABLE, 0x01, 0x7F050001)])  # a resource reference
    assert "isn't a plain false" in problems(make_apk(tmp_path / "r.apk", m))[0]


def test_the_debug_key_is_refused_in_the_signing_block_and_in_v1(tmp_path):
    debug = "it is signed with an Android debug key (CN=Android Debug)"
    assert problems(make_apk(tmp_path / "v2.apk", v2_cn="Android Debug")) == [debug]
    assert problems(make_apk(tmp_path / "v1.apk", v2_cn=None, v1_cn="Android Debug")) == [debug]
    assert problems(make_apk(tmp_path / "both.apk", v1_cn="Android Debug")) == [debug]
    # Phones check only v2/v3 (minSdk 30): a v1-only APK can't be matched to the pinned key.
    assert problems(make_apk(tmp_path / "v1only.apk", v2_cn=None, v1_cn="CN OpenMob")) == [
        "it has no v2/v3 signature to check against the release key"]


def test_a_key_that_isnt_the_pinned_release_key_is_refused(tmp_path):
    other = "it is signed with a key that isn't the pinned release key (OPENMOB_RELEASE_SIGNERS)"
    assert problems(make_apk(tmp_path / "renamed.apk", v2_cn="CN Release")) == [other]  # e.g. a renamed debug key
    assert problems(make_apk(tmp_path / "v3.apk", v2_cn="CN Release", scheme=V3)) == [other]


def test_with_no_pinned_key_every_apk_is_refused_and_a_self_hoster_pins_their_own(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENMOB_RELEASE_SIGNERS")
    assert problems(make_apk(tmp_path / "a.apk")) == [NO_SIGNERS]  # fail closed, saying what to set
    assert "OPENMOB_RELEASE_SIGNERS" in NO_SIGNERS and "scripts/om keygen" in NO_SIGNERS
    monkeypatch.setenv("OPENMOB_RELEASE_SIGNERS", " , ")
    assert problems(make_apk(tmp_path / "blank.apk")) == [NO_SIGNERS]
    monkeypatch.setenv("OPENMOB_RELEASE_SIGNERS", f" {sha('CN Other').upper()} , {sha('CN OpenMob')}")
    assert problems(make_apk(tmp_path / "b.apk")) == []


def test_the_hosted_server_pins_its_release_key_in_fly_toml():
    """The owner's key moved from the code to the hosted deploy config (open-source prep): fly deploy passes it
    as a build arg, so the image build and the server keep refusing every other key."""
    import tomllib

    fly = tomllib.loads((ROOT / "fly.toml").read_text())
    assert fly["build"]["args"]["OPENMOB_RELEASE_SIGNERS"] == (
        "8b6dcac4692c34cd101a72c7afd30555980ba43867403470804182f089c6d3b8")
    docker = (ROOT / "Dockerfile").read_text()
    assert "ENV OPENMOB_RELEASE_SIGNERS=$OPENMOB_RELEASE_SIGNERS\n" in docker  # the server checks with it too


def test_an_unsigned_apk_is_refused(tmp_path):
    assert problems(make_apk(tmp_path / "u.apk", v2_cn=None)) == ["the APK isn't signed"]


def test_another_package_is_refused(tmp_path):
    m = axml(package="dev.evil.companion", app_attrs=CLEAN)
    assert problems(make_apk(tmp_path / "p.apk", m)) == ["the package is 'dev.evil.companion', not dev.openmob.companion"]


def test_not_an_apk_is_refused(tmp_path):
    junk = tmp_path / "junk.apk"
    junk.write_bytes(b"not a zip")
    assert "not a readable APK" in check_apk(junk).problems[0]


def test_the_script_exits_non_zero_and_names_om_release(tmp_path):
    script = [sys.executable, "-I", str(ROOT / "scripts" / "check_release_apk.py")]
    ok = subprocess.run(script + [str(make_apk(tmp_path / "ok.apk"))], capture_output=True, text=True)
    assert ok.returncode == 0 and "SHA-256" in ok.stdout, ok.stderr
    bad = subprocess.run(script + [str(make_apk(tmp_path / "d.apk", v2_cn="Android Debug"))],
                         capture_output=True, text=True)
    assert bad.returncode == 1 and "scripts/om release" in bad.stderr and "debug key" in bad.stderr
    other = subprocess.run(script + [str(make_apk(tmp_path / "o.apk", v2_cn="CN Release"))],
                           capture_output=True, text=True)
    assert other.returncode == 1 and "pinned release key" in other.stderr


def test_the_dockerfile_runs_the_check_on_the_apk_it_ships():
    lines = (ROOT / "Dockerfile").read_text().splitlines()
    copy = lines.index("COPY deploy/OpenMob.apk ./OpenMob.apk")
    after = "\n".join(lines[copy:])
    assert "ARG OPENMOB_REQUIRE_RELEASE_APK=1\n" in after  # on unless a build opts out
    assert "ARG OPENMOB_RELEASE_SIGNERS=\n" in after  # no default: fly.toml or the self-hoster passes the pin
    assert "ENV OPENMOB_REQUIRE_RELEASE_APK=$OPENMOB_REQUIRE_RELEASE_APK\n" in after  # the server checks too
    assert "1|true|on|yes) python -I scripts/check_release_apk.py OpenMob.apk ;;" in after
    assert '*) echo "OPENMOB_REQUIRE_RELEASE_APK must be 1 or 0" >&2; exit 1 ;;' in after  # never on by accident


# --- the hosted server's download ---------------------------------------------

@pytest.fixture
def serve(monkeypatch):
    from openmob import server
    from test_runner_server import FakeManager, coordinator

    def client(apk, require):
        monkeypatch.setattr(server, "APK", apk)
        if require:
            monkeypatch.setenv("OPENMOB_REQUIRE_RELEASE_APK", "1")
        else:
            monkeypatch.delenv("OPENMOB_REQUIRE_RELEASE_APK", raising=False)
        return TestClient(server.create_app(FakeManager(coordinator()), token="secret"))

    return client


def test_a_hosted_server_refuses_to_serve_a_debug_build(tmp_path, serve, capsys):
    client = serve(make_apk(tmp_path / "debug.apk", v2_cn="Android Debug"), require=True)
    assert "not serving" in capsys.readouterr().err  # loud at start
    assert client.head("/download/openmob.apk").status_code == 503
    r = client.get("/download/openmob.apk")
    assert r.status_code == 503 and "signed release" in r.json()["detail"]
    assert client.post("/api/pairing", headers={"X-OpenMob-Token": "secret"}).json()["apk_url"] is None


def test_a_hosted_server_serves_a_release_build(tmp_path, serve):
    apk = make_apk(tmp_path / "release.apk")
    client = serve(apk, require=True)
    r = client.get("/download/openmob.apk")
    assert r.status_code == 200 and r.content == apk.read_bytes()


def test_a_hosted_server_refuses_a_build_signed_by_another_key(tmp_path, serve):
    client = serve(make_apk(tmp_path / "other.apk", v2_cn="CN Release"), require=True)
    assert client.get("/download/openmob.apk").status_code == 503


def test_a_local_server_still_serves_a_debug_build(tmp_path, serve):
    client = serve(make_apk(tmp_path / "debug.apk", v2_cn="Android Debug"), require=False)
    assert client.get("/download/openmob.apk").status_code == 200


def test_a_network_security_config_is_refused(tmp_path):
    """Review 5 W5-L1: a network security config can re-allow cleartext per domain; the guard doesn't parse it, so
    an APK that sets one is refused (the app sets none)."""
    from openmob.apk_check import ATTR_NETWORK_SECURITY_CONFIG

    m = axml(app_attrs=[*CLEAN, ("networkSecurityConfig", ATTR_NETWORK_SECURITY_CONFIG, 0x01, 0x7F120001)])
    assert problems(make_apk(tmp_path / "n.apk", m)) == [
        "the manifest sets android:networkSecurityConfig (it could allow cleartext)"]
    m = axml(app_attrs=[*CLEAN, ("renamed", ATTR_NETWORK_SECURITY_CONFIG, 0x01, 0x7F120001)])
    assert problems(make_apk(tmp_path / "r.apk", m))


def _fake_release_checkout(tmp_path):
    """A stand-in `main` checkout for `om release`: gradlew writes an empty APK, fly.toml pins a key."""
    repo = tmp_path / "repo"
    (repo / "android" / "app" / "build" / "outputs" / "apk" / "release").mkdir(parents=True)
    (repo / "scripts").mkdir()
    (repo / "deploy").mkdir()
    gradlew = repo / "android" / "gradlew"
    gradlew.write_text("#!/bin/sh\ntouch app/build/outputs/apk/release/app-release.apk\n")
    gradlew.chmod(0o755)
    (repo / "fly.toml").write_text('[build.args]\nOPENMOB_RELEASE_SIGNERS = "ab" \n')
    (repo / "scripts" / "check_release_apk.py").write_text(
        "import os, sys\nprint('signers=' + os.environ.get('OPENMOB_RELEASE_SIGNERS', ''))\n")
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
                    "--allow-empty", "-m", "x"], check=True)
    envs = tmp_path / "envs"
    envs.mkdir()
    (envs / "release-signing.properties").write_text("")
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "OPENMOB_STANDARD_DIR": str(repo),
           "OPENMOB_ENVS_HOME": str(envs)}
    return repo, env


def test_om_release_says_python_is_too_old_instead_of_no_key_pinned(tmp_path):
    """On Python < 3.11, `om release` used to swallow the tomllib error and report that no release key is pinned."""
    repo, env = _fake_release_checkout(tmp_path)
    shim = tmp_path / "bin"
    shim.mkdir()
    (shim / "python3").write_text("#!/bin/sh\n"
                                  'case "$*" in *version_info*) exit 1;; *--version*) echo "Python 3.10.9";; esac\n'
                                  "exit 0\n")
    (shim / "python3").chmod(0o755)
    env["PATH"] = f"{shim}:{env['PATH']}"
    r = subprocess.run(["bash", str(ROOT / "scripts" / "om"), "release"], env=env, capture_output=True, text=True)
    assert r.returncode != 0
    assert "Python 3.11+ is needed to read the pinned release key from fly.toml" in r.stderr
    assert "3.10.9" in r.stderr and not (repo / "deploy" / "OpenMob.apk").exists()


def test_om_release_reads_the_pin_from_fly_toml(tmp_path):
    repo, env = _fake_release_checkout(tmp_path)
    shim = tmp_path / "bin"
    shim.mkdir()
    (shim / "python3").symlink_to(sys.executable)  # this test run's Python (3.11+), not the system one
    env["PATH"] = f"{shim}:{env['PATH']}"
    r = subprocess.run(["bash", str(ROOT / "scripts" / "om"), "release"], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "signers=ab" in r.stdout and (repo / "deploy" / "OpenMob.apk").exists()
