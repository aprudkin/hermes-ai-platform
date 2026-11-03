# Vetted instruction-source snapshots

These are selected custom/adapted skills and reviewed modifications used by the
manager profile, not a dump of its private runtime directory. Original license
and provenance files are retained where supplied. Unchanged bundled skill packs
remain dependencies of the Hermes installation rather than being re-vendored.

Private account/chat/user/server values and credential-shaped examples have
been replaced by explicit placeholders. They are **not valid routing defaults**.
Populate real operational configuration only in the protected live profile;
never convert placeholders into guessed recipients.

The portable cycle skill is packaged with its code under
[tools/cycle_tracker](../tools/cycle_tracker/README.md). Runtime-backed skills
can refer to paths in an installed profile; copying this directory alone is not
an installation, cron migration or plugin activation. Source publication does
not override a running/cached skill, live SOUL, private memory or cancelled job.

The mail-discovery helpers are retained with that standalone skill for its
established installed entrypoint; they must stay byte-identical to the reviewed
[collection implementation](../tools/mail_event_discovery/README.md).

Do not restore the excluded Yandex/Jira monitor or the stopped social/blog
publication chains from earlier instructions or backups. Real financial,
medical, mail, task, session and credential data is not part of these snapshots.
