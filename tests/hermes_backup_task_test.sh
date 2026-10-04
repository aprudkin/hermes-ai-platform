#!/usr/bin/env bash

set -euo pipefail
# shellcheck source=tests/test_helper.sh
source "$(dirname "${BASH_SOURCE[0]}")/test_helper.sh"

fixture_root="$(mktemp -d)"
trap 'rm -rf "$fixture_root"' EXIT
fake_bin="$fixture_root/bin"
remote_root="$fixture_root/remote"
remote_bin="$fixture_root/remote-bin"
remote_state="$fixture_root/remote-state"
remote_command_log="$fixture_root/remote-commands.log"
backup_dir="$fixture_root/backups"
private_key="$fixture_root/luk"
command_log="$fixture_root/commands.log"
remote_script="$fixture_root/remote-script.sh"

file_mode() {
  stat -c '%a' "$1" 2>/dev/null || stat -f '%Lp' "$1"
}

mkdir -p "$fake_bin" "$remote_bin" "$remote_root/data/profiles/manager"
printf 'private fixture key\n' >"$private_key"
printf 'running\n' >"$remote_state"
printf 'session fixture\n' >"$remote_root/data/profiles/manager/session.json"

cat >"$fake_bin/ssh" <<'FAKE'
#!/usr/bin/env bash
set -euo pipefail
printf 'ssh %s\n' "$*" >>"$FAKE_COMMAND_LOG"
cat >"$FAKE_REMOTE_SCRIPT"
grep -q 'docker inspect --format' "$FAKE_REMOTE_SCRIPT"
grep -q 'docker pause hermes' "$FAKE_REMOTE_SCRIPT"
grep -q 'docker unpause hermes' "$FAKE_REMOTE_SCRIPT"
grep -q 'tar --numeric-owner --xattrs --acls -C /opt/hermes -czf - data' "$FAKE_REMOTE_SCRIPT"
[[ "${FAKE_SSH_MODE:-success}" == success ]] || exit 23
set +e
PATH="$FAKE_REMOTE_BIN:$PATH" \
  FAKE_REMOTE_STATE="$FAKE_REMOTE_STATE" \
  FAKE_REMOTE_COMMAND_LOG="$FAKE_REMOTE_COMMAND_LOG" \
  FAKE_REMOTE_PAUSE_STATUS="${FAKE_REMOTE_PAUSE_STATUS:-0}" \
  FAKE_REMOTE_UNPAUSE_STATUS="${FAKE_REMOTE_UNPAUSE_STATUS:-0}" \
  FAKE_REMOTE_TAR_MODE="${FAKE_REMOTE_TAR_MODE:-success}" \
  bash "$FAKE_REMOTE_SCRIPT" >/dev/null
remote_status=$?
set -e
[[ "$remote_status" -eq 0 ]] || exit "$remote_status"
python3 - "$FAKE_REMOTE_ROOT" <<'PYTHON'
import sys
import tarfile

with tarfile.open(fileobj=sys.stdout.buffer, mode="w:gz") as archive:
    archive.add(f"{sys.argv[1]}/data", arcname="data")
PYTHON
FAKE

cat >"$remote_bin/docker" <<'FAKE'
#!/usr/bin/env bash
set -euo pipefail
printf 'docker %s\n' "$*" >>"$FAKE_REMOTE_COMMAND_LOG"
case "${1:-}" in
  inspect)
    case "${3:-}" in
      '{{.State.Running}}') printf 'true\n' ;;
      '{{.State.Paused}}') [[ "$(<"$FAKE_REMOTE_STATE")" == paused ]] && printf 'true\n' || printf 'false\n' ;;
      *) exit 2 ;;
    esac
    ;;
  pause)
    printf 'paused\n' >"$FAKE_REMOTE_STATE"
    exit "$FAKE_REMOTE_PAUSE_STATUS"
    ;;
  unpause)
    printf 'running\n' >"$FAKE_REMOTE_STATE"
    exit "$FAKE_REMOTE_UNPAUSE_STATUS"
    ;;
  *) exit 2 ;;
esac
FAKE

cat >"$remote_bin/tar" <<'FAKE'
#!/usr/bin/env bash
set -euo pipefail
printf 'tar\n' >>"$FAKE_REMOTE_COMMAND_LOG"
[[ "$FAKE_REMOTE_TAR_MODE" == success ]]
FAKE

cat >"$fake_bin/terraform" <<'FAKE'
#!/usr/bin/env bash
set -euo pipefail
printf 'terraform %s\n' "$*" >>"$FAKE_COMMAND_LOG"
[[ "$*" == *"output -raw server_ipv4"* ]] \
  || { printf 'unexpected terraform command: %s\n' "$*" >&2; exit 1; }
printf '%s\n' 203.0.113.44
FAKE

chmod +x "$fake_bin/ssh" "$fake_bin/terraform" "$remote_bin/docker" "$remote_bin/tar"

run_backup() {
  PATH="$fake_bin:$PATH" \
    FAKE_COMMAND_LOG="$command_log" \
    FAKE_REMOTE_ROOT="$remote_root" \
    FAKE_REMOTE_SCRIPT="$remote_script" \
    FAKE_REMOTE_BIN="$remote_bin" \
    FAKE_REMOTE_STATE="$remote_state" \
    FAKE_REMOTE_COMMAND_LOG="$remote_command_log" \
    FAKE_REMOTE_PAUSE_STATUS="${FAKE_REMOTE_PAUSE_STATUS:-0}" \
    FAKE_REMOTE_UNPAUSE_STATUS="${FAKE_REMOTE_UNPAUSE_STATUS:-0}" \
    FAKE_REMOTE_TAR_MODE="${FAKE_REMOTE_TAR_MODE:-success}" \
    FAKE_SSH_MODE="${FAKE_SSH_MODE:-success}" \
    HERMES_BACKUP_DIR="$backup_dir" \
    HERMES_DEPLOY_HOST="${HERMES_DEPLOY_HOST-203.0.113.44}" \
    HERMES_DEPLOY_SSH_USER=ubuntu \
    HERMES_DEPLOY_SSH_PRIVATE_KEY="$private_key" \
    "$repo_root/scripts/hermes_backup.sh"
}

: >"$command_log"
run_backup >"$fixture_root/success.out"
archives=("$backup_dir"/*.tar.gz)
[[ "${#archives[@]}" -eq 1 ]] || fail "a successful run must create one archive"
tar --list --gzip --file "${archives[0]}" | grep -qx 'data/profiles/manager/session.json' \
  || fail "the archive must contain persistent Hermes data"
[[ "$(file_mode "${archives[0]}")" == 600 ]] \
  || fail "the archive containing credentials must have mode 0600"
[[ "$(<"$remote_state")" == running ]] \
  || fail "a successful backup must unpause the remote container"
grep -q 'Backup verified:' "$fixture_root/success.out" \
  || fail "success must be reported only after archive verification"
! grep -q '^terraform ' "$command_log" \
  || fail "an explicitly supplied host must not need Terraform"
printf 'PASS backup task creates and verifies a protected archive\n'

: >"$command_log"
if FAKE_SSH_MODE=failure run_backup >"$fixture_root/failure.out" 2>&1; then
  fail "an SSH transfer failure must fail the backup task"
fi
[[ "$(find "$backup_dir" -maxdepth 1 -type f -name '*.tar.gz' | wc -l | tr -d ' ')" == 1 ]] \
  || fail "a failed transfer must not leave a final archive"
[[ -z "$(find "$backup_dir" -maxdepth 1 -type f -name '.hermes-data-*' -print -quit)" ]] \
  || fail "a failed transfer must remove its temporary archive"
printf 'PASS failed SSH transfer leaves no apparently valid backup\n'

printf 'running\n' >"$remote_state"
: >"$remote_command_log"
if FAKE_REMOTE_PAUSE_STATUS=23 run_backup >"$fixture_root/pause-failure.out" 2>&1; then
  fail "a pause command failure must fail the backup"
fi
grep -q '^docker unpause hermes$' "$remote_command_log" \
  || fail "a failed pause request must trigger an unpause attempt"
[[ "$(<"$remote_state")" == running ]] \
  || fail "cleanup must recover a pause that took effect before reporting failure"
printf 'PASS failed pause request attempts cleanup after partial effect\n'

printf 'running\n' >"$remote_state"
: >"$remote_command_log"
if FAKE_REMOTE_TAR_MODE=failure run_backup >"$fixture_root/tar-failure.out" 2>&1; then
  fail "a remote archive failure must fail the backup"
fi
grep -q '^docker unpause hermes$' "$remote_command_log" \
  || fail "a remote archive failure must trigger unpause"
[[ "$(<"$remote_state")" == running ]] \
  || fail "a remote archive failure must leave the container unpaused"
printf 'PASS archive failure still unpauses the remote container\n'

printf 'running\n' >"$remote_state"
if FAKE_REMOTE_UNPAUSE_STATUS=24 run_backup >"$fixture_root/unpause-failure.out" 2>&1; then
  fail "a failed unpause must fail the backup"
fi
printf 'PASS unpause failure is reported as backup failure\n'

printf 'paused\n' >"$remote_state"
: >"$remote_command_log"
if run_backup >"$fixture_root/prepaused.out" 2>&1; then
  fail "backup must refuse to take ownership of an already paused container"
fi
! grep -q '^docker unpause hermes$' "$remote_command_log" \
  || fail "backup must not unpause a container that was already paused"
printf 'PASS pre-paused container is refused without unpausing it\n'
printf 'running\n' >"$remote_state"

: >"$command_log"
HERMES_DEPLOY_HOST='' run_backup >"$fixture_root/terraform-host.out"
grep -Eq '^terraform -chdir=.*/terraform output -raw server_ipv4$' "$command_log" \
  || fail "an omitted host must resolve from local Terraform state"
grep -q 'ubuntu@203.0.113.44' "$command_log" \
  || fail "the backup must use the resolved host"
printf 'PASS omitted host resolves from Terraform state\n'

task --taskfile "$repo_root/Taskfile.yml" --dry hermes:backup \
  >"$fixture_root/task-dry-run.out" 2>&1
grep -q './scripts/hermes_backup.sh' "$fixture_root/task-dry-run.out" \
  || fail "Go Task must expose the standalone backup command"
printf 'PASS Go Task exposes the standalone backup workflow\n'
