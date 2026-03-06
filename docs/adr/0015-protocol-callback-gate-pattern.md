# ADR-0015: Protocol-Based Callback Injection for Merge-Phase Gates

**Status:** Proposed
**Date:** 2026-03-01

## Context

HydraFlow's review-to-merge pipeline requires multiple verification gates before
a PR can be merged: CI status checks, code scanning alerts, visual validation,
and adversarial review thresholds. Each gate is independently configurable, may
be disabled entirely, and must be testable in isolation.

Early implementations embedded gate logic directly in `PostMergeHandler` and
`ReviewPhase`, creating tight coupling that made it difficult to add new gates,
test individual checks, or disable features without conditional sprawl.

The CI gate (`CiGateFn`) established a pattern: define the gate as a
`typing.Protocol` callback, inject it as an optional parameter on
`handle_approved()`, and guard execution behind a config boolean. The visual
validation gate in `review_phase.py` (`check_visual_gate` /
`compute_visual_validation`) independently converged on the same four-phase
protocol:

1. **Config guard** — check a feature flag; return early if disabled.
2. **Bypass path** — skip execution when the config cap is zero or the feature
   is not applicable.
3. **Execute** — run the gate logic (async callback or sync decision function).
4. **Telemetry** — record metrics, post PR comments, update state.

This convergence was identified in memory issue #1720 and warrants codification
as the standard pattern for all merge-phase gates.

## Decision

Adopt the protocol-based callback injection pattern as the standard architecture
for all merge-phase gates in HydraFlow. Specifically:

1. **Define gate signatures as `typing.Protocol` classes** in `models.py`.
   Each protocol specifies the exact async callable signature the gate must
   satisfy (e.g., `CiGateFn`, `EscalateFn`, `PublishFn`).

2. **Inject gates as parameters** on `PostMergeHandler.handle_approved()`.
   Gates are passed in by the calling phase, not constructed internally. This
   enables mock injection in tests and decouples gate implementation from merge
   orchestration.

3. **Guard every gate with a config boolean or threshold**. Disabled gates
   return immediately with no side effects. Zero-cap thresholds
   (`max_ci_fix_attempts == 0`) bypass execution entirely.

4. **Use decision objects for multi-factor gates**. Where a gate's outcome
   depends on multiple inputs (file patterns, labels, overrides), return a
   typed decision object (`VisualValidationDecision`, `EscalationDecision`)
   rather than a bare boolean.

5. **Follow the four-phase protocol** for every new gate:
   - Config guard → bypass path → execute → telemetry.

6. **Separate escalation from gate logic**. HITL escalation is its own
   `EscalateFn` callback, not embedded within individual gates.

### Current gates following this pattern

| Gate | Type | Protocol / Decision | Config Guard |
|------|------|---------------------|--------------|
| CI gate | Async callback | `CiGateFn` | `max_ci_fix_attempts > 0` |
| Visual validation decision | Sync decision object | `VisualValidationDecision` | `visual_validation_enabled` |
| Visual gate | Async callback | `VisualGateFn` | `visual_gate_enabled` |
| Merge conflict fix | Async callback | `MergeConflictFixFn` | Triggered on merge conflict |
| Escalation | Async callback | `EscalateFn` | `debug_escalation_enabled` |
| Status publishing | Async callback | `PublishFn` | Always active |
| Adversarial threshold | Async method (not yet injected) | Returns `ReviewResult` | `min_review_findings > 0` |

**Note:** The visual validation row represents the pre-gate decision object that
determines *whether* validation is required. The visual gate row (`VisualGateFn`)
is the actual async callback that enforces the gate at merge time. The adversarial
threshold is currently an embedded async method on `ReviewPhase` rather than an
injected Protocol callback — it follows the four-phase protocol pattern but does
not yet conform to Rule 2 (injection as a parameter).

## Consequences

**Positive:**
- New merge-phase gates slot in with minimal changes to `PostMergeHandler`.
- Each gate is independently testable via mock protocol implementations.
- Disabled features have zero runtime cost (early return before any I/O).
- Decision objects make multi-factor gate outcomes inspectable and loggable.
- Consistent pattern reduces cognitive load when onboarding or reviewing.

**Trade-offs:**
- Protocol definitions add one indirection layer per gate.
- Callers must wire up callbacks explicitly, increasing `handle_approved()`
  parameter count as gates accumulate.
- Sync decision objects and async callbacks coexist, requiring developers to
  choose the right variant for each gate type.

## Alternatives considered

1. **Gate registry with dynamic dispatch.**
   Register gates by name, iterate and call at merge time.
   Rejected: loses type safety and makes parameter passing opaque.

2. **Inheritance-based gate hierarchy.**
   Base `Gate` class with `check()` method overrides.
   Rejected: forces shared state and lifecycle coupling between unrelated gates.

3. **Middleware chain (request/response pipeline).**
   Each gate wraps the next in a chain.
   Rejected: ordering becomes implicit and harder to reason about; gates are
   independent checks, not a sequential pipeline.

## Related

- Source memory: #1720
- Issue: #1746
- `src/models.py` — `CiGateFn`, `VisualGateFn`, `MergeConflictFixFn`, `EscalateFn`, `PublishFn`, `VisualValidationDecision`
- `src/post_merge_handler.py` — `handle_approved()` callback injection
- `src/review_phase.py` — `check_visual_gate()`, `_fetch_code_scanning_alerts()`
- `src/visual_validation.py` — `compute_visual_validation()`
- `src/escalation_gate.py` — `should_escalate_debug()`
