# Per-Area Review: MockWorld Test Harness — 2026-05-12

**Slice:** 5.7  
**Area:** Test Harness (MockWorld)  
**Governing ADRs:** ADR-0022 (integration test architecture), ADR-0047 (fake-adapter contract testing)  
**Audit commit:** `038f2146` (staging HEAD at time of review)  
**Reviewer:** automated agent, 90-minute time-box  

---

## Executive Summary

The MockWorld harness is structurally sound and well-designed. The core harness, `PipelineHarness`, `MockWorld`, the scenario runner, and `MockWorldSeed` are clean and maintainable. The loop catalog registers all 42 background loops, and most have at least some scenario coverage. The principal gaps are in fake-adapter contract testing: ADR-0047 remains in **Proposed** status, 11 of 15 fakes have no cassette directory at all, the Cassette schema validator hard-codes `adapter in {github|git|docker}` while the `_FAKE_TO_CASSETTE_DIR` map in `FakeCoverageAuditorLoop` enumerates 9 adapters, and sandbox_main.py carries stale "PR B widens the Fakes" comments that no longer reflect reality.

---

## Dimension 1 — Harness Quality

**Verdict: clean**

The harness comprises four well-separated layers:

| Path | Role |
|---|---|
| `src/mockworld/seed.py` | Serializable initial-state dataclass; clean `to_json` / `from_json` with explicit int-key coercion |
| `src/mockworld/fakes/` | 15 Fake adapters, each scoped to one external dependency |
| `tests/scenarios/fakes/mock_world.py` | `MockWorld` — fluent seed API + wiring + runner |
| `tests/scenarios/catalog/loop_registrations.py` | Declarative `LoopCatalog` registry; 37 builders registered on import |

Notable design strengths:

- `MockWorld._wire_targets` patches runner/PR/workspace methods from a single central point, preventing "works in MockWorld but fails in sandbox" divergence.
- `_HarnessOrchestratorShim` and `_SafeProxy` protect dashboard polling routes against `AttributeError` 500s without leaking test-only logic into the harness core.
- The `_is_fake_adapter = True` marker pattern is enforced by `test_mockworld_fakes_marker.py`; 14 of 15 exported fakes carry it (FakeHoneycomb is intentionally excluded from `fakes/__init__` exports).

Minor issues:

1. **Stale cast comments in `sandbox_main.py` (lines 58–63).** The "PR B widens the Fakes" comment documents a gap that was already resolved. `FakeIssueStore` now implements all 11 `IssueStorePort` methods; `FakeIssueFetcher` covers both `IssueFetcherPort` methods. The `cast()` calls remain (four total: `WorkspacePort`, `IssueFetcherPort`, `IssueStorePort`, `PRPort`) but their justifying prose is inaccurate — they should either be removed (if the Fakes satisfy the Port structurally at runtime) or the comments updated to state the actual reason.

2. **`test_mockworld_fakes_conformance.py` covers only 2 of 15 fakes** (`FakeGitHub` vs `PRPort`, `FakeWorkspace` vs `WorkspacePort`). The module docstring explicitly notes "Add new pairs as Fakes are introduced" but `FakeIssueStore`, `FakeIssueFetcher`, and others have not been added. This means Port-signature drift in those Fakes is only caught at runtime.

---

## Dimension 2 — Scenario Coverage Adequacy

**Verdict: thin for 4 loops; covered elsewhere**

All 42 background loop modules have a corresponding `_build_*` function in `loop_registrations.py`. The catalog is complete.

Of the 42 loops, 4 have **no scenario coverage** anywhere in `tests/scenarios/`:

| Loop | Class | Status |
|---|---|---|
| `edge_proposer_loop` | `EdgeProposerLoop` | unit tests only; no MockWorld scenario |
| `label_drift_watcher_loop` | `LabelDriftWatcherLoop` | integration test in `test_label_drift_watcher_integration.py`; no MockWorld scenario |
| `term_proposer_loop` | `TermProposerLoop` | extensive unit tests; no MockWorld scenario |
| `term_pruner_loop` | `TermPrunerLoop` | unit tests only; no MockWorld scenario |

An additional 3 loops are **registered in the catalog but no scenario test file exercises them via `run_with_loops` or direct instantiation** (previously identified as Group B in the coherency drift audit of 2026-05-12):

- `CostBudgetWatcherLoop`
- `MergeStateWatcherLoop`
- `SandboxFailureFixerLoop`

The remaining 35 loops have MockWorld scenario coverage ranging from single-method smoke tests (pattern B: direct instantiation in caretaker test files) to full multi-tick end-to-end scenarios (pattern A: `run_with_loops` with assertions on outcomes).

The three-layer standard (unit + MockWorld + sandbox e2e) is upheld for the core pipeline phases (triage/plan/implement/review) and for the most critical caretaker loops.

---

## Dimension 3 — Fake Fidelity

**Verdict: drift-risk for 11 of 15 fakes; no-contract**

ADR-0047 is still in **Proposed** status. The contract test infrastructure exists and works (4 fakes have contract test files, cassette directories, and a `test_cassette_directory_not_empty` guard), but coverage is sparse.

| Fake | Contract test | Cassette dir | Cassettes |
|---|---|---|---|
| `FakeDocker` | `test_fake_docker_contract.py` | `cassettes/docker/` | 1 |
| `FakeGit` | `test_fake_git_contract.py` | `cassettes/git/` | 7 |
| `FakeGitHub` | `test_fake_github_contract.py` | `cassettes/github/` | 3 |
| `FakeLLM` | `test_fake_llm_contract.py` | `claude_streams/` (JSONL) | 1 |
| `FakeBeads` | none | none | 0 |
| `FakeClock` | none | none | 0 |
| `FakeFS` | none | none | 0 |
| `FakeHTTP` | none | none | 0 |
| `FakeHoneycomb` | none | none | 0 |
| `FakeIssueFetcher` | none | none | 0 |
| `FakeIssueStore` | none | none | 0 |
| `FakeSentry` | none | none | 0 |
| `FakeSubprocessRunner` | none | none | 0 |
| `FakeWikiCompiler` | none | none | 0 |
| `FakeWorkspace` | none | none | 0 |

For the 4 fakes that do have contracts, cassette coverage is thin relative to method surface:

- `FakeGitHub`: 3 cassettes (create_pr, close_issue, close_task) against 75 methods. The most load-bearing methods — `transition`, `wait_for_ci`, `merge_pr`, `list_issues_by_label` — have no cassette.
- `FakeGit`: 7 cassettes against 13 methods. Best-covered of the four.
- `FakeDocker`: 1 cassette (`run_alpine_echo`) against 7 methods.
- `FakeLLM`: 1 JSONL stream sample. No cassette for `evaluate`, `plan`, `review`.

A structural mismatch exists between the `FakeCoverageAuditorLoop._FAKE_TO_CASSETTE_DIR` map (9 fakes: github, docker, git, beads, sentry, http, subprocess, fs, llm) and the `Cassette._validate_adapter` field validator, which only accepts `github | git | docker`. Writing cassettes for `FakeBeads`, `FakeSentry`, `FakeHTTP`, `FakeSubprocessRunner`, or `FakeFS` would fail schema validation at load time. The validator must be widened before the `FakeCoverageAuditorLoop` can detect gaps for those adapters.

---

## Dimension 4 — Cassette Freshness

**Verdict: stale / absent**

All 11 cassettes present were last recorded between 2026-04-22 and 2026-05-07. The most recent cassettes (git/config_get, git/config_unset, git/rev_parse, git/worktree_add, github/close_issue, github/close_task) were recorded 2026-05-07 — five days before this review.

`ContractRefreshLoop` is designed to re-record cassettes weekly. Its loop scenario (`test_contract_refresh_scenario.py`) passes, and it is registered in the loop catalog. Whether the loop has actually run and refreshed cassettes in production is not verifiable from this audit (that would require checking CI run history), but the cassette ages are consistent with the 2026-04-22 initial recording plus one manual refresh pass on 2026-05-07.

There are no overdue cassettes by the weekly refresh cadence at the time of this audit. However, with only 11 cassettes covering 4 adapters and a schema constraint blocking expansion to 9 adapters, the automated refresh infrastructure is maintaining a small baseline rather than the full surface the `FakeCoverageAuditorLoop` specification envisions.

---

## Dimension 5 — Wiki/ADR Currency

**Verdict: sparse**

| Source | Coverage |
|---|---|
| `docs/wiki/testing.md` | Good. Two entries directly address this area: "Cassette-based fake adapter contract testing" (entry with `json:entry` block) and "MockWorld fixture composes all external fakes into controllable environment". Both are corroborated and marked `stale: false`. |
| `docs/arch/generated/mockworld.md` | Good. Auto-generated, last refreshed from commit `d649803` on 2026-05-11. Accurately reflects the 15 fakes, their Port associations, and scenario usage. Notable: `FakeIssueFetcher` and `FakeIssueStore` show "—" under "Used in scenarios" — an accurate gap signal. |
| ADR-0022 | Accepted. Accurately describes the PipelineHarness pattern as implemented. No drift detected. |
| ADR-0047 | **Proposed, not Accepted.** The cassette schema, contract tests, `ContractRefreshLoop`, and `FakeCoverageAuditorLoop` all exist and run. The ADR's intent is implemented but the status has not been advanced to Accepted. |
| `docs/arch/functional_areas.yml` | Not read in this audit; not in scope for MockWorld area. |

The gap is that ADR-0047 being "Proposed" means the contract testing pattern does not carry the same architectural authority as the PipelineHarness pattern. Accepting the ADR (or documenting why it remains Proposed) would clarify the stability expectation.

---

## Gaps Summary

| # | Gap | Severity | Recommended Action |
|---|---|---|---|
| G1 | ADR-0047 status is Proposed; implementation is live | Medium | Accept ADR-0047 or document the reason it remains Proposed |
| G2 | Cassette schema `adapter` validator rejects `beads\|sentry\|http\|subprocess\|fs` but `_FAKE_TO_CASSETTE_DIR` includes them | High | Widen the validator to match the 9-entry map, then add cassette dirs for each |
| G3 | 11 of 15 fakes have zero cassettes | High | Per ADR-0047 §"When to add a new cassette": add at least one cassette per production-wired fake. Priority order: FakeWorkspace, FakeIssueFetcher, FakeIssueStore, FakeHTTP |
| G4 | FakeGitHub has 3 cassettes against 75 methods; highest-risk uncassetted calls: `transition`, `wait_for_ci`, `merge_pr`, `list_issues_by_label` | Medium | Record cassettes for the 4–6 highest-traffic methods |
| G5 | `test_mockworld_fakes_conformance.py` covers only 2 of 15 Port/Fake pairs | Medium | Add pairs for FakeIssueStore/IssueStorePort and FakeIssueFetcher/IssueFetcherPort |
| G6 | 4 loops have no MockWorld scenario at all: EdgeProposerLoop, LabelDriftWatcherLoop, TermProposerLoop, TermPrunerLoop | Low-Medium | File `hydraflow-find` issues for each; TermProposerLoop warrants scenario coverage given its ubiquitous-language role (ADR-0053/0054) |
| G7 | 3 catalog-registered loops have no exercising scenario test: CostBudgetWatcherLoop, MergeStateWatcherLoop, SandboxFailureFixerLoop | Low | At minimum add Pattern B (direct instantiation + tick) scenarios |
| G8 | sandbox_main.py cast comments describe an old gap that was resolved by PR B; prose is now misleading | Low | Remove or replace the "PR B widens the Fakes" comments with accurate rationale or remove casts where they're no longer needed |

---

## Files Examined

- `src/mockworld/__init__.py`, `seed.py`, `sandbox_main.py`
- `src/mockworld/fakes/` (all 15 files)
- `tests/scenarios/fakes/mock_world.py`, `scenario_result.py`
- `tests/scenarios/catalog/loop_catalog.py`, `loop_registrations.py`
- `tests/trust/contracts/` (all 4 contract test files, `_replay.py`, `_schema.py`)
- `tests/trust/contracts/cassettes/` (all 11 cassette YAMLs)
- `tests/trust/contracts/claude_streams/` (1 JSONL sample)
- `src/contracts/_schema.py`
- `src/fake_coverage_auditor_loop.py` (excerpt)
- `src/contract_refresh_loop.py` (excerpt)
- `docs/adr/0022-integration-test-architecture-cross-phase.md`
- `docs/adr/0047-fake-adapter-contract-testing-cassettes.md`
- `docs/arch/generated/mockworld.md`
- `docs/wiki/testing.md` (relevant entries)
- `tests/test_mockworld_fakes_conformance.py`
- `tests/test_mockworld_fakes_marker.py`
- Representative scenario tests: `test_happy.py`, `test_caretaker_loops.py`, `test_caretaker_loops_part2.py`, `test_loops.py`
