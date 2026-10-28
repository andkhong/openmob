# Redesign step 5: the Activity screen

Status: built on `feature/redesign-activity` (2026-10-17), behind the debug-only `RedesignActivity` then; since step 6
it is the app's own Activity screen (`ui/activity/`), merged into `main` on 2026-10-18. Mockup:
`Activity.dc.html`. The screen also fills Home's "Latest" card and its "Asked you N times" line.

## Data: only what the phone already gets

There is **no new server message or endpoint.** The history is built on the phone, as tasks run, from three sources:

- **`task_state`** (`docs/phone-protocol.md` §3.4, step 4): the task id, the request, the step count and the outcome
  (`done`, `failed` or `stopped`). The task id is what groups everything else.
- **The phone's own approval events** while the task is open: "… asks: …", "Asked on this phone: …" and
  "Denied: …", matched against the app's own string formats. They give the "asked you N times" count and "Denied by
  you".
- **The phone's own Stop note** ("You stopped the agent with the Stop button…"), for "Stopped by you".

The code is `TaskLog` (pure, tested) and `TaskHistory` (the app's copy). It is fed from `ConnectionService`'s
`task_state` handler and `AppState.addEvent`. It is display only: nothing decides anything from it.

**Tasks from before this phone ran this code aren't shown**, and neither are tasks from an older server that sends
no `task_state`. The screen says full logs are on the server's dashboard. A server endpoint for older history would
be the next step, if wanted (owner, 2026-10-17: no; the history stays phone-only).

## Privacy

- **What is kept.** Per task:
  - the request text, as the server sent it (`task_state.text`, from "Working on: …"), which the server has already
    redacted (card numbers, SSNs). The phone stores nothing the server didn't already send it;
  - the start and end times, the outcome, and the step and ask counts;
  - whether it was denied or stopped by the owner;
  - for a failed task only, its result line, cut to 120 characters.
- **What is never kept:** step texts (they can name what was typed), typed text, screen contents, approval
  questions, and crops.
- **How long:** 7 days, and at most 50 tasks. Older or extra ones are dropped whenever the list is read or written.
- **Where:** app-private SharedPreferences (`openmob_activity`). It isn't encrypted: it holds the same text the app
  already shows in its activity list.
- **Unpair:** cleared on unpair (`PairingFlow.unpair`, so the old screen's Unpair, the redesign's and the notification's
  Undo). Also cleared when the phone pairs with another account or server (`PairingFlow.claimAndSave`). The default
  the coordinator asked for.

## Owner-only

The Activity screen is one of OpenMob's own windows. The gatekeeper refuses every agent act on an `own_packages`
window (`builtin:own_window`, `Gatekeeper.kt`), and an unrecognized window fails closed (`builtin:unknown_window`). So an
agent can't open, scroll or tap it.

An agent's screenshot is a separate matter: these screens have no FLAG_SECURE. The history shows only request texts the
server itself sent. (Owner, 2026-10-17: no FLAG_SECURE on Activity or Home.)

## Differences from the mockup

- **No "Faster mode off · Session ended" rows.** Mode changes aren't task history. Since 2026-10-17 (`eb13d2e`) the
  one exception is the owner's answers to Faster mode requests made in Settings: their own rows (approved, with the
  scope, or denied; `TaskLog.KIND_FASTER`, at most 10, the same 7 days and unpair clearing). Home's "Latest" stays
  tasks only.
- **"Didn't finish: the connection ended"**: a task the server never said had ended (the connection dropped).
- **"Drive session"**: a task with no request text, such as an outside agent driving step by step.
- **Rows don't open anything.** There is no task detail screen in the mockups (owner, 2026-10-17: none for the MVP).
