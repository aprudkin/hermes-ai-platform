# Domain context

Use a single context for this repository: one persistent Hermes environment,
with optional infrastructure bootstrap and recovery tooling.

Before researching project concepts, read [the operating model](../../README.md),
[architecture](../architecture.md) and [state ownership](../state-first.md).
Keep these distinctions explicit:

- A Hermes profile is an identity and state boundary inside one runtime, not a
  separate Hermes Core instance.
- Runtime-owned identity and personal state differ from repository templates.
- Minimal and later roadmap levels describe this project's scope, not upstream
  feature guarantees.
- Local validation, deployed health and behavioral verification are different
  evidence; backup capture alone does not establish recoverability.

For operational detail, follow the existing domain document: [operations](../operations.md),
[personal-state backup](../personal-backup.md) or [full recovery](../backup-restore.md).

## New terminology and decisions

Use `GLOSSARY.md` and `docs/adr/` as the single-context locations when concrete
new terms or architectural decisions need durable records. Read them when
present; do not create empty files or directories for layout completeness.
Use the domain-modeling skill for substantive glossary or ADR work. Keep current
definitions in one place and link to them rather than copying architecture docs.

Surface contradictions between code, runtime claims and documentation; identify
the evidence and resolve the relevant decision rather than silently changing
the operating model. This document does not authorize host access or deployment.
