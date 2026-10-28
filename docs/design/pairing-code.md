# Typed pairing code (the fallback to the QR code)

Status: built and in `main` (2026-10-18): the server side on `feature/pairing-code` (2026-10-17), the
Android side in the redesigned setup (redesign step 4, `docs/design/redesign-setup.md`); reviewed in
security review 3 (§8), not yet tested on a real phone. Owner decisions: `docs/decisions.md`, 2026-10-17, "Pairing (redesign)" and its
conditions. Mockups: `SetupPair`, `SetupPairCode`, `SetupPairConfirm`, `SetupPaired`,
`SetupPairMore`, `SetupPairReplace` in the "Control Room" redesign.

## 1. The flow

1. The owner, **signed in on the dashboard**, opens **Connect a phone** and clicks "Can't scan?
   Show a code to type". The server makes a code such as `K7P-2QX` (`POST /api/pairing/code`).
   Only a dashboard session can: API keys reach `/v1` only, never `/api`, and `openmob phone add`
   keeps using QR-style codes.
2. The owner types it on the phone (Pairing › Type a code instead). The app sends
   `POST /api/pair/check {code, device_id, model}`.
3. The phone shows the confirm screen: the account email and the server in large text, with "Only
   pair with your own account. OpenMob will never ask you for a code." At the same moment the
   dashboard, polling `GET /api/pairing/code`, shows "A phone entered the code and is
   confirming: **Pixel 9 Pro**. Is that your phone?" with **Not my phone: cancel the code**.
4. The owner confirms with the screen lock. The app sends `POST /api/pair/claim` (same body as a QR
   claim). The phone gets a device key, exactly as with a QR code.
5. The phone posts the notification "Paired with … on … · Undo"; the dashboard shows "Paired:
   **SM-S948U1** · Undo".

## 2. Choices

| Rule | How | Why |
|---|---|---|
| Length and alphabet | 6 characters from `23456789ABCDEFGHJKMNPQRSTUVWXYZ` (31). Any case; spaces and an optional dash (`-` or a typographic dash) are ignored. Shown as `K7P-2QX`. | No 0/O or 1/I/L, which leaves 31 characters (owner, 2026-10-17: keep 31). 31^6 = 8.9 × 10^8 codes (29.7 bits). |
| Slot and secret | The first 2 characters pick one of 961 slots; the last 4 (923,521 values, 19.8 bits) are the secret. Minting picks a random slot from the free ones, or refuses (`429`, "scan the QR code") when none is free: it never retries at random. A claimed code leaves its slot at once (the dashboard's "Paired" status reads a separate per-account record, `typed_paired`, kept a day), so only waiting, cancelled or expired codes hold slots, and only until they expire. | A code that is only a secret can't count a wrong guess against any code, so "5 tries kill the code" would be impossible. With a slot, a wrong guess counts against the code it hit, so **each code gets at most 5 guesses, however many addresses the guesser has**: at most 5 / 923,521 ≈ 1 in 185,000 per code made. |
| Expiry | 5 minutes. | Owner decision. |
| Tries | 5 wrong secrets in a live slot void the code. **The phone never learns the tries left**: every wrong code gets `400 {"detail": "Wrong code. Check it on your dashboard, or make a new one there."}`, with the same headers, whether it hit a live code, an empty slot or a spent one, and the server does the same work for each (two HMACs, no store write: the tries are counted in the server's memory), so timing doesn't tell either. The tries left show only on the owner's dashboard. A wrong length or a character outside the alphabet hits no code, so it isn't counted (and says so). | Owner decisions, 2026-10-17. Hiding hits keeps live slots secret (§7.4). |
| One per account | Making a typed code voids the account's previous typed code. A typed code and the QR code are separate (the QR code stays as it was). | |
| Single use | A claimed code is spent; any later check or claim is refused (no replay). | |
| Bound to one phone | The first phone to **check** the code is the only one that can claim it, and a claim must follow a check from the same `device_id`. A second phone entering it cancels it for both. | The dashboard always names the phone before anything is paired (§3), and a code read over the owner's shoulder can't be raced. |
| Rate limits | Wrong codes, QR and typed together: 10 per address in 10 minutes (an IPv6 address counts by its /64), then `429`. Per account, 10 in 10 minutes, counted apart for typed and QR codes: wrong typed codes lock only the account's typed codes, never its QR code. Only a wrong secret at a **live** code counts against its account; a guess at an empty, spent, cancelled or expired slot names no account. A locked account's code isn't bound to a phone. Minting shares the account's 30-codes-an-hour limit. At most 480 typed codes hold slots server-wide (half the slots, every record in the slot table counted); past that, minting asks for the QR code. The failure counts live in memory, and old keys are swept once a window. | The per-code cap is the real bound; these limit sweeps and DoS. Security review 3 (K3-H2): when any slot record named its account and that count also locked QR codes, a blind spray of all 961 slots locked the owner out of all pairing. |
| Constant time | An HMAC is computed and compared with `hmac.compare_digest` for every guess, empty slot or not. | Timing doesn't tell which slots are live. |
| Storage | `accounts.json` (`typed_codes`) holds only HMAC-SHA256 of the code under a 32-byte key made at start-up and **held only in memory**. Each record carries the start-up's random epoch; a record from an earlier start-up is dead. Wrong tries per code are kept in memory, not in the file. | A plain hash of 4 secret characters is brute-forced in a second from a copied file; a keyed one isn't. A server restart voids live typed codes (the owner makes a new one), which is also why the tries can live in memory: a restart that forgets them has already voided every code they counted against, so the 5-tries cap holds across restarts. |
| Nothing logged | The code is in the mint reply only. It's never printed, never in an error message, never in the audit log (`pairing.code_created` with outcome `typed`, `pairing.code_cancelled`, `device.paired`), history or the status reply. It travels in POST bodies, never in a URL, so access logs can't hold it. | Decision 4. |
| Same result | Claiming goes through the same `finish_pairing` and the same device record (`_bind_device`): the same key, trust rule (a second phone isn't trusted for approvals), approval key, socket close on re-pair and audit entry. A phone registered to another account is still refused until that account removes it. | |

## 3. How the confirm screen binds to the dashboard

The phone's confirm screen shows **who the code belongs to** (account email, server). The
dashboard shows **which phone is about to join** (the model the phone sent with its check). Each
side shows what the other can't fake to its own viewer:

- Someone talks the owner into typing *their* code: the owner's phone names the stranger's email
  in large text, with the warning, before the screen lock.
- Someone gets the owner's code (over the shoulder, a phishing page that relays it): the owner's
  dashboard names the stranger's phone model while it's confirming, with one click to cancel;
  and once it pairs, "Paired: … · Undo", the "New phone added" banner, and the audit log.
  The model is whatever the phone sends, so it's a hint, not proof: a stranger can send the
  owner's model name. The owner's own phone hasn't checked the code yet in that case, so the
  stronger signal is "a phone is confirming" while their own phone isn't.

## 4. Undo

Undo only removes access, so it needs no screen lock (owner decision).

- **On the phone** (the "Paired with … · Undo" notification): `POST /api/phone/unpair` with the
  device key, as today. The server revokes the key and closes the phone's sockets.
- **On the dashboard**: "Undo: remove this phone" calls `POST /api/devices/{id}/revoke`, as
  Remove does today.

## 5. Endpoints

| | Who | |
|---|---|---|
| `POST /api/pairing/code` | dashboard session | → `{code: "K7P-2QX", expires, ttl, tries: 5, email, server}`. `429` past the hourly or server-wide limit. |
| `GET /api/pairing/code` | dashboard session | → `{status: none \| waiting \| confirming \| paired \| expired \| cancelled, expires, tries_left, model, device_id}`. Never the code. |
| `DELETE /api/pairing/code` | dashboard session | Cancels a waiting code. |
| `POST /api/pair/check` | the phone, no session | `{code, device_id, model}` → `{email, expires, server}`. Binds the code to this phone. |
| `POST /api/pair/claim` | the phone, no session | `{code, device_id, model, approval_key}` → `{key, server, email, device_id, trusted_for_approvals}`, as for QR. |

The server tells the two kinds of code apart by length: a typed code is at most 12 characters
once spaces and dashes go, a QR code is 30.

## 6. What the Android app needs (the separate step)

- **Type a code** screen (`SetupPairCode`): normalize nothing itself (the server does), send
  `POST /api/pair/check {code, device_id, model}` to the hosted server by default, or to the
  address from More options › Your own server (the same https rule as links, phone-protocol §6).
  Show `detail` on a `400` (a wrong code is always the same "Wrong code" reply: the phone doesn't
  know the tries left, so the mockup's "2 tries left" line goes; the dashboard shows them). `429`:
  show "Try again in a few minutes".
- **Confirm** (`SetupPairConfirm`): the `email` and `server` from the check reply, in large text,
  and the warning; then the screen lock (as for QR), then `POST /api/pair/claim` with the same
  `device_id`. "This isn't me" just goes back (the code stays unused; the owner can cancel it).
- **Already paired** (`SetupPairReplace`): unpair first, with the screen lock, as for QR links.
- **Paired** notification (`SetupPaired`) with Undo → `POST /api/phone/unpair` (no screen lock).
- No new WebSocket messages.

## 7. Threat assumptions (for the batched security review)

1. **TLS protects the code in transit**, and the hosted server is the one in the app by default.
   A self-hosted address is typed by the owner.
2. **The attacker can't read the server's memory.** If they can, they have far more than codes.
   With only a copy of `accounts.json`, typed codes can't be recovered (keyed hash).
3. **The guesser can use many addresses.** Per-address limits don't bound them; the 5-tries-per-code
   cap does: at most 5 in 923,521 per code made, and an account makes at most 30 codes an hour.
   Across all accounts, the expected number of codes a guesser wins is codes made × 5.4 × 10⁻⁶
   (about one per 185,000 codes, if the guesser burns every code's tries).
4. **The phone can't tell which slots are live.** A wrong secret in a live slot, an empty slot and
   a spent or expired code get the same reply (status, body, headers) and cost the server the
   same work (`test_a_hit_and_a_miss_look_the_same_from_the_phone`): two HMACs and no store write.
   Remaining tells, accepted: a guess that kills a live code is invisible to the guesser, but the
   owner sees it; a locked account answers `429` only to a **right** code (wrong ones still get
   "Wrong code"). A guesser can still kill live codes blindly (5 wrong tries each, spread over 961
   slots), and by killing two of an account's codes in 10 minutes lock its typed codes for 10
   minutes: denial of service, not access, and the QR code still works.
5. **Social engineering is the main risk**, more than guessing, and the server can't stop it
   alone. It relies on the phone's confirm screen naming the account and server (owner condition
   1), the dashboard naming the phone, the post-pair notification with Undo, and the existing
   "New phone added" banner and audit log. A phone added this way can't approve for the owner's
   other phones until trusted (unchanged).
6. **The phone's `device_id` and `model` aren't secret or verified.** The binding uses them only to
   (a) stop a second phone from claiming a code a first phone checked, and (b) show the owner a
   name. A stranger who already knows the code and checks first wins the race against the
   owner's phone, but the owner's dashboard then shows "confirming" while their own phone hasn't
   been used, and they can cancel.
7. **A server restart voids live typed codes** (the key is in memory). Accepted: they live 5 minutes.
   The wrong tries and the per-account failure counts are in memory too and go with them.
8. **One process.** The failure windows and the HMAC key live in the server process, as the QR
   limits do today; several server processes would need a shared store.

## 8. Security review 3 (reviewer K, 2026-10-18)

- **K3-H1:** claimed codes kept their slot a day while the cap counted only live ones, so 961 claims
  (two accounts, within the hourly limit) filled the table and the next mint looped forever holding
  the store's lock (sign-in and sessions froze). Now a claim frees its slot, the cap counts every
  record in the table, and minting picks from the free slots or refuses.
- **K3-H2:** a guess at any slot record named its account, and that count also locked QR codes. Now
  only a live code's account is named, and typed and QR counts are separate (Rate limits above).
- **K3-M1:** per-address limits counted every IPv6 address apart (a /64 is 2^64 of them); the
  failure windows never forgot a key; every wrong guess rewrote `accounts.json`. Now IPv6 counts
  by /64, stale keys are swept, and tries are counted in memory.
- **K3-M2:** look-alike emails. New accounts need a plain-ASCII email after NFKC, and one that
  reads like an existing account's is refused (`docs/safety.md`, "No look-alike accounts"). The
  confirm screen says "This address has unusual characters" for any non-ASCII email or server.
- **K3-L1:** `GET /api/pairing` made a QR code, so a link or image on any site could void the live
  one and spend the hourly allowance (shared with typed codes). Both mints are now `POST` only and
  refuse a request another site's page made (`Origin`, `Sec-Fetch-Site`).
- **K3-L2:** a valid code plus the owner's phone's `device_id` replaced that phone's record (as the
  "first", trusted phone) and cut the real phone off. A phone paired now must prove its current key
  to pair again (phone-protocol §2.6); a re-pair never counts as the first phone.
- **K3-L3:** the app's error filter missed lowercase codes and free-text lures. The app now shows
  only a fixed list of the server's own sentences (`PairingFlow.KNOWN_SENTENCES`), else its own words.
- **K3-L4:** an unpair the server didn't get was lost. The app keeps it and sends it again on the
  next connection, and tells the owner "Removed on this phone; also remove it on the dashboard."
- Tests: `tests/test_review3_pairing.py`, `PairingFlowTest` (L3, L4).

## 9. For the owner

Decided 2026-10-17 (`docs/decisions.md`): 31 characters; the phone gets one generic "Wrong code"
reply and the tries left show only on the dashboard; the code appears only when asked for ("Can't
scan? Show a code to type", under the QR code); a typed-code pairing doesn't mark the QR code used
(devices carry `paired_via`: `qr` or `typed`).

Fixed on the app side (redesign step 4, `docs/design/redesign-setup.md` S11):
- **The "pairing error that printed a link"** (abuse series 2026-10-10). Nothing on the server
  printed it. The app showed any server's `detail`, and any exception's text, as they were. A
  server could put a link or a code in its reply, and OkHttp's URL errors carry the whole URL.
  `PairingFlow.errorText` now shows the server's sentence only when it holds no link and no code,
  and the phone's own words otherwise. MainActivity's error dialog and its sign-in use it too.
