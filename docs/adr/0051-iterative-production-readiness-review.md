# ADR-0051: Iterative production-readiness review

- **Status:** Accepted
- **Date:** 2026-04-26
- **Supersedes:** none
- **Superseded by:** none
- **Related:** [ADR-0044](0044-hydraflow-principles.md) (TDD as default workflow), [ADR-0049](0049-trust-loop-kill-switch-convention.md) (kill-switch convention), [ADR-0050](0050-auto-agent-hitl-preflight.md) (auto-agent HITL pre-flight). See also `docs/wiki/dark-factory.md` (lessons inventory).
- **Enforced by:** `superpowers:subagent-driven-development` workflow (per-task reviews), this ADR (process documentation), `superpowers:code-reviewer` skill (the fresh-eyes reviewer).

## Context

Across the trust-fleet (#8390) and auto-agent (#8431, #8439) feature builds, every Critical finding caught in fresh-eyes review was a missed load-bearing convention. Each feature took 3–5 review iterations before converging to "no Critical findings on the next pass." Without an explicit policy, convergence is a heroic ad-hoc effort that depends on the engineer remembering to dispatch reviewers; with one, it's the standard workflow.

We need to codify the "iterate fresh-eyes review until convergence" pattern as the standard for substantial features, so that the engineer's first instinct after implementation passes its per-task reviews is to start fresh-eyes iteration rather than to merge.

## Decision

For substantial features (new caretaker loop, new runner, spec → multi-task implementation), after the implementation passes its per-task reviews, run **fresh-eyes review iterations** until convergence.

- Each iteration uses `superpowers:code-reviewer` (or equivalent reviewer with no conversation context) on the cumulative diff against `main`.
- The reviewer reads the spec + the diff + the live codebase and reports Critical / Important / Minor findings.
- After fixes, the next iteration repeats.
- **Convergence = next pass finds nothing material** (Critical = 0, Important ≤ 1, all explained as deliberate).

Plan for **3 iterations** before merge. Empirical convergence point on recent features:

- Trust-fleet (#8390): 5 passes
- Auto-Agent spec (#8431): 3 passes
- Auto-Agent wiring (#8439): 3 passes

## Rules

1. **Fresh-eyes means no conversation context.** The reviewer reads the diff + the live codebase and reports findings without seeing the design rationale that produced the diff. This catches assumptions the engineer has grown blind to.
2. **Don't merge before convergence.** A Critical finding on iteration N is a merge-blocker until iteration N+1 confirms the fix.
3. **Iteration counts decline.** Each pass should find fewer issues. If iteration N+1 finds MORE issues than iteration N, something is wrong with the fixes — pause and re-spec.
4. **Per-task reviews continue during implementation.** This ADR is about the END phase (after implementation looks done); per-task reviews remain the standard during the build (per `superpowers:subagent-driven-development`).

## Consequences

**Positive:**
- Critical bugs caught at PR time, not in production.
- Reviews surface architectural drift while still cheap to fix.
- "Substantial features take 3 review passes" becomes a planning expectation, not a surprise.
- Convergence is a clear merge gate: don't merge until reviews are clean.

**Negative:**
- Substantial features take longer to merge (~30–60 min of reviewer time per pass).
- Reviewers must read live code (not just the diff) — but `code-reviewer` agent already does this.

**Risks:**
- Reviewer fatigue / noise from repeated passes. Mitigation: skip iterations once convergence reached; Minor-only findings don't re-trigger.

## Alternatives Considered

- **Single review pass.** Rejected — empirically misses bugs.
- **Reviewer in CI (mandatory).** Rejected — too much friction; reviewer needs codebase access and runs ~5 minutes per pass.
- **Pre-merge checklist.** Rejected — doesn't catch what reviewers do (cross-cutting drift, contract holes).

## When to supersede this ADR

- If a `superpowers:production-readiness-review` skill is built that automates the iteration loop, this ADR's "manually iterate" guidance becomes a legacy fallback. Update accordingly.
- If empirical convergence point shifts (e.g., features routinely converge in 1 pass), reduce the planning expectation.

## Source-file citations

- `docs/wiki/dark-factory.md` §3 — the convergence loop documentation.
- `docs/adr/0050-auto-agent-hitl-preflight.md` — the recent feature whose review iterations validated this ADR.
- `superpowers:code-reviewer` (Claude Code skill) — the reviewer this ADR refers to.
- `superpowers:subagent-driven-development` (Claude Code skill) — the per-task review workflow during implementation.
