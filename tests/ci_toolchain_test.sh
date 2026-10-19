#!/usr/bin/env bash
set -euo pipefail
if ! ansible-playbook --version >/dev/null 2>&1; then
  printf 'SKIP CI toolchain contract (Ansible/PyYAML environment unavailable)\n'
  exit 0
fi
python3 "$(dirname "${BASH_SOURCE[0]}")/ci_toolchain_test.py" -v
