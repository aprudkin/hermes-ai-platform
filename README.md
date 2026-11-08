# Chebi: maintenance and recovery

One persistent Hermes Agent. This repository holds its approved instruction
snapshot, custom runtime source, container reference, backup tools, recovery
procedures and tests. Source publication is not deployment or job activation.
It does not provision a new server or recreate private state from templates.

## What is kept

- `profiles/manager/SOUL.md` — versioned instructions for Чеби / Chebi.
- `docker/docker-compose.yml` — the reviewed image pin and one-container layout;
  defaults to the active `manager` profile. It is not a replacement for the
  deployed configuration saved in a recovery bundle.
- `scripts/` and `systemd/` — capture, verify, offline restore, encrypted cloud
  transfer, the daily host backup and explicitly gated image updates.
- `docs/` — current operating and recovery instructions.
- `tests/` — checks for these tools, error paths and repository boundaries.
- [`tools/mail_event_discovery/`](tools/mail_event_discovery/README.md) — generic
  read-only text-only email helpers for the installed manager skill; no mail data.

- [`tools/` and `extensions/`](docs/runtime-reconciliation.md) — reviewed custom
  runtime source, both calendars, voice, accounting, reminders and safe helpers;
  source storage does not activate an integration.
- [`skills/`](skills/README.md) — vetted instruction-source snapshots, with
  private configuration replaced by placeholders.

Live identity customizations, memory, history, credentials, application data and
job settings remain in `/opt/hermes/data` on the host, mounted at `/opt/data`.
Private instance state does not belong in Git. Ordinary container replacement
must not erase it. Reviewed source/snapshots are versioned separately and are
not permission to overwrite live instructions, configuration or skills.

## Commands

Run capture from the owner's computer or another independent controller, not
inside the container it pauses. Configure the controller's `hermes-minimal`
SSH alias for an account with the required Docker/read permissions.
`HERMES_DEPLOY_HOST`, `HERMES_DEPLOY_SSH_USER` and
`HERMES_DEPLOY_SSH_PRIVATE_KEY` are optional explicit connection overrides.

- `task auth:hermes:codex` — repeat the browser device-code login for Chebi's
  OpenAI Codex credentials on `hermes-minimal`, profile `manager`; no PTY or restart.
  Open the displayed URL, enter the code and keep the terminal open until success.
  Adds a priority-0 credential without removing existing ones. The global launcher
  also exposes `task -g auth:hermes:codex` from any directory.
- `task backup:hermes` / `task b:hermes` — full state, dependencies and exact image;
  verify before publishing the local archive. Default: `~/backup/hermer/`.
- `task backup:hermes:personal` — lighter state-only archive; image and recognized
  dependency/cache trees excluded. The direct backup script defaults to this mode.
- `task backup:hermes:cloud` — explicitly upload an existing full archive through
  the dedicated crypt configuration and verify a recovery-config download.
- `task verify:hermes` — inspect the trusted `HERMES_BACKUP_FILE`; no host access.
- `task restore:hermes:state` — restore into a **new** `HERMES_RESTORE_DIR` on
  compatible Linux; never starts the agent or its jobs.
- `task update:hermes` / `task update:hermes:prepare` — full backup and reviewed
  local image-pin preparation; **no deployment**, commit or push.
- `task update:hermes:inspect` — read deployed update-review fingerprints over SSH.
- `task update:hermes:apply` — **replace the running container** with the exact
  reviewed image after a fresh full backup; requires explicit confirmation and
  a private deployment review. See [the update procedure](docs/operations.md#apply-a-reviewed-image).
  No automatic retry/rollback; functional acceptance is reported separately.
- `task validate` / `./scripts/validate.sh --all` — strict local checks and tests;
  no live host, cloud or Telegram operations.

The existing `hermes:backup`, `backup:hermes:full` and `hermes:update` aliases
remain. A global Go Task launcher may delegate to this Taskfile; this repository
does not install or modify that launcher.

## Read before acting

- [Runtime source reconciliation and exclusions](docs/runtime-reconciliation.md)
- [State boundaries](docs/state-first.md)
- [Runtime layout](docs/architecture.md)
- [Maintenance and image updates](docs/operations.md)
- [Personal-state backup](docs/personal-backup.md)
- [Full recovery and migration](docs/backup-restore.md)
- [Move to another hosting provider](docs/migration.md) — including recovery without the old server
- [Explicit encrypted cloud transfer](docs/cloud-backup.md)
- [Daily host backup and retention](docs/server-backup.md)

Local archives contain secrets and are **not encrypted**. The cloud workflow
encrypts remote objects; permissions alone are not encryption. Keep independent
recovery material outside the server's failure domain.

An archive being created, passing integrity checks, having its data restored,
and producing a working restored installation are four different results.
Use an already prepared compatible Linux/Docker target for recovery, rehearse
with external effects blocked, and transfer Telegram/job ownership deliberately.
Never start a second production copy or revive cancelled jobs from an old backup.

## Validation tools

Strict checks require Git, Bash, Python 3 with PyYAML, ripgrep, ShellCheck, Docker
Compose and Go Task. No Docker daemon is needed for Compose rendering. The
optional local rclone crypt integration test reports an explicit skip when
rclone is absent. `./scripts/validate.sh --local` allows missing static tools
and is not strict validation evidence. Runtime suites also require the isolated
packages pinned in `requirements-test.txt`, FFmpeg/ffprobe and DejaVu fonts.
Voice/image contract tests use a real Hermes checkout at
`345cd2b057a452236de401d3534b8502a7465e8d` via `HERMES_SRC`; this matches the
reviewed runtime image's source tag, not a request to upgrade/deploy Hermes.
CI prepares those test dependencies outside the project source and runs the
same strict gate. No real credentials or live profile are required.
