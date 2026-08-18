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
  printf 'SKIP root credential hardening (runnable ansible-playbook unavailable)\n'
  exit 0
fi

fixture_root="$(mktemp -d)"
trap 'rm -rf "$fixture_root"' EXIT
root_home="$fixture_root/root"
public_key="$fixture_root/root-admin.pub"
invalid_key="$fixture_root/multiple.pub"
owner="$(id -un)"
group="$(id -gn)"
first_log="$fixture_root/first.log"
second_log="$fixture_root/second.log"
legacy_authorization='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestFixtureOnly previous-comment'
backup_file="$root_home/.ssh/authorized_keys.pre-hermes-hardening"

printf 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestFixtureOnly ignored-comment\n' >"$public_key"
printf '%s\n%s\n' \
  'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestFixtureOnly first' \
  'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAnotherFixtureOnly second' \
  >"$invalid_key"
mkdir -p "$root_home/.ssh"
printf '%s\n' "$legacy_authorization" >"$root_home/.ssh/authorized_keys"

run_fixture() {
  local key_source="$1"
  local output_path="$2"
  HERMES_TEST_ROOT_HOME="$root_home" \
  HERMES_TEST_PUBLIC_KEY="$key_source" \
  HERMES_TEST_OWNER="$owner" \
  HERMES_TEST_GROUP="$group" \
  ANSIBLE_ROLES_PATH="$repo_root/ansible/roles" \
    "${ansible_command[@]}" --inventory localhost, \
      "$repo_root/tests/fixtures/root_credential_hardening.yml" >"$output_path"
}

run_fixture "$public_key" "$first_log"

expected='restrict ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestFixtureOnly'
[[ "$(cat "$root_home/.ssh/authorized_keys")" == "$expected" ]] \
  || fail "managed authorization must contain exactly one restricted key without its comment"

file_mode() {
  stat -c '%a' "$1" 2>/dev/null || stat -f '%Lp' "$1"
}

[[ "$(file_mode "$root_home/.ssh")" == "700" ]] \
  || fail "managed root SSH directory must use mode 0700"
[[ "$(file_mode "$root_home/.ssh/authorized_keys")" == "600" ]] \
  || fail "managed root authorization file must use mode 0600"
[[ "$(cat "$backup_file")" == "$legacy_authorization" ]] \
  || fail "the first hardening run must preserve the previous authorization exactly"
[[ "$(file_mode "$backup_file")" == "600" ]] \
  || fail "the preserved authorization must use mode 0600"

run_fixture "$public_key" "$second_log"
grep -Eq 'changed=0[[:space:]]' "$second_log" \
  || fail "a second root credential hardening run must be idempotent"
[[ "$(cat "$backup_file")" == "$legacy_authorization" ]] \
  || fail "later hardening runs must not overwrite the original authorization backup"

rm -f "$root_home/.ssh/authorized_keys"
set +e
run_fixture "$invalid_key" "$fixture_root/invalid.log"
invalid_status=$?
set -e
[[ "$invalid_status" -ne 0 ]] \
  || fail "multiple public-key records must fail closed"
[[ ! -e "$root_home/.ssh/authorized_keys" ]] \
  || fail "invalid public-key input must fail before writing authorization"

root_playbook="$repo_root/ansible/root_hardening.yml"
base_tasks="$repo_root/ansible/roles/base/tasks/main.yml"
preflight_line="$(grep -n -m1 'Validate SSH before root credential mutation' "$root_playbook" | cut -d: -f1 || true)"
credential_line="$(grep -n -m1 'Apply the production root credential controls' "$root_playbook" | cut -d: -f1 || true)"
postcheck_line="$(grep -n -m1 'Validate SSH after root credential mutation' "$root_playbook" | cut -d: -f1 || true)"
[[ -n "$preflight_line" && -n "$credential_line" && -n "$postcheck_line" ]] \
  || fail "the targeted play must define SSH preflight, credential mutation, and SSH postcheck"
[[ "$preflight_line" -lt "$credential_line" && "$credential_line" -lt "$postcheck_line" ]] \
  || fail "the targeted play must validate SSH before and after credential mutation"

flush_line="$(grep -n -m1 'Flush validated SSH configuration before root credential changes' "$base_tasks" | cut -d: -f1 || true)"
base_preflight_line="$(grep -n -m1 'Validate SSH before enforcing root credentials' "$base_tasks" | cut -d: -f1 || true)"
base_credential_line="$(grep -n -m1 'Enforce the root credential lifecycle' "$base_tasks" | cut -d: -f1 || true)"
[[ -n "$flush_line" && -n "$base_preflight_line" && -n "$base_credential_line" ]] \
  || fail "the base role must flush handlers and define an SSH preflight before credential mutation"
[[ "$flush_line" -lt "$base_preflight_line" && "$base_preflight_line" -lt "$base_credential_line" ]] \
  || fail "the base role must validate the effective SSH configuration before credential mutation"

printf 'PASS root credential hardening restricts one key and is idempotent\n'
