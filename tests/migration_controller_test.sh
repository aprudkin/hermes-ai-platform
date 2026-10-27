#!/usr/bin/env bash
# Local fixtures only: no SSH, Docker daemon, Telegram or real capture.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
python3 "$root/tests/migration_controller_test.py"
python3 "$root/tests/migration_plan_b_test.py"
