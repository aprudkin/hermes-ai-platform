# Hermes AI Platform

## Baseline

- `PROJECT_AUDIT.md` records that the 2026-08-16 audit found the repository non-deployable: documentation and skeletons existed, but Terraform resources, Ansible playbooks, prompt stage files, tests, a functional installer, and complete Docker and validation paths did not.
- Re-check the current tree before relying on this baseline; do not repeat findings after relevant implementation has changed.
- `CODEX_SETUP_PROMPT.md` is historical input. Use `CODEX_CLI_START.md` as the implementation brief only for work the user requests.

## Product and roadmap boundaries

- Build one Hermes Agent runtime. Express Manager, DevOps, Coding, and Research specialization through upstream-supported profiles, skills, memory, policies, tools, and configuration—not separate Hermes Core instances.
- Roadmap levels are project planning levels, not claims about upstream Hermes:
  - **Minimal:** stages 00–04; the smallest end-to-end deployable system.
  - **Optimal:** stages 05–10; only after Minimal is verified.
  - **Advanced:** stages 11–19; only after Optimal is verified.
  - **Maximum:** stages 20–31; only after Advanced is verified.
- Implement Minimal first. Do not pull later-level features into Minimal without a concrete dependency and documented reason.
- Do not invent upstream features to satisfy a roadmap label.
- Production deployment paths must not contain placeholders, TODOs, mocks, sample data, fabricated images, echo-only installers or validators, empty implementation skeletons, hard-coded success or health results, or checks that cannot fail when the system is broken. Empty user-supplied credential-template values are permitted; other incomplete work blocks the associated readiness claim.

## Deployment facts

- Future Minimal deployment: Hetzner project `hermes`, Finland location `hel1`, replacing the earlier Germany-only constraint.
- Select an explicit cost-optimized server type only after checking current availability and price in `hel1`; `cx23` is the current documented choice, not a durable default.
- Intended public SSH key: `~/.ssh/luk.pub`.
