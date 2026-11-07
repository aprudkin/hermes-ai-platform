#!/bin/sh
# Preserved entry point only; no --enabled default and no schedule installation.
set -eu
exec "${PYTHON:-python3}" "$(dirname -- "$0")/cash_review_escalation_monitor.py" "$@"
