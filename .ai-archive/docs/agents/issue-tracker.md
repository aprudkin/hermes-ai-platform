# Issue tracker: GitHub

Use GitHub Issues in `github.com/aprudkin/hermes-ai-platform`.
[issue-tracker.json](issue-tracker.json) is the source of truth for the target,
project label and approved area labels. Keep that configuration; remote labels
alone do not redefine the vocabulary.

## Operations

Use `gh` with the explicit `--repo github.com/aprudkin/hermes-ai-platform`
target, including when working outside the repository. These are command
forms for agents; substitute a verified issue number and a prepared body file.

- List: `gh issue list --repo github.com/aprudkin/hermes-ai-platform --state all --limit 100 --json number,title,state,labels`.
  The limit is not proof of a complete inventory; paginate API queries when needed.
- Read: `gh issue view NUMBER --repo github.com/aprudkin/hermes-ai-platform --json number,title,body,labels,comments`.
- Create: `gh issue create --repo github.com/aprudkin/hermes-ai-platform --title TITLE --body-file FILE`.
  Add the configured project label and applicable approved area with `--label`.
- Update body: `gh issue edit NUMBER --repo github.com/aprudkin/hermes-ai-platform --body-file FILE`.
- Record progress/result: `gh issue comment NUMBER --repo github.com/aprudkin/hermes-ai-platform --body-file FILE`.
- Close completed work: `gh issue close NUMBER --repo github.com/aprudkin/hermes-ai-platform`.

Read the existing issue and comments before updating; preserve unrelated content.
Pass multiline bodies through a file, not shell-expanded inline text. Record
changes, checks and blockers in the tracked issue, and reference its real number
in related commits. An access failure means the tracker is unverified, not empty.

These command forms do not grant permission for external mutation; use the
applicable task authorization. A project-init reconciliation preserves issues,
comments, labels and milestones unless a separate change is explicitly selected.

## Triage scope

PRs as a request surface: **no**. Do not automatically discover or classify PRs
as requests.

Keep the existing issue workflow. Standard triage-role setup is deferred in
`.pi/project-init.json`; no mapping from legacy workflow labels to Matt triage
roles has been agreed. Resolve that mapping before applying role-based triage.
