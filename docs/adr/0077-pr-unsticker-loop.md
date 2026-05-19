# ADR-0077 — PRUnstickerLoop: Goal-Driven HITL PR Resolution

**Status:** Proposed
**Date:** 2026-05-19

## Context

HITL-labeled PRs get stuck for three distinct reasons: merge conflicts, CI failures, and generic stuck states where the auto-agent ran out of attempts. Each cause requires different resolution logic. Without an autonomous resolution path, stuck PRs accumulate in the HITL queue and require human intervention even when the fix is mechanical (rebase, re-trigger CI, supply missing context).

`MergeStateWatcherLoop` handles conflict detection broadly across all PRs. `PRUnstickerLoop` handles the narrower case: open PRs that already carry a HITL label with a known stuck cause, and need targeted resolution.

## Decision

`PRUnstickerLoop` (`src/pr_unsticker_loop.py`) subclasses `BaseBackgroundLoop` and delegates to `PRUnsticker` to resolve all HITL causes on each tick. The loop:

1. Queries `PRPort.list_hitl_items(config.hitl_label)` for open HITL issues.
2. Filters to items with an associated open PR (`item.pr > 0`).
3. Calls `PRUnsticker.unstick(active_pr_items)` which dispatches by cause.

The separation of `PRUnstickerLoop` (tick scheduling, filtering) from `PRUnsticker` (resolution logic) keeps the resolution strategies independently testable and lets new resolution strategies be added to `PRUnsticker` without touching the loop.

Kill-switch: `enabled_cb("pr_unsticker")` and `config.pr_unsticker_loop_enabled` (ADR-0049). Interval: `config.pr_unstick_interval`.

## Consequences

- HITL issues with associated PRs are processed autonomously; human intervention is needed only when all resolution strategies are exhausted.
- HITL issues without PRs are ignored (they have a different resolution path — the preflight loop).
- The loop's output is structured stats from `PRUnsticker.unstick`, making it observable via the dashboard.

## Alternatives considered

- **Fold into `MergeStateWatcherLoop`.** Rejected: the watcher is a broad periodic scan; the unsticker is a targeted HITL resolver. The two have different scopes, different filters, and different resolution logic. Merging them would couple unrelated concerns.
- **Inline in HITL phase.** Rejected: the HITL phase runs synchronously in the pipeline; autonomous resolution must be asynchronous to avoid blocking.

## Related

- [ADR-0029](0029-caretaker-loop-pattern.md) — caretaker loop pattern
- [ADR-0049](0049-trust-loop-kill-switch-convention.md) — kill-switch convention
- [ADR-0075](0075-merge-state-watcher-loop.md) — `MergeStateWatcherLoop` (complementary)
- `src/pr_unsticker_loop.py:PRUnstickerLoop`
- `src/pr_unsticker.py:PRUnsticker`
