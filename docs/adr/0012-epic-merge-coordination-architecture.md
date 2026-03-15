# ADR-0012: Epic Merge Coordination Architecture

**Status:** Accepted
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

Intercept the merge path in `PostMergeHandler.handle_approved()` to support
four merge strategies, coordinated between `PostMergeHandler._should_defer_merge()`
and `EpicManager.on_child_approved()`:

1. **`independent`** (default): No coordination — PRs merge immediately on
   approval. This preserves current behavior and requires no configuration.

2. **`bundled`**: Hold approved PRs until all children in the epic are approved,
   then auto-merge the full bundle. The coordinator applies a
   `hydraflow-approved` label to each approved child and checks bundle readiness
   after each approval.

3. **`bundled_hitl`**: Same as `bundled`, but instead of auto-merging when the
   bundle is ready, escalate to HITL for human sign-off before the merge batch
   executes.

4. **`ordered`**: Registration-order merge sequencing. Children are merged in
   the order they were registered in `EpicState.child_issues`. Explicit
   dependency metadata (BLOCKS/BLOCKED_BY) is not yet implemented; callers
   must register children in the correct order at epic creation time.

### Merge flow

```
Review approves PR
  → PostMergeHandler.handle_approved()
    → _notify_epic_approval(issue_number)          [unconditional w.r.t. merge strategy]
      → EpicManager.on_child_approved()
      → Records approval in EpicState.approved_children
      → Applies hydraflow-approved label to the child PR (non-independent strategies only)
      → If strategy ≠ independent AND bundle ready (all siblings approved or completed):
        - bundled: auto-merge all via _handle_bundled_ready() → release_epic()
        - bundled_hitl: escalate to HITL with merge instructions
        - ordered: merge in registration order via _handle_ordered_ready() → release_epic()
      → If strategy ≠ independent AND bundle not yet ready: hold, await siblings
    → _should_defer_merge(issue_number)            [boolean: should this PR skip merge_pr()?]
      → Checks parent epics via EpicManager.find_parent_epics()
      → Returns True if any parent epic uses bundled/bundled_hitl/ordered
      → If True: return early — do not call merge_pr() for this issue now
      → If False (all parents independent, or no parent epics): proceed to merge
```

### Model changes

Extend `EpicState` with:
- `approved_children: list[int]` — children whose PRs passed review but are held
  from merge.
- `merge_strategy: str` — one of `independent`, `bundled`, `bundled_hitl`,
  `ordered` (default: `independent`).

### Integration point

`PostMergeHandler.handle_approved()` first calls `_notify_epic_approval()` (which
calls `EpicManager.on_child_approved()`) unconditionally w.r.t. merge strategy —
recording the approval, checking bundle readiness, and dispatching to the appropriate
strategy handler (`_handle_bundled_ready`, `_handle_bundled_hitl_ready`, or
`_handle_ordered_ready`). Only after that does it call `_should_defer_merge()`, which
queries `EpicManager.find_parent_epics()` to decide whether to proceed to merge or
hold. When a defer is indicated, `handle_approved()` returns early without merging
and the PR remains open and approved until the bundle is ready.

### Relationship to ADR-0011

ADR-0011 prohibits placing **release-creation** logic in `PostMergeHandler`, directing
it instead to `EpicCompletionChecker._try_close_epic()`. ADR-0012 intentionally places
**merge-coordination** hooks (approval notification and defer checks) in
`PostMergeHandler` because this is the only point in the pipeline where the merge
decision can be intercepted before execution. These are distinct concerns:
release-creation runs *after* all children complete and the epic closes, while
merge-coordination runs *before* each individual merge to decide whether to proceed
or hold. ADR-0012 does not supersede ADR-0011; the two ADRs govern different stages
of the epic lifecycle.

### `hydraflow-approved` label lifecycle

The `hydraflow-approved` label tracks child PRs that have passed review but are held
from merge under a coordinated strategy:

- **Applied:** By `EpicManager.on_child_approved()` when a child PR passes review
  and belongs to an epic with a non-independent merge strategy (`bundled`,
  `bundled_hitl`, or `ordered`).
- **Removed on merge:** By `release_epic()` after the bundle is ready and the PR
  is successfully merged.
- **Removed on failure:** When a child PR fails review or CI while held, the label
  is removed by `EpicManager.on_child_failed()` and the child moves to
  `EpicState.failed_children`.
- **Removed on cancellation:** If the epic is cancelled or the child is removed
  from the epic's `child_issues` list, the label is removed during cleanup.

### Failure path

When a held child PR fails review while siblings remain approved-but-held, the
`failed_children` list in `EpicState` is updated. The bundle readiness check
(`EpicProgress.ready_to_merge`) requires `failed == 0`, so a single failure
blocks the entire bundle. Recovery requires manual intervention: re-trigger
review on the failed child, or remove it from the epic's `child_issues` list.

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
- `ordered` strategy currently uses registration order only; explicit dependency
  metadata (BLOCKS/BLOCKED_BY graphs) is not yet implemented.
- Bundle failures block all siblings — if one child fails review, approved
  siblings remain held indefinitely until the failure is resolved or the child
  is removed from the epic.
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
- `src/post_merge_handler.py` (`handle_approved`, `_should_defer_merge` — merge interception)
- `src/epic.py` (`EpicManager.on_child_approved`, `_handle_bundled_ready`, `_handle_ordered_ready`, `_get_merge_order`)
- `src/models.py` (`EpicState` — model to extend)
- `src/review_phase.py` (`_handle_approved_merge` — review-to-merge flow)
- `src/epic_monitor_loop.py` (stale epic detection — relevant for held bundles)
