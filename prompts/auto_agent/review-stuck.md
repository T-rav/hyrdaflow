# Auto-Agent — review-stuck Playbook (ADR-0063 W1)

{{> _envelope.md}}

## Sub-label: review-stuck

ReviewPhase escalated. Most commonly this is a sandbox/CI red — but the
SandboxFailureFixerLoop already runs for those, so by the time the issue
reaches you, the failure-fixer either gave up or wasn't applicable.

## Specific guidance

Order of operations:

1. Identify the failure class from the escalation context:
   - **CI / sandbox red** — read the test transcript (in escalation context).
     Then `git log -3 --stat` on the branch to see the last three commits.
     Pair the failing test name(s) to the commit that touched the closest
     surface. Fix the test or the production code, push, return `resolved`.
   - **Visual-validation failure** — HITL-by-design (ADR-0063 §Decision).
     Return `needs_human` with the failing screenshot path; do not attempt
     a fix.
   - **Merge conflict with main** — also HITL-by-design when the conflict
     touches files outside the PR's stated scope. Otherwise, rebase, run
     `make quality`, and push.

2. If the failure class is ambiguous, the diagnosis goes in the audit and
   the issue gets `needs_human` — don't guess.

Tools you should reach for:
- `git log --oneline -10` and `git log -3 --stat` (recent commit shape)
- `git diff HEAD~3` (what changed)
- The test transcript text in `escalation_context_block`
- The wiki entries in `wiki_excerpts_block` (often encode the regression
  pattern explicitly)

Do NOT:
- Modify visual-validation baselines without a human signing off.
- Force-push to resolve merge conflicts.
- "Fix" failures by deleting tests. If a test is genuinely wrong, the fix
  is to change the assertion (with a code comment explaining why) — not to
  delete the test.
