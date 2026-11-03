# Mail event discovery helpers (#50)

Reviewable generic source for the existing manager skill, not a new mail service.
Only synthetic fixtures belong in Git. **Never commit snapshots, accounts,
subjects, raw mail, section files, attachments, manifests or credentials.**
The live skill remains authoritative for event interpretation and owner scope.

## Installed entrypoint

The three sibling Python modules are installed byte-for-byte under the active
manager skill's `scripts/` directory:

`/opt/data/profiles/manager/skills/productivity/mail-event-discovery/scripts/`

Do not rewrite a collector in a new session. Invoke its `mail_events.py` with
`/opt/hermes/.venv/bin/python` (Python 3.10+; stdlib, plus existing `python-dotenv`
only when `--env-file` is used). Repository copies can be invoked identically.
No PDF/OCR/browser dependency, service, scheduler or calendar integration exists.

```bash
# Placeholder account and frozen example window; choose the authorized interval.
# The secret must ALREADY be in the protected environment or owner-only env file.
# Do not pass a password value, source an env file in a shell, or print its values.
/opt/hermes/.venv/bin/python \
  /opt/data/profiles/manager/skills/productivity/mail-event-discovery/scripts/mail_events.py \
  collect --host imap.yandex.ru --account person@example.invalid \
  --start '2026-10-20T12:00:00+00:00' --end '2026-11-03T12:00:00+00:00' \
  --password-env MAIL_EVENTS_IMAP_PASSWORD \
  --env-file /opt/data/profiles/manager/.env \
  --output /opt/data/profiles/manager/workspace/mail-events-NEW-UNIQUE-RUN
```

`--env-file` is optional. The existing process environment takes precedence.
Only regular owner-owned files with no group/other permissions are accepted;
symlinks are rejected and dotenv interpolation is disabled. No password-value
argument or interactive password prompt exists. TLS certificate and hostname
verification are required. Login/connection exceptions are reduced to their type,
not echoed (server error strings can contain private information).

Every collection needs a new or empty output directory. Nonempty directories
are rejected **before login in the CLI and before LIST in the collector API**;
failed attempts cannot replace an older successful snapshot. New snapshots are
private: directories `0700`, files `0600`, incremental manifests. Rerun with a
new path; there is no destructive resume or force option.

## Transport and provenance

- LIST all selectable folders (including Sent/Spam/Trash); read-only SELECT and
  UID SEARCH/FETCH only. Mail INTERNALDATE determines the exact half-open UTC
  interval; the sender Date remains a separate header. Broad SINCE candidates
  are filtered locally before body fetch. Flags before/after are recorded.
- Fetch BODYSTRUCTURE, then bounded `BODY.PEEK[HEADER]`, selected part `.MIME`
  headers and selected part payloads. Never use `BODY.PEEK[]`, `RFC822` or a
  multipart container section. PDF payloads are not requested, stored or decoded.
  Binary/image/archive/document parts are excluded by this fresh text-only scope.
- Select text/*, application/ics and application/icalendar, plus octet-stream
  receipts with explicit .html/.htm/.txt/.ics/.csv/.json/.xml names. Calendar
  source is preserved, not recurrence/timezone-expanded. PDF MIME type or PDF
  filename (including RFC 2231 names) always overrides text selection.
- Exact header/MIME/payload bytes are saved separately as `.section`, with
  per-section hashes and folder/UIDVALIDITY/UID provenance. They are **not** a
  complete original `.eml`. `selected_sections_sha256` is explicitly selected-only,
  never a full-MIME or unfetched-attachment hash.
- Fresh snapshots conservatively keep each source identity separate, even when
  selected text matches. Repeated Message-IDs are review flags, not proof of a
  conflict or whole-message equality. Historical full-MIME storage frames MIME
  headers/part hashes in canonical JSON; exact duplicates keep all source refs,
  differing content with the same Message-ID stays separate and flags both.
- Per-part encoded text limit: 2 MiB; header limit: 64 KiB. Partial range requests
  are capped at limit+1, and oversized declared text is not requested. Oversize,
  unsupported nested messages/structures, decode uncertainty and MIME defects
  are visible gaps/errors. Unsupported text (e.g. enriched) is retained verbatim
  as fallback in readable output, but still marks extraction partial.

## Completeness and agent review

CLI exits **0** only for `complete`, **1** for a recorded partial result, **2** for
preflight/login/fatal failure (argparse usage errors also return 2). Its JSON
summary includes `transport_complete`, `extraction_complete`, totals and gap
counts; inspect private `coverage.json` for exact errors/gaps/source identifiers.

Transport completeness means successful folder enumeration/selection/search and
all in-window selected-source fetches. Extraction completeness separately checks
body coverage and decoding/MIME gaps. Global `complete` requires both. Excluded
PDF/binary parts are scope exclusions, not outstanding PDF-verification work.
Neither flag claims that an agent has actually reviewed all readable messages,
resolved ICS recurrence, reconciled reschedules or produced the final event list.
`unique_messages` counts source records in fresh mode, **not deduplicated events**.
On successful transport, candidate refs equal excluded+collected refs; failed
refs and folder/global errors must be checked on partial runs. A failed SELECT
means the folder's candidate count is unknown, not zero proven messages.

## Historical offline full-MIME re-extraction

```bash
/opt/hermes/.venv/bin/python \
  /opt/data/profiles/manager/skills/productivity/mail-event-discovery/scripts/mail_events.py \
  reextract --input /private/OLD-CORPUS --output /private/NEW-REEXTRACTION
```

Input and output must be disjoint. The old corpus is read-only; existing metadata,
raw sources and stale artifacts are not rewritten or deleted. This mode needs a
historical full-MIME `raw_path` index; it does not reconstruct an .eml from a new
selected-section snapshot. New output may contain historical full raw copies
that already included PDF bytes; that is **not** a claim they were never downloaded.
PDF decoding/artifact creation is skipped. Existing historical key/hash/source
identities are preserved for audit rather than relabeled as newly collected mail.

## Offline checks

```bash
PYTHON=/opt/hermes/.venv/bin/python bash tests/mail_event_discovery_test.sh
```

CI installs `python3-dotenv` for the protected-env-file regression. No tests need
IMAP, a real account, a network connection, a PDF parser or private corpus. The
legacy synthetic extractor tests are retained; their transport fixture now speaks
selected sections and their re-extract fixture requires a fresh output directory.
Live mailbox acceptance is a separate authorized operator check; offline passes
are not evidence of a live login or event-review completeness.
