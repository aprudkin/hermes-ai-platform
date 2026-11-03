# Custom Codex image-provider source

This is the actual local `openai-codex-25` plugin source and manifest, retained
as dormant reconstruction material. It provides Flare/Sunburst catalog entries
and quality selection through the installed Hermes Codex image transport. It
uses the genuine framework provider API, a request-scoped model lock and
restores the transport's model global on completion/failure.

It does not include OAuth/access/refresh tokens, auth.json, images, request
history, private configuration or a new login flow. It does not register or
activate itself merely by being stored under this extensions directory.
Installation and provider selection are deliberate separate operator steps.
Do not assume model catalog entries prove that a subscription/API accepts them.

Offline tests load this source against the pinned real Hermes checkout used by
CI and verify registration, catalog, empty-prompt/no-auth access and missing-auth
failure with socket connects denied. They do not spend credits or generate an
image. The source reconciliation did not exercise live generation, subscription
acceptance, image editing, authenticated setup or gateway plugin activation.
