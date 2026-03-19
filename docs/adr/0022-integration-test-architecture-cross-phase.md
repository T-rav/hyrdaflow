# ADR-0022: Integration Test Architecture — Cross-Phase Pipeline Harness

**Status:** Accepted
**Date:** 2026-03-06

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
`src/state.py:StateTracker`.

Several concrete requirements flow from the production code:

- `IssueStore.refresh()` pulls tasks via a `TaskFetcher` protocol
  (`src/task_source.py`). Tests must provide a fetcher that implements
  `fetch_all()` so refresh() repopulates the queues exactly like production.
- Label routing depends on config-driven tags (`hydraflow-find`, `hydraflow-plan`,
  `hydraflow-ready`, `hydraflow-review`). Without realistic tags, the `_build_label_map`
  logic in `IssueStore` will route nothing to downstream phases, so integration tests
  would give false confidence.
- Queue updates are published via `_publish_queue_update_nowait()`, which calls
  `loop.create_task()` on the running loop (`src/issue_store.py:_publish_queue_update_nowait`). Tests must run
  under `pytest-asyncio` (or an equivalent running event loop) and often need
  `await asyncio.sleep(0)` so those fire-and-forget `EventBus.publish()` tasks drain
  before making assertions.
- Planner/implement/review loops need the persisted state transitions tracked by
  `StateTracker` (`src/state.py`). Using the real tracker against a `tmp_path`
  ensures the harness observes activity counters, crate membership, and crash
  recovery semantics that single-phase mocks currently skip.

## Decision

Ratify the existing **Pipeline Harness** pattern for cross-phase integration tests.
The harness, already implemented in `tests/helpers.py:PipelineHarness` and exercised
by `tests/test_integration_pipeline.py`, uses real queueing and state components with
controlled mocks for external systems.

### Harness composition

1. **Core services:** `PipelineHarness.__init__` instantiates `HydraFlowConfig`,
   `StateTracker`, `EventBus`, and `IssueStore` exactly as production code does.
   The tracker persists to a temporary directory so repeated phase invocations
   observe real disk writes.
2. **Task ingestion:** Two implementations satisfy the `TaskFetcher.fetch_all()`
   protocol. `PipelineHarness` uses an `AsyncMock` fetcher whose return value tests
   control directly. `tests/orchestrator_integration_utils.py:StaticTaskFetcher`
   provides a reusable concrete implementation that returns `Task` instances whose
   `tags` already match the configured HydraFlow labels. Both approaches call
   `await IssueStore.refresh()` inside harness setup so queues populate from the
   fetcher instead of hand-inserting tasks.
3. **Phase runners:** Runners that invoke external AI agents or GitHub APIs are
   mocked (`TriageRunner`, `PlannerRunner`, `AgentRunner`, `ReviewRunner`, and the
   `PRManager`). They expose deterministic hooks (e.g., `AsyncMock` side effects)
   that tests assert on while allowing the harness to drive real orchestrator loops.
4. **Event propagation:** The `EventBus` instance is shared with every phase so
   queue metrics, worker updates, and transcript events mirror production routing.
   Integration tests subscribe to the bus via `async for` iterators or capture
   snapshots directly from `EventBus` to verify emitted events.
5. **Clocking:** A single `asyncio.Event` stop flag lets the harness start and stop
   each phase loop deterministically while still running inside
   `pytest.mark.asyncio` tests.

### Execution semantics

- After each `refresh()` or queue-modifying action, `await asyncio.sleep(0)` (or an
  explicit helper) flushes `loop.create_task()` callbacks emitted by
  `_publish_queue_update_nowait()`. This keeps queue stats observed by the harness in
  sync with expectations.
- When tests need to seed new work mid-run, they update the fetcher's return value
  and call `await IssueStore.refresh()` again rather than mutating queues directly.
  That guarantees `_route_issues()` and `IssueStoreStage` priorities are exercised
  end-to-end.
- Tests use `pytest-asyncio` to provide the event loop and rely on the same config
  labels used in production (read from `HydraFlowConfig.find_label`, `planner_label`,
  `ready_label`, and `review_label`).

### Scope boundaries

- The harness stops at the PR boundary: `PRManager`, `WorktreeManager`, and
  external CLI invocations remain mocked so tests stay hermetic.
- Background GitHub polling is replaced by deterministic fetcher responses, but the
  harness deliberately leaves `IssueStore.refresh()` untouched so routing logic,
  deduplication, and queue statistics are validated.

### Operational impact on HydraFlow workers

- Each HydraFlow worker loop (triage, planner, implement, review) runs against the
  same `EventBus` instance and async stop flag, matching the orchestration model in
  production so queue-drain behaviour and worker lifecycle hooks are validated.
- Using the real `StateTracker` preserves worker counters, crash-recovery markers,
  and pause/resume semantics so integration tests detect regressions that would
  otherwise only surface when supervisors restart HydraFlow processes.
- Config-driven tags flowing through `IssueStore.refresh()` ensure workers see the
  same label transitions and queue membership rules enforced in live runs, giving
  reviewers confidence that scheduler decisions stay aligned with operational
  limits (max planners, reviewers, etc.).

## Consequences

**Positive**

- Cross-phase tests cover the real queue/state interactions, so regressions in
  label routing, queue publishing, or persistence logic surface immediately rather
  than leaking into production orchestrator runs.
- Shared harness code reduces bespoke mock setups across test files and increases
  confidence that future multi-phase scenarios reuse the same proven fixture.
- EventBus metrics and queue snapshots emitted during tests provide observability
  into cross-phase event flow, aiding reviewers and future ADRs.

**Negative / Trade-offs**

- Running real IssueStore/StateTracker/EventBus objects inside tests requires an
  async event loop and filesystem access, so tests are slower than pure unit tests
  and must be marked `pytest.mark.asyncio`.
- Mocking runners/PRManager still leaves gaps around git side effects, so failures
  in Worktree orchestration continue to rely on dedicated implement-phase tests.
- The harness introduces more moving parts per test case, raising the bar for
  contributors who only need to cover a single phase.

## Alternatives considered

1. **Continue phase-by-phase mocks** — rejected because they never exercise the
   real IssueStore queues or EventBus updates, so routing regressions go unnoticed.
2. **Full end-to-end tests with live GitHub** — rejected for cost and brittleness; a
   hermetic harness with mocked runners provides 90% coverage without network IO or
   secrets management.
3. **pytest fixtures instead of a helper class** — considered but rejected because a
   standalone `PipelineHarness` class encapsulates the wiring of five phases, their
   shared stores, and mock setup in one place. A fixture-based approach would scatter
   this wiring across conftest files or require a factory fixture that duplicates the
   class structure, with no clear advantage.

## Related

- Source memory: [#1953 — Integration test architecture pattern for cross-phase testing](https://github.com/T-rav/hydra/issues/1953)
- Implementing issue: [#1977](https://github.com/T-rav/hydra/issues/1977)
- Supporting learning: [#2027 — PipelineHarness for orchestrator loops](https://github.com/T-rav/hydra/issues/2027)
