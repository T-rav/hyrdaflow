# ADR-0005: PR Recovery and Zero-Diff Branch Handling in Implement Phase

**Status:** Accepted
**Date:** 2026-02-27

## Context

Implementation could succeed while PR creation still failed for branch-state reasons:
- The `agent/issue-N` branch existed but had no commits ahead of `main`.
- `gh pr create` returned "No commits between main and branch".
- The pipeline could leave issues in `hydraflow-ready` with stale branches and no reviewable PR.

This created queue churn and blocked review intake because review only consumes
issues with `hydraflow-review` plus an open PR.

## Decision

1. Add PR recovery by branch:
   - On PR creation failure, query for an already-open PR on `agent/issue-N` and reuse it.
2. Add branch diff guard:
   - Compare `main...agent/issue-N` and detect `ahead_by == 0`.
3. Enforce implement->review contract:
   - Never transition a successful implementation to review without a valid PR.
4. Zero-diff branch resolution:
   - If no PR exists and branch has no diff, close issue as already satisfied.
   - If branch has diff but PR is still missing, keep issue in ready/retry path.

## Consequences

**Positive:**
- Review queue only receives reviewable items (with real PRs).
- Stale zero-diff branches no longer strand ready issues.
- Existing PRs are recovered instead of duplicated.

**Trade-offs:**
- One extra branch-compare call in failure paths.
- Slightly more logic in implement finalization and PR manager.

## Alternatives considered

1. Always force-push a fresh branch and retry PR creation.
   - Rejected: unnecessary churn and risk of overwriting useful branch history.
2. Leave issue in ready and rely on manual cleanup.
   - Rejected: repeated failures and queue noise.

## Related

- `src/implement_phase.py`
- `src/pr_manager.py`
- PR #1294
