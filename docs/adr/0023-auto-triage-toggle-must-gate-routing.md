# ADR-0023: Auto-Triage Toggle Must Gate Routing, Not Just Stat Tracking

**Status:** Proposed
**Date:** 2026-03-15

## Context

HydraFlow's ADR review pipeline includes an `adr_auto_triage` config toggle
that controls whether fixable issues are routed back through the triage pipeline
(creating a follow-up issue) or escalated to HITL for human intervention.

> **Note:** The `adr_auto_triage` toggle is not yet defined in `config.py` or
> enforced in `adr_reviewer.py`. This ADR describes the intended design for
> when the toggle is implemented. The canonical toggle name is
> `adr_auto_triage` (not `adr_review_auto_triage`).

A bug pattern was identified where a routing method unconditionally calls
`_route_to_triage()` and only conditionally increments the `auto_triaged` stat
counter based on a toggle value.  This means:

- When the toggle is disabled, the system still routes issues to triage
  (creating follow-up issues and bypassing HITL), but simply does not count them
  in the `auto_triaged` metric.
- The operator believes HITL escalation is active, but issues are silently
  being auto-triaged — a correctness bug masked as a stats-only difference.

This pattern follows the same config-guard principle established in
[ADR-0015 (Protocol-Based Callback Injection Gate Pattern)](0015-protocol-callback-gate-pattern.md),
which defines a four-phase protocol where the **config guard** is always the
first step: check the feature flag and return early if disabled.

Three routing paths require audit for toggle consistency:

| Method                              | Purpose                                          |
|-------------------------------------|--------------------------------------------------|
| `_route_pre_validation_failure()`   | Routes ADRs that fail structural validation      |
| `_execute_triage_or_hitl()`         | Routes post-council rejected/changes-requested   |
| `_handle_duplicate()`               | Always escalates duplicates to HITL (correct)    |

The fix will unify post-council routing through `_execute_triage_or_hitl()`,
which gates the `_route_to_triage()` call on the toggle before any action is
taken.  `_route_pre_validation_failure()` must also check the toggle before
attempting triage.

## Decision

Adopt the following rule for config-gated routing in HydraFlow workers:

1. **A config toggle that controls routing must gate the routing call itself,
   not just downstream side-effects like stat counters.**  If
   `adr_auto_triage` is `False`, no code path may call `_route_to_triage()`.
   The toggle must be the first condition checked, before any issue creation or
   API call occurs.

   Anti-pattern versus correct toggle-first guard pattern (applied in `_execute_triage_or_hitl`):

   ```python
   # Anti-pattern: triage call is unconditional
   routed = await self._route_to_triage(result, reason=reason)
   if not routed:
       await self._escalate_to_hitl(result, reason=reason)

   # Correct pattern: gate triage on the toggle
   if not self._config.adr_auto_triage:
       await self._escalate_to_hitl(result, reason=reason)
       return
   routed = await self._route_to_triage(result, reason=reason)
   if not routed:
       await self._escalate_to_hitl(result, reason=reason)
   ```

2. **Centralise gated routing through a single helper.**  All post-council
   routing decisions (reject, changes requested, no consensus) must flow
   through `_execute_triage_or_hitl()`, which encapsulates the toggle check,
   the triage attempt, the stat increment, and the HITL fallback in one place.
   Individual routing call-sites must not duplicate this logic.

3. **Audit all routing paths when adding or modifying a routing toggle.**
   When a new toggle is introduced or an existing one is changed, every method
   that could trigger the gated action must be reviewed for consistency.  A
   grep for the routing target (e.g. `_route_to_triage`) is the minimum
   verification step.

4. **Stats must be coupled to the action, not to the toggle check.**  See
   [ADR-0023 (Stats Counter Placement in Delegating Helpers)](0023-stats-counter-placement-in-delegating-helpers.md)
   for the full treatment of this principle.  In brief: the `auto_triaged`
   counter increments inside the helper's success branch, and `escalated`
   increments inside the fallback branch — never unconditionally at the
   call site.

### Verification checklist

When reviewing any routing method that calls both `_route_to_triage` and
`_escalate_to_hitl`:

- Confirm the `adr_auto_triage` toggle is checked **before** the triage call.
- Confirm the toggle-off path calls HITL and returns without invoking triage.
- Confirm tests enable the toggle when asserting triage is called, and disable
  it when asserting HITL is called directly.

## Consequences

**Positive:**

- Eliminates silent toggle bypass — operators can trust that disabling
  auto-triage actually disables it across all code paths.
- Centralised routing helper (`_execute_triage_or_hitl`) reduces duplication
  and makes the routing logic auditable from a single location.
- Stats accurately reflect system behaviour, improving observability and
  debugging.
- Establishes a review checklist item: "does every call-site for the gated
  action check the toggle?"

**Trade-offs:**

- Routing changes require touching the centralised helper, which could become
  a merge-conflict hotspot if multiple features modify routing simultaneously.
- Strict coupling between toggle and action means there is no way to
  "soft-launch" auto-triage for a subset of routing paths without introducing
  a separate, path-scoped toggle.
- Auditing all routing paths on toggle changes adds review overhead, though
  this is a one-time cost per change and prevents a class of correctness bugs.

## Alternatives considered

1. **Decorator-based toggle enforcement.**
   A `@gated_by("adr_auto_triage")` decorator that wraps `_route_to_triage()`
   and short-circuits when the toggle is off.
   Rejected: adds indirection and makes the fallback-to-HITL path harder to
   follow.  The explicit `if` check in `_execute_triage_or_hitl()` is clearer.

2. **Toggle check inside `_route_to_triage()` itself.**
   Move the toggle check into the routing method so callers cannot forget it.
   Rejected: `_route_to_triage()` is a low-level method that should remain
   toggle-unaware.  The toggle is a policy decision that belongs in the
   orchestration layer (`_execute_triage_or_hitl`), not in the action method.

3. **Separate toggle per routing path.**
   E.g. `adr_auto_triage_pre_review`, `adr_auto_triage_post_council`.
   Rejected: over-engineering for the current use case.  A single toggle with
   centralised enforcement is sufficient.  Can revisit if granular control is
   needed.

## Related

- **Supersedes:** [ADR-0023 (Gate Triage Call on Config Toggle, Not Just HITL Fallback)](0023-gate-triage-call-not-hitl-fallback.md)
  - Absorbed: toggle-first guard pattern code samples (Decision §1) and verification checklist
- **Cross-references:**
  - [ADR-0015 (Protocol-Based Callback Injection Gate Pattern)](0015-protocol-callback-gate-pattern.md) — Rule 1 (config-guard-first) is a specific application of ADR-0015's four-phase protocol (config guard → bypass → execute → telemetry)
  - [ADR-0023 (Stats Counter Placement in Delegating Helpers)](0023-stats-counter-placement-in-delegating-helpers.md) — Rule 4 (stats coupled to action) defers to this ADR for the full counter-placement principle
- Council resolution: #2755
- Source memory: #2327
- Source issue: #2341
- Related: #2345, #2355, #2346, #2350
- Duplicate resolution: #2757
- `src/adr_reviewer.py` — `_execute_triage_or_hitl()`, `_route_to_triage()`, `_route_pre_validation_failure()`, `_handle_duplicate()`
- `src/config.py` — `adr_auto_triage` toggle (planned, not yet implemented)
