# ADR-0080 — EpicMonitorLoop: Autonomous Stale-Epic Detection and Progress Refresh

**Status:** Proposed
**Date:** 2026-05-19

## Context

Open epics accumulate in the issue tracker without any automated signal of whether they are progressing or stagnating. Without a periodic staleness check, epics can drift unnoticed for weeks — sub-issues merge, the epic stays open, and the backlog obscures the true pipeline state. The `EpicManager` already has `check_stale_epics` and `get_all_progress` logic but no autonomous trigger to run it on a cadence.

## Decision

`EpicMonitorLoop` (`src/epic_monitor_loop.py`) subclasses `BaseBackgroundLoop` and runs on `config.epic_monitor_interval`. Each tick:

1. Calls `EpicManager.check_stale_epics()` to detect epics that have been open beyond the staleness threshold and fires the appropriate escalation or alert actions.
2. Calls `EpicManager.refresh_cache()` to keep the in-memory epic state current.
3. Returns `{"stale_count": N, "tracked_epics": M}` as the structured tick result for observability.

The loop delegates all business logic to `EpicManager`, keeping tick scheduling decoupled from staleness policy.

Kill-switch: `enabled_cb("epic_monitor")` and `config.epic_monitor_loop_enabled` (ADR-0049).

## Consequences

- Stale epics surface automatically on each tick; the pipeline state is observable without manual audit.
- Adding new staleness policies only requires changes to `EpicManager`, not the loop.
- The cache refresh ensures downstream consumers reading epic progress always see a recent snapshot.

## Alternatives considered

- **Inline in the issue pipeline phase.** Rejected: staleness detection is a caretaking concern, not a per-issue routing concern. The pipeline phase is synchronous; periodic caretaking must be asynchronous.
- **One-shot script on a cron.** Rejected: the in-process loop is already available, observable via the dashboard, and respects the kill-switch convention uniformly.

## Related

- [ADR-0029](0029-caretaker-loop-pattern.md) — caretaker loop pattern
- [ADR-0049](0049-trust-loop-kill-switch-convention.md) — kill-switch convention
- [ADR-0081](0081-epic-sweeper-loop.md) — `EpicSweeperLoop` (complementary auto-close)
- `src/epic_monitor_loop.py:EpicMonitorLoop`
- `src/epic.py:EpicManager`
