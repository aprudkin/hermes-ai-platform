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
  printf 'SKIP profile identity verification (runnable ansible-playbook unavailable)\n'
  exit 0
fi

fixture_root="$(mktemp -d)"
trap 'rm -rf "$fixture_root"' EXIT
data_dir="$fixture_root/data"
mkdir -p "$data_dir/profiles"

for profile_name in manager devops coding research; do
  mkdir -p "$data_dir/profiles/$profile_name"
  cp "$repo_root/profiles/$profile_name/SOUL.md" \
    "$data_dir/profiles/$profile_name/SOUL.md"
done

HERMES_TEST_DATA_DIR="$data_dir" \
HERMES_TEST_PROFILE_SOURCE_DIR="$repo_root/profiles" \
  "${ansible_command[@]}" --inventory localhost, \
    "$repo_root/tests/fixtures/profile_identity_verification.yml" >/dev/null

printf 'PASS profile identity verification preserves trailing newlines exactly\n'
