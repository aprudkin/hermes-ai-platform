# Hermes: one persistent agent

This repository maintains **one working Hermes Agent**, its private state and
its recovery path. The current `manager` identity is **Чеби (Chebi)**, not a
fresh task-manager template. Container recreation must preserve that identity,
memory, history, skills, applications and job settings.

The operating cycle is: **maintain → back up off-server → verify → rehearse
recovery → deliberately update or move**. Terraform and Ansible are supporting
bootstrap/deployment tools, not a roadmap to a larger infrastructure platform.
There is no requirement to add databases, Redis, monitoring or more agents.

## Start with the existing installation

- [State boundaries and identity ownership](docs/state-first.md): what belongs
  to the running agent, what belongs in Git, and PR #40's identity guarantees.
- [Operations](docs/operations.md): maintenance, controlled updates and Telegram
  acceptance controls. Inspection is not permission to restart or deploy.
- [Personal backup](docs/personal-backup.md): routine private state, excluding
  the runtime image and recognized dependency/cache trees.
- [Full recovery](docs/backup-restore.md): exact image plus state/dependencies,
  offline restoration, isolated checks, cutover and rollback boundaries.

The normal persistent mount is `/opt/hermes/data` on the host → `/opt/data` in
the container. `/opt/hermes/app` contains deployed Compose/gateway configuration.
Files created only in the container's writable layer are **not durable state**;
full backup refuses unsupported customizations rather than silently losing them.

## Main commands

Run from this checkout on the owner's computer or another explicitly selected
independent controller. See the backup guides for SSH access, authorization,
protected storage and space requirements **before** running a capture.

| Command | Result / boundary |
| --- | --- |
| `task backup:hermes` | Capture full state, retained dependencies and exact image to this computer; briefly pauses the live container; verifies the received archive |
| `task backup:hermes:full` | Explicit equivalent of the full default |
| `task backup:hermes:personal` | Lighter personal-state backup without the image or recognized dependencies/caches |
| `task verify:hermes` | Locally verify the trusted archive named by `HERMES_BACKUP_FILE`; no server access |
| `task restore:hermes:state` | Restore and compare files into a **new** `HERMES_RESTORE_DIR` on compatible Linux; requires `HERMES_BACKUP_FILE`; never starts Hermes |
| `task update:hermes` | Back up, review and validate a candidate image pin **only**; no commit/push/deployment |
| `./installer/install.sh validate` | Strict repository checks including behavioral tests; not a live recovery test |

`task --list` shows the commands. Existing aliases `b:hermes`, `hermes:backup`
and `hermes:update` remain. **The default backup Task now creates a full bundle**;
use `backup:hermes:personal` for the previous lightweight Task behavior. The direct
`./scripts/hermes_backup.sh` CLI still defaults to personal state for compatibility.

With the owner's existing global Go Task catalog, the usual command from any
directory is `task -g b:hermes` (or `t b:hermes` with the existing shell alias).
The global launcher delegates to this project Taskfile, like the other backups;
no extra global implementation, cloud destination or schedule is needed. **Update behavior intentionally changed:** automatic
commit/push/deploy was removed; legacy `CONFIRM_PUSH` / `CONFIRM_DEPLOY` flags
are rejected. A matching local image pin is not proof of a successful deployment
and returns a non-success result with explicit retry guidance.

`HERMES_DEPLOY_HOST` selects the SSH destination. Standalone backup defaults to
an operator-configured `hermes-minimal` SSH alias. `HERMES_BACKUP_DIR` chooses
where the controller saves archives (legacy default: `~/backup/hermer`). Choose
a private directory on the owner's encrypted disk or an approved encrypted
external volume; no disk encryption, cloud account or upload is provisioned.
A controller **on the same server** is not an independent backup.

The `.tar.gz` archives contain secrets and **are not encrypted by these tools**.
Mode `0600` is access control, not encryption. Keep credentials for the backup
storage and recovery instructions available independently of the old server.
See [independent storage](docs/personal-backup.md#independent-storage-and-recovery-kit).

## Recovery and migration acceptance

1. Create and verify a trusted independent copy; retain access to its storage.
2. Prepare a compatible clean target, restore files without starting the agent.
3. Inspect identity, memory/history, databases, dependencies and job definitions
   offline. Rehearse runtime only with external networking blocked and jobs
   disabled; a second host alone is not isolation.
4. Keep cancelled reports and mail monitoring disabled, even if an older archive
   contains them. Only explicitly approved jobs may resume.
5. Fence/stop the old installation before authorizing the new one to own Telegram
   keys and jobs. Never run both with production credentials.
6. Verify actual behavior after cutover; retain the stopped old installation and
   the backup until the owner accepts the result. No automatic destructive cleanup.

Report evidence separately:

| Claim | What establishes it |
| --- | --- |
| Archive created | Capture and transfer completed |
| Structure/integrity verified | Verifier checked schema, boundaries and hashes |
| Data restored | Extraction without diagnostics and file/basic-stat comparison completed; required ACL/xattr readback checked separately |
| Working restored installation verified | Isolated runtime checks, then separately authorized functional checks after cutover |

None implies the next. Repository fixture tests do not establish recovery of
the owner's actual installation. `--local` validation may skip unavailable
tools and is not strict readiness evidence. Historical deployment records are
not current health or Telegram verification.

## Supporting tools and historical scope

[INSTALLATION_GUIDE.md](INSTALLATION_GUIDE.md), [QUICKSTART.md](QUICKSTART.md),
[architecture](docs/architecture.md), [Ansible](ansible/README.md) and
[Terraform](terraform/README.md) remain useful for explicitly requested host
preparation or deployment. **Do not run the full installer over recovered state**:
it reconciles selected configuration/credentials rather than restoring verbatim.

The old Minimal/Optimal/Advanced/Maximum levels, `PROJECT_AUDIT.md`,
`CODEX_SETUP_PROMPT.md`, `CODEX_CLI_START.md` and stage prompts describe earlier
planning. They are not the current backlog and do not authorize implementation.
The DevOps/Coding/Research profile templates remain for compatibility, not as
required separate services. No useful bootstrap code has been removed.

## Upstream contracts

The official image pin is in `docker/docker-compose.yml`; review its exact
release notes before changing it. Do not infer availability from a historic tag.

- [Hermes releases](https://github.com/NousResearch/hermes-agent/releases)
- [Docker layout and health](https://hermes-agent.nousresearch.com/docs/user-guide/docker)
- [Profiles](https://hermes-agent.nousresearch.com/docs/reference/profile-commands)
- [Providers and Codex OAuth](https://hermes-agent.nousresearch.com/docs/integrations/providers)
- [Codex app-server runtime](https://hermes-agent.nousresearch.com/docs/user-guide/features/codex-app-server-runtime)
- [Telegram contract at the current pin](https://github.com/NousResearch/hermes-agent/blob/v2026.9.14/website/docs/user-guide/messaging/telegram.md)
- [Docker Engine on Ubuntu](https://docs.docker.com/engine/install/ubuntu/)
- [Hetzner provider](https://github.com/hetznercloud/terraform-provider-hcloud)
