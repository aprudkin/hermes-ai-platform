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
  printf 'SKIP Hermes directory ownership (runnable ansible-playbook unavailable)\n'
  exit 0
fi

fixture_root="$(mktemp -d)"
trap 'rm -rf "$fixture_root"' EXIT
app_dir="$fixture_root/app"
data_dir="$fixture_root/data"
owner="$(id -un)"
group="$(id -gn)"

file_identity_and_mode() {
  local target_path="$1"
  stat -c '%U:%G:%a' "$target_path" 2>/dev/null \
    || stat -f '%Su:%Sg:%Lp' "$target_path"
}

HERMES_TEST_APP_DIR="$app_dir" \
HERMES_TEST_DATA_DIR="$data_dir" \
HERMES_TEST_OWNER="$owner" \
HERMES_TEST_GROUP="$group" \
ANSIBLE_ROLES_PATH="$repo_root/ansible/roles" \
  "${ansible_command[@]}" --inventory localhost, \
    "$repo_root/tests/fixtures/hermes_directories.yml" >/dev/null

[[ "$(file_identity_and_mode "$app_dir")" == "$owner:$group:750" ]] \
  || fail "the application directory must retain controller-owned test identity and mode 0750"
[[ "$(file_identity_and_mode "$data_dir")" == "$owner:$group:750" ]] \
  || fail "the data mount root must belong to the Hermes runtime identity with mode 0750"
printf 'PASS Hermes data mount root is traversable by the runtime identity\n'
