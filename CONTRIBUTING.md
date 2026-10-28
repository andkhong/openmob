# Contributing to OpenMob

Thanks for helping. OpenMob lets an AI agent operate a real Android phone, so changes are judged first on whether
they keep connecting a phone easy and secure, and agent access secure and fast.

## Ground rules

- **Never commit secrets.** API keys go in `.env` (git-ignored; see `.env.example`), never in code, tests,
  `config.yaml`, issues or pull requests. Signing keys and their properties files stay outside the repository.
  If you commit one by accident, revoke it first, then tell us.
- **Use a test phone or an emulator.** Don't develop against the phone you rely on: the agent taps and types on
  it, and debug builds of the app are debuggable.
- **Security issues go through [SECURITY.md](SECURITY.md)**, not public issues or pull requests.
- One change per pull request, on its own branch from `main`, with tests.

## Development setup

You need Python 3.11+ (CI uses 3.13), and for the app JDK 17 and the Android SDK with API 35.

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev,openai,gemini]'
cp .env.example .env && chmod 600 .env   # only needed to run the server against real models
```

The tests don't need any provider key or phone.

## Running the tests

```sh
python -m pytest -q                                   # from the repository root

cd android
./gradlew testDebugUnitTest lintDebug assembleDebug   # Kotlin unit tests, lint, the debug APK
```

Set `JAVA_HOME` to a JDK 17 and `ANDROID_HOME` (or `android/local.properties`) to your Android SDK. A few timing
tests can be flaky on a loaded machine (`test_timings.py`, `test_stop_latency.py`): re-run one alone before
treating it as a real failure. Keep `main` green: run the full pytest, and the Kotlin tests for Android changes,
before asking for review.

## Gatekeeper changes

The on-phone gatekeeper (`android/app/src/main/java/dev/openmob/companion/gate/`, with
`android/app/src/main/resources/gatekeeper/rules.json`) has a Python reference engine, `tests/gatekeeper_ref.py`.
Both run the same shared scenarios, so they can't drift apart. Any change to what the gatekeeper allows, asks
about or refuses needs:

1. the change in **both** the Kotlin gatekeeper and `tests/gatekeeper_ref.py`;
2. scenarios for it in `tests/fixtures/gatekeeper/build.py`, then regenerate the fixtures and commit the JSON:

   ```sh
   python tests/fixtures/gatekeeper/build.py
   ```

3. both suites passing: pytest (`tests/test_gatekeeper_*.py`) and the Kotlin tests (`GateScenarioTest` and friends).

Changes that loosen a check need a clear reason in the pull request. Changes to approvals, pairing, keys or
anything the phone trusts from the server get extra review.

## Pull requests

- Describe what changed and why, and how you tested it (which tests, and which phone or emulator if any).
- Update the docs in `docs/` when behaviour, the API, the phone protocol or configuration changes.
- Fill in the pull request checklist.
