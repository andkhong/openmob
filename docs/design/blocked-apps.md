# Owner-added blocked apps

Built 2026-10-20 on `feature/blocked-apps`, from the owner's decision of 2026-10-20 (`docs/decisions.md`) and the
"Blocked Apps Mockup" design canvas. **Not yet security-reviewed** (for the next batched review) and not run on a
real phone.

## What it does

The owner can add apps the agent may not open or act in, on top of the built-in sensitive apps (banking, payments,
wallets, crypto, password managers, authenticators, OpenMob). An added app gets every built-in treatment: launching
it, links into it, acting in it and its app-info page are refused; screenshots, the element list, `wait_for` and the
live view are black while it is on screen. In every mode, including Don't ask, the drive level and Faster mode
(Faster mode's frames are screenshots, which the gate blacks out).

## Who decides (the owner's rules)

- **The phone is the authority.** The list lives on the phone (`BlockedApps`, app-private storage, never backed
  up) and the gatekeeper enforces it (`Gatekeeper.ownerBlocked`, rule `owner:blocked_apps`). Entries are exact package
  names: `com.whatsapp` doesn't block `com.whatsapp.w4b`.
- **Blocking:** from the phone (Settings › Blocked apps › Block more apps) or the dashboard (Your phones › Blocked apps ›
  Block on phone). No screen lock: it only tightens.
- **Unblocking: only on the phone, with the screen lock** (Android's own prompt, strong biometric or PIN, as
  pairing). The dashboard, the API and MCP have no unblock; the phone's `block_apps` handler reads only `packages`
  and only adds. A compromised server can only grow the list (to 200 entries at most).
- **Built-ins can't be removed.** An app that is both built in and owner-listed keeps the built-in rule.
- **Three packages can't be blocked** (review 5 P5-L1, narrowed after re-review 1 N3 under the owner's tighten-only
  rule; `BlockedList.protectedPackage`): exactly OpenMob itself, the phone's current default Home app and System UI,
  by exact package name. A request naming one keeps its other entries; the picker doesn't list them; the act watch
  never presses Home for them (even from a list stored before the rule): blocking them would lock the owner out (a
  blocked Home app would send the phone Home into itself). Everything else can be blocked: Settings, permission
  controllers, package installers, other launchers and any app with "launcher" in its name
  (`com.epicgames.launcher`). Blocking Settings or an installer is the owner's choice; the gate's own checks on
  those surfaces are unchanged.

## The phone's screens (owner-approved revision, 2026-10-20)

Settings has one row, **Blocked apps** ("4 built in · N by you"), opening its own page. The page shows **Always blocked · built in** first (the four categories, each with a switch locked
on), then **Blocked by you · N** (each app with its icon, name and a switch, on), then **Block more apps**. The
**Block apps** list works like Settings › Notifications › App notifications: search, an All apps / Blocked by you
filter, "N blocked by you", and every launchable app with its real icon and a Material 3 switch. A switch turned on
blocks at once, with no confirmation; a switch turned off opens the "Unblock <app>?" sheet (Unblock with screen lock
/ Keep blocked), then Android's screen-lock prompt, and only its success removes the app. Built-in apps show a
disabled switch, on, with "Always blocked (built in)".

## However it's reached

Since 2026-10-20 a blocked app opened from the home screen is caught too (the 2026-10-18 Google Authenticator gap):
a launcher tap on anything named exactly after a blocked app is refused (`owner:blocked_app_name`), and an app an act
opened anyway is left at once with the next call refused (`owner:blocked_app_opened`). See phone-gatekeeper.md,
"Blocked apps however they're reached".

Since review 5 (P5-M1, 2026-10-21):
- **Notifications.** A notification's reply or inline action, and ENTER in its reply field, ask in every mode
  (refused under Don't ask), whichever app it's from. A notification row whose header app name
  (`android:id/app_name_text`) is exactly a blocked app's label is refused for acts (`owner:blocked_app_notification`,
  or `builtin:sensitive_notification`: the task stops as for the app) and blacks out screenshots, `ui_elements`,
  waits and Faster frames while it shows (`builtin:blocked_notification`; the task goes on, since a heads-up can pop up
  over anything). Limits: a row whose layout hides the app name (some conversation-style notifications) isn't
  identified, so only (a) covers it; a status-bar icon isn't a row; labels come from installed launchable blocked apps.
- **Widgets.** A tap inside a home-screen widget (`AppWidgetHostView` on the tap's path, in a known launcher) whose
  text or description names a blocked app exactly is refused like its icon. Accessibility reports a widget's nodes
  under the launcher's package, so a widget that shows no app name isn't identified (the act watch still leaves an
  app it opens); reads aren't blacked out for widgets.
- Quick Settings tiles of blocked apps aren't identified.

## A task that reaches a blocked app

It **stops, not fails**: status `cancelled`, `outcome.reason: "blocked_app"`. The phone decides, the moment its gate
refuses an act or blacks out a read with `owner:blocked_apps` while a task runs:

1. it sends `task_stop` with `reason: "blocked_app"` (and the package and label) **before** the refusal itself, so the
   server stops before the agent's next step;
2. it holds acts as after the owner's Stop (`gate_owner_stopped`) until the task ends;
3. it posts one notification: **"Task stopped · It reached an app you've blocked. Open OpenMob to see which."** No app
   name, no task text (review 4 M3).

The server ends the task (and the queue) as `cancelled` / `blocked_app` with a summary naming the app, which the
phone's thread shows under "Stopped · blocked app". Status choice: `cancelled` is a status every client already
handles as a deliberate stop, so no new terminal status was added; the new part is only the reason. An orchestration
step stopped this way ends the run as `stopped_on_phone`, like the owner's Stop.
API, MCP and orchestration callers (and webhooks) see that summary, so they learn which blocked app stopped the
task; this is intended (owner, 2026-10-21, review 5 A5-L1): only the phone's notification hides the name.

## The dashboard's copy

The phone reports its list (`blocked_apps`) after each welcome and each change; the server keeps it per account and
phone (`openmob/blocked_apps.py`, `blocked_apps.json` in the data directory) with the time it came. Dashboard
requests stay pending until a report includes them and go again on each connection (never in reply to a report, so a
phone that refuses one can't loop). `GET`/`POST /api/devices/{id}/blocked-apps` (owner session only, POST same-site;
there is no DELETE, PUT or PATCH). Protocol: `docs/phone-protocol.md` §3.8.

## Choices worth knowing

- **Plain app-private storage, not Keystore-encrypted:** a decrypt failure would empty the list, which loosens. A
  package list isn't a credential; backups are off (review 4 L7).
- **Exact names only:** no patterns from the owner or the server, so a server can't block "everything" with one
  regex (it can still list up to 200 apps, which only tightens).
- **Server-side checks don't know the list.** The server's own `sensitive_apps` (API tasks, `allow_sensitive_apps`)
  is unchanged; the phone enforces owner blocks regardless of that setting.

## Not done

- Not verified on the Samsung (owner's rule: no phone-side change is verified until it runs there).
- The Block-apps list shows launchable apps only; a package with no launcher entry can be blocked from the dashboard
  by name.
- The dashboard shows the phone's name for each app with its package beneath (the phone reports `{package, label}`;
  a package requested from the dashboard shows by package until the phone reports it). Names are display only.
