# Redesign step 3: the approval screen

Status: final build (`feature/redesign-final`, step 6, 2026-10-17), merged into `main` on 2026-10-18. The Compose screen is the **only** approval UI in
every build type: the developer switch and the old view rendering are gone. The two controls that grant anything,
Approve (`Button`) and "Always allow" (`CheckBox`), are still the original Android views, built in
`ApprovalActivity.buildControls()` with their original flags and embedded in Compose. This file lists every
protection the approval screen has and how the final build keeps it; the table was re-run against the final build
on 2026-10-17 (see "Status in the final build").

## What was read

- `ApprovalActivity.kt`: the screen, the approve flow, the screen lock, the signing.
- `Approvals.kt`: requests, expiry, the notification and its Deny receiver.
- `ApprovalKeys.kt` and `TapKeys.kt`: the keys. `PromptOutcome.kt`: how a cancelled lock is read.
- `ActionDigest.kt` and `gate/ModeChange.kt`: the phone's own wording of what is approved.
- `gate/GateHost.kt` and `gate/Gatekeeper.kt` (read only): the own-window refusal, the prompt-open refusal,
  `approvalMessage`, `approve`, `markShown`.
- `OpenMobAccessibilityService.kt` and `ControlIndicator.kt`: the overlay and the amber state.

## The protections

The table below has one row per protection. For each one, **Where** is where it lives, **Layer** is whether the
redesign touches it, and **Test** is how the Compose version checks it. "Both UIs" in a Test cell meant the step-3 build;
since step 6 there is one UI, and every test named runs against it.

| # | Protection | Where | Layer | Test |
|---|---|---|---|---|
| P1 | **FLAG_SECURE**: no screenshots, screen recording or live view of this screen, so the agent can't read it. | `ApprovalActivity.onCreate`, window | Window, unchanged | Robolectric: the window has FLAG_SECURE in both UIs. |
| P2 | **Other apps' overlays are hidden** while it shows (`setHideOverlayWindows(true)`, API 31+). | `onCreate`, window | Window, unchanged | Robolectric, both UIs: the permission is declared, and onCreate makes the call (it throws when the permission is withheld). *The effect on real overlays: device only.* |
| P3 | **Approve ignores touches through an overlay** (`filterTouchesWhenObscured`), and so does the "Always allow" box. | The Approve `Button` and `alwaysBox` `CheckBox` | View | The Compose screen embeds **the same `Button` and `CheckBox` objects** (AndroidView), with the same flags. Robolectric, both UIs: a touch flagged `FLAG_WINDOW_IS_OBSCURED` does nothing, whether sent to Approve or to the window at Approve's place (through Compose's interop); an unflagged one reaches onApprove. *Real overlays: device only.* |
| P4 | **Approve and "Always allow" are hidden from accessibility services** that aren't accessibility tools, including the agent's own service (`setAccessibilityDataSensitive`, API 34+). | Same two views | View | Same embedded views. Robolectric: both report `isAccessibilityDataSensitive`. *What a real service sees: device only.* |
| P5 | **Agents can never tap OpenMob's windows.** The gatekeeper refuses any act on an `own_packages` window (`builtin:own_window`). While a prompt is pending, every act is refused (`gate_prompt_open`). | `Gatekeeper` (by window package, not by view) | Not view; untouched | Not affected by the view layer: the window's package doesn't change. Covered by the existing gatekeeper tests. |
| P6 | **Approve needs the screen lock**: `BiometricPrompt` with BIOMETRIC_STRONG or DEVICE_CREDENTIAL. The approval key needs user authentication on every use (timeout 0), so it signs only inside that prompt. With no screen lock set up, there is no approval at all. | `authenticate`, `ApprovalKeys` | Logic, unchanged | The same `onApprove` → `authenticate` code runs from the same Button. *The prompt itself: device only.* |
| P7 | **Tap-level gate prompts** (everyday actions) are approved with a tap on Allow, signed with the tap key, no lock. Their basis is P3, P4 and P5. | `approveWithTap`, `TapKeys` | Logic, unchanged | Same code path. The tests check that only that path is tap-level. |
| P8 | **A tap just after the screen appears is ignored** (500 ms after window focus, gate prompts; review B1). | `onWindowFocusChanged`, `onApprove` | Logic, unchanged | Same code path. *Timing on device.* |
| P9 | **Second confirmations**: "Also allow purchases" for Don't ask with money, and "Always allow" for payments (`confirmTwice`). Both are platform dialogs, shown before the lock. | `onApprove` | Logic, unchanged | Same code path. |
| P10 | **The answer is bound to this request.** It signs `id|task|digest|true|ts[|always]`, or the gatekeeper's own `approvalMessage(id, always)` (device, prompt, action, crop). Each request is answered at most once (`finished`). | `ApprovalKeys`, `Approvals`, `GateHost` | Logic, unchanged | Same code path. |
| P11 | **What is shown is what is signed.** `actionLine` is built on the phone from the action's own fields. A digest that doesn't match its fields, or a missing digest where a signature is required, is a **blocker**: Approve is gone and only Deny is left. A phone that can't sign (`canApprove` false) can only deny. | `render`, `blocker` | View plus logic | The blocker logic is unchanged and moved into a pure function that both UIs use. Robolectric: with a blocker there is no Approve node and Deny still works. |
| P12 | **Phone text versus server text.** The question is the phone's own words where it has them: the gate's wording, a mode change described from the signed change, or a question built from the signed fields. An older server's question is shown as before. Server-supplied text is labelled: "Server says: …" (gate) and "Asked by <requester>". | `Request.shownQuestion`, `render` | View | The Compose screen puts server text only in a section headed "Server says (not checked by the phone)", in a muted, quoted style. It is never in the "Checked by this phone" box. Robolectric: the `serverSays` text sits under that heading and isn't inside the checked section. |
| P13 | **Expiry**: 2 minutes. The notification has `setTimeoutAfter`. Unanswered means no answer, never a yes. An answered or expired request shows "This request is over" with only Close (UX review 2): no Approve, Deny, "Always allow" or amber. | `Approvals`, `render`, `ApprovalScreen.Closed` | Logic unchanged; view changed | Robolectric: a missing request can't be approved (`p13_anAnsweredOrExpiredRequestCantBeApproved`, `p13_approveAfterTheTwoMinutesIsRefused`); the closed state shows only Close (`p13_anAnsweredRequestShowsOnlyClose`). |
| P14 | **Back or dismiss is not a yes.** The activity finishes and the request stays pending until Deny, another answer or expiry. A cancelled screen lock is a deny for gate prompts (DECLINED). A system interruption brings the prompt back (INTERRUPTED). | Activity default; `PromptOutcome` | Logic, unchanged | The existing PromptOutcome tests. Back is unchanged: ComponentActivity's default back is `finish()`. |
| P15 | **Deny and Approve are the same size**, side by side; at large text (font scale 1.3 and up) stacked, Deny first. Deny is never the smaller target, and both sit in the fixed bar under the scrolling body, so Approve is never on screen without Deny. Since step 6 they are the same style too (outlined pills, owner 2026-10-17). | Layout (`EqualButtons`) | View | Robolectric: identical width and height, each at least 48 dp (56 in the redesign); `FontScaleTest`: at font scale 2.0 on a 360 x 740 dp window both are displayed, fully on screen, equal, Deny above Approve. |
| P16 | **No default focus on Approve.** Nothing requests focus, so a keyboard or switch-access "enter" can't approve by default. | Layout | View | Robolectric: no node is focused after launch. |
| P17 | **"Always allow" is off by default** and shown only while the request is open. | `alwaysBox` | View | Same CheckBox. Robolectric: unchecked at launch. |
| P18 | **The heads-up notification** offers only **Deny** (a broadcast, no lock) and **Review** (opens this screen). There is no approve from the notification. On the lock screen it shows "OpenMob needs your approval" (VISIBILITY_PRIVATE). | `Approvals.notify` | Copy and icon only (step 6) | Actions, visibility and timeout unchanged; the title, text, small icon, amber colour and the expanded title changed. Seen on the emulator (step 6): Deny and Review only. |
| P19 | **The prompt counts as shown** only when this screen renders it (`GateHost.markShown`, for the prompt limit). | `render` | Logic, unchanged | Same call, in the shared state function's caller. |
| P20 | **The agent indicator turns amber** while a phone prompt is pending (`ControlIndicator`, from `GateHost.promptPending`). | Overlay | Not view; untouched | Existing tests. |
| P21 | **Not in recents, own task** (`excludeFromRecents`, `taskAffinity=""`, `singleTop`, not exported). | Manifest | Unchanged | Manifest unchanged. |

## Status in the final build (step 6, 2026-10-17)

- **P1 to P4, P6, P11, P13, P16, P17:** re-run in `ApprovalProtectionTest` against the final build; all pass, in the
  debug, release and local unit-test variants. `theComposeScreenIsTheOnlyUi` checks there is no other UI to fall
  back to; `theRedesignEmbedsTheOriginalApproveButton` checks Approve is the activity's own `Button`.
- **Deny** goes through the same `onDeny` path: `ApprovalDenyTest` clicks the Compose Deny and sees the answer sent
  (offline in the test).
- **P12, P15, the closed state and the lock and one-tap looks:** `ApprovalComposeTest`, `UxReview2Test`,
  `FontScaleTest`.
- **P5, P7 to P10, P14, P19 to P21:** not in the view layer; their code is unchanged, and the gatekeeper and manifest
  tests still pass. The manifest still has ApprovalActivity not exported, `excludeFromRecents`, `taskAffinity=""`.
- **Device only (not shown by any JVM test):** P2 and P3 against a real overlay; P4, what a real accessibility
  service sees; P6, the BiometricPrompt itself; P8's timing. On the emulator (step 6): the window was black in
  screenshots (P1), Approve opened Android's own lock prompt and a PIN approval reached the server ("Faster mode is on for this session: approved on the phone"), and Deny
  closed the prompt (the server log has no line for a denial, so its receipt there was not seen).

## What the redesign changes

- **The view layer only.** `ApprovalActivity` extends `ComponentActivity` and sets one `ComposeView`, from the
  `ApprovalScreenState` computed by the same render logic.
- **Approve, Deny, the "Always allow" box, the lock flow, the signing and the dialogs** are the same objects and the
  same functions as before the redesign. Approve's label is "Approve with screen lock", or "Allow" on a one-tap gate
  prompt (owner, 2026-10-17).
- **Large text (step 6):** at font scale 1.3 and up, Deny and Approve stack (Deny first), the header chip and "from
  OpenMob on this phone" stack, and the approve note scrolls with the body; a rule above the buttons shows when more
  of the request is below.

## Differences from the mockups (not built, or built differently)

- **Amount as a large separate figure ($249.99).** Deferred (owner, 2026-10-17): it needs a signed amount field.
  The amount shows where the phone's own wording includes it.
- **"Your task, typed on this phone: …"** Built (owner, 2026-10-17). It comes from the read-only
  `GateHost.attestedTaskText(id)`: the gate prompt's own call carries the server's `task_text`, and the text is shown
  only when `Gatekeeper.taskAttested` holds, meaning the phone holds that very text (typed here, or in a task grant
  approved here). Otherwise nothing is shown; the server's text is never used in its place. Labelled by source
  (owner, 2026-10-18; review 3 P3-M1): "Your task, typed on this phone", inside "Checked by this phone", only when the
  owner typed it here (`Gatekeeper.taskTyped`: `noteInstruction`'s own requests). Text held only because a task grant
  for it was approved here was worded by the server, so it is shown outside the checked box, headed "The task you
  allowed (worded by the server)". The gate's own use of attested text (the L2 install rule) is unchanged. Tests:
  `AttestedTaskTextTest`, `ApprovalComposeTest`, `Review3ApprovalTest`.
- **What goes in "Checked by this phone"** (review 3 P3-M2, 2026-10-18): only what the phone built itself: the crop,
  the action line from the signed fields, and task text typed here. A permission change's action line is worded
  from the parsed change (`ModeChange.lockText` over its signed `input`); its `text` and `desc` change nothing and
  are chosen freely by the server, so they are never shown (`ActionDigest.describe` gives a `mode_change` only its
  verb). Audit of the other kinds: a gate prompt carries no action fields (its words and crop are the phone's); for
  an action or a step the line's target text is the element the signature binds (the agent re-checks the digest
  before it acts); a plan has no action line. Server-supplied fields otherwise stay under "Server says".
- **The expiry countdown.** Built (owner, 2026-10-17). It is timed from when this phone received the request
  (`Approvals.Request.receivedAt`, `SystemClock.uptimeMillis`, the clock the expiry timer runs on), against the
  existing 2-minute expiry, not the mockup's 5. At 0 the screen shows "already answered or has expired", Approve is
  gone, and Deny or closing is left. `onApprove` also refuses once the 2 minutes are up by that clock, in both UIs,
  even in the moment before the expiry timer runs (a tightening). Tests: `ApprovalComposeTest`,
  `ApprovalProtectionTest`.
- **The heads-up notification's copy.** Changed in step 6: the title is the phone's question, the text says who is
  asking and that Review opens the screen lock; expanded, the question shows once under "OpenMob needs your
  approval". Its actions already matched the mockup: Deny and Review, no approve.
- **The lock sheet** is Android's own BiometricPrompt. Its title and description come from the existing code,
  unchanged.
- **The lock icon on Approve.** Approve is the original Android `Button` (P3, P4), so it is styled to match without
  the icon.
