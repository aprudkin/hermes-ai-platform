#!/usr/bin/env bash

set -euo pipefail
# shellcheck source=tests/test_helper.sh
source "$(dirname "${BASH_SOURCE[0]}")/test_helper.sh"

grep -Eq 'apt-get install.*ripgrep' \
  "$repo_root/.github/workflows/validate.yml" || \
  fail "CI must install ripgrep before running the fail-closed secret scan"

printf 'PASS CI installs the validator secret-scan dependency\n'

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
limited_path="$limited_bin:/usr/bin:/bin"

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
  || fail "explicit --local validation must allow unavailable native tools"
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

printf 'HCLOUD_TOKEN=fixture-secret-value-that-must-not-pass\n' >"$fixture_root/repo/leaked.env"
set +e
output="$(cd "$fixture_root/repo" && bash scripts/validate.sh --secrets 2>&1)"
status=$?
set -e

[[ "$status" -ne 0 ]] || fail "secret validation must reject a populated HCLOUD_TOKEN"
[[ "$output" == *"credential"* ]] || fail "secret validation must explain the credential failure"

printf 'PASS validate rejects populated infrastructure credentials\n'
