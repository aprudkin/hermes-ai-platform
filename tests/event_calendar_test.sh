#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
export PYTHONDONTWRITEBYTECODE=1
"${PYTHON:-python3}" -c 'import PIL'
"${PYTHON:-python3}" -W error -m unittest discover -s "$repo_root/tests" -p 'event_calendar_test.py' -v
