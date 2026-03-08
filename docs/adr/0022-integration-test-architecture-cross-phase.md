# ADR-0022: Pipeline Integration Harness for Cross-Phase Testing

**Status:** Proposed
**Date:** 2026-03-06

## Context

HydraFlow's orchestrator spans five asynchronous phases that all rely on a shared
`IssueStore`, persistent `StateTracker`, and in-process `EventBus`. Individual test
modules cover each phase in isolation (see `tests/helpers.py:586` for the
single-phase factories), but regressions have started to appear when changes alter
how queues, runners, and GitHub labels interact across phase boundaries. Issue
#1953 captured the lesson learned while debugging those regressions: integration
tests must exercise the real queueing/data layers so they see the same routing
logic implemented in `src/issue_store.py`, the label-to-stage mapping in
`HydraFlowConfig` (`src/config.py`), and the persistence semantics inside
`src/state.py`.

Several concrete requirements flow from today's code:

- `IssueStore.refresh()` pulls tasks via a `TaskFetcher` protocol
  (`src/task_source.py`). Tests must provide a mock fetcher that implements
  `fetch_all()` so refresh() repopulates the queues exactly like production.
- Label routing depends on config-driven tags (`hydraflow-find`, `hydraflow-plan`,
  `hydraflow-ready`, `hydraflow-review`). Without realistic tags, the `_build_label_map`
  logic in `IssueStore` will route nothing to downstream phases, so integration tests
  would give false confidence.
- Queue updates are published via `_publish_queue_update_nowait()`, which calls
  `loop.create_task()` on the running loop (`src/issue_store.py:494`). Tests must run
  under `pytest-asyncio` (or an equivalent running event loop) and often need
  `await asyncio.sleep(0)` so those fire-and-forget `EventBus.publish()` tasks drain
  before making assertions.
- Planner/implement/review loops need the persisted state transitions tracked by
  `StateTracker` (`src/state.py`). Using the real tracker against a `tmp_path`
  ensures the harness observes activity counters, crate membership, and crash
  recovery semantics that single-phase mocks currently skip.

## Decision

Adopt a dedicated **Pipeline Harness** for cross-phase integration tests that uses
real queueing/state components and controlled mocks for external systems.

### Harness composition

1. **Core services:** Instantiate `HydraFlowConfig`, `StateTracker`, `EventBus`, and
   `IssueStore` exactly as production code does. The tracker persists to a
   temporary directory so repeated phase invocations observe real disk writes.
2. **Task ingestion:** Provide a purpose-built `MockTaskFetcher` that satisfies the
   `TaskFetcher.fetch_all()` protocol and returns `Task` instances whose `tags`
   already match the configured HydraFlow labels. Call `await IssueStore.refresh()`
   inside the harness setup so queues populate from this fetcher instead of
   hand-inserting tasks.
3. **Phase runners:** Keep runners that invoke external AI agents or GitHub APIs
   mocked (`TriageRunner`, `PlannerRunner`, `AgentRunner`, `ReviewRunner`, and the
   `PRManager`). They expose deterministic hooks (e.g., AsyncMocks) the tests can
   assert on while allowing the harness to drive real orchestrator loops.
4. **Event propagation:** Share the `EventBus` instance with every phase so queue
   metrics, worker updates, and transcript events mirror production routing.
   Integration tests subscribe to the bus via `async for` iterators or capture
   snapshots directly from `EventBus` to verify emitted events.
5. **Clocking:** Manage a single `asyncio.Event` stop flag so the harness can start
   and stop each phase loop deterministically while still running inside
   `pytest.mark.asyncio` tests.

### Execution semantics

- After each `refresh()` or queue-modifying action, `await asyncio.sleep(0)` (or an
  explicit helper) to flush `loop.create_task()` callbacks emitted by
  `_publish_queue_update_nowait()`. This keeps queue stats observed by the harness in
  sync with expectations.
- When tests need to seed new work mid-run, update the `MockTaskFetcher` return
  value and call `await IssueStore.refresh()` again rather than mutating queues
  directly. That guarantees `_route_issues()` and `IssueStoreStage` priorities are
  exercised end-to-end.
- Use `pytest-asyncio` to provide the event loop and rely on the same config labels
  used in production (read from `HydraFlowConfig.find_label`, `planner_label`,
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
- EventBus metrics and queue snapshots emitted during tests double as living
  documentation for the dashboard contract, aiding reviewers and future ADRs.

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

## Related

- Source memory: [#1953 — Integration test architecture pattern for cross-phase testing](https://github.com/T-rav/hydra/issues/1953)
- Implementing issue: [#1977](https://github.com/T-rav/hydra/issues/1977)
- Supporting learning: [#2027 — PipelineHarness for orchestrator loops](https://github.com/T-rav/hydra/issues/2027)
