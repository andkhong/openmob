# The phone reads chats (2026-10-17)

Home becomes the current chat's thread and the ☰ drawer lists the chats, the same chats as the web dashboard
(`/api/chats`, one `chat_id` per task). This note covers the server side: how the phone reads them over its existing
WebSocket. Protocol: `docs/phone-protocol.md` §3.6.

## Scope (owner decision)

A trusted phone sees all of this account's chats, matching the web: the drawer lists chats started on this phone, on
the dashboard, and on the account's other phones. Opening a chat (making it the one new tasks go into) follows the
web's rule: only a chat with this phone. Another phone's chat can be read, not continued.

**Own chats until trusted** (owner, 2026-10-18; review 3 K3-M3): a phone that isn't trusted for the account (the
device record's `trusted` flag: the account's first phone is; a later one is once the owner chooses "Trust for
approvals" on the dashboard, or a trusted phone vouches for it) lists, searches, reads, opens, renames and deletes
only chats with itself (the chat's `device_id` is this phone's). Every other chat of the account, including the
dashboard's and API chats with no phone, answers `unknown`, exactly like a missing chat; renames and deletes of them
aren't pushed to it. Its `chats` answers say `this_phone_only: true`, and the drawer says why the others are missing.
The dashboard's own session keeps the full account view.

## What the phone can do

| Message | Answer | Reuses |
|---|---|---|
| `chats_list` {before?, limit ≤ 50} | `chats`: id, title, updated, origin, this_phone; `more` | `History.list_chats` (with an offset) |
| `chat_read` {chat_id, before?} | `chat`: the turns (request, summary, outcome, steps, asks, stop lines), newest 30 per page | `History.events` + `History.turns`, the rows the web's chat view replays |
| `chat_open` {chat_id} | `chat_opened` | `Coordinator.open_chat`, as `POST /api/devices/{id}/chat/open` |
| `chat_new` {} | `chat_opened` {chat_id: null} | `Coordinator.clear_log`, as `POST …/chat/new` |
| `chat_rename` {chat_id, title} | `chat_renamed` {chat_id, title} | `History.rename_chat`, as `PATCH /api/chats/{id}` |
| `chat_delete` {chat_id} | `chat_deleted` {chat_id} | `phone_chats.delete_chat`, shared with `DELETE /api/chats/{id}` |

**2026-10-18 audit fixes** (owner): the dashboard's New chat / open chat is pushed to the phone (`chat_opened`);
the drawer pages at its end and the thread at its top; the title search runs on the server over all of the
account's chats (`q`, account-scoped, LIKE with `%` and `_` escaped); turns carry the owner's corrections and
answers and the agent's past questions (`messages`), shown as the owner's bubbles with a caption and as read-only
question cards; Jev lines are hidden like on the web; a turn with no end and no live task is `interrupted` ("Didn't
finish"); chats from the API and MCP say so ("From the API", "From MCP").

**Rename and delete** (owner, 2026-10-17): long-press a chat in the drawer, or TalkBack's actions. Any chat the phone
can see (on a trusted phone, the dashboard's and other phones' too). Delete has a confirmation and no screen lock: it removes history only,
which the account's own web session can already do; note it for the security review. Deleting a chat with a running
task is refused, on the web too (409, a bug fixed here: the task used to keep recording into the deleted chat); a
session showing the deleted chat continues as a fresh chat. Successful renames and deletes are pushed to the
account's connected phones: from a phone, to its other phones; from the web (`PATCH`/`DELETE /api/chats/{id}`), to
all of them (fixed 2026-10-18: a web delete used to leave the chat in the phone's drawer until it reconnected). An
untrusted phone is told only of its own chats.

## Rules

- **Account.** Every query takes the session's own `account_id` (from the device key the socket proved). A chat id
  of another account answers `unknown`, exactly like a missing one: nothing tells the two apart.
- **Trust.** An untrusted phone's queries also take its own device id (`own_only` in `phone_chats`,
  `History.list_chats(device_id=…)`): another phone's chat answers `unknown` as a missing one does, for every message.
  Trust is read on each message, so trusting the phone on the dashboard widens its view at once.
- **Device auth.** Before answering any chat message the server re-checks the pairing (`pairing_still_valid`), not
  only every `LINK_RECHECK` seconds: a revoked, unpaired or re-paired device gets nothing and its socket is closed.
- **Redaction.** Nothing new is read: event and turn text is redacted when it is recorded (`sensitive.redact` in the
  runner; typed text redacted in steps), and the phone gets the same rows the web shows. Not sent: usage and token
  counts, feedback, models, step coordinates, anchors, packages. Step lines are the logged `action` texts the web
  already shows.
- **Size.** 50 chats per page, 30 turns per page, 40 step lines per turn; texts capped (titles 120, requests and
  summaries 600, step lines 200). A page is read in SQL: the turns' order from the `events_by_turn` index
  (`History.turn_order`), then only that page's events and turn rows (`History.turn_page`), not the chat's whole log
  (review 3 S3-L1: on a 20,000-event chat, one read went from about 29 ms to about 11 ms holding History's lock).
- **Limits.** 5 chat messages a second per socket, 20 at once (`phone_chats.RateLimit`); more answer `rate_limited`.
  Numbers are clamped (`phone_chats.number`), and anything a reply raises answers `bad_request` (`safe_chat_reply`):
  bad input never drops the phone as if its network had gone (review 3 S3-L2).
- **Origin.** Only the source `phone` is a phone. A drive session's chat is `drive` ("From an outside agent"), the
  server's terminal is `local` ("From the server's terminal"), and a chat with no recorded source is `unknown`
  ("Source not recorded") (review 3 S3-L3).
- **On the phone.** Kept in memory for the session only; nothing is written to storage beyond the existing Activity
  log (TaskHistory). Disconnected, Home says the chats load again on connect.
- **Who can ask.** The messages come only from the OpenMob app's own UI over this socket. The agent can't send them:
  it has no access to the socket, and the phone refuses its taps on OpenMob's own screens.
- **Switching while a task runs** is refused (`busy`), as on the web: open or new chat waits until the task ends.
  The phone says "Stop the current task first, or wait for it to finish."

## Sensitive

The chat list and turns are the account's task history: requests ("Pay the rent to …"), results, and what the agent
did. That is why: account-scoped queries, the re-check of the pairing, no storage on the phone, and the Activity
screen's existing rules (no FLAG_SECURE on Home, owner 2026-10-17) apply unchanged.
