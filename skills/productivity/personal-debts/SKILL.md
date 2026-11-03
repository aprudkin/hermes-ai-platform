---
name: personal-debts
description: "Use when recording who owes whom or debt repayments."
---

# Personal debts

## Canonical record

Use `$HERMES_HOME/personal-debts/ledger.json` for private personal debts, distinct from Bablomat business accounting and shared task reminders. Read the entire existing ledger before changing it. If absent, initialize parties, debts and append-only events. Preserve unrelated entries. Use private directory0700/file0600 and atomic replacement for updates.

## Recording

- Record debtor, creditor, explicit currency, integer minor-unit principal, repayments, outstanding balance, verbatim note, nullable due_date, status and source provenance. Use stable IDs. Resolve "я" from authenticated sender, never from a quoted author. Names without verified contacts remain unresolved identities, not guessed Telegram accounts.
- Preserve separate debts/tranches even if debtor and creditor match when the user gives distinct repayment notes. A note such as salary or a joke is not a calendar date or permission to create a reminder or arrange a transaction. Preserve it as a note.
- Append original source text, actor, origin chat and message ID when available; use null for an unavailable message ID, never fabricate one. Deduplicate by source ID when available; inspect previous entries before treating a repeated statement as new lending.
- On explicit repayment, append an event and reduce only the specified debt. Ask which tranche if allocation is genuinely ambiguous. Do not infer settlement from an unrelated transfer, phrase of intention or silence. Corrections preserve original events and append the correction, rather than erasing history.
- Separate operating debts from explicitly classified capital debt. Preserve capital balances and notes in the same canonical ledger with category=capital and include_in_operating_totals=false; ordinary debt lists/totals include only operating entries unless the user asks for capital or all obligations. Reclassification is not repayment, forgiveness or deletion: append an event and preserve principal/outstanding amounts.
- Calculate totals in tools using minor units; never net different currencies or opposite-direction debts silently. Show clear debtor→creditor direction and note partial balances.
- Keep detailed amounts in the task file, not global memory or reusable skill. Share only in the ledger's authorized conversation/with authorized participants; do not contact third-party debtors or publish debts without authorization.

## Delivery

Confirm recorded entries and any computed totals in Russian. Scheduling is separate and requires an actual verified reminder job; do not claim automatic reminders merely because a due note was stored.
