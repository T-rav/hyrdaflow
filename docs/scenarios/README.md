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
