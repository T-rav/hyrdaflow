# ADR-0045: Trust Architecture Hardening — Lights-Off Trust Fleet

- **Status:** Proposed
- **Date:** 2026-04-23
- **Supersedes:** none
- **Superseded by:** none
- **Spec:** [docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md](../superpowers/specs/2026-04-22-trust-architecture-hardening-design.md)
- **Implementation plans:** 11 plans under [docs/superpowers/plans/2026-04-22-*.md](../superpowers/plans/) — one per trust loop and subsystem.

## Context

HydraFlow shipped a strong *happy-path* pipeline: triage → plan → implement → review → merge. ADR-0044 codified the principles that make each step auditable. But across a running fleet of 5+ concurrent loops and dozens of caretakers, there was no single observable that answered the question **"is the factory healthy without a human in the loop?"** When a loop stalled, broke a cassette, filed issues faster than humans could close them, or produced wall-clock drift in the release-candidate gate, the first signal was an operator noticing — not the system. That makes the factory *staffed*, not *dark*.

The trust architecture hardening initiative exists to close that gap: every automated loop in HydraFlow must be individually observable, individually gated by a live System-tab kill-switch, individually dedup'd against issue spam, and individually escalatable via the `hitl-escalation` label when it hits an actual unknown. On top of that, one meta-observability loop must watch the other nine, and one dead-man-switch must watch the meta-observer. This makes the fleet self-supervising through one bounded meta-layer.

## Decision

Build a trust fleet of **10 autonomous background loops plus 2 non-loop subsystems** per the spec at `docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md`. Each loop must:

1. **Be a `BaseBackgroundLoop` subclass** with the standard 5-checkpoint wiring (`service_registry.py`, `orchestrator.py bg_loop_registry`, `ui/src/constants.js`, `dashboard_routes/_common.py _INTERVAL_BOUNDS`, `tests/scenarios/catalog/`).
2. **Gate every tick on `LoopDeps.enabled_cb(worker_name)`** — the live System-tab kill-switch is the ONLY stop button. No config-field-only toggles (ref spec §12.2).
3. **Persist dedup via `DedupStore`** keyed on the specific anomaly. File one issue per anomaly event, not one per tick. Clear the dedup entry when the filed issue is closed, via `_reconcile_closed_escalations` called on each tick.
4. **Escalate only via `hitl-escalation` label** — loops do not page humans by any other channel. A loop that cannot recover files one escalation issue and stops re-filing until the operator resolves it.
5. **Tolerate env imperfection on startup** — a broken `gh`, a missing Makefile target, a stale credential, etc. must log + skip the tick, not raise and pause the orchestrator.

### The ten loops

| § | Loop | What it does | Spec |
|---|------|---|---|
| 4.1 | `CorpusLearningLoop` | Reads `skill-escape` issues, synthesizes adversarial corpus cases, validates, opens PRs | Phase 2 of §4.1 |
| 4.2 | `ContractRefreshLoop` | Records fake adapters, detects drift, opens refresh PR, runs replay gate | §4.2 |
| 4.3 | `StagingBisectLoop` | Auto-bisects RC red, attributes culprit, opens auto-revert PR, watchdogs next RC | §4.3 |
| 4.4 | `PrinciplesAuditLoop` | Weekly ADR-0044 audit of HydraFlow-self + managed repos (onboarding + drift) | §4.4 |
| 4.5 | `FlakeTrackerLoop` | Detects persistently flaky tests across 20 RC runs | §4.5 |
| 4.6 | `SkillPromptEvalLoop` | Weekly adversarial-corpus gate against `BUILTIN_SKILLS` | §4.6 |
| 4.7 | `FakeCoverageAuditorLoop` | Flags un-cassetted fake methods and un-exercised helpers | §4.7 |
| 4.8 | `RCBudgetLoop` | Detects RC wall-clock bloat via rolling-median + spike signals | §4.8 |
| 4.9 | `WikiRotDetectorLoop` | Weekly scan of per-repo wikis for broken code cites | §4.9 |
| 12.1 | `TrustFleetSanityLoop` | Meta-observer — watches the 9 trust loops for 5 anomaly kinds | §12.1 |

### Non-loop subsystems

- **§4.10 Product-phase evaluators:** `discover-completeness` + `shape-coherence` skills wired into `DiscoverRunner`/`ShapeRunner` dispatch. Not a loop — a skill-retry gate on Discover/Shape phase outputs.
- **§4.11 Cost + trust observability:** shared cost aggregator (`src/dashboard_routes/_cost_rollups.py`), 4 diagnostics cost routes, `/api/trust/fleet` endpoint, 4 React UI components (FactoryCostSummary, PerLoopCostTable, WaterfallView, FactoryCostTab), daily + per-issue budget alerts.

### Bounded meta-observability

`TrustFleetSanityLoop` watches the 9 trust loops. `HealthMonitorLoop._check_sanity_loop_staleness` watches `TrustFleetSanityLoop` (dead-man-switch — fires on >= 3× interval silence). Recursion bounded at one meta-layer per spec §12.1 "Bounds of meta-observability".

## Consequences

**Positive:**
- Every background concern is now observable at `/api/trust/fleet`.
- Operators can disable any loop live without a restart.
- Failed work escalates; the factory keeps going.
- Cost spend per issue + per loop is visible via the Factory Cost UI tab.
- Dark-factory principle: no single loop failure can kill the orchestrator.

**Negative:**
- 10 new loops + 2 subsystems are a lot of surface area. The trade-off is explicitly: more surface in exchange for self-supervision.
- Dedup stores are filesystem-backed — high-volume fleets will see I/O on every tick. Acceptable since loops tick on minute-or-longer intervals.
- Initial rollout to managed repos is manual (per-repo onboarding gate in §4.4).

**Neutral:**
- Telemetry cost (per-loop subprocess traces) adds observability overhead on the order of one JSON write per subprocess call. Negligible at steady state.

## Implementation notes

The plan files under `docs/superpowers/plans/2026-04-22-*.md` are the authoritative task breakdown (194 beads across 11 plans). They include explicit spec-to-code mappings (which module, which method, which test). The spec is the why; the plans are the how. This ADR is the *decision* that binds them together as architecture and promises the dark-factory property as the acceptance criterion.

## Follow-on ADRs

- A future ADR-0046 may be needed if Phase 2 of §4.1 (CorpusLearningLoop auto-filing PRs) ever needs a per-tick cap on PR volume.
- A future ADR may be needed when the sandbox repo for §4.2 live recording (contracts Task 0) graduates from manual prereq to automated.
- An ADR for the `Skip-ADR:` PR-body marker convention is in scope for any follow-on that adopts it as a policy.

## Enforced by

- `tests/test_loop_wiring_completeness.py` — auto-discovers loops from `src/*_loop.py` and verifies every one is wired in all 5 checkpoints.
- `tests/scenarios/catalog/test_loop_instantiation.py` + `test_loop_registrations.py` — parametric ctor-drift guards.
- `tests/scenarios/test_*_scenario.py` — one MockWorld scenario per trust loop.
- `make trust` (fixture mode, RC CI gate) — runs adversarial corpus + contract tests on every RC promotion PR.
- `HealthMonitorLoop._check_sanity_loop_staleness` + `TrustFleetSanityLoop` — runtime dead-man-switch enforcement of the dark-factory property.
