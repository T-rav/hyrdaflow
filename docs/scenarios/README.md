# Scenario Testing Framework

Release-gating scenario tests that prove the full pipeline and background loops work before shipping.

## Architecture

Two layers: a **MockWorld** fixture that composes all external fakes into a controllable environment, and **scenario test files** grouped by happy/sad/edge/loop paths.

### MockWorld

A single test fixture that wires up every external service as a stateful fake, builds on top of `PipelineHarness`, and exposes a fluent API for seeding state and running the pipeline.

```
tests/scenarios/
  conftest.py              # MockWorld fixture
  fakes/
    mock_world.py          # MockWorld — composes all fakes
    fake_github.py         # Issues, PRs, labels, CI status, comments
    fake_llm.py            # Scripted triage/plan/implement/review results
    fake_hindsight.py      # Memory bank retain/recall with fail mode
    fake_workspace.py      # Worktree lifecycle tracking
    fake_sentry.py         # Breadcrumb/event capture
    fake_clock.py          # Deterministic time control
    scenario_result.py     # IssueOutcome + ScenarioResult dataclasses
  test_happy.py            # Happy path scenarios (mark: scenario)
  test_sad.py              # Failure + recovery scenarios (mark: scenario)
  test_edge.py             # Race conditions, mid-flight mutations (mark: scenario)
  test_loops.py            # Background loop scenarios (mark: scenario_loops)
```

### Stateful Fakes

Each fake is a real Python class with in-memory state (not `AsyncMock`). Assertions inspect the world's final state directly (e.g. `world.github.issue(1).labels`) rather than checking mock call counts.

| Fake | Replaces | State It Tracks |
|------|----------|----------------|
| `FakeGitHub` | `PRManager`, `IssueFetcher` | Issues, PRs, labels, CI, comments |
| `FakeLLM` | All 4 runners | Per-phase, per-issue scripted results (supports retry sequences) |
| `FakeHindsight` | `HindsightClient` | Per-bank memory entries, fail mode |
| `FakeWorkspace` | `WorkspaceManager` | Created/destroyed worktrees |
| `FakeSentry` | `sentry_sdk` | Breadcrumbs and events |
| `FakeClock` | `time.time` | Controllable time for TTL/staleness |

### MockWorld API

```python
# Seed the world (fluent, returns self)
world.add_issue(number, title, body, labels=...)
world.set_phase_result(phase, issue, result)
world.set_phase_results(phase, issue, [result1, result2])  # retry sequences
world.on_phase(phase, callback)                            # mid-flight hooks
world.fail_service(name)
world.heal_service(name)

# Run
result = await world.run_pipeline()              # pipeline phases
stats  = await world.run_with_loops(["ci_monitor"], cycles=1)  # background loops

# Inspect
world.github.issue(1).labels
world.github.pr_for_issue(1).merged
world.hindsight.bank_entries("learnings")
```

## Running

```bash
make scenario          # pipeline scenarios (pytest -m scenario)
make scenario-loops    # background loop scenarios (pytest -m scenario_loops)
make quality           # includes both in the quality gate
```

## Scenario Matrix

### Happy Paths (`test_happy.py`)

| # | Scenario | Asserts |
|---|----------|---------|
| H1 | Single issue end-to-end | find -> triage -> plan -> implement -> review -> done, PR merged |
| H2 | Multi-issue concurrent batch (3 issues) | All complete independently, no cross-contamination |
| H3 | HITL round-trip | Issue escalates to HITL, correction submitted, resumes |
| H4 | Review approve + merge | APPROVE verdict, CI passes, PR merged, cleanup runs |
| H5 | Plan produces sub-issues | Planner returns `new_issues`, sub-issues created |

### Sad Paths (`test_sad.py`)

| # | Scenario | Asserts |
|---|----------|---------|
| S1 | Plan fails then succeeds on retry | First plan `success=False`, retry succeeds |
| S2 | Implement exhausts attempts | Docker fails N times, issue does not complete |
| S3 | Review rejects -> route-back | REQUEST_CHANGES, routes back, re-review approves |
| S4 | GitHub API 5xx during PR creation | `fail_service("github")` mid-implement, recovery on heal |
| S5 | Hindsight down -> pipeline continues | Memory calls fail, pipeline completes without writes |
| S6 | CI fails -> auto-fix -> CI passes | `wait_for_ci` returns failure first, then passes |

### Edge Cases (`test_edge.py`)

| # | Scenario | Asserts |
|---|----------|---------|
| E1 | Duplicate issues (same title/body) | Both tracked by number, no crash |
| E2 | Issue relabeled mid-flight | `on_phase` hook fires, pipeline continues |
| E3 | Stale worktree during active processing | GC skips actively-processing issues |
| E4 | Epic with child ordering | Parent waits for children, dependency order |
| E5 | Zero-diff implement (already satisfied) | Agent produces 0 commits, `success=True` |

### Background Loop Scenarios (`test_loops.py`)

| # | Loop | Scenario | Asserts |
|---|------|----------|---------|
| L1 | HealthMonitor | Low first_pass_rate triggers config bump | `max_quality_fix_attempts` increased, decision audit written |
| L2 | WorkspaceGC | Cleans stale worktrees | Closed-issue worktrees destroyed, active preserved |
| L3 | StaleIssueGC | Closes inactive HITL issues | Old HITL issues auto-closed with comment, fresh untouched |
| L4 | PRUnsticker | Processes HITL items with open PRs | Unstick attempted on qualifying items |
| L5 | CIMonitor | CI failure creates issue | GitHub issue created with `hydraflow-ci-failure` label |
| L6 | CIMonitor | CI recovery closes issue | Failure issue auto-closed on green CI |
| L7 | DependabotMerge | Auto-merges bot PR on CI pass | PR approved, merged, processed set updated |
| L8 | DependabotMerge | Skips bot PR on CI failure | PR not merged, skip recorded |

## Relationship to Existing Tests

- **Unit tests (9K+):** Unchanged. Test individual functions/methods.
- **Integration tests (`PipelineHarness`):** Unchanged. Test phase wiring with mocked runners.
- **Scenario tests (this):** Test complete flows with stateful fakes. Additive, not replacing.

## ADR Reference

- [ADR-0022](../adr/0022-integration-test-architecture-cross-phase.md) — PipelineHarness pattern (foundation MockWorld builds on)

## Future: v2 Observability-Driven Scenarios

Auto-generation from production run traces:
1. Production run recorder captures external interactions
2. Trace-to-scenario converter builds MockWorld seed + assertions
3. Self-improvement loop adds scenarios when production diverges

Out of scope for v1. MockWorld API is designed to support it.

---

## Conventions (Tier 1 / 2 / 3 Helpers)

### Test Helpers

- **`init_test_worktree(path, *, branch="agent/issue-1", origin=None)`** — Helper at `tests/scenarios/helpers/git_worktree_fixture.py`. Initializes a git repo with a bare origin, main branch, and feature branch. Use for any realistic-agent scenario that runs `_count_commits`. Pass `origin=...` when multiple worktrees share a parent directory.

- **`seed_ports(world, **ports)`** — Helper at `tests/scenarios/helpers/loop_port_seeding.py`. Pre-seeds `world._loop_ports` with `AsyncMock` variants before `run_with_loops` runs the catalog builder. Use when a caretaker-loop scenario needs to observe calls on an inner delegate.

### MockWorld Constructor Flags

- **`MockWorld(use_real_agent_runner=True)`** — Opt-in flag that replaces the scripted `FakeLLM.agents` with a real production `AgentRunner` wired to `FakeDocker` via `FakeSubprocessRunner`. Default `False` preserves scripted-mode behavior.

- **`MockWorld(wiki_store=..., beads_manager=...)`** — Thread `RepoWikiStore` and `FakeBeads` into `PlanPhase`/`ImplementPhase`.

### MockWorld Methods

- **`MockWorld.fail_service("docker" | "github" | "hindsight")`** — Arms fault injection on the corresponding fake. Mirrored `heal_service(...)` clears.

### FakeDocker Scripting

- **`FakeDocker.script_run_with_commits(events, commits, cwd)`** — Script agent run events plus one commit to the worktree repo at `cwd`.

- **`FakeDocker.script_run_with_multiple_commits(events, commit_batches, cwd)`** — Script agent run events plus N separate commits, respectively. Use when the scenario must verify multi-commit push behavior.

### FakeGitHub Fault Injection

- **`FakeGitHub.add_alerts(*, branch, alerts)`** — Script code-scanning alerts for a branch. Keys by branch string to match `PRPort.fetch_code_scanning_alerts(branch)`.

### FakeWorkspace Fault Injection

- **`FakeWorkspace.fail_next_create(kind)`** — Single-shot fault: `permission | disk_full | branch_conflict`. The workspace raises on the next `create()` call then resets, so subsequent calls succeed.

---

## Scenario Catalog (Extended)

### Realistic-Agent Scenarios (`test_agent_realistic.py`)

| # | Scenario | Asserts |
|---|----------|---------|
| A0 | Happy path realistic agent | Single issue flows through real AgentRunner and merges |
| A1 | AgentRunner sees no commits | 0 commits ahead of origin/main → not merged |
| A2 | AgentRunner git commit failure | Git commit error is handled, issue does not merge |
| A3 | AgentRunner quality gate fail | `make quality` non-zero → issue does not merge |
| A4 | AgentRunner skill parse fail | Skill output unparseable → falls through gracefully |
| A5 | AgentRunner pre-quality review | Pre-quality review rejects → issue does not merge |
| A6 | AgentRunner multi-commit | Multiple commits ahead → merged successfully |
| A7 | AgentRunner success=False | Docker reports failure → issue does not merge |
| A8 | AgentRunner timeout | Docker run times out → issue does not merge |
| A9 | AgentRunner exit_code non-zero | Non-zero exit code → not merged |
| A10 | Beads claim + close | FakeBeads claim + close lifecycle verified |
| A11 | Beads note mid-flight | Bead note written during implement |
| A12 | Docker OOM kill | Out-of-memory Docker exit handled gracefully |
| A13 | Multiple issues concurrent realistic | Two issues processed concurrently via real AgentRunner |
| A14 | Hindsight recall seeded | Seeded memory recalled by planner |
| A15 | Hindsight retain written | Pipeline writes retention entry after merge |
| A16 | Hindsight down no crash | Hindsight unavailable, pipeline still merges |
| A17 | Wiki pre-populated | RepoWikiStore wired; PlanPhase._wiki_store set |
| A18 | Code-scanning alerts passed | Alerts fetched and forwarded to reviewer LLM |
| A19 | Multiple commits batch | script_run_with_multiple_commits produces merged PR |
| A20 | Workspace create permission failure | PermissionError swallowed, issue not merged |
| A20b | Workspace create disk full | OSError(ENOSPC) swallowed, issue not merged |
| A20c | Workspace create branch conflict | RuntimeError (worktree exists) swallowed, not merged |
| A21 | State JSON corruption graceful fallback | StateTracker recovers to empty state, pipeline continues |
| A22 | Wiki populated plan consults it | wiki_store wired to PlanPhase, no crash |

### Bead Workflow Scenarios

| # | Scenario | Asserts |
|---|----------|---------|
| B1 | Bead claim + complete lifecycle | Issue lifecycle writes claim, notes, and close bead |

### Background Loop Scenarios (`test_loops.py`) — Extended

| # | Loop | Scenario | Asserts |
|---|------|----------|---------|
| L1 | HealthMonitor | Low first_pass_rate triggers config bump | `max_quality_fix_attempts` increased, decision audit written |
| L2 | WorkspaceGC | Cleans stale worktrees | Closed-issue worktrees destroyed, active preserved |
| L3 | StaleIssueGC | Closes inactive HITL issues | Old HITL issues auto-closed with comment, fresh untouched |
| L4 | PRUnsticker | Processes HITL items with open PRs | Unstick attempted on qualifying items |
| L5 | CIMonitor | CI failure creates issue | GitHub issue created with `hydraflow-ci-failure` label |
| L6 | CIMonitor | CI recovery closes issue | Failure issue auto-closed on green CI |
| L7 | DependabotMerge | Auto-merges bot PR on CI pass | PR approved, merged, processed set updated |
| L8 | DependabotMerge | Skips bot PR on CI failure | PR not merged, skip recorded |
| L9 | MemorySync | Syncs hindsight bank to state | State updated with latest memory entries |
| L10 | MemorySync | Hindsight down → sync skipped | Graceful degradation, no crash |
| L11 | PRUnsticker | Skips non-HITL PRs | Active non-HITL PRs not touched |
| L12 | StaleIssueGC | Skips fresh HITL issues | Issues under threshold not closed |
| L13 | WorkspaceGC | Preserves in-flight worktrees | Worktree for active issue not removed |
| L14 | CIMonitor | Duplicate failure suppressed | Second CI failure for same branch not double-reported |
| L15 | HealthMonitor | High pass rate → no bump | Config unchanged when health is good |
| L16 | DependabotMerge | Multi-PR batch | Multiple bot PRs processed in one cycle |
| L17 | StagingPromotion | Promotion PR created | Staging-to-main PR opened after all checks pass |
| L18 | StagingPromotion | Promotion blocked by failing check | PR not created when staging CI fails |
| L19 | CreditMonitor | Low credits → pause | `creditsPausedUntil` set when balance below threshold |
| L20 | CreditMonitor | Credits recovered → resume | Pause cleared when balance restored |
| L21 | RepoScanner | New repo registered | Supervised repo list extended on discovery |
| L22 | RepoScanner | Existing repo skipped | No duplicate entry added |
| L23 | PRUnsticker | Comment posted on stuck PR | Unstick comment written to GitHub |

---

## Caretaker-Loop Authoring Patterns

### Pattern A — Catalog-Driven (preferred)

Use `await world.run_with_loops(["loop_name"], cycles=1)`. Works when the loop is registered in `tests/scenarios/catalog/loop_registrations.py`. Minimal boilerplate.

```python
stats = await world.run_with_loops(["ci_monitor"], cycles=1)
assert stats["ci_monitor"]["cycles_completed"] == 1
```

### Pattern B — Direct Instantiation

Use `_make_loop_deps` from `tests/helpers.py` and construct the loop class directly. Required when:
- Config flags differ from catalog defaults, or
- The loop is not yet registered in the catalog (e.g. `staging_promotion_loop` as of this writing).

```python
from tests.helpers import _make_loop_deps
from src.loops.staging_promotion import StagingPromotionLoop

deps = _make_loop_deps(world, config_overrides={"staging_branch": "staging"})
loop = StagingPromotionLoop(**deps)
await loop.run_once()
```

Pattern A is simpler; use Pattern B only when Pattern A cannot accommodate the scenario.
