# Coherency Drift Audit — 2026-05-12

**Slice #2 of the documentation audit roadmap.** Consumes the matrix at
`docs/arch/coverage_matrix.md` (slice #1 PR #8738) and verifies the ⚠️ cells
and a 20-cell ✅ sample.

**Audit commit SHA:** `a33312a3fd593c2016f46588cd1d493b5951f441`
**Baseline matrix SHA:** `06781b1b3ffd068169ea5fd991d88c67510356b7`

---

## Summary

- ⚠️ cells checked: 13
- ⚠️ verdicts: accurate=13, drifted=0, unclear=0
- ✅ cells sampled: 20
- ✅ verdicts: accurate=18, drifted=2
- New `coverage-drift` beads filed: 2
- ⚠️ beads closed: 13

---

## ⚠️ cell verdicts

All 13 ⚠️ cells are **accurate** as of this audit. The gaps recorded in
slice #1 still exist; no code or doc change since `06781b1b` has resolved any
of them.

### Notes on evaluation approach

The matrix branch (`origin/worktree-audit+coverage-matrix-baseline`, at
`06781b1b`) was cut ahead of staging (`a33312a3`). ADRs 0060, 0061, and 0062
exist on the matrix branch but not on staging. This matters for the ✅ sample
(see below) but not for the ⚠️ cells, all of which concern Scenario column
coverage for specific loops — that coverage state is the same on staging as it
was on the matrix branch.

### Loop Scenario ⚠️ cells

The 12 loop Scenario ⚠️ cells split into two groups:

**Group A — registered in `loop_registrations.py`, scenario invocation exists
but coverage is partial** (8 loops):

| Row | Section | Column | Cell | Verdict | Notes | Bead action |
|---|---|---|---|---|---|---|
| `CIMonitorLoop` | Loops | Scenario | ⚠️ in catalog [bd:advisor-g95] | accurate | `TestL5` and `TestL6` in `test_loops.py` invoke the loop but coverage is deliberately scoped; gap unchanged since baseline | closed bd:advisor-g95 |
| `DependabotMergeLoop` | Loops | Scenario | ⚠️ in catalog [bd:advisor-lq2] | accurate | `TestL7`/`TestL8` in `test_loops.py` invoke it; has sandbox e2e too but MockWorld scenario coverage is partial per original bead | closed bd:advisor-lq2 |
| `EpicSweeperLoop` | Loops | Scenario | ⚠️ in catalog [bd:advisor-4m0] | accurate | `TestL12` in `test_caretaker_loops.py` invokes it; partial per original bead | closed bd:advisor-4m0 |
| `HealthMonitorLoop` | Loops | Scenario | ⚠️ in catalog [bd:advisor-ddg] | accurate | `TestL1` in `test_loops.py` invokes it; partial coverage per original bead | closed bd:advisor-ddg |
| `PRUnstickerLoop` | Loops | Scenario | ⚠️ in catalog [bd:advisor-mfs] | accurate | `TestL4` in `test_loops.py` invokes it; has sandbox e2e; partial per original bead | closed bd:advisor-mfs |
| `RetrospectiveLoop` | Loops | Scenario | ⚠️ in catalog [bd:advisor-dca] | accurate | `TestL11` in `test_caretaker_loops.py` invokes it; partial per original bead | closed bd:advisor-dca |
| `StagingPromotionLoop` | Loops | Scenario | ⚠️ [bd:advisor-tmo3] | accurate | `TestL22` in `test_caretaker_loops_part2.py` invokes it directly (Pattern B); one mock method added since baseline (`push_synthetic_commit`) but coverage level unchanged | closed bd:advisor-tmo3 |
| `WorkspaceGCLoop` | Loops | Scenario | ⚠️ in catalog [bd:advisor-f1wy] | accurate | `TestL2` in `test_loops.py` invokes it; has sandbox e2e; partial per original bead | closed bd:advisor-f1wy |

**Group B — registered in `loop_registrations.py` but no dedicated scenario
test directly invokes the loop** (3 loops):

| Row | Section | Column | Cell | Verdict | Notes | Bead action |
|---|---|---|---|---|---|---|
| `CostBudgetWatcherLoop` | Loops | Scenario | ⚠️ in catalog [bd:advisor-ga3] | accurate | Builder exists in `loop_registrations.py` (`_build_cost_budget_watcher_loop`) but no scenario test file invokes it via `run_with_loops` or direct instantiation; unchanged since baseline | closed bd:advisor-ga3 |
| `MergeStateWatcherLoop` | Loops | Scenario | ⚠️ in catalog [bd:advisor-308] | accurate | Builder exists (`_build_merge_state_watcher`) but no scenario test exercises it; unchanged since baseline | closed bd:advisor-308 |
| `SandboxFailureFixerLoop` | Loops | Scenario | ⚠️ in catalog [bd:advisor-rqj] | accurate | Builder exists (`_build_sandbox_failure_fixer`) but no scenario test exercises it; unchanged since baseline | closed bd:advisor-rqj |

**Group C — loop source not yet on staging at time of audit** (1 loop):

| Row | Section | Column | Cell | Verdict | Notes | Bead action |
|---|---|---|---|---|---|---|
| `EntryEvidenceLoop` | Loops | Scenario | ⚠️ [bd:advisor-4dj] | accurate | `EntryEvidenceLoop` source is not on staging (`a33312a3`); it shipped via PR #8733 to main but has not promoted to staging yet; scenario file (`test_entry_evidence_loop_scenario.py`) exists on main but not in this worktree; gap unchanged relative to staging | closed bd:advisor-4dj |

### Port ADR ⚠️ cell

| Row | Section | Column | Cell | Verdict | Notes | Bead action |
|---|---|---|---|---|---|---|
| `ObservabilityPort` | Ports | ADR | ⚠️ [bd:advisor-yjwy] | accurate | Only mention is ADR-0044 P7.7 (principles table), which the matrix extractor treated as a roll-call excluded ref; no new ADR covers this port substantively; ADR-0055 (OTel) does not mention `ObservabilityPort` by name; unchanged | closed bd:advisor-yjwy |

---

## ✅ cells sampled

Random seed 2027. 20 cells drawn from 182 ✅ cells across all three sections.

| Row | Section | Column | Cell | Verdict | Notes | Bead action |
|---|---|---|---|---|---|---|
| `DependabotMergeLoop` | Loops | Standard | ✅ (caretaking/caretaker loop) | accurate | Covered by caretaker loop standard in `docs/standards/factory_operation/README.md` §"Self-modifying maintenance mode" | no action |
| `TermProposerLoop` | Loops | ADR | ✅ [0054][0057][0060] | **drifted** | ADR-0054 and 0057 exist on staging and substantively describe the loop; ADR-0060 (`atlas-graph-view-and-provenance`) exists on the matrix branch but is not on staging at `a33312a3`; cited ref is invalid from staging perspective | filed bd:advisor-v79u |
| `CorpusLearningLoop` | Loops | ADR | ✅ [0045] | accurate | ADR-0045 §4.1 names `CorpusLearningLoop` with substantive description | no action |
| `AdrTouchpointAuditorLoop` | Loops | ADR | ✅ [0056] | accurate | ADR-0056 (`adr-touchpoint-gate-to-caretaker-loop`) names and describes the loop | no action |
| `plan` | Factory phases | ADR | ✅ [ADR-0001][ADR-0002] (Accepted) | accurate | Both ADRs exist on staging and describe the plan phase in body prose | no action |
| `RetrospectiveLoop` | Loops | Standard | ✅ (caretaking/caretaker loop) | accurate | Covered by caretaker loop standard | no action |
| `StagingBisectLoop` | Loops | Wiki | ✅ `architecture.md` | accurate | `docs/wiki/architecture.md` line 246 describes `StagingBisectLoop` behavior in substantive prose | no action |
| `triage` | Factory phases | Standard | ✅ `factory_operation/README.md` | accurate | `docs/standards/factory_operation/README.md` line 9 names triage as a required phase | no action |
| `EpicSweeperLoop` | Loops | Standard | ✅ (caretaking/caretaker loop) | accurate | Covered by caretaker loop standard | no action |
| `StagingBisectLoop` | Loops | ADR | ✅ [0045][0048][0049] | accurate | All three ADRs exist on staging and substantively mention `StagingBisectLoop` | no action |
| `SandboxFailureFixerLoop` | Loops | Unit | ✅ `test_sandbox_failure_fixer_loop.py` | accurate | `tests/test_sandbox_failure_fixer_loop.py` exists with direct class tests | no action |
| `ReviewInsightStorePort` | Ports | Generated | ✅ ports.md | accurate | `docs/arch/generated/ports.md` §ReviewInsightStorePort with adapter table and Protocol methods listed | no action |
| `EpicMonitorLoop` | Loops | Scenario | ✅ in catalog | accurate | Registered in `loop_registrations.py` (`_build_epic_monitor`) and invoked in `test_caretaker_loops_part2.py::TestL16EpicMonitorLoop` | no action |
| `RCBudgetLoop` | Loops | ADR | ✅ [0045] | accurate | ADR-0045 §4.8 names `RCBudgetLoop` with description | no action |
| `RepoWikiLoop` | Loops | ADR | ✅ [0032][0053][0061] | **drifted** | ADR-0032 and 0053 exist on staging and substantively describe the loop; ADR-0061 (`atlas-entries-as-evidence`) exists on the matrix branch but is not on staging at `a33312a3`; cited ref is invalid from staging perspective | filed bd:advisor-qif3 |
| `review` | Factory phases | Standard | ✅ `factory_operation/README.md` | accurate | `docs/standards/factory_operation/README.md` names review as a required phase | no action |
| `WorkspacePort` | Ports | Generated | ✅ ports.md | accurate | `docs/arch/generated/ports.md` §WorkspacePort with `WorkspaceManager` adapter listed | no action |
| `ContractRefreshLoop` | Loops | Scenario | ✅ in catalog | accurate | Registered in `loop_registrations.py` and invoked in `test_contract_refresh_scenario.py` via `run_with_loops(["contract_refresh"])` | no action |
| `discover` | Factory phases | Standard | ✅ `factory_operation/README.md` | accurate | Phase named in the standard diagram and prose | no action |
| `plan` | Factory phases | Standard | ✅ `factory_operation/README.md` | accurate | Phase named in the standard diagram and prose | no action |

---

## Highlights

### 1. ADR-0060 and ADR-0061 are cited in ✅ cells but do not exist on staging

The most consequential drift found in this audit. The matrix branch
(`worktree-audit+coverage-matrix-baseline`) includes ADRs 0059–0062 from the
atlas feature chain. These ADRs have not been promoted to staging as of
`a33312a3`. Two sampled ✅ cells cite them:

- **`TermProposerLoop` ADR column** cites ADR-0060. Drop to `✅ [0054][0057]`
  once ADR-0060 lands on staging; or annotate the matrix as anticipatory.
- **`RepoWikiLoop` ADR column** cites ADR-0061. Same path.

This is anticipated drift — both ADRs are in-flight — but the matrix as
shipped in PR #8738 overstates coverage against the staging codebase. Slice
#3 or the next PR promotion cycle should re-verify.

### 2. Three Group B loops have scenario builders but no scenario test

`CostBudgetWatcherLoop`, `MergeStateWatcherLoop`, and `SandboxFailureFixerLoop`
each have a builder registered in `loop_registrations.py` but no test file that
calls `run_with_loops([...])` or directly instantiates them through a MockWorld
scenario. These ⚠️ beads were accurately filed at slice #1. The gap is real and
unresolved.

### 3. EntryEvidenceLoop is on main but not staging

`EntryEvidenceLoop` shipped in PR #8733 to main, including a MockWorld
scenario (`test_entry_evidence_loop_scenario.py`). The staging branch at
`a33312a3` predates that merge. The loop source, scenario, and ADR-0062 are
all absent from this worktree. Once the next RC promotion cycle runs, this ⚠️
may resolve to ✅ automatically.

### 4. All 13 ⚠️ beads closed — none drifted to worse status

No ⚠️ cell worsened since slice #1. The 13 partial-coverage gaps are exactly
as documented. This gives confidence that slices #3–5 can target the genuinely
unresolved gaps rather than stale entries.
