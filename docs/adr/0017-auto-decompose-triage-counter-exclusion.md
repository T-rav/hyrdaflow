# ADR-0017: Auto-Decompose Triage Path Excluded from Session Counter

**Status:** Accepted
**Date:** 2026-03-01

## Context

In the triage phase (`src/triage_phase.py`), when an issue scores above the
`epic_decompose_complexity_threshold` and `epic_auto_decompose` is enabled,
`_maybe_decompose()` creates an epic plus child issues on GitHub, closes the
original issue, and marks it as `"decomposed"` in the state tracker.

Both call sites that execute `increment_session_counter("triaged")` sit
inside branches guarded by `if not _maybe_decompose(...)`:

1. **Normal plan routing** (line 121): counter incremented only when the issue
   is transitioned to the `planner_label` queue — i.e., when decomposition
   did **not** fire.
2. **ADR fast-path** (line 97): counter incremented when a valid ADR issue is
   routed directly to `ready` — decomposition is not attempted for ADR issues.

When `_maybe_decompose()` returns `True`, the original issue is closed and
replaced by an epic + children. The `"triaged"` session counter is **not**
incremented for the original issue, nor for any of the newly created child
issues (those re-enter the pipeline as fresh `find`-labelled issues and will
be individually triaged and counted later).

This behaviour was introduced in PR #1689 (issue #1542) but was not
explicitly documented as a design decision at the time. Memory #1729
flagged the gap: if epic auto-decomposition is used frequently, triage
throughput metrics will be systematically lower than the actual number of
issues processed by the triage phase.

## Decision

The exclusion of auto-decomposed issues from the `"triaged"` session counter
is **intentional and should remain as-is**. The rationale:

1. **Avoid double-counting.** The original issue is closed, not planned. Its
   child issues will each be triaged individually and increment the counter
   when they reach the planning queue. Counting the parent would inflate the
   metric because the parent never enters planning or implementation.

2. **Counter semantics = issues entering planning.** The `"triaged"` counter
   represents issues that successfully passed triage **and were routed to the
   next pipeline phase** (plan or ready). A decomposed issue is neither
   planned nor implemented — it is replaced. The counter should reflect
   actionable throughput, not raw processing volume.

3. **Decomposition is observable via other signals.** The state tracker
   records `mark_issue(id, "decomposed")`, the `record_issue_created()`
   counter tracks child issue creation, and the `EpicManager` maintains
   epic-to-child mappings. These provide sufficient visibility into
   decomposition activity without conflating it with triage throughput.

4. **HITL-routed issues are already excluded.** Issues escalated to HITL
   during triage also do not increment the counter, establishing a consistent
   pattern: only issues that proceed forward in the pipeline are counted.

## Consequences

**Positive:**
- Triage throughput metrics accurately reflect issues entering
  planning/implementation, enabling reliable capacity planning.
- No risk of double-counting when child issues are subsequently triaged.
- Consistent counter semantics across all triage exit paths (plan, ready,
  HITL, decomposed).

**Trade-offs:**
- Dashboard triage counts will understate the total volume of issues
  _processed_ by the triage phase when decomposition is active. Operators
  must check decomposition-specific metrics (epic count, child issue count)
  for full visibility.
- If a future change introduces a `"decomposed"` session counter, callers
  displaying "total triage work" will need to sum `triaged + decomposed`.

## Alternatives considered

1. **Increment `"triaged"` for decomposed issues too.**
   Rejected: inflates the counter with issues that never enter planning,
   making throughput metrics unreliable for capacity planning. Also risks
   double-counting when child issues are subsequently triaged.

2. **Add a separate `"decomposed"` session counter.**
   Viable future enhancement but not required today — decomposition activity
   is already observable via `mark_issue(id, "decomposed")` and
   `record_issue_created()`. A dedicated counter could be added if dashboard
   reporting needs evolve.

3. **Count decomposed as `triaged` but subtract children later.**
   Rejected: introduces coupling between counter logic and epic lifecycle
   tracking, making the metric harder to reason about.

## Related

- Source memory: #1729
- Original implementation: PR #1689 (issue #1542)
- `src/triage_phase.py` — `_maybe_decompose()`, `triage_issues()`
- `src/state.py` — `StateTracker.increment_session_counter()`,
  `StateTracker.mark_issue()`
- ADR-0001 (Five concurrent async loops — triage is loop 1)
