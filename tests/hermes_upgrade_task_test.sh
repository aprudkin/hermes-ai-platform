#!/usr/bin/env bash

set -euo pipefail
# shellcheck source=tests/test_helper.sh
source "$(dirname "${BASH_SOURCE[0]}")/test_helper.sh"

fixture_root="$(mktemp -d)"
trap 'rm -rf "$fixture_root"' EXIT
fake_bin="$fixture_root/bin"
fixture_repo="$fixture_root/repo"
command_log="$fixture_root/commands.log"
remote_root="$fixture_root/remote"
backup_dir="$fixture_root/backups"
private_key="$fixture_root/luk"
public_key="$fixture_root/luk.pub"
provider_env="$fixture_root/hermes.env"
review_file="$fixture_root/compatibility-review.json"

mkdir -p "$fake_bin" "$fixture_repo/scripts" "$fixture_repo/docker" \
  "$fixture_repo/docs" "$fixture_repo/installer" "$remote_root/data"
cp "$repo_root/scripts/hermes_upgrade.sh" "$fixture_repo/scripts/hermes_upgrade.sh"
cp "$repo_root/docker/docker-compose.yml" "$fixture_repo/docker/docker-compose.yml"
cp "$repo_root/README.md" "$fixture_repo/README.md"
cp "$repo_root/docs/operations.md" "$fixture_repo/docs/operations.md"
# Keep the disposable baseline independent of the production image pin.
python3 - "$fixture_repo/docker/docker-compose.yml" <<'PYTHON'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
content, count = re.subn(
    r"(?m)^(\s*image:\s*nousresearch/hermes-agent:)[^\s#]+\s*$",
    r"\g<1>v2026.8.27",
    path.read_text(),
)
if count != 1:
    raise SystemExit("expected exactly one Hermes image pin in test fixture")
path.write_text(content)
PYTHON
cp "$fixture_repo/docker/docker-compose.yml" "$fixture_root/compose.baseline.yml"
printf 'private fixture key\n' >"$private_key"
printf 'public fixture key\n' >"$public_key"
printf 'OPENROUTER_API_KEY=test-only-value\n' >"$provider_env"
printf 'persistent state\n' >"$remote_root/data/state.txt"

cat >"$fake_bin/ssh" <<'FAKE'
#!/usr/bin/env bash
set -euo pipefail
printf 'ssh %s\n' "$*" >>"$FAKE_COMMAND_LOG"
tar -C "$FAKE_REMOTE_ROOT" -cf - data | gzip -c
FAKE

cat >"$fake_bin/gh" <<'FAKE'
#!/usr/bin/env bash
set -euo pipefail
printf 'gh %s\n' "$*" >>"$FAKE_COMMAND_LOG"
printf '%s\n' "$FAKE_HERMES_TAG"
FAKE

cat >"$fake_bin/terraform" <<'FAKE'
#!/usr/bin/env bash
set -euo pipefail
printf 'terraform %s\n' "$*" >>"$FAKE_COMMAND_LOG"
[[ "$*" == *"output -raw server_ipv4"* ]] \
  || { printf 'unexpected terraform command: %s\n' "$*" >&2; exit 1; }
printf '%s\n' 203.0.113.44
FAKE


cat >"$fake_bin/git" <<'FAKE'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "-C" ]]; then
  shift 2
fi
case "${1:-}" in
  status)
    exit 0
    ;;
  symbolic-ref)
    printf 'main\n'
    ;;
  commit)
    printf 'git commit' >>"$FAKE_COMMAND_LOG"
    printf ' <%s>' "$@" >>"$FAKE_COMMAND_LOG"
    printf '\n' >>"$FAKE_COMMAND_LOG"
    ;;
  add|push)
    printf 'git %s\n' "$*" >>"$FAKE_COMMAND_LOG"
    ;;
  *)
    printf 'unexpected git command: %s\n' "$*" >&2
    exit 1
    ;;
esac
FAKE

cat >"$fixture_repo/installer/install.sh" <<'FAKE'
#!/usr/bin/env bash
set -euo pipefail
printf 'installer %s\n' "$*" >>"$FAKE_COMMAND_LOG"
FAKE

chmod +x "$fake_bin/ssh" "$fake_bin/gh" "$fake_bin/git" "$fake_bin/terraform" \
  "$fixture_repo/scripts/hermes_upgrade.sh" "$fixture_repo/installer/install.sh"

run_upgrade() {
  PATH="$fake_bin:$PATH" \
    FAKE_COMMAND_LOG="$command_log" \
    FAKE_REMOTE_ROOT="$remote_root" \
    HERMES_BACKUP_DIR="$backup_dir" \
    HERMES_DEPLOY_HOST="${HERMES_DEPLOY_HOST-203.0.113.44}" \
    HERMES_DEPLOY_SSH_USER=root \
    HERMES_DEPLOY_SSH_PRIVATE_KEY="$private_key" \
    HERMES_DEPLOY_SSH_PUBLIC_KEY="$public_key" \
    HERMES_DEPLOY_SSH_SOURCE_CIDR=198.51.100.10/32 \
    HERMES_MODEL_PROVIDER=openrouter \
    HERMES_MODEL=test/model \
    HERMES_ENV="$provider_env" \
    HERMES_ISSUE_NUMBER="${HERMES_ISSUE_NUMBER-}" \
    HERMES_UPGRADE_REVIEW_FILE="${HERMES_UPGRADE_REVIEW_FILE:-}" \
    "$fixture_repo/scripts/hermes_upgrade.sh"
}

: >"$command_log"
FAKE_HERMES_TAG=v2026.8.27 run_upgrade >"$fixture_root/no-update.out"

archives=("$backup_dir"/*.tar.gz)
[[ "${#archives[@]}" -eq 1 ]] \
  || fail "the no-update path must create exactly one backup archive"
tar --list --gzip --file "${archives[0]}" | grep -qx 'data/state.txt' \
  || fail "the backup archive must contain the persistent Hermes data"
[[ "$(sed -n '1p' "$command_log")" == ssh\ * ]] \
  || fail "the backup must run before the upstream release lookup"
! grep -q '^git ' "$command_log" \
  || fail "the no-update path must not commit or push"
! grep -q '^installer ' "$command_log" \
  || fail "the no-update path must not deploy"
grep -q 'skipping push and deployment' "$fixture_root/no-update.out" \
  || fail "the no-update path must report the skipped external mutations"
printf 'PASS no-update path backs up before skipping push and deployment\n'

: >"$command_log"
if FAKE_HERMES_TAG=v2026.9.01 HERMES_ISSUE_NUMBER=123 \
  CONFIRM_PUSH=yes CONFIRM_DEPLOY=yes \
  run_upgrade >"$fixture_root/unreviewed.out" 2>&1; then
  fail "the update path must reject a release without compatibility evidence"
fi
! grep -q '^git ' "$command_log" \
  || fail "an unreviewed release must not be staged, committed, or pushed"
! grep -q '^installer ' "$command_log" \
  || fail "an unreviewed release must not be deployed"
grep -q 'HERMES_UPGRADE_REVIEW_FILE' "$fixture_root/unreviewed.out" \
  || fail "the refusal must explain the missing review evidence"
printf 'PASS changed release refuses to proceed without compatibility evidence\n'

python3 - "$review_file" "$fixture_repo" <<'PYTHON'
import hashlib
import json
from pathlib import Path
import sys

review_path = Path(sys.argv[1])
root = Path(sys.argv[2])
contracts = ["README.md", "docs/operations.md", "docker/docker-compose.yml"]
review = {
    "tag": "v2026.9.01",
    "release_notes_url": "https://github.com/NousResearch/hermes-agent/releases/tag/v2026.9.01",
    "compatibility": "compatible",
    "summary": "Reviewed release notes and current image-dependent project contracts.",
    "contracts": {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in contracts
    },
    "checks": [
        {"command": "./installer/install.sh validate", "result": "passed"}
    ],
}
review_path.write_text(json.dumps(review))
PYTHON

python3 - "$review_file" <<'PYTHON'
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
review = json.loads(path.read_text())
review["tag"] = "v2026.8.27"
path.write_text(json.dumps(review))
PYTHON
: >"$command_log"
if FAKE_HERMES_TAG=v2026.9.01 HERMES_ISSUE_NUMBER=123 \
  HERMES_UPGRADE_REVIEW_FILE="$review_file" \
  CONFIRM_PUSH=yes CONFIRM_DEPLOY=yes run_upgrade >"$fixture_root/stale-tag.out" 2>&1; then
  fail "the update path must reject evidence for a different release tag"
fi
! grep -q '^git ' "$command_log" \
  || fail "evidence for a different release tag must not reach Git mutations"
! grep -q '^installer ' "$command_log" \
  || fail "evidence for a different release tag must not reach deployment"
printf 'PASS review evidence must match the exact release tag\n'

python3 - "$review_file" "$fixture_repo" <<'PYTHON'
import hashlib
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
root = Path(sys.argv[2])
review = json.loads(path.read_text())
review["tag"] = "v2026.9.01"
review["contracts"]["README.md"] = hashlib.sha256(
    (root / "README.md").read_bytes()
).hexdigest()
path.write_text(json.dumps(review))
(root / "README.md").write_text((root / "README.md").read_text() + " ")
PYTHON
: >"$command_log"
if FAKE_HERMES_TAG=v2026.9.01 HERMES_ISSUE_NUMBER=123 \
  HERMES_UPGRADE_REVIEW_FILE="$review_file" \
  CONFIRM_PUSH=yes CONFIRM_DEPLOY=yes run_upgrade >"$fixture_root/stale-contract.out" 2>&1; then
  fail "the update path must reject evidence for changed project contracts"
fi
! grep -q '^git ' "$command_log" \
  || fail "stale contract evidence must not reach Git mutations"
! grep -q '^installer ' "$command_log" \
  || fail "stale contract evidence must not reach deployment"
printf 'PASS review evidence must match the inspected project contracts\n'
cp "$repo_root/README.md" "$fixture_repo/README.md"

: >"$command_log"
FAKE_HERMES_TAG=v2026.9.01 HERMES_ISSUE_NUMBER=123 \
  HERMES_UPGRADE_REVIEW_FILE="$review_file" \
  CONFIRM_PUSH=yes CONFIRM_DEPLOY=yes run_upgrade >"$fixture_root/update.out"
grep -q 'nousresearch/hermes-agent:v2026.9.01' \
  "$fixture_repo/docker/docker-compose.yml" \
  || fail "the update path must pin the discovered Hermes release"
grep -q '^git add docker/docker-compose.yml$' "$command_log" \
  || fail "the update path must stage only the image pin"
grep -Fqx 'git commit <commit> <-m> <chore: update Hermes Agent to v2026.9.01> <-m> <Refs: #123>' \
  "$command_log" \
  || fail "the update commit must use the required conventional header and issue-reference footer"
grep -q '^git push origin main$' "$command_log" \
  || fail "the update path must push the current branch"
grep -q '^installer deploy existing ' "$command_log" \
  || fail "the update path must invoke the existing-host installer"
grep -q -- '--confirm-external-mutation' "$command_log" \
  || fail "the update path must preserve the installer's deployment confirmation"
printf 'PASS update path pins, pushes, and deploys after a verified backup\n'
cp "$fixture_repo/docker/docker-compose.yml" "$fixture_root/compose.updated.yml"
cp "$fixture_root/compose.baseline.yml" "$fixture_repo/docker/docker-compose.yml"

: >"$command_log"
if FAKE_HERMES_TAG=v2026.9.01 HERMES_ISSUE_NUMBER='' run_upgrade \
  >"$fixture_root/missing-issue.out" 2>&1; then
  fail "the update path must reject a missing task issue number"
fi
grep -q 'HERMES_ISSUE_NUMBER must be a positive decimal issue number' \
  "$fixture_root/missing-issue.out" \
  || fail "a missing issue number must report the validation failure"
! grep -Eq '^(git (add|commit|push)|installer )' "$command_log" \
  || fail "the update path must reject a missing issue number before external mutation"

: >"$command_log"
if FAKE_HERMES_TAG=v2026.9.01 HERMES_ISSUE_NUMBER=issue-123 run_upgrade \
  >"$fixture_root/invalid-issue.out" 2>&1; then
  fail "the update path must reject a malformed task issue number"
fi
grep -q 'HERMES_ISSUE_NUMBER must be a positive decimal issue number' \
  "$fixture_root/invalid-issue.out" \
  || fail "a malformed issue number must report the validation failure"
! grep -Eq '^(git (add|commit|push)|installer )' "$command_log" \
  || fail "the update path must reject a malformed issue number before external mutation"
printf 'PASS update path rejects missing and malformed issue references\n'
cp "$fixture_root/compose.updated.yml" "$fixture_repo/docker/docker-compose.yml"

: >"$command_log"
FAKE_HERMES_TAG=v2026.9.01 HERMES_DEPLOY_HOST='' run_upgrade \
  >"$fixture_root/terraform-host.out"
grep -Eq '^terraform -chdir=.*/terraform output -raw server_ipv4$' "$command_log" \
  || fail "the upgrade must resolve an omitted deployment host from Terraform state"
grep -q 'root@203.0.113.44' "$command_log" \
  || fail "the backup must use the Terraform-resolved deployment host"
printf 'PASS omitted deployment host resolves from Terraform state\n'


task --taskfile "$repo_root/Taskfile.yml" --dry hermes:update \
  >"$fixture_root/task-dry-run.out" 2>&1
grep -q './scripts/hermes_upgrade.sh' "$fixture_root/task-dry-run.out" \
  || fail "Go Task dry run must invoke the upgrade workflow"
printf 'PASS Go Task exposes the upgrade workflow\n'
