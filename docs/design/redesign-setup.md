# Redesign step 4: setup and pairing

Status: final build (`feature/redesign-final`, step 6, 2026-10-17), merged into `main` on 2026-10-18 (with `feature/redesign-composer`). The Compose app is the launcher in every build
type: `MainActivity` now hosts it, and `RedesignActivity` and the old screens are gone. QR and `openmob://connect`
links still arrive at `MainActivity` and go through `PairingFlow` with the same checks. This file lists the
protections setup and pairing have, and how the final build keeps each one (re-run 2026-10-17; see "Status in the
final build"). The typed code's server side is
`docs/design/pairing-code.md`; §6 there is what the app needs, §7 the threat assumptions.

## What was read

- `MainActivity.kt`: the link handling, the sign-in fallback, the developer token, the confirmation, the claim,
  unpair, the Accessibility disclosure and the setup checklist.
- `Pairing.kt` (link parsing), `ServerPolicy.kt`, `AccountApi.kt`, `Settings` (`AppState.kt`) and `SecureStore`.
- `docs/design/pairing-code.md` and the server's `/api/pair/check` and `/api/pair/claim`.

## One code path

The pairing steps moved out of `MainActivity` into `PairingFlow` without a behaviour change; the setup screens and
the link handler both call them:
- the screen-lock prompt (`confirmPrompt`);
- the claim and what it saves (`claimAndSave`);
- `unpair` and `reconnect`.

The system screens moved the same way, into `SetupIntents`: Accessibility, App info, notifications and battery.
The one change on purpose is `PairingFlow.errorText` (S11).

## The protections

| # | Protection | Where | Redesign | Test |
|---|---|---|---|---|
| S1 | **A link never pairs by itself.** Developer-token links are refused. A link's code and server are checked (`Pairing.parse`). | `MainActivity` (rewritten in step 6) | Same parse; then a notification-permission ask, `checkAndConfirm`, `PairingFlow.confirmPrompt`, `claimAndSave`. | `PairingTest` (existing); emulator: a QR link paired only after the PIN |
| S2 | **https only**, plain http only to this phone or the local network (`ServerPolicy`), also for a typed own server. | `ServerPolicy` | More options › Your own server checks it before anything is sent. | `SetupViewModelTest.ownServerMustPassServerPolicy` |
| S3 | **No pairing without a screen lock**, checked before the code is even checked. | `startAccountPairing`, `confirmAndPair` | Same check, same order, before `/api/pair/check` and again before the prompt. | `SetupViewModelTest.noScreenLockNoCheck` |
| S4 | **One screen-lock confirmation names the server and account** before the claim. Nothing is saved until the claim succeeds; a failure leaves the old pairing as it was. | `PairingFlow.confirmPrompt`, `claimAndSave` | The same prompt and claim. The claim runs only after the prompt passed. | `SetupViewModelTest.claimOnlyAfterTheLock`, `failedClaimSavesNothing` |
| S5 | **The confirm screen names the account and server in large text**, with "Only pair with your own account. OpenMob will never ask you for a code." (owner condition 1a, word for word; security review 3 restored it after UX review 2 had changed it), "This address has unusual characters. Check it letter by letter." when the email or server isn't plain ASCII (review 3, K3-M2), and "Your dashboard should now show this phone (<model>) waiting." (owner, 2026-10-17). | New (typed code) | `SetupConfirmScreen`. | `SetupSemanticsTest.s5_confirmNamesAccountAndServer`, `UxReview2Test` |
| S6 | **Already paired: unpair first, with the screen lock** (SetupPairReplace; `pairing-code.md` §6). The confirm prompt also says what it replaces. | `PairingFlow.unpairPrompt`, `confirmPrompt` | The replace screen shows both pairings. Unpair runs only after its prompt passed, then the normal confirm follows. | `SetupViewModelTest.alreadyPairedGoesThroughReplace` |
| S7 | **Moving servers tells the old one** with the old key. | `claimAndSave` | Same code. | Same code path (no Kotlin test: AccountApi is a network class) |
| S8 | **Sign-in fallback**: the session lives in memory for seconds, is signed out before the prompt, and only the device key is kept. | `PairingFlow.signInForCode` (was `MainActivity.showSignIn`) | Ported in step 6 to `SetupSignInScreen`: sign in, mint one code, sign out in `finally`, then the same check, confirm screen, lock and claim as a typed code. Password field masked, no suggestions; FLAG_SECURE while shown. | `SetupViewModelTest.signInChecksFirstThenTheSameConfirmAndClaim`, `aFailedSignInShowsOnlyTheSafeText`; `SetupSecureTest` |
| S9 | **Developer token**: a "Connect to …?" dialog, the screen lock when it replaces a pairing, and a no-suggestions input. | `PairingFlow.saveToken` (was `MainActivity.savePairForm`) | Ported in step 6 to `SetupTokenScreen`: the same dialog (Compose), the lock (`LockRequest.Token`) only when it replaces a pairing; token field masked, no suggestions; FLAG_SECURE while shown. | `SetupViewModelTest.developerTokenAsksConnectAndTheLockOnlyToReplace`, `cancellingTheTokenSavesNothing`; `SetupSecureTest` |
| S10 | **The Accessibility disclosure, with an explicit Agree, before every route to Android's Accessibility settings.** | Consent screen (the OPEN_ACCESSIBILITY shortcut lands there too) | The consent screen is that disclosure. Only "Agree and open Settings" opens Accessibility (or App info first while restricted settings block it); "Not now" opens nothing. The restricted-settings help is inline when it applies (UX review 2). | `SetupSemanticsTest.s10_consentIsTheOnlyRouteToAccessibility`, `UxReview2Test`; emulator: the shortcut opened consent |
| S11 | **Error screens never show a pairing link or code** (the "pairing error that printed a link", abuse series 2026-10-10). | New: `PairingFlow.errorText` | Used by both UIs, also MainActivity's error dialog and sign-in. | `PairingFlowTest` (`errorText`) |
| S12 | **A wrong code shows the server's generic reply only.** There is no tries-left line: the phone never learns it (owner, 2026-10-17). | Server | The "2 tries left" line in the mockup isn't built. | `SetupViewModelTest.wrongCodeShowsTheServersReply`, the screenshots |
| S13 | **A typed code is bound to this phone**: check and claim carry the same `device_id` (and the model, shown on the owner's dashboard). | `AccountApi.check`, `claim` | Same calls; QR checks still send only the code. | Server: `tests/test_pairing_code.py`; end to end, see below |
| S14 | **Undo needs no screen lock**, and undoes only that pairing: the same server and account, still paired. | New: `PairingFlow.undo`, `PairUndoReceiver` (not exported, immutable PendingIntent) | The "Paired with … · Undo" notification after every account pairing: typed code, and QR or link (owner, 2026-10-17). | `PairingFlowTest`, `SetupSecureTest.pairedNotificationOffersUndoWithoutALock`; QR end to end on the emulator |
| S18 | **FLAG_SECURE while a pairing code is shown or held** (owner, 2026-10-17): the code entry, More options, confirm and Replace. Held per window, so it never drops between two such screens. | New: `SecureWindow` | Same. | `SetupSecureTest.flagSecureOnlyWhileACodeIsShownOrHeld` |
| S15 | **The code is never stored.** It lives in the ViewModel until the pairing ends, is cleared after it, and is never logged. | New | Same. | `SetupViewModelTest.claimOnlyAfterTheLock` (cleared) |
| S16 | **"This isn't me" pairs nothing**: back to the code, which stays unused (the owner can cancel it on the dashboard). | New | Same. | `SetupViewModelTest.notMePairsNothing` |
| S17 | **Agents can't tap OpenMob's screens** (the gatekeeper's `own_window`). | Gatekeeper, by window package | Unchanged. | Existing gatekeeper tests |

**FLAG_SECURE** (S18, owner, 2026-10-17) closes the gap where an already-paired phone's server could see a newly typed
code in a screenshot. Since step 6 the sign-in and developer-token screens hold it too (they show a password or a
token); Connection and pairing does not (it shows no secret).

## Status in the final build (step 6, 2026-10-17)

- **S2 to S6, S8 to S16, S18:** the tests named in the table pass against the final build in the debug, release and
  local unit-test variants.
- **S1, S7, S17:** code unchanged (S1's parse and checks), existing tests pass.
- **On the emulator** (R8 local build, step 6): typed code via More options, confirm, PIN, then "Paired · Undo"; Undo
  emptied the server's device list; a QR link asked "Connect this phone to 127.0.0.1? as e2e-owner@example.com" and
  paired only after the PIN, with its own Undo notification.
- **Device only:** Samsung's restricted-settings path wording; that TalkBack reads the setup screens in order (the
  emulator's uiautomator dump went stale once OpenMob's accessibility service was on, so it couldn't be used).

## Differences from the mockups

- **No in-app camera scanner** (SetupPair's viewfinder; owner, 2026-10-17). The phone's camera app opens the
  `openmob://connect` link in MainActivity, as today. The pair screen says so.
- **No "2 tries left"** (S12).
- **"Sign in on this phone" and "Developer token"** are Compose screens since step 6 (S8, S9), with the same steps.
- **The typed code's default server is `https://openmob.fly.dev`** (owner, 2026-10-17).
- **"Paired with … · Undo" after QR and link pairing too** (owner, 2026-10-17). It is the only change on the QR path.

## End to end (emulator, 2026-10-17)

**Setup.**
- A throwaway server from this worktree on port 8766, with a fresh data directory in the scratchpad (never 8765,
  never `~/.config/openmob*`), and a test account `e2e-owner@example.com`.
- emulator-5554 (Android 15, PIN 1234). Another lane's debug build was on it; it was backed up first and restored
  afterwards: reinstalled, its app data cleared to the unpaired state it had, notifications revoked and its
  Accessibility service re-enabled, as before. `adb reverse tcp:8766` was removed.

**Steps:** `RedesignActivity`, then Continue setup › Get started › Type a code instead › More options:
1. Server `http://127.0.0.1:8766` and a wrong code: the server's "Wrong code. Check it on your dashboard, or make a
   new one there." and nothing else.
2. The right code: the confirm screen named `e2e-owner@example.com` and `127.0.0.1`. The dashboard's
   `GET /api/pairing/code` said `confirming`, with the model `sdk_gphone64_arm64`. The tries left (4) appeared there
   only.
3. "Pair with this account": Android's prompt read "Connect this phone to 127.0.0.1? as e2e-owner@example.com".
   The PIN paired the phone (`paired`, `paired_via: typed`) and Setup › Ready showed "Connected to 127.0.0.1".
4. The first pairing posted no notification: the fresh install had no notification permission, and the redesign's
   Notifications › Allow granted it. A second code then paired again: the code field was empty, and "Paired with
   e2e-owner@example.com on 127.0.0.1. Not you? Undo…" appeared.
5. **Undo, with no screen lock:** the server's device list went from one (online) to none. The phone's stored
   email and device key were cleared.

**Not covered end to end:** `task_state` on the device (no model keys on the throwaway server; pytest covers it),
the QR path (unchanged), and Replace (the ViewModel and screen tests cover it).
