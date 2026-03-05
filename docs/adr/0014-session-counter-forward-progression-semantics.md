# ADR-0014: Session Counter Forward-Progression Semantics

**Status:** Accepted
**Date:** 2026-03-01

## Context

`SessionCounters` (introduced in PR #1689, issue #1542) tracks per-session
completion counts for each pipeline stage: `triaged`, `planned`, `implemented`,
`reviewed`, and `merged`. These counters drive the dashboard's
`completed_session` metric via `build_pipeline_stats` in `orchestrator.py`.

Three stages — triage, plan, and implement — follow a consistent
**forward-progression** pattern: the counter increments exactly once per issue,
only when the issue successfully exits that stage and transitions to the next
one. Failures, escalations to HITL, and retries do not increment.

| Stage | Increments when | Guard |
|-----------|----------------------------------------------|-------|
| `triaged` | Issue transitions from triage to `plan` or `ready` | Transition call succeeds |
| `planned` | Plan posted and label swapped to `ready`, or issue closed as already satisfied | Plan completion path |
| `implemented` | PR created and issue transitions to `review` | `result.success` is `True` |

The **review** stage counter in `_record_review_outcome` (`review_phase.py:440`)
increments only when the verdict is `APPROVE`. This is semantically correct
for forward-progression — non-approved reviews (REQUEST_CHANGES, NEEDS_CHANGES)
represent retry loops, not successful exits from the stage. An earlier version
of the code (noted in memory #1697) called `increment_session_counter` for all
verdicts, which inflated the count when issues cycled through multiple review
rounds. The current code guards on `APPROVE`, aligning with the
forward-progression pattern.

A secondary risk exists in `session_counter_map` inside `build_pipeline_stats`
(`orchestrator.py:443`). This dict maps dashboard stage names to
`SessionCounters` field names. If an unknown stage is added and mapped to
another stage's field name (e.g., mapping `"hitl"` to `"reviewed"` instead of
`""`), that stage's count leaks into the wrong display column. The current code
correctly maps `"hitl"` to `""` so the `if counter_field else 0` guard returns
zero.

## Decision

Adopt **forward-progression-only** as the canonical semantics for all
`SessionCounters` stage counters:

1. **Increment once per issue, on successful stage exit.** A counter increments
   when the issue irreversibly transitions to the next pipeline stage. Retries,
   failures, and intermediate states do not increment.

2. **Guard on transition, not on attempt.** The increment must be co-located
   with the actual state transition (label swap, PR creation, merge) — not in
   shared outcome-recording paths that fire for all verdicts or results.

3. **Map unknown stages to empty string in `session_counter_map`.** Any stage
   without a dedicated `SessionCounters` field must map to `""` so the
   `if counter_field else 0` guard produces zero. Never map an unknown stage
   to another stage's field name.

4. **New counters follow the same pattern.** When adding a stage counter (e.g.,
   for HITL completions), place the `increment_session_counter` call at the
   point where the issue exits that stage successfully, not where the stage
   records any outcome.

## Consequences

**Positive:**
- Dashboard `completed_session` metrics accurately reflect unique issues that
  passed through each stage, enabling reliable throughput measurement.
- Counter cardinality matches issue cardinality: each issue contributes at most
  one increment per stage, making counts directly comparable across stages.
- Pattern is simple to follow and audit: find the transition call, confirm the
  counter increment is adjacent to it.

**Trade-offs:**
- Retries and failures are invisible in session counters. Operators who want
  attempt-level metrics must use `record_review_verdict` or the event bus, not
  `SessionCounters`.
- The `reviewed` counter does not distinguish between normal PR approvals and
  ADR-specific review completions (both increment on success). This is
  acceptable because both represent a successful exit from the review stage.
- Adding new stages requires updating both `SessionCounters` and
  `session_counter_map` in lockstep; forgetting the map entry silently shows
  zero rather than erroring.

## Alternatives considered

1. **Attempt-counting semantics (increment on every review outcome).**
   Rejected: inflates counts when issues cycle through REQUEST_CHANGES rounds,
   making `completed_session` unreliable for throughput measurement. Attempt
   counts are available through other mechanisms (`record_review_verdict`).

2. **Separate attempt and completion counters per stage.**
   Rejected for now: doubles the counter surface area without a clear dashboard
   consumer. Can be revisited if operators need attempt-level visibility in the
   dashboard.

3. **Strict enum-based mapping (error on unknown stage).**
   Rejected: the silent-zero behavior is safer for forward compatibility. New
   stages can be added to the orchestrator loop before their counters exist
   without crashing the dashboard.

## Related

- Source memory: #1697
- Implementation: PR #1689, issue #1542
- `src/models.py:SessionCounters` — counter model definition
- `src/state.py:StateTracker.increment_session_counter` — increment logic
- `src/triage_phase.py:97,121` — triaged counter (forward-progression)
- `src/plan_phase.py:120,180` — planned counter (forward-progression)
- `src/implement_phase.py:419` — implemented counter (forward-progression)
- `src/review_phase.py:441` — reviewed counter (guarded on APPROVE)
- `src/post_merge_handler.py:141` — merged counter (forward-progression)
- `src/orchestrator.py:443` — session_counter_map (stage-to-field mapping)
