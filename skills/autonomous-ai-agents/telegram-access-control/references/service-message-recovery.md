# Bounded recovery of Telegram join/leave notifications

## Preconditions

Use this recipe for a user-requested, narrowly scoped cleanup in a verified supergroup. It is not a history scraper or a passive read API: temporary replies are visible writes to the group. Notify the requester briefly before using them. Preserve the requested person's stable numeric identity and exact action sequence; an invitation does not prove membership and a screenshot does not supply native message IDs.

1. Call `getMe`, `getChat(chat_id)` and `getChatMember(chat_id, bot_id)`. Require the intended supergroup and `can_delete_messages=true`.
2. Inspect received messages and prior delivery receipts before writing. Keep two separate values: a recent **surviving anchor** whose original message still exists, and the **examined high-water mark** from exact earlier responses. Exclude previously examined ranges on a follow-up cleanup; do not restart at the oldest transcript message or treat an already deleted diagnostic as a surviving anchor.
3. Persist intent, then send one temporary reply to the surviving anchor. Explicit payload fields: `chat_id`, short diagnostic `text`, `disable_notification=true`, `allow_paid_broadcast=false`, and `reply_parameters={message_id: anchor_id, allow_sending_without_reply: false}`. Save the returned Message privately before proceeding. Its new message ID supplies a real upper bound for the current inspection.
4. Immediately remove that exact diagnostic using its returned chat, author and message ID. Do not continue if the send outcome or cleanup is uncertain; reconcile the existing attempt instead of creating another diagnostic blindly.

## Identify originals without guessing deletions

5. Inspect only the small range between the prior high-water mark and the observed upper bound. Choose a low explicit cap, such as twenty candidates, and stop if exceeded rather than widening into a history sweep. Reply to each candidate using the same strict payload. A candidate number is a lookup hypothesis, not a verified deletion target.
6. For every successful probe, validate `reply_to_message.chat.id` and `reply_to_message.message_id`, then inspect `new_chat_members` or `left_chat_member`. Match the requested numeric user ID, action and permissible date window. Persist the original and diagnostic response, then delete only that probe's verified bot-owned message. Skip specifically absent targets; stop or report other errors accurately.
7. Sort confirmed service messages by their real IDs and compare them with the user's requested latest actions. Delete only exact matches, not ordinary messages or other members' notifications. If too few matches were found, retain uncertainty instead of deleting substitutes.

## Delete and independently verify

8. Save the exact deletion intent and use `deleteMessage` or `deleteMessages` with the verified IDs. Remember that batch deletion skips missing messages, so a batch `True` is not per-target proof.
9. Attempt a strict reply to each exact deleted target. Only `message to be replied not found` confirms absence for that check. With `allow_sending_without_reply=false`, an absent target does not produce a standalone message. Permission failures, timeouts and unrelated errors are not absence evidence.
10. If a verification reply unexpectedly succeeds, persist and remove its exact diagnostic, and report the original as not independently confirmed absent. Do not guess another original or claim the whole cleanup succeeded.
11. Preserve the high-water mark and a still-existing anchor for future requested cleanups. Report only the verified requested deletions and diagnostic cleanup; do not promise that temporary replies were invisible or never generated a banner.

## Alternative transports

MTProto `channels.getMessages` supports bot sessions and can retrieve bounded explicit IDs in a supergroup, but requires legitimate application credentials and the bot login. `messages.getHistory` and `channels.getAdminLog` are user-only methods. Do not borrow another application's credentials, impersonate a human, or expand account access merely to avoid a missing gateway event. Prefer the already verified bounded Bot API method when its temporary-write scope is appropriate.

## Contract references

- https://core.telegram.org/bots/api/methods/sendmessage.md
- https://core.telegram.org/bots/api/types/replyparameters.md
- https://core.telegram.org/bots/api/types/message.md
- https://core.telegram.org/bots/api/methods/deletemessage.md
- https://core.telegram.org/bots/api/methods/deletemessages.md
- https://core.telegram.org/method/channels.getMessages
