# Portable Bablomat accounting

This tool prepares a **new offline Hermes profile**, not a running bot. It never
calls Telegram, runs imported scripts, merges into an existing profile, installs
packages, copies cron, or activates plugins. Source publication is not deployment.
Use a trusted, consistent **offline snapshot**, not `/opt/data` on a running agent.
The existing full recovery bundle remains the independent rollback copy.

## What travels

- All rows of `cash-ledger/ledger.db`, `reply-deliveries.db`, and `review-cases.db`:
  open and closed periods, dated entries, payout items, corrections, unresolved
  cases and sent/uncertain receipts. No payout is inferred from report wording.
- `native-inputs.db`, restricted to the selected accounting source messages.
- Current top-level `cash-ledger/*.json` and `*.txt` policy/audit files; old `.bak`
  databases and cancelled activity-alert databases are not active state.
- Only referenced participant messages from `state.db`, including linked review
  responses, plus explicitly selected source rows. Other conversations, session
  prompts, tool calls, model settings, gateway routing and queued jobs are absent.
  The database is rebuilt from schema; unrelated text is not left in free pages
  or search indexes. Imported source sessions are ended and archived.
- The snapshot's accounting scripts and native-input plugin, not the older Git
  parser snapshot. Code is copied as data and never imported/executed by migration.
  The cleaned `skills/bablomat-accounting/SKILL.md` replaces mixed monitoring skills.
- Telegram response/access modes and all configured group IDs in
  `telegram-settings.json`; selected Telegram/Bablomat environment values,
  **including the bot token**, in `telegram-secrets.json`. Native plugin settings
  are saved in `accounting-settings.json`. These are review inputs, not active
  configuration/credentials. A minimal `config.yaml` explicitly disables Telegram
  and the accounting plugin: a missing plugin allow-list can cause Hermes config
  migration to enable installed plugins. Old channel prompts are intentionally
  excluded: they can conflict with the cleaned skill or contain unrelated instructions.
- Explicitly reviewed report snapshots, receipt images and other accounting
  artifacts. Not the entire `workspace/`, `image_cache/`, or `reports/` by default.
  The helper, this guide and hashes/row inventories travel with the bundle.

**The output contains financial/personal data and credentials. It is not
encrypted.** Store snapshot, temporary space and output on protected encrypted
storage outside Git. Directories are 0700, files 0600. These permissions do not
replace encryption. Hashes establish integrity, not trusted provenance.

## Export from an offline snapshot

Requirements: Python 3.11+, SQLite 3.37+ with the source schema's FTS5 tokenizers,
PyYAML and python-dotenv. The declared test environment pins the two Python
packages in the repository's `requirements-test.txt`; ordinary Hermes already
uses them. Unknown schemas/tokenizers fail rather than discarding data.

1. Use the existing [backup/recovery procedure](../../docs/backup-restore.md) to
   obtain a consistent independent snapshot. Capture/pausing the live instance
   is a separate operational action. Work on a disposable offline copy and keep
   the original archive. SQLite reads may create coordination sidecars; valid
   saved WAL commits are included through SQLite's backup API.
2. Check the profile's accounting inventory. Besides `cash-ledger/`, inspect
   report workspaces and their referenced receipts. Some manually prepared
   calculations live only in `reports/` or a selected `workspace/` directory.
   Include each report's referenced attachments, not a global image cache.
   Read the actual records privately: a saved report is not proof of a payout.
3. Write a private selection JSON **outside Git**, using actual reviewed values:

   ```json
   {
     "chat_id": "<verified bookkeeping group ID>",
     "artifacts": ["reports/<reviewed-report-directory>"],
     "source_rows": []
   }
   ```

   `artifacts` accepts exact files/subdirectories under `reports/`, `workspace/`,
   `assets/`, `image_cache/` or `cash-ledger/`. Inspect their contents before
   inclusion; the tool cannot decide which manual reports belong to accounting.
   Never select the whole mixed workspace. Symlinks and special files are refused.
   `source_rows` contains exact internal message IDs for separately verified
   accounting decisions not already linked from the accounting databases/policy.
   It is not a chat-wide history export. Missing referenced rows block export;
   reconcile their evidence rather than silently declaring history complete.
4. Set `SNAPSHOT_HOME`, `SELECTION_FILE` and `BUNDLE_DIR` to absolute private
   paths. The destination must not exist and must be outside the snapshot:

   ```bash
   umask 077
   python3 tools/accounting/scripts/bablomat_portable.py export \
     --home "$SNAPSHOT_HOME" --selection "$SELECTION_FILE" \
     --destination "$BUNDLE_DIR" --offline-snapshot
   python3 tools/accounting/scripts/bablomat_portable.py verify "$BUNDLE_DIR"
   ```

   In an already imported profile the helper is `scripts/bablomat_portable.py`.
   `--offline-snapshot` acknowledges the snapshot boundary; it is not a live
   database lock. The helper checks selected files for changes during export,
   but this is not a substitute for coordinated capture across databases.

The snapshot must have no active unprocessed participant messages in the source
chat after the monitor cursor. Otherwise export stops: it cannot safely classify
or discard those messages. For final cutover, arrange a quiet, caught-up capture
under separate authorization. This tool neither runs the monitor nor advances
the source cursor. Writes after capture still require a final snapshot.

## Import and ID continuity

Transfer the complete bundle over an authenticated encrypted connection. From a
trusted checkout, choose a **new, nonexistent** profile directory:

```bash
python3 tools/accounting/scripts/bablomat_portable.py import "$BUNDLE_DIR" \
  --destination "$NEW_PROFILE_HOME"
```

Import copies into private staging, verifies the bytes actually copied, checks
SQLite integrity/foreign keys and compares every database table's row inventory.
Only then is the prepared directory published. It refuses an existing destination
and leaves no completed profile on failure. It writes `IMPORT-RECEIPT.json` with
`activated: false`. Never interpret that receipt as successful bot operation.

The old internal accounting source IDs remain intact. Filtered `state.db` reserves
its message sequence through the **global** snapshot high-water mark, including
omitted conversations. The new monitor cursor is advanced to that same mark only
after proving the source chat was caught up. New Hermes messages therefore get
IDs beyond all old references. Old reports/confirmations are not replayed.
This is deliberately a fresh-profile import, not a merge into another history.

Original financial evidence and report files are byte-preserved (databases are
logical copies); stored absolute paths inside historical artifacts are not blindly
rewritten. Resolve them against the bundled relative file inventory when reading
old reports. Include required external receipts explicitly. A successful export
proves preservation of the selected scope, not discovery of all manual artifacts.

## Before separately authorized activation

- Install a compatible ordinary Hermes version; first match the source runtime,
  do not combine migration with an unreviewed framework upgrade. The contract test
  uses source `345cd2b057a452236de401d3534b8502a7465e8d`. Custom native capture needs
  `ctx.register_telegram_handler`. Runtime binaries/environments are not bundled.
- Set `HERMES_HOME` to the imported profile. Install the accounting dependencies
  in that runtime, and reconcile any remaining old absolute paths in executable
  code. Historical evidence paths are a different matter and must retain provenance.
- Apply the saved Telegram access/response settings and credentials deliberately
  through the target's supported configuration mechanism. Keep every configured
  group ID in its original scope; do not grant free-response or control access to
  extra chats. Same bot identity preserves Telegram membership, not host settings.
  Check any shared/root-level environment overrides separately: this export reads
  the selected profile's `.env`, not other profiles or the process environment.
- Configure only the native accounting plugin and use the cleaned skill for the
  source chat. Resolve the review-group/user routing explicitly. Older live scripts
  may have private route defaults; examine these before activation, not by running
  a sender as a probe. Do not copy old channel prompts over the new instructions.
- Reconcile source and imported inventories, per-register/day totals, recipient
  balances, payout checkpoints, corrections and unresolved cases. Empty closure
  tables remain empty; migration does not turn historical prose into payments.
- Rehearse on disposable data without network/production credentials. Check a new
  source, retry, a payout boundary and uncertain delivery. Then fence the old bot
  and all restart/scheduler paths before starting the new one. Only one owner may
  poll/send. Keep the original server/backup recoverable until live acceptance.
- If ordinary automated checks are wanted, activate only the reviewed accounting
  polling job separately. No daily digest, social/blog, mail monitor, activity
  alert, clarification escalation or old cron is recreated by import.

## Verification evidence and limits

Run `HERMES_SRC=/path/to/pinned/hermes PYTHON=python3 sh tests/accounting_test.sh`.
The isolated suite checks exact accounting row preservation, private-data exclusion
(including FTS/page bytes), five configured group IDs, archived sessions, WAL data,
missing evidence, corruption, path traversal/symlinks, changing snapshots and refusal
to overwrite. A real ledger test preserves model/agency payout checkpoints and
processes a new report exactly once after import. A real pinned Hermes schema is
filtered, reopened through `SessionDB`, and accepts a new message above the old
high-water mark. Network and non-temporary databases remain blocked in tests.

The two pre-existing expected failures in the Git accounting source remain visible;
this migration tool does not repair those business rules or certify the newer live
code. Full private-state capture, live export/import, Telegram delivery and target
cutover are not performed by developing or publishing this tool.
