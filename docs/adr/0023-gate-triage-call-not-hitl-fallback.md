# ADR-0023: Gate Triage Call on Config Toggle, Not Just HITL Fallback

**Status:** Superseded
**Date:** 2026-03-08

> **Superseded by [ADR-0023 (Auto-Triage Toggle Must Gate Routing, Not Just Stat Tracking)](0023-auto-triage-toggle-must-gate-routing.md).**
> That ADR covers the same toggle-bypass bug with broader scope: centralized helper, stats coupling, and pre-review failure paths.

## Context

HydraFlow's ADR review pipeline routes council results through `_route_result`
in `adr_reviewer.py`. When a council decision is REJECT, REQUEST_CHANGES, or
deadlocked, the system must choose between two paths:

1. **Triage** — create a follow-up issue routed through the normal
   plan → implement → review pipeline (`_route_to_triage`).
2. **HITL** — escalate to a human-in-the-loop issue (`_escalate_to_hitl`).

A config toggle (e.g., `adr_auto_triage`) is intended to control whether
the system uses automatic triage or always escalates to HITL. The current
implementation in `_route_result` always calls `_route_to_triage` first and only
falls back to `_escalate_to_hitl` when triage fails (returns `False`):

```python
# Current anti-pattern
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
   return. Do not call triage at all.
2. **Only call triage when the toggle is on.** The triage call itself must be
   gated, not just the HITL fallback.
3. **Preserve the HITL fallback for triage failures.** When triage is enabled
   but fails (API error, invalid issue number), fall back to HITL as before.
4. **Apply consistently.** Every code path in `_route_result` that calls both
   `_route_to_triage` and `_escalate_to_hitl` must follow this pattern
   (REJECT, REQUEST_CHANGES, and the default/deadlock branch).

### Verification checklist

When reviewing any routing method that calls both `_route_to_triage` and
`_escalate_to_hitl`:

- Confirm the config toggle is checked **before** the triage call.
- Confirm the toggle-off path calls HITL and returns without invoking triage.
- Confirm tests enable the toggle when asserting triage is called, and disable
  it when asserting HITL is called directly.

## Consequences

**Positive:**
- Config toggles faithfully control routing behavior — operators get the
  routing mode they configured.
- Eliminates silent triage calls when HITL-only mode is intended.
- HITL escalation path is no longer dead code when triage succeeds.
- Test coverage becomes meaningful: tests must set the toggle to match the
  asserted behavior, catching toggle-mismatch bugs early.

**Trade-offs:**
- Adds a conditional branch at the top of each routing path, slightly
  increasing code in `_route_result`.
- Developers must remember to gate new routing methods on the toggle. This
  ADR and the verification checklist serve as the enforcement mechanism.

## Alternatives considered

1. **Always call triage, conditionally call HITL as fallback (current state).**
   Rejected: the toggle does not actually prevent triage from executing,
   making the config option misleading.

2. **Single unified routing method with an early return.**
   Considered but deferred: collapsing all three branches (REJECT,
   REQUEST_CHANGES, deadlock) into a single helper would reduce duplication
   but changes the structure of `_route_result` beyond the scope of this
   decision. Can be done as a follow-up refactor.

3. **Remove the toggle and always use triage-then-HITL.**
   Rejected: operators need the ability to force HITL-only routing for
   sensitive repositories or during incident response.

## Related

- **Superseded by:** [ADR-0023 (Auto-Triage Toggle Must Gate Routing, Not Just Stat Tracking)](0023-auto-triage-toggle-must-gate-routing.md)
- Council resolution: #2755
- Source memory: #2345
- Issue: #2355
- Related learning: #2346, #2350
- Duplicate resolution: #2757
- `src/adr_reviewer.py` — `_route_result`, `_route_to_triage`, `_escalate_to_hitl`
- `src/config.py` — `HydraFlowConfig` (toggle definition)
