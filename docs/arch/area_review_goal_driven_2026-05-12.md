# Per-Area Review: Goal-Driven Development

**Slice:** 5.9
**Date:** 2026-05-12
**Reviewer:** Audit agent (Claude Sonnet 4.6)
**Scope note:** `functional_areas.yml` assigns only `discover_phase.py` and
`shape_phase.py` to the `goal_driven_dev` area. The audit task additionally
covers the full phase coordinator set (`triage_phase.py`, `plan_phase.py`,
`implement_phase.py`, `review_phase/_phase.py`, `hitl_phase.py`) and their
matched runners, as these constitute the Phases pipeline referenced in the
task spec.

---

## 1. Phase Coordinator Quality

| Coordinator | Lines | Rating | Notes |
|---|---|---|---|
| `triage_phase.py` | 495 | **clean** | Clear routing, deferred label-swap ordering is correct and documented, sentry noise handling, bug reproducer integration all clean. |
| `discover_phase.py` | 150 | **minor** | Accepts concrete `IssueStore`/`PRManager` instead of `IssueStorePort`/`PRPort` (see §5). No exception handling around `_discover_single` — relies on `store_lifecycle` context manager only, which only catches fatal signals if the coordinator uses `run_with_fatal_guard`; `discover_phase` does not. |
| `shape_phase.py` | 875 | **minor** | Same concrete-type concern as `DiscoverPhase`. HTML artifact saving and council mediation work is well-guarded (best-effort `try/except`). The `_run_council_vote` two-round mediation path is untested (see §3). |
| `plan_phase.py` | 1136 | **clean** | Ports used correctly. Epic gap review loop, adversarial plan reviewer, wiki ingest, and beads integration all properly guarded with best-effort handling. `_precompute_corroboration` has a private method access on `tracked_store` (`_tracked_topic_dir`, `_load_tracked_topic_entries_with_paths`) that is a minor encapsulation leak but not a defect. |
| `implement_phase.py` | 884 | **clean** | Ports used correctly. `PipelineEscalator` and `PreconditionGate` wiring look sound. |
| `review_phase/_phase.py` | 3568 | **clean** | Large but justified by breadth (CI checks, spec-match, conflict resolution, post-merge hooks, ADR review, visual validation). Late-binding import pattern for patchable symbols is explicitly documented. `reraise_on_credit_or_bug` called in three distinct subprocess spans. |
| `hitl_phase.py` | 341 | **clean** | |

**Overall coordinator rating: clean with two minor defects** in the product-track phases.

---

## 2. Runner Quality

All runners in scope inherit `BaseRunner` and call `reraise_on_credit_or_bug`
in their broad `except Exception` blocks. Auth-retry is inherited from
`BaseRunner._execute` (`_AUTH_RETRY_MAX = 3`). No runner was found that
bypasses these.

| Runner | Inherits BaseRunner | `reraise_on_credit_or_bug` | `_phase_name` set |
|---|---|---|---|
| `DiscoverRunner` | yes | yes (lines 158, 205) | **no** (falls back to BaseRunner default `"unknown"`) |
| `ShapeRunner` | yes | yes (lines 181, 231) | **no** (falls back to `"unknown"`) |
| `PlannerRunner` | yes | yes (line 215) | yes (`"plan"`) |
| `DiagnosticRunner` | yes | via `reraise_on_credit_or_bug` in diagnostic_loop | yes |
| `HITLRunner` | yes | yes (line 152) | — |
| `ResearchRunner` | yes | yes (line 77) | — |

`DiscoverRunner` and `ShapeRunner` both omit `_phase_name: ClassVar[str]`. The
default value is `"unknown"`, which means tracing spans and phase-rollup logs
for these runners will be labelled incorrectly. Minor but creates telemetry
noise.

**Overall runner rating: clean** with one minor gap (`_phase_name` missing
on product-track runners).

---

## 3. Phase Test Coverage

### Coordinator tests

| Phase | Test file(s) | Tests | Rating | Key gaps |
|---|---|---|---|---|
| Triage | `test_triage_phase.py` | 21 | **covered** | Routing, parked, duplicate, ADR, discover routing, infra error retry, pool supply, complexity rank all covered. |
| Discover | `test_discover_phase.py` | 6 | **thin** | Happy path, dry-run, events, counter. No test for missing-runner fallback stub text (though text is trivially correct). No test for `store_lifecycle` fatal-error propagation. |
| Shape | `test_shape_phase.py` + `test_shape_conversation.py` | 12 + 27 = 39 | **thin** | Comment-based path (generate options, detect selection, parse directions) is well-covered. The `ShapeRunner`-driven path (`_shape_with_runner`, `_run_council_vote`, `_handle_waiting_state` → timeout branch, `_process_finalization`) is **not covered by any unit test**. Council mediation round-2 path, WhatsApp notification path, and HTML artifact save are also untested. |
| Plan | `test_plan_phase.py` | 44 | **covered** | Product-track decomposition retry, epic group planning, gap review, already-satisfied evidence validation all tested. |
| Implement | `test_implement_phase.py` | 103 | **covered** | Extensive coverage. |
| Review | `test_review_phase_*.py` (8 files) | 346 | **covered** | Pre-merge spec-check, CI, HITL, metrics, term-proposer routing all covered. |
| HITL | `test_hitl_phase.py` | 30 | **covered** | |

### Runner tests

| Runner | Test file(s) | Tests | Rating |
|---|---|---|---|
| DiscoverRunner | `test_discover_runner.py` + evaluator files | 6 + 183 = 189 | **covered** |
| ShapeRunner | `test_shape_runner.py` + evaluator files | 8 + 188 = 196 | **covered** |
| PlannerRunner | `test_planner.py` | (not counted here) | **covered** |

### MockWorld / integration

`tests/scenarios/test_product_phase_trust_scenario.py` (346 lines, 2 tests)
covers the discover → shape → plan trust-model path, including retry-then-shape
and discover-exhaustion escalation. This is the only MockWorld-tier scenario
for the product track.

No sandbox e2e scenario covers the Discover → Shape → Plan full fork. The
nearest sandbox scenario (`s01_happy_single_issue.py`) covers only the direct
triage → plan path.

**Summary:** The product track (Discover + Shape) is **thin at unit and missing at sandbox e2e**. The engineering track (Triage, Plan, Implement, Review) has adequate pyramid coverage.

---

## 4. Subprocess / Billing Safety

Slice #3 confirmed 11/11 runners carry `reraise_on_credit_or_bug`. Spot-check
of three runners validates this:

1. **`DiscoverRunner`** (`src/discover_runner.py`, lines 158, 205): `reraise_on_credit_or_bug(exc)` called in both the primary `discover` method and the evaluator re-run path. Auth retry inherited from `BaseRunner._execute` (3 attempts with exponential backoff). Confirmed.

2. **`ShapeRunner`** (`src/shape_runner.py`, lines 181, 231): Same pattern — two call sites covering the turn execution and evaluator re-run. Confirmed.

3. **`PlannerRunner`** (`src/planner.py`, line 215): Single call site in the broad `except Exception` block after `BaseRunner._execute`. Confirmed.

`DiscoverPhase._discover_single` does not contain its own broad exception block — it relies on `store_lifecycle` to catch fatal signals, but `store_lifecycle` propagates (does not swallow) exceptions. If `DiscoverRunner.discover()` raises a non-credit, non-auth `RuntimeError`, it will bubble up through `_discover_single`, `_discover_one`, and `run_refilling_pool`. The `run_refilling_pool` utility does not suppress arbitrary exceptions either. This means a `DiscoverRunner` infrastructure error (e.g., malformed LLM response) could crash the refilling pool. `TriagePhase._triage_single_traced` explicitly catches `RuntimeError` to suppress and retry — `DiscoverPhase` does not. Minor gap vs. the triage pattern.

---

## 5. Wiki / ADR Currency

### ADR-0031 status mismatch

`docs/adr/0031-product-track-architecture.md` is marked **Proposed** despite
the feature being live, fully wired in `service_registry.py`, and in
production. The ADR should be promoted to **Accepted**. This is the primary
ADR currency gap for this area.

ADR-0063 referenced in the audit task does not exist in the repository. The
task description says "Cross-reference slice #4 ADR-0063 — phase coordinators
are the unit ADR-0063's workstreams target." ADR-0063 is either not yet filed
or was filed in a branch not yet merged. This audit cannot cross-reference it.

### `functional_areas.yml` scope mismatch

`docs/arch/functional_areas.yml` lists only `discover_phase.py` and
`shape_phase.py` under `goal_driven_dev`. The phase coordinators for triage,
plan, implement, review, and HITL fall under `orchestration`. This split is
architecturally reasonable (the product track is an extension of the base
pipeline) but may cause future per-area audits to miss triage/plan coordinator
health when auditing `orchestration`. Worth a note in the yml.

### Concrete-type injection in product-track coordinators

`DiscoverPhase` and `ShapePhase` accept `IssueStore` (concrete) and
`PRManager` (concrete) instead of `IssueStorePort` and `PRPort` (abstract).
All other phase coordinators (`TriagePhase`, `PlanPhase`, `ImplementPhase`,
`ReviewPhase`) use ports. This inconsistency:

- Breaks the hexagonal architecture pattern established by the other phases.
- Makes `DiscoverPhase` and `ShapePhase` harder to test against fake adapters.
- Was likely an oversight when these phases were added (ADR-0031 date: 2026-04-04).

No ADR documents this divergence as intentional.

### Wiki currency

One wiki entry in `architecture-async-control.md` documents the
`clarity_score ≥ 7` routing rule correctly. No wiki entries cover the
`DECOMPOSITION REQUIRED` marker, the council mediation protocol, or the
`max_shape_turns` / `shape_timeout_minutes` config parameters. Sparse but not
blocking — ADR-0031 covers the design intent adequately once promoted.

---

## 6. Summary Table

| Dimension | Rating | Findings |
|---|---|---|
| Phase coordinator quality | minor | `DiscoverPhase` + `ShapePhase` use concrete types vs ports; `DiscoverPhase` missing `RuntimeError` catch pattern |
| Runner quality | minor | `DiscoverRunner` + `ShapeRunner` missing `_phase_name` ClassVar |
| Phase test coverage | thin / covered | Product track (Discover + Shape runner-driven path) thin; no sandbox e2e for product track |
| Subprocess / billing safety | clean | 3/3 spot-checked runners confirmed `reraise_on_credit_or_bug` + 3-attempt auth retry |
| Wiki / ADR currency | sparse | ADR-0031 stuck at Proposed; concrete-type injection undocumented |

---

## 7. Recommended Actions (Priority Order)

1. **Promote ADR-0031 to Accepted** — the feature is live. Update
   `docs/adr/README.md` status column and the ADR header.

2. **Fix `DiscoverPhase` / `ShapePhase` port injection** — change constructor
   signatures to accept `IssueStorePort` / `PRPort` (under TYPE_CHECKING) as
   the other phase coordinators do. This is a type-annotation change; the
   concrete objects passed at wire-up time satisfy the structural protocol.

3. **Add `_phase_name` to `DiscoverRunner` and `ShapeRunner`** — add
   `_phase_name: ClassVar[str] = "discover"` / `"shape"` so telemetry spans
   are correctly labelled.

4. **Add `RuntimeError` suppression to `DiscoverPhase._discover_single`** —
   mirror the `TriagePhase._triage_single_traced` pattern: catch `RuntimeError`,
   log a warning, return 0 so the issue stays in the discover queue for the
   next cycle rather than crashing the refilling pool.

5. **Add unit tests for `ShapePhase` runner-driven path** — specifically:
   `_shape_with_runner` happy path, `_handle_waiting_state` timeout branch,
   `_run_council_vote` with consensus and with split-then-mediation, and
   `_process_finalization`. The 12 existing unit tests only cover the
   comment-based (no-runner) path.

6. **Add sandbox e2e scenario for the product track** — a new `s14_product_track.py`
   covering: vague issue → Discover (stub research brief) → Shape (direction
   posted, direction selected) → Plan → ready. This completes the three-layer
   pyramid for ADR-0031 per `docs/standards/testing/README.md`.

7. **File a `hydraflow-find` issue** for the ADR-0063 reference in the audit
   task spec — it does not exist in the codebase and cannot be cross-referenced.
