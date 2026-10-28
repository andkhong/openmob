#!/usr/bin/env python3
"""Refuse an APK that isn't a release build of OpenMob: debuggable, cleartext http, an Android debug
key or no signature, or another package. Prints the signer's SHA-256 (to pin later).

    python -I scripts/check_release_apk.py deploy/OpenMob.apk

The checks live in openmob/apk_check.py (stdlib only), which the hosted server also runs before it
serves the download; this loads that file by path, so it needs no install.
"""
import runpy
import sys
from pathlib import Path

if __name__ == "__main__":
    module = runpy.run_path(str(Path(__file__).resolve().parent.parent / "openmob" / "apk_check.py"))
    sys.exit(module["main"]())
