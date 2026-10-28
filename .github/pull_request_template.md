## What and why

## How it was tested

## Checklist

- [ ] No secrets: no API keys, passwords, tokens, signing keys, `.env` / `config.yaml` contents, or personal data (emails, phone serials, screenshots of a personal phone) in the diff or the description
- [ ] `python -m pytest -q` passes
- [ ] Android changes: `./gradlew testDebugUnitTest lintDebug` passes (in `android/`)
- [ ] Gatekeeper changes: made in both the Kotlin gatekeeper and `tests/gatekeeper_ref.py`, with scenarios in `tests/fixtures/gatekeeper/build.py` and the regenerated JSON committed
- [ ] Phone-side changes tried on a test phone or emulator (which one: )
- [ ] Docs updated where behaviour, the API, the phone protocol or configuration changed
