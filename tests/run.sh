#!/usr/bin/env bash

set -euo pipefail

tests_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

for test_file in "$tests_dir"/*_test.sh; do
  bash "$test_file"
done
