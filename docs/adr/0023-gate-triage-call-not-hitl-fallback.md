# ADR-0023: Gate Triage Call on Config Toggle, Not Just HITL Fallback

**Status:** Accepted
**Date:** 2026-03-08

## Context

HydraFlow's ADR review pipeline routes council results through `_route_result`
in `adr_reviewer.py`. When a council decision is REJECT, REQUEST_CHANGES, or
deadlocked, the system must choose between two paths:

1. **Triage** — create a follow-up issue routed through the normal
   plan → implement → review pipeline (`_route_to_triage`).
2. **HITL** — escalate to a human-in-the-loop issue (`_escalate_to_hitl`).

A config toggle (`adr_auto_triage`) is intended to control whether the system
uses automatic triage or always escalates to HITL. The original implementation
in `_route_result` always called `_route_to_triage` first and only fell back to
`_escalate_to_hitl` when triage failed (returned `False`):

```python
# Anti-pattern: toggle not gating the routing call
routed = await self._route_to_triage(result, reason="rejected")
if not routed:
    await self._escalate_to_hitl(result, reason="rejected")
```

This is an anti-pattern because the triage call executes unconditionally. When
the toggle is off (operator intends HITL-only routing), the system still attempts
triage — creating follow-up issues, calling the GitHub API, and only reaching
HITL if triage happens to fail. The toggle does not actually gate the behavior
it claims to control.

This bug class is subtle because it only manifests when:
- The toggle is explicitly disabled, AND
- The triage call succeeds (which it usually does).

When both conditions are true, the system silently routes to triage despite the
operator disabling it. The HITL path is dead code in practice.

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

Adopt the **toggle-first guard pattern** for any routing method that chooses
between triage and HITL based on a config toggle. The correct structure is:

```python
# Correct pattern: gate triage on the toggle
if not self._config.adr_auto_triage:
    await self._escalate_to_hitl(result, reason=reason)
    return

routed = await self._route_to_triage(result, reason=reason)
if not routed:
    await self._escalate_to_hitl(result, reason=reason)
```

Key rules:

1. **Check the toggle first.** If the toggle is off, call HITL immediately and
   return. Do not call triage at all. The toggle must be the first condition
   checked, before any issue creation or API call occurs.

2. **Centralise gated routing through a single helper.** All post-council
   routing decisions (reject, changes requested, no consensus) must flow
   through `_triage_or_hitl()`, which encapsulates the toggle check, the
   triage attempt, the stat increment, and the HITL fallback in one place.
   Individual routing call-sites must not duplicate this logic.

3. **Audit all routing paths when adding or modifying a routing toggle.**
   When a new toggle is introduced or an existing one is changed, every method
   that could trigger the gated action must be reviewed for consistency. A
   grep for the routing target (e.g. `_route_to_triage`) is the minimum
   verification step.

4. **Preserve the HITL fallback for triage failures.** When triage is enabled
   but fails (API error, invalid issue number), fall back to HITL as before.

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

1. **Always call triage, conditionally call HITL as fallback (original state).**
   Rejected: the toggle does not actually prevent triage from executing,
   making the config option misleading.

2. **Decorator-based toggle enforcement.**
   A `@gated_by("adr_auto_triage")` decorator that wraps `_route_to_triage()`
   and short-circuits when the toggle is off.
   Rejected: adds indirection and makes the fallback-to-HITL path harder to
   follow. The explicit `if` check in `_triage_or_hitl()` is clearer.

3. **Toggle check inside `_route_to_triage()` itself.**
   Move the toggle check into the routing method so callers cannot forget it.
   Rejected: `_route_to_triage()` is a low-level method that should remain
   toggle-unaware. The toggle is a policy decision that belongs in the
   orchestration layer (`_triage_or_hitl`), not in the action method.

4. **Separate toggle per routing path.**
   E.g. `adr_auto_triage_pre_review`, `adr_auto_triage_post_council`.
   Rejected: over-engineering for the current use case. A single toggle with
   centralised enforcement is sufficient. Can revisit if granular control is
   needed.

## Related

- **Absorbs:** [ADR-0023 (Auto-Triage Toggle Must Gate Routing)](0023-auto-triage-toggle-must-gate-routing.md) — broader-scope duplicate that added the routing-path audit table and audit rule, now merged here
- Source memory: #2345, #2327
- Issue: #2355, #2341
- Related learning: #2346, #2350
- See also: [ADR-0023 (Stats Counter Placement in Delegating Helpers)](0023-stats-counter-placement-in-delegating-helpers.md) — stats-coupling rule for counter placement
- `src/adr_reviewer.py` — `_triage_or_hitl()`, `_route_to_triage()`, `_handle_pre_review_failure()`, `_handle_duplicate()`
- `src/config.py` — `adr_auto_triage` toggle definition
