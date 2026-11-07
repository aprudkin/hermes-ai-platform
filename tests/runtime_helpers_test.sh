#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
"${PYTHON:-python3}" "$root/tests/runtime_helpers_test.py"
