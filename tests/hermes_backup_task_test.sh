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
printf '%s\0' "$@" >"$FAKE_FIXTURE_ROOT/ssh-args"
cat >"$FAKE_FIXTURE_ROOT/remote-program.py"
case "$FAKE_SSH_MODE" in
  success) cat "$FAKE_FIXTURE_ROOT/personal.tar.gz" ;;
  full) cat "$FAKE_FIXTURE_ROOT/full.tar.gz" ;;
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
    "$repo_root/scripts/hermes_backup.sh" "$@"
}

archive_count() {
  find "$backup_dir" -maxdepth 1 -type f -name '*.tar.gz' | wc -l | tr -d ' '
}

expect_failure() {
  local mode="$1" before
  shift
  before="$(archive_count)"
  if FAKE_SSH_MODE="$mode" run_backup "$@" >"$fixture_root/$mode.out" 2>&1; then
    fail "$mode input must not be published as a verified backup for the requested scope"
  fi
  [[ "$(archive_count)" == "$before" ]] || fail "$mode left a final archive"
  ! grep -q 'Backup verified:' "$fixture_root/$mode.out" \
    || fail "$mode printed a success message"
  [[ -z "$(find "$backup_dir" -maxdepth 1 -name '.hermes-*' -print -quit)" ]] \
    || fail "$mode left temporary backup files"
}

python3 "$repo_root/tests/hermes_backup_bundle_test.py" \
  --fixture-bundle "$fixture_root/full.tar.gz"
# The default must not accept a full image-bearing bundle instead of personal state.
expect_failure full
printf 'PASS default scope rejects full recovery bundles\n'

# Gzip readability alone is not proof of a verified personal backup.
expect_failure legacy
printf 'PASS legacy archives cannot masquerade as verified personal backups\n'

python3 "$repo_root/tests/hermes_backup_bundle_test.py" \
  --fixture-personal-bundle "$fixture_root/personal.tar.gz"
: >"$command_log"
run_backup >"$fixture_root/success.out"
archives=("$backup_dir"/hermes-personal-*.tar.gz)
[[ "${#archives[@]}" -eq 1 && -f "${archives[0]}" ]] || fail "expected one personal backup"
python3 "$repo_root/scripts/hermes_backup_bundle.py" verify "${archives[0]}" personal
python3 - "${archives[0]}" <<'PYTHON'
from pathlib import Path
import stat
import sys
assert stat.S_IMODE(Path(sys.argv[1]).stat().st_mode) == 0o600
PYTHON
grep -q 'Backup verified:' "$fixture_root/success.out" || fail "missing verified success"
grep -q 'root@203.0.113.44 python3 - capture /opt/hermes hermes personal$' "$command_log" \
  || fail "default SSH capture must request personal state from the fixed runtime"
python3 - "$fixture_root/remote-program.py" <<'PYTHON'
from pathlib import Path
import sys
compile(Path(sys.argv[1]).read_text(), '<remote-program>', 'exec')
PYTHON
! grep -q '^terraform ' "$command_log" || fail "explicit host must not require Terraform"
printf 'PASS protected personal backup is verified before publication\n'

for mode in failure partial empty corrupt bad-tar legacy; do
  expect_failure "$mode"
done
[[ "$(archive_count)" == 1 ]] || fail "failed attempts must preserve the previous backup"
printf 'PASS bad transfers and archives fail without deleting previous good backups\n'

: >"$command_log"
HERMES_DEPLOY_HOST='' run_backup >"$fixture_root/default-host.out"
! grep -q '^terraform ' "$command_log" || fail "backup must not consult retired infrastructure state"
grep -q 'root@hermes-minimal' "$command_log" || fail "SSH overrides without a host must use the default alias"
[[ "$(archive_count)" == 2 ]] || fail "successive backups must remain distinct"
printf 'PASS omitted host uses the SSH alias with explicit user/key overrides\n'

: >"$command_log"
FAKE_SSH_MODE=full run_backup --full >"$fixture_root/full-success.out"
archives=("$backup_dir"/hermes-recovery-*.tar.gz)
[[ "${#archives[@]}" -eq 1 && -f "${archives[0]}" ]] || fail "expected one explicit full bundle"
python3 "$repo_root/scripts/hermes_backup_bundle.py" verify "${archives[0]}" full
grep -q 'root@203.0.113.44 python3 - capture /opt/hermes hermes$' "$command_log" \
  || fail "explicit full capture must retain the full recovery path"
expect_failure success --full
[[ "$(archive_count)" == 3 ]] || fail "scope mismatch must preserve all prior backups"
printf 'PASS explicit full recovery remains available and rejects personal-only input\n'

: >"$command_log"
if run_backup --unknown >"$fixture_root/invalid-flag.out" 2>&1; then
  fail "unknown flags must fail before host access"
fi
if run_backup --full unexpected >"$fixture_root/extra-argument.out" 2>&1; then
  fail "extra arguments must fail before host access"
fi
[[ ! -s "$command_log" ]] || fail "invalid arguments contacted an external command"
printf 'PASS invalid arguments fail before SSH or Terraform\n'

# Exercise the same missing-environment boundary as an ordinary shell launch.
run_connection_backup() {
  env -u HERMES_DEPLOY_HOST -u HERMES_DEPLOY_SSH_USER \
    -u HERMES_DEPLOY_SSH_PRIVATE_KEY \
    PATH="$fake_bin:$PATH" \
    FAKE_COMMAND_LOG="$command_log" \
    FAKE_FIXTURE_ROOT="$fixture_root" \
    FAKE_SSH_MODE=success \
    HERMES_BACKUP_DIR="$backup_dir" \
    "$@"
}

assert_connection() {
  python3 - "$fixture_root/ssh-args" "$@" <<'PYTHON'
from pathlib import Path
import sys

args = Path(sys.argv[1]).read_bytes().decode().split('\0')[:-1]
destination, key, scope = sys.argv[2:]
assert args[-2] == destination, args
command = 'python3 - capture /opt/hermes hermes'
if scope == 'personal':
    command += ' personal'
assert args[-1] == command, args
if key:
    assert args[args.index('-i') + 1] == key, args
else:
    assert '-i' not in args, args
assert '-o' in args and 'BatchMode=yes' in args, args
PYTHON
  ! grep -q '^terraform ' "$command_log" || fail "alias/explicit host must not use Terraform"
}

: >"$command_log"
run_connection_backup "$repo_root/scripts/hermes_backup.sh" >"$fixture_root/default-alias.out"
assert_connection hermes-minimal '' personal
: >"$command_log"
run_connection_backup HERMES_DEPLOY_HOST='' HERMES_DEPLOY_SSH_USER='' \
  HERMES_DEPLOY_SSH_PRIVATE_KEY='' "$repo_root/scripts/hermes_backup.sh" \
  >"$fixture_root/empty-alias.out"
assert_connection hermes-minimal '' personal
printf 'PASS unset/empty deployment variables use the SSH alias without identity overrides\n'

: >"$command_log"
before="$(archive_count)"
if run_connection_backup FAKE_SSH_MODE=failure "$repo_root/scripts/hermes_backup.sh" \
  >"$fixture_root/alias-failure.out" 2>&1; then
  fail "SSH alias failure must not succeed or switch targets"
fi
assert_connection hermes-minimal '' personal
[[ "$(grep -c '^ssh ' "$command_log")" == 1 ]] || fail "alias failure retried SSH"
[[ "$(archive_count)" == "$before" ]] || fail "alias failure published an archive"
[[ -z "$(find "$backup_dir" -maxdepth 1 -name '.hermes-*' -print -quit)" ]] \
  || fail "alias failure left temporary backup files"
printf 'PASS SSH alias failure does not fall back to Terraform or publish a backup\n'

for task_name in backup:hermes b:hermes hermes:backup backup:hermes:full; do
  : >"$command_log"
  run_connection_backup FAKE_SSH_MODE=full task --taskfile "$repo_root/Taskfile.yml" "$task_name" \
    >"$fixture_root/task-run.out" 2>&1 \
    || { printf '%s\n' "$(<"$fixture_root/task-run.out")" >&2; fail "Go Task $task_name must request a full recovery bundle"; }
  assert_connection hermes-minimal '' full
  grep -q 'Backup verified:' "$fixture_root/task-run.out" \
    || fail "Go Task $task_name must verify the backup without deployment variables"
done
printf 'PASS canonical, short, legacy and explicit-full Task names create full recovery bundles\n'

for task_name in backup:hermes:personal b:hermes:personal; do
  : >"$command_log"
  run_connection_backup task --taskfile "$repo_root/Taskfile.yml" "$task_name" \
    >"$fixture_root/task-personal.out" 2>&1
  assert_connection hermes-minimal '' personal
  grep -q 'Backup verified:' "$fixture_root/task-personal.out" \
    || fail "Go Task $task_name must retain an explicit verified personal-state path"
done
printf 'PASS explicit personal Task preserves the lightweight backup path\n'

: >"$command_log"
before="$(archive_count)"
if run_connection_backup task --taskfile "$repo_root/Taskfile.yml" backup:hermes \
  >"$fixture_root/task-scope-mismatch.out" 2>&1; then
  fail 'default Task must reject a personal-only archive when full recovery was requested'
fi
assert_connection hermes-minimal '' full
[[ "$(archive_count)" == "$before" ]] || fail 'Task scope mismatch published an archive'
printf 'PASS default Task rejects a personal-only response without publishing it\n'

: >"$command_log"
run_connection_backup FAKE_SSH_MODE=full "$repo_root/scripts/hermes_backup.sh" --full \
  >"$fixture_root/full-alias.out"
assert_connection hermes-minimal '' full
printf 'PASS explicit full mode also accepts the default SSH alias\n'

: >"$command_log"
run_connection_backup HERMES_DEPLOY_HOST=other-hermes "$repo_root/scripts/hermes_backup.sh" \
  >"$fixture_root/host-only.out"
assert_connection other-hermes '' personal

: >"$command_log"
run_connection_backup HERMES_DEPLOY_HOST=other-hermes HERMES_DEPLOY_SSH_USER=operator \
  "$repo_root/scripts/hermes_backup.sh" >"$fixture_root/user-override.out"
assert_connection operator@other-hermes '' personal

key_with_spaces="$fixture_root/override key"
cp "$private_key" "$key_with_spaces"
: >"$command_log"
run_connection_backup HERMES_DEPLOY_HOST=other-hermes \
  HERMES_DEPLOY_SSH_PRIVATE_KEY="$key_with_spaces" \
  "$repo_root/scripts/hermes_backup.sh" >"$fixture_root/key-override.out"
assert_connection other-hermes "$key_with_spaces" personal
printf 'PASS explicit host, user and key overrides preserve SSH argument boundaries\n'

: >"$command_log"
if run_connection_backup HERMES_DEPLOY_HOST=other-hermes \
  HERMES_DEPLOY_SSH_PRIVATE_KEY="$fixture_root/missing-key" \
  "$repo_root/scripts/hermes_backup.sh" >"$fixture_root/missing-key.out" 2>&1; then
  fail "an explicitly supplied missing key must fail"
fi
[[ ! -s "$command_log" ]] || fail "missing key contacted SSH or Terraform"
grep -q 'HERMES_DEPLOY_SSH_PRIVATE_KEY must name an existing regular file' \
  "$fixture_root/missing-key.out" || fail "missing key failure must identify the bad input"
printf 'PASS explicitly supplied keys are checked before external access\n'
