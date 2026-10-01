#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
compose_file="$repo_root/docker/docker-compose.yml"

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

  require_command terraform
  HERMES_DEPLOY_HOST="$(terraform -chdir="$repo_root/terraform" output -raw server_ipv4)" \
    || fail "failed to resolve HERMES_DEPLOY_HOST from Terraform state"
  require_var HERMES_DEPLOY_HOST
}


require_backup_configuration() {
  require_var HERMES_DEPLOY_HOST
  require_var HERMES_DEPLOY_SSH_USER
  require_file HERMES_DEPLOY_SSH_PRIVATE_KEY
}

backup_runtime_data() {
  local backup_dir="${HERMES_BACKUP_DIR:-$HOME/backup/hermer}"
  local timestamp temporary_archive archive

  mkdir -p -- "$backup_dir"
  timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  archive="$backup_dir/hermes-data-$timestamp.tar.gz"
  temporary_archive="$(mktemp "$backup_dir/.hermes-data-$timestamp.XXXXXX")"
  trap 'rm -f -- "$temporary_archive"' RETURN

  printf 'Creating consistent backup at %s\n' "$archive"
  ssh \
    -i "$HERMES_DEPLOY_SSH_PRIVATE_KEY" \
    -o BatchMode=yes \
    -o StrictHostKeyChecking=accept-new \
    "$HERMES_DEPLOY_SSH_USER@$HERMES_DEPLOY_HOST" \
    'bash -s' >"$temporary_archive" <<'REMOTE_BACKUP'
set -euo pipefail

docker inspect --format '{{.State.Running}}' hermes | grep -qx true
docker pause hermes >&2
cleanup() {
  local status=$?
  docker unpause hermes >&2 || status=$?
  exit "$status"
}
trap cleanup EXIT
tar --numeric-owner --xattrs --acls -C /opt/hermes -czf - data
REMOTE_BACKUP

  [[ -s "$temporary_archive" ]] || fail "remote backup archive is empty"
  gzip --test "$temporary_archive"
  tar --list --gzip --file "$temporary_archive" >/dev/null
  mv -- "$temporary_archive" "$archive"
  trap - RETURN
  printf 'Backup verified: %s\n' "$archive"
}

read_pinned_tag() {
  local -a tags=()
  mapfile -t tags < <(
    sed -nE \
      's#^[[:space:]]*image:[[:space:]]*nousresearch/hermes-agent:([^[:space:]#]+)[[:space:]]*$#\1#p' \
      "$compose_file"
  )
  [[ "${#tags[@]}" -eq 1 ]] \
    || fail "expected exactly one Hermes image pin in $compose_file"
  printf '%s\n' "${tags[0]}"
}

read_latest_tag() {
  local latest_tag
  latest_tag="$(gh api repos/NousResearch/hermes-agent/releases/latest --jq .tag_name)"
  [[ "$latest_tag" =~ ^[A-Za-z0-9._-]+$ ]] \
    || fail "upstream returned an unsafe release tag"
  printf '%s\n' "$latest_tag"
}

verify_compatibility_review() {
  local latest_tag="$1"
  local review_file="${HERMES_UPGRADE_REVIEW_FILE:-}"

  [[ -n "$review_file" && -f "$review_file" ]] \
    || fail "HERMES_UPGRADE_REVIEW_FILE must name a compatibility review JSON file"

  python3 - "$review_file" "$repo_root" "$latest_tag" <<'PYTHON' \
    || fail "compatibility review evidence is invalid or incomplete"
import hashlib
import json
from pathlib import Path
import sys

review_path = Path(sys.argv[1])
root = Path(sys.argv[2])
tag = sys.argv[3]
required_contracts = (
    "README.md",
    "docs/operations.md",
    "docker/docker-compose.yml",
)
try:
    review = json.loads(review_path.read_text())
except (OSError, UnicodeError, json.JSONDecodeError):
    raise SystemExit(1)

if not isinstance(review, dict):
    raise SystemExit(1)
if review.get("tag") != tag:
    raise SystemExit(1)
if review.get("release_notes_url") != (
    f"https://github.com/NousResearch/hermes-agent/releases/tag/{tag}"
):
    raise SystemExit(1)
if review.get("compatibility") != "compatible":
    raise SystemExit(1)
if not isinstance(review.get("summary"), str) or not review["summary"].strip():
    raise SystemExit(1)

contracts = review.get("contracts")
if not isinstance(contracts, dict) or set(contracts) != set(required_contracts):
    raise SystemExit(1)
for relative_path in required_contracts:
    expected = contracts[relative_path]
    if not isinstance(expected, str) or len(expected) != 64:
        raise SystemExit(1)
    actual = hashlib.sha256((root / relative_path).read_bytes()).hexdigest()
    if expected != actual:
        raise SystemExit(1)

checks = review.get("checks")
if not isinstance(checks, list) or not any(
    isinstance(check, dict)
    and check.get("command") == "./installer/install.sh validate"
    and check.get("result") == "passed"
    for check in checks
):
    raise SystemExit(1)
PYTHON
  printf 'Compatibility review verified for %s.\n' "$latest_tag"
}

assert_clean_worktree() {
  [[ -z "$(git -C "$repo_root" status --porcelain --untracked-files=all)" ]] \
    || fail "working tree is not clean; refusing to mix the Hermes image update with unrelated changes"
}

update_image_pin() {
  local current_tag="$1"
  local latest_tag="$2"

  python3 - "$compose_file" "$current_tag" "$latest_tag" <<'PYTHON'
from pathlib import Path
import sys

path = Path(sys.argv[1])
current_tag = sys.argv[2]
latest_tag = sys.argv[3]
current_image = f"nousresearch/hermes-agent:{current_tag}"
latest_image = f"nousresearch/hermes-agent:{latest_tag}"
content = path.read_text()
if content.count(current_image) != 1:
    raise SystemExit("expected exactly one current Hermes image pin")
path.write_text(content.replace(current_image, latest_image))
PYTHON
}

require_deploy_configuration() {
  require_var HERMES_DEPLOY_SSH_SOURCE_CIDR
  require_file HERMES_DEPLOY_SSH_PUBLIC_KEY
  require_var HERMES_MODEL_PROVIDER
  require_var HERMES_MODEL

  if [[ "$HERMES_MODEL_PROVIDER" == "openai-codex" ]]; then
    require_file HERMES_CODEX_AUTH
    [[ -z "${HERMES_ENV:-}" ]] \
      || fail "HERMES_ENV must not be set for the openai-codex provider"
  else
    require_file HERMES_ENV
    [[ -z "${HERMES_CODEX_AUTH:-}" ]] \
      || fail "HERMES_CODEX_AUTH is supported only for the openai-codex provider"
  fi
}

push_update() {
  local latest_tag="$1"
  local branch

  [[ "${CONFIRM_PUSH:-}" == "yes" ]] \
    || fail "set CONFIRM_PUSH=yes immediately before allowing a GitHub push"
  branch="$(git -C "$repo_root" symbolic-ref --quiet --short HEAD)" \
    || fail "refusing to push from a detached HEAD"
  git -C "$repo_root" add docker/docker-compose.yml
  git -C "$repo_root" commit -m "chore: update Hermes Agent to $latest_tag"
  git -C "$repo_root" push origin "$branch"
}

deploy_update() {
  local -a deploy_args=(
    deploy existing
    --host "$HERMES_DEPLOY_HOST"
    --ssh-user "$HERMES_DEPLOY_SSH_USER"
    --ssh-public-key "$HERMES_DEPLOY_SSH_PUBLIC_KEY"
    --ssh-private-key "$HERMES_DEPLOY_SSH_PRIVATE_KEY"
    --ssh-source-cidr "$HERMES_DEPLOY_SSH_SOURCE_CIDR"
    --model-provider "$HERMES_MODEL_PROVIDER"
    --model "$HERMES_MODEL"
    --confirm-external-mutation
  )

  [[ "${CONFIRM_DEPLOY:-}" == "yes" ]] \
    || fail "set CONFIRM_DEPLOY=yes immediately before allowing a server deployment"
  if [[ "$HERMES_MODEL_PROVIDER" == "openai-codex" ]]; then
    deploy_args+=(--codex-auth "$HERMES_CODEX_AUTH")
  else
    deploy_args+=(--hermes-env "$HERMES_ENV")
  fi
  "$repo_root/installer/install.sh" "${deploy_args[@]}"
}

main() {
  local current_tag latest_tag

  require_command ssh
  require_command gzip
  require_command tar
  resolve_deploy_host

  require_backup_configuration
  backup_runtime_data
  require_command gh
  require_command git
  require_command python3

  current_tag="$(read_pinned_tag)"
  latest_tag="$(read_latest_tag)"
  if [[ "$current_tag" == "$latest_tag" ]]; then
    printf 'Hermes is already pinned to the latest stable release (%s); skipping push and deployment.\n' \
      "$current_tag"
    return
  fi

  verify_compatibility_review "$latest_tag"
  assert_clean_worktree
  require_deploy_configuration
  update_image_pin "$current_tag" "$latest_tag"
  push_update "$latest_tag"
  deploy_update
}

main "$@"
