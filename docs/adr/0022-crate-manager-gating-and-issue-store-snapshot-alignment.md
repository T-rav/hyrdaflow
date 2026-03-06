# ADR-0022: CrateManager Gating and IssueStore Snapshot Alignment

- Status: Proposed
- Date: 2026-03-06

## Context

HydraFlow now processes issues in "crates" (GitHub milestones) to keep each pipeline run focused. The `CrateManager` exposes a single gate, `is_in_active_crate()`, which compares `task.metadata["milestone_number"]` to the active crate number persisted in state (`src/crate_manager.py:21-168`). Queue consumers rely on `IssueStore._take_from_queue()` to respect that gate: when a crate is active, the dequeuer skips non-matching issues for every stage except `find` (`src/issue_store.py:413-449`).

The dashboard, orchestration tooling, and supervisors read from `IssueStore.get_pipeline_snapshot()`, which currently builds the queued view via `_snapshot_queued()` without applying the same crate filter (`src/issue_store.py:536-567`). As a result, the UI and metrics can display queued issues that the workers are not allowed to pull yet, forcing humans to mentally diff two sources of truth.

A related observation from memory issue #1979 is that `PipelineSnapshotEntry` is a plain `TypedDict` whose `status` field is typed as `str` (`src/models.py:1452-1461`). Validation happens later via the `PipelineIssue` Pydantic model and its `PipelineIssueStatus` `StrEnum` (`src/models.py:1131-1157`), so adding a new status only requires extending the enum, but this coupling was undocumented.

## Decision

1. **Crate gate is canonical for visibility and dequeueing.** `IssueStore` will expose a shared helper that encapsulates the crate filter (including the `stage != STAGE_FIND` exemption) and both `_take_from_queue()` and `_snapshot_queued()` must use it before surfacing issues. This keeps dashboards, queue stats, and worker dequeues consistent and makes the crate gate observable by HydraFlow operators.
2. **Snapshot statuses stay stringly-typed at the transport layer but are validated centrally.** `PipelineSnapshotEntry` remains a `TypedDict[str]` to keep the JSON wire format stable, while `PipelineIssueStatus` defines the authoritative status vocabulary. Implementation guideline: when adding a status, update the enum first, then teach the snapshot builder to emit that enum value as a string.
3. **Operational boundaries.** `CrateManager` owns crate membership, `IssueStore` owns queue visibility, and downstream consumers treat the snapshot as filtered truth. Workers outside the orchestrator (e.g., dashboard refreshers) must not bypass `IssueStore` or disable the gate ad hoc; any tooling that needs the raw backlog should query GitHub directly or add a dedicated API.
4. **Linked artifacts.** This ADR documents source memory [#1979](https://github.com/T-rav/hydra/issues/1979) and issue [#1981](https://github.com/T-rav/hydra/issues/1981) so future audits can trace the reasoning back to the crate-filtering regression report.

## Consequences

**Positive:**

- Snapshot data now mirrors the work queues, eliminating discrepancies between what agents can work on and what the dashboard promises.
- Operators gain a single place (`IssueStore`) to adjust crate filtering logic, simplifying future experiments (e.g., multiple concurrent crates or "ungated" maintenance queues).
- Documenting the status contract clarifies that most caller code should import `PipelineIssueStatus` rather than duplicating literals, reducing drift.
- HydraFlow workers (planners, implementers, reviewers) now see only actionable work in their dequeues and dashboards, reducing idle cycles spent polling non-crate tasks.

**Negative / Trade-offs:**

- Blocking queued visibility by crate might hide backlog pressure unless a separate ungated report is built; this is an intentional trade-off to keep the live dashboard actionable.
- Tighter coupling between `IssueStore` and `CrateManager` means simulator tests must provide crate metadata, raising the bar for test fixtures.
- Adding new statuses still requires coordination between the enum definition, the snapshot builder, and any front-end components that render them.

## Alternatives considered

1. **Gating only at dequeue time.** Rejected because operators still saw "phantom" items in dashboards and could not explain why agents appeared idle.
2. **Duplicating crate-filtering logic in the dashboard backend.** Rejected to avoid spreading policy logic; the IssueStore already has the necessary state and caches.
3. **Upgrading `PipelineSnapshotEntry.status` to `PipelineIssueStatus`.** Deferred to maintain backwards compatibility for existing JSON consumers and to avoid forcing TypedDict -> Pydantic migrations mid-release.

## Related

- Source memory: [#1979 — CrateManager gating and IssueStore snapshot architecture](https://github.com/T-rav/hydra/issues/1979)
- Tracking issue: [#1981 — ADR for CrateManager gating and IssueStore snapshot alignment](https://github.com/T-rav/hydra/issues/1981)
- Code references: `src/issue_store.py` (queue dequeue vs. snapshot), `src/crate_manager.py` (active crate membership), `src/models.py` (`PipelineSnapshotEntry`, `PipelineIssueStatus`)
