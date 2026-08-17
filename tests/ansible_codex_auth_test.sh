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
  printf 'SKIP Codex subscription auth installation (runnable ansible-playbook unavailable)\n'
  exit 0
fi

fixture_root="$(mktemp -d)"
trap 'rm -rf "$fixture_root"' EXIT
data_dir="$fixture_root/data"
codex_auth="$fixture_root/codex-auth.json"
fake_bin="$fixture_root/bin"
auth_command_log="$fixture_root/auth-command.log"
auth_stdin_log="$fixture_root/auth-stdin.log"
mkdir -p "$data_dir" "$fake_bin"
printf '{"tokens":{"access_token":"fixture-access","refresh_token":"fixture-refresh"}}\n' >"$codex_auth"
chmod 600 "$codex_auth"

cat >"$fake_bin/script" <<'FAKE'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"$HERMES_TEST_AUTH_COMMAND_LOG"
expected="--quiet --return --command docker exec --interactive --tty --user $HERMES_TEST_OWNER:$HERMES_TEST_GROUP --env HOME=/opt/data --env CODEX_HOME=/opt/data/.codex hermes hermes model /dev/null"
[[ "$*" == "$expected" ]] || exit 64
for prompt_number in 1 2 3 4; do
  IFS= read -r answer
  printf '%s\n' "$answer" >>"$HERMES_TEST_AUTH_STDIN_LOG"
done
[[ "$(sed -n '3p' "$HERMES_TEST_AUTH_STDIN_LOG")" == "y" ]] || exit 65
mkdir -p "$(dirname "$HERMES_TEST_HERMES_AUTH")"
printf '{"active_provider":"openai-codex"}\n' >"$HERMES_TEST_HERMES_AUTH"
chmod 600 "$HERMES_TEST_HERMES_AUTH"
FAKE
chmod +x "$fake_bin/script"

PATH="$fake_bin:$PATH" \
HERMES_TEST_DATA_DIR="$data_dir" \
HERMES_TEST_CODEX_AUTH="$codex_auth" \
HERMES_TEST_OWNER="$(id -un)" \
HERMES_TEST_GROUP="$(id -gn)" \
HERMES_TEST_AUTH_COMMAND_LOG="$auth_command_log" \
HERMES_TEST_AUTH_STDIN_LOG="$auth_stdin_log" \
HERMES_TEST_HERMES_AUTH="$data_dir/auth.json" \
ANSIBLE_ROLES_PATH="$repo_root/ansible/roles" \
  "${ansible_command[@]}" --inventory localhost, \
    "$repo_root/tests/fixtures/codex_auth_install.yml" >"$fixture_root/ansible.log" \
  || {
    sed -n '1,160p' "$fixture_root/ansible.log" >&2
    fail "Codex subscription auth installation playbook failed"
  }

installed_auth="$data_dir/.codex/auth.json"
runtime_env="$data_dir/.env"
[[ -f "$installed_auth" ]] \
  || fail "Codex subscription auth must be installed at HERMES_HOME/.codex/auth.json"
cmp -s "$codex_auth" "$installed_auth" \
  || fail "installed Codex auth must preserve the protected source exactly"
[[ "$(stat -f '%Lp' "$installed_auth" 2>/dev/null || stat -c '%a' "$installed_auth")" == "600" ]] \
  || fail "installed Codex auth must have mode 0600"
[[ -f "$runtime_env" ]] \
  || fail "the loopback API server must receive a generated runtime credential"
[[ "$(stat -f '%Lp' "$runtime_env" 2>/dev/null || stat -c '%a' "$runtime_env")" == "600" ]] \
  || fail "the runtime environment must have mode 0600"
[[ "$(grep -Ec '^API_SERVER_KEY=[0-9a-f]{64}$' "$runtime_env")" == "1" ]] \
  || fail "the runtime environment must contain exactly one strong API server key"
[[ "$(wc -l <"$auth_command_log" | tr -d ' ')" == "1" ]] \
  || fail "Codex CLI credentials must be imported into Hermes auth exactly once"
[[ "$(sed -n '3p' "$auth_stdin_log")" == "y" ]] \
  || fail "the guarded Codex CLI credential import must be explicitly accepted"
printf 'PASS Codex subscription auth is installed exactly with mode 0600\n'
