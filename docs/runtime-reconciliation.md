# Runtime source reconciliation

This repository versions reviewed custom source, instruction snapshots and
reconstruction guidance. Publication/merge does **not** install those files,
overwrite the live profile, change cron, register accounts or resume a cancelled
operation. Private recovery state remains authoritative.

## Included source

- [Backup policy](server-backup.md): visible dated cloud directories, suffixes,
  Moscow calendar-date retention, metadata-only remote checks and preservation
  of the last successful local archive.
- [System status](../tools/system_status/README.md): quiet, content-free status
  notifier, durable intent/receipt handling and explicit private routing config.
- [Deepgram voice](../extensions/deepgram-voice/README.md): actual installed
  upstream package/license/provenance plus the local tempo wrapper and offline
  request/audio tests.
- [Event calendars](../tools/event_calendar/README.md): notebook monthly/day
  rendering and below-image caption generation from explicit inputs; no live
  mail/traffic/Telegram access.
- [Cycle tracker](../tools/cycle_tracker/README.md): engine, notebook renderer,
  replies/outbox/buttons, vetted skill and synthetic tests. No medical state.
- [Accounting](../tools/accounting/README.md): Bablomat parser, formatting,
  corrections, source replies, clarification handling and daily digest.
- [Meter reminders](../tools/meter_reminders/README.md): explicit configuration,
  monthly windows, acknowledgments, durable no-blind-retry delivery.
- [Addressing extension](../extensions/elena-addressing/README.md): scoped
  addressing behavior, separate from any private conversation or contact list.
- [Browser bridges](../tools/browser_bridge/README.md): explicit file queue and
  separate browser launcher; no Mac session, cookies or SSH keys.
- [AgentMail setup](../tools/agent_mail/README.md): inert import and explicit
  one-time signup gate; no personal introduction sender or account state.
- [Image provider](../extensions/image-generation/openai-codex-25/README.md):
  custom model catalog/provider source; no OAuth material or live generation.
- [Task register template](../tools/shared_tasks/README.md): schema/reference
  only, never a replacement for the actual private register or scheduled jobs.
- [Vetted skills](../skills/README.md) and
  [approved identity snapshot](../profiles/manager/SOUL.md).
- Existing [mail event extraction](../tools/mail_event_discovery/README.md),
  already merged separately, remains the same collection implementation.

## Deliberately excluded

- Yandex/Jira mail monitoring, digests and briefs: explicitly removed from this
  reconciliation by the owner. No corresponding implementation/skill is added.
- Live medical dates/history, financial ledgers/reports, debts, task/register
  contents, IMAP messages/attachments, identities/keys/authentication material,
  conversation/session databases, browser profiles, contacts and receipts.
- Personal one-off announcements/checks/restart probes, generated private PNGs
  or audio, caches, environments and nested Git repositories.
- Cancelled social/blog publication automation is not restored or enabled.
  Retain its cancellation through any future reconstruction.

The retired migration feature branch and its local pending changes must not be
mistaken for current operating requirements. Repository source publication is
not a migration, target setup, rehearsal, cutover or authorisation to start one.

## Evidence and limits

`./scripts/validate.sh --all` remains the strict local gate; it never needs a
live host, production database, cloud account or Telegram sender. CI runs that
gate with declared test dependencies and a pinned real Hermes source checkout
for provider contracts. Fixture transports/identities/dates are synthetic.

Tests and local source reconstruction do not prove live delivery, paid API
acceptance, a current Mac connection, cron adoption, a restored account or a
complete restored runtime. They do not enable the event-calendar previews in
existing reminder jobs. Existing running code/configuration is not replaced.

The accounting quote and confirmation fixes are described and regression-tested
in [the accounting package](../tools/accounting/README.md). Source publication does
not activate the optional native-input collector or replay historical approvals.
Preserve delivery uncertainty and require separate live activation evidence.

For actual recovery use [state-first boundaries](state-first.md) and the
[private recovery bundle](backup-restore.md), then reconcile cancellation and
single-owner polling/sending before any separately approved activation.
