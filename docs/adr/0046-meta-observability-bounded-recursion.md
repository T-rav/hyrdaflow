# ADR-0046: Meta-observability with bounded recursion

- **Status:** Proposed
- **Date:** 2026-04-23
- **Supersedes:** none
- **Superseded by:** none
- **Related:** [ADR-0045](0045-trust-architecture-hardening.md) (establishes the trust fleet that this ADR supervises)
- **Enforced by:** `src/trust_fleet_sanity_loop.py` (the meta-observer); `src/health_monitor_loop.py::_check_sanity_loop_staleness` (the dead-man-switch watching the meta-observer); `tests/test_health_monitor_sanity_stall.py` (runtime enforcement test).

## Context

Once HydraFlow had 9 autonomous trust loops (ADR-0045), one natural question became load-bearing: **who watches the watchers?** If any of the 9 loops stalls or floods the issue queue, a human might notice — but that breaks the dark-factory property the fleet was designed to uphold. The obvious fix is a meta-observability loop: a loop that watches the other loops. That immediately raises a second question: **who watches the meta-observer?** A tempting answer is "another loop", but that recurses — a loop that watches the loop that watches the loops, and so on. At some level something has to watch the last watcher, and if the answer is "the same class of loop", the chain is infinite and the last layer has no observer.

We needed a convention that:
1. Gives the trust fleet a self-supervising layer (so loops can fail without a human noticing first).
2. Terminates the recursion explicitly — no infinite chain of meta-observers.
3. Uses an existing, independent health signal at the base layer rather than spawning yet another loop.

## Decision

**One and only one meta-observability layer.** A single loop (`TrustFleetSanityLoop`, spec §12.1) watches the 9 trust loops and files a `hitl-escalation` + `trust-loop-anomaly` issue when any of five anomaly signals breach (issues_per_hour, repair_ratio, tick_error_ratio, staleness, cost_spike). That loop is **itself watched by `HealthMonitorLoop._check_sanity_loop_staleness`**, which runs inside the pre-existing (non-trust) health monitor and uses a dead-man-switch pattern (file one issue when the sanity-loop heartbeat is older than `3 × trust_fleet_sanity_interval`).

The recursion terminates at the health monitor on purpose:
- HealthMonitor predates the trust fleet and is part of the base HydraFlow skeleton — it cannot be turned off by the trust fleet's own kill-switch without a code change.
- HealthMonitor's check is a simple heartbeat-timeout read, not another trust loop. It has no anomaly detectors of its own for the trust fleet — just a liveness probe.
- That asymmetry is the bound: the trust fleet's meta-observer is one loop with rich semantic signals, and the dead-man-switch is a simple timeout living outside the trust fleet.

Future observability questions must either (a) extend the detectors inside `TrustFleetSanityLoop` (same layer), (b) add signals to the `HealthMonitorLoop._check_sanity_loop_staleness` path (the bound), or (c) be answered with "no — we don't add another meta-layer." A proposal to add a `TrustFleetSanityWatcherLoop` would need to supersede this ADR.

## Consequences

**Positive:**
- Operators have one place to read fleet health (`/api/trust/fleet`) and one loop to kill-switch if the meta-observer itself goes wrong.
- The dead-man-switch is simple (heartbeat timeout) and lives in a loop that predates the trust fleet — its correctness is not contingent on the fleet being healthy.
- Bounded recursion makes the system analyzable: a failure mode can only propagate across two layers before either the operator is paged or HealthMonitor catches it.

**Negative:**
- `TrustFleetSanityLoop` is a single point of partial failure. If it stalls silently, the dead-man-switch catches it, but in the 3× interval window between stall and catch there's no meta-observability. Acceptable because the trust loops themselves keep working during that window — only the aggregate signal is paused.
- No observability for the dead-man-switch itself. A bug in `_check_sanity_loop_staleness` could leave the fleet unmonitored. Mitigated by keeping the method small (one heartbeat read + one threshold compare + one dedup-gated `create_issue`) and testing it in `tests/test_health_monitor_sanity_stall.py`.

**Neutral:**
- The 5 anomaly signals in `TrustFleetSanityLoop` are operator-tunable thresholds. If a signal is consistently noisy, the fix is to tune the threshold (config), not add another loop.

## Rules of thumb for future meta-observers

When a proposal arrives like "we should watch X with a background loop," check:
1. Is X already observable via heartbeats + event-log? If yes, add a signal to `TrustFleetSanityLoop`, not a new loop.
2. Does X live *inside* the trust fleet? If yes, the dead-man-switch already covers liveness. Specific-failure observability belongs in `TrustFleetSanityLoop`.
3. Does X live *outside* the trust fleet (e.g. a new cluster of business logic)? Consider a peer at the same layer as `TrustFleetSanityLoop` watching that cluster — NOT a loop that watches sanity.

If a proposal fails all three (wants to add a loop that watches sanity), it's violating this ADR. The fix is either to collapse it into `TrustFleetSanityLoop` or to supersede this ADR with a 3-layer design and explicit termination rule.

## Implementation notes

The `_SANITY_STALL_MULTIPLIER = 3` in `health_monitor_loop.py` is chosen so the dead-man-switch fires after missing 3 scheduled ticks. At the default 10-minute interval that's a 30-minute silence before a page. This is the *maximum* time the fleet can be unmonitored before a human is notified.

The dead-man-switch has its own dedup (`_sanity_stall_dedup`) so a prolonged silence fires exactly one `sanity-loop-stalled` issue, not one per `HealthMonitorLoop` tick (~1 minute).
