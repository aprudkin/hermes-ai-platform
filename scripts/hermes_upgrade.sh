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


backup_runtime_data() {
  # Retain explicit target credentials for the pre-upgrade recovery capture.
  require_var HERMES_DEPLOY_SSH_USER
  require_file HERMES_DEPLOY_SSH_PRIVATE_KEY
  HERMES_DEPLOY_HOST="$HERMES_DEPLOY_HOST" "$repo_root/scripts/hermes_backup.sh" --full
}

read_pinned_tag() {
  local tag
  local -a tags=()
  while IFS= read -r tag; do
    tags+=("$tag")
  done < <(
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

main() {
  local current_tag latest_tag

  [[ "$#" -eq 0 ]] || fail "usage: hermes_upgrade.sh (prepare only; see docs/operations.md)"
  [[ -z "${CONFIRM_PUSH:-}" && -z "${CONFIRM_DEPLOY:-}" ]] \
    || fail "automatic push/deploy was retired; unset CONFIRM_PUSH/CONFIRM_DEPLOY and see docs/operations.md"
  require_command ssh
  require_command git
  require_command python3
  assert_clean_worktree
  resolve_deploy_host

  backup_runtime_data
  require_command gh
  require_command git
  require_command python3

  current_tag="$(read_pinned_tag)"
  latest_tag="$(read_latest_tag)"
  if [[ "$current_tag" == "$latest_tag" ]]; then
    fail "local pin already matches $current_tag; live deployment is UNKNOWN, not a successful update. For deploy/retry use the explicit existing-host workflow in docs/operations.md"
  fi

  verify_compatibility_review "$latest_tag"
  assert_clean_worktree
  update_image_pin "$current_tag" "$latest_tag"
  # Validate the candidate, not merely the old pin attested in the review.
  # On failure leave the diff for inspection; a retry fails the clean-tree gate.
  "$repo_root/installer/install.sh" validate
  printf 'Prepared and locally validated pin %s. NOT committed, pushed or deployed.\n' "$latest_tag"
  printf 'Review the diff, publish separately, then authorize an explicit deployment; see docs/operations.md.\n'
}

main "$@"
