# ADR-0023: Auto-Triage Toggle Must Gate Routing, Not Just Stat Tracking

**Status:** Proposed
**Date:** 2026-03-08

## Context

HydraFlow's ADR review pipeline includes an `adr_auto_triage` config toggle
that controls whether fixable issues are routed back through the triage pipeline
(creating a follow-up issue) or escalated to HITL for human intervention.

A bug was discovered where the toggle was not consistently enforced across all
routing paths.  Specifically, a routing method would unconditionally call
`_route_to_triage()` and only conditionally increment the `auto_triaged` stat
counter based on the toggle value.  This meant:

- When `adr_auto_triage = False`, the system still routed issues to triage
  (creating follow-up issues and bypassing HITL), but simply did not count them
  in the `auto_triaged` metric.
- The operator believed HITL escalation was active, but issues were silently
  being auto-triaged — a correctness bug masked as a stats-only difference.

Three routing paths required audit for toggle consistency:

| Method                         | Purpose                                          |
|--------------------------------|--------------------------------------------------|
| `_handle_pre_review_failure()` | Routes ADRs that fail structural validation      |
| `_triage_or_hitl()`           | Routes post-council rejected/changes-requested   |
| `_handle_duplicate()`          | Always escalates duplicates to HITL (correct)    |

The fix unified post-council routing through `_triage_or_hitl()`, which gates
the `_route_to_triage()` call on the toggle before any action is taken.
`_handle_pre_review_failure()` was also corrected to check the toggle before
attempting triage.

## Decision

Adopt the following rule for config-gated routing in HydraFlow workers:

1. **A config toggle that controls routing must gate the routing call itself,
   not just downstream side-effects like stat counters.**  If
   `adr_auto_triage` is `False`, no code path may call `_route_to_triage()`.
   The toggle must be the first condition checked, before any issue creation or
   API call occurs.

   Anti-pattern versus correct toggle-first guard pattern (applied in `_triage_or_hitl`):

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
   through `_triage_or_hitl()`, which encapsulates the toggle check, the
   triage attempt, the stat increment, and the HITL fallback in one place.
   Individual routing call-sites must not duplicate this logic.

3. **Audit all routing paths when adding or modifying a routing toggle.**
   When a new toggle is introduced or an existing one is changed, every method
   that could trigger the gated action must be reviewed for consistency.  A
   grep for the routing target (e.g. `_route_to_triage`) is the minimum
   verification step.

4. **Stats must be coupled to the action, not to the toggle check.**  The
   `auto_triaged` counter should increment when triage actually occurs (i.e.
   inside the success branch of the helper), not in a separate conditional
   block that can drift out of sync with the routing logic.

## Consequences

**Positive:**

- Eliminates silent toggle bypass — operators can trust that disabling
  auto-triage actually disables it across all code paths.
- Centralised routing helper (`_triage_or_hitl`) reduces duplication and
  makes the routing logic auditable from a single location.
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
   follow.  The explicit `if` check in `_triage_or_hitl()` is clearer.

2. **Toggle check inside `_route_to_triage()` itself.**
   Move the toggle check into the routing method so callers cannot forget it.
   Rejected: `_route_to_triage()` is a low-level method that should remain
   toggle-unaware.  The toggle is a policy decision that belongs in the
   orchestration layer (`_triage_or_hitl`), not in the action method.

3. **Separate toggle per routing path.**
   E.g. `adr_auto_triage_pre_review`, `adr_auto_triage_post_council`.
   Rejected: over-engineering for the current use case.  A single toggle with
   centralised enforcement is sufficient.  Can revisit if granular control is
   needed.

## Related

- **Supersedes:** [ADR-0023 (Gate Triage Call on Config Toggle, Not Just HITL Fallback)](0023-gate-triage-call-not-hitl-fallback.md)
  - Absorbed: toggle-first guard pattern code samples (verification checklist was already present)
- Source memory: #2327
- Source issue: #2341
- Related: #2345, #2355, #2346, #2350
- `src/adr_reviewer.py` — `_triage_or_hitl()`, `_route_to_triage()`, `_handle_pre_review_failure()`, `_handle_duplicate()`
- `src/config.py` — `adr_auto_triage` toggle definition
