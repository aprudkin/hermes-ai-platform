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

mkdir -p "$fake_bin" "$fixture_repo/scripts" "$fixture_repo/docker" \
  "$fixture_repo/installer" "$remote_root/data"
cp "$repo_root/scripts/hermes_upgrade.sh" "$fixture_repo/scripts/hermes_upgrade.sh"
cp "$repo_root/docker/docker-compose.yml" "$fixture_repo/docker/docker-compose.yml"
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
  add|commit|push)
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

chmod +x "$fake_bin/ssh" "$fake_bin/gh" "$fake_bin/git" \
  "$fixture_repo/scripts/hermes_upgrade.sh" "$fixture_repo/installer/install.sh"

run_upgrade() {
  PATH="$fake_bin:$PATH" \
    FAKE_COMMAND_LOG="$command_log" \
    FAKE_REMOTE_ROOT="$remote_root" \
    HERMES_BACKUP_DIR="$backup_dir" \
    HERMES_DEPLOY_HOST=203.0.113.44 \
    HERMES_DEPLOY_SSH_USER=root \
    HERMES_DEPLOY_SSH_PRIVATE_KEY="$private_key" \
    HERMES_DEPLOY_SSH_PUBLIC_KEY="$public_key" \
    HERMES_DEPLOY_SSH_SOURCE_CIDR=198.51.100.10/32 \
    HERMES_MODEL_PROVIDER=openrouter \
    HERMES_MODEL=test/model \
    HERMES_ENV="$provider_env" \
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
FAKE_HERMES_TAG=v2026.9.01 CONFIRM_PUSH=yes CONFIRM_DEPLOY=yes run_upgrade \
  >"$fixture_root/update.out"
grep -q 'nousresearch/hermes-agent:v2026.9.01' \
  "$fixture_repo/docker/docker-compose.yml" \
  || fail "the update path must pin the discovered Hermes release"
grep -q '^git add docker/docker-compose.yml$' "$command_log" \
  || fail "the update path must stage only the image pin"
grep -q '^git commit -m chore: update Hermes Agent to v2026.9.01$' "$command_log" \
  || fail "the update path must create a release-specific commit"
grep -q '^git push origin main$' "$command_log" \
  || fail "the update path must push the current branch"
grep -q '^installer deploy existing ' "$command_log" \
  || fail "the update path must invoke the existing-host installer"
grep -q -- '--confirm-external-mutation' "$command_log" \
  || fail "the update path must preserve the installer's deployment confirmation"
printf 'PASS update path pins, pushes, and deploys after a verified backup\n'

task --taskfile "$repo_root/Taskfile.yml" --dry hermes:update \
  >"$fixture_root/task-dry-run.out" 2>&1
grep -q './scripts/hermes_upgrade.sh' "$fixture_root/task-dry-run.out" \
  || fail "Go Task dry run must invoke the upgrade workflow"
printf 'PASS Go Task exposes the upgrade workflow\n'
