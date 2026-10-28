#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=tests/test_helper.sh
source "$(dirname "${BASH_SOURCE[0]}")/test_helper.sh"
fixture_root="$(mktemp -d)"
trap 'rm -rf "$fixture_root"' EXIT
fake_bin="$fixture_root/bin"
fixture_repo="$fixture_root/repo"
command_log="$fixture_root/commands.log"
review_file="$fixture_root/review.json"
mkdir -p "$fake_bin" "$fixture_repo/"{scripts,docker,docs}
cp "$repo_root/scripts/"hermes_{upgrade.sh,backup.sh,backup_bundle.py,backup_progress.py} "$fixture_repo/scripts/"
cp "$repo_root/docs/"{backup-restore.md,operations.md} "$fixture_repo/docs/"
cp "$repo_root/README.md" "$fixture_repo/"
printf 'image: nousresearch/hermes-agent:v1\n' >"$fixture_repo/docker/docker-compose.yml"
printf 'fixture key\n' >"$fixture_root/key"
python3 "$repo_root/tests/hermes_backup_bundle_test.py" --fixture-bundle "$fixture_root/bundle.tar.gz"
cat >"$fake_bin/ssh" <<'FAKE'
#!/usr/bin/env bash
set -euo pipefail
printf 'ssh %s\n' "$*" >>"$FAKE_COMMAND_LOG"
cat >/dev/null
[[ "${FAIL_BACKUP:-no}" != yes ]] || exit 23
cat "$FAKE_BUNDLE"
FAKE
cat >"$fake_bin/gh" <<'FAKE'
#!/usr/bin/env bash
printf 'gh %s\n' "$*" >>"$FAKE_COMMAND_LOG"
printf '%s\n' "$FAKE_TAG"
FAKE
cat >"$fake_bin/git" <<'FAKE'
#!/usr/bin/env bash
set -euo pipefail
shift 2
[[ "$1" == status ]] || { printf 'git mutation forbidden\n' >&2; exit 91; }
printf '%s' "${DIRTY:-}"
FAKE
cat >"$fake_bin/terraform" <<'FAKE'
#!/usr/bin/env bash
printf 'terraform %s\n' "$*" >>"$FAKE_COMMAND_LOG"
printf '203.0.113.44\n'
FAKE
cat >"$fixture_repo/scripts/validate.sh" <<'FAKE'
#!/usr/bin/env bash
set -euo pipefail
printf 'validate %s\n' "$*" >>"$FAKE_COMMAND_LOG"
[[ "$*" == --all ]] || exit 92
[[ "${FAIL_VALIDATE:-no}" != yes ]] || exit 42
FAKE
chmod +x "$fake_bin/"* "$fixture_repo/scripts/validate.sh"
run_upgrade() {
  PATH="$fake_bin:$PATH" FAKE_COMMAND_LOG="$command_log" \
    FAKE_BUNDLE="$fixture_root/bundle.tar.gz" FAKE_TAG="${FAKE_TAG:-v2}" \
    HERMES_BACKUP_DIR="$fixture_root/backups" \
    HERMES_DEPLOY_HOST="${HERMES_DEPLOY_HOST-203.0.113.44}" \
    HERMES_DEPLOY_SSH_USER="${HERMES_DEPLOY_SSH_USER-root}" \
    HERMES_DEPLOY_SSH_PRIVATE_KEY="${HERMES_DEPLOY_SSH_PRIVATE_KEY-$fixture_root/key}" \
    HERMES_UPGRADE_REVIEW_FILE="${HERMES_UPGRADE_REVIEW_FILE-$review_file}" \
    bash "$fixture_repo/scripts/hermes_upgrade.sh"
}
make_review() {
  python3 - "$review_file" "$fixture_repo" <<'PY'
import hashlib, json, sys
from pathlib import Path
root = Path(sys.argv[2])
Path(sys.argv[1]).write_text(json.dumps({
    "tag": "v2", "release_notes_url": "https://github.com/NousResearch/hermes-agent/releases/tag/v2",
    "compatibility": "compatible", "summary": "Fixture review",
    "contracts": {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                  for name in ("README.md", "docs/operations.md", "docker/docker-compose.yml")},
    "checks": [{"command": "./scripts/validate.sh --all", "result": "passed"}]
}))
PY
}
# An explicit bad key must fail before host access; otherwise SSH alias config
# may supply both the user and identity without duplicated environment settings.
: >"$command_log"
if HERMES_DEPLOY_SSH_PRIVATE_KEY="$fixture_root/missing" run_upgrade >"$fixture_root/error" 2>&1; then
  fail 'an explicit missing SSH key must fail'
fi
[[ ! -s "$command_log" ]] || fail 'missing SSH key reached host access'
for variable in CONFIRM_PUSH CONFIRM_DEPLOY; do
  : >"$command_log"
  if (export "$variable=yes"; run_upgrade) >"$fixture_root/error" 2>&1; then
    fail "legacy automation flags must explicitly fail, not silently change behavior"
  fi
  [[ ! -s "$command_log" ]] || fail "legacy flags reached remote access"
done
: >"$command_log"
if DIRTY=' M unrelated' run_upgrade >"$fixture_root/error" 2>&1; then fail 'dirty checkout accepted'; fi
[[ ! -s "$command_log" ]] || fail 'dirty checkout reached backup'
: >"$command_log"
if FAIL_BACKUP=yes run_upgrade >"$fixture_root/error" 2>&1; then fail 'failed backup accepted'; fi
! grep -Eq '^(gh|validate) ' "$command_log" || fail 'backup failure reached later actions'
printf 'PASS input, legacy authorization, clean-tree and backup gates\n'

: >"$command_log"
if FAKE_TAG=v1 run_upgrade >"$fixture_root/same-pin" 2>&1; then
  fail 'REGRESSION: matching local pin is not evidence of a successful deployment/retry'
fi
grep -q 'live deployment is UNKNOWN' "$fixture_root/same-pin" \
  || { printf '%s\n' "$(<"$fixture_root/same-pin")" >&2; fail 'missing deployment uncertainty'; }
! grep -q '^validate ' "$command_log" || fail 'same pin invoked installer'
archives=("$fixture_root/backups/"*.tar.gz)
[[ "${#archives[@]}" -eq 1 ]] || fail 'same pin must still retain one recovery capture'
python3 "$repo_root/scripts/hermes_backup_bundle.py" verify "${archives[0]}" full
grep -q 'root@203.0.113.44 python3 - capture /opt/hermes hermes$' "$command_log" || fail 'backup is not full'
[[ "$(head -1 "$command_log")" == ssh\ * ]] || fail 'release lookup preceded backup'
printf 'PASS same-pin retry cannot report a successful no-op\n'

if HERMES_UPGRADE_REVIEW_FILE='' run_upgrade >"$fixture_root/error" 2>&1; then fail 'missing review accepted'; fi
make_review
for mutation in tag contracts compatibility; do
  cp "$review_file" "$fixture_root/review-original"
  python3 - "$review_file" "$mutation" <<'PY'
import json, sys
from pathlib import Path
p = Path(sys.argv[1]); value = json.loads(p.read_text())
if sys.argv[2] == 'contracts': value['contracts']['README.md'] = '0' * 64
else: value[sys.argv[2]] = 'wrong'
p.write_text(json.dumps(value))
PY
  : >"$command_log"
  if run_upgrade >"$fixture_root/error" 2>&1; then fail "invalid $mutation accepted"; fi
  ! grep -q '^validate ' "$command_log" || fail 'invalid review reached validation/deployment'
  cp "$fixture_root/review-original" "$review_file"
done
printf 'PASS missing, stale and incompatible reviews fail closed\n'

: >"$command_log"
run_upgrade >"$fixture_root/prepared"
grep -q 'image: nousresearch/hermes-agent:v2' "$fixture_repo/docker/docker-compose.yml" || fail 'pin not prepared'
grep -qx 'validate --all' "$command_log" || fail 'candidate not validated'
! grep -q '^validate deploy' "$command_log" || fail 'preparation deployed'
grep -q 'NOT committed, pushed or deployed' "$fixture_root/prepared" || fail 'missing scope of evidence'
printf 'PASS candidate validated without commit, push or deployment\n'

: >"$command_log"
if run_upgrade >"$fixture_root/retry" 2>&1; then fail 'same pin retry returned success'; fi
! grep -q '^validate ' "$command_log" || fail 'retry silently deployed'
printf 'image: nousresearch/hermes-agent:v1\n' >"$fixture_repo/docker/docker-compose.yml"
make_review
if FAIL_VALIDATE=yes run_upgrade >"$fixture_root/error" 2>&1; then fail 'candidate validation failure swallowed'; fi
grep -q 'image: nousresearch/hermes-agent:v2' "$fixture_repo/docker/docker-compose.yml" || fail 'failed candidate diff must remain inspectable'
if run_upgrade >"$fixture_root/retry" 2>&1; then fail 'failed validation retry returned success'; fi
printf 'PASS failed validation and retry stay failures\n'

: >"$command_log"
if HERMES_DEPLOY_HOST='' HERMES_DEPLOY_SSH_USER='' HERMES_DEPLOY_SSH_PRIVATE_KEY='' run_upgrade >"$fixture_root/error" 2>&1; then fail 'same pin unexpectedly prepared'; fi
! grep -q '^terraform ' "$command_log" || fail 'retired infrastructure lookup was invoked'
grep -q 'hermes-minimal python3 - capture' "$command_log" || fail 'default SSH alias was not used'
for task_name in update:hermes hermes:update; do
  task --taskfile "$repo_root/Taskfile.yml" --dry "$task_name" >"$fixture_root/task" 2>&1
  grep -q './scripts/hermes_upgrade.sh' "$fixture_root/task" || fail 'legacy task alias lost'
done
printf 'PASS task aliases and default SSH alias preserved\n'
