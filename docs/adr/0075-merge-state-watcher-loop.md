# ADR-0075 — MergeStateWatcherLoop: Autonomous Conflict Detection and Rebase

**Status:** Proposed
**Date:** 2026-05-19

## Context

Any open PR can go DIRTY against `main` at any time — when another PR lands ahead of it, when a Dependabot bump changes a lockfile, or when an agent PR lags behind a staging promotion. Without a watcher, dirty PRs sit unresolved until a human or another loop trips over them.

`PRUnstickerLoop` handles HITL-labeled PRs with known stuck causes. What's missing is a broader, periodic scan that catches PRs going dirty before they reach HITL, and auto-rebases them preemptively.

## Decision

`MergeStateWatcherLoop` (`src/merge_state_watcher_loop.py`) subclasses `BaseBackgroundLoop` and runs every 600 seconds (10 minutes). Each tick it delegates to `MergeStateWatcher.unstick_conflicts()`, which:

1. Queries `PRPort` for open PRs across the managed repository.
2. Filters out PRs labeled `hydraflow-hitl` (already being handled by `PRUnstickerLoop`) and `hydraflow-review` (active reviewer worktree) to avoid stepping on in-progress work.
3. For remaining DIRTY PRs, attempts an auto-rebase.
4. If rebase fails, escalates via the HITL path.

The filter is intentionally broad: RC promotion PRs, Dependabot bumps, agent PRs, and manual PRs all benefit from auto-rebase. Narrowing the scope would leave dirty PRs on the floor.

Kill-switch: `enabled_cb("merge_state_watcher")` and `config.merge_state_watcher_loop_enabled` (ADR-0049).

## Consequences

- Dirty PRs are detected and rebased within a 10-minute window in steady state.
- PRs already in active human or bot review are not touched.
- The combination of `MergeStateWatcherLoop` (broad periodic) and `PRUnstickerLoop` (HITL-specific) covers the full PR lifecycle without overlap.

## Alternatives considered

- **Single unified unsticker.** Rejected: HITL PRs need cause-specific logic (conflict resolution, CI triage, generic stuck) that would bloat a general-purpose watcher.
- **Event-driven on PR state change.** Rejected: requires GitHub webhook infrastructure; the polling model is consistent with other caretaker loops.

## Related

- [ADR-0029](0029-caretaker-loop-pattern.md) — caretaker loop pattern
- [ADR-0049](0049-trust-loop-kill-switch-convention.md) — kill-switch convention
- `src/merge_state_watcher_loop.py:MergeStateWatcherLoop`
- `src/merge_state_watcher.py:MergeStateWatcher`
