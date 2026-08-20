#!/usr/bin/env bash

set -euo pipefail

# shellcheck source=tests/test_helper.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)/test_helper.sh"

fixture_dir="$(mktemp -d)"
fixture="$fixture_dir/telegram.env"
trap 'rm -rf "$fixture_dir"' EXIT

write_valid_env() {
  local destination="$1"
  local users="${2:-101,202}"
  local chats="${3:--1001,-1002}"
  {
    printf 'TELEGRAM_BOT_TOKEN=%s:%s\n' '123456789' 'fixture_value_abcdefghijklmnop'
    printf 'TELEGRAM_ALLOWED_USERS=%s\n' "$users"
    printf 'TELEGRAM_ALLOWED_CHATS=%s\n' "$chats"
    printf 'TELEGRAM_REQUIRE_MENTION=true\n'
    printf 'TELEGRAM_EXCLUSIVE_BOT_MENTIONS=true\n'
    printf 'TELEGRAM_OBSERVE_UNMENTIONED_GROUP_MESSAGES=false\n'
  } >"$destination"
  chmod 600 "$destination"
}

assert_valid() {
  local label="$1"
  local output
  local status_code
  set +e
  output="$(HERMES_REPO_ROOT="$repo_root" python3 scripts/telegram_env.py check "$fixture" 2>&1)"
  status_code=$?
  set -e
  assert_status 0 "$status_code" "$label"
  [[ -z "$output" ]] || fail "$label: expected no output"
}

assert_invalid() {
  local label="$1"
  local output
  local status_code
  set +e
  output="$(HERMES_REPO_ROOT="$repo_root" python3 scripts/telegram_env.py check "$fixture" 2>&1)"
  status_code=$?
  set -e
  [[ "$status_code" -ne 0 ]] || fail "$label: expected non-zero status"
  [[ "$output" != *'fixture_value_abcdefghijklmnop'* ]] || fail "$label: leaked token fragment"
  local users chats identifier
  users="$(awk -F= '$1 == "TELEGRAM_ALLOWED_USERS" { print $2 }' "$fixture")"
  chats="$(awk -F= '$1 == "TELEGRAM_ALLOWED_CHATS" { print $2 }' "$fixture")"
  for identifier in ${users//,/ } ${chats//,/ }; do
    [[ "$output" != *"$identifier"* ]] || fail "$label: leaked identifier"
  done
}

replace_line() {
  local line_number="$1"
  local replacement="$2"
  awk -v line_number="$line_number" -v replacement="$replacement" \
    'NR == line_number { $0 = replacement } { print }' "$fixture" >"$fixture.tmp"
  mv "$fixture.tmp" "$fixture"
  chmod 600 "$fixture"
}

delete_line() {
  local line_number="$1"
  awk -v line_number="$line_number" 'NR != line_number { print }' "$fixture" >"$fixture.tmp"
  mv "$fixture.tmp" "$fixture"
  chmod 600 "$fixture"
}

insert_blank_line() {
  local line_number="$1"
  awk -v line_number="$line_number" 'NR == line_number { print "" } { print }' "$fixture" >"$fixture.tmp"
  mv "$fixture.tmp" "$fixture"
  chmod 600 "$fixture"
}

prefix_line() {
  local line_number="$1"
  awk -v line_number="$line_number" 'NR == line_number { $0 = " " $0 } { print }' "$fixture" >"$fixture.tmp"
  mv "$fixture.tmp" "$fixture"
  chmod 600 "$fixture"
}

suffix_line() {
  local line_number="$1"
  awk -v line_number="$line_number" 'NR == line_number { $0 = $0 " " } { print }' "$fixture" >"$fixture.tmp"
  mv "$fixture.tmp" "$fixture"
  chmod 600 "$fixture"
}

write_valid_env "$fixture"
assert_valid "valid multiple lists"
write_valid_env "$fixture" 101 -1001
assert_valid "valid single lists"
{
  printf 'TELEGRAM_OBSERVE_UNMENTIONED_GROUP_MESSAGES=false\n'
  printf 'TELEGRAM_ALLOWED_CHATS=-1001,-1002\n'
  printf 'TELEGRAM_BOT_TOKEN=%s:%s\n' '123456789' 'fixture_value_abcdefghijklmnop'
  printf 'TELEGRAM_EXCLUSIVE_BOT_MENTIONS=true\n'
  printf 'TELEGRAM_ALLOWED_USERS=101,202\n'
  printf 'TELEGRAM_REQUIRE_MENTION=true\n'
} >"$fixture"
chmod 600 "$fixture"
assert_valid "valid reordered keys"
chmod 400 "$fixture"
assert_valid "valid mode 0400"
chmod 600 "$fixture"

write_valid_env "$fixture"
delete_line 6
assert_invalid "missing key"
write_valid_env "$fixture"
printf 'TELEGRAM_UNKNOWN=value\n' >>"$fixture"
assert_invalid "unknown key"
write_valid_env "$fixture"
printf 'TELEGRAM_ALLOWED_USERS=303\n' >>"$fixture"
assert_invalid "duplicate key"
write_valid_env "$fixture"
replace_line 1 '# this is not an assignment'
assert_invalid "comment record"
write_valid_env "$fixture"
insert_blank_line 3
assert_invalid "blank record"
write_valid_env "$fixture"
prefix_line 2
assert_invalid "leading whitespace"
write_valid_env "$fixture"
suffix_line 2
assert_invalid "trailing whitespace"
write_valid_env "$fixture"
replace_line 2 'TELEGRAM_ALLOWED_USERS =101,202'
assert_invalid "spaces around equals"

for invalid_users in ',202' '101,' '101,101' '0' '-1' 'abc' '*' '101, 202'; do
  write_valid_env "$fixture" "$invalid_users"
  assert_invalid "invalid users $invalid_users"
done
for invalid_chats in ',-1002' '-1001,' '-1001,-1001' '0' '1001' 'abc' '*' '-1001, -1002'; do
  write_valid_env "$fixture" 101,202 "$invalid_chats"
  assert_invalid "invalid chats $invalid_chats"
done

for invalid_token in '' 'malformed' '0:fixture_value_abcdefghijklmnop' '123456789:short'; do
  write_valid_env "$fixture"
  replace_line 1 "TELEGRAM_BOT_TOKEN=$invalid_token"
  assert_invalid "invalid token"
done
for invalid_flag in \
  '4:TELEGRAM_REQUIRE_MENTION=false' \
  '5:TELEGRAM_EXCLUSIVE_BOT_MENTIONS=false' \
  '6:TELEGRAM_OBSERVE_UNMENTIONED_GROUP_MESSAGES=true'; do
  write_valid_env "$fixture"
  replace_line "${invalid_flag%%:*}" "${invalid_flag#*:}"
  assert_invalid "invalid flag"
done

for forbidden_key in \
  TELEGRAM_ALLOW_GROUP_WIDE_MESSAGES \
  TELEGRAM_WEBHOOK_URL \
  TELEGRAM_WEBHOOK_SECRET \
  TELEGRAM_ALLOW_ALL_USERS \
  TELEGRAM_ALLOW_ALL_CHATS; do
  write_valid_env "$fixture"
  printf '%s=true\n' "$forbidden_key" >>"$fixture"
  assert_invalid "forbidden key"
done

write_valid_env "$fixture"
ln -s "$fixture" "$fixture_dir/symlink.env"
fixture="$fixture_dir/symlink.env"
assert_invalid "symlink input"
fixture="$fixture_dir/telegram.env"
write_valid_env "$fixture"
chmod 644 "$fixture"
assert_invalid "mode 0644"

printf 'PASS: telegram input parser matrix\n'
