"""Is this APK fit to hand out from a hosted server? Stdlib only, so it also runs as a plain script
(`python -I scripts/check_release_apk.py <apk>`, the Docker build and `om release`).

Refuses an APK that is debuggable, allows cleartext http, is signed with an Android debug key (or
not signed at all), is signed by any key but a pinned release key (OPENMOB_RELEASE_SIGNERS; none pinned refuses every APK), or isn't OpenMob's package. A debug build lets anyone with USB access read the
app's device key (`run-as`), and its key is unprotected: whoever copies it can sign an update that
installs over the app. docs/release-signing.md.
"""
from __future__ import annotations

import hashlib
import os
import struct
import sys
import zipfile
from dataclasses import dataclass, field

PACKAGE = "dev.openmob.companion"
DEBUG_CN = "Android Debug"
ATTR_DEBUGGABLE = 0x0101000F
ATTR_USES_CLEARTEXT = 0x010104EC
ATTR_VERSION_CODE = 0x0101021B
# A network security config can re-allow cleartext per domain; it isn't parsed, so any is refused (review 5 W5-L1).
ATTR_NETWORK_SECURITY_CONFIG = 0x01010527
SIGNATURE_SCHEMES = {0x7109871A: "v2", 0xF05368C0: "v3", 0x1B93AD61: "v3.1"}
# The release keys' certificate SHA-256s (v2/v3 APK Signing Block, as check_release_apk.py prints them) come from
# OPENMOB_RELEASE_SIGNERS (comma-separated): each server pins its own key. None set: every APK is refused (fail
# closed). The hosted server's pin is a build arg in fly.toml.
NO_SIGNERS = ("no release key is pinned: set OPENMOB_RELEASE_SIGNERS to your release key's certificate SHA-256 "
              "(scripts/om keygen and scripts/check_release_apk.py print it; docs/release-signing.md)")
FIX = "Build the hosted download with the release key: scripts/om release (docs/release-signing.md)."


@dataclass
class Report:
    problems: list[str] = field(default_factory=list)
    signers: list[tuple[str, str, str]] = field(default_factory=list)  # (scheme, subject CN, cert SHA-256)

    @property
    def ok(self) -> bool:
        return not self.problems


def check_apk(path) -> Report:
    report = Report()
    try:
        with zipfile.ZipFile(path) as z:
            manifest = z.read("AndroidManifest.xml")
            v1 = [(n, z.read(n)) for n in z.namelist()
                  if n.upper().startswith("META-INF/") and n.upper().endswith((".RSA", ".EC", ".DSA"))]
        with open(path, "rb") as f:
            raw = f.read()
    except (OSError, zipfile.BadZipFile, KeyError) as e:
        report.problems.append(f"not a readable APK ({e})")
        return report
    try:
        _check_manifest(manifest, report)
    except (struct.error, IndexError, ValueError) as e:
        report.problems.append(f"AndroidManifest.xml couldn't be parsed ({e})")
    try:
        for scheme, cert in _signing_block_certs(raw):
            report.signers.append((scheme, ", ".join(_common_names(cert)) or "?", hashlib.sha256(cert).hexdigest()))
    except (struct.error, ValueError) as e:
        report.problems.append(f"the APK Signing Block couldn't be parsed ({e})")
    for name, blob in v1:
        report.signers.append((f"v1 {name}", ", ".join(_common_names(blob)) or "?", ""))
    if not report.signers:
        report.problems.append("the APK isn't signed")
    if any(DEBUG_CN in cn.split(", ") for _, cn, _ in report.signers):
        report.problems.append(f"it is signed with an Android debug key (CN={DEBUG_CN})")
    elif report.signers:
        # Phones verify v2/v3 only (minSdk 30), so a v1 signature can't stand in for the pinned key.
        pinned = release_signers()
        if not pinned:
            report.problems.append(NO_SIGNERS)
        elif not any(sha for _, _, sha in report.signers):
            report.problems.append("it has no v2/v3 signature to check against the release key")
        elif any(sha and sha not in pinned for _, _, sha in report.signers):
            report.problems.append("it is signed with a key that isn't the pinned release key (OPENMOB_RELEASE_SIGNERS)")
    return report


def release_signers() -> frozenset[str]:
    """The pinned release keys (OPENMOB_RELEASE_SIGNERS), lower-case; empty when none are set."""
    env = os.environ.get("OPENMOB_RELEASE_SIGNERS", "")
    return frozenset(x.strip().lower() for x in env.split(",") if x.strip())


# --- the binary manifest (AXML) -----------------------------------------------

def _elements(data: bytes):
    """Each start element of a binary manifest, in order: (element name, [(attribute name, resource id or None,
    its string or None, data type, value)]). Resource ids come from the resource map, so a renamed attribute
    is still recognised by its id."""
    strings: list[str] = []
    res_ids: list[int] = []
    pos = 8  # after the RES_XML_TYPE file header
    while pos + 8 <= len(data):
        ctype, hsize, size = struct.unpack_from("<HHI", data, pos)
        if size < 8:
            raise ValueError("bad chunk size")
        if ctype == 0x0001:
            strings = _string_pool(data, pos)
        elif ctype == 0x0180:
            res_ids = list(struct.unpack_from(f"<{(size - hsize) // 4}I", data, pos + hsize))
        elif ctype == 0x0102:  # start element
            name = strings[struct.unpack_from("<I", data, pos + 20)[0]]
            attr_start, attr_size, count = struct.unpack_from("<HHH", data, pos + 24)
            attrs = []
            for i in range(count):
                a = pos + 16 + attr_start + i * attr_size
                _, aname, raw, _, _, dtype, value = struct.unpack_from("<IIIHBBI", data, a)
                rid = res_ids[aname] if aname < len(res_ids) else None
                text = strings[raw] if raw != 0xFFFFFFFF else None
                if text is None and dtype == 0x03:  # TYPE_STRING: the value is a string pool index
                    text = strings[value]
                attrs.append((strings[aname], rid, text, dtype, value))
            yield name, attrs
        pos += size


def _check_manifest(data: bytes, report: Report) -> None:
    package = None
    for name, attrs in _elements(data):
        for aname, rid, text, dtype, value in attrs:
            if name == "manifest" and aname == "package":
                package = text
            if name != "application":
                continue
            if rid == ATTR_NETWORK_SECURITY_CONFIG or (rid is None and aname == "networkSecurityConfig"):
                report.problems.append("the manifest sets android:networkSecurityConfig (it could allow cleartext)")
            for attr_id, label in ((ATTR_DEBUGGABLE, "debuggable"), (ATTR_USES_CLEARTEXT, "usesCleartextTraffic")):
                if rid == attr_id or (rid is None and aname == label):
                    if dtype == 0x12 and value == 0:
                        continue  # false
                    if dtype == 0x12 or (text or "").lower() == "true":
                        report.problems.append(f"the manifest has android:{label}=true")
                    else:
                        report.problems.append(f"android:{label} isn't a plain false (type {dtype:#x})")
    if package != PACKAGE:
        report.problems.append(f"the package is {package!r}, not {PACKAGE}")


def manifest_version_code(data: bytes) -> int | None:
    """android:versionCode on <manifest> (by its resource id 0x0101021b, or by name without a resource map), or
    None when it's missing or not a plain integer."""
    for name, attrs in _elements(data):
        if name != "manifest":
            continue
        for aname, rid, text, dtype, value in attrs:
            if rid == ATTR_VERSION_CODE or (rid is None and aname == "versionCode"):
                if dtype in (0x10, 0x11):  # TYPE_INT_DEC, TYPE_INT_HEX
                    return value
                if text is not None and text.strip().isdigit():
                    return int(text.strip())
                return None
        return None
    return None


def version_code(path) -> int | None:
    """The APK's versionCode, or None when it can't be read (not an APK, no manifest, no versionCode)."""
    try:
        with zipfile.ZipFile(path) as z:
            manifest = z.read("AndroidManifest.xml")
        return manifest_version_code(manifest)
    except (OSError, zipfile.BadZipFile, KeyError, struct.error, IndexError, ValueError):
        return None


def _string_pool(data: bytes, pos: int) -> list[str]:
    _, hsize, _, count, _, flags, start, _ = struct.unpack_from("<HHIIIIII", data, pos)
    utf8 = bool(flags & 0x100)
    offsets = struct.unpack_from(f"<{count}I", data, pos + hsize)
    out = []
    for off in offsets:
        p = pos + start + off
        if utf8:
            p += 2 if data[p] & 0x80 else 1  # UTF-16 length, unused
            n = data[p]
            if n & 0x80:
                n, p = ((n & 0x7F) << 8) | data[p + 1], p + 2
            else:
                p += 1
            out.append(data[p:p + n].decode("utf-8", "replace"))
        else:
            n = struct.unpack_from("<H", data, p)[0]
            if n & 0x8000:
                n, p = ((n & 0x7FFF) << 16) | struct.unpack_from("<H", data, p + 2)[0], p + 4
            else:
                p += 2
            out.append(data[p:p + 2 * n].decode("utf-16-le", "replace"))
    return out


# --- signatures ---------------------------------------------------------------

def _signing_block_certs(raw: bytes) -> list[tuple[str, bytes]]:
    """The X.509 certificates of every v2/v3 signer, from the APK Signing Block before the central
    directory. An APK without the block (v1 only, or unsigned) gives none."""
    eocd = raw.rfind(b"PK\x05\x06", max(0, len(raw) - 65557))
    if eocd < 0:
        raise ValueError("no end of central directory")
    cd = struct.unpack_from("<I", raw, eocd + 16)[0]
    if cd < 24 or raw[cd - 16:cd] != b"APK Sig Block 42":
        return []
    size = struct.unpack_from("<Q", raw, cd - 24)[0]
    pos, end, certs = cd - size, cd - 24, []
    while pos + 12 <= end:
        length, block_id = struct.unpack_from("<QI", raw, pos)
        value = raw[pos + 12:pos + 8 + length]
        pos += 8 + length
        if block_id not in SIGNATURE_SCHEMES:
            continue
        for signer in _lp(_lp(value)[0]):  # a length-prefixed sequence of length-prefixed signers
            signed_data = _lp(signer, 1)[0]  # signer: signed data, signatures, public key
            _digests, cert_seq = _lp(signed_data, 2)  # signed data: digests, certificates, ...
            certs += [(SIGNATURE_SCHEMES[block_id], c) for c in _lp(cert_seq)]
    return certs


def _lp(buf: bytes, limit: int | None = None) -> list[bytes]:
    """u32-length-prefixed items of a signing block value (the first `limit` of them, if given)."""
    out, p = [], 0
    while p + 4 <= len(buf) and (limit is None or len(out) < limit):
        n = struct.unpack_from("<I", buf, p)[0]
        if p + 4 + n > len(buf):
            raise ValueError("truncated signing block")
        out.append(buf[p + 4:p + 4 + n])
        p += 4 + n
    if limit is not None and len(out) < limit:
        raise ValueError("short signing block")
    return out


def _common_names(der: bytes) -> list[str]:
    """Every commonName (OID 2.5.4.3) value in a DER blob: a certificate or a v1 PKCS#7 file."""
    names, p = [], 0
    while (p := der.find(b"\x06\x03\x55\x04\x03", p)) >= 0:
        p += 5
        if p + 2 <= len(der) and der[p] in (0x0C, 0x13, 0x14, 0x16, 0x1E) and der[p + 1] < 0x80:
            value = der[p + 2:p + 2 + der[p + 1]]
            names.append(value.decode("utf-16-be" if der[p] == 0x1E else "latin-1", "replace"))
    return sorted(set(names))


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: check_release_apk.py <apk>", file=sys.stderr)
        return 2
    report = check_apk(args[0])
    for scheme, cn, sha in report.signers:
        print(f"signer ({scheme}): CN={cn}" + (f"  SHA-256 {sha}" if sha else ""), flush=True)
    if report.ok:
        print(f"✓ {args[0]}: a release build of {PACKAGE}")
        return 0
    print(f"✗ {args[0]} is not a release build fit to serve:", file=sys.stderr)
    for problem in report.problems:
        print(f"  - {problem}", file=sys.stderr)
    print(FIX, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
