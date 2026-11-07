#!/usr/bin/env bash
# Local repository checks only. Never connect to or mutate a host.
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
mode="${1:---all}"
[[ "$#" -le 1 ]] || { printf 'Usage: scripts/validate.sh [--all|--local|--static|--structure|--secrets]\n' >&2; exit 2; }

error() { printf 'ERROR: %s\n' "$*" >&2; return 1; }

require_artifacts() {
  local path failed=0
  local required=(
    .gitignore .ai-archive/AGENTS.current.md README.md Taskfile.yml .github/workflows/validate.yml
    profiles/manager/SOUL.md docker/docker-compose.yml
    scripts/hermes_backup.sh scripts/hermes_backup_bundle.py scripts/hermes_backup_progress.py
    scripts/hermes_cloud_backup.py scripts/hermes_server_backup.py
    scripts/hermes_server_backup_entry.py scripts/install_server_backup.py scripts/hermes_upgrade.sh
    systemd/hermes-backup.service systemd/hermes-backup.timer
    docs/state-first.md docs/architecture.md docs/operations.md
    docs/personal-backup.md docs/backup-restore.md docs/cloud-backup.md docs/server-backup.md
    tests/run.sh
  )
  for path in "${required[@]}"; do
    if [[ ! -s "$repo_root/$path" ]]; then
      error "required artifact is missing or empty: $path" || true
      failed=1
    fi
  done
  [[ "$failed" == 0 ]] || return 1
  printf 'PASS repository structure\n'
}

need_command() {
  if ! command -v "$1" >/dev/null 2>&1 || ! "$1" --version >/dev/null 2>&1; then
    if [[ "$mode" == --local ]]; then
      printf 'SKIP %s (tool unavailable or not runnable)\n' "$1"
    else
      error "required command unavailable or not runnable: $1" || true
    fi
    return 1
  fi
}

validate_shell() {
  local file files=("$repo_root"/scripts/*.sh "$repo_root"/tests/*.sh)
  for file in "${files[@]}"; do
    bash -n "$file"
  done
  printf 'PASS bash syntax\n'
  if need_command shellcheck; then
    (cd "$repo_root" && shellcheck "${files[@]}")
    printf 'PASS ShellCheck\n'
  elif [[ "$mode" != --local ]]; then
    return 1
  fi
}

validate_python() {
  python3 - "$repo_root" <<'PY'
from pathlib import Path
import sys
root = Path(sys.argv[1])
for directory in ('scripts', 'tests'):
    for path in sorted((root / directory).glob('*.py')):
        compile(path.read_bytes(), str(path), 'exec')
PY
  printf 'PASS Python syntax (no execution)\n'
}

validate_compose() {
  if need_command docker && docker compose version >/dev/null 2>&1; then
    HERMES_DATA_DIR=/opt/hermes/data docker compose \
      --file "$repo_root/docker/docker-compose.yml" config --quiet
    printf 'PASS Docker Compose schema\n'
  elif [[ "$mode" == --local ]]; then
    printf 'SKIP Docker Compose schema (runnable Compose unavailable)\n'
  else
    error 'strict validation requires runnable docker compose'
  fi
}

validate_secrets() {
  command -v rg >/dev/null 2>&1 || { error 'secret scan requires ripgrep'; return 1; }
  local status pattern
  pattern='-----BEGIN (OPENSSH|RSA|EC) PRIVATE KEY-----|^[[:space:]]*(OPENROUTER_API_KEY|ANTHROPIC_API_KEY|OPENAI_API_KEY|TELEGRAM_BOT_TOKEN|DISCORD_BOT_TOKEN|SLACK_BOT_TOKEN|SLACK_APP_TOKEN|GITHUB_TOKEN|GH_TOKEN)=[^[:space:]#].*|gh[pousr]_[A-Za-z0-9_]{30,}|github_pat_[A-Za-z0-9_]{30,}|sk-ant-[A-Za-z0-9_-]{20,}|sk-(proj-)?[A-Za-z0-9_-]{20,}'
  if rg --quiet --hidden --no-ignore --glob '!.git/**' --glob '!.generated/**' \
      -- "$pattern" "$repo_root"; then
    error 'credential-shaped content found; values suppressed'
    return 1
  else
    status=$?
  fi
  [[ "$status" == 1 ]] || { error "secret scan failed (status $status)"; return 1; }
  printf 'PASS repository secret-pattern scan\n'
}

static_checks() {
  require_artifacts
  validate_shell
  validate_python
  validate_compose
  validate_secrets
}

case "$mode" in
  --structure) require_artifacts ;;
  --secrets) validate_secrets ;;
  --static) static_checks ;;
  --all|--local)
    static_checks
    if ! need_command task && [[ "$mode" != --local ]]; then exit 1; fi
    bash "$repo_root/tests/run.sh"
    printf 'PASS behavioral tests (inspect any explicit SKIP lines)\n'
    ;;
  *) printf 'Usage: scripts/validate.sh [--all|--local|--static|--structure|--secrets]\n' >&2; exit 2 ;;
esac
