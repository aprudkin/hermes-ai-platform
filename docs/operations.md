# Operations status

Implemented local and deployment-time checks:

- Terraform format and schema validation without apply;
- Ansible syntax/lint and post-deployment runtime verification;
- Compose schema validation as a required strict-gate check, or an explicit
  `SKIP` only in opportunistic `scripts/validate.sh --local` mode;
- container health through the loopback Hermes `/health` endpoint;
- profile existence through `hermes profile show`;
- bounded Docker log rotation and persistent `/opt/hermes/data` state.

Profile reconciliation follows the CLI contract in the pinned Hermes
`v2026.8.16` source. [`profile show`](https://github.com/NousResearch/hermes-agent/blob/v2026.8.16/hermes_cli/main.py#L10266-L10281)
uses exit 1 with `does not exist` for a missing named profile, while
[`config get`](https://github.com/NousResearch/hermes-agent/blob/v2026.8.16/hermes_cli/config.py#L5429-L5441)
uses exit 1 with `Config key not set` for a missing key. The role tolerates
only those two documented absence results; every other non-zero query result
fails before create or set operations.

The desired profile matrix also sets `stt.language=ru` for the default profile
and every named profile. In pinned Hermes `v2026.8.16`, the global
[`stt.language`](https://github.com/NousResearch/hermes-agent/blob/v2026.8.16/website/docs/user-guide/configuration.md#speech-to-text-stt)
value is the language hint for every STT provider unless a provider-specific
language overrides it; an empty value restores provider auto-detection. This
setting does not select an STT provider and is separate from the UI language.

Not implemented in Minimal: automated backup/restore, monitoring/alerting,
image upgrade automation, DNS, TLS, public dashboard/API access, or disaster
recovery. These remain later-level work and must not be inferred from this
repository.

For an authorized deployment, preserve the Terraform plan and validation
output under `.generated/` until review. After the first successful run, rerun
the same Ansible playbook and require zero semantic changes before calling the
host configuration idempotent. Back up `/opt/hermes/data` before any image pin
change; an upgrade procedure has not yet been implemented or tested.
