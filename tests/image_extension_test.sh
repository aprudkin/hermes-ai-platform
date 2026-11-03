#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
sandbox="$(mktemp -d)"
trap 'rm -rf "$sandbox"' EXIT
export HOME="$sandbox/home" HERMES_HOME="$sandbox/profile" PYTHONDONTWRITEBYTECODE=1
mkdir -p "$HOME" "$HERMES_HOME"
"${PYTHON:-python3}" "$root/tests/image_extension_test.py"
