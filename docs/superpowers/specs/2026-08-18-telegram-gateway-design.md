# Hermes Telegram Gateway Design

**Date:** 2026-08-18
**Tracking:** aimem#795
**Deployment level:** Minimal follow-up on the verified Hermes Minimal host

## Objective

Add a reproducible, fail-closed Telegram access path to the existing pinned
Hermes runtime. Authorized users must be able to talk to one selected Hermes
profile in direct messages and, when explicitly triggered, in an explicit set
of group chats. The integration must use the upstream Telegram gateway rather
than a second bot implementation and must not weaken the root credential
controls delivered by aimem#791.

The first production instance selects the `manager` profile, two authorized
users, and one authorized group. The installer and Ansible implementation must
remain generic: they accept a global set of one or more users and a global set
of one or more groups, with every authorized user permitted in every authorized
group.

## Upstream contract

The implementation is pinned to `NousResearch/hermes-agent:v2026.8.16` and must
be revalidated if the image tag changes. The pinned Telegram documentation is:

- <https://github.com/NousResearch/hermes-agent/blob/v2026.8.16/website/docs/user-guide/messaging/telegram.md>
- <https://github.com/NousResearch/hermes-agent/releases/tag/v2026.8.16>

The selected upstream behavior is:

- long polling, with no webhook URL and no new inbound listener;
- `TELEGRAM_ALLOWED_USERS` for users who may use both DMs and groups;
- `TELEGRAM_ALLOWED_CHATS` to reject every group outside the configured list;
- `TELEGRAM_REQUIRE_MENTION=true` for command, reply, or direct-mention group
  triggers;
- `TELEGRAM_EXCLUSIVE_BOT_MENTIONS=true` for deterministic multi-bot routing;
- no passive observation of unmentioned group messages;
- one gateway process for one selected profile.

`TELEGRAM_GROUP_ALLOWED_CHATS` is forbidden by this design because it grants
every member of an allowed group access. `TELEGRAM_GROUP_ALLOWED_USERS` is also
unnecessary because the selected users require DM access. Wildcards and
allow-all settings are forbidden.

## Scope

### Included

- text messages, Telegram commands, replies to the bot, and direct mentions;
- direct messages from every configured user;
- group messages from configured users in configured groups only;
- a parameterized selected Hermes profile, with `manager` selected for the
  first production instance;
- reusable installer validation for variable-length user and group lists;
- a targeted existing-host Telegram deployment path that does not run
  Terraform, package, firewall, Docker installation, or root credential tasks;
- optional Telegram configuration during a future full new-host or
  existing-host deployment through the same shared validation and role tasks;
- explicit disable and rollback behavior;
- hermetic failure-path tests and separately authorized production probes.

### Excluded

- images, files, voice messages, speech-to-text, and text-to-speech;
- webhooks, public ports, DNS, TLS termination, or reverse proxies;
- per-chat user matrices;
- anonymous group access or authorization by group membership;
- passive ingestion of ordinary group conversation;
- DM-only mode with zero configured groups;
- multiple simultaneous Telegram gateway profiles;
- BotFather or group-administrator changes performed by automation;
- changes to root SSH authorization, UFW, packages, or Hermes model/provider
  configuration.

DM-only mode is intentionally excluded because an empty upstream
`TELEGRAM_ALLOWED_CHATS` value means that groups are not restricted. A future
DM-only feature needs its own explicit disable-groups contract and tests.

## Access model

Authorization is the intersection of three independent gates:

1. The sender must appear in the non-empty global user set.
2. A group message must originate from the non-empty global group set. This
   gate does not apply to DMs.
3. A group message must be a command, a reply to the bot, or a direct mention.

Therefore every configured user may:

- start and continue a private conversation with the bot without a mention;
- invoke the bot in every configured group through a supported explicit
  trigger.

No configured user may invoke the bot from another group. No unconfigured user
may invoke the bot in a DM or in a configured group. A configured group never
authorizes its other members.

For the first production instance, Telegram privacy mode remains enabled and
the bot is made an administrator of the one configured group with the minimum
permissions available in Telegram. This allows Telegram to deliver direct
mentions while Hermes still rejects unmentioned messages before agent dispatch.

## Protected input contract

The operator supplies one controller-local file with mode `0400` or `0600`.
The file is outside Git and generated artifacts and contains exactly these
keys:

```dotenv
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_USERS=
TELEGRAM_ALLOWED_CHATS=
TELEGRAM_REQUIRE_MENTION=true
TELEGRAM_EXCLUSIVE_BOT_MENTIONS=true
TELEGRAM_OBSERVE_UNMENTIONED_GROUP_MESSAGES=false
```

The production copy populates the first line with one token, the second with a
comma-separated list of one or more positive IDs, and the third with a
comma-separated list of one or more negative IDs.

Validation must occur before Terraform, Ansible, SSH, Docker, or another
external process is invoked. It must enforce:

- an exact key set with no duplicate assignments;
- one non-empty structurally valid bot token without printing or hashing it;
- one or more unique positive decimal user IDs;
- one or more unique negative decimal group IDs;
- trimmed comma-separated values with no empty records;
- both mention flags exactly `true` and observation exactly `false`;
- no wildcard;
- no webhook, allow-all, `TELEGRAM_GROUP_ALLOWED_CHATS`, or
  `TELEGRAM_GROUP_ALLOWED_USERS` key.

Ansible repeats the same semantic assertions with `no_log: true`. The source
path, selected profile, and SSH key paths may appear in process arguments; the
file contents and parsed identities may not.

## Runtime layout

The selected profile is explicit rather than dependent on ambient profile
state. The Compose command becomes profile-parameterized using the pinned
global profile flag:

```yaml
command: ["-p", "${HERMES_GATEWAY_PROFILE:-default}", "gateway", "run"]
```

The existing default remains backward compatible when Telegram is not enabled.
The first production configuration sets `HERMES_GATEWAY_PROFILE=manager`.
Exactly one Compose service and one long-polling gateway remain active.

Telegram variables are installed only in the selected profile's protected
`.env` file. They are managed as a distinct marked block so API-provider
credentials and unrelated profile configuration remain byte-for-byte outside
that block. For the `openai-codex` provider, the profile `.env` may be created
solely for the Telegram block while OAuth material remains in the existing
Codex auth store.

The Compose runtime profile selection is stored in a root-owned deployment env
file under the existing Hermes application directory. Enabling Telegram
preserves the prior profile value once before changing it. Disabling Telegram
restores that preserved value instead of assuming `default`.

## Installer interface

The installer gains a `telegram` target alongside `new` and `existing`:

```text
./installer/install.sh plan telegram --telegram-state enabled --host HOST --ssh-user USER --ssh-public-key PUBLIC_KEY --ssh-private-key PRIVATE_KEY --telegram-env TELEGRAM_ENV --gateway-profile PROFILE

./installer/install.sh deploy telegram --telegram-state enabled --host HOST --ssh-user USER --ssh-public-key PUBLIC_KEY --ssh-private-key PRIVATE_KEY --telegram-env TELEGRAM_ENV --gateway-profile PROFILE --confirm-external-mutation

./installer/install.sh deploy telegram --telegram-state disabled --host HOST --ssh-user USER --ssh-public-key PUBLIC_KEY --ssh-private-key PRIVATE_KEY --confirm-external-mutation
```

The target reuses existing host, user, public/private key, inventory, and
keypair validation. `plan telegram` performs local structure, input, and
Ansible syntax validation without contacting the host. `deploy telegram`
requires the existing external-mutation confirmation and runs only the
targeted Telegram playbook followed by targeted verification.

`--telegram-state` is mandatory for the targeted flow. `enabled` requires
`--telegram-env` and `--gateway-profile`; `disabled` rejects both because it
restores the preserved pre-Telegram profile and removes the managed block.

The full `new` and `existing` deployment paths may accept the same optional
`--telegram-env` and `--gateway-profile` pair. Supplying one without the other
fails before external tools. Both paths call the same validation and Ansible
task implementation as the targeted flow.

Disable is an explicit targeted operation, not an automatic cleanup after
failure. It removes only the managed Telegram block, restores the recorded
pre-Telegram gateway profile, recreates the one container, and verifies the
ordinary Hermes runtime. It does not remove profiles, sessions, memory, model
credentials, Codex auth, or API-server credentials.

## Ansible design

Add a targeted `ansible/telegram_gateway.yml` playbook with these phases:

1. Validate the current container, Compose definition, selected profile, and
   current gateway profile without mutation.
2. Read and validate the controller-local Telegram source with `no_log`.
3. Preserve the current gateway profile once.
4. Atomically manage the selected profile's Telegram environment block and
   enforce directory/file ownership and mode.
5. Render the runtime profile selection and validate `docker compose config`.
6. Recreate only the Hermes Compose service.
7. Wait for container health and verify the selected profile through the
   Hermes CLI.
8. Verify that the gateway reports Telegram connected without returning the
   token or allowlist contents.

The full Hermes role imports the same Telegram task file only when both
Telegram inputs are explicitly supplied. The targeted playbook never imports
the base, Docker-installation, or root-credential roles.

In the full role, provider credential synchronization completes before the
Telegram task runs. The Telegram block is always applied last so the existing
whole-file provider copy cannot erase it on the same run or a later idempotent
run.

Every mutation is notified only after all local semantic assertions pass.
Failures report the phase and the last completed phase. They do not attempt an
automatic restart loop or destructive cleanup.

## Tests and verification

### Hermetic source tests

- Accept one and many unique user and group IDs.
- Reject missing keys, unknown keys, duplicate assignments, empty records,
  duplicate IDs, wrong signs, non-decimal IDs, whitespace ambiguity,
  wildcards, allow-all keys, group-wide authorization keys, webhook keys, and
  false mention controls.
- Prove invalid input invokes neither Terraform nor Ansible.
- Prove token and IDs are absent from stdout/stderr and command logs.
- Verify the selected profile is passed to Compose and only one gateway is
  started.
- Exercise the targeted success path, each phase failure, safe-resume output,
  and absence of Terraform/base-role commands.
- Exercise Ansible against a disposable filesystem: exact managed block,
  mode `0600`, unrelated credential preservation, idempotence, profile
  preservation, disable, and rollback.
- Verify full-deploy optional-pair behavior and backward compatibility when
  Telegram inputs are absent.
- Run repository secret scanning with token-shaped fixtures explicitly scoped
  to hermetic test data.

### Static and CI gates

- Bash syntax and ShellCheck;
- Terraform format and safe validation because the repository-wide gate
  includes Terraform, although Telegram makes no Terraform change;
- Ansible syntax and lint for the full and targeted playbooks;
- Docker Compose configuration for default and selected profiles;
- the complete behavioral suite;
- hosted CI on the exact implementation commit.

Unavailable tools remain `SKIP`, never `PASS`.

### Separately authorized production verification

Production deployment and restart require a separate owner decision after
source review and CI. The production evidence chain is:

1. Bot API identity succeeds and is recorded without sensitive fields.
2. Webhook state is empty and exactly one long-polling owner exists.
3. The container and selected `manager` profile are healthy.
4. Every configured user receives a substantive response in a DM.
5. Every configured user receives a substantive response through a mention or
   reply in a configured group.
6. An unconfigured user is denied in a configured group.
7. A configured user is denied in an unconfigured group.
8. An ordinary unmentioned group message produces no response and does not
   enter agent context.
9. Existing loopback API health and model inference probes still pass.
10. An independent read-back confirms the deployed profile, file modes,
    gateway status, and retained rollback state without exposing values.

Unit tests, configuration presence, `getMe`, and container health alone do not
prove Telegram end-to-end behavior.

## Operational boundaries

- Local implementation, tests, formatting, syntax checks, and CI preparation
  are authorized by aimem#795.
- Host connection, secret installation, container recreation, Telegram Bot API
  probes, visible test messages, and group-administrator changes are production
  actions and require their exact authorization.
- Real tokens, user IDs, chat IDs, message bodies, and raw Telegram updates are
  never committed or copied into Issue evidence.
- Production logs are queried through narrow status/nonces and summarized with
  placeholders.
- No host apply is inferred from an approved design, passing tests, a merged
  commit, or Project status.

## Completion criteria

aimem#795 may be completed only when the source implementation is merged, CI is
green on the merged commit, the separately authorized production deployment
has passed every applicable end-to-end and negative control above, rollback
state is retained, and the exact Issue and Project card are independently read
back after guarded completion.
