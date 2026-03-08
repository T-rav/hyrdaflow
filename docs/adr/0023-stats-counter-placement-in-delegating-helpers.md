# ADR-0023: Stats Counter Placement When Delegating to Conditional Helpers

**Status:** Proposed
**Date:** 2026-03-08

## Context

Several HydraFlow phases delegate outcome routing to helper methods that
conditionally increment stats counters on success. For example, in the ADR
reviewer (`src/adr_reviewer.py`), `_route_result()` delegates to
`_route_to_triage()` which may succeed (auto-triaged) or fail (falling back to
`_escalate_to_hitl()`). When a stats counter like `escalated` is placed
unconditionally at the call site — after the delegation call — it increments
regardless of which path the helper took, causing double-counting.

Concretely, if `_triage_or_hitl()` internally increments `auto_triaged` on
success, and the caller unconditionally increments `escalated` after the call,
then a successful triage route counts as *both* `auto_triaged` and `escalated`.
This violates the mutual-exclusivity invariant: a single event should increment
exactly one counter along its resolution path.

This pattern was identified in memory #2298 and mirrors the counter-placement
principle established in ADR-0017 (auto-decompose triage counter exclusion),
where `"triaged"` is only incremented inside branches that actually route
forward to the planning queue.

## Decision

**Stats counters that depend on a helper's outcome must be placed inside the
helper's branching logic, not unconditionally at the call site.**

The rule:

1. If a helper method has two or more exit paths (e.g., success vs fallback),
   each path should increment its own counter internally.
2. The caller must not increment a counter after invoking the helper unless
   the counter is truly unconditional (i.e., it should fire regardless of
   which path the helper took).
3. When a helper returns a boolean indicating which path was taken, the caller
   may use that return value to conditionally increment — but placing the
   counter inside the helper is preferred to keep the stat logic co-located
   with the branching logic.

Applied to `_route_result()` and similar delegation patterns: the `escalated`
counter belongs inside the else/fallback branch (when `_route_to_triage()`
returns `False`), not unconditionally after the call. A separate
`auto_triaged` counter belongs inside the success branch (when
`_route_to_triage()` returns `True`).

## Consequences

**Positive:**
- Eliminates double-counting bugs where a single event inflates multiple
  mutually exclusive counters.
- Co-locates counter logic with branching logic, making stats behavior
  easier to audit and reason about.
- Consistent with the counter-placement pattern established in ADR-0017.

**Trade-offs:**
- Counter increments are distributed across helper methods rather than
  centralized at the call site, which can make it harder to see all stats
  updates in one place. Code reviewers must inspect helpers to verify
  counter behavior.
- Refactoring a helper's internal branches requires updating the associated
  counters, increasing the surface area of stats-related changes.

## Alternatives considered

1. **Keep counters at the call site, use the helper's return value to branch.**
   Viable but scatters the concern: the caller must know the helper's internal
   semantics to pick the right counter. Preferred only when the helper is a
   thin wrapper with obvious return semantics.

2. **Return an enum from the helper indicating the outcome.**
   The caller uses the enum to increment the appropriate counter. This keeps
   counters centralized but adds boilerplate. Appropriate for helpers with
   three or more distinct outcomes.

3. **Unconditionally increment a single "processed" counter and track
   sub-outcomes separately.**
   Rejected: loses the mutual-exclusivity invariant that makes individual
   counters meaningful for capacity planning and alerting.

## Related

- Source memory: #2298
- Issue: #2306
- ADR-0017 (Auto-Decompose Triage Counter Exclusion) — establishes the
  counter-placement principle for triage paths
- ADR-0014 (Session Counter Forward-Progression Semantics) — defines
  counter semantics across the pipeline
- `src/adr_reviewer.py` — `_route_result()`, `_route_to_triage()`,
  `_escalate_to_hitl()`
- `src/triage_phase.py` — `_maybe_decompose()`, counter exclusion pattern
