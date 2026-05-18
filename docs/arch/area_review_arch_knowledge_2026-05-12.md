# Per-Area Review: Architecture Knowledge (slice 5.5)

**Date:** 2026-05-12
**Auditor:** Claude (subagent, slice 5.5)
**Branch:** `audit/area-arch-knowledge`
**Scope:** `src/arch/generators/*`, `src/arch/extractors/*`, `src/arch/runner.py`,
`src/arch/_models.py`, `src/arch/_functional_areas_schema.py`, `src/arch/freshness.py`,
`src/diagram_loop.py`, `tests/architecture/`, `docs/arch/generated/`

---

## Summary Scorecard

| Dimension | Status | Notes |
|---|---|---|
| Generator code quality | clean | All 10 generators are pure functions, well-structured, documented. One minor issue (see G1). |
| Generator test coverage | covered | Every generator has a dedicated unit test; extractor tests use fixture trees. Drift test passes. |
| Drift detection coverage | partial | `test_curated_drift.py` works. Two extractors have systematic data gaps (see E1, E2). |
| Subprocess / billing safety | clean | `arch.runner` is pure (no LLM calls); DiagramLoop uses `asyncio.to_thread` with timeout. |
| Wiki / ADR currency | sparse | No wiki entry documents the arch-knowledge area itself or the runner/extractor design. |

**Overall health: good structure, two known extractor blind spots producing silent data loss in the loop registry, no sandbox e2e layer for DiagramLoop.**

---

## Findings

### E1 (medium): `tick_interval_seconds` extractor blind spot — whole column is blank

**File:** `src/arch/extractors/loops.py`, `_tick_interval()` (lines 36–48)

The extractor looks for a class-level assignment `tick_interval_seconds = <int>`. The
entire live codebase uses `_get_default_interval()` (a method override) instead.
Result: the Tick (s) column in `docs/arch/generated/loops.md` shows `—` for all 42 loops.

```python
# What the extractor expects (never used in live code):
class SomeLoop(BaseBackgroundLoop):
    tick_interval_seconds = 3600

# What every real loop uses:
class SomeLoop(BaseBackgroundLoop):
    def _get_default_interval(self) -> int:
        return 3600
```

Verified by running the extractor against the live tree: zero loops return a tick interval.
The originally documented escape hatch (Plan A assumed the class-attribute pattern) was
superseded when the codebase migrated to `_get_default_interval()`, but the extractor was
not updated to match.

**Fix path:** Update `_tick_interval()` to also walk the class body for a
`_get_default_interval` method returning a constant, and add a test case in
`test_extractor_loops.py` covering the method-override pattern.

---

### E2 (medium): Kill-switch extractor blind spot — column is blank for all loops

**File:** `src/arch/extractors/loops.py`, `_kill_switch()` (lines 51–54)

The extractor calls `ast.unparse(cls)` and searches for `HYDRAFLOW_DISABLE_[A-Z0-9_]+`
inside the class body. The pattern was designed for a direct inline usage like:

```python
os.environ.get("HYDRAFLOW_DISABLE_WIDGET_LOOP")
```

In practice, most loops delegate kill-switch enforcement to `BGWorkerManager.is_enabled()`
via `self._enabled_cb(name)` — there is no `HYDRAFLOW_DISABLE_*` literal anywhere in the
class body, so the regex never matches. The three loops that do carry an explicit kill
switch (DiagramLoop, CostBudgetWatcherLoop, PricingRefreshLoop) store the env-var name in
a module-level constant `_KILL_SWITCH_ENV = "HYDRAFLOW_DISABLE_..."` that is outside the
class body and therefore invisible to `ast.unparse(cls)`.

Verified: `extract_loops(src_dir)` returns `kill_switch_var=None` for all 42 loops.

**Fix path — two options:**
1. Extend the search to the containing module text (already available as `tree` in the
   function): scan `ast.unparse(tree)` for the `HYDRAFLOW_DISABLE_*` pattern and, if the
   module also contains a `BaseBackgroundLoop` subclass, attribute the match to that class.
2. Accept that this field is now handled through `BGWorkerManager` and repurpose the column
   to show the worker name (which is already in `LoopInfo.module` context). File a
   `hydraflow-find` issue with a clear description of the approach.

---

### E3 (low): Labels extractor returns empty — xfail acknowledged but undocumented

**File:** `src/arch/extractors/labels.py`

The extractor walks `src/` for a top-level `TRANSITIONS = [...]` constant. HydraFlow uses
imperative `swap_pipeline_labels()` call-sites scattered across files; no declarative
table exists. The extractor silently returns an empty `LabelStateMachine`. This is
documented as a known gap (xfail in `test_label_state_matches_adr0002.py`), but there is
no open `hydraflow-find` issue tracking the remediation and ADR-0002 still lacks the
Mermaid block that the test expects.

**Fix path:** File a `hydraflow-find` issue to introduce a declarative `TRANSITIONS`
constant in `src/labels.py` (or equivalent) and add the Mermaid diagram to ADR-0002.
This is Plan B task 22 — it was documented as pending but never filed.

---

### G1 (low): `mockworld_map.py` generator caps scenario listing at 3 per fake without documenting the cap

**File:** `src/arch/generators/mockworld_map.py`, line 36

```python
for s in f.used_in_scenarios[:3]:  # cap to keep diagram readable
```

The cap is inline-commented but the generated Markdown gives no indication that scenario
lists may be truncated. A user looking at `mockworld.md` cannot distinguish "this fake is
used in 3 scenarios" from "this fake is used in more than 3 but the diagram was trimmed."

**Fix path:** Add a parenthetical note after the diagram (e.g., "_scenarios shown up to 3
per fake; see the table above for the full list_") or raise the cap slightly (5) since the
table itself already shows all scenarios.

---

### G2 (low): `ubiquitous-language.md` and `ubiquitous-language-context-map.md` are outside `arch.runner`

`docs/arch/generated/` contains two files (`ubiquitous-language.md`,
`ubiquitous-language-context-map.md`) generated by `src/ubiquitous_language.py:render_glossary`
and `render_context_map` rather than by `arch.runner`. They carry a different `<!-- DO NOT EDIT`
header and are not included in `_ARTIFACT_FILES` — so `arch.runner --check` does not guard
them for drift. If `arch-regen.yml` only calls `python -m arch.runner --emit`, these two
artifacts silently go stale.

**Fix path:** Verify the CI workflow (`.github/workflows/arch-regen.yml`) also calls whatever
generates the ubiquitous-language files. If not, either fold the generation into `arch.runner`
or add a separate CI step and document the separation.

---

### D1 (medium): DiagramLoop missing sandbox e2e layer

**Files:** `tests/test_diagram_loop.py`, `tests/test_diagram_loop_kill_switch.py`,
`tests/scenarios/test_diagram_loop_scenario.py`, `tests/scenarios/test_diagram_loop_mockworld.py`

CLAUDE.md §"Load-bearing features" mandates the full three-layer pyramid: unit + MockWorld
scenario + sandbox e2e. DiagramLoop has strong coverage at the unit and MockWorld layers
(6 unit tests, 2 MockWorld tests, 4 direct-`_do_work` scenario tests — all pass). The
sandbox e2e layer (docker/git integration level) is absent. The loop calls
`arch.runner.emit()`, `subprocess.run(git status ...)`, and `auto_pr.open_automated_pr_async`;
these seams are patched in every existing test. A real git repo + temp `docs/arch/generated/`
directory would exercise the wiring in a way unit tests cannot.

**Fix path:** Add a `tests/sandbox_scenarios/test_diagram_loop_e2e.py` that uses a real
temp git repo (similar to `tests/architecture/test_runner.py`'s `populated_repo` fixture)
to exercise the full `DiagramLoop._do_work()` without patching `subprocess.run`.

---

### W1 (low): No wiki entry for the Architecture Knowledge system itself

There is no entry in `docs/wiki/` explaining how the arch-knowledge system works
(runner, extractors, generators, DiagramLoop, freshness badges, drift detection). The
dark-factory wiki mentions `make arch-regen` but only as an operational command;
the system's internals (why AST not introspection, how `{{ARCH_FOOTER}}` works, the
`_DRIFT_EXEMPT` set, the freshness badge lifecycle) are undocumented outside ADRs
and inline source comments.

**Fix path:** Add `docs/wiki/architecture-knowledge-system.md` covering the three-layer
model (extractors → generators → runner) and the DiagramLoop lifecycle. RepoWikiLoop will
keep it fresh once the entry exists.

---

## Test coverage summary

| Component | Unit | MockWorld | Sandbox |
|---|---|---|---|
| `src/arch/extractors/loops.py` | covered (4 tests) | n/a | n/a |
| `src/arch/extractors/ports.py` | covered (3 tests) | n/a | n/a |
| `src/arch/extractors/events.py` | covered (2 tests) | n/a | n/a |
| `src/arch/extractors/labels.py` | covered (2 tests) | n/a | n/a |
| `src/arch/extractors/modules.py` | covered (2 tests) | n/a | n/a |
| `src/arch/extractors/adr_xref.py` | covered (2 tests) | n/a | n/a |
| `src/arch/extractors/mockworld.py` | covered (4 tests) | n/a | n/a |
| `src/arch/generators/*` (10 generators) | covered (1–3 tests each) | n/a | n/a |
| `src/arch/runner.py` | covered (3 runner tests) | n/a | n/a |
| `src/arch/freshness.py` | covered (4 tests) | n/a | n/a |
| `src/arch/_functional_areas_schema.py` | covered (5 tests) | n/a | n/a |
| `src/diagram_loop.py` | covered (6 unit tests) | covered (2 tests) | missing |
| Drift detection (`test_curated_drift.py`) | passes | n/a | n/a |
| Functional area coverage (`test_functional_area_coverage.py`) | passes (3 tests) | n/a | n/a |

**Test run:** 87 collected, 85 passed, 1 xfailed (label state / ADR-0002), 1 skipped (mkdocs strict).

---

## Actions required

| Priority | Finding | Action |
|---|---|---|
| P1 | E1 — tick interval column blank | Update `_tick_interval()` to handle `_get_default_interval()` method; add test |
| P1 | E2 — kill switch column blank | Extend kill-switch extractor to scan module scope or file a `hydraflow-find` tracking the decision |
| P2 | D1 — no sandbox e2e for DiagramLoop | Add `tests/sandbox_scenarios/test_diagram_loop_e2e.py` with a real git fixture |
| P2 | G2 — UL artifacts outside runner drift guard | Verify CI generates UL artifacts and guards them for drift |
| P3 | E3 — labels extractor empty, no tracking issue | File `hydraflow-find` for declarative TRANSITIONS table + ADR-0002 Mermaid block |
| P3 | G1 — scenario cap undocumented | Add note to generated mockworld.md or raise cap |
| P3 | W1 — no wiki entry for arch-knowledge system | Add `docs/wiki/architecture-knowledge-system.md` |

---

## Cross-reference notes

- **T1.1 (PR fixing loops.md generator):** Finding E1 and E2 are in the extractor layer,
  not the generator. The generator (`render_loop_registry`) correctly renders whatever the
  extractor provides — the fix must land in `src/arch/extractors/loops.py`.
- **T1.3 (coverage_matrix generator):** This area has no overlap with the coverage matrix
  PR beyond shared test infrastructure. No conflicts expected.
- **ADR-0029 / ADR-0049:** DiagramLoop is correctly implementing both patterns. The kill-switch
  extractor gap (E2) is a documentation accuracy issue, not a runtime safety issue —
  `BGWorkerManager.is_enabled()` is the live enforcement path.
- **ADR-0053 (ubiquitous language):** The two UL artifacts in `docs/arch/generated/` sit
  outside the arch runner's drift guard. See G2.

---

_Human review required before any action items above are merged. Findings cite specific
file paths and line numbers; verify against the live tree before implementing._
