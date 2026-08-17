#!/usr/bin/env bash

set -euo pipefail
# shellcheck source=tests/test_helper.sh
source "$(dirname "${BASH_SOURCE[0]}")/test_helper.sh"

fixture_root="$(mktemp -d)"
trap 'rm -rf "$fixture_root"' EXIT
fake_bin="$fixture_root/bin"
mkdir -p "$fake_bin"

command_log="$fixture_root/commands.log"
public_key="$fixture_root/luk.pub"
private_key="$fixture_root/luk"
provider_env="$fixture_root/hermes.env"
codex_auth="$fixture_root/codex-auth.json"

printf 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestFixtureOnly hermes-test\n' >"$public_key"
: >"$private_key"
printf 'OPENROUTER_API_KEY=test-only-provider-value\n' >"$provider_env"
printf '{"tokens":{"access_token":"fixture-access","refresh_token":"fixture-refresh"}}\n' >"$codex_auth"
chmod 600 "$provider_env"
chmod 600 "$codex_auth"

cat >"$fake_bin/terraform" <<'FAKE'
#!/usr/bin/env bash
printf 'terraform %s\n' "$*" >>"$COMMAND_LOG"

case " $* " in
  *' output -raw server_ipv4 '*)
    if [[ "${FAIL_TERRAFORM_OUTPUT:-0}" == "1" ]]; then
      printf 'fixture Terraform output failure\n' >&2
      exit 31
    fi
    printf '192.0.2.55\n'
    ;;
esac
FAKE

cat >"$fake_bin/ansible-playbook" <<'FAKE'
#!/usr/bin/env bash
printf 'ansible %s\n' "$*" >>"$COMMAND_LOG"

case " $* " in
  *'/ansible/site.yml '*)
    if [[ "${FAIL_ANSIBLE:-0}" == "1" ]]; then
      printf 'fixture Ansible failure\n' >&2
      exit 41
    fi
    ;;
  *'/ansible/verify.yml'*)
    if [[ "${FAIL_RUNTIME:-0}" == "1" ]]; then
      printf 'fixture runtime verification failure\n' >&2
      exit 42
    fi
    ;;
esac
FAKE

cat >"$fake_bin/stat" <<'FAKE'
#!/usr/bin/env bash
case "${1:-}" in
  -c)
    printf '600\n'
    ;;
  -f)
    printf 'File: fixture\nID: fixture Namelen: 255 Type: ext2/ext3\n'
    ;;
  *)
    exit 2
    ;;
esac
FAKE

chmod +x "$fake_bin/terraform" "$fake_bin/ansible-playbook" "$fake_bin/stat"

run_installer() {
  local output_path="$1"
  shift
  env HCLOUD_TOKEN="test-only-token" PATH="$fake_bin:$PATH" \
    COMMAND_LOG="$command_log" "$@" >"$output_path" 2>&1
}

assert_log_order() {
  local previous=0
  local pattern
  local line
  for pattern in "$@"; do
    line="$(grep -n -m1 -- "$pattern" "$command_log" | cut -d: -f1 || true)"
    [[ -n "$line" ]] || fail "command log is missing: $pattern"
    [[ "$line" -gt "$previous" ]] || fail "command is out of order: $pattern"
    previous="$line"
  done
}

assert_command_counts() {
  local expected_terraform="$1"
  local expected_ansible="$2"
  local actual_terraform
  local actual_ansible

  actual_terraform="$(grep -c '^terraform ' "$command_log" || true)"
  actual_ansible="$(grep -c '^ansible ' "$command_log" || true)"
  [[ "$actual_terraform" -eq "$expected_terraform" ]] \
    || fail "expected $expected_terraform Terraform commands, got $actual_terraform"
  [[ "$actual_ansible" -eq "$expected_ansible" ]] \
    || fail "expected $expected_ansible Ansible commands, got $actual_ansible"
  ! grep -Eq '^terraform .* destroy([[:space:]]|$)' "$command_log" \
    || fail "deploy failure handling must never invoke Terraform destroy"
}

assert_failure_report() {
  local output_path="$1"
  local failed_phase="$2"
  local last_completed_phase="$3"

  grep -q "Failed phase: $failed_phase" "$output_path" \
    || fail "failure must identify phase $failed_phase"
  grep -q "Last completed phase: $last_completed_phase" "$output_path" \
    || fail "failure must identify last completed phase $last_completed_phase"
  grep -q 'Safe resume:' "$output_path" \
    || fail "failure must provide a safe resume step"
  ! grep -qi 'destroy' "$output_path" \
    || fail "failure handling must not suggest automatic Terraform destroy"
  ! grep -q 'Hermes Minimal deployment verified successfully.' "$output_path" \
    || fail "failure must not print the deployment success message"
}

: >"$command_log"
run_installer "$fixture_root/new-success.out" \
  "$repo_root/installer/install.sh" deploy new --location hel1 --server-type cx23 \
    --hcloud-ssh-key-name Luk --ssh-public-key "$public_key" \
    --ssh-private-key "$private_key" --ssh-source-cidr 192.0.2.10/32 \
    --hermes-env "$provider_env" --model-provider openrouter \
    --model test/model --confirm-external-mutation

assert_log_order \
  'terraform -chdir=.* init ' \
  'terraform -chdir=.* validate' \
  'terraform -chdir=.* plan ' \
  'terraform -chdir=.* apply ' \
  'terraform -chdir=.* output -raw server_ipv4' \
  'ansible .*ansible/site.yml ' \
  'ansible .*ansible/verify.yml'
assert_command_counts 5 2
grep -q 'Hermes Minimal deployment verified successfully.' "$fixture_root/new-success.out" \
  || fail "confirmed new-host deploy must report success after runtime verification"
printf 'PASS confirmed new-host deploy runs every phase in order\n'

: >"$command_log"
run_installer "$fixture_root/existing-success.out" \
  "$repo_root/installer/install.sh" deploy existing \
    --host 192.0.2.44 --ssh-user ubuntu --ssh-private-key "$private_key" \
    --ssh-source-cidr 192.0.2.10/32 --hermes-env "$provider_env" \
    --model-provider openrouter --model test/model \
    --confirm-external-mutation

assert_log_order \
  'ansible .*ansible/site.yml ' \
  'ansible .*ansible/verify.yml'
assert_command_counts 0 2
grep -q 'Hermes Minimal deployment verified successfully.' "$fixture_root/existing-success.out" \
  || fail "confirmed existing-host deploy must report success after runtime verification"
printf 'PASS confirmed existing-host deploy runs configure and verify phases in order\n'

: >"$command_log"
run_installer "$fixture_root/codex-subscription-success.out" \
  "$repo_root/installer/install.sh" deploy existing \
    --host 192.0.2.44 --ssh-user ubuntu --ssh-private-key "$private_key" \
    --ssh-source-cidr 192.0.2.10/32 --codex-auth "$codex_auth" \
    --model-provider openai-codex --model gpt-5.4 \
    --confirm-external-mutation

assert_log_order \
  'ansible .*ansible/site.yml .*hermes_codex_auth_source=' \
  'ansible .*ansible/verify.yml'
assert_command_counts 0 2
! grep -q 'hermes_env_source=' "$command_log" \
  || fail "Codex subscription deployment must not pass an API-key env file"
grep -q 'Hermes Minimal deployment verified successfully.' \
  "$fixture_root/codex-subscription-success.out" \
  || fail "Codex subscription deploy must report success after runtime verification"
printf 'PASS Codex subscription deploy passes protected OAuth auth without an API-key env\n'

: >"$command_log"
set +e
run_installer "$fixture_root/codex-subscription-missing-auth.out" \
  "$repo_root/installer/install.sh" deploy existing \
    --host 192.0.2.44 --ssh-user ubuntu --ssh-private-key "$private_key" \
    --ssh-source-cidr 192.0.2.10/32 \
    --model-provider openai-codex --model gpt-5.4 \
    --confirm-external-mutation
codex_missing_auth_rc=$?
set -e

[[ "$codex_missing_auth_rc" -ne 0 ]] \
  || fail "Codex subscription deploy must require an explicit auth file"
[[ ! -s "$command_log" ]] \
  || fail "missing Codex auth must fail before Ansible"
grep -q -- '--codex-auth is required for openai-codex' \
  "$fixture_root/codex-subscription-missing-auth.out" \
  || fail "missing Codex auth failure must identify --codex-auth"
printf 'PASS Codex subscription deploy fails before external tools without auth\n'

: >"$command_log"
set +e
FAIL_TERRAFORM_OUTPUT=1 run_installer "$fixture_root/terraform-output-failure.out" \
  "$repo_root/installer/install.sh" deploy new --location hel1 --server-type cx23 \
    --hcloud-ssh-key-name Luk --ssh-public-key "$public_key" \
    --ssh-private-key "$private_key" --ssh-source-cidr 192.0.2.10/32 \
    --hermes-env "$provider_env" --model-provider openrouter \
    --model test/model --confirm-external-mutation
status=$?
set -e

[[ "$status" -eq 31 ]] || fail "Terraform output failure must propagate status 31, got $status"
grep -q 'terraform .* apply ' "$command_log" \
  || fail "Terraform output failure fixture must run after apply"
assert_command_counts 5 0
assert_failure_report "$fixture_root/terraform-output-failure.out" \
  "resolve-target" "provision"
printf 'PASS Terraform output failure stops deployment and reports safe resume\n'

: >"$command_log"
set +e
FAIL_ANSIBLE=1 run_installer "$fixture_root/ansible-failure.out" \
  "$repo_root/installer/install.sh" deploy existing \
    --host 192.0.2.44 --ssh-user ubuntu --ssh-private-key "$private_key" \
    --ssh-source-cidr 192.0.2.10/32 --hermes-env "$provider_env" \
    --model-provider openrouter --model test/model \
    --confirm-external-mutation
status=$?
set -e

[[ "$status" -eq 41 ]] || fail "Ansible failure must propagate status 41, got $status"
grep -q 'ansible .*ansible/site.yml ' "$command_log" \
  || fail "Ansible failure fixture must reach configuration"
! grep -q 'ansible .*ansible/verify.yml' "$command_log" \
  || fail "Ansible failure must stop before runtime verification"
assert_command_counts 0 1
assert_failure_report "$fixture_root/ansible-failure.out" \
  "configure" "inventory"
printf 'PASS Ansible failure stops deployment and reports safe resume\n'

: >"$command_log"
set +e
FAIL_RUNTIME=1 run_installer "$fixture_root/runtime-failure.out" \
  "$repo_root/installer/install.sh" deploy existing \
    --host 192.0.2.44 --ssh-user ubuntu --ssh-private-key "$private_key" \
    --ssh-source-cidr 192.0.2.10/32 --hermes-env "$provider_env" \
    --model-provider openrouter --model test/model \
    --confirm-external-mutation
status=$?
set -e

[[ "$status" -eq 42 ]] || fail "runtime failure must propagate status 42, got $status"
assert_log_order \
  'ansible .*ansible/site.yml ' \
  'ansible .*ansible/verify.yml'
assert_command_counts 0 2
assert_failure_report "$fixture_root/runtime-failure.out" \
  "verify" "configure"
printf 'PASS runtime failure suppresses success and reports safe resume\n'
