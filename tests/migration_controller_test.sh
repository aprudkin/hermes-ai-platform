#!/usr/bin/env bash
# Local fixtures only: no SSH, Docker daemon or Telegram; real fixture captures.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
python3 "$root/tests/migration_controller_test.py"
python3 "$root/tests/migration_safety_regression_test.py"
python3 "$root/tests/migration_sigkill_test.py"
python3 "$root/tests/migration_plan_b_test.py"
python3 "$root/tests/migration_cold_capture_test.py"
python3 "$root/tests/migration_host_test.py"
python3 "$root/tests/migration_notice_test.py"
