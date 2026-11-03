# Payment receipt collection and reconciliation

Use this workflow for screenshot batches, dictated payment lists and revisions of a saved payment report. Keep this work separate from cash-register accrual ingestion and payout closure.

## 1. Resolve the report before adding amounts

Read the replied-to list, the current report pointer and the user's latest instruction. Identify whether the input is an addition, a complete resend, a correction, a reordering or a separate comparison list. A new arithmetic list and newly supplied older receipts do not automatically amend the last report merely because they arrived next. Preserve uncertain scope in a separate incoming manifest and ask one concrete question before combining totals.

For a date-only report revision, preserve every record's amount and position, add only verified absolute receipt dates, and verify the full count and total remain unchanged. Distinguish sent/processing dates from delivery dates. A date in an email's Transaction details > Date is payment evidence; a date in a photo overlay, note header or messenger caption is not automatically a payment date. Check uncertain child extracts against the exact original field before accepting them.

### Merge cash reports into one continuous report

1. Resolve both exact source reports, the recipient, their revisions and the inclusive range from replies and saved snapshots. Do not pick sources by conversational recency or merge different recipient aliases without confirmation. Retrieve available sources before asking for another copy.
2. Compare the daily entries in the latest quoted version with previously confirmed data. List only the changed or blank dates that need clarification. Approval of the format, a start date or a generic «да» does not supply missing numeric values. Once the owner gives the values, persist them and proceed without reconfirming the whole request.
3. Build one ordered date-to-amount map with source provenance. Preserve explicit zero days and days off; leave genuinely missing days unresolved rather than filling them with zero. Count matching overlapping source records once; ask about conflicting overlaps instead of adding both. Keep a payment annotation separate from that day's cash amount, even when its amount is larger.
4. Recalculate the entire combined revenue from the resolved daily map. Recalculate agency and operator percentages on their authorized bases, then apply each identified transfer offset or deduction once at its confirmed scope. Old report totals and computed salaries become superseded when daily inputs change; never retain them merely because they were once approved. Do not carry a phone/debt deduction from an unrelated multi-person summary into a single-person merge.
5. Verify date coverage, per-source subtotals, the combined total and transfer provenance with code. Save the original versions, owner resolutions and new combined snapshot without changing cash-ledger records or recording a payout.
6. Render one continuous daily column and one combined totals block using Elena's established format. Include date/weekday, day-specific transfer annotations, gross revenue, agency amount, transfer deduction, agency remainder and «Зарплата оператора». Split into separate weekly totals only when requested; deliver to the requested chat, not automatically to the bookkeeping group.

Retain the user-specified period boundary separately from receipt dates. Record a date only when supplied or visible; a heading's start date is not every payment's transaction date. Keep model labels separate from bank-account recipients. Preserve an unmatched short caption with its message rather than applying it to every attachment.

## 2. Save an ordered intake manifest

For each source message record its chat/message reference, attachment ordinal, image path and inspection state. When a queued or interrupted message has a null `platform_message_id`, inspect its persisted content and available origin fields within the verified chat instead of treating a failed ID-only lookup as missing history. Keep Telegram message IDs distinct from SQLite row IDs; use the actual persisted source row for an append-only calculation audit, and never invent a row ID from the transport ID. For each inspected receipt preserve:

- Displayed amount in integer minor units.
- Accounting amount and its basis; leave unresolved values unknown rather than silently substituting zero.
- Explicit principal, fee and debit total, when itemized.
- Method, displayed recipient, visible date, status and transaction identifier with their source.
- Original user caption separately from image-derived fields.
- SHA-256, duplicate candidate, verified match and any linked owner resolution.
- Separate readiness flags for amount, identity, direction, status and report membership. A readable amount is not proof that the receipt is an eligible, distinct completed payment; record every unresolved reason rather than checking only for a missing numeric value.

Inspect each original once, persist that batch, then continue. For an uncertain date, permit one targeted crop/readback; then save an unknown instead of repeatedly reopening the same image. For delegated extraction, bound each assignment, require a partial manifest promptly, and steer or stop a child that repeats reads without saving results. Inspect several images, persist that batch, then continue. An interruption can leave the tail of the previous message uninspected even when newer images are visible. Reconcile all received paths against inspected/pending paths before declaring coverage complete. Do not treat a partly viewed composite or a previously interrupted tool batch as evidence that every receipt was read.

## 3. Interpret amounts and status

| Receipt evidence | Treatment |
| --- | --- |
| Explicit principal, fee and debit total | One payment. Keep the three fields separate and use principal for a transfer list unless total debits were requested. |
| Notification amount differs from main receipt | Preserve both and request a linked clarification if no explicit breakdown resolves it. Do not infer a fee from the numerical gap. |
| Minus sign on a sent payment | Use positive magnitude when summing outgoing payment amounts; do not reinterpret it as a refund. |
| `Paid`, `Complete` or `Payment sent` | Preserve the displayed confirmation; screenshot evidence is not an independently checked bank statement. |
| `Sending` or expected delivery message | Preserve pending status. Include only within a clearly labeled screenshot-amount sum, not a completed-payment claim. |
| `Pay` button with entered amount | Preparation screen, not proof of payment. Hold unresolved for an actual-payment report. |
| `Deposit` activity row | Preserve the label and amount. Determine direction/linkage before treating it as another outgoing transfer. |
| Advertising, bonus, balance or unrelated notification | Do not add it as a client payment. |
| Caption repeats the attached amount | Corroborating description, not another payment. |
| Owner confirms a combined total with component amounts | Count that total once at the confirmed scope. Do not add its components or older activity rows visible within the same chat screenshot again. Record whether it is an aggregate rather than claiming it proves one bank transaction. |

Do not carry an owner's correction of one receipt onto another receipt merely because the same principal/debit pair appears there.

## 4. Reconcile duplicates without deleting evidence

1. Compare byte hashes for exact resends and retain all source paths.
2. For re-encoded, resized or letterboxed copies, compare the underlying receipt/photo and visible identifiers. A low-resolution similarity score can nominate a match but cannot prove transaction identity.
3. Use a side-by-side composite when photos need comparison. If text is too small, inspect the originals or crops rather than trusting downscaled detail.
4. Match receipt identifiers first; retain distinct equal-valued transactions when their identity differs.
5. If similar photographs lack identifiers, ask whether they are one transaction or separate transactions. Preserve the linked answer. The image attached to that clarification is not an additional payment.
6. Mark uncertain matches as candidates. Do not tell the user a suspected repeat has been permanently excluded before verification. If comparison reveals different receipt identifiers or funding accounts, clear the candidate/exclusion and preserve the reason; the earlier tentative classification must not remove a valid payment.

For additions, compare against the latest corrected report and against other receipts in the current batch. Do not exclude a new payment solely because its amount already appears in the report.

## 5. Compute from records, not from prose

Use code to count and sum the included records in saved order. Reconcile received images into verified repeats, included new evidence and unresolved evidence. Separate image count from payment count: multiple images can document one transaction, while a text-only entry may have no image. Assign a stable evidence-to-entry link instead of assuming one image equals one payment. Keep screenshot coverage, distinct-payment identity and report eligibility as independent checks. Do not describe an aggregate row as one bank transaction unless its evidence establishes that.

For an additions report verify:

- New count equals previous count plus included additions.
- New total equals previous total plus included addition amounts.
- No unresolved receipt is hidden inside a definitive final total.
- The declared user count is checked independently of arithmetic.

If a dictated expression contains fewer values than its declared payment count, report the actual count and whether the stated sum matches. Never invent a balancing entry.

## 6. Apply edits as report revisions

Resolve a numbered edit against the current ordered snapshot before changing data. Retain the previous revision, the original evidence and the exact edit's scope.

- Amount correction: replace only that record's accounting amount, recalculate every included amount and count, then verify the old-to-new difference.
- Reordering: move the record and renumber; keep all other relative ordering, count and total unchanged.
- New additions: append after the existing records unless explicitly instructed otherwise.

Write the new audit manifest and rendered report, then update the current pointer. Do not leave the pointer referencing an older total after publishing a revision. Do not copy a stale cached subtotal or turn a report edit into a change to the live cash ledger.

### Date-only enrichment of an existing report

1. Freeze the replied-to report's ordered evidence IDs, accounting amounts, owner resolutions, count and total. Use the current saved snapshot, not an earlier uncorrected receipt amount; adding dates must not restore fees or undo an approved correction.
2. Inspect each linked receipt for an absolute date. Treat previously extracted date fields as lookup hints, not verified evidence. Preserve the exact visible date text, normalized date when justified, event type and image reference; record any inferred year separately.
3. Prefer an explicitly labeled sent/payment date for the transfer. Preserve a distinct delivery/completion date separately and label it if displayed instead. Treat an email date as confirmation metadata unless the text identifies the transaction date. Do not silently convert a payment-note date, Telegram caption or forwarding date into the bank transaction date.
4. Leave the absolute date unknown when only a phone clock, `Today` or `Yesterday` is visible; the screenshot's capture date must be established independently before resolving a relative label. Keep ambiguous numeric date formats unresolved rather than choosing a locale from the user's language. Compute weekdays from the full resolved date, never from a guessed year.
5. Join the extraction back by stable entry/evidence ID, not amount or date, because several payments can share either value. Verify every original entry is covered once, source image paths match, the ordered amount list is unchanged, and recalculated count and total equal the frozen baseline.
6. Render the entire same numbered report, adding a date only where supported. Leave other lines unchanged, retain the count and total at the bottom, and use at most one short note explaining that dates were added only where visible. Save a new annotated revision and update its pointer without modifying the original receipts or cash ledger.

## 7. Return the requested layout

Use the standing SKILL.md currency and output preferences. Return the actual complete revised report when requested, not merely an assurance that it was changed. For bulk intake, acknowledge briefly and wait for the completion signal rather than repeatedly publishing partial totals. Keep unresolved questions focused on the exact receipt and its contradictory fields; do not ask the user to resend an entire batch that is already persisted. After intake closes, finish the evidence audit and collect independent clarification questions into one concise request. Identify each receipt by its contradictory amounts or distinctive description, present alternatives neutrally, and preserve each answer against its exact evidence record. Keep the draft and unresolved items saved; do not advance the verified-report pointer or label a known-amount subtotal as the complete payment total while eligibility remains unresolved.
