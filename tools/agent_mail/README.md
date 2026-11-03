# Explicit AgentMail setup helper

`agentmail_setup.py` preserves the local one-time signup, durable intent,
no-blind-retry receipt, protected credential append and exact authenticated
inbox readback flow. Imports and `--help` are inert. Registration requires both
an explicit private `--home`, `--username`, and `--execute`.

Use it only for a separately authorized **new** account. Restoring an existing
account means restoring its private state and credentials, not registering a
replacement. No signup, inbox read, email send or Telegram announcement is run
by tests, validation, repository publication or merge.

The private profile holds `agent-mail/` intents/receipts/account metadata and
`.env`; neither belongs in Git. Preserve uncertain attempts for reconciliation,
do not clear their intent to force another signup. Never print the API key.
The helper's successful inbox readback is not proof of email deliverability or
an enabled incoming-mail monitor.

The historical personal introduction/announcement sender is deliberately not
copied: it embeds a person's address, private text and one-time delivery intent.
It must not be replayed during reconstruction.

Offline tests verify inert imports and the explicit-execution gate. This
reconciliation did not create an account or exercise the remote signup API.
