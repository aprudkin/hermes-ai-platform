# Maintain the existing Hermes installation

Start with the current host, not a new infrastructure plan. After authorized
read-only access, check the selected profile, container/image, loopback health,
disk space and age/location of the last verified independent backup. Do not
print credentials, conversation logs or Docker environment values into shared
output. Health does not prove inference, Telegram behavior or recoverability.
Routine inspection does not require full Ansible reconciliation or a restart.

Keep personal changes in the host-backed data volume; preserve Чеби's live
identity and cancelled-job decisions. Before changes that may affect state,
capture and verify an independent backup. For recovery or a server move follow
[the recovery procedure](backup-restore.md), not the original platform roadmap.

Available local and deployment-time checks:

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
`task hermes:backup`) to create and verify a **full recovery bundle** on the
controller computer. It retains state, dependencies and the exact current
Docker image. The existing global catalog exposes the same task from any
directory as `task -g backup:hermes` / `task -g b:hermes` (or `t b:hermes`).
The global launcher remains a thin project-task delegation, like other backups.

The default destination is `~/backup/hermer/hermes-recovery-<timestamp>-<pid>.tar.gz`.
`HERMES_BACKUP_DIR` selects another local destination. Capture uses the configured
`hermes-minimal` SSH alias unless overridden; see the [full recovery guide](backup-restore.md)
for connection inputs, permissions, space and consistency requirements. Run from
the owner's computer or another independent controller, not the source container.

This intentionally changes the ordinary Task default from personal to full.
`task backup:hermes:full` remains equivalent. For the previous lightweight behavior,
use `task backup:hermes:personal` / `task b:hermes:personal` in this project.
The direct `./scripts/hermes_backup.sh` CLI without flags still uses personal
mode; `--full` selects full mode. See [personal backup](personal-backup.md) for
its exclusions and separately required image/dependency reconstruction.

Both modes temporarily pause the source for the snapshot, resume it before
compression/transfer, and verify the received archive before publishing its
mode-0600 final name. A failed unpause is an error, not success. Do not deploy or
edit state concurrently. These commands do not restore, deploy, upload to a cloud,
configure a schedule or delete existing backups. Verification is not proof of a
working restored installation. Archives contain credentials and remain
**unencrypted**; protect storage and transport. Whole-host files, controller keys,
Terraform state and external accounts remain outside the bundle boundary.

## Hermes image updates

`task update:hermes` (legacy alias `task hermes:update`) explicitly requests a
verified **full** recovery bundle, including the current image and deployed
app/data state, then contacts GitHub for the latest stable
`nousresearch/hermes-agent` release.

**This command now prepares a local change only.** It never commits, pushes or
deploys, even if preparation succeeds. The old `CONFIRM_PUSH` and
`CONFIRM_DEPLOY` variables are rejected before remote access; unset them rather
than reusing an old unattended invocation. Existing task aliases are retained.

Preparation requires a clean checkout, `HERMES_DEPLOY_SSH_USER` and
`HERMES_DEPLOY_SSH_PRIVATE_KEY` for backup, and preferably explicit
`HERMES_DEPLOY_HOST`. The omitted host retains the legacy Terraform `server_ipv4`
lookup. No provider credentials are needed just to prepare a pin. SSH uses
`accept-new` trust on first use; confirm the intended host fingerprint separately.

If the local pin already matches the release, preparation returns nonzero after
the verified backup: **live deployment is unknown**. This intentionally replaces
the old successful no-op, which could conceal a previous deployment failure.
Otherwise it requires a compatibility review JSON file named by
`HERMES_UPGRADE_REVIEW_FILE` before changing the pin. Review the exact upstream release notes, current image-related
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

After review, preparation updates only `docker/docker-compose.yml` and runs the
strict `./installer/install.sh validate` gate against the **candidate** pin.
If it fails, the command fails and leaves the diff for inspection. It does not
reset Git, weaken the gate or proceed to publication. Correct/review that diff
and rerun the strict gate; do not mistake rerunning preparation for deployment.

### Publish, deploy, verify — separate decisions

1. Inspect the candidate diff and validation output. Update release-specific
   contracts where needed; repeat validation after those edits. Publish only
   reviewed changes on an appropriate branch/PR under the repository's Git rules.
   Neither the commit nor a merge records successful runtime deployment.
2. Immediately before a separately authorized update, retain a recent verified
   **full** off-server bundle and agree on rollback/maintenance time. A backup
   captured during preparation can become stale before deployment.
3. Use the existing-host deployment interface in [INSTALLATION_GUIDE.md](../INSTALLATION_GUIDE.md)
   with the explicit host, SSH public/private keys, source CIDR, selected
   provider/model and exactly one credential source. Preserve the installer's
   `--confirm-external-mutation` gate. Check the current runtime configuration
   before reconciling; leave `hermes_replace_profile_identities` false. This is
   a real deployment, not a local test or a recovery command.
4. On failure, record the nonzero result, inspect actual image/service state and
   partial changes before another action. Retry the **explicit deployment**
   against the reviewed pin only after reauthorization; do not rerun the pin
   preparation command as a deployment retry. The installer does not gate
   deployment on whether Git's pin changed, so a same-pin deployment is possible.
5. Check actual image/profile, health, identity preservation, memory/history,
   applications and the separately authorized model/Telegram controls above.
   Report local validation, published pin, deployed runtime and behavior separately.

A failed upgrade may already have changed runtime state. Do not blindly start
an older image over migrated databases. Use the retained full bundle on a clean
isolated target and the [recovery/cutover procedure](backup-restore.md) if rollback
requires old state. Preserve newer state before deciding to discard it.

No automatic restore/start, cloud storage, monitoring, DNS, TLS or public API
is introduced by this maintenance workflow.
