# Run your own server

Throughout these docs, `<server>` is the address of an OpenMob server: the dashboard, the phones'
connections, the REST API (`/v1`), the MCP server (`/mcp`) and these docs all live there. In the
developer console, `<server>` is already replaced with the server you're on.

The project's own hosted server is invite-only. To use OpenMob otherwise, you run a server yourself
(or use one that someone runs for you). One server can hold many accounts, each with its own phones
and API keys.

**OpenMob drives a real phone.** The agent taps, types and opens apps on every phone paired to your
server, and screen content goes to the model providers you configure. Use a test phone while you
evaluate it, and read [Safety, approvals, and data handling](safety.md).

## Quick start

You need Python 3.11 or newer and an API key for at least one AI model provider.

```sh
git clone https://github.com/andkhong/openmob.git && cd openmob
cp .env.example .env                        # then fill in at least one model key: see Model providers
chmod 600 .env                              # a .env other users can read is refused
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
(cd android && ./gradlew assembleDebug)     # the phone app (JDK 17, Android SDK 35): see The phone app

openmob account add you@example.com --password-file ~/.openmob-password
openmob run --accounts --no-adb --public
```

Then, in a second terminal, `openmob account link you@example.com` prints a one-time sign-in link;
open it and choose **Connect a phone** ([Set up a phone](phone-setup.md)).

### The .env file

`openmob` reads `.env` from the directory you run it in, or the file you name with
`openmob --env-file PATH <command>`. `.env.example` in the repository lists every variable it
accepts, grouped and commented: model keys (at least one is required), the optional Jev classifier,
server settings (`OPENMOB_PUBLIC_URL`, `OPENMOB_DATA_DIR`, `OPENMOB_APK`, `OPENMOB_MEMORY`, …) and
release signing. The file is parsed as data (`NAME=value` or `export NAME=value`, shell quoting,
`#` comments) and never run. Any other variable name, or a file that other users can read, stops the
command with a message and loads nothing; the message never shows a value. A variable already set
in the environment wins over the file, so `fly secrets`, Docker `-e` or your shell can override it.
`.env` and `.env.*` are in `.gitignore` and `.dockerignore`.

`config.yaml` is optional: copy `config.example.yaml` to change models, tiers and limits
([Configuration](#configuration)).

| Flag | Does |
|---|---|
| `--accounts` | Accounts mode: people sign in, phones pair to their owner's account, and the developer API and MCP server are on. **Required for `/v1` and `/mcp`** |
| `--no-adb` | Only use phones that connect in with the OpenMob app, not phones plugged into this computer |
| `--public` | Also publish the server over HTTPS through a Cloudflare quick tunnel (needs `cloudflared` installed), and print the public link |
| `--quiet` | Don't speak replies aloud on this computer |

The server listens on port 8765 by default (`server_port` and `server_host` in `config.yaml`).

## Accounts

Create the first account and sign in from the server's command line:

```sh
openmob account add you@example.com --password-file ~/.openmob-password   # generates one if the file is missing
openmob account link you@example.com     # prints a one-time sign-in link
openmob account invite                   # prints a one-time invite (link and code) for someone else
openmob account admin you@example.com    # optional: the /admin page (kill switches, audit log)
openmob key create you@example.com --name my-agent   # an API key, without the web console
```

Nobody can create an account without an invite. Someone you invite opens the invite link (or enters
the code at Log in → "Have an invite code?", or in the OpenMob app's Create account), then picks
their own email and password. Each code works once and expires after 7 days; only its hash is stored.

Admin rights can only be granted from the server's command line. An admin can switch off any API
key or a whole account's API access from `/admin`.

## HTTPS and reachability

Phones, webhooks and AI providers all need to reach or be reached over HTTPS:

- **Phones** connect from anywhere, so the server needs a public address. The pairing QR code
  doesn't work from a `localhost` address. The QR code carries your server's address; a typed
  pairing code doesn't, so on the phone tap **More options** › **Your own server** and enter the
  server's address first (`https://`, or plain `http://` only on your own network), then type the
  code from your server's Connect page.
- **Webhooks** are only delivered to public `https://` URLs.
- **The Claude API's MCP connector and the OpenAI API's MCP tool** call `https://<server>/mcp` from
  the provider's own servers, so `<server>` must be reachable from the internet over HTTPS.
  Local clients (Claude Code, Cursor, `openmob mcp`) only need to reach it from your machine.

`--public` gives you an HTTPS address without any setup, at a random `trycloudflare.com` name that
stays the same across restarts of the server while the tunnel keeps running. For a permanent
address, put the server behind your own HTTPS reverse proxy or host it (below).

## Model providers

The server's operator chooses which AI model providers run tasks, and which model serves each tier
(`fast`, `balanced`, `best`). Provider keys go in `.env` or the server's **environment**, never in
`config.yaml`:

| Variable | Provider |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic |
| `OPENAI_API_KEY` | OpenAI (`pip install -e '.[openai]'`) |
| `GEMINI_API_KEY` or `GOOGLE_API_KEY` | Google (`pip install -e '.[gemini]'`) |
| `OPENAI_COMPATIBLE_API_KEY` | Any OpenAI-compatible endpoint, including local models |

Map the tiers to models with `api_tiers` in `config.yaml` (see `config.example.yaml`). API
callers only ever see the tier names, never which model or provider runs them.

The dashboard's model picker includes Claude, GPT-6.1 Sol, GPT-6 Astra, GPT-6 Luna, Gemini 3.8 Flash,
Qwen 3.8 Flash, and Grok 4.7 by default, grouped by provider. OpenAI's models use `OPENAI_API_KEY`;
Gemini uses `GEMINI_API_KEY` (or `GOOGLE_API_KEY`); Qwen uses `QWEN_API_KEY` (or `DASHSCOPE_API_KEY`);
Grok uses `XAI_API_KEY`. Qwen and Grok use the OpenAI SDK. Install the SDKs with
`pip install -e '.[openai,gemini]'`, set the keys
in `.env` or the server's environment, and restart the server. The Docker image includes both SDKs.
Models without a configured provider key stay visible but disabled. ChatGPT/Codex, Gemini, Qwen and Grok app
subscriptions do not configure these API connections.

An explicit `models:` list replaces the defaults; add the desired entries from `config.example.yaml`
if you maintain a custom allowlist. GPT-6 and Codex model IDs use OpenAI's Responses API, retaining
encrypted reasoning between tool calls with response storage disabled. Other OpenAI models and
OpenAI-compatible endpoints keep the existing Chat Completions path. The default Gemini model
uses low thinking; the new reasoning models have an 8192-token budget for thinking and tool output,
overriding the usual 512-token vision-step cap. These settings can be changed per model.

Qwen uses Model Studio's OpenAI-compatible Chat Completions API with thinking disabled for the
synchronous phone loop. Its default endpoint is Singapore:
`https://dashscope-intl.aliyuncs.com/compatible-mode/v1`. Set `QWEN_BASE_URL` (or `qwen_base_url`
in YAML) to the [endpoint for your API key's region/workspace](https://www.alibabacloud.com/help/en/model-studio/base-url).
Grok uses xAI's Responses API at `https://api.x.ai/v1`, with low reasoning and encrypted reasoning
preserved between steps; override it with `XAI_BASE_URL` or `xai_base_url`. Each model can also
override its `base_url` and `api_key_env`. Local Qwen deployments still use `provider: openai_compatible`
with their own endpoint and capabilities, as shown in `config.example.yaml`.

Model call timeouts: calls to the hosted providers (Anthropic, OpenAI, Google, xAI) time out after 20 s
for a vision step (60 s for a bigger call). A connection failure, 429 or overload is tried up to 3 more times
with growing waits, a timeout once more (`model_timeout_s`, `model_timeout_long_s`, `model_retries`). `openai_compatible` and `qwen`
keep the SDK's own behaviour (600 s, 2 retries), because a local vision model can take longer than 20 s on a
screenshot. To give them the same limits, set `model_timeout_self_hosted: true`, or set
`OPENMOB_MODEL_TIMEOUT_S` (which then applies to every provider).

Model/API references: [GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol),
[GPT-6 Astra](https://developers.openai.com/api/docs/models/gpt-6-astra),
[GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna), and
[Gemini 3.8 Flash](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash),
[Qwen vision and tools](https://www.alibabacloud.com/help/en/model-studio/vision-model), and
[Grok 4.7](https://docs.x.ai/developers/grok-4-7).

## Configuration

`config.yaml` is read from the current directory, then `~/.config/openmob/config.yaml` (or pass
`openmob -c path/to/config.yaml run …`). The settings that shape the developer API:

| Setting | Default | Meaning |
|---|---|---|
| `api_tiers` | `fast` 1, `balanced` 3, `best` 10 credits per step | Tier name → `{model, credits_per_step}` |
| `api_default_tier` | `balanced` | Tier for tasks that don't name one |
| `api_rate_per_minute` | 60 | Requests per API key per minute |
| `api_max_concurrent_tasks` | 2 | Unfinished tasks per key |
| `api_daily_tasks` | 200 | Tasks per key per UTC day |
| `api_daily_credits` | 0 (no limit) | Credits per key per UTC day |
| `api_max_steps` | 40 | The most steps a task may take |
| `api_max_running_orchestrations` | 3 | Multi-phone runs in progress per key |
| `api_max_running_orchestrations_per_account` | 10 | … per account |
| `question_timeout_seconds` | 300 | A task whose question nobody answers ends after this long (0: never) |
| `sensitive_apps` | banking, payment, wallet, crypto, password and authenticator apps | Package-name patterns API tasks may not open unless the phone's owner allows it |
| `confirm_actions` | `unrequested` | Ask before risky taps the instruction didn't ask for (`always`: every risky tap; `never`: none) |
| `confirm_keywords` | buy, pay, send, delete, … | Words that make a tap risky |
| `default_permission_mode` | `auto` | A phone's [permission mode](safety.md#permission-modes) until its owner picks one: `ask`, `plan` or `auto` (looser modes need the phone's own approval) |
| `money_keywords` | buy, pay, order, checkout, … | Payment words: they ask even when requested and are refused under Don't ask (unless the owner allowed purchases with it) |
| `confirm_skip_phrases` | add to cart, proceed to checkout, … | Steps on the way to a commit point, never asked about |
| `settings_refuse_terms`, `settings_everyday_terms`, `settings_ask_terms` | see `openmob/permissions.py` | The Settings tiers: refused, never asked, asked |
| `app_categories` | messaging, email, social, notes, photos | Categories a trusted entry may name (package-name parts). A `games` entry also counts those apps as games for Faster mode's sparse screens |
| `history_retention_days` | 0 (keep forever) | Delete chats (task text and outcomes) not used for this many days |

The developer console's **Overview** page shows each account the tiers and limits in effect.

## The phone app

The server offers the Android app at `/download/openmob.apk`. Build it from `android/` in the
repository (`./gradlew assembleDebug`); the server finds the debug build there, or set
`OPENMOB_APK` to the APK's path. See [Set up a phone](phone-setup.md) for what phone owners do.

A debug build is fine for your own phones, but it is debuggable (anyone with USB access to a phone
can read the app's device key) and signed with an unprotected key. To offer the app to other people,
sign a release build with your own key (`scripts/om keygen`, then `./gradlew assembleRelease` in
`android/`) and pin that key's certificate SHA-256 in `OPENMOB_RELEASE_SIGNERS`; see
`docs/release-signing.md` in the repository. The Docker image (below) only accepts a release build
signed by a pinned key, and with no key pinned it serves no app at all.

### Build the app for your server

The app has a built-in default server: where a typed pairing code goes unless the phone's owner taps
**More options** › **Your own server** and enters another. (A QR code always carries your server's
address, so scanning works with any build.) The default is the project's hosted server. To build an
app that defaults to yours, set `OPENMOB_DEFAULT_SERVER` as a Gradle property or environment
variable:

```sh
cd android
./gradlew assembleDebug -POPENMOB_DEFAULT_SERVER=https://openmob.example.com
# or: OPENMOB_DEFAULT_SERVER=https://openmob.example.com ./gradlew assembleRelease
```

It must be a bare address (`https://host` or `https://host:port`, no path); the build fails
otherwise. Release and local (signed) builds need an `https://` address and fail to build with
`http://`; a debug build may use `http://` (an emulator against your computer:
`-POPENMOB_DEFAULT_SERVER=http://10.0.2.2:8765`). A release build only connects over `https://`.

## Storage and backups

Everything lives in one data directory: `~/.config/openmob`, or `OPENMOB_DATA_DIR` if set.

| File | Holds |
|---|---|
| `accounts.json` | Accounts, paired phones, API key hashes, webhook URLs and signing secrets, settings |
| `ledger.sqlite` | API tasks, credits, the audit log, the webhook outbox, idempotency keys, orchestrations |
| `history.sqlite` | Chat history: the text of tasks and their outcomes |

Back up the whole directory, with the server stopped or using SQLite's online backup
(`sqlite3 ledger.sqlite ".backup ledger.bak"`). `accounts.json` contains secrets (webhook signing
secrets, phone keys): keep backups private.

## One server at a time

Run **one server process per data directory**. Phones hold a live connection to the process they
connected to, running tasks live in its memory, and per-key limits are counted in memory, so
OpenMob doesn't support several servers behind a load balancer yet. Restarting the server ends the
tasks that were running (they fail with `outcome.reason: "server_restarted"` and cost nothing);
phones reconnect by themselves.

## Hosting

The repository includes a `Dockerfile` and a `fly.toml` for [Fly.io](https://fly.io): one always-on
machine with a volume mounted at `/data` (`OPENMOB_DATA_DIR`), running
`openmob run --no-adb --quiet --accounts` on port 8080. Set the provider keys as secrets
(`fly secrets set ANTHROPIC_API_KEY=…`), and don't let the platform stop idle machines: phones
keep a WebSocket open to it. The `fly.toml` in the repository is the project's own hosted server:
for yours, change `app`, `OPENMOB_PUBLIC_URL`, `OPENMOB_INVITE_EMAIL` and the
`OPENMOB_RELEASE_SIGNERS` build arg (your release key's SHA-256).

The image serves `deploy/OpenMob.apk` to phones, and its build fails unless that file is a release
build of the app: not debuggable, https only, not signed with an Android debug key. The server
checks again before serving it (`OPENMOB_REQUIRE_RELEASE_APK=1`). To knowingly serve a debug build
from your own image, build with `--build-arg OPENMOB_REQUIRE_RELEASE_APK=0`. Otherwise pass your
release key's certificate SHA-256: `--build-arg OPENMOB_RELEASE_SIGNERS=<sha256>` (the build fails
without it).

On your own domain, set `OPENMOB_PUBLIC_URL` (one or more URLs, comma-separated, e.g.
`https://openmob.example.com, http://192.168.1.20:8765`) so the agent refuses to open your dashboard on the phone.
Every address your dashboard answers at belongs there: the server never learns one from a request's `Host` or
`X-Forwarded-Host` (a client could name any site). On Fly, `<FLY_APP_NAME>.fly.dev` counts without it; the
`openmob run --public` tunnel, localhost, `10.0.2.2` and this machine's name and LAN address count too.

The phone's own check (its gatekeeper refuses to act while a browser's address bar shows the server) knows only the
host the phone paired with. If your dashboard also answers at another domain or a LAN address, only the server's
check covers that one.
