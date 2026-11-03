# Elena addressing extension

Native `pre_gateway_dispatch` hook plus a standard-library helper. The only permitted
address is **Ле**. The old weighted pet-name policy is not current and is not included.
The seeded, event-keyed selector retains its 300-slot API for compatibility; all
slots now select the same current name. Seed files remain private, mode 0600, and
are never bundled. No source message text, seed or name is written per event.

## Offline verification

```sh
PYTHON=python3 sh extensions/elena-addressing/test.sh
# Also exercise real native registration and gateway hook consumption:
HERMES_SOURCE_ROOT=/path/to/hermes-checkout PYTHON=python3 sh extensions/elena-addressing/test.sh
```

The portable suite uses only Python 3.10+ standard library. Two native hook tests
explicitly skip unless `HERMES_SOURCE_ROOT` is supplied; with it they use that
checkout and its installed Hermes dependencies, not a fabricated gateway. They
copy this plugin/helper into a temporary profile and exercise the actual
`PluginManager` and gateway inbound hook. No live profile/plugin is touched.

## Packaging and fail-closed configuration

`plugin/` is the native plugin source; the helper remains under `scripts/`.
The original loader contract expects the plugin at the chosen active home's
`plugins/elena-addressing/` and the helper at `scripts/elena_addressing.py`.
Cross-profile loads are rejected. This repository does not copy/install/enable it.

Supply the following environment configuration **before plugin registration**:

- `ELENA_ADDRESSING_USER_ID`: Elena's exact numeric Telegram sender/DM ID.
- `ELENA_ADDRESSING_OWNER_ID`: owner's exact numeric Telegram sender ID.
- `ELENA_ADDRESSING_GROUP_ID`: authorized shared Telegram supergroup ID.
- `ELENA_ADDRESSING_PROFILE`: authorized profile name.

There are no recipient/profile routing defaults, real or synthetic. Missing or
invalid configuration leaves rewrites inert and prevents native registration
before seed/state creation. Pure name selection remains usable offline.

The hook uses authenticated adapter metadata, never a sender guessed from message
text. It preserves authentication/source fields, skips commands, bots, internal
messages, rejected routes and other profiles/chats, and appends at most one
conditional hint per event. The hint applies only when addressing Elena, not the
owner, and does not demand a salutation in every response. Its appended context can
persist in ordinary transcripts; it is a style hint, not an authorization boundary.
