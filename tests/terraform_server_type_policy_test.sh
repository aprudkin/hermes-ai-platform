#!/usr/bin/env bash

set -euo pipefail
# shellcheck source=tests/test_helper.sh
source "$(dirname "${BASH_SOURCE[0]}")/test_helper.sh"

if ! terraform version >/dev/null 2>&1; then
  printf 'SKIP Terraform server-type category policy (runnable terraform unavailable)\n'
  exit 0
fi

test_output="$(mktemp)"
trap 'rm -f "$test_output"' EXIT

set +e
terraform -chdir="$repo_root/terraform" test \
  -filter=tests/server_type_category.tftest.hcl -no-color >"$test_output" 2>&1
test_rc=$?
set -e

# Terraform mocks cannot create an instance in the provider's computed
# locations list, so that independent location guard is expected to fail.
[[ "$test_rc" -ne 0 ]] || fail "the provider location mock must retain its expected fail-closed guard"
grep -q 'selected server_type must be available, recommended, and not deprecated' "$test_output" \
  || fail "the expected provider location guard did not run"
! grep -q "cost_optimized category" "$test_output" \
  || fail "a recommended regular-performance type must not be rejected by category"
printf 'PASS recommended regular-performance types pass the shared-resource category policy\n'
