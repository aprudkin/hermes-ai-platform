#!/usr/bin/env bash
# No install, plugin discovery, live config, or speech API calls.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python="${PYTHON:-python3}"
for cmd in "$python" ffmpeg ffprobe; do
  command -v "$cmd" >/dev/null || { printf 'Required offline voice test command missing: %s\n' "$cmd" >&2; exit 1; }
done
if [[ -n "${HERMES_SRC:-}" && ! -f "$HERMES_SRC/agent/tts_provider.py" ]]; then
  printf 'HERMES_SRC must name a compatible Hermes checkout\n' >&2
  exit 1
fi
sandbox="$(mktemp -d)"
trap 'rm -rf "$sandbox"' EXIT
mkdir -p "$sandbox/home" "$sandbox/profile"
export HOME="$sandbox/home" HERMES_HOME="$sandbox/profile" XDG_CONFIG_HOME="$sandbox/home/.config"
unset HERMES_PROFILE DEEPGRAM_API_KEY DEEPGRAM_TTS_BASE_URL DEEPGRAM_STT_BASE_URL
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$root/extensions/deepgram-voice${HERMES_SRC:+:$HERMES_SRC}${PYTHONPATH:+:$PYTHONPATH}"
"$python" -c 'import pytest, requests, hermes_cli.config; from agent.tts_provider import TTSProvider; from agent.transcription_provider import TranscriptionProvider' || {
  printf 'Use an isolated test Python with pytest, requests, and Hermes contract dependencies; see extensions/deepgram-voice/README.md\n' >&2
  exit 1
}
cd "$root"
"$python" -m pytest -p no:cacheprovider -o addopts= "$root/extensions/deepgram-voice/tests" "$@"
