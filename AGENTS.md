# Chebi maintenance and reviewed runtime source

Maintain the existing manager profile's recovery toolbox and owner-approved
custom source. Read README.md, docs/state-first.md and
[reconciliation scope](docs/runtime-reconciliation.md) before changing behavior.

- Live identity, private configuration/state, credentials, conversations,
  accounting/medical records and real task registers are not Git source.
- Reviewed snapshots under skills/ and profiles/ are not an installer, a live
  overwrite policy or authority to resume a cancelled job.
- Yandex/Jira monitoring was expressly excluded. Social/blog automation remains
  stopped. Source publication is not migration, deployment, restart or cutover.
- Preserve working backup aliases, protected receipts, fail-closed uncertainty
  and the boundary between local integrity, upload metadata and a proven restore.
- Use the existing source structure and smallest complete change. Add a failing
  regression before changing behavior; keep tests isolated from real accounts,
  host/cloud/Telegram writes, live databases and production configuration.
- Keep custom extension/tool source dormant until separately installed. Require
  explicit private routing/configuration; do not invent recipient defaults.
- Run scripts/validate.sh --all with declared dependencies. Do not disable
  retained checks to obtain green CI; label explicit optional skips accurately.
- Inspect exact staged files for private data before committing, verify pushed
  refs and CI, and read back the final PR/merge state before reporting completion.
- Do not include source from another Hermes profile, generated environments,
  caches, nested Git metadata, personal one-off senders or private test receipts.
