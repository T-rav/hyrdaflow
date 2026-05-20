# ADR-0081 — EpicSweeperLoop: Autonomous Completion-Based Epic Auto-Close

**Status:** Proposed
**Date:** 2026-05-19

## Context

When all sub-issues of an epic are resolved, the epic itself should close automatically. Without an autonomous sweeper the completed epics accumulate as open issues, cluttering the backlog and hiding the factory's true progress signal. The existing `EpicMonitorLoop` (ADR-0079) handles stale detection but not completion-based closure — stale and complete are distinct states that warrant separate resolution paths.

Sub-issues are registered two ways: formally as `EpicState` children and informally as checkbox-style refs in the epic body. A sweeper that only handles one representation leaves the other unswept.

## Decision

`EpicSweeperLoop` (`src/epic_sweeper_loop.py`) subclasses `BaseBackgroundLoop` and runs on `config.epic_sweep_interval`. Each tick:

1. Fetches all open issues carrying `config.epic_label` (cap 50; logs a warning if the cap is hit).
2. For each epic, collects sub-issue references by merging `EpicState.child_issues` and `parse_epic_sub_issues(body)` — both formal and checkbox refs are included.
3. Skips epics with no sub-issues.
4. For epics with sub-issues, fetches each referenced issue via `IssueFetcherPort`. If any sub-issue is still open (or not found), the epic is skipped this tick. If a sub-issue is missing from GitHub, the epic is skipped and a warning is logged prompting removal of the stale ref.
5. When all sub-issues are closed: updates checkboxes via `check_all_checkboxes`, applies `config.fixed_label`, posts a completion comment, and closes the epic.

Kill-switch: `enabled_cb("epic_sweeper")` and `config.epic_sweeper_loop_enabled` (ADR-0049).

## Consequences

- Completed epics close within one tick interval of their last sub-issue closing.
- Both formal (`EpicState`) and informal (checkbox) sub-issue registrations are swept — no representation is privileged.
- A stale body reference (deleted sub-issue) blocks auto-close for that epic and surfaces as a warning, prompting a human to clean the ref rather than silently closing an incomplete epic.
- Per-epic exceptions are caught and logged without aborting the full sweep — one bad epic does not stall the rest.

## Alternatives considered

- **Fold into `EpicMonitorLoop`.** Rejected: stale detection and completion-based closure are independent concerns with different triggers and different side-effects. Coupling them makes each harder to test and reason about.
- **Event-driven close on the last sub-issue merge.** Rejected: requires event wiring into every sub-issue close path; the periodic sweep is simpler and robust to out-of-band closes (manual close, other bots).

## Related

- [ADR-0029](0029-caretaker-loop-pattern.md) — caretaker loop pattern
- [ADR-0049](0049-trust-loop-kill-switch-convention.md) — kill-switch convention
- [ADR-0080](0080-epic-monitor-loop.md) — `EpicMonitorLoop` (complementary stale detection)
- `src/epic_sweeper_loop.py:EpicSweeperLoop`
- `src/epic.py:parse_epic_sub_issues`, `check_all_checkboxes`
