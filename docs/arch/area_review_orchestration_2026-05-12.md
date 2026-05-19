# Per-Area Review: Orchestration (Slice 5.10)

**Date:** 2026-05-12
**Branch:** audit/area-orchestration (from staging @ 038f2146)
**Auditor:** slice 5.10 (automated)
**Files reviewed:**
- `src/orchestrator.py` (1,529 lines)
- `src/service_registry.py` (1,191 lines)
- `src/server.py` (349 lines)
- `src/events.py` (452 lines)
- `src/bg_worker_manager.py` (143 lines)
- `tests/test_loop_wiring_completeness.py`
- `tests/scenarios/catalog/loop_registrations.py`
- `tests/scenarios/catalog/test_loop_registrations.py`
- `docs/arch/functional_areas.yml` (orchestration entry)
- `docs/wiki/dark-factory.md` (§2.1 five-checkpoint wire)

---

## 1. Wire Quality

**Rating: clean, with one minor defect (IssueCache double-construction)**

The orchestrator is well-structured. The five-checkpoint pattern from
dark-factory.md §2.1 is fully implemented for all 41 background loops.
`_supervise_loops` runs a correct supervisory while-loop over
`asyncio.FIRST_COMPLETED`, handles `AuthenticationError` and
`CreditExhaustedError` separately from generic restarts, and cancels all
tasks on stop. `_polling_loop` provides a reusable circuit-breaker with
consecutive-failure escalation that all pipeline phase loops use correctly.

The `build_services` factory in `service_registry.py` is long (960 lines)
but mechanically regular — one construction block per service, no branching
logic beyond the sandbox-override seam. The `cast()` annotations for
`WorkspaceManager`, `PRManager`, `IssueFetcher`, and `IssueStore` all carry
honest "type-checker blind spot" warnings, which is correct documentation for
a known tracked debt.

**Confirmed defect:** `IssueCache` is constructed twice in `build_services`
(lines 455–458 and 496–499). Both calls produce an identical object bound to
the same local name. The second binding silently overwrites the first. The
`CachingIssueStore` at line 465 consumes the first instance; the second
instance (line 496) is the one passed into all phase constructors. In practice
the two instances are equivalent (same path + same config flag), but the
duplicate construction wastes an `__init__` call and could confuse future
state-sharing between `phase_store` and the phases if the constructor ever
gains side-effects.

**Minor:** `gh_cache` at line 423 carries a `# noqa: F841` comment that is
stale — `gh_cache` is referenced at lines 805, 828, and 1159. The suppression
is harmless but misleading.

---

## 2. Wiring Test Coverage

**Rating: covered at 4 of 5 checkpoints; 5th checkpoint (catalog) has drift**

`tests/test_loop_wiring_completeness.py` auto-discovers all
`BaseBackgroundLoop` subclasses from `src/*_loop.py` and validates four wiring
sites:

1. `orchestrator.py` `bg_loop_registry` — covered
2. `ServiceRegistry` dataclass fields — covered
3. `ui/src/constants.js` `BACKGROUND_WORKERS` — covered
4. `dashboard_routes/_common.py` `_INTERVAL_BOUNDS` — covered
5. `tests/scenarios/catalog/loop_registrations.py` builder + entry — **not validated**

The fifth checkpoint (dark-factory.md §2.1 item 1) requires every loop to
have a builder entry in the MockWorld loop catalog. This is not enforced by
any auto-discovery test. The gap is:

| Loop (worker name) | In `bg_loop_registry` | In catalog (`loop_registrations.py`) |
|-|-|-|
| `edge_proposer` | yes | **NO** |
| `label_drift_watcher` | yes | **NO** |
| `sentry_ingest` | yes | **NO** (catalog has `sentry`, wrong name) |
| `staging_promotion` | yes | **NO** |
| `term_proposer` | yes | **NO** |
| `term_pruner` | yes | **NO** |

The `sentry` catalog key is misnamed — the loop's actual `worker_name` is
`sentry_ingest` (confirmed in `sentry_loop.py` line 51). The six missing loops
are all post-trust-fleet additions (ADR-0054 terms, ADR-0057/0058 proposers,
label drift watcher). Each can be instantiated as a real object in MockWorld
scenarios, but the catalog has no registered builder for them so
`LoopCatalog.instantiate(name)` would raise `KeyError`.

Additionally, `test_loop_registrations.py` `ALL_LOOPS` is a hardcoded list of
30 loops. The bg_loop_registry has 41. The 11 loops not in `ALL_LOOPS` (e.g.,
`adr_touchpoint_auditor`, `cost_budget_watcher`, `diagram_loop`,
`merge_state_watcher`, `memory_backlog`, `pricing_refresh`,
`sandbox_failure_fixer`) are not tested by that file, though most of them do
have catalog builders.

The `pipeline_stats` loop and the eight internal pipeline loops (`store`,
`triage`, `discover`, `shape`, `plan`, `implement`, `review`, `hitl`) are
in `loop_factories` but are intentionally not `BaseBackgroundLoop` subclasses.
They are correctly excluded from all wiring tests.

---

## 3. Loop Registry Fidelity

**Rating: matches-functional-areas for all 41 entries; two module-path stales in YAML**

All 41 `bg_loop_registry` entries are present in `loop_factories`
(`TestLoopFactories` covers this). The 42nd discovered loop (`GitHubCacheLoop`)
is in `_ORCHESTRATOR_SKIP` with a comment explaining it is started separately,
which is correct.

The `functional_areas.yml` `orchestration` area lists two module paths that
do not exist:
- `src/agent_runner.py` — no such file; the implementation lives in `src/agent.py`
- `src/review_phase.py` — now a package (`src/review_phase/`); the path should
  be `src/review_phase/`

These module paths are not validated by `test_functional_area_coverage.py`
(which only checks `loops:` and `ports:` entries, not `modules:`), so the
drift has not been caught by CI. They are documentation-only stales with no
runtime impact.

The `DiagramLoop` pre-staging exemption in `_PRE_ASSIGNED` inside
`test_functional_area_coverage.py` should be removed now that `DiagramLoop`
exists in `src/diagram_loop.py` and is discovered by the extractor. The
exemption comment says "Once Plan C lands... this exception is obsolete."
Plan C has landed.

---

## 4. Subprocess / Billing Safety

**Rating: n/a for orchestration layer**

`orchestrator.py` does not spawn subprocesses directly — it delegates to
runner pools (`AgentRunner`, `PlannerRunner`, `ReviewRunner`, `HITLRunner`,
`TriageRunner`). `CreditExhaustedError` propagates correctly from
`_do_review_work` (the `AuthenticationError | CreditExhaustedError | MemoryError`
re-raise at line 1342) and is caught by `_handle_loop_exception` in
`_supervise_loops`. The credit-pause flow (`_pause_for_credits` /
`_resume_loops_after_credit_pause`) uses a `Lock` to prevent multiple loops
from racing into the pause logic simultaneously. This is correct.

The `server.py` `_run_headless` path creates `shutdown_tasks` as a `set` with
a done-callback that discards completed tasks, matching the strong-ref pattern
required by dark-factory.md §6513 precedent.

---

## 5. Wiki / ADR Currency

**Rating: well-documented, ADR-0001 accurately amended**

ADR-0001 carries an explicit amendment note acknowledging the system now runs
~42 loops and that "five-loop" refers to the orchestration-pipeline loops
specifically. This is accurate.

`docs/arch/generated/loops.md` matches the live extractor output — 42
`BaseBackgroundLoop` subclasses. The generated file includes the Tick, Kill
Switch, and Events columns; all three show `—` for most loops because the
generator's AST extractor does not yet pull those values. This is a generator
capability gap, not an audit finding here.

The `functional_areas.yml` orchestration entry references ADRs 0001, 0004,
0011, 0012, 0029. All five are accepted and current.

---

## Findings Summary

| # | Severity | Finding | File:Line |
|---|---|---|---|
| F1 | medium | `IssueCache` constructed twice; second instance silently overwrites first | `service_registry.py:455,496` |
| F2 | medium | 6 loops missing from MockWorld catalog (`edge_proposer`, `label_drift_watcher`, `sentry_ingest` [misnamed as `sentry`], `staging_promotion`, `term_proposer`, `term_pruner`) | `tests/scenarios/catalog/loop_registrations.py` |
| F3 | medium | No auto-discovery test enforces that `loop_registrations.py` catalog is complete vs `bg_loop_registry`; `ALL_LOOPS` in `test_loop_registrations.py` is hardcoded at 30, registry has 41 | `tests/scenarios/catalog/test_loop_registrations.py` |
| F4 | low | `functional_areas.yml` `orchestration.modules` lists `src/agent_runner.py` (does not exist) and `src/review_phase.py` (now a package) | `docs/arch/functional_areas.yml:186-191` |
| F5 | low | `DiagramLoop` pre-staging exemption in `test_functional_area_coverage.py` is stale — Plan C landed, `DiagramLoop` is live | `tests/architecture/test_functional_area_coverage.py:12` |
| F6 | low | Stale `# noqa: F841` on `gh_cache` in `build_services` — variable is used at lines 805, 828, 1159 | `service_registry.py:423` |
| F7 | low | `# Alias for backward compatibility — request_stop = stop` is still in use by `_control_routes.py:326`; alias is load-bearing, not stale, but undocumented as such | `orchestrator.py:472` |

---

## Recommendations

**F1 (IssueCache double-construction):** Remove the second `IssueCache(...)` construction at lines 496–499 in `build_services`. Pass the instance created at line 455 directly into the phase constructors. Verify with `make quality`.

**F2 + F3 (catalog completeness):** Add builders for the 6 missing loops to
`tests/scenarios/catalog/loop_registrations.py`. Rename `sentry` → `sentry_ingest`
to match the loop's `worker_name`. Add an auto-discovery test modeled on
`TestLoopFactories` in `test_loop_wiring_completeness.py` that cross-checks
the catalog against `bg_loop_registry` worker names. This closes the fifth
checkpoint enforcement gap.

**F4 (stale module paths):** Fix the two paths in `functional_areas.yml`:
`src/agent_runner.py` → `src/agent.py`; `src/review_phase.py` → `src/review_phase/`.
Consider whether the `modules:` field is enforced anywhere before investing time
in a validator.

**F5 (stale exemption):** Remove the `_PRE_ASSIGNED = {"DiagramLoop"}` set
and its associated comment from `test_functional_area_coverage.py`.

**F6 (stale noqa):** Remove the `# noqa: F841` comment from `service_registry.py:423`.

**F7 (undocumented alias):** Add a comment to `request_stop = stop` noting that
`_control_routes.py` calls this name, so it is load-bearing, not historical.

---

*Auto-generated by audit slice 5.10. Human review required before acting on findings.*
