# Security policy

OpenMob lets an AI agent operate a real Android phone. A bug here can mean someone else controls a phone, reads
what is on its screen, or gets past an approval the owner never gave, so we take security reports seriously and
prioritise them over feature work.

## Reporting a vulnerability

**Please report privately. Don't open a public issue, pull request or discussion for a vulnerability.**

Use GitHub's private vulnerability reporting: open this repository's **Security** tab and click
**Report a vulnerability**. The report is visible only to the maintainers, and we can work on a fix and an
advisory with you there.

If you can't use GitHub, email **andkhong@gmail.com** with "OpenMob security" in the subject.

Please include:

- what an attacker can do, and what they need first (a network position, an API key, a paired phone, an app
  installed on the phone, a malicious web page or screen content, …);
- the component and version (commit hash, or the app's version from Settings › About);
- steps to reproduce or a proof of concept. Test against **your own server and a test phone or emulator**, never
  against someone else's server, phone or account.

Please don't include real API keys, passwords, or screenshots of a personal phone.

## What to expect

We aim to acknowledge a report within a few days, keep you updated while we work on it, and credit you in the
advisory if you'd like. Please give us a reasonable time to ship a fix before disclosing publicly.

## Scope

In scope:

- **The server** (`openmob/`): accounts and sign-in, phone pairing, API keys and scopes, the REST API (`/v1`), the
  MCP server (`/mcp`), the dashboard and developer console, webhooks, the agent loop, and how screen content and
  task data are stored and sent to model providers.
- **The Android app** (`android/`, `dev.openmob.companion`): the Accessibility service, the connection to the
  server, pairing, approvals and the screen-lock checks, the device key, and app updates.
- **The on-phone gatekeeper** (`android/.../gate/`, `rules.json`, and the Python reference in
  `tests/gatekeeper_ref.py`): any way to make the phone perform an action it should refuse or ask about (blocked
  apps, password fields, purchases, security settings, unsafe links), including through screen content, prompt
  injection or a compromised server. The gatekeeper is designed to protect the phone even from its own server.
- The release-APK checks (`openmob/apk_check.py`), the Docker image and `scripts/`.

Phone-control issues (an action taken without the owner's approval, a stop that doesn't stop, a phone controlled
by the wrong account) are treated as high severity.

Out of scope: vulnerabilities in third-party model providers, TypeSafe, Fly.io or Android itself (report those to
them); attacks that need the phone already unlocked in an attacker's hands with the owner's screen lock known;
and the known limitations documented in [docs/safety.md](docs/safety.md) (for example, risky controls the
gatekeeper can't recognise), unless you find a practical way to exploit them beyond what is documented.

## Supported versions

Security fixes go to the `main` branch. Self-hosters should update their server and rebuild the app from `main`.
