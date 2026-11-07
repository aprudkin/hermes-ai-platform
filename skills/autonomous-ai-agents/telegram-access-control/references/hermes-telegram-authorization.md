# Hermes Telegram Authorization Reference

Official source: <https://hermes-agent.nousresearch.com/docs/user-guide/messaging/telegram>

## Environment-variable scopes

| Purpose | Setting | Value shape |
|---|---|---|
| Allow a person in DMs, groups, and forums | `TELEGRAM_ALLOWED_USERS` | Comma-separated positive numeric user IDs |
| Allow a sender in groups/forums only | `TELEGRAM_GROUP_ALLOWED_USERS` | Comma-separated positive numeric user IDs |
| Allow everyone in a specific group/forum | `TELEGRAM_GROUP_ALLOWED_CHATS` | Comma-separated negative chat IDs |

`TELEGRAM_ALLOWED_USERS` is the appropriate setting when an individual should be allowed to write the agent privately. Keep distinct people’s IDs in that single comma-separated list.

## Safe confirmation procedure

1. Read the active profile’s configured allowlist without exposing the bot token.
2. Treat an unknown ID as unassigned until a live incoming event identifies its `from.id`, or the person reports their ID from `@userinfobot`.
3. Do not rely on an empty `getUpdates` response: it only says no events are currently queued.
4. After authorization changes, require a real message from the new user as the completion check.

## Group visibility

Telegram privacy settings affect whether a bot receives ordinary group messages. A bot promoted to group admin receives all group messages; otherwise disable BotFather Group Privacy and remove/re-add the bot after changing the setting. Visibility does not substitute for sender authorization.
