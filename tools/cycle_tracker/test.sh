#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
export PYTHONDONTWRITEBYTECODE=1
"${PYTHON:-python3}" -c 'import PIL, httpx, dotenv; from telegram.ext import CallbackQueryHandler'
"${PYTHON:-python3}" -W error "$root/tests/run_offline.py"
