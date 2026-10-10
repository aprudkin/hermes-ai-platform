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
[Telegram guide](https://github.com/NousResearch/hermes-agent/blob/v2026.9.14/website/docs/user-guide/messaging/telegram.md)
and [v2026.9.14 release](https://github.com/NousResearch/hermes-agent/releases/tag/v2026.9.14).
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
[`v2026.9.14` source](https://github.com/NousResearch/hermes-agent/tree/v2026.9.14).
[`profile show`](https://github.com/NousResearch/hermes-agent/blob/v2026.9.14/hermes_cli/profile_cmd.py)
uses exit 1 with `does not exist` for a missing named profile, while
[`config get`](https://github.com/NousResearch/hermes-agent/blob/v2026.9.14/hermes_cli/config.py)
uses exit 1 with `Config key not set` for a missing key. The role tolerates
only those two documented absence results; every other non-zero query result
fails before create or set operations.

The desired profile matrix also sets `stt.language=ru` for the default profile
and every named profile. In pinned Hermes `v2026.9.14`, the global
[`stt.language`](https://github.com/NousResearch/hermes-agent/blob/v2026.9.14/website/docs/user-guide/configuration.md#speech-to-text-stt)
value is the language hint for every STT provider unless a provider-specific
language overrides it; an empty value restores provider auto-detection. This
setting does not select an STT provider and is separate from the UI language.

## Hermes backups

Run `task backup:hermes` (short alias `task b:hermes`; legacy alias
`task hermes:backup`) to create a verified **personal-state backup**. It keeps
configuration/authentication, memory/history, custom skills and jobs, and custom
application source/data from `/opt/hermes/data` and `/opt/hermes/app`. Recognized
caches and dependency environments are excluded; no Docker image is exported.
Small runtime metadata, a Compose definition and a manual recovery guide are
included. Restore requires a separately installed image and dependencies.

The task uses `HERMES_DEPLOY_HOST` when set; otherwise it resolves the host from
local Terraform state. Set `HERMES_DEPLOY_SSH_USER` and
`HERMES_DEPLOY_SSH_PRIVATE_KEY` for SSH. The controller requires Python 3; the
server requires Python 3, Docker access and GNU tar. Bundles default to
`~/backup/hermer/hermes-personal-<timestamp>-<pid>.tar.gz`; set
`HERMES_BACKUP_DIR` to choose another local destination.

One filtered state snapshot is staged privately on the server. The free-space
check covers retained state and metadata overhead, not an image or excluded
caches. Compression streams to the controller, which verifies the transfer
using temporary uncompressed payloads before publishing the final archive.
The container is paused only while the state snapshot is written locally,
then unpaused before compression and network transfer. Cleanup attempts to release its owned pause on failure. A failed
unpause is an error; check the actual container state before continuing. Do not
deploy or edit server state concurrently with a backup.

Before publishing the mode-0600 final archive, the task verifies the bundle
personal-state format, required contents and payload hashes. This is not proof of a
successful live restore. The bundle contains credentials and is not encrypted;
protect its storage and transfer. It does not copy the entire host, controller
SSH keys, Terraform state or external service settings, and does not configure
a schedule, retention, automatic restore or cloud storage. Legacy data-only
archives and full recovery bundles cannot masquerade as personal-state backups.

See [Hermes settings and personal-state backup](personal-backup.md) for exact
exclusions, resource requirements and manual recovery boundaries. That guide is
included as `RESTORE.md`. Unknown files and custom binaries are retained; the
backup is not a promise of a small, fixed archive size.

For explicit self-contained migration, `./scripts/hermes_backup.sh --full`
retains dependencies and the installed image in the existing
`hermes-recovery-*.tar.gz` format. See the
[full recovery guide](backup-restore.md). Existing archives are not rewritten or
deleted when the ordinary backup default changes.

## Hermes image updates

`task update:hermes` (legacy alias `task hermes:update`) explicitly requests a
verified **full** recovery bundle, including the current image and deployed
app/data state, then contacts GitHub for the latest stable
`nousresearch/hermes-agent` release.

The task requires `HERMES_DEPLOY_SSH_USER`, `HERMES_DEPLOY_SSH_PRIVATE_KEY`,
`HERMES_DEPLOY_SSH_PUBLIC_KEY`, `HERMES_DEPLOY_SSH_SOURCE_CIDR`,
`HERMES_MODEL_PROVIDER`, and `HERMES_MODEL`. It resolves an omitted
`HERMES_DEPLOY_HOST` from the local Terraform state's `server_ipv4` output;
set that variable to explicitly target a different existing host. Set exactly
one credential source: `HERMES_CODEX_AUTH` for `openai-codex`, otherwise
`HERMES_ENV`. Values remain outside the repository. The SSH client uses
batch-mode trust on first use: it records an unknown host key and rejects any
later key change.

If the current pin is already the latest stable release, the task exits after
the verified backup and neither pushes nor deploys. Otherwise it requires a
compatibility review JSON file named by `HERMES_UPGRADE_REVIEW_FILE` before it
can change the pin. Review the exact upstream release notes, current image-related
project contracts, and run `./installer/install.sh validate` first. The JSON
must use the JSON keys `tag`, `release_notes_url`, `compatibility`, `summary`,
`contracts` (path-to-SHA-256 map), and `checks` (command/result records). It must
record the exact release tag and official release-notes URL, a non-empty
compatibility summary, `compatibility: "compatible"`, SHA-256 hashes for exactly
`README.md`, `docs/operations.md`, and `docker/docker-compose.yml`, and a passed
`./installer/install.sh validate` check. Contract hashes bind the review to the
local content that was inspected; the gate rejects missing, stale, mismatched,
or incompatible evidence. Keep the review file outside the repository so it does
not make the clean-worktree check fail. The review remains an operator
attestation; the script cannot independently judge release compatibility.

After the review passes, the task requires a clean worktree, updates only
`docker/docker-compose.yml`, and requires `CONFIRM_PUSH=yes` immediately before
pushing the current branch and `CONFIRM_DEPLOY=yes` immediately before the
existing-host deployment. The installer's own `--confirm-external-mutation` gate
remains in force.

Automated restore, monitoring/alerting, DNS, TLS, public dashboard/API access,
and disaster recovery remain outside Minimal.
