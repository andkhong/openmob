# OpenMob hosted server (Fly.io). Phones connect in with the OpenMob app; no adb, mic or OCR here.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    OPENMOB_DATA_DIR=/data \
    OPENMOB_APK=/app/OpenMob.apk

WORKDIR /app
COPY pyproject.toml README.md ./
COPY openmob ./openmob
# Public developer docs, served at /docs/{name} for the /developer console.
COPY docs/quickstart.md docs/concepts.md docs/phone-setup.md docs/api.md docs/mcp.md docs/examples.md \
     docs/webhooks.md docs/safety.md docs/conventions.md docs/errors.md docs/testing.md \
     docs/self-hosting.md ./docs/
RUN pip install ".[openai,gemini]"

COPY deploy/config.yaml ./config.yaml
COPY deploy/OpenMob.apk ./OpenMob.apk
# Phones download this file, so the image refuses to build around a debug or unsigned app, and the server
# refuses to serve one (OPENMOB_REQUIRE_RELEASE_APK). If this step fails, build the download with the
# release key (scripts/om release) and deploy again. A self-hosted image that knowingly serves a debug
# build: docker build --build-arg OPENMOB_REQUIRE_RELEASE_APK=0 (never for the hosted server).
ARG OPENMOB_REQUIRE_RELEASE_APK=1
ENV OPENMOB_REQUIRE_RELEASE_APK=$OPENMOB_REQUIRE_RELEASE_APK
# The release key's certificate SHA-256 (comma-separated for several). No default: an image built without one
# refuses every APK. The hosted server's is in fly.toml [build.args]; a self-hosted image passes its own:
# docker build --build-arg OPENMOB_RELEASE_SIGNERS=<sha256>[,<sha256>] (docs/release-signing.md).
ARG OPENMOB_RELEASE_SIGNERS=
ENV OPENMOB_RELEASE_SIGNERS=$OPENMOB_RELEASE_SIGNERS
COPY scripts/check_release_apk.py ./scripts/
RUN case "$(echo "$OPENMOB_REQUIRE_RELEASE_APK" | tr A-Z a-z)" in \
      1|true|on|yes) python -I scripts/check_release_apk.py OpenMob.apk ;; \
      0|false|off|no) echo "WARNING: OPENMOB_REQUIRE_RELEASE_APK=0: this image may serve a debug build of the app" ;; \
      *) echo "OPENMOB_REQUIRE_RELEASE_APK must be 1 or 0" >&2; exit 1 ;; esac

EXPOSE 8080
CMD ["openmob", "run", "--no-adb", "--quiet", "--accounts"]
