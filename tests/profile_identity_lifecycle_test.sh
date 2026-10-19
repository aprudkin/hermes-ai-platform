#!/usr/bin/env bash
set -euo pipefail

if ! ansible-playbook --version >/dev/null 2>&1; then
  printf 'SKIP profile identity lifecycle (runnable ansible-playbook unavailable)\n'
  exit 0
fi

python3 "$(dirname "${BASH_SOURCE[0]}")/profile_identity_lifecycle_test.py" -v
