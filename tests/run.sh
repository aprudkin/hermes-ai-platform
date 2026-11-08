#!/usr/bin/env bash

set -euo pipefail

tests_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

# Update commands invoke validation with private routing/review variables set.
# Keep test-source dependencies, never operational settings or a live profile.
for variable in ${!HERMES_@}; do
  case "$variable" in
    HERMES_SRC|HERMES_SOURCE_ROOT) ;;
    *) unset "$variable" ;;
  esac
done
unset CONFIRM_PUSH CONFIRM_DEPLOY
test_home="$(mktemp -d)"
trap 'rm -rf -- "$test_home"' EXIT
export HERMES_HOME="$test_home"

for test_file in "$tests_dir"/*_test.sh; do
  bash "$test_file"
done
