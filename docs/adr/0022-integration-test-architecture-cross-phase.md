# ADR-0022: Integration Test Architecture — Cross-Phase Pipeline Harness

**Status:** Accepted
**Date:** 2026-03-18

## Context

HydraFlow's orchestrator spans five asynchronous phases that all rely on a shared
`IssueStore`, persistent `StateTracker`, and in-process `EventBus`. Individual test
modules cover each phase in isolation (see `tests/helpers.py` `make_plan_phase`,
`make_implement_phase`, etc. for the single-phase factories), but regressions
started to appear when changes altered how queues, runners, and GitHub labels
interact across phase boundaries. Issue #1953 captured the lesson learned while
debugging those regressions: integration tests must exercise the real queueing and
data layers so they see the same routing logic implemented in
`src/issue_store.py:IssueStore`, the label-to-stage mapping in
`src/config.py:HydraFlowConfig`, and the persistence semantics inside
`src/state:StateTracker`.

Several concrete requirements flow from the production code:

- `IssueStore` manages internal queues via `enqueue_transition()`, which places a
  `Task` into the appropriate stage queue and publishes queue-update events.
  Integration tests need a mechanism to seed work directly into these queues without
  going through external fetcher polling.
- Label routing depends on config-driven tags (`hydraflow-find`, `hydraflow-plan`,
  `hydraflow-ready`, `hydraflow-review`). Without realistic tags, the queue-stage
  logic in `IssueStore` will route nothing to downstream phases, so integration tests
  would give false confidence.
- Queue updates are published via `_publish_queue_update_nowait()`, which calls
  `loop.create_task()` on the running loop (`src/issue_store.py:_publish_queue_update_nowait`). Tests must run
  under `pytest-asyncio` (or an equivalent running event loop) and often need
  `await asyncio.sleep(0)` so those fire-and-forget `EventBus.publish()` tasks drain
  before making assertions.
- Planner/implement/review loops need the persisted state transitions tracked by
  `src/state:StateTracker`. Using the real tracker against a `tmp_path`
  ensures the harness observes activity counters, active-crate gating
  (`src/crate_manager.py:CrateManager`), and crash recovery semantics that
  single-phase mocks currently skip.

## Decision

Ratified the existing **Pipeline Harness** pattern for cross-phase integration tests.
The harness, already implemented in `tests/helpers.py:PipelineHarness` and exercised
by `tests/test_integration_pipeline.py`, uses real queueing and state components with
controlled mocks for external systems.

### Harness composition

1. **Core services:** Instantiate `HydraFlowConfig`, `StateTracker`, `EventBus`, and
   `IssueStore` exactly as production code does. The tracker persists to a
   temporary directory so repeated phase invocations observe real disk writes,
   including crash-recovery markers and pause/resume semantics that detect
   regressions only surfacing when HydraFlow processes restart.
2. **Task seeding:** Seed work into `IssueStore` queues via `seed_issue()`, which
   calls `IssueStore.enqueue_transition(task, stage)` to place a `Task` directly
   into the target stage queue (where `stage` is an `IssueStoreStage` value, the
   `StrEnum` defined in `src/issue_store.py:IssueStoreStage`). This bypasses the
   external `TaskFetcher` polling
   path (`refresh()`) and instead exercises the same `enqueue_transition` machinery
   that phase hand-offs use in production. The `TaskFetcher` passed to `IssueStore`
   is an `AsyncMock` that is not invoked during normal harness operation.
3. **Phase runners:** Keep runners that invoke external AI agents or GitHub APIs
   mocked (`TriageRunner`, `PlannerRunner`, `AgentRunner`, `ReviewRunner`,
   `HITLRunner`, and the `PRManager`). They expose deterministic hooks (e.g.,
   `AsyncMock` side effects) that tests assert on while allowing the harness to
   drive real orchestrator loops.
4. **Event propagation:** The `EventBus` instance is shared with every phase so
   queue metrics, worker updates, and transcript events mirror production routing.
   Integration tests subscribe to the bus via `async for` iterators or capture
   snapshots directly from `EventBus` to verify emitted events.
5. **Clocking:** A single `asyncio.Event` stop flag lets the harness start and stop
   each phase loop deterministically while still running inside
   `pytest.mark.asyncio` tests.

### Execution semantics

- After each queue-modifying action, `await asyncio.sleep(0)` (or an explicit
  helper) to flush `loop.create_task()` callbacks emitted by
  `_publish_queue_update_nowait()`. This keeps queue stats observed by the harness in
  sync with expectations.
- Use `pytest-asyncio` to provide the event loop and rely on the same config labels
  used in production (read from `HydraFlowConfig.find_label`, `planner_label`,
  `ready_label`, and `review_label`).

### PipelineRunResult contract

`PipelineHarness.run_full_lifecycle()` returns a `PipelineRunResult` dataclass that
serves as the primary assertion surface for integration tests. Its fields are:

| Field | Type | Description |
|-------|------|-------------|
| `task` | `Task` | The seeded task that entered the pipeline. |
| `triaged_count` | `int` | Number of issues triaged in the triage phase. |
| `plan_results` | `list` | Results returned by `PlanPhase.plan_issues()`. |
| `worker_results` | `list` | Results returned by `ImplementPhase.run_batch()`. |
| `review_results` | `list` | Results returned by `ReviewPhase.review_prs()`. |
| `snapshots` | `dict[str, QueueStats]` | Queue-stats snapshots captured after each phase (`after_triage`, `after_plan`, `after_implement`, `after_review`). |
| `events` | `list[HydraFlowEvent]` | Full event history from the shared `EventBus`. |

The `snapshot(label)` helper method provides keyed access to queue stats at each
phase boundary, raising `KeyError` with available labels if the requested snapshot
does not exist.

### Scope boundaries

- The harness stops at the PR boundary: `PRManager`, `WorktreeManager`, and
  external CLI invocations remain mocked so tests stay hermetic.
- The HITL phase is included in the harness (`HITLPhase` is wired with
  `HITLRunner` and issue-fetcher mocks) but is not exercised by the default
  `run_full_lifecycle()` path, which covers triage → plan → implement → review.
  HITL-specific integration scenarios can be tested by seeding issues into the
  HITL queue and invoking `hitl_phase` directly.
- Background GitHub polling is omitted; work is seeded directly via
  `enqueue_transition()`. The `refresh()` → `_build_label_map` → `_route_issues`
  path is intentionally not exercised by the harness; it is covered by dedicated
  `IssueStore` unit tests instead.

## Consequences

**Positive**

- Cross-phase tests cover the real queue/state interactions, so regressions in
  label routing, queue publishing, or persistence logic surface immediately rather
  than leaking into production orchestrator runs.
- Shared harness code reduces bespoke mock setups across test files and increases
  confidence that future multi-phase scenarios reuse the same proven fixture.
- EventBus metrics and queue snapshots emitted during tests double as living
  documentation for the dashboard contract, aiding reviewers and future ADRs.
- The `PipelineRunResult` return contract gives tests a structured assertion surface
  with queue snapshots at each phase boundary, reducing boilerplate assertions.

**Negative / Trade-offs**

- Running real IssueStore/StateTracker/EventBus objects inside tests requires an
  async event loop and filesystem access, so tests are slower than pure unit tests
  and must be marked `pytest.mark.asyncio`.
- Mocking runners/PRManager still leaves gaps around git side effects, so failures
  in Worktree orchestration continue to rely on dedicated implement-phase tests.
- The harness introduces more moving parts per test case, raising the bar for
  contributors who only need to cover a single phase.
- The `enqueue_transition`-based seeding strategy deliberately skips the external
  polling path (see Scope boundaries), which means label-routing correctness for
  `_build_label_map` and `_route_issues` depends entirely on dedicated `IssueStore`
  unit tests — a gap contributors must remember to maintain.

## Alternatives considered

1. **Continue phase-by-phase mocks** — rejected because they never exercise the
   real IssueStore queues or EventBus updates, so routing regressions go unnoticed.
2. **Full end-to-end tests with live GitHub** — rejected for cost and brittleness; a
   hermetic harness with mocked runners provides 90% coverage without network IO or
   secrets management.
3. **Fetcher mock + `refresh()`-based seeding** — considered but not adopted. This
   approach would wire the fetcher `AsyncMock` to return pre-built issues and call
   `refresh()` to exercise `_build_label_map` and `_route_issues` end-to-end, but
   it couples test setup to the external-polling path. The `enqueue_transition`
   approach was chosen for simplicity and directness, with `refresh()` coverage
   deferred to `IssueStore` unit tests.

## Related

- Source memory: [#1953 — Integration test architecture pattern for cross-phase testing](https://github.com/T-rav/hydra/issues/1953)
- Implementing issue: [#1977](https://github.com/T-rav/hydra/issues/1977)
- Supporting learning: [#2027 — PipelineHarness for orchestrator loops](https://github.com/T-rav/hydra/issues/2027)
