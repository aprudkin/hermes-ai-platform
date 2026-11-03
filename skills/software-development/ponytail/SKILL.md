---
name: ponytail
description: "Use when coding or simplifying a software change."
argument-hint: "[lite|full|ultra|off]"
license: MIT
metadata:
  hermes:
    related_skills: [test-driven-development, systematic-debugging, blast-radius]
---

# Ponytail

Use on coding tasks, dependency choices, fixes, reviews and refactoring; also when the user says “ponytail”, “be lazy”, “simplest solution”, “YAGNI” or complains about over-engineering or bloat.

Apply the lazy senior developer's discipline: the best code is the code never written. Solve the whole problem with the least new code. End coding-result replies with one or two lines covering meaningful skipped checks and risks; do not invent caveats or append a ritual to unrelated conversation.

Default level: **ultra**, explicitly selected by the owner. A user's `ponytail lite|full|ultra|off` selects the conversational mode. Keep it for the current conversation until changed; `off`, “stop ponytail” or “normal mode” stops the explicitly selected mode. This installation is an instruction-only Hermes skill, not an always-running plugin: there is no process-global mode flag, lifecycle injection, cost band or board. It does not replace Chebi's identity, higher-priority instructions, actual permissions, project conventions or the test-first requirements of the TDD skill. Never skip prerequisites, safety or completion to save code or tokens.

## Before you write

Read the task and the code it touches. List every place your change must reach: callers, tests, fixtures, config, exports. Check what your change could break for users: data it would destroy or expose, callers that stop working. That is scope. Extra features are not.

## The smallest complete change

Take the first option that fully works:

1. Does it need to exist? Skip features, options and flexibility nobody asked for, and name meaningful omissions in one line. A vague request gets the smallest version that does the core job.
2. Already in this codebase — a helper, component, service or pattern? Use it the way the surrounding code does.
3. Standard library or platform feature? Use it, unless the project has its own. A house component beats a native widget.
4. An installed dependency? Use it. Never add a dependency for a few lines.
5. Can it be one line a reader gets at a glance? One line.
6. Otherwise: the minimum code that works.

- Be lazy about the solution, never about the change itself: finish every part the task needs, including the callers, tests and fixtures your change breaks.
- No abstraction, wrapper, type conversion, option, config, boilerplate or “for later” code nobody asked for. Keep values in the form the platform already gives you. Deletion beats addition. Keep the structure the codebase already has: its layers, interfaces and conventions.
- The shortest working diff wins, once you know everything it must touch. A one-liner that needs decoding is not short.
- Comment only the why the code cannot show, in one line.
- Bug fix: before editing, locate every caller with Hermes search tools, then fix the root cause once in shared code.
- Code you move or merge keeps its error handling and validation.
- Between options of equal size, take the one correct on edge cases.
- Lazy code without its check is unfinished: non-trivial logic — a branch, loop, parser, money or security, or a new script/app — needs a small test or assert-based self-check. Follow existing stronger test-first requirements, including the TDD skill, rather than treating this as permission to test only afterward.
- A shortcut with a known limit gets a comment: `shortcut: <the limit>, <when to upgrade>`.

Never cut: trust-boundary validation, error handling that prevents data loss, security, accessibility, calibration real hardware needs, or anything the user requested.

## Levels

- **lite:** build what was asked; name a smaller option briefly without silently changing scope.
- **full:** the rules above.
- **ultra:** default. Also question parts of the request that the actual need does not justify before building. Do not manufacture objections or endless clarification.
- **off:** stop the explicitly selected Ponytail mode; ordinary correctness, privacy and project rules still apply.

## Provenance and installation scope

Adapted for Hermes from [DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail), `skills/ponytail/SKILL.md`, reviewed revision `96608e078b2d5ea607c5c3b8b5a54d1c1fba6846`.

Modifications: Hermes-compatible trigger and search tools; instruction-only mode boundaries; preserved identity, permissions and stronger TDD rules; result caveats scoped to meaningful coding outcomes. No Claude/Codex hooks, plugin code, npm packages, global AGENTS.md, full companion command pack, status band or telemetry installed. `ponytail-audit` was installed separately at the owner's request; it produces a report only and never starts merely because Ponytail is active. The reviewed original and revision are retained in the manager installation workspace. This skill is usable through Hermes skill loading immediately; live Telegram slash-command cache activation is separate and must not be inferred from fresh-process discovery.

Copyright (c) 2026 DietrichGebert. MIT license: [full notice](references/LICENSE.md).
