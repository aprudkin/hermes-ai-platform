#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
export PYTHONDONTWRITEBYTECODE=1
"${PYTHON:-python3}" -c 'import dotenv'  # Existing runtime dependency for protected env files.
"${PYTHON:-python3}" -W error -m unittest discover -s "$repo_root/tests" -p 'mail_event*_test.py' -v
