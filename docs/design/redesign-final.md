# Redesign step 6: the switch (owner summary)

Branch `feature/redesign-final`, 2026-10-17. Merged into `main` on 2026-10-18 (with `feature/redesign-composer`,
`e3e7ad7`) before the phone-only checks below, which are still to do.

## What changed

- **The Compose app is the app**, in every build type (debug, release, local). `MainActivity` hosts it and is the
  launcher; `RedesignActivity`, its debug manifest and every old MainActivity screen are gone. App shortcuts
  (Open Accessibility, Connect, Ask, Share screen) and `openmob://connect` links still arrive at `MainActivity`.
  Links go through `PairingFlow` with the same checks: a notification-permission ask, the code check, the
  screen-lock prompt that names the server and account, then the claim.
- **The new approval screen is the only one.** The developer switch and the old view rendering are removed.
  Approve and "Always allow" are still `ApprovalActivity`'s own Android views, with their original flags and click
  path, embedded in Compose. Approve reads "Approve with screen lock", or "Allow" on a one-tap gate prompt.
- **Ported from the old UI:** sign in on this phone and the developer token (as setup screens, S8 and S9 in
  `redesign-setup.md`), Connection and pairing (connect, disconnect, smooth live view, share screen when the
  dashboard asks, unpair behind a confirm, the device id), the restricted-settings help, the Samsung "sleeping apps"
  link.
- **Polish:**
  - notification text for the connection, the approval heads-up (still only Deny and Review), and Undo;
  - a dark-mode blue (#5A7CFF) clearly apart from the amber, still WCAG AA;
  - an adaptive launcher icon with a monochrome layer (themed icons).
- **UX review 2** (items 1 to 12) and **the four held items** (owner): see `docs/decisions.md`, 2026-10-17.
- **200% text** (owner): every screen was checked at font scale 1.0, 1.5 and 2.0. What broke at 2.0 and was fixed:
  - approval: Deny and Approve stack at 1.3 and up (Deny first, equal); the header chip and "from OpenMob on this
    phone" stack; the approve note scrolls with the request; a rule shows when more of the request is below;
  - labels beside values (Server, Account, Phone) went under each other; words were cut mid-word;
  - Activity rows put the time under the text; the filters wrap instead of running off the edge;
  - Settings' "Default" and "Current" tags; the Ready checklist's Done and Allow; the indicator legend and colour
    swatches (three per row);
  - text-field hints wrap instead of being cut; the developer-token and unpair dialogs scroll;
  - the indicator's drawn phone keeps its label to scale.
- **Found on the emulator and fixed:** Home's "Latest" said "Didn't finish" for a task you stopped, while Activity
  said "Stopped by you"; now both say "Stopped by you" with the stop icon. The expanded approval notification showed
  the question twice; now once, under "OpenMob needs your approval".

## Old routes that remain

None of MainActivity's old screens remain. Kept as they were, outside the redesign: the agent indicator overlay and
its Stop pill, Android's own lock prompt, the notification actions.

Not ported, on purpose: the raw event log (Activity replaces it; full logs are on the dashboard).

## Leftovers not done

- From the reviews: the Faster mode "Turn off" button colour; a nit in the blue inner frame; the Ready "Done"
  alignment at 1.0; the dark Stop pill colour; "asked you 0 times" still shown; the interrupted-lock styling.
- Samsung's wording of the restricted-settings path ("Installed apps") is from Android's docs, not seen on a Samsung.
- An unknown restricted-settings state counts as restricted, so the help can show when it isn't needed.
- At 2.0 the approval screen's fixed bar takes about a third of a small screen; the exact action may need a scroll
  (the rule above the buttons says so).
- The text-overflow test can't see texts that clear their own semantics (the colour swatch labels); those were
  checked in the screenshots.

## Phone-only checks (the owner's Samsung, after the merge decision)

1. A real overlay over the approval screen: hidden, and a touch through it doesn't approve.
2. What TalkBack and another accessibility service read on the approval screen (Approve and "Always allow" are
   data-sensitive).
3. The screen-lock prompt itself, approve and cancel.
4. TalkBack on Home and setup: the order, and that it refreshes (the emulator's uiautomator dump went stale once
   OpenMob's service was on).
5. The R8 release signed with the owner's key: installs, launches, pairs (only debug-signed R8 builds ran here).
6. Samsung's restricted settings for a sideloaded app, and the help text's path.
7. The notifications' look on One UI (connection, approval, Undo).
8. The themed (monochrome) icon on the home screen.
9. 200% text on the Samsung: Font size and Display size both at maximum.
