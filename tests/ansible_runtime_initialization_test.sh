#!/usr/bin/env bash

set -euo pipefail
# shellcheck source=tests/test_helper.sh
source "$(dirname "${BASH_SOURCE[0]}")/test_helper.sh"

ansible_command=()
if ansible-playbook --version >/dev/null 2>&1; then
  ansible_command=(ansible-playbook)
elif [[ "${HERMES_TEST_ALLOW_UVX:-0}" == "1" ]] \
  && command -v uvx >/dev/null 2>&1; then
  ansible_command=(uvx --from 'ansible-core>=2.18,<2.20' ansible-playbook)
else
  printf 'SKIP Hermes runtime initialization (runnable ansible-playbook unavailable)\n'
  exit 0
fi

fixture_root="$(mktemp -d)"
trap 'rm -rf "$fixture_root"' EXIT
fake_bin="$fixture_root/bin"
docker_log="$fixture_root/docker.log"
runtime_state="$fixture_root/runtime-current"
ansible_log="$fixture_root/ansible.log"
mkdir -p "$fake_bin"

cat >"$fake_bin/docker" <<'FAKE'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"$HERMES_TEST_DOCKER_LOG"
if [[ "$*" == "exec --user 10000:10000 --env HOME=/opt/data --env CODEX_HOME=/opt/data/.codex hermes hermes config check" ]]; then
  if [[ -e "$HERMES_TEST_RUNTIME_STATE" ]]; then
    printf 'Config version: 37 ✓\n'
  else
    printf 'Config version: 0 → 37 (update available)\n'
  fi
elif [[ "$*" == "exec --user 10000:10000 --env HOME=/opt/data --env CODEX_HOME=/opt/data/.codex hermes hermes setup --non-interactive --reset" ]]; then
  : >"$HERMES_TEST_RUNTIME_STATE"
  printf 'Setup complete\n'
else
  printf 'unexpected docker command: %s\n' "$*" >&2
  exit 64
fi
FAKE
chmod +x "$fake_bin/docker"

HERMES_TEST_BIN="$fake_bin" \
HERMES_TEST_DOCKER_LOG="$docker_log" \
HERMES_TEST_RUNTIME_STATE="$runtime_state" \
ANSIBLE_ROLES_PATH="$repo_root/ansible/roles" \
  "${ansible_command[@]}" --inventory localhost, \
    "$repo_root/tests/fixtures/hermes_runtime_initialization.yml" >"$ansible_log" \
  || {
    sed -n '1,180p' "$ansible_log" >&2
    fail "Hermes runtime initialization playbook failed"
  }

[[ "$(grep -c '^exec --user 10000:10000 --env HOME=/opt/data --env CODEX_HOME=/opt/data/.codex hermes hermes config check$' "$docker_log")" == "2" ]] \
  || fail "each run must inspect the runtime configuration"
[[ "$(grep -c '^exec --user 10000:10000 --env HOME=/opt/data --env CODEX_HOME=/opt/data/.codex hermes hermes setup --non-interactive --reset$' "$docker_log")" == "1" ]] \
  || fail "only the outdated runtime configuration must be initialized"
printf 'PASS Hermes runtime initialization upgrades once before health checks\n'
