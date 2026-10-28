# What OpenMob remembers (preferences memory)

OpenMob can remember short facts you confirm, so you don't repeat yourself: "add my favorite soda to my Amazon
cart", "text my sis I'm late", "install it from the app, not the website". Design:
[the spec](superpowers/specs/2026-10-20-preferences-memory-design.md). It ships **off** (`memory: false`,
`OPENMOB_MEMORY=1` to turn it on) until the security review passes ([review packet](memory-review-packet.md)).

## What it is

A **preference** is a note of at most 300 characters. Three kinds:

| Kind | Example | Used |
|---|---|---|
| About you | "I prefer dark mode" | At the start of your tasks (up to 10, newest-used first) |
| About an app | "In Amazon my favorite soda is Coke Zero, 12-pack" | When your request names the app, or the first time the task opens it (up to 5) |
| A person | "sis" = "Maya Lee" | When your request says the relation or the name |

A person note stores a relation and the contact's **display name** as it appears in the phone's Contacts, never a
number or an email. The agent finds the person by that name in the messaging app; if none or several match, it asks you.

## How a note gets saved

- **Only with your tap.** The agent can propose a note (when you say "remember ...", or at most one it noticed
  during a task). It shows as **"Save this? ..."** with **Save** and **Not now**. Nothing becomes active
  otherwise. Text on a screen (a message, a web page, an ad) can at most become a proposal you can ignore.
- Limits: 200 notes and 20 waiting proposals per account, one new proposal per task.
- You can edit, delete and confirm notes on the dashboard (**What OpenMob remembers**) and on the phone
  (Settings, **What OpenMob remembers**). Adding a note directly on the phone page is not built yet; use "remember
  ..." in a chat (you tap Save) or the dashboard.

## Where it applies

Only to tasks **you** start from the dashboard or from a **trusted phone** with memory switched on. Tasks from the
developer API, MCP (including the drive level), orchestrations and the terminal get none and cannot create any. An
untrusted phone (trust it on the dashboard, "Trust for approvals") gets none and cannot see your notes. In
"Don't ask" mode, people notes are not used.

## What you see

- In the thread: **"Used your preferences: ..."** names the notes the task relied on.
- Before a message goes to a remembered person: **"Sending to Maya Lee - your sis, from your saved preferences"**.
  The line appears only when that person's contact name is on the screen (not in a text field); otherwise there is no
  line (owner, 2026-10-21, review 5: a remembered name shown while the screen is someone else's chat would mislead).
- A suggestion shows as a card, **"Save this? ..."** with Save / Not now; once saved it reads **"Saved: ..."**.
- Old threads store a note's id, not its text. A deleted note shows as **"a deleted preference"** ("Sending to a
  deleted preference" for a deleted person), an unreadable one (untrusted phone) as **"a saved preference"**.
- Notifications never show note text.

## Privacy

- A note goes to the AI provider only when it is relevant to the task (about-you notes with each of your tasks, app
  and person notes when the request or the app in front matches). When **Faster mode** is on, a matched note can
  also reach **TypeSafe** (Jev), our disclosed screen-classification processor, inside the request it judges.
- Notes live in `memory.sqlite` in the data directory (owner-only). Note text is not written to history steps,
  events, logs, the audit log (ids and counts only) or notifications by the memory code itself; the agent's
  answers can quote it (below). The answer check (`agent/answer_check.py`)
  counts saved preferences as seen, and what it flags is kept as a count only, never the words.
- **Deleting a note removes the note itself everywhere except backups until they expire**: the row, the search index and the
  database's write-ahead log are overwritten, thread lines re-render as "a deleted preference", and the text only
  survives in Fly volume snapshots, which expire after **5 days**.
- **Deleting a note does not reach the agent's answers.** When you ask the agent to read or list what it remembers
  ("what do you know about my sis?"), its answer quotes note text, and that answer stays in the chat thread,
  Activity and the task history (and was spoken, if voice is on), and the agent's list of recent requests keeps it
  as context for its next five tasks (until the server restarts). Deleting the note doesn't remove those copies.
  Otherwise the agent is told not to repeat note text unless asked.
- No account-deletion flow exists yet, so `Memory.delete_all` is not wired to anything. Delete notes one by one until
  it is.
- The privacy policy (launch blocker 3) must say: what is stored, that relevant notes are sent to the model provider
  and to TypeSafe with Faster mode, and the backup window above.

## Known limitation

A remembered person gets **no extra phone prompt**: inside a task you approved (or one typed on the phone), a wrong
person note can message the wrong person. The thread's "Sending to ..." line comes before the send, ambiguous names
ask, and people notes are off in "Don't ask" mode. The phone's gate never reads memory. See
[safety](safety.md#memory).

## Switch

`memory: false` (default) or `OPENMOB_MEMORY=1`. Off: no retrieval, no tools, `/memory` and `/api/memory` answer
404, the nav link and the phone row are hidden, memory lines disappear from threads; the data is kept.

## Cost

Measured in-process, no phone or provider: under 0.3 ms median per task, no extra model call, the system prompt
identical and the tools list only extended (`docs/benchmarks.md`, "Memory overhead"). Real provider cache hits and
on-phone latency are measured in the owner's Samsung test.
