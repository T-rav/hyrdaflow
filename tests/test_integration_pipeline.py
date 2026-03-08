"""Integration tests covering cross-phase pipeline flows."""

from __future__ import annotations

from unittest.mock import call

import pytest

from events import EventType
from issue_store import IssueStoreStage
from models import IssueOutcomeType, ReviewVerdict
from tests.conftest import PlanResultFactory, TaskFactory
from tests.helpers import PipelineHarness, PipelineRunResult


@pytest.mark.asyncio
async def test_pipeline_lifecycle_integration(tmp_path):
    harness = PipelineHarness(tmp_path)
    result: PipelineRunResult = await harness.run_full_lifecycle(task_id=401)

    assert result.triaged_count == 1
    assert result.plan_results and result.plan_results[0].success
    assert result.worker_results and result.worker_results[0].success
    assert (
        result.review_results
        and result.review_results[0].verdict == ReviewVerdict.APPROVE
    )

    transition_calls = harness.prs.transition.await_args_list
    assert len(transition_calls) >= 3
    assert transition_calls[0] == call(result.task.id, "plan")
    assert transition_calls[1] == call(result.task.id, "ready")
    review_call = transition_calls[2]
    assert review_call.args[:2] == (result.task.id, "review")
    assert review_call.kwargs["pr_number"] == result.worker_results[0].pr_info.number


@pytest.mark.asyncio
async def test_plannable_data_flow_uses_issue_store_objects(tmp_path):
    harness = PipelineHarness(tmp_path)
    task = TaskFactory.create(
        id=777,
        tags=[harness.config.planner_label[0]],
    )
    harness.seed_issue(task, "plan")
    harness.planners.plan.return_value = PlanResultFactory.create(issue_number=task.id)

    await harness.plan_phase.plan_issues()

    assert harness.planners.plan.await_args_list, (
        "plan() was never called; check task seeding"
    )
    called_issue = harness.planners.plan.await_args_list[0].args[0]
    assert called_issue is task


@pytest.mark.asyncio
async def test_event_bus_emits_ordered_phase_events(tmp_path):
    harness = PipelineHarness(tmp_path)
    result = await harness.run_full_lifecycle(task_id=502)

    queue_events = [e for e in result.events if e.type == EventType.QUEUE_UPDATE]
    assert queue_events, "expected queue depth updates for each phase"

    def _find_event(
        stage: IssueStoreStage, depth: int, *, processed: int | None = None
    ) -> tuple[int, dict]:
        for idx, event in enumerate(queue_events):
            q_depth = event.data.get("queue_depth", {})
            totals = event.data.get("total_processed", {})
            if q_depth.get(stage.value) != depth:
                continue
            if processed is not None and totals.get(stage.value, 0) < processed:
                continue
            return idx, event.data
        raise AssertionError(f"no queue event reached {stage.value} depth={depth}")

    plan_idx, _ = _find_event(IssueStoreStage.PLAN, 1)
    ready_idx, _ = _find_event(IssueStoreStage.READY, 1)
    review_idx, _ = _find_event(IssueStoreStage.REVIEW, 1)
    drained_idx, drained_event = _find_event(IssueStoreStage.REVIEW, 0, processed=1)

    assert plan_idx < ready_idx < review_idx < drained_idx
    assert drained_event["total_processed"][IssueStoreStage.REVIEW.value] >= 1

    statuses = [
        e.data.get("status") for e in result.events if e.type == EventType.REVIEW_UPDATE
    ]
    assert statuses and statuses[0] == "start"
    assert "merging" in statuses


@pytest.mark.asyncio
async def test_post_merge_chain_updates_state_and_cleans_worktree(tmp_path):
    harness = PipelineHarness(tmp_path)
    result = await harness.run_full_lifecycle(task_id=903)

    outcome = harness.state.get_outcome(result.task.id)
    assert outcome is not None
    assert outcome.outcome == IssueOutcomeType.MERGED

    cleanup_calls = harness.worktrees.post_work_cleanup.await_args_list
    assert cleanup_calls and cleanup_calls[-1] == call(result.task.id)
    assert harness.state.get_active_worktrees() == {}

    assert any(
        e.type == EventType.REVIEW_UPDATE and e.data.get("status") == "merging"
        for e in result.events
    )


@pytest.mark.asyncio
async def test_enqueue_transition_handoff_updates_queue_depths(tmp_path):
    harness = PipelineHarness(tmp_path)
    result = await harness.run_full_lifecycle(task_id=1205)

    triage_stats = result.snapshot("after_triage")
    assert triage_stats.queue_depth[IssueStoreStage.PLAN] == 1
    assert triage_stats.queue_depth[IssueStoreStage.FIND] == 0

    plan_stats = result.snapshot("after_plan")
    assert plan_stats.queue_depth[IssueStoreStage.READY] == 1
    assert plan_stats.queue_depth[IssueStoreStage.PLAN] == 0

    implement_stats = result.snapshot("after_implement")
    assert implement_stats.queue_depth[IssueStoreStage.REVIEW] == 1
    assert implement_stats.queue_depth[IssueStoreStage.READY] == 0

    review_stats = result.snapshot("after_review")
    assert review_stats.queue_depth[IssueStoreStage.REVIEW] == 0
    assert review_stats.total_processed[IssueStoreStage.PLAN] >= 1
    assert review_stats.total_processed[IssueStoreStage.REVIEW] >= 1
