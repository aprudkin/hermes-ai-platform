# Customize agent workflows without importing another platform

## 1. Establish the requested change

Separate three requests: assess a workflow, install/adapt it, and execute work with it. For an assessment, inspect the relevant material and give a recommendation without installing skills or creating a backlog. For an approved change, define the task class and the behavior that should improve: clearer configuration decisions, a retrospective, risk analysis, or repeat-error prevention.

Match rigor to the actual problem. Do not introduce an orchestration framework merely to obtain a better interview or a small improvement checklist.

## 2. Inspect the actual skill dependency chain

1. Load the applicable runtime skill and current official skills documentation. Inspect the capabilities of the installed runtime separately from the upstream documentation.
2. Resolve the repository revision and list its skill files. Download only the relevant instructions and supporting files into a review workspace; do not execute an installer to discover what it contains.
3. Read SKILL.md bodies rather than relying on README descriptions. If rendered pages disagree, use raw files from the same resolved revision throughout the comparison.
4. Follow skill-to-skill calls and references. A short command can be only a wrapper around an interview primitive; installing the wrapper alone omits its behavior. Include required references, templates and supporting scripts in a proposed adaptation.
5. Inventory harness assumptions: tool names, subagent types, model-routing syntax, plugin commands, browser controls, project steering files, and user-only invocation metadata. Translate calls to the actual Hermes tools and verify metadata handling; Markdown compatibility does not establish executable plugin compatibility.
6. Compare with already available debugging, testing, review and repository workflows. Prefer a complementary subset over competing duplicate disciplines. Explain whether the pack adds a missing capability or just another name for an existing one.

Keep the assessment task-specific. Interview and retrospective procedures fit configuration/improvement requests; architecture surveys target code structure and are not substitutes for inspecting live settings. Large multi-model engineering modes can be useful for broad development but should not become prerequisites for ordinary maintenance. Do not assume that every leaf skill is standalone: trace its dependency closure before promising a small import.

## 3. Design questioning without creating an approval ritual

1. Establish the outcome, scope and protected behavior before proposing configuration edits.
2. Find retrievable facts through tools and documentation. Do not ask the user to supply settings, file contents or behavior the agent can inspect safely itself.
3. Ask the user for genuine decisions: the desired outcome, acceptable tradeoffs and constraints that observation cannot settle. Batch independent questions; defer dependent questions until their prerequisites are answered.
4. For an explicitly requested interview, agree on the direction before applying changes. For ordinary authorized low-stakes work, use the existing discretion instead of requiring confirmation at every step.
5. Make recommendations with reasons, without turning the recommended answer into presumed consent. An exhaustive decision tree is a technique, not a requirement to ask every conceivable question.
6. Stop the interview when the consequential decisions and acceptance criteria are settled. State remaining uncertainty rather than inventing certainty or extending the process indefinitely. Once the user approves a bounded implementation, execute that scope without another round of generic confirmation; a later correction replaces only the affected decision unless the user stops the work. Distinguish accepting a temporary operational rule from claiming that the rule was learned from observations: label the assumption, preserve the underlying facts, and do not silently switch forecasting policy while collecting data.

Do not import a pack's broad autonomy rules as new authorization. Workflow instructions about proceeding, posting updates or selecting models must stay inside the real permissions and spending boundaries.

## 4. Review improvements against observed friction

Use a retrospective to inspect the work and its environment: navigation, missing information, tool economy, checks, instruction conflicts and recurring mistakes. Present a small prioritized set of changes with expected benefit, risk and verification. Prefer a deterministic check for a mechanical recurring error; reserve prose guidance for judgment that cannot be encoded cheaply. Do not claim a new instruction makes a failure impossible.

Before a risky configuration change, identify what it could break beyond the edited file and test the key safety assumption against the real implementation. A list of hypothetical risks is not proof of safety.

## 5. Choose a tracker without duplicating task ownership

- Use repository issues for a deliberately selected long-lived project backlog, a session checklist for execution steps, and Cron for scheduled invocation or reminders. Retain the existing shared-task register for its own authorized reminder use; do not mirror every project issue into a second authoritative list.
- Before recommending a GitHub repository as the tracker, inspect GET /repos/{owner}/{repo} for visibility, has_issues, archived state and permissions. List open issues with pagination and exclude pull requests from issue counts; inspect existing labels before proposing another taxonomy.
- For a proposal, report readiness without creating issues or assuming the workflow has been adopted. Once authorized, search for duplicates before filing.
- Give each issue the intended outcome, non-goals, unresolved decisions and a verifiable definition of done. Reference relevant code, tests or resulting changes rather than pasting private conversations or raw runtime stores; private repository visibility is not a reason to include secrets.
- Keep the initial process small: ordinary issues and a few existing statuses are enough unless a board or extra automation solves a demonstrated problem.
- Allow operational changes to resolve through an issue with verification evidence even when no code PR is needed. For code changes, link the implementation and distinguish merged repository work from deployed runtime behavior.
- Explain what triggers execution. Recording an issue alone does not schedule, monitor or dispatch an agent. Add such automation only as a separate authorized, verified change.

## 6. Verify adoption separately from installation

For an approved import, use the active profile and preserve existing skills. Verify discovery/loading, required dependencies, invocation boundaries and a bounded representative task before describing the workflow as working. Report the stages precisely: reviewed, downloaded, installed, discoverable, exercised, and behavior verified. Keep untested benefits as expectations, not established results.

- Test the user's actual invocation surface, not only a fresh CLI process. Skill files can load correctly while a long-running gateway still has a stale command index; use its native `/reload-skills` and verify a real skill invocation before claiming slash dispatch works. Reloading a helper process does not refresh the gateway.
- For inline answer buttons, verify outbound keyboard construction and inbound callback handling separately. Scope the handler to its own prefix, bind the real responder/chat/message to the durable question receipt, and test wrong-user, stale-button and duplicate-click rejection; a successful keyboard payload alone cannot prove that a tap records an answer.
- Check activation behavior against the installed runtime rather than assuming that newer documentation's hot-loading applies. Plugin discovery or an enable command is not proof that the live adapter wired its native handler. Keep that stage explicitly pending until an actual runtime readiness witness exists, and never describe a planned restart or an unperformed live interaction as verified.
