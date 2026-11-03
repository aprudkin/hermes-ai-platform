# Recurring Ledger Monitors

## When to use

Use this pattern when a Telegram group continuously posts amounts and stated totals, and the bot must verify arithmetic, retain daily statistics, and produce detailed reports for a date range. Keep ingestion deterministic and reserve an agent turn for an explicitly addressed report request.

## Human-entry format design

Design the source message for the person entering it, not around implementation-specific regular expressions. Start with one ordinary daily-cash example and a few rules; explain special cases only after the main pattern.

```text
Касса <постоянное имя модели>
Дата: <ДД.ММ.ГГГГ>
Валюта: USD

1. 450 — Cash
2. 450 — Venmo

Итого: 900
Модели: 540
Агентству: 360
Оператор <имя>: 40
```

- Keep one client per numbered line; the number is an index, not money. Require its amount and payment method. Time, duration and transfer recipient are optional annotations, never inferred amounts.
- Express a split in the same client line: `1. 450 — Zelle 100 + Cash 350`. The client amount is counted once; components must reconcile with it. A recipient name in parentheses identifies the payment account, not its economic share.
- Use `0` only for a confirmed zero and `неизвестно` for an unresolved amount. Preserve this distinction in validation and statistics.
- Keep stable model/operator names. Do not silently merge unconfirmed aliases merely to simplify the template.
- Put allocations below the total boundary. Operator accrual is separate from client revenue; its funding/deduction rule must come from explicit business instructions, not the visual order of fields.
- Prefer complete corrected reports replying to their source over detached changes such as `ещё +100`; retain version linkage and do not turn a correction into another day's revenue.

An operator-only message needs no fabricated customer transaction:

```text
Начисление оператору
Модель: <имя>
Дата: <ДД.ММ.ГГГГ>
Оператор <имя>: <сумма>
Модели: 0
Агентству: 0
```

A financial summary should contain an explicit period with both months and years, a visible sum expression, the claimed total, the percentage result and the amount after a percentage deduction. Keep financial-summary validation distinct from revalidating all historical source cash reports; missing pre-connection history does not prevent checking the expressions.

**Adoption gate:** explanation-only requests stop at the proposal. If implementation is later authorized, add source-linked tests for all exact sample shapes before changing the parser: daily report, optional time/duration, split payment, explicit zero, unknown value, labelled date, operator-only accrual, financial summary and corrected repost. Verify normalized names, date assignment, coverage of every monetary field, no double-counting and source-specific reply delivery. Do not announce that a standard is live from a saved description or channel prompt alone.

## Source and cursor

Query `state.db` by joining `messages` to `sessions` and filter:

- `sessions.chat_id = <target>`
- `messages.role = 'user'`
- `messages.active = 1`
- `messages.id > last_seen`

Do not require `observed=1`: unmentioned chatter is observed, but messages that mention or reply to the bot can contain accounting data and normally have `observed=0`. Process rows in ascending ID order and make the source row ID unique in the ledger. Persist `last_seen` with an atomic replace after the batch so retries remain idempotent.

## Durable ledger

Use a separate SQLite database rather than editing Hermes `state.db`. A minimal reusable schema has:

- `messages`: source row ID, platform message ID, accounting date, timestamp, sender ID/name, raw content, claimed total, computed total, difference, and check status.
- `entries`: source row ID, line number, label, and integer minor-unit amount; unique on `(source_row_id, line_no)`.
- Workflow-specific dimensions such as register/person name and operator payouts belong in dedicated columns/tables keyed by source row ID; keep them separate from revenue entries so post-total metadata cannot inflate totals.

Store money as integer minor units, never binary floats. Preserve labels and raw source text so a detailed report can explain every amount. Maintain an optional JSON read model with per-day total, entry count, and total-check counts; regenerate it from SQLite rather than treating it as the source of truth.

Keep the full ISO accounting date in storage and compute presentation separately; hiding the year must not discard it or make weekday calculation depend on today's year. Prefer the source report's explicit date. For this user's undated reports, use the approved California business-day fallback described in SKILL.md; do not substitute the server's UTC receipt date or silently redate existing entries.

## Parsing boundary

Accept only positive accounting evidence:

- amount-only lines;
- labeled cash/card/bank/expense/revenue lines;
- explicit currency values;
- `total`, `итого`, `итог`, `тотал`, or `всего` lines, case-insensitively.

Strip attributed sender headers before parsing. Exclude times, dates, phone-like identifiers, questions without a stated amount, and unrelated prose containing a number. Preserve ambiguous lines as raw messages but do not create ledger entries from them. When a self-contained report reaches its first recognized total boundary, compute revenue only from lines above it; parse model, agency and operator shares below it separately. Attach the model and agency shares to the normalized heading, not the sender. Leave missing shares unknown rather than inferring percentages. Backfill new share fields from persisted raw reports without resetting the monitor cursor or replaying notices.

## Total verification

Use these boundaries in order:

1. If a message contains both entries and a stated total, compare the total with only those entries.
2. If a message contains only a stated total, compare it with entries after the previous total in the same accounting day.
3. If no unambiguous entries exist, mark the check `unverified`; never manufacture a zero-data reconciliation.

For each stated total, build one source-specific result: verified total with running unpaid shares, mismatch with computed/claimed/difference, or unverified. Use the presentation rules in SKILL.md: bold accounting date, weekday dates without years, recipient emoji and whole-dollar amounts without `.00`. An agency line is the running unpaid share for that register, not merely the current report's fee. Reply to the source report through the reply sender; do not merge notices for different sources into one standalone cron post. Produce no notice for chatter.

## Period reports and requester identity

Generate reports from the ledger with explicit inclusive `from` and `to` dates. Include:

- each day's total;
- detailed labels/amounts in source order when requested;
- grand total for the period;
- counts of correct, mismatched, and unverified totals.

Resolve a named requester to a numeric Telegram user ID from attributed transcript rows, then verify the current username with `getChatMember`. Put the numeric IDs and the exact report command/interface in the channel prompt. The username is a human-friendly alias, not the authorization key.

## Read-only model report audits

- For an unspecified-period model report, state the available-history date range and separately show the current calculation after the latest period-start/payout cutoff. Historical accrual totals are not current unpaid balances, and a new-period marker is not proof of an actual cash transfer.
- Use SQLite `mode=ro` rather than initializing the mutable Ledger merely to inspect data. Select the latest source row per exact normalized register/accounting date before joining model shares, operator rows and revenue entries. Reconcile every included Total against entry sums and explicit model-plus-agency shares; do not add operator accruals or financial-monitoring summaries to revenue.
- Compare saved active source cash reports with ledger source IDs before claiming history coverage. Operator-only summaries under decorated or longer model names can repeat the operators already listed in cash reports; do not add them again or infer an alias solely from matching amounts.
- Audit explicit post-total operator lines against the operator table. Mixed-script/prefix variants such as `Оperator Anna: 30` may exist in the source but have no normalized operator row even when the cash Total is marked `ok`. Clearly identify a source-supported report adjustment, preserve its exact source link, and distinguish it from a persisted ledger repair. Do not silently omit the amount, infer it from percentages, or mutate historical financial data just to generate a report.
- Keep missing accounting days distinct from explicit zero-revenue reports. Compute weekdays from stored full dates, use integer minor units/Decimal, and retain detailed evidence in a profile-local report artifact. Return a readable inline summary rather than forcing an attachment when the report fits in chat.

## Dictation-to-report workflow

1. **Capture before calculating.** Save the verbatim dictation and a structured date-to-Total map in the active profile's report workspace. Keep source provenance for owner input distinct from observed group messages. A spoken date without an amount remains null; do not shift the next day's amount backward or manufacture a zero. Keep allocation instructions alongside the data, not in a global parser default.
2. **Resolve the calculation scope.** Separate an allocation for newly dictated Totals from a requested recalculation of the whole historical report. Preserve explicit historical shares unless their recalculation is authorized; flag differences if a requested uniform percentage differs from recorded shares. A rate cannot generally be inferred from Total alone because extras, fixed operator amounts and minimum payments can produce different distributions.
3. **Reconcile overlap before finalizing.** Read the current ledger and saved active source messages read-only; a new cash report may have arrived during dictation. Select the latest cash report per exact normalized register and full accounting date, then compare it with the dictated date map. Classify each day as group-only, dictation-only, matching overlap or conflicting overlap. Matching repeated dates corroborate one amount rather than adding revenue; dictation-only zeroes are known zeroes, not gaps. Save conflicts as unresolved records containing both amounts, source links and the eventual explicit decision; do not overwrite either provenance or pass an unapproved value into a published calculation. Report the first available group date, count matching overlaps programmatically, and ask only about conflicting dates. Keep accepting other dictated batches while resolution is pending. Do not supplement missing daily figures by guessing a date mapping from an aggregate financial summary or an unconfirmed model alias.
4. **Calculate from one structured dataset.** Tag every input as Total, explicit agency cash, explicit model cash or an allocation instruction; never overwrite Total with an agency-only dictation. Store full ISO dates and integer minor units. For explicit agency amounts, subtract from the previously approved Total and assert `model + agency = Total`; flag an agency amount exceeding Total rather than silently clamping it. Missing Total leaves the model amount unknown. For a fully allocated percentage split, use Decimal, assert the percentages sum to the full Total and reconcile both daily and aggregate shares with a documented cent-rounding policy. Omit an excluded operator entirely. Preserve the prior calculation as a versioned snapshot when input semantics change; replace only the affected date/scope and require fresh approval of the resulting draft.
5. **Prove date coverage and revision consistency.** Enumerate every inclusive requested date and assert `resolved days + missing days + unresolved conflict days = calendar days`, with mutually exclusive categories. Emit one dated line per day and total resolved values only; label omitted conflicts separately from absent data. Verify that identical repeated input leaves totals unchanged and that a confirmed replacement changes only its date, never adds a second day. Distinguish lifetime/report accruals from payout balances: do not subtract new-period markers or payments unless the request is specifically for the remaining balance. Retain raw input, source comparison, explicit decisions, calculated JSON and human-readable report as separate artifacts. On a new input batch, invalidate downstream calculations and locale variants without erasing the previously sent snapshot or its delivery manifest; rebuild all requested variants from the same resolved revision before sending.
6. **Localize the verified snapshot.** Translate wording and weekday labels to the requested dialect; for Brazilian Portuguese use Brazilian wording and number separators with an unambiguous USD marker, not BRL. Assert that parsed amounts, dates, known/missing-day counts and shares match the original JSON. Preserve explicit missing-day markers and the distinction between accruals and actual payouts. For customer-forwardable copies, keep explanatory limitations in a separate reply rather than restoring internal commentary the owner asked to remove. Do not recompute from a later ledger snapshot while claiming to send merely a translation.

## Report delivery and verification

Before rebuilding an interrupted report, inspect the current snapshot pointer, saved source adjustments, language artifacts and delivery manifests. A ledger-only search is insufficient for manually supplied historical days. Resolve a conflicting spoken date range once, preserve that decision with the snapshot, and confirm that all language files use the same approved allocation semantics. If the verified files already exist and delivery is authorized, send them before doing unrelated cleanup; repeated progress messages do not substitute for delivery.

1. Resolve each named recipient through saved DM/session identity and conversation evidence. Use verified numeric chat IDs, not an opaque display name alone. Build the per-recipient body from the same report artifact; keep any required personal salutation outside the financial data.
2. Send the report text through the active profile using `hermes -p <profile> send --to telegram:<verified_chat_id> --file <report_path> --json`. Use `--subject` for a recipient-specific introduction if needed. Pass arguments with a subprocess list instead of embedding a long report or Python program inside shell quoting. The `--file` option sends text; it is not a document attachment.
3. Retain the successful send result immediately, including platform, exact chat ID and returned message ID. Read back the destination's saved assistant-message mirror and compare the complete expected text, accounting for the separately constructed salutation. A CLI mirror can lack `platform_message_id`; do not treat a failed lookup by that column alone as failed delivery or resend. Pair the returned remote message ID with the exact destination/content mirror and record both pieces of evidence.
4. Store a delivery manifest keyed by report version, locale and recipient, with artifact path, returned message ID and verified mirror row. Distinguish a successful platform send from a person having read the message. If an outcome is uncertain, reconcile receipts before any retry; an older-language delivery does not prove the current translation was sent.
5. If the owner stops or changes language before sending, cancel the unsent version and update the delivery plan before proceeding. Resume external sending only within current authorization. If the latest request only creates a replacement-language report, return it here; send to another person when that sending request is present or explicitly renewed.
6. After sending to the originating DM through the CLI, use a short final delivery confirmation rather than posting the entire report again. If asked whether Elena received it, answer for the exact current version and language, not for any earlier report.

## Payout checkpoints

For commands such as `Payout <operator>` / `Выдача <оператор>`, persist a per-operator checkpoint keyed by the command's source row ID. Aggregate operator amounts by accounting date only from report rows after the previous checkpoint and before the command, then store the exact daily items and total used for that payout. Make the command idempotent by returning the already stored result when the same source row is retried. A correction/repost for the same register and accounting date supersedes the earlier report; use the latest source row so reposts do not double-count. Unknown operator names must not advance the checkpoint.

Include the inclusive accounting-date period, daily amounts, and grand total in the payout response. The next payout starts after the prior command source row, so previously issued amounts cannot reappear.

For model payouts, save the model and linked agency payout amounts/items in one transaction with the same command source row and payout timestamp. Use the model checkpoint for both balances; operator checkpoints remain independent. A standalone agency command must not advance a separate period. Return the stored result for a repeated command without another accrual or payment. Viewing balances must never call a payout method on the live ledger.

Compute each notice as of its source row, excluding future reports and payout commands. Sum the operator's unpaid entries across registers, but the model and agency balances only for the report's register. Use latest reports per register/accounting day to prevent correction/repost double-counting. Confirm explicit recipient aliases before merging names across languages; if their identity is unclear, leave the merge pending and ask in shared Hermes with Elena mentioned rather than silently splitting or combining balances.

## Source-to-reply audits

1. Resolve the requested chat and compute the window using the live clock and an explicit timezone. Do not widen a bookkeeping request to unrelated DMs without saying so.
2. Read incoming source rows from `state.db` and outgoing records from delivery receipts, logs and timestamped tool results. Join on the exact chat and platform message ID; a numeric message ID alone is not unique across Telegram chats. If older receipts encode the chat in a digest rather than a column, validate that digest before attributing a receipt to a destination.
3. Filter replies by verified delivery time, not merely the source message timestamp: a later correction can reply to an older source. If receipts lack delivery timestamps and logs cannot supply them, explicitly limit the report to the verifiable records instead of claiming completeness. When evolving the receipt schema, retain destination, source ID, returned bot ID and delivery timestamp together.
4. Distinguish original posts, later formatting revisions and separate correction replies. Preserve earlier text as audit evidence, mark the superseded version, and treat a correction replying to a bot warning as a separate source-answer pair.
5. Export the collected pairs to JSON or Markdown, deduplicate by destination and sent message ID, and count in code. Include links and complete original/answer texts; provide a file when the inline version would be cumbersome. Never replace the source with a reconstructed accounting template or silently normalize its wording, dates or amounts.

## Shared clarification routing and timeout verification

1. Resolve the separately authorized discussion group and Elena's numeric identity, then verify both intended participants' current membership. Do not substitute the source bookkeeping chat for the shared review group.
2. Build one concrete question per ambiguous source, retaining the source URL, accounting date/register and disputed text. Use a real `tg://user?id=...` mention rendered as a Telegram entity, not a plain name. Verify returned chat, text, message ID and mention target; enable notifications without promising the recipient will read them.
3. Persist the question's delivery receipt and due time before relying on a timeout. Anchor the six-hour interval to successful group delivery, not source receipt or a process-local sleep. Preserve dedupe and uncertainty states across restarts; routing changes do not authorize replaying previously delivered private questions.
4. Match answers to the particular question through a verified native reply, unique case reference or exact unambiguous quoted text from an authorized respondent. Unrelated conversation or a bare acknowledgment elsewhere must not cancel the reminder. Track a relevant response separately from financial resolution: a response alone does not authorize a payout or ledger correction.
5. At the due time, send at most one personal reminder to Elena for an unanswered case, with the original question and group/source links. Persist `sending` before network delivery, verify the exact destination and rendered response, then read back the durable receipt. Keep uncertain outcomes blocked from automatic retries; never remind about an already answered/resolved case.
6. Before declaring the policy operational, exercise the actual scheduled entrypoint and test the boundary before/at the deadline, relevant versus unrelated replies, restart dedupe, wrong mention entities and uncertain sends with isolated fixtures. Verify a real group mention independently of the synthetic timeout tests. Keep policy saved, code tested, delivery verified and scheduler active as separate outcomes; a policy edit alone enables none of them. Do not claim an unattended reminder while the responsible poller is paused.

## Confirmation closure gates

Keep linkage evidence, implemented processing, persisted closure and delivered acknowledgment separate. Reading a screenshot or saving an approval policy does not perform a closure. Before reporting one as complete, verify the recipient/report reference, ensure the applicable close operation actually exists, persist the boundary atomically, read back the affected balances/checkpoint, and verify the reply acknowledgment against the confirmation's own message ID. A missing implementation or uncertain target remains pending rather than becoming a plausible-looking completion notice.

## Cron migration

When a first-match alert becomes ongoing bookkeeping, update the existing cron job rather than creating a second scanner:

- preserve the approved polling interval;
- `no_agent: true`;
- script: recurring reply ledger watcher;
- delivery and failure delivery: `local`, because the script sends each notice directly as a reply;
- durable receipts: record each source message ID, text and returned bot message ID; block blind retries of uncertain sends.

Remove or replace the old `alerted` state; leaving the one-shot watcher active can produce a stale “first message” notification after the recurring system is already authoritative.

## Verification matrix

Automate and run tests for:

- labeled amounts plus a correct total;
- labeled amounts plus an incorrect total;
- amount-only lines;
- a total-only message after entries;
- a second total that resets the pending-entry boundary;
- time/date chatter that must not become an amount;
- duplicate execution of the same source row;
- daily aggregation across at least two dates;
- detailed inclusive period reporting;
- a live no-data run that advances the cursor without posting;
- independent operator and linked model/agency payout checkpoints, including a retried command;
- notice balances as of the source row, excluding later reports;
- backfilled shares without repeated revenue or notices;
- weekday formatting in headers, payout dates and report periods, retaining ISO dates internally;
- separate reply anchors for a batch and persistent delivery deduplication.

Before changing a shared date formatter, search related ledger, reply-delivery and business-date tests for old expectations; update only presentation assertions, not source fixtures, money literals or stored ISO dates. Keep formatting-only edits separate from accounting changes. Preserve historical source and calculation evidence; publish the correction as a new reply and apply only the user's authorized strikethrough to the old bot notice, without changing its words or amounts.

After scheduling, verify a completed cron run reports `last_status=ok`. End-to-end completion still requires one harmless chatter message and one representative total in the actual group.