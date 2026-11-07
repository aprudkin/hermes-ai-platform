# Telegram Observation Modes

## Decision table

| Goal | Configuration | Agent dispatch | Main tradeoff |
|---|---|---:|---|
| Reply only when addressed | `require_mention: true` | On mention/reply/command | Ordinary chatter is not retained |
| Retain chatter silently | `require_mention: true`, `observe_unmentioned_group_messages: true`, chat in both `allowed_chats` and `group_allowed_chats` | Only when addressed | Group-scoped authorization is broadened |
| Respond to every message | Chat in `free_response_chats` | Every message | Noisy and exposes the full platform toolset to each dispatched turn |
| Alert on a narrow event | Silent observation plus one-shot `no_agent` cron watcher | No agent needed | Classifier must be deterministic and tested |
| Track recurring amounts/totals | Silent observation plus a stateful `no_agent` ledger watcher | No agent for ingestion; agent only for addressed reports | Requires durable dedupe, day boundaries, and tested parsing |

## Delivery checks

- `getChat` proves the bot can resolve the group.
- `getChatMember` proves membership/admin status.
- `getMe.can_read_all_group_messages` reports whether BotFather privacy mode is disabled.
- Administrator status or disabled privacy enables future ordinary-message delivery; neither grants old history.

## Authorization boundary

`allowed_chats` is the response-location gate. `group_allowed_chats` is a sender authorization scope for the whole group. Silent observation currently requires the group-scoped list, so surface that security tradeoff before enabling it in a group with untrusted participants.

## One-shot cron shape

Use a script-only cron job:

- schedule: `every 1m`
- `no_agent: true`
- script: copied watcher under `$HERMES_HOME/scripts/`
- deliver: `telegram:<chat_id>`
- failure delivery: `local`

The script prints nothing when there is no match. This matters: empty stdout suppresses delivery, while placeholder text creates chat noise.

## Recurring ledger shape

Use the same silent-observation routing but process all new active user rows, because addressed messages are not marked observed. Persist a source-row cursor and normalized ledger separately from `state.db`; emit only total-check results, and answer addressed period requests from the ledger. Extend or update the existing watcher job when the requirement changes from first-match alerting to ongoing bookkeeping—parallel jobs create duplicate scans and conflicting notifications.
