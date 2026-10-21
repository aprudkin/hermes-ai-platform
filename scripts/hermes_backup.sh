#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
temporary_archive=''

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

require_var() {
  local name="$1"
  [[ -n "${!name:-}" ]] || fail "${name} must be set"
}

require_file() {
  local name="$1"
  require_var "$name"
  [[ -f "${!name}" ]] || fail "${name} must name an existing regular file"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"
}

resolve_deploy_host() {
  if [[ -n "${HERMES_DEPLOY_HOST:-}" ]]; then
    return
  fi

  # A plain backup uses the controller's SSH alias. Retain Terraform lookup
  # for callers that already supply deployment credentials but omit the host.
  if [[ -z "${HERMES_DEPLOY_SSH_USER:-}" && -z "${HERMES_DEPLOY_SSH_PRIVATE_KEY:-}" ]]; then
    HERMES_DEPLOY_HOST=hermes-minimal
    return
  fi

  require_command terraform
  HERMES_DEPLOY_HOST="$(terraform -chdir="$repo_root/terraform" output -raw server_ipv4)" \
    || fail "failed to resolve HERMES_DEPLOY_HOST from Terraform state"
  require_var HERMES_DEPLOY_HOST
}

main() {
  local backup_dir timestamp archive ssh_destination elapsed
  local started_seconds=$SECONDS
  local -a ssh_options=(-o BatchMode=yes -o StrictHostKeyChecking=accept-new)
  local scope=personal prefix=hermes-personal
  local guide="$repo_root/docs/personal-backup.md"
  local remote_command='python3 - capture /opt/hermes hermes personal'
  local description='Hermes personal-state backup'

  if [[ "$#" -eq 1 && "${1:-}" == --full ]]; then
    scope=full
    prefix=hermes-recovery
    guide="$repo_root/docs/backup-restore.md"
    remote_command='python3 - capture /opt/hermes hermes'
    description='portable Hermes recovery bundle'
  elif [[ "$#" -ne 0 ]]; then
    fail "usage: hermes_backup.sh [--full] (default: personal state)"
  fi

  umask 077
  require_command ssh
  require_command python3
  if [[ -n "${HERMES_DEPLOY_SSH_PRIVATE_KEY:-}" ]]; then
    require_file HERMES_DEPLOY_SSH_PRIVATE_KEY
    ssh_options+=(-i "$HERMES_DEPLOY_SSH_PRIVATE_KEY")
  fi
  resolve_deploy_host
  ssh_destination="$HERMES_DEPLOY_HOST"
  if [[ -n "${HERMES_DEPLOY_SSH_USER:-}" ]]; then
    ssh_destination="$HERMES_DEPLOY_SSH_USER@$ssh_destination"
  fi

  backup_dir="${HERMES_BACKUP_DIR:-$HOME/backup/hermer}"
  mkdir -p -- "$backup_dir"
  timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  archive="$backup_dir/$prefix-$timestamp-$$.tar.gz"
  temporary_archive="$(mktemp "$backup_dir/.$prefix-$timestamp.XXXXXX")"
  trap 'if [[ -n "${temporary_archive:-}" ]]; then rm -f -- "$temporary_archive"; fi' EXIT

  printf 'Creating %s at %s\n' "$description" "$archive"
  # remote_command is selected from fixed literals above, not remote variables.
  # shellcheck disable=SC2029
  python3 "$repo_root/scripts/hermes_backup_bundle.py" program "$guide" | ssh \
    "${ssh_options[@]}" "$ssh_destination" \
    "$remote_command" | python3 "$repo_root/scripts/hermes_backup_progress.py" \
      receive "$((SECONDS - started_seconds))" >"$temporary_archive"

  [[ -s "$temporary_archive" ]] || fail "remote backup archive is empty"
  python3 "$repo_root/scripts/hermes_backup_progress.py" verify "$temporary_archive" "$scope" \
    "$((SECONDS - started_seconds))"
  mv -- "$temporary_archive" "$archive"
  elapsed=$((SECONDS - started_seconds))
  printf 'Backup verified: %s (elapsed %02d:%02d:%02d)\n' "$archive" \
    "$((elapsed / 3600))" "$((elapsed / 60 % 60))" "$((elapsed % 60))"
}

main "$@"
