# Auto-Agent — implement-stuck Playbook (ADR-0063 W1)

{{> _envelope.md}}

## Sub-label: implement-stuck

ImplementPhase hit the attempt cap or produced a zero-diff branch. The
implementation runner already tried the plain "implement this spec" loop.
Don't retry the same shape — apply the two-stage review pattern.

## Specific guidance

Order of operations:

1. Read the spec (issue body / escalation context) and any prior attempts'
   diagnoses (in prior attempts block).
2. Dispatch a spec-compliance subagent (mental model — even if you do this
   in-process): "given this spec and this current branch state, list every
   spec requirement not yet satisfied by the diff." If the diff is empty,
   list every requirement from scratch.
3. For each unmet requirement, write the failing test first (TDD per
   `docs/wiki/testing.md`). If a requirement can't be tested with the
   existing fixture set, that's the diagnosis — escalate with the specific
   testing gap.
4. Implement the smallest change that makes the test pass. Then run
   `make quality` (per CLAUDE.md quick-rules) before pushing.
5. Either push and open a PR (`resolved`) or return `needs_human` with the
   precise spec-vs-code gap (e.g. "spec requires Port X; the existing
   adapter registry has no slot for X, blocked on ADR amendment").

Do NOT:
- Force-push the existing branch over the prior implementation. Start fresh
  on `agent/auto-agent-<issue>` or whatever branch the loop already created.
- Mark the spec as "ambiguous, escalating" without first trying the
  spec-compliance walk. Most "ambiguous" specs are precise but contradicted
  by an unspoken convention; the wiki entries surface those.
- Skip `make quality`. Cleanup PRs over-pruning defensive guards has
  bitten this project before (PR #8460 → #8463).
