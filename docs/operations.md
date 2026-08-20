# Operations status

Implemented local and deployment-time checks:

- Terraform format and schema validation without apply;
- Ansible syntax/lint and post-deployment runtime verification;
- Compose schema validation as a required strict-gate check, or an explicit
  `SKIP` only in opportunistic `scripts/validate.sh --local` mode;
- container health through the loopback Hermes `/health` endpoint;
- profile existence through `hermes profile show`;
- bounded Docker log rotation and persistent `/opt/hermes/data` state.

## Telegram gateway operations

The implemented Telegram path manages one upstream long-polling process for
one explicitly selected profile. The first intended production selection is
`manager`; this is an instance choice, not the global default. Telegram privacy
mode remains enabled, the bot requires only the minimum group-administrator
permissions, and configured group messages dispatch only for a command, reply,
or direct mention. No webhook or inbound port is added.

Telegram configuration comes from a separate external mode-`0400`/`0600`
six-key file. Enabling stores the original gateway profile once in
`/opt/hermes/app/gateway-profile.pre-telegram`, records the managed profile,
updates only that profile's marked Telegram block, and recreates only the
Hermes service. Disabling removes only that block, restores the retained
profile, recreates only the service, and preserves profiles, sessions, memory,
provider credentials, Codex auth, API credentials, and rollback evidence.

The contract is pinned to the upstream
[Telegram guide](https://github.com/NousResearch/hermes-agent/blob/v2026.8.16/website/docs/user-guide/messaging/telegram.md)
and [v2026.8.16 release](https://github.com/NousResearch/hermes-agent/releases/tag/v2026.8.16).
Syntax, Compose configuration, container health, and bounded connected-log
status are deployment evidence only and do not prove user-visible Telegram
behavior.

### Separately authorized production controls

1. Record a successful Bot API identity check without sensitive fields.
2. Prove webhook state is empty and exactly one long-polling owner exists.
3. Prove the container and selected `manager` profile are healthy.
4. Obtain a substantive DM response for every configured user.
5. Obtain a substantive mention or reply response for every configured user in
   a configured group.
6. Deny an unconfigured user in a configured group.
7. Deny a configured user in an unconfigured group.
8. Prove an ordinary unmentioned group message causes no response and never
   enters agent context.
9. Re-run loopback API health and model inference controls.
10. Independently read back profile selection, protected file modes, gateway
    status, and retained rollback state without values.

Host connection, protected credential installation, service recreate/restart,
Bot API probes, visible messages, group-administrator changes, and GitHub
mutation remain separate approval boundaries. Passing local validation or CI
does not authorize any of them.

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
