---
name: operator-only-accruals
description: "Use when parsing operator-only cash accrual messages."
metadata:
  hermes:
    related_skills: [telegram-group-monitoring]
---

# Operator-only accruals in БАБЛОМАТ

Apply alongside `telegram-group-monitoring` when working with the user's bookkeeping chat.

## Confirmed meaning

The owner defines this compact format:

```text
Модель 💎🧡AlinaMelori🧡💎

Опер Анна

03.10.2026 + 40 💸💸💸
```

- The stated date is the accounting date.
- $40 is accrued only to operator Анна.
- Model and agency accruals in this record are $0.
- Normalize the decorated model name to AlinaMelori.
- Record this as an accrual, not an actual payout or a command to close the unpaid period.
- In БАБЛОМАТ, Alexy authorizes confirmations from @USA_808 (numeric user ID PARTICIPANT_USER_ID), such as «Тут да все верно 🙌» or «Да все верно … к выдаче», to mark the specifically confirmed operator/model period as paid and closed. Subsequent source messages for those recipients start a new period; preserve old accruals and confirmation provenance. Do not close unrelated recipients or add the confirmation to revenue.
- Resolve the exact report being confirmed from a verified reply/message reference or an explicit recipient. Chronological proximity alone is insufficient when several reports are awaiting approval. If no reference survives observation, leave payouts pending and ask in shared Hermes (`telegram:SHARED_CHAT_ID`) with a real mention of Elena (`PARTICIPANT_USER_ID`) for the specific report/recipient; do not invent the mapping or send the question to the source bookkeeping group by default. Follow the shared clarification and six-hour personal-escalation policy in `telegram-group-monitoring`; policy documentation is not proof that the automatic sender/timer has been deployed.
- This confirmation rule is user policy, not proof that the deterministic monitor supports it. Verify implementation before describing confirmation-based closing as automatic.
- Keep the compact accrual separate from a full cash report for the same model/day; do not overwrite that day's revenue or model/agency shares.
- Do not enter an example quoted in the control chat as a real transaction; identify the actual source message in the bookkeeping chat.

## Reply expectations

When the owner asks to reply to the source message with the operator balance “и всё”, send only the balance as a reply to that verified message, without model/agency breakdowns or explanatory text. Compute the balance with tools and existing payout checkpoints; never run a payout command merely to inspect it. In this chat, Anna and Анна refer to the same operator for balance calculation.

## Verification boundary

Saving this rule does not mean the monitor implements it. Inspect the current parser and prove support with a failing regression test followed by a passing implementation before claiming automatic handling. Only post to a verified chat/message target with the owner's authorization.
