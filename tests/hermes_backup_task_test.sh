#!/usr/bin/env bash

set -euo pipefail
# shellcheck source=tests/test_helper.sh
source "$(dirname "${BASH_SOURCE[0]}")/test_helper.sh"

fixture_root="$(mktemp -d)"
trap 'rm -rf "$fixture_root"' EXIT
fake_bin="$fixture_root/bin"
backup_dir="$fixture_root/backups"
command_log="$fixture_root/commands.log"
private_key="$fixture_root/luk"
mkdir -p "$fake_bin" "$backup_dir"
printf 'private fixture key\n' >"$private_key"

python3 - "$fixture_root" <<'PYTHON'
import gzip
import io
from pathlib import Path
import sys
import tarfile

root = Path(sys.argv[1])
with tarfile.open(root / "legacy.tar.gz", "w:gz") as archive:
    value = b"persistent fixture state\n"
    info = tarfile.TarInfo("data/state.txt")
    info.size = len(value)
    archive.addfile(info, io.BytesIO(value))
(root / "bad-tar.gz").write_bytes(gzip.compress(b"not a tar archive"))
PYTHON

cat >"$fake_bin/ssh" <<'FAKE'
#!/usr/bin/env bash
set -euo pipefail
printf 'ssh %s\n' "$*" >>"$FAKE_COMMAND_LOG"
cat >"$FAKE_FIXTURE_ROOT/remote-program.py"
case "$FAKE_SSH_MODE" in
  success) cat "$FAKE_FIXTURE_ROOT/valid.tar.gz" ;;
  legacy) cat "$FAKE_FIXTURE_ROOT/legacy.tar.gz" ;;
  bad-tar) cat "$FAKE_FIXTURE_ROOT/bad-tar.gz" ;;
  corrupt) printf 'not gzip\n' ;;
  empty) : ;;
  failure) exit 23 ;;
  partial) head -c 80 "$FAKE_FIXTURE_ROOT/legacy.tar.gz"; exit 24 ;;
  *) exit 99 ;;
esac
FAKE

cat >"$fake_bin/terraform" <<'FAKE'
#!/usr/bin/env bash
set -euo pipefail
printf 'terraform %s\n' "$*" >>"$FAKE_COMMAND_LOG"
[[ "$*" == *"output -raw server_ipv4"* ]] || exit 2
printf '%s\n' 203.0.113.44
FAKE
chmod +x "$fake_bin/ssh" "$fake_bin/terraform"

run_backup() {
  PATH="$fake_bin:$PATH" \
    FAKE_COMMAND_LOG="$command_log" \
    FAKE_FIXTURE_ROOT="$fixture_root" \
    FAKE_SSH_MODE="${FAKE_SSH_MODE:-success}" \
    HERMES_BACKUP_DIR="$backup_dir" \
    HERMES_DEPLOY_HOST="${HERMES_DEPLOY_HOST-203.0.113.44}" \
    HERMES_DEPLOY_SSH_USER=root \
    HERMES_DEPLOY_SSH_PRIVATE_KEY="$private_key" \
    "$repo_root/scripts/hermes_backup.sh"
}

archive_count() {
  find "$backup_dir" -maxdepth 1 -type f -name '*.tar.gz' | wc -l | tr -d ' '
}

expect_failure() {
  local mode="$1" before
  before="$(archive_count)"
  if FAKE_SSH_MODE="$mode" run_backup >"$fixture_root/$mode.out" 2>&1; then
    fail "$mode input must not be published as a complete recovery bundle"
  fi
  [[ "$(archive_count)" == "$before" ]] || fail "$mode left a final archive"
  ! grep -q 'Backup verified:' "$fixture_root/$mode.out" \
    || fail "$mode printed a success message"
  [[ -z "$(find "$backup_dir" -maxdepth 1 -name '.hermes-*' -print -quit)" ]] \
    || fail "$mode left temporary backup files"
}

# A gzip-readable data-only archive is not sufficient for portable recovery.
expect_failure legacy
printf 'PASS data-only archives cannot masquerade as complete recovery bundles\n'

python3 "$repo_root/tests/hermes_backup_bundle_test.py" \
  --fixture-bundle "$fixture_root/valid.tar.gz"
: >"$command_log"
run_backup >"$fixture_root/success.out"
archives=("$backup_dir"/hermes-recovery-*.tar.gz)
[[ "${#archives[@]}" -eq 1 && -f "${archives[0]}" ]] || fail "expected one recovery bundle"
python3 "$repo_root/scripts/hermes_backup_bundle.py" verify "${archives[0]}"
python3 - "${archives[0]}" <<'PYTHON'
from pathlib import Path
import stat
import sys
assert stat.S_IMODE(Path(sys.argv[1]).stat().st_mode) == 0o600
PYTHON
grep -q 'Backup verified:' "$fixture_root/success.out" || fail "missing verified success"
grep -q 'root@203.0.113.44 python3 - capture /opt/hermes hermes' "$command_log" \
  || fail "SSH must execute the capture helper against the fixed project runtime"
python3 - "$fixture_root/remote-program.py" <<'PYTHON'
from pathlib import Path
import sys
compile(Path(sys.argv[1]).read_text(), '<remote-program>', 'exec')
PYTHON
! grep -q '^terraform ' "$command_log" || fail "explicit host must not require Terraform"
printf 'PASS protected complete bundle is verified before publication\n'

for mode in failure partial empty corrupt bad-tar legacy; do
  expect_failure "$mode"
done
[[ "$(archive_count)" == 1 ]] || fail "failed attempts must preserve the previous backup"
printf 'PASS bad transfers and archives fail without deleting previous good backups\n'

: >"$command_log"
HERMES_DEPLOY_HOST='' run_backup >"$fixture_root/terraform-host.out"
grep -Eq '^terraform -chdir=.*/terraform output -raw server_ipv4$' "$command_log" \
  || fail "omitted host must resolve from local Terraform state"
grep -q 'root@203.0.113.44' "$command_log" || fail "resolved host was not used"
[[ "$(archive_count)" == 2 ]] || fail "successive backups must remain distinct"
printf 'PASS omitted host resolves from Terraform state\n'

for task_name in backup:hermes b:hermes hermes:backup; do
  task --taskfile "$repo_root/Taskfile.yml" --dry "$task_name" \
    >"$fixture_root/task-dry-run.out" 2>&1
  grep -q './scripts/hermes_backup.sh' "$fixture_root/task-dry-run.out" \
    || fail "Go Task $task_name must expose the standalone backup command"
done
printf 'PASS Go Task exposes canonical, short, and legacy backup names\n'
