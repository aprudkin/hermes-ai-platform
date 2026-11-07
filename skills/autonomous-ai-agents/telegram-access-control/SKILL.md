---
name: telegram-access-control
description: "Use for Telegram access and service-message cleanup."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [telegram, authorization, allowlist, gateway, security]
    related_skills: [hermes-agent]
---

# Telegram Access Control

## When to Use

Use for Telegram user allowlists, group invitations/access, identity-to-ID verification, authorization audits, and deleting join/leave service messages. For missed service-message IDs, follow the verified temporary-reply recovery procedure below before asking the owner for links or declaring the operation unavailable.

Use when configuring, auditing, or verifying who may interact with a Telegram-connected agent. Treat this as an authorization task: distinguish a person’s immutable numeric Telegram user ID from their mutable `@username`, and do not broaden access while merely investigating.

## Authorization model

- For direct messages and all chat types, use a **numeric user-ID allowlist**. In Hermes this is `TELEGRAM_ALLOWED_USERS`, a comma-separated list.
- Group/chat authorization and sender authorization are different scopes. A negative group ID belongs in `TELEGRAM_GROUP_ALLOWED_CHATS`; a user ID belongs in `TELEGRAM_ALLOWED_USERS` (or the group-only sender allowlist when DM access is not intended).
- Never use a wildcard/allow-all setting for an agent that can access files, shells, or connected services.
- Preserve existing authorized IDs unless the operator explicitly asks to remove or replace someone.

## Verify an existing allowlist

1. Resolve the active profile home from `HERMES_HOME`.
2. Read only the relevant allowlist values from the profile’s configuration/secrets store. Never print or transmit the bot token.
3. Report the exact configured count and IDs to the operator only when they are authorized to see them.
4. Do **not** infer a person’s identity from an unlabelled numeric ID. An allowlist proves authorization, not ownership.

## Match a person to an ID

Use one of the following verified paths:

1. Ask the person to message `@userinfobot` and supply the returned numeric ID; compare it with the configured allowlist.
2. Have the person message the agent directly or trigger it in an authorized group (for example, through an explicit mention). Inspect the live incoming Telegram update’s sender `from.id` and name, then compare `from.id` to the allowlist.

Being an admin in a group does not by itself establish a complete, queryable roster of members through ordinary bot updates. If no qualifying update is available, state that identity cannot yet be confirmed and use one of the paths above.

## Authorizing a user to control Hermes

Use this procedure for agent-access permission, not for adding a person to a Telegram group. A group invitation alone does not authorize expanding who can control the agent.

- Confirm the exact numeric ID and requested scope before changing anything.
- For Hermes, add the ID to the existing comma-separated `TELEGRAM_ALLOWED_USERS` value; retain the current IDs.
- Apply changes using the documented Hermes configuration mechanism, not hand-edited YAML.
- Restart/reload the gateway only if required by the configured deployment, then have the newly authorized user send a test message. Confirm both receipt and correct authorization.

## Invite a person into an existing Telegram group

1. Distinguish group membership from Hermes sender authorization. For a request to add the owner to a group with a known contact, resolve the existing shared chat from profile-local routing metadata; do not change allowlists or restart the gateway just to issue an invitation.
2. Verify `getMe`, `getChat(chat_id)`, and `getChatMember` for the exact bot, requested person and known contact. Use immutable user IDs and current membership to distinguish the intended conversation from another group with the same participants. Require bot administrator status with `can_invite_users` before creating a link. If the person is already a member, report that instead of creating unnecessary access.
3. Use `createChatInviteLink` for an additional, bounded invitation: explicit `chat_id`, a short purpose label in `name`, a computed `expire_date`, `member_limit=1`, and `creates_join_request=false` when direct entry is authorized. Prefer this over exporting/replacing a primary link, which can invalidate other invitations. Treat a one-entry link as bearer access, not an identity-bound invitation; share it only with the intended requester.
4. Persist the returned invitation privately before attempting further operations, so interruption does not lead to issuing duplicate links. Verify the exact link and its creator, expiry, member limit and revocation state. Where a separate getter is unavailable, a same-settings `editChatInviteLink` can confirm Telegram still recognizes the exact created link without creating another one.
5. Give one clickable entry link in the requester's DM with its actual expiry. Distinguish an invitation from completed membership: say that the person needs to enter, not that they have already been added. Only a subsequent `getChatMember` result or delivered membership update establishes that they joined.

## Group intake and response verification

1. Resolve the exact bot identity with `getMe`, then check its membership in the requested chat using `getChatMember`. Administrator visibility proves that Telegram can deliver ordinary messages, not that Hermes will dispatch them.
2. Read the active profile's YAML and only the relevant legacy env gate values. Check sender authorization, chat response allowlist and mention requirements separately; env overrides can survive a YAML-only change.
3. For an operator-authorized interactive group where ordinary messages should address the bot, add that exact chat to `platforms.telegram.free_response_chats`, retaining existing entries. Do not disable mention requirements globally or put a passive bookkeeping group in this list.
4. Verify configuration with the gateway loader, then apply it through the deployment's supported reload/restart path. If restart waits for the current turn, report it as queued, not completed; verify a new process and Telegram connection afterward.
5. Require a real group-origin test. Check the incoming log's chat ID and the matching response delivery, not a successful DM ping, a healthy polling flag or an outbound API probe alone. Diagnose lost messages along the intake gates before widening authorization.

## Reference

- `references/hermes-telegram-authorization.md` — Hermes-specific setting names, scope distinctions, and official documentation links.

## Service-message deletion

Telegram Bot API `deleteMessage` explicitly supports service messages, including member joins/leaves; do not confuse these with the undeletable supergroup/channel/forum-topic CREATION notifications. The usual deletion window is under 48 hours. In a supergroup verify the actual bot's `can_delete_messages` right, not merely administrator or invite privileges. `deleteMessages` accepts 1–100 exact IDs but skips missing messages, so success does not prove that every requested target existed or was removed. Official references: https://core.telegram.org/bots/api/methods/deletemessage.md and https://core.telegram.org/bots/api/methods/deletemessages.md.

Join/leave service events use Message fields `new_chat_members` and `left_chat_member`, not ordinary `text`. Distinguish Telegram capability, local gateway ingestion and preserved message IDs; absent transcript rows are not evidence that Telegram never sent an event. A screenshot identifies visible content, not native message IDs. For a targeted cleanup obtain exact chat/message provenance; never infer IDs from adjacency or delete a guessed range. Do not start competing `getUpdates` polling to recover already consumed events, promise that service messages can always be forwarded/replied to, or expand capture/automatic deletion without the requested scope.

## Recover missed service-message IDs before declaring a blocker

Use the verified temporary-reply method only for an explicitly requested narrow cleanup in the confirmed supergroup. Announce the temporary replies first: this recovery **writes briefly to the group**, even though its purpose is reading. Set `disable_notification=true`, `allow_paid_broadcast=false`, and `reply_parameters.allow_sending_without_reply=false`; a successful reply can return the original service Message in `reply_to_message`. Do not equate silent delivery with invisibility or promise a read-only operation.

Bound candidate inspection from verified per-chat evidence; candidate IDs are lookup targets, never authorization to delete a guessed range. Before deleting an original, match the returned literal chat/message IDs, requested user's numeric ID, join/leave action, date window and requested sequence. Persist send intent and returned evidence privately, delete every exact bot-owned diagnostic promptly, and stop on uncertain sends or cleanup. Preserve unrelated group content and do not turn a one-off request into automatic deletion or revive cancelled publishing tasks.

Confirm each original's absence with a reply attempt that forbids sending without the target: the specific `message to be replied not found` response establishes absence at that check, while permission/network errors do not. Clean up any unexpectedly successful diagnostic and report verification as incomplete. Preserve a surviving lookup anchor separately from the examined high-water mark, because previous diagnostics and deleted notifications cannot serve as reply anchors on the next cleanup.

Follow [bounded service-message recovery](references/service-message-recovery.md) for the ordered API recipe, repeated cleanups and alternative transports. Do not require user-provided links before trying this bounded verified path, and never start a competing `getUpdates` consumer.

## Pitfalls

- Check both authorization and response scope: `group_allowed_chats` authorizes a group, but a non-empty legacy `TELEGRAM_ALLOWED_CHATS` / YAML `allowed_chats` remains a hard response gate. Preserve its existing chat IDs and add the new chat there too, preferably migrating the legacy env value into `platforms.telegram.allowed_chats` so YAML is authoritative.
- Verify group membership against the exact bot identity: resolve the token's bot with `getMe`, then call `getChatMember` for that bot ID and chat ID. A screenshot or display name may refer to another bot or stale client state.
- Treat `getChatMember.status == "left"` together with `leaveChat: Bad Request: chat is deactivated` as an obsolete chat ID, commonly left behind by a group migration. Stop testing permissions against that ID; discover the live ID from a fresh incoming command/mention or forwarded-message metadata, then update every allowlist, channel prompt, monitor, and delivery target that used the old ID.
- When Telegram upgrades a basic group, the chat ID changes to a `-100…` supergroup ID. If `sendMessage` reports `group chat was upgraded to a supergroup chat`, read `parameters.migrate_to_chat_id` and add the new ID to every applicable `allowed_chats`, `group_allowed_chats`, and `free_response_chats` list before restarting; keep unrelated existing IDs.
- A Telegram username is not a stable authorization identifier.
- `getUpdates` is a queue of delivered events, not a reliable historical membership directory; an empty queue does not prove that a person is absent from a group. Do not start a second polling consumer to inspect an active gateway's traffic: it competes for updates and can itself cause Telegram conflicts. Prefer gateway intake logs and source message records.
- Do not expose `TELEGRAM_BOT_TOKEN` while diagnosing authorization.
