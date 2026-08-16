#!/usr/bin/env bash

set -euo pipefail
# shellcheck source=tests/test_helper.sh
source "$(dirname "${BASH_SOURCE[0]}")/test_helper.sh"

grep -Eq 'apt-get install.*ripgrep' \
  "$repo_root/.github/workflows/validate.yml" || \
  fail "CI must install ripgrep before running the fail-closed secret scan"

printf 'PASS CI installs the validator secret-scan dependency\n'

fixture_root="$(mktemp -d)"
trap 'rm -rf "$fixture_root"' EXIT
cp -R "$repo_root/." "$fixture_root/repo"
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
