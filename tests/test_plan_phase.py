"""Tests for plan_phase.py — PlanPhase."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock
from unittest.mock import patch as mock_patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from typing import TYPE_CHECKING

from events import EventBus
from issue_store import IssueStore
from models import PlanResult, Task
from plan_phase import PlanPhase
from state import StateTracker
from tests.conftest import TaskFactory

if TYPE_CHECKING:
    from config import HydraFlowConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_phase(
    config: HydraFlowConfig,
    *,
    summarizer: AsyncMock | None = None,
) -> tuple[PlanPhase, StateTracker, AsyncMock, AsyncMock, IssueStore, asyncio.Event]:
    """Build a PlanPhase with mock dependencies.

    Returns (phase, state, planners_mock, prs_mock, store, stop_event).
    """
    state = StateTracker(config.state_file)
    bus = EventBus()
    fetcher = AsyncMock()
    store = IssueStore(config, fetcher, bus)
    planners = AsyncMock()
    prs = AsyncMock()
    prs.post_comment = AsyncMock()
    prs.remove_label = AsyncMock()
    prs.add_labels = AsyncMock()
    prs.swap_pipeline_labels = AsyncMock()
    prs.transition = AsyncMock()
    prs.create_task = AsyncMock(return_value=99)
    prs.close_task = AsyncMock()
    stop_event = asyncio.Event()
    phase = PlanPhase(
        config,
        state,
        store,
        planners,
        prs,
        bus,
        stop_event,
        transcript_summarizer=summarizer,
    )
    return phase, state, planners, prs, store, stop_event


# ---------------------------------------------------------------------------
# Plan phase
# ---------------------------------------------------------------------------


class TestPlanPhase:
    """Tests for PlanPhase.plan_issues()."""

    @pytest.mark.asyncio
    async def test_plan_issues_posts_comment_on_success(
        self, config: HydraFlowConfig
    ) -> None:
        """On successful plan, post_comment should be called."""
        phase, _state, planners, prs, store, _stop = _make_phase(config)
        issue = TaskFactory.create(id=42)
        plan_result = PlanResult(
            issue_number=42,
            success=True,
            plan="Step 1: Do the thing",
            summary="Plan done",
            actionability_score=87,
            actionability_rank="high",
        )

        planners.plan = AsyncMock(return_value=plan_result)
        store.get_plannable = lambda _max_count: [issue]  # type: ignore[method-assign]

        await phase.plan_issues()

        # post_comment called twice: plan comment + analysis comment
        assert prs.post_comment.await_count >= 1
        plan_call = prs.post_comment.call_args_list[0]
        assert plan_call.args[0] == 42
        assert "Step 1: Do the thing" in plan_call.args[1]
        assert "agent/issue-42" in plan_call.args[1]
        assert "Actionability score:** 87/100 (high)" in plan_call.args[1]

    @pytest.mark.asyncio
    async def test_plan_issues_swaps_labels_on_success(
        self, config: HydraFlowConfig
    ) -> None:
        """On success, planner_label should be removed and config.ready_label added."""
        phase, _state, planners, prs, store, _stop = _make_phase(config)
        issue = TaskFactory.create(id=42)
        plan_result = PlanResult(
            issue_number=42,
            success=True,
            plan="The plan",
            summary="Done",
        )

        planners.plan = AsyncMock(return_value=plan_result)
        store.get_plannable = lambda _max_count: [issue]  # type: ignore[method-assign]

        await phase.plan_issues()

        prs.transition.assert_awaited_once_with(42, "ready")

    @pytest.mark.asyncio
    async def test_plan_issues_skips_label_swap_on_failure(
        self, config: HydraFlowConfig
    ) -> None:
        """On failure, no label changes should be made."""
        phase, _state, planners, prs, store, _stop = _make_phase(config)
        issue = TaskFactory.create(id=42)
        plan_result = PlanResult(
            issue_number=42,
            success=False,
            error="Agent crashed",
        )

        planners.plan = AsyncMock(return_value=plan_result)
        store.get_plannable = lambda _max_count: [issue]  # type: ignore[method-assign]

        await phase.plan_issues()

        prs.post_comment.assert_not_awaited()
        prs.remove_label.assert_not_awaited()
        prs.add_labels.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_plan_issues_returns_empty_when_no_issues(
        self, config: HydraFlowConfig
    ) -> None:
        """When no issues have the planner label, return empty list."""
        phase, _state, _planners, _prs, store, _stop = _make_phase(config)
        store.get_plannable = lambda _max_count: []  # type: ignore[method-assign]

        results = await phase.plan_issues()

        assert results == []

    @pytest.mark.asyncio
    async def test_plan_issue_creation_records_lifetime_stats(
        self, config: HydraFlowConfig
    ) -> None:
        """record_issue_created should be called for each new issue filed by planner."""
        from models import NewIssueSpec

        phase, state, planners, prs, store, _stop = _make_phase(config)
        issue = TaskFactory.create(id=42)
        plan_result = PlanResult(
            issue_number=42,
            success=True,
            plan="The plan",
            summary="Done",
            new_issues=[
                NewIssueSpec(
                    title="Issue A",
                    body="Issue A has a bug in the authentication flow "
                    "that causes login failures on retry.",
                    labels=["bug"],
                ),
                NewIssueSpec(
                    title="Issue B",
                    body="Issue B has a race condition in the websocket "
                    "handler that drops messages under load.",
                    labels=["bug"],
                ),
            ],
        )

        planners.plan = AsyncMock(return_value=plan_result)
        store.get_plannable = lambda _max_count: [issue]  # type: ignore[method-assign]

        await phase.plan_issues()

        stats = state.get_lifetime_stats()
        assert stats.issues_created == 2

    @pytest.mark.asyncio
    async def test_plan_issues_files_new_issues(self, config: HydraFlowConfig) -> None:
        """When planner discovers new issues, they should be filed via create_issue."""
        from models import NewIssueSpec

        phase, _state, planners, prs, store, _stop = _make_phase(config)
        issue = TaskFactory.create(id=42)
        plan_result = PlanResult(
            issue_number=42,
            success=True,
            plan="The plan",
            summary="Done",
            new_issues=[
                NewIssueSpec(
                    title="Tech debt",
                    body="The auth module has accumulated significant tech debt "
                    "that needs cleanup and refactoring.",
                    labels=["tech-debt"],
                ),
            ],
        )

        planners.plan = AsyncMock(return_value=plan_result)
        store.get_plannable = lambda _max_count: [issue]  # type: ignore[method-assign]

        await phase.plan_issues()

        prs.create_task.assert_awaited_once_with(
            "Tech debt",
            "The auth module has accumulated significant tech debt "
            "that needs cleanup and refactoring.",
            ["tech-debt"],
        )

    @pytest.mark.asyncio
    async def test_plan_issues_semaphore_limits_concurrency(
        self, config: HydraFlowConfig
    ) -> None:
        """max_planners=1 means at most 1 planner runs concurrently."""
        concurrency_counter = {"current": 0, "peak": 0}

        async def fake_plan(issue: Task, worker_id: int = 0) -> PlanResult:
            concurrency_counter["current"] += 1
            concurrency_counter["peak"] = max(
                concurrency_counter["peak"], concurrency_counter["current"]
            )
            await asyncio.sleep(0)  # yield to allow other tasks to start
            concurrency_counter["current"] -= 1
            return PlanResult(
                issue_number=issue.id,
                success=True,
                plan="The plan",
                summary="Done",
            )

        issues = [TaskFactory.create(id=i) for i in range(1, 6)]

        phase, _state, planners, prs, store, _stop = _make_phase(config)
        planners.plan = fake_plan
        store.get_plannable = lambda _max_count: issues  # type: ignore[method-assign]

        await phase.plan_issues()

        assert concurrency_counter["peak"] <= config.max_planners

    @pytest.mark.asyncio
    async def test_plan_issues_marks_active_during_processing(
        self, config: HydraFlowConfig
    ) -> None:
        """Plan should mark issues active to prevent re-queuing by refresh."""
        phase, _state, planners, prs, store, _stop = _make_phase(config)
        issue = TaskFactory.create(id=42)

        was_active_during_plan = False

        async def check_active_plan(
            issue_obj: object, worker_id: int = 0
        ) -> PlanResult:
            nonlocal was_active_during_plan
            was_active_during_plan = store.is_active(42)
            return PlanResult(
                issue_number=42, success=True, plan="Plan", summary="Done"
            )

        planners.plan = AsyncMock(side_effect=check_active_plan)
        store.get_plannable = lambda _max_count: [issue]  # type: ignore[method-assign]

        await phase.plan_issues()

        assert was_active_during_plan, "Issue should be marked active during planning"
        assert not store.is_active(42), "Issue should be released after planning"

    @pytest.mark.asyncio
    async def test_plan_issues_failure_returns_result_with_error(
        self, config: HydraFlowConfig
    ) -> None:
        """Plan failure (success=False) should still return the result."""
        phase, _state, planners, prs, store, _stop = _make_phase(config)
        issue = TaskFactory.create(id=42)
        plan_result = PlanResult(
            issue_number=42,
            success=False,
            error="Agent crashed",
        )

        planners.plan = AsyncMock(return_value=plan_result)
        store.get_plannable = lambda _max_count: [issue]  # type: ignore[method-assign]

        results = await phase.plan_issues()

        assert len(results) == 1
        assert results[0].success is False
        assert results[0].error == "Agent crashed"

    @pytest.mark.asyncio
    async def test_plan_issues_new_issues_use_default_planner_label_when_no_labels(
        self, config: HydraFlowConfig
    ) -> None:
        """New issues with empty labels should fall back to planner_label."""
        from models import NewIssueSpec

        phase, _state, planners, prs, store, _stop = _make_phase(config)
        issue = TaskFactory.create(id=42)
        plan_result = PlanResult(
            issue_number=42,
            success=True,
            plan="The plan",
            summary="Done",
            new_issues=[
                NewIssueSpec(
                    title="Discovered issue",
                    body="This issue was discovered during planning — the config "
                    "parser does not handle nested environment variables.",
                ),
            ],
        )

        planners.plan = AsyncMock(return_value=plan_result)
        store.get_plannable = lambda _max_count: [issue]  # type: ignore[method-assign]

        await phase.plan_issues()

        prs.create_task.assert_awaited_once_with(
            "Discovered issue",
            "This issue was discovered during planning — the config "
            "parser does not handle nested environment variables.",
            [config.planner_label[0]],
        )

    @pytest.mark.asyncio
    async def test_plan_issues_skips_new_issues_with_short_body(
        self, config: HydraFlowConfig
    ) -> None:
        """New issues with body < 50 chars should be skipped, not filed."""
        from models import NewIssueSpec

        phase, state, planners, prs, store, _stop = _make_phase(config)
        issue = TaskFactory.create(id=42)
        plan_result = PlanResult(
            issue_number=42,
            success=True,
            plan="The plan",
            summary="Done",
            new_issues=[
                NewIssueSpec(title="Short body issue", body="Too short"),
            ],
        )

        planners.plan = AsyncMock(return_value=plan_result)
        store.get_plannable = lambda _max_count: [issue]  # type: ignore[method-assign]

        await phase.plan_issues()

        prs.create_task.assert_not_awaited()
        assert state.get_lifetime_stats().issues_created == 0

    @pytest.mark.asyncio
    async def test_plan_issues_stop_event_cancels_remaining(
        self, config: HydraFlowConfig
    ) -> None:
        """Setting stop_event after first plan should cancel remaining."""
        phase, _state, planners, prs, store, stop_event = _make_phase(config)
        issues = [
            TaskFactory.create(id=1),
            TaskFactory.create(id=2),
            TaskFactory.create(id=3),
        ]
        call_count = {"n": 0}

        async def fake_plan(issue: Task, worker_id: int = 0) -> PlanResult:
            call_count["n"] += 1
            if call_count["n"] == 1:
                stop_event.set()
            return PlanResult(
                issue_number=issue.id,
                success=False,
                error="stopped",
            )

        planners.plan = fake_plan
        store.get_plannable = lambda _max_count: issues  # type: ignore[method-assign]

        results = await phase.plan_issues()

        # Not all 3 should have completed — stop event triggers cancellation
        assert len(results) < len(issues)

    @pytest.mark.asyncio
    async def test_plan_issues_escalates_to_hitl_after_retry_failure(
        self, config: HydraFlowConfig
    ) -> None:
        """Failed retry triggers HITL label swap and comment."""
        phase, state, planners, prs, store, _stop = _make_phase(config)
        issue = TaskFactory.create(id=42)
        plan_result = PlanResult(
            issue_number=42,
            success=False,
            plan="Bad plan",
            summary="Failed",
            retry_attempted=True,
            validation_errors=[
                "Missing required section: ## Testing Strategy",
                "Plan has 10 words, minimum is 200",
            ],
        )

        planners.plan = AsyncMock(return_value=plan_result)
        store.get_plannable = lambda _max_count: [issue]  # type: ignore[method-assign]

        await phase.plan_issues()

        # HITL comment should be posted
        prs.post_comment.assert_awaited_once()
        comment = prs.post_comment.call_args.args[1]
        assert "Plan Validation Failed" in comment
        assert "Testing Strategy" in comment

        # Planner label removed, HITL label added via swap (escalate_to_hitl still uses swap_pipeline_labels)
        prs.swap_pipeline_labels.assert_awaited_once_with(42, config.hitl_label[0])

        # HITL origin and cause tracked in state
        assert state.get_hitl_origin(42) == config.planner_label[0]
        assert state.get_hitl_cause(42) == "Plan validation failed after retry"

    @pytest.mark.asyncio
    async def test_plan_issues_no_hitl_on_failure_without_retry(
        self, config: HydraFlowConfig
    ) -> None:
        """Normal failure (no retry) should NOT escalate to HITL."""
        phase, _state, planners, prs, store, _stop = _make_phase(config)
        issue = TaskFactory.create(id=42)
        plan_result = PlanResult(
            issue_number=42,
            success=False,
            error="Agent crashed",
            retry_attempted=False,
        )

        planners.plan = AsyncMock(return_value=plan_result)
        store.get_plannable = lambda _max_count: [issue]  # type: ignore[method-assign]

        await phase.plan_issues()

        prs.post_comment.assert_not_awaited()
        prs.remove_label.assert_not_awaited()
        prs.add_labels.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_plan_issues_runs_analysis_before_label_swap(
        self, config: HydraFlowConfig
    ) -> None:
        """Analysis comment should be posted after the plan comment."""
        phase, _state, planners, prs, store, _stop = _make_phase(config)
        issue = TaskFactory.create(id=42)
        plan_result = PlanResult(
            issue_number=42,
            success=True,
            plan="## Files to Modify\n\n- `models.py`: change\n\n## Testing Strategy\n\nUse pytest.",
            summary="Plan done",
        )

        # Create the files so analysis passes
        repo = config.repo_root
        repo.mkdir(parents=True, exist_ok=True)
        (repo / "models.py").write_text("# models\n")
        (repo / "tests").mkdir(exist_ok=True)
        (repo / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")

        planners.plan = AsyncMock(return_value=plan_result)
        store.get_plannable = lambda _max_count: [issue]  # type: ignore[method-assign]

        await phase.plan_issues()

        # Two comments: plan + analysis
        assert prs.post_comment.await_count == 2
        analysis_comment = prs.post_comment.call_args_list[1].args[1]
        assert "Pre-Implementation Analysis" in analysis_comment

    @pytest.mark.asyncio
    async def test_plan_issues_proceeds_on_analysis_pass(
        self, config: HydraFlowConfig
    ) -> None:
        """PASS verdict should proceed with normal label swap."""
        from analysis import PlanAnalyzer
        from models import AnalysisResult, AnalysisSection, AnalysisVerdict

        phase, _state, planners, prs, store, _stop = _make_phase(config)
        issue = TaskFactory.create(id=42)
        plan_result = PlanResult(
            issue_number=42,
            success=True,
            plan="The plan",
            summary="Done",
        )

        pass_result = AnalysisResult(
            issue_number=42,
            sections=[
                AnalysisSection(
                    name="File Validation",
                    verdict=AnalysisVerdict.PASS,
                    details=["All good"],
                ),
            ],
        )

        planners.plan = AsyncMock(return_value=plan_result)
        store.get_plannable = lambda _max_count: [issue]  # type: ignore[method-assign]

        with mock_patch.object(PlanAnalyzer, "analyze", return_value=pass_result):
            await phase.plan_issues()

        # Should swap to ready label
        prs.transition.assert_awaited_once_with(42, "ready")

    @pytest.mark.asyncio
    async def test_plan_issues_proceeds_on_analysis_warn(
        self, config: HydraFlowConfig
    ) -> None:
        """WARN verdict should still proceed with normal label swap."""
        from analysis import PlanAnalyzer
        from models import AnalysisResult, AnalysisSection, AnalysisVerdict

        phase, _state, planners, prs, store, _stop = _make_phase(config)
        issue = TaskFactory.create(id=42)
        plan_result = PlanResult(
            issue_number=42,
            success=True,
            plan="The plan",
            summary="Done",
        )

        warn_result = AnalysisResult(
            issue_number=42,
            sections=[
                AnalysisSection(
                    name="Conflict Check",
                    verdict=AnalysisVerdict.WARN,
                    details=["Minor overlap"],
                ),
            ],
        )

        planners.plan = AsyncMock(return_value=plan_result)
        store.get_plannable = lambda _max_count: [issue]  # type: ignore[method-assign]

        with mock_patch.object(PlanAnalyzer, "analyze", return_value=warn_result):
            await phase.plan_issues()

        # Should swap to ready label (warn doesn't block)
        prs.transition.assert_awaited_once_with(42, "ready")


# ---------------------------------------------------------------------------
# Plan phase — already_satisfied
# ---------------------------------------------------------------------------


class TestPlanPhaseAlreadySatisfied:
    """Tests for already_satisfied handling in the plan phase."""

    @pytest.mark.asyncio
    async def test_plan_already_satisfied_closes_issue_with_dup_label(
        self, config: HydraFlowConfig
    ) -> None:
        """When planner returns already_satisfied, issue should be closed with dup label."""
        phase, _state, planners, prs, store, _stop = _make_phase(config)
        issue = TaskFactory.create(id=42)
        plan_result = PlanResult(
            issue_number=42,
            success=True,
            already_satisfied=True,
            summary="The feature is already implemented in src/models.py",
        )

        planners.plan = AsyncMock(return_value=plan_result)
        store.get_plannable = lambda _max_count: [issue]  # type: ignore[method-assign]

        await phase.plan_issues()

        # Should swap to dup label
        prs.swap_pipeline_labels.assert_awaited_once_with(42, config.dup_label[0])

        # Comment should be posted
        prs.post_comment.assert_awaited_once()
        comment = prs.post_comment.call_args.args[1]
        assert "Already Satisfied" in comment
        assert "HydraFlow Planner" in comment

        # Issue should be closed
        prs.close_task.assert_awaited_once_with(42)

    @pytest.mark.asyncio
    async def test_plan_already_satisfied_does_not_swap_to_ready(
        self, config: HydraFlowConfig
    ) -> None:
        """When already_satisfied, issue should NOT get hydraflow-ready label."""
        phase, _state, planners, prs, store, _stop = _make_phase(config)
        issue = TaskFactory.create(id=42)
        plan_result = PlanResult(
            issue_number=42,
            success=True,
            already_satisfied=True,
            summary="Already met",
        )

        planners.plan = AsyncMock(return_value=plan_result)
        store.get_plannable = lambda _max_count: [issue]  # type: ignore[method-assign]

        await phase.plan_issues()

        # Should NOT add ready label
        add_calls = [c.args for c in prs.add_labels.call_args_list]
        ready_calls = [c for c in add_calls if config.ready_label[0] in c[1]]
        assert len(ready_calls) == 0

    @pytest.mark.asyncio
    async def test_epic_child_not_closed_as_already_satisfied(
        self, config: HydraFlowConfig
    ) -> None:
        """Epic children should never be auto-closed as already satisfied."""
        phase, _state, planners, prs, store, _stop = _make_phase(config)
        issue = TaskFactory.create(id=42, tags=["hydraflow-epic-child"])
        plan_result = PlanResult(
            issue_number=42,
            success=True,
            already_satisfied=True,
            summary="The feature is already implemented",
        )

        planners.plan = AsyncMock(return_value=plan_result)
        store.get_plannable = lambda _max_count: [issue]  # type: ignore[method-assign]

        await phase.plan_issues()

        # Should NOT close the issue
        prs.close_task.assert_not_awaited()
        # Should NOT swap to dup label
        prs.swap_pipeline_labels.assert_not_awaited()


# ---------------------------------------------------------------------------
# Plan phase — transcript summary comments
# ---------------------------------------------------------------------------


class TestPlanPhaseTranscriptSummary:
    """Tests for transcript summary comments after plan phase."""

    @pytest.mark.asyncio
    async def test_successful_plan_calls_summarize_and_comment(
        self, config: HydraFlowConfig
    ) -> None:
        """After successful plan, summarize_and_comment is called with phase=plan."""
        mock_summarizer = AsyncMock()
        mock_summarizer.summarize_and_comment = AsyncMock(return_value=True)
        phase, _state, planners, prs, store, _stop = _make_phase(
            config, summarizer=mock_summarizer
        )
        issue = TaskFactory.create(id=42, title="Fix bug")
        plan_result = PlanResult(
            issue_number=42,
            success=True,
            plan="Step 1: Do the thing",
            summary="Plan done",
            transcript="x" * 1000,
            duration_seconds=30.0,
        )

        planners.plan = AsyncMock(return_value=plan_result)
        store.get_plannable = lambda _max_count: [issue]  # type: ignore[method-assign]

        await phase.plan_issues()

        mock_summarizer.summarize_and_comment.assert_awaited_once()
        call_kwargs = mock_summarizer.summarize_and_comment.call_args
        assert call_kwargs.kwargs["phase"] == "plan"
        assert call_kwargs.kwargs["status"] == "success"
        assert call_kwargs.kwargs["issue_title"] == "Fix bug"
        assert call_kwargs.kwargs["duration_seconds"] == 30.0
        assert ".hydraflow/logs/plan-issue-42.txt" in call_kwargs.kwargs["log_file"]

    @pytest.mark.asyncio
    async def test_failed_plan_escalation_calls_summarize_with_escalated(
        self, config: HydraFlowConfig
    ) -> None:
        """After HITL escalation, status should be 'escalated'."""
        mock_summarizer = AsyncMock()
        mock_summarizer.summarize_and_comment = AsyncMock(return_value=True)
        phase, _state, planners, prs, store, _stop = _make_phase(
            config, summarizer=mock_summarizer
        )
        issue = TaskFactory.create(id=42)
        plan_result = PlanResult(
            issue_number=42,
            success=False,
            retry_attempted=True,
            transcript="x" * 1000,
            validation_errors=["Missing section"],
        )

        planners.plan = AsyncMock(return_value=plan_result)
        store.get_plannable = lambda _max_count: [issue]  # type: ignore[method-assign]

        await phase.plan_issues()

        mock_summarizer.summarize_and_comment.assert_awaited_once()
        assert (
            mock_summarizer.summarize_and_comment.call_args.kwargs["status"]
            == "escalated"
        )

    @pytest.mark.asyncio
    async def test_failed_plan_calls_summarize_with_failed(
        self, config: HydraFlowConfig
    ) -> None:
        """After plan failure (no retry), status should be 'failed'."""
        mock_summarizer = AsyncMock()
        mock_summarizer.summarize_and_comment = AsyncMock(return_value=True)
        phase, _state, planners, prs, store, _stop = _make_phase(
            config, summarizer=mock_summarizer
        )
        issue = TaskFactory.create(id=42)
        plan_result = PlanResult(
            issue_number=42,
            success=False,
            transcript="x" * 1000,
            error="Agent crashed",
        )

        planners.plan = AsyncMock(return_value=plan_result)
        store.get_plannable = lambda _max_count: [issue]  # type: ignore[method-assign]

        await phase.plan_issues()

        mock_summarizer.summarize_and_comment.assert_awaited_once()
        assert (
            mock_summarizer.summarize_and_comment.call_args.kwargs["status"] == "failed"
        )

    @pytest.mark.asyncio
    async def test_empty_transcript_skips_summarize(
        self, config: HydraFlowConfig
    ) -> None:
        """When transcript is empty, summarize_and_comment is NOT called."""
        mock_summarizer = AsyncMock()
        mock_summarizer.summarize_and_comment = AsyncMock(return_value=True)
        phase, _state, planners, prs, store, _stop = _make_phase(
            config, summarizer=mock_summarizer
        )
        issue = TaskFactory.create(id=42)
        plan_result = PlanResult(
            issue_number=42,
            success=True,
            plan="The plan",
            summary="Done",
            transcript="",
        )

        planners.plan = AsyncMock(return_value=plan_result)
        store.get_plannable = lambda _max_count: [issue]  # type: ignore[method-assign]

        await phase.plan_issues()

        mock_summarizer.summarize_and_comment.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_already_satisfied_calls_summarize_with_success(
        self, config: HydraFlowConfig
    ) -> None:
        """When plan closes issue as already_satisfied, transcript summary is still posted."""
        mock_summarizer = AsyncMock()
        mock_summarizer.summarize_and_comment = AsyncMock(return_value=True)
        phase, _state, planners, prs, store, _stop = _make_phase(
            config, summarizer=mock_summarizer
        )
        issue = TaskFactory.create(id=42, title="Add feature")
        plan_result = PlanResult(
            issue_number=42,
            success=True,
            already_satisfied=True,
            summary="Already implemented.",
            transcript="x" * 1000,
            duration_seconds=10.0,
        )

        planners.plan = AsyncMock(return_value=plan_result)
        store.get_plannable = lambda _max_count: [issue]  # type: ignore[method-assign]

        await phase.plan_issues()

        mock_summarizer.summarize_and_comment.assert_awaited_once()
        call_kwargs = mock_summarizer.summarize_and_comment.call_args
        assert call_kwargs.kwargs["phase"] == "plan"
        assert call_kwargs.kwargs["status"] == "success"
        assert call_kwargs.kwargs["issue_title"] == "Add feature"

    @pytest.mark.asyncio
    async def test_no_summarizer_does_not_crash(self, config: HydraFlowConfig) -> None:
        """When transcript_summarizer is None, no crash occurs."""
        phase, _state, planners, prs, store, _stop = _make_phase(config)
        issue = TaskFactory.create(id=42)
        plan_result = PlanResult(
            issue_number=42,
            success=True,
            plan="The plan",
            summary="Done",
            transcript="x" * 1000,
        )

        planners.plan = AsyncMock(return_value=plan_result)
        store.get_plannable = lambda _max_count: [issue]  # type: ignore[method-assign]

        # Should not raise
        await phase.plan_issues()
