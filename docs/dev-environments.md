# Development environments: standard and gatekeeper

Internal. Two local environments that never share code, Python packages or data, so two checkouts (for
example `main` and a branch under test) can be tested separately and switched on demand. The gatekeeper
code has been in `main` since 2026-10-10 (PR #26); the names are historical, and the two now differ only
in what they're checked out at and in their data.

| | standard | gatekeeper |
|---|---|---|
| Code | `~/Desktop/openmob` on `main` | `~/Desktop/openmob-gatekeeper`, a detached git worktree, at whatever is being tested |
| Python | its own `.venv` | its own `.venv` (an editable install of that folder, so it imports only its own code) |
| Data (accounts, history, ledger) | `~/.config/openmob` | `~/.config/openmob-gatekeeper` |
| Phone app | the standard build | built from that checkout (same app id: a phone holds one or the other) |

The server and the app must come from the same code: the phone protocol changes between versions, and
`om run` warns when the phone has the other environment's app.

## Setup (once)

```sh
git worktree add --detach ~/Desktop/openmob-gatekeeper main   # or the commit to test
cd ~/Desktop/openmob-gatekeeper
python3 -m venv .venv && .venv/bin/pip install -e .
cp ~/Desktop/openmob/config.yaml . && cp ~/Desktop/openmob/android/local.properties android/
# Start the gatekeeper data as a copy of the standard data, so the same account and phone pairing work
# in both (copy SQLite files with the backup API, or while no server is running).
```

## Daily use: `scripts/om`

```sh
om run standard            # start the standard server on port 8765 (one server at a time)
om run gatekeeper          # or the gatekeeper server
om run gatekeeper 8766     # both at once: a second port (pair a second device, e.g. the emulator, to it)
om phone standard          # install the standard app on the USB phone (om phone <env> <serial> for others)
om phone gatekeeper
om build gatekeeper        # rebuild an environment's app from its code (a debug build)
om build gatekeeper signed # the same, signed with the owner's key and not debuggable (docs/release-signing.md)
om update standard         # pull the latest main and refresh its packages
om status                  # what's checked out, which servers run, which app the phone has
```

`om update gatekeeper` still detaches the worktree at `origin/gatekeeper-p1`, an old branch: move the
gatekeeper worktree with git instead.

Switching: stop the running server (Control + C in its terminal; a server running in the background needs
SIGTERM), `om run <other>`, `om phone <other>`, then tap Connect in the app. `om run` loads
`<data>/provider-keys.env` (it must be mode 600; the same parser and allow-list as `.env`, `openmob/envfile.py`; a
variable already set in the terminal wins). Built apps and the record of what's on the phone live in
`~/.config/openmob-envs` (not in git). Paths can be changed with `OPENMOB_STANDARD_DIR`,
`OPENMOB_GATEKEEPER_DIR`, `OPENMOB_STANDARD_DATA`, `OPENMOB_GATEKEEPER_DATA` and `OPENMOB_ENVS_HOME`.

The two data directories diverge once used: pairing a phone again, or changing settings, in one
environment doesn't change the other.
