#!/usr/bin/env bash

set -euo pipefail
# shellcheck source=tests/test_helper.sh
source "$(dirname "${BASH_SOURCE[0]}")/test_helper.sh"

grep -Eq 'apt-get install.*ripgrep' \
  "$repo_root/.github/workflows/validate.yml" || \
  fail "CI must install ripgrep before running the fail-closed secret scan"

printf 'PASS CI installs the validator secret-scan dependency\n'

grep -Fq \
  'not hermes_targeted_installation_paths.results[1].stat.exists or' \
  "$repo_root/ansible/telegram_gateway.yml" || \
  fail "targeted Telegram preflight must accept an absent runtime selector as default"

printf 'PASS targeted Telegram preflight accepts the legacy default runtime state\n'

if ! grep -Fq 'hermes_targeted_preflight_env_path' \
  "$repo_root/ansible/telegram_gateway.yml" || \
  ! grep -Fq "else '/dev/null'" \
    "$repo_root/ansible/telegram_gateway.yml"; then
  fail "targeted Compose preflight must use a read-only fallback when the runtime selector is absent"
fi

printf 'PASS targeted Compose preflight handles an absent runtime selector\n'

if ! grep -Fq 'hermes_targeted_pending_reconciliation_valid' \
  "$repo_root/ansible/telegram_gateway.yml" || \
  ! grep -Fq 'not hermes_targeted_pending_reconciliation_valid' \
    "$repo_root/ansible/telegram_gateway.yml"; then
  fail "targeted health preflight must permit only a validated pending reconciliation retry"
fi

printf 'PASS targeted health preflight permits validated pending reconciliation retries\n'

if [[ "${HERMES_VALIDATE_TEST_NO_RECURSE:-0}" == "1" ]]; then
  printf 'SKIP nested validator mode self-test\n'
  exit 0
fi

fixture_root="$(mktemp -d)"
trap 'rm -rf "$fixture_root"' EXIT
cp -R "$repo_root/." "$fixture_root/repo"

limited_bin="$fixture_root/limited-bin"
mkdir -p "$limited_bin"
ln -s "$(command -v rg)" "$limited_bin/rg"
for unavailable_command in shellcheck terraform ansible-playbook docker; do
  cat >"$limited_bin/$unavailable_command" <<'FAKE'
#!/usr/bin/env bash
exit 127
FAKE
  chmod +x "$limited_bin/$unavailable_command"
done
python_bin_dir="$(dirname "$(command -v python3)")"
limited_path="$limited_bin:$python_bin_dir:/usr/bin:/bin"

set +e
output="$(cd "$fixture_root/repo" && env \
  HERMES_VALIDATE_TEST_NO_RECURSE=1 PATH="$limited_path" \
  bash scripts/validate.sh --all 2>&1)"
status=$?
set -e

[[ "$status" -ne 0 ]] \
  || fail "strict --all validation must fail when a required tool is unavailable"
[[ "$output" == *"required command is not runnable: shellcheck"* ]] \
  || fail "strict --all validation must name the first missing required tool"
[[ "$output" != *"SKIP ShellCheck"* ]] \
  || fail "strict --all validation must not disguise missing required checks as skips"

set +e
output="$(cd "$fixture_root/repo" && env \
  HERMES_VALIDATE_TEST_NO_RECURSE=1 PATH="$limited_path" \
  bash scripts/validate.sh --local 2>&1)"
status=$?
set -e

[[ "$status" -eq 0 ]] \
  || fail "explicit --local validation must allow unavailable native tools: $output"
[[ "$output" == *"SKIP ShellCheck"* ]] \
  || fail "explicit --local validation must report skipped ShellCheck"
[[ "$output" == *"SKIP Terraform"* ]] \
  || fail "explicit --local validation must report skipped Terraform"
[[ "$output" == *"SKIP Ansible"* ]] \
  || fail "explicit --local validation must report skipped Ansible"
[[ "$output" == *"SKIP docker compose"* ]] \
  || fail "explicit --local validation must report skipped Compose"
printf 'PASS strict and opportunistic validation modes are explicit\n'

rm -f "$fixture_root/repo/terraform/main.tf"

set +e
output="$(cd "$fixture_root/repo" && bash scripts/validate.sh --structure 2>&1)"
status=$?
set -e

[[ "$status" -ne 0 ]] || fail "validation must fail when terraform/main.tf is missing"
[[ "$output" == *"terraform/main.tf"* ]] || fail "validation must name the missing artifact"

printf 'PASS validate rejects a missing required artifact\n'
cp "$repo_root/terraform/main.tf" "$fixture_root/repo/terraform/main.tf"

required_telegram_artifacts=(
  scripts/telegram_env.py
  ansible/telegram_gateway.yml
  ansible/telegram_verify.yml
  ansible/roles/hermes/tasks/validate_telegram.yml
  ansible/roles/hermes/tasks/telegram_gateway.yml
  tests/telegram_env_test.sh
  tests/compose_gateway_profile_test.sh
  tests/fixtures/telegram_gateway.yml
  tests/ansible_telegram_gateway_test.sh
  tests/ansible_telegram_verify_test.sh
  tests/validate_runtime_test.sh
)

for relative_path in "${required_telegram_artifacts[@]}"; do
  mv "$fixture_root/repo/$relative_path" "$fixture_root/repo/$relative_path.missing"
  set +e
  output="$(cd "$fixture_root/repo" && bash scripts/validate.sh --structure 2>&1)"
  status=$?
  set -e
  mv "$fixture_root/repo/$relative_path.missing" "$fixture_root/repo/$relative_path"

  [[ "$status" -ne 0 ]] || fail "validation must fail when $relative_path is missing"
  [[ "$output" == *"$relative_path"* ]] || fail "validation must name missing $relative_path"
done

printf 'PASS validate rejects every missing Telegram gateway artifact\n'

strict_bin="$fixture_root/strict-bin"
mkdir -p "$strict_bin"
ln -s "$(command -v rg)" "$strict_bin/rg"
ansible_log="$fixture_root/ansible.log"
compose_log="$fixture_root/compose.log"

cat >"$strict_bin/shellcheck" <<'FAKE'
#!/usr/bin/env bash
exit 0
FAKE
cat >"$strict_bin/terraform" <<'FAKE'
#!/usr/bin/env bash
exit 0
FAKE
cat >"$strict_bin/ansible-playbook" <<'FAKE'
#!/usr/bin/env bash
if [[ "${1:-}" != "--version" ]]; then
  printf '%s\n' "$*" >>"$HERMES_FAKE_ANSIBLE_LOG"
fi
FAKE
cat >"$strict_bin/ansible-lint" <<'FAKE'
#!/usr/bin/env bash
if [[ "${1:-}" != "--version" ]]; then
  printf 'lint %s\n' "$*" >>"$HERMES_FAKE_ANSIBLE_LOG"
fi
FAKE
cat >"$strict_bin/docker" <<'FAKE'
#!/usr/bin/env bash
if [[ "${1:-}" != "--version" ]]; then
  printf 'profile=%s args=%s\n' "${HERMES_GATEWAY_PROFILE-}" "$*" >>"$HERMES_FAKE_COMPOSE_LOG"
fi
FAKE
chmod +x \
  "$strict_bin/shellcheck" \
  "$strict_bin/terraform" \
  "$strict_bin/ansible-playbook" \
  "$strict_bin/ansible-lint" \
  "$strict_bin/docker"

strict_path="$strict_bin:/usr/bin:/bin"
set +e
output="$(cd "$fixture_root/repo" && env \
  HERMES_FAKE_ANSIBLE_LOG="$ansible_log" \
  HERMES_FAKE_COMPOSE_LOG="$compose_log" \
  PATH="$strict_path" bash scripts/validate.sh --static 2>&1)"
status=$?
set -e

[[ "$status" -eq 0 ]] || fail "strict static validation fixture must pass: $output"
grep -Fq 'ansible/site.yml' "$ansible_log" || fail "strict Ansible validation must name site.yml"
grep -Fq 'ansible/telegram_gateway.yml' "$ansible_log" \
  || fail "strict Ansible validation must name telegram_gateway.yml"
grep -Fq 'ansible/telegram_verify.yml' "$ansible_log" \
  || fail "strict Ansible validation must name telegram_verify.yml"
grep -Eq '^lint .*ansible/site\.yml.*ansible/telegram_gateway\.yml$' "$ansible_log" \
  || fail "strict ansible-lint must cover site.yml and telegram_gateway.yml"
grep -Fq 'profile=default args=compose' "$compose_log" \
  || fail "strict Compose validation must render the default gateway profile"
grep -Fq 'profile=manager args=compose' "$compose_log" \
  || fail "strict Compose validation must render the manager gateway profile"

printf 'PASS strict static gate covers targeted playbooks and both Compose profiles\n'

rg_error_bin="$fixture_root/rg-error-bin"
mkdir -p "$rg_error_bin"
cat >"$rg_error_bin/rg" <<'FAKE'
#!/usr/bin/env bash
exit 2
FAKE
chmod +x "$rg_error_bin/rg"
set +e
output="$(cd "$fixture_root/repo" && PATH="$rg_error_bin:$PATH" bash scripts/validate.sh --secrets 2>&1)"
status=$?
set -e

[[ "$status" -ne 0 ]] || fail "secret validation must fail when rg exits with a scan error"
[[ "$output" == *"secret scan failed"* ]] \
  || fail "secret validation must identify a scanner execution failure"
printf 'PASS validate rejects secret scanner errors\n'

rg_no_match_bin="$fixture_root/rg-no-match-bin"
mkdir -p "$rg_no_match_bin"
cat >"$rg_no_match_bin/rg" <<'FAKE'
#!/usr/bin/env bash
exit 1
FAKE
chmod +x "$rg_no_match_bin/rg"
set +e
output="$(cd "$fixture_root/repo" && PATH="$rg_no_match_bin:$PATH" bash scripts/validate.sh --secrets 2>&1)"
status=$?
set -e

[[ "$status" -eq 0 ]] || fail "secret validation must accept rg status 1 when no matches are found"
[[ "$output" == *"PASS repository secret-pattern scan"* ]] \
  || fail "secret validation must report success for an rg no-match result"
printf 'PASS validate accepts no-match scanner status\n'

set +e
output="$(cd "$fixture_root/repo" && bash scripts/validate.sh --secrets 2>&1)"
status=$?
set -e

[[ "$status" -eq 0 ]] \
  || fail "secret validation must allow the hermetic Task 4 token fixture only at its named path"

cp "$fixture_root/repo/tests/ansible_telegram_gateway_test.sh" \
  "$fixture_root/ansible_telegram_gateway_test.sh.different-token-safe"
printf 'TELEGRAM_BOT_TOKEN=%s:%s\n' '864209753' \
  'different_fixture_abcdefghijklmnop' \
  >>"$fixture_root/repo/tests/ansible_telegram_gateway_test.sh"
set +e
output="$(cd "$fixture_root/repo" && bash scripts/validate.sh --secrets 2>&1)"
status=$?
set -e
mv "$fixture_root/ansible_telegram_gateway_test.sh.different-token-safe" \
  "$fixture_root/repo/tests/ansible_telegram_gateway_test.sh"

[[ "$status" -ne 0 ]] \
  || fail "a different valid-looking token in the Task 4 test must fail the secret scan"

cp "$fixture_root/repo/tests/ansible_telegram_gateway_test.sh" \
  "$fixture_root/ansible_telegram_gateway_test.sh.safe"
printf 'TELEGRAM_BOT_TOKEN=%s:%s%s%s\n' '975310864' \
  'fixture_token_abcdefghijklmnop' '-----BEGIN ' 'RSA PRIVATE KEY-----' \
  >>"$fixture_root/repo/tests/ansible_telegram_gateway_test.sh"
set +e
output="$(cd "$fixture_root/repo" && bash scripts/validate.sh --secrets 2>&1)"
status=$?
set -e
mv "$fixture_root/ansible_telegram_gateway_test.sh.safe" \
  "$fixture_root/repo/tests/ansible_telegram_gateway_test.sh"

[[ "$status" -ne 0 ]] \
  || fail "the Task 4 token allowance must not hide another secret pattern on the same line"

{
  printf 'TELEGRAM_BOT_TOKEN=%s:%s\n' '975310864' 'not_allowed_outside_fixture'
} >"$fixture_root/repo/tests/token-outside-task4-fixture.env"
set +e
output="$(cd "$fixture_root/repo" && bash scripts/validate.sh --secrets 2>&1)"
status=$?
set -e

[[ "$status" -ne 0 ]] || fail "secret validation must reject a token-shaped value outside the Task 4 test"
[[ "$output" == *"credential"* ]] || fail "secret validation must explain the token-shaped failure"
rm -f "$fixture_root/repo/tests/token-outside-task4-fixture.env"

printf 'PASS token-shaped values are allowed only in the named hermetic Task 4 test\n'

printf 'HCLOUD_TOKEN=fixture-secret-value-that-must-not-pass\n' >"$fixture_root/repo/leaked.env"
set +e
output="$(cd "$fixture_root/repo" && bash scripts/validate.sh --secrets 2>&1)"
status=$?
set -e

[[ "$status" -ne 0 ]] || fail "secret validation must reject a populated HCLOUD_TOKEN"
[[ "$output" == *"credential"* ]] || fail "secret validation must explain the credential failure"

printf 'PASS validate rejects populated infrastructure credentials\n'
