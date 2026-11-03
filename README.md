# Chebi: maintenance and recovery

One persistent Hermes Agent. This repository holds its approved instruction
snapshot, container reference, backup tools, recovery procedures and tests.
It does not provision a new server or recreate private state from templates.

## What is kept

- `profiles/manager/SOUL.md` — versioned instructions for Чеби / Chebi.
- `docker/docker-compose.yml` — the reviewed image pin and one-container layout;
  defaults to the active `manager` profile. It is not a replacement for the
  deployed configuration saved in a recovery bundle.
- `scripts/` and `systemd/` — capture, verify, offline restore, encrypted cloud
  transfer, the daily host backup and controlled image-update preparation.
- `docs/` — current operating and recovery instructions.
- `tests/` — checks for these tools, error paths and repository boundaries.
- [`tools/mail_event_discovery/`](tools/mail_event_discovery/README.md) — generic
  read-only text-only email helpers for the installed manager skill; no mail data.

Live identity, memory, history, skills, credentials, application data and job
settings remain in `/opt/hermes/data` on the host, mounted at `/opt/data`.
They do not belong in Git. Ordinary container replacement must not erase them.
A repository snapshot is not permission to overwrite the live instructions.

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
- `task update:hermes` — full backup and reviewed local image-pin preparation;
  no commit, push or deployment.
- `task validate` / `./scripts/validate.sh --all` — strict local checks and tests;
  no live host, cloud or Telegram operations.

The existing `hermes:backup`, `backup:hermes:full` and `hermes:update` aliases
remain. A global Go Task launcher may delegate to this Taskfile; this repository
does not install or modify that launcher.

## Read before acting

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
and is not strict validation evidence. CI runs the strict gate.
