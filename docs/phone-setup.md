# Set up a phone

Before any code or agent can use a phone, its owner installs the OpenMob app on it and pairs it
with their account. This page is what the owner does, and what they see afterwards. It takes about
five minutes.

You need an **Android phone with Android 11 or newer**, with a screen lock (PIN, pattern, password
or fingerprint) set up. iPhones aren't supported: see [iPhone](#iphone).

## 1. Get the app

The app is downloaded from your OpenMob server, at `https://<server>/download/openmob.apk`. You
don't need to type that address: the pairing page in step 2 links to it. The file is named after its
build (`OpenMob-<build>.apk`) and is never served from a cache, so a new download is always the newest app.

OpenMob isn't on Google Play. Google Play's policies don't allow an app that lets an AI agent see
and operate the whole phone through Android's accessibility service, which is exactly what
OpenMob does. So Android installs it as an app "from an unknown source":

1. Download `OpenMob.apk` and open it.
2. If Android asks, allow your browser to **install unknown apps** (Android shows a switch for it),
   then go back and tap **Install**.

## 2. Pair it with your account

1. On a computer, open your dashboard, click the account button (bottom left) → **Connect a phone**.
   It shows a QR code.
2. Scan the QR code with the phone's camera. It opens a page on the phone, **Set up this phone**,
   with the app download (step 1, first time only) and an **Open OpenMob** button.
3. Tap **Open OpenMob**. The phone asks once, with its own screen-lock prompt:
   **Connect this phone to *\<server\>*? as *you@example.com***. Touch the fingerprint sensor (or
   enter your PIN, pattern or password). That's it: no sign-in on the phone.

So pairing is three steps and two taps plus one touch: scan, **Open OpenMob**, confirm.

What makes this safe:

- **The QR code is the credential.** The dashboard makes it only when you open **Connect a phone**.
  It works once, for 2 minutes, only for your account, and it has 128 bits of secret (the server
  keeps only a hash). A few wrong guesses void it, and the server limits attempts per network
  address and per account.
- **The phone confirms with its own screen.** The prompt names the server and the account, and
  needs the phone's screen lock, so a link from anywhere else can't pair your phone silently.
  OpenMob only pairs phones that have a screen lock.
- **The phone never holds your sign-in.** It gets its own device key, stored encrypted with a key in
  the phone's hardware keystore. That key can only drive this phone, and you can revoke it.
- **You see every new phone.** The dashboard shows **New phone added: SM-S948U1** with a one-click
  **Remove**, and each pairing is written to your account's audit log (Developer › Logs).

If the QR code expired, click **Make a new code** on the Connect page. Can't scan? The Connect page
also shows the address to open on the phone, or you can type a short code instead (below).

### Can't scan: type a code instead

1. On the Connect page, under the QR code, click **Can't scan? Show a code to type**. The dashboard
   shows a code such as `K7P-2QX`. It works **once, for 5 minutes**, and only for your account;
   making a new one cancels the old one.
2. In the app, on **Pair with your account**, tap **Type a code instead** and type it. Capitals or
   not, dash or not. Codes never use 0, O, 1, I or L.
3. The phone shows the account and the server in large text, with **Only pair with your own
   account. OpenMob will never ask you for a code.** Check that it's your own email. If the address
   has unusual characters, the phone says so: check it letter by letter. If it isn't yours, tap
   **This isn't me**.
4. At the same time, the Connect page shows **A phone entered the code and is confirming:** and the
   phone's model. If that isn't the phone in your hand, click **Not my phone: cancel the code**.
5. Tap **Pair with this account** and confirm with the screen lock. The phone gets the same device
   key a QR code gives.

After pairing, the phone shows a **Paired with …** notification with **Undo**, and the Connect page
shows the phone with **Undo: remove this phone**. Either one removes the phone at once, with no
screen lock. Five wrong tries cancel a code; the dashboard shows how many are left, the phone
doesn't.

Never type a code someone else gave you, and never read your code to anyone: whoever types it on
their phone, and confirms, gets a phone on your account (your Connect page would show it confirming).

**For your own server**, in the app tap **More options** › **Your own server**, enter its address
(`https://` only, plain `http://` only on your own network), then type the code from that server's
dashboard.

**No computer at hand?** In the app, tap **More options** › **Sign in on this phone** and sign in
with your OpenMob account. The app uses that sign-in only to make a pairing code, signs out again at
once, and then shows the same one-touch confirmation. It never keeps the session.

### Developers: one command over USB

With the phone plugged into your computer (USB debugging on), one command installs the app, sets
it up and pairs it:

```sh
export OPENMOB_SERVER=https://openmob.example.com
export OPENMOB_API_KEY=om_live_…   # a key with the devices:add scope
openmob phone add                  # --serial SERIAL with several phones, --apk PATH for a local build
```

It needs an API key with the **`devices:add`** scope (make one on the dashboard's **Developer API** page, or
`openmob key create you@example.com --scopes devices:add` on the server). It's never a default
scope: it can start pairings for your account. The command:

| Step | How | On a second run |
|---|---|---|
| Install or update the app | `adb install -r` with the server's `/download/openmob.apk` (or `--apk`). adb installs aren't subject to Android's "restricted settings" | Skipped when the installed app is the same build |
| Notifications | `pm grant … POST_NOTIFICATIONS` (Android 13+) | Skipped when granted |
| Run in the background | `dumpsys deviceidle whitelist +dev.openmob.companion` | Skipped when exempt |
| Accessibility | Adds OpenMob to `enabled_accessibility_services`, **keeping every other service** you have on, and sets `accessibility_enabled 1` | Skipped when on |
| Screen sharing | Tries `appops set … PROJECT_MEDIA allow` and reports whether Android kept it. Android 14+ still asks once per connection, the first time you open the live view | Tried again |
| Pair | Makes a single-use, 2-minute enrollment code and opens the app on it. **The phone still shows its confirmation** naming the server and your account, passed with its screen lock: the server doesn't pair the phone until then | Skipped when the app is already paired to your account (read from a debug build) |
| Verify | Waits for the phone to come online and prints a summary with the time taken | |

So `phone add` needs one touch on the phone (the confirmation), plus **Allow** on "Allow USB
debugging?" the first time you plug in. Re-running it fixes whatever is missing. It explains what to
do when there's no phone, the phone hasn't allowed this computer, several phones are plugged in, the
phone runs Android older than 11, or a Samsung phone is plugged in but invisible to adb because of
**Auto Blocker** (Settings › Security and privacy › Auto Blocker › off; checked on macOS).

For a server on your own computer, run the command with the address you use locally: the server
gives the phone its network name (`http://<computer>.local:<port>`), so keep the phone on the same
Wi-Fi.

## 3. Finish the checklist in the app

After pairing, the app's setup screens show the rest, in order (**2 of 3**, **3 of 3**):

| Step | Why |
|---|---|
| **Allow OpenMob to control this phone?** (Accessibility) | The screen says what the agent can see and do, and where screen contents go. Tap **Agree and open Settings**. On Samsung: **Installed apps → OpenMob → On → Allow**. On other phones, look under **Downloaded apps** (sometimes called Installed apps). Once enabled, OpenMob tries to return to its setup screen automatically |
| **Two last switches: Notifications** | For the always-visible "agent active" notification, with its Stop and Disconnect buttons, for approval requests, and for your agent's questions. Tap **Allow**, then one tap on Android's prompt |
| **Two last switches: Run in the background** | Tap **Allow**: Android's own "Let app always run in background?" prompt. Without it, Android may cut the connection when the screen is off. On **Samsung** phones, the screen then offers **Never sleeping apps** (Battery › Background usage limits) as well; on **Pixel** the standard prompt is all it takes |
| **Share the screen for the live view** | In **Settings › Connection and pairing**, and only once someone opens this phone's live view on the dashboard (the phone also gets a notification). It's never asked for at setup or when connecting |

**"App was denied access", "Restricted setting", or a greyed-out switch?** Android blocks the
accessibility switch for downloaded APKs until you allow it once. Dismiss the denial, return to
OpenMob: the Accessibility setup screen shows the steps. Tap **Open App info**, tap the ⋮ menu
(top right), tap **Allow restricted settings** and confirm. Then turn OpenMob on in Accessibility.
If the menu doesn't have that option, try turning OpenMob on in Accessibility once first: Android
only offers the approval after showing the initial denial. The app keeps a direct App info shortcut
visible even when the phone cannot report its restriction status. (`openmob phone add` avoids this:
apps installed over adb aren't
restricted.)

Android's per-service Accessibility details shortcut requires a system/installer-only permission;
ordinary apps cannot reliably open the switch itself. OpenMob uses the supported Accessibility
screen, requesting that Settings highlight OpenMob where supported. It does not bypass Android's
restricted-settings approval or enable the service on the user's behalf.

## 4. Connect

Once Accessibility is on, the app connects by itself after pairing; later, tap **Connect**. While it's connected, a notification says the OpenMob agent can control
the phone, and the phone shows as online (`"online": true` in
[`GET /v1/devices`](api.md#get-v1devices)).

**Smooth live view** (under **Settings › Connection and pairing**) shows the screen as video on your dashboard. Connecting
never asks for screen sharing: the first time someone opens the phone's live view, the phone offers
it (a notification and a **Share screen** step), and Android asks once for that connection. Until
then, and with the switch off, the dashboard shows a few screenshots a second. Either way, tasks
work the same.

Keep the app connected while you want agents to be able to use the phone. If the connection drops
(Wi-Fi to mobile data, for example), the app reconnects by itself, retrying every few seconds. A
task that was running waits up to 45 seconds for the phone to come back.

## Locks and the screen

A task needs the phone **awake and unlocked**:

- A phone with a **PIN, pattern, password or fingerprint** lock must be unlocked by you. OpenMob
  never types a PIN or password. A task for a phone that is locked, or whose screen is off, is
  refused with `409 phone_locked` ("Unlock it to continue"), and a step of a multi-phone run waits
  (`waiting_for_phone`) until you unlock it.
- A **swipe-only** lock (no PIN) is dismissed automatically, and OpenMob wakes the screen if needed.

For a phone that agents use often, set the screen timeout to a few minutes so it doesn't lock in
the middle of your work. The app also keeps the screen on while an agent is working (only then).
If the phone locks anyway, a task **pauses** with "Unlock your phone to continue" and carries on once
you unlock it.

**Test-phone tip:** on Samsung phones turn off **Settings › Display › Accidental touch protection**,
and keep the phone **face-up** during tasks: face-down or in a pocket, the proximity sensor can turn the
screen off and lock it mid-task.

### Permission dialogs ("Allow Chess.com to …?")

When an app asks for a permission during a task, OpenMob answers by your settings, without the AI. Set them on
the dashboard's **Your phones** page under **Permission prompts** (or `permission_prompts` in the phone's
permission settings):

| Permission | Settings | Default |
|---|---|---|
| Location, camera, microphone, contacts, photos and media, phone, SMS, calendar, nearby devices | **Ask me** · **Only this time** · **While using the app** · **Don't allow** | Ask me |
| Location accuracy | **Approximate** · **Precise** | Approximate (OpenMob picks the Approximate card first) |
| Notifications | **Don't allow** · **Allow** | Don't allow |

- **Ask me** asks you on the phone ("Allow **Kalshi** to use your **location**?"). A yes picks **Only this
  time**, else **While using the app**. Tick **Always allow for Kalshi** on that prompt to keep that answer for
  that app.
- OpenMob **never** picks **Allow all the time** on its own; if that's the only way to grant, you're asked.
- Allowing more (Only this time, While using the app, Precise, Allow) needs your approval on the phone with its
  screen lock; asking more applies at once.
- A request from an app other than the one the task is using is always asked about.
- Under **Don't ask**, nobody can be asked: anything set to Ask me is denied; Only this time and While using the
  app still apply.
- **Android 14 and later:** the system doesn't let OpenMob read permission dialogs, so these settings can't be
  applied there. The task pauses and your phone shows "**Kalshi** is asking for **location**: choose on your
  phone, then the task continues"; answer the dialog yourself and the task carries on.

## While an agent works

- The notification and the app say who is using the phone: "**CI bot** is using your phone", with
  the name of the API key, and later "CI bot stopped using your phone".
- The app's **Activity** list shows what the agent hears, does and says.
- **To stop it:** tap **Stop and disconnect** in the notification. That stops the running task and anything
  queued, and disconnects the phone; tap **Connect** again when you want agents back. Over the API,
  the task ends as `cancelled`; for a [multi-phone run](api.md#orchestrations), the whole run ends
  (`stopped_on_phone`).
- You can also tap the on-screen **■ Stop** button or **Stop task** on OpenMob's Home, or say or type
  "stop" in the app's composer, with the same effect on the task, without disconnecting.
- **Questions** ("Which account should I use?") appear on the app's Home under **Your agent asks**.
  You can answer there, or whoever started the task answers through the API. Wherever you are on the phone, a
  notification "**Your agent has a question**" tells you (it never shows the question itself, so the lock
  screen, a watch or another app can't read it); tap it to open OpenMob's Home, read the question and type your
  answer. Never type a password or a code in an answer. The ongoing notification also shows what the agent is
  working on only while the phone is unlocked. While the question is open, the ongoing notification reads
  "Waiting for your answer" and the screen's border turns dotted. With notifications off you still see the
  question in the app.

### Approving risky actions

Before the agent buys, sends, deletes or posts something, you get an approval request: a
notification (**Approval needed**) with the question, **Deny** and **Review**. Tap **Review**, read
what it wants to do and who is asking, then tap **Approve with screen lock** and confirm, or tap
**Deny**. A routine step that this phone's own check stopped can show **Allow** instead, which needs
only your tap.

- The request goes to **all** your online phones, so you can answer on whichever you're holding.
  It names the phone that would act. The first answer counts and the other phones drop the request.
  A phone answers for your other phones only once it's trusted for approvals (**Trust for approvals**
  under **Your phones** on the dashboard); a phone re-paired without proving its old key comes back
  untrusted.
- Agents can't tap OpenMob's own screens, and approving anything beyond a routine step needs your
  screen lock, so the AI using your phone can't approve for itself.
- No answer within about 2 minutes counts as **Deny**.
- Denying a step of a multi-phone run ends the whole run.

See [Safety & approvals](safety.md) for what the agent may and may not do.

## Troubleshooting

| Symptom | Fix |
|---|---|
| The phone shows offline, or tasks fail with `409 phone_offline` | Open the app and tap **Connect**. Check the phone has a network connection |
| `409 phone_locked` | Unlock the phone (and wake the screen), then retry |
| `409 app_update_required`, or "Update required" on the phone | The server needs a newer OpenMob app. Tap **Download update** on the phone's Home screen, open the download and choose **Update** (Android may ask you to allow installs from your browser). Your chats and pairing stay |
| "This app is too old for the server" | The server speaks a newer protocol than this app. Download the app again from your server (`<server>/download/openmob.apk`) and install it over this one |
| `409 phone_unresponsive` | The app is connected but didn't answer in 5 seconds, usually because Android put it to sleep. Wake the phone, open the app, and make sure battery optimisation is off for OpenMob (below) |
| It disconnects whenever the screen turns off | Allow OpenMob to run in the background. **Samsung:** Settings → Apps → OpenMob → Battery → **Unrestricted**, and remove OpenMob from "Sleeping apps" under Battery → Background usage limits. **Pixel:** Settings → Apps → OpenMob → App battery usage → **Unrestricted** |
| "Accessibility is off" in the app | Turn OpenMob on again in Settings → Accessibility. Some phones turn it off after an app update |
| A task failed with "The phone didn't reconnect within 45 s" | The connection dropped mid-task and didn't come back in time. Check the network and battery settings, then run it again |
| No approval notifications | Allow notifications for OpenMob. Approval requests also show in the app |
| The QR code doesn't work | It's valid once, for 2 minutes. Click **Make a new code** on the Connect page. Still can't scan? Use **Can't scan? Show a code to type** |
| "Wrong code" for a typed code | Check it on the Connect page. It's valid once, for 5 minutes, and five wrong tries cancel it: click **Make a new code** |
| "This code was already entered on another phone" | A second phone typed the same code, so it was cancelled for both. Make a new one and type it only on your phone |
| "This phone is already paired with this account" | In the app, **Unpair this phone** (or **Remove** it on the dashboard), then pair again |
| "Removed on this phone; also remove it on the dashboard" | The phone couldn't reach the server when you unpaired. Click **Remove** next to it under **Your phones**. The app also sends the unpair again the next time it connects |
| "Too many pairing attempts" | Several wrong codes came from your network or for your account. Wait 10 minutes and make a new code |

Every phone paired to your account, online or not, is listed under the account button →
**Your phones** (and on the Connect page). **Remove** revokes its key and closes its connections at
once. In the app, **Unpair this phone** does the same from the phone, proven with its own key.

## iPhone

iPhones aren't supported for end users: iOS doesn't let one app control others, so there is no
OpenMob app for iPhone.

For local development only, an iPhone can be driven from a **Mac** that has Xcode and Apple's
WebDriverAgent (the UI-testing tool Appium uses) installed, with the phone attached by USB and in
Developer Mode. The Mac runs `openmob bridge --ios` to connect it to a server, where it appears with
`"platform": "ios"`. It needs a source checkout of OpenMob, an Apple developer signing setup, and
the Mac staying on, so it isn't a way to offer OpenMob to iPhone users.
