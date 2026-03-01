# ADR-0012: Epic Merge Coordination Architecture

**Status:** Proposed
**Date:** 2026-03-01

## Context

HydraFlow's review phase currently merges each approved PR independently via
`PostMergeHandler.handle_approved()`. After merge, `EpicManager.on_child_completed()`
tracks progress and auto-closes the parent epic when all children complete.

This independent-merge model works well for standalone issues but falls short for
epics that require coordinated merges:

- **Bundled releases:** Some epics represent a feature bundle where all child PRs
  should land together to avoid shipping a partially-complete feature to users.
- **Dependency ordering:** Child issues may have inter-dependencies where merging
  out of order causes test failures or broken intermediate states on `main`.
- **Human gates:** High-risk epics may need a human sign-off before any approved
  PRs are merged, even after automated review passes.

Today, the only merge strategy is effectively "independent" — each PR merges as
soon as it passes review and CI. There is no mechanism to hold an approved PR,
coordinate merge ordering, or gate merges on bundle readiness.

The `EpicState` model tracks `completed_children` and `failed_children` but has
no concept of "approved but not yet merged" children — approval and merge are
conflated into a single step.

## Decision

Introduce an **EpicMergeCoordinator** that intercepts the merge path in
`PostMergeHandler.handle_approved()` to support four merge strategies:

1. **`independent`** (default): No coordination — PRs merge immediately on
   approval. This preserves current behavior and requires no configuration.

2. **`bundled`**: Hold approved PRs until all children in the epic are approved,
   then auto-merge the full bundle. The coordinator applies a
   `hydraflow-approved` label to each approved child and checks bundle readiness
   after each approval.

3. **`bundled_hitl`**: Same as `bundled`, but instead of auto-merging when the
   bundle is ready, escalate to HITL for human sign-off before the merge batch
   executes.

4. **`ordered`**: Dependency-aware merge ordering. Children specify merge order
   or dependencies, and the coordinator merges them sequentially in the correct
   order once all are approved.

### Merge flow

```
Review approves PR
  → PostMergeHandler.handle_approved()
    → EpicMergeCoordinator.should_hold_merge(issue)
      → If independent: proceed to merge (no change)
      → If bundled/bundled_hitl/ordered:
        1. Apply `hydraflow-approved` label
        2. Record in EpicState.approved_children
        3. Check bundle readiness (all children approved?)
        4. If ready:
           - bundled: auto-merge all approved children
           - bundled_hitl: escalate to HITL with merge instructions
           - ordered: merge in dependency order
        5. If not ready: hold (do not merge), log status
```

### Model changes

Extend `EpicState` with:
- `approved_children: list[int]` — children whose PRs passed review but are held
  from merge.
- `merge_strategy: str` — one of `independent`, `bundled`, `bundled_hitl`,
  `ordered` (default: `independent`).

### Integration point

`EpicMergeCoordinator` is injected into `PostMergeHandler` alongside the existing
`EpicManager`. The coordinator's `should_hold_merge()` is called before the
`merge_pr()` call. When the coordinator holds a merge, it returns `False` and
the handler skips the merge without escalating to HITL (the PR remains open and
approved).

### Configuration

Add `epic_merge_strategy` to `HydraFlowConfig` as a global default. Per-epic
overrides can be set via a label convention (e.g., `epic-strategy:bundled`) or
an epic body directive parsed during registration.

## Consequences

**Positive:**
- Enables coordinated feature releases — all child PRs land together or not at
  all, preventing partially-shipped features.
- Supports dependency-aware merge ordering for complex epics where child issues
  build on each other.
- Human gating (`bundled_hitl`) provides a safety valve for high-risk changes.
- Default `independent` strategy preserves existing behavior — zero migration
  cost for current users.
- `hydraflow-approved` label provides visibility into which PRs are approved but
  held, useful for dashboards and manual inspection.

**Trade-offs:**
- Adds complexity to the merge path — `PostMergeHandler` gains a new
  interception point that must be tested for all four strategies.
- Held PRs may become stale if the bundle takes a long time to complete. Needs a
  staleness timeout or periodic rebase mechanism.
- `ordered` strategy requires dependency metadata (merge order or explicit
  dependency graph) that must be authored and maintained in epic bodies.
- Bundle failures are harder to reason about — if one child fails review, the
  entire bundle is blocked. Clear status reporting and HITL escalation paths are
  needed.
- Merge conflicts become more likely when multiple PRs are held open
  simultaneously. A conflict resolution strategy (sequential rebase before merge)
  is needed for `bundled` and `ordered`.

## Alternatives considered

1. **Merge queue via GitHub merge queue (branch protection).**
   Rejected: GitHub's native merge queue does not support epic-scoped bundling
   or dependency ordering. It operates at the individual PR level and cannot
   hold PRs pending sibling approval.

2. **Post-merge revert on partial bundle failure.**
   Rejected: reverting merged PRs is destructive and complex. Holding merges
   until the bundle is ready avoids the need for rollback entirely.

3. **Manual coordination via HITL for all epic merges.**
   Rejected: too slow for the common case. The `independent` and `bundled`
   strategies automate the majority of cases, with `bundled_hitl` available
   when human oversight is explicitly requested.

## Related

- Source memory: #1684
- ADR issue: #1702
- `src/post_merge_handler.py` (`handle_approved` — merge interception point)
- `src/epic.py` (`EpicManager`, `EpicCompletionChecker`)
- `src/models.py` (`EpicState` — model to extend)
- `src/review_phase.py` (`_handle_approved_merge` — review-to-merge flow)
- `src/epic_monitor_loop.py` (stale epic detection — relevant for held bundles)
