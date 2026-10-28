# OpenMob

**Let AI agents use your Android phone: one self-hosted server, a REST API and an MCP endpoint.**

[![CI](https://github.com/andkhong/openmob/actions/workflows/ci.yml/badge.svg)](https://github.com/andkhong/openmob/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

OpenMob runs a goal on a real phone with its own agent ("open Settings and go to Display"), or lets *your* agent
observe and operate the phone step by step over MCP. A companion app on the phone connects out to your server, reads
the screen through Android Accessibility, and checks every action **on the phone** before it happens.

> “Open Settings and go to Display.” · “Search YouTube for lo-fi.” · “Open Maps and find Golden Gate Park.”

> [!WARNING]
> OpenMob gives an AI agent control of a real Android phone: it opens apps, taps, types and reads the screen, and
> screen content goes to the AI providers you configure. **Use a test phone or an emulator**, not the phone you rely
> on, and read [Safety](docs/safety.md) first.

**Status:** early and self-hosted. It works on real apps on real phones, but reliability depends on the app, its
layout and the model you use. Expect rough edges; issues and pull requests are welcome.

## Features

- **Pair a phone in a minute.** Scan a QR code (or type a short code) and confirm with the phone's screen lock. After
  that it connects over Wi-Fi or mobile data: no USB cable or ADB for everyday use.
- **Ask from anywhere.** Type or speak a request on the phone or the web dashboard, watch each step and the live
  screen, answer the agent's questions, and stop it at any time.
- **Bring your own agent (MCP).** Delegate a goal with `run_task`, or open a *drive session* and let your agent
  observe, tap, type, scroll, launch apps and wait for the screen, with its own reasoning.
- **REST API.** Scoped API keys, tasks, live server-sent events, cancellation, history, screenshots, webhooks, rate
  limits, quotas and an audit log.
- **Any model.** Anthropic, OpenAI, Google, Qwen, xAI and any OpenAI-compatible endpoint.
- **Fast where it can be.** Direct jumps to Settings pages and in-app links, waits on real screen conditions, and an
  optional classifier for well-labelled screens, so many steps need no model call.
- **Safety on the phone.** The app's gatekeeper judges each action against the actual screen: it blocks banking,
  wallet, password and authenticator apps (plus any you add), refuses security-critical Settings, and asks you before
  risky actions such as sending, buying or installing.
- **Many phones.** Accounts own their phones; orchestrations run tasks across phones and pass results between them.
- **Optional extras:** preferences memory ("text my sis" knows who your sister is; off by default), an ADB backend
  for development, and an experimental iPhone bridge on a Mac.

## How it works

```text
 Dashboard / phone app           Your code or AI agent
            │                     │  REST /v1 · MCP /mcp
            └──────────┬──────────┘
                       ▼
                OpenMob server ── AI model providers
       accounts · API keys · tasks · approvals
                       │
        built-in agent  or  your agent's drive session
                       │  outbound WebSocket from the phone
                       ▼
           Android companion app
   Accessibility · screen · on-phone gatekeeper
                       │
                       ▼
                   Your apps
```

The server never gets the last word: it may be misconfigured or compromised, so the phone enforces its own rules,
and approvals happen on the phone with its screen lock. See [Architecture](docs/architecture.md) and
[the phone gatekeeper](docs/design/phone-gatekeeper.md).

## Quick start

You need **Python 3.11+**, an API key for at least one model provider, and an **Android 11+** phone (ARM64) with a
screen lock, or an emulator. Building the app needs **JDK 17** and the **Android SDK (API 35)**.

```sh
# 1. Get the code and add one model key
git clone https://github.com/andkhong/openmob.git && cd openmob
cp .env.example .env          # then set at least one key, e.g. ANTHROPIC_API_KEY (the default models are Claude)
chmod 600 .env                # OpenMob refuses a .env that other users can read

# 2. Install
python3 -m venv .venv && source .venv/bin/activate
pip install -e .              # add '.[openai,gemini]' for OpenAI, Gemini, Qwen, xAI or compatible endpoints

# 3. Build the phone app (the server offers it at /download/openmob.apk)
(cd android && ./gradlew assembleDebug)

# 4. Create your account and start the server
openmob account add you@example.com --password-file ~/.openmob-password   # creates the password if the file is missing
openmob run --accounts --no-adb --public     # --public gives you an HTTPS address via a Cloudflare quick tunnel

# 5. In a second terminal (same folder and virtualenv): a one-time sign-in link
openmob account link you@example.com
```

Open the link, choose **Connect a phone**, install the app from the pairing page, and scan the QR code (or tap
**Type a code instead** in the app). Confirm with the phone's screen lock, finish the short setup checklist
(Accessibility, notifications, background running), and send your first request.

- `--public` needs [`cloudflared`](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/).
  Without it the dashboard is at `http://localhost:8765` and phones need another way in (your own HTTPS reverse
  proxy, or plain `http://` on your own network with a debug build).
- Keys live in `.env` (read as data, never executed; only the names in [.env.example](.env.example) are accepted;
  a variable already set in your shell wins). Never commit it.
- Sign-up is invite-only: `openmob account invite` makes a one-time code for someone else.
- More: [Self-hosting](docs/self-hosting.md) (HTTPS, hosting, storage, backups, configuration),
  [Phone setup](docs/phone-setup.md), [Quickstart for the API](docs/quickstart.md).

## Use it from code or an agent

Create an API key on the dashboard under **Developer API › API keys**. Default scopes list phones and run and read
tasks; screenshots and drive sessions need explicit scopes.

**MCP:** point your client at `https://<your-server>/mcp` (Streamable HTTP) with the header
`Authorization: Bearer <your-api-key>`. For clients that launch a local stdio server, set `OPENMOB_SERVER` and
`OPENMOB_API_KEY` and run `openmob mcp`. See [MCP tools and examples](docs/mcp.md).

**REST:**

```sh
export OPENMOB_SERVER="https://<your-server>"
export OPENMOB_API_KEY="<your-api-key>"

curl -sS "$OPENMOB_SERVER/v1/devices" -H "Authorization: Bearer $OPENMOB_API_KEY"

curl -sS -X POST "$OPENMOB_SERVER/v1/devices/<device-id>/tasks" \
  -H "Authorization: Bearer $OPENMOB_API_KEY" -H "Content-Type: application/json" \
  -d '{"instruction":"Open Settings and go to Display","tier":"fast"}'
```

Follow `/v1/tasks/<task-id>/events` for live events. A task can pause for your answer or an approval on the phone;
disconnecting your client doesn't cancel it. See the [REST reference](docs/api.md), [code examples](docs/examples.md),
[webhooks](docs/webhooks.md) and [errors and limits](docs/errors.md).

## Model providers

| Provider | Variable (in `.env`) |
|---|---|
| Anthropic (default) | `ANTHROPIC_API_KEY` |
| OpenAI | `OPENAI_API_KEY` |
| Google | `GEMINI_API_KEY` or `GOOGLE_API_KEY` |
| Qwen | `QWEN_API_KEY` or `DASHSCOPE_API_KEY` |
| xAI | `XAI_API_KEY` |
| OpenAI-compatible endpoint | `OPENAI_COMPATIBLE_BASE_URL`, plus `OPENAI_COMPATIBLE_API_KEY` if it needs one |

Install the extras with `pip install -e '.[openai,gemini]'` (Qwen, xAI and compatible endpoints use the `openai`
extra). The default models and API tiers (`fast`, `balanced`, `best`) use Anthropic; to use another provider, copy
`config.example.yaml` to `config.yaml` and change the mapping ([Model providers](docs/self-hosting.md#model-providers)).

> [!NOTE]
> **Jev (TypeSafe) is an optional third-party service.** With `TYPESAFE_API_KEY` set, its classifier receives the
> screen's text on each step, and, only if you turn on Faster mode on the phone, small screenshots of some screens.
> Leave it blank and OpenMob uses your model provider alone. On macOS, `pip install -e '.[mac]'` adds Apple Vision
> OCR for canvas screens.

## Safety and privacy

OpenMob's Accessibility service can see and operate other apps, so pairing a phone grants a lot of access.

- **The phone checks every action itself.** It refuses blocked apps (banking, wallet, password managers,
  authenticators, and any you add), typing into password fields, unsafe links and security-critical Settings. These
  checks live in the Android app; the ADB and iPhone development backends don't have them.
- **Approvals happen on the phone.** Risky actions ask for a tap; purchases and dangerous actions need your
  fingerprint or PIN. An outside agent can't answer "yes" for you.
- **You stay in control.** Stop from the phone, the dashboard or the API; unpair a phone or revoke a key to cut off
  access.
- **Screen content leaves the phone.** Screens are sent to the AI providers you configure (and to TypeSafe if you
  enable Jev). OpenMob doesn't keep screenshots; task text, results and step records are kept for 30 days by
  default, with typed text redacted.
- **Guardrails have limits.** Screen content is untrusted input; these checks reduce, but can't rule out, prompt
  injection or unintended actions.

Details: [Safety, approvals and data handling](docs/safety.md). Found a vulnerability? Please report it privately:
see [SECURITY.md](SECURITY.md).

## Limitations

- The phone must be awake and unlocked; OpenMob never bypasses the screen lock.
- Unlabelled controls, animations and game or canvas screens are harder; real-time gameplay is out of scope.
- Secure screens can appear black in captures. Live video needs Android's screen-sharing consent; tasks don't.
- One server process per data directory; no horizontal scaling yet.
- iPhone support is an experimental Mac + Xcode + WebDriverAgent bridge, not an iPhone app ([iOS](docs/ios.md)).

## Build the app for distribution

Debug builds are for your own test phones. To give the app to others, make your own signing key
(`scripts/om keygen`), build `assembleRelease` in `android/`, and point the app at your server with
`-POPENMOB_DEFAULT_SERVER=https://your.server` (release builds require `https://`). Serve your APK with
`OPENMOB_APK`, and pin your key's certificate SHA-256 in `OPENMOB_RELEASE_SIGNERS` so the server refuses any other
build. See [Release signing](docs/release-signing.md) and
[Build the app for your server](docs/self-hosting.md#build-the-app-for-your-server).

## Contributing

```sh
pip install -e '.[dev,openai,gemini]'
python -m pytest -q                                   # server tests
cd android && ./gradlew testDebugUnitTest assembleDebug lintDebug   # app tests (JDK 17)
```

For development without the app, `openmob doctor`, `openmob do "Open Settings and go to Display"` and `openmob run`
drive a phone over ADB. Read [CONTRIBUTING.md](CONTRIBUTING.md) first: gatekeeper changes need tests in both the
Kotlin app and the Python reference engine, and secrets never go in commits. See also [Testing](docs/testing.md) and
[the phone protocol](docs/phone-protocol.md).

| Path | What's there |
|---|---|
| `android/` | Companion app, Accessibility actions, approvals, on-phone gatekeeper |
| `openmob/agent/` | Built-in agent, drive sessions, links, navigation shortcuts |
| `openmob/platform/` | REST, MCP, orchestrations, webhooks |
| `openmob/phone/` | Phone drivers: remote (the app), ADB, iOS |
| `openmob/static/` | Dashboard, pairing, developer console |
| `tests/` | Server tests, gatekeeper fixtures, adversarial harness |

## License

[MIT](LICENSE) © 2026 andkhong.

The phone app bundles IBM Plex Sans and IBM Plex Mono (© 2017 IBM Corp., Reserved Font Name "Plex") under the SIL
Open Font License 1.1, shipped as `android/app/src/main/assets/licenses/ibm-plex-ofl.txt`. Sources: Plex Sans 3.005
from the official IBM release (`@ibm/plex-sans@1.1.0`) and Plex Mono 2.3 from the Google Fonts repository
(`ofl/ibmplexmono`); the font files are unmodified apart from their names.
