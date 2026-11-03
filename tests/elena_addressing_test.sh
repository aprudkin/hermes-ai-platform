#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
export HERMES_SOURCE_ROOT="${HERMES_SOURCE_ROOT:-${HERMES_SRC:?Set HERMES_SRC to the reviewed Hermes checkout}}"
bash "$root/extensions/elena-addressing/test.sh"
