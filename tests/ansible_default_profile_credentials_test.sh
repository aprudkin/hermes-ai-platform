#!/usr/bin/env bash

set -euo pipefail
# shellcheck source=tests/test_helper.sh
# shellcheck disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/test_helper.sh"

ansible_command=()
if ansible-playbook --version >/dev/null 2>&1; then
  ansible_command=(ansible-playbook)
elif [[ "${HERMES_TEST_ALLOW_UVX:-0}" == "1" ]] \
  && command -v uvx >/dev/null 2>&1; then
  ansible_command=(uvx --from 'ansible-core>=2.18,<2.20' ansible-playbook)
else
  printf 'SKIP default profile credentials (runnable ansible-playbook unavailable)\n'
  exit 0
fi

fixture_root="$(mktemp -d)"
trap 'rm -rf "$fixture_root"' EXIT
data_dir="$fixture_root/data"
provider_env="$fixture_root/provider.env"
ansible_log="$fixture_root/ansible.log"
# shellcheck disable=SC2154
fixture_file="$repo_root/tests/fixtures/default_profile_credentials.yml"
roles_path="$repo_root/ansible/roles"
mkdir -p "$data_dir"
printf 'OPENROUTER_API_KEY=fixture-provider-secret\n' >"$provider_env"
chmod 600 "$provider_env"

HERMES_TEST_DATA_DIR="$data_dir" \
HERMES_TEST_PROVIDER_ENV="$provider_env" \
HERMES_TEST_OWNER="$(id -un)" \
HERMES_TEST_GROUP="$(id -gn)" \
ANSIBLE_ROLES_PATH="$roles_path" \
  "${ansible_command[@]}" --inventory localhost, \
    "$fixture_file" >"$ansible_log" \
  || {
    sed -n '1,160p' "$ansible_log" >&2
    fail "default profile credential installation playbook failed"
  }

profile_env="$data_dir/profiles/default/.env"
named_profile_env="$data_dir/profiles/manager/.env"
runtime_env="$data_dir/.env"
[[ -f "$profile_env" ]] \
  || fail "the selected API provider credential must be installed for the default profile"
cmp -s "$provider_env" "$profile_env" \
  || fail "the default profile must receive the exact provider credential source"
[[ "$(stat -c '%a' "$profile_env" 2>/dev/null || stat -f '%Lp' "$profile_env")" == "600" ]] \
  || fail "the default profile provider credential must have mode 0600"
[[ -f "$runtime_env" ]] \
  || fail "the loopback API server credential must remain installed separately"
[[ "$(grep -Ec '^API_SERVER_KEY=[0-9a-f]{64}$' "$runtime_env")" == "1" ]] \
  || fail "the loopback API server credential must remain intact"
[[ "$(grep -Fxc 'OPENROUTER_API_KEY=fixture-provider-secret' "$profile_env")" == "1" ]] \
  || fail "the default profile must retain its provider credential"
[[ "$(grep -Ec '^API_SERVER_KEY=' "$profile_env" || true)" == "0" ]] \
  || fail "the loopback API server credential must not be mixed into the profile credential file"
[[ "$(grep -Ec '^OPENROUTER_API_KEY=' "$runtime_env" || true)" == "0" ]] \
  || fail "the provider credential must not replace the loopback API server environment"
[[ "$(grep -Ec '^API_SERVER_KEY=' "$runtime_env")" == "1" ]] \
  || fail "the loopback API server credential must appear exactly once"
[[ "$(grep -Ec '^OPENROUTER_API_KEY=' "$profile_env")" == "1" ]] \
  || fail "the default profile must contain exactly one provider credential"
[[ -f "$named_profile_env" ]] \
  || fail "the selected API provider credential must remain installed for named profiles"
cmp -s "$provider_env" "$named_profile_env" \
  || fail "named profiles must receive the exact provider credential source"
[[ "$(stat -c '%a' "$named_profile_env" 2>/dev/null || stat -f '%Lp' "$named_profile_env")" == "600" ]] \
  || fail "named-profile provider credentials must have mode 0600"
printf 'PASS API provider credentials are installed for default and named profiles without replacing the API server key\n'
