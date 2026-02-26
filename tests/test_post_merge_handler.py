"""Tests for post_merge_handler.py — PostMergeHandler class."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import HydraFlowConfig

from events import EventBus
from models import (
    CriterionResult,
    CriterionVerdict,
    JudgeVerdict,
)
from post_merge_handler import PostMergeHandler
from state import StateTracker
from tests.conftest import PRInfoFactory, ReviewResultFactory, TaskFactory


def _make_handler(
    config: HydraFlowConfig,
    *,
    ac_generator=None,
    retrospective=None,
    verification_judge=None,
    epic_checker=None,
) -> PostMergeHandler:
    """Build a PostMergeHandler with standard mock dependencies."""
    state = StateTracker(config.state_file)
    return PostMergeHandler(
        config=config,
        state=state,
        prs=AsyncMock(),
        event_bus=EventBus(),
        ac_generator=ac_generator,
        retrospective=retrospective,
        verification_judge=verification_judge,
        epic_checker=epic_checker,
    )


class TestPostMergeHandler:
    """Tests for the PostMergeHandler class."""

    @pytest.mark.asyncio
    async def test_handle_approved_merges_and_labels(
        self, config: HydraFlowConfig
    ) -> None:
        """On successful merge, should mark issue and swap labels."""
        handler = _make_handler(config)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()
        result = ReviewResultFactory.create()

        handler._prs.merge_pr = AsyncMock(return_value=True)
        publish_fn = AsyncMock()
        escalate_fn = AsyncMock()
        ci_gate_fn = AsyncMock(return_value=True)

        await handler.handle_approved(
            pr,
            issue,
            result,
            "diff",
            0,
            ci_gate_fn=ci_gate_fn,
            escalate_fn=escalate_fn,
            publish_fn=publish_fn,
        )

        assert result.merged is True
        handler._prs.swap_pipeline_labels.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_approved_posts_inference_totals_comment(
        self, config: HydraFlowConfig
    ) -> None:
        """On successful merge, should comment inference usage on the issue."""
        handler = _make_handler(config)
        pr = PRInfoFactory.create(number=123, issue_number=42)
        issue = TaskFactory.create(id=42)
        result = ReviewResultFactory.create()

        handler._prompt_telemetry.get_pr_totals = lambda _pr: {
            "inference_calls": 5,
            "total_tokens": 1200,
            "total_est_tokens": 1300,
            "actual_usage_calls": 5,
        }
        handler._prs.merge_pr = AsyncMock(return_value=True)
        publish_fn = AsyncMock()
        escalate_fn = AsyncMock()
        ci_gate_fn = AsyncMock(return_value=True)

        await handler.handle_approved(
            pr,
            issue,
            result,
            "diff",
            0,
            ci_gate_fn=ci_gate_fn,
            escalate_fn=escalate_fn,
            publish_fn=publish_fn,
        )

        handler._prs.post_comment.assert_awaited()
        args = handler._prs.post_comment.await_args.args
        assert args[0] == 42
        assert "Inference Usage" in args[1]
        assert "Total tokens: 1,200" in args[1]

    @pytest.mark.asyncio
    async def test_handle_approved_escalates_on_merge_failure(
        self, config: HydraFlowConfig
    ) -> None:
        """When merge fails, should escalate to HITL."""
        handler = _make_handler(config)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()
        result = ReviewResultFactory.create()

        handler._prs.merge_pr = AsyncMock(return_value=False)
        publish_fn = AsyncMock()
        escalate_fn = AsyncMock()
        ci_gate_fn = AsyncMock(return_value=True)

        await handler.handle_approved(
            pr,
            issue,
            result,
            "diff",
            0,
            ci_gate_fn=ci_gate_fn,
            escalate_fn=escalate_fn,
            publish_fn=publish_fn,
        )

        escalate_fn.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_judge_result_none(self, config: HydraFlowConfig) -> None:
        """When verdict is None, should return None."""
        handler = _make_handler(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        result = handler._get_judge_result(issue, pr, None)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_judge_result_converts_verdict(
        self, config: HydraFlowConfig
    ) -> None:
        """Should convert JudgeVerdict into JudgeResult."""
        handler = _make_handler(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()
        verdict = JudgeVerdict(
            issue_number=42,
            criteria_results=[
                CriterionResult(
                    criterion="AC-1",
                    verdict=CriterionVerdict.PASS,
                    reasoning="OK",
                ),
            ],
            summary="1/1 passed",
            verification_instructions="Check it",
        )

        result = handler._get_judge_result(issue, pr, verdict)

        assert result is not None
        assert len(result.criteria) == 1
        assert result.criteria[0].passed is True
        assert result.verification_instructions == "Check it"

    @pytest.mark.asyncio
    async def test_retrospective_called_after_merge(
        self, config: HydraFlowConfig
    ) -> None:
        """retrospective.record() should be called after successful merge."""
        mock_retro = AsyncMock()
        handler = _make_handler(config, retrospective=mock_retro)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()
        result = ReviewResultFactory.create()

        handler._prs.merge_pr = AsyncMock(return_value=True)
        publish_fn = AsyncMock()
        escalate_fn = AsyncMock()
        ci_gate_fn = AsyncMock(return_value=True)

        await handler.handle_approved(
            pr,
            issue,
            result,
            "diff",
            0,
            ci_gate_fn=ci_gate_fn,
            escalate_fn=escalate_fn,
            publish_fn=publish_fn,
        )

        mock_retro.record.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_verification_issue_created_when_judge_returns_verdict(
        self, config: HydraFlowConfig
    ) -> None:
        """create_issue should be called when the judge returns a non-None verdict."""
        verdict = JudgeVerdict(
            issue_number=1,
            criteria_results=[
                CriterionResult(
                    criterion="AC-1",
                    verdict=CriterionVerdict.PASS,
                    reasoning="Looks good",
                ),
            ],
            summary="1/1 passed",
            verification_instructions="Open the app in browser and click Save button",
        )
        mock_judge = AsyncMock()
        mock_judge.judge = AsyncMock(return_value=verdict)
        handler = _make_handler(config, verification_judge=mock_judge)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()
        result = ReviewResultFactory.create()

        handler._prs.merge_pr = AsyncMock(return_value=True)
        handler._prs.create_issue = AsyncMock(return_value=42)
        publish_fn = AsyncMock()
        escalate_fn = AsyncMock()
        ci_gate_fn = AsyncMock(return_value=True)

        await handler.handle_approved(
            pr,
            issue,
            result,
            "+++ b/src/ui/App.tsx\n@@\n+<button>Save</button>",
            0,
            ci_gate_fn=ci_gate_fn,
            escalate_fn=escalate_fn,
            publish_fn=publish_fn,
        )

        handler._prs.create_issue.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_verification_issue_skipped_for_refactor_and_test_only_work(
        self, config: HydraFlowConfig
    ) -> None:
        """Refactor/test-only changes should not generate Verify issues."""
        verdict = JudgeVerdict(
            issue_number=1,
            criteria_results=[
                CriterionResult(
                    criterion="AC-1",
                    verdict=CriterionVerdict.PASS,
                    reasoning="Looks good",
                ),
            ],
            summary="1/1 passed",
            verification_instructions="Run unit tests and lint",
        )
        mock_judge = AsyncMock()
        mock_judge.judge = AsyncMock(return_value=verdict)
        handler = _make_handler(config, verification_judge=mock_judge)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create(
            title="Refactor test helpers",
            body="Cleanup test fixtures and typing in unit tests.",
        )
        result = ReviewResultFactory.create()

        handler._prs.merge_pr = AsyncMock(return_value=True)
        handler._prs.create_issue = AsyncMock(return_value=42)
        publish_fn = AsyncMock()
        escalate_fn = AsyncMock()
        ci_gate_fn = AsyncMock(return_value=True)

        await handler.handle_approved(
            pr,
            issue,
            result,
            "+++ b/tests/test_helpers.py\n@@\n+assert value == expected",
            0,
            ci_gate_fn=ci_gate_fn,
            escalate_fn=escalate_fn,
            publish_fn=publish_fn,
        )

        handler._prs.create_issue.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_epic_runs_when_verification_issue_creation_fails(
        self, config: HydraFlowConfig
    ) -> None:
        """Epic checker should still run when _create_verification_issue raises."""
        verdict = JudgeVerdict(
            issue_number=1,
            criteria_results=[
                CriterionResult(
                    criterion="AC-1",
                    verdict=CriterionVerdict.PASS,
                    reasoning="OK",
                ),
            ],
            summary="1/1 passed",
            verification_instructions="Check it",
        )
        mock_judge = AsyncMock()
        mock_judge.judge = AsyncMock(return_value=verdict)
        mock_epic = AsyncMock()
        handler = _make_handler(
            config,
            verification_judge=mock_judge,
            epic_checker=mock_epic,
        )
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()
        result = ReviewResultFactory.create()

        handler._prs.merge_pr = AsyncMock(return_value=True)
        handler._prs.create_issue = AsyncMock(side_effect=RuntimeError("GH API down"))
        publish_fn = AsyncMock()
        escalate_fn = AsyncMock()
        ci_gate_fn = AsyncMock(return_value=True)

        await handler.handle_approved(
            pr,
            issue,
            result,
            "diff",
            0,
            ci_gate_fn=ci_gate_fn,
            escalate_fn=escalate_fn,
            publish_fn=publish_fn,
        )

        mock_epic.check_and_close_epics.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_safe_hook_returns_result_on_success(
        self, config: HydraFlowConfig
    ) -> None:
        """_safe_hook should return the coroutine's result on success."""
        handler = _make_handler(config)

        async def _success() -> str:
            return "ok"

        result = await handler._safe_hook("test hook", _success(), issue_number=1)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_safe_hook_returns_none_on_failure(
        self, config: HydraFlowConfig
    ) -> None:
        """_safe_hook should return None when the coroutine raises."""
        handler = _make_handler(config)

        async def _fail() -> str:
            msg = "boom"
            raise RuntimeError(msg)

        result = await handler._safe_hook("test hook", _fail(), issue_number=1)
        assert result is None

    @pytest.mark.asyncio
    async def test_safe_hook_logs_warning_on_failure(
        self, config: HydraFlowConfig, caplog: pytest.LogCaptureFixture
    ) -> None:
        """_safe_hook should log a warning with hook name and issue number."""
        handler = _make_handler(config)

        async def _fail() -> str:
            msg = "boom"
            raise RuntimeError(msg)

        with caplog.at_level(logging.WARNING, logger="hydraflow.post_merge_handler"):
            await handler._safe_hook("AC generation", _fail(), issue_number=42)

        matching = [
            rec
            for rec in caplog.records
            if "AC generation failed for issue #42" in rec.message
        ]
        assert matching, "Expected warning log for hook failure"
        assert matching[0].exc_info is not None, "Expected exc_info to be attached"

    @pytest.mark.asyncio
    async def test_all_hooks_called_when_all_present(
        self, config: HydraFlowConfig
    ) -> None:
        """AC, retrospective, judge, and epic hooks should all run after a successful merge.

        Verification-issue creation is conditional on a non-None judge verdict
        and is covered by test_verification_issue_created_when_judge_returns_verdict.
        """
        mock_ac = AsyncMock()
        mock_retro = AsyncMock()
        mock_judge = AsyncMock()
        mock_judge.judge = AsyncMock(return_value=None)
        mock_epic = AsyncMock()
        handler = _make_handler(
            config,
            ac_generator=mock_ac,
            retrospective=mock_retro,
            verification_judge=mock_judge,
            epic_checker=mock_epic,
        )
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()
        result = ReviewResultFactory.create()

        handler._prs.merge_pr = AsyncMock(return_value=True)
        publish_fn = AsyncMock()
        escalate_fn = AsyncMock()
        ci_gate_fn = AsyncMock(return_value=True)

        await handler.handle_approved(
            pr,
            issue,
            result,
            "diff",
            0,
            ci_gate_fn=ci_gate_fn,
            escalate_fn=escalate_fn,
            publish_fn=publish_fn,
        )

        mock_ac.generate.assert_awaited_once()
        mock_retro.record.assert_awaited_once()
        mock_judge.judge.assert_awaited_once()
        mock_epic.check_and_close_epics.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_later_hooks_run_when_earlier_hook_fails(
        self, config: HydraFlowConfig
    ) -> None:
        """Epic checker should still run when verification judge fails."""
        mock_judge = AsyncMock()
        mock_judge.judge = AsyncMock(side_effect=RuntimeError("judge broke"))
        mock_epic = AsyncMock()
        handler = _make_handler(
            config,
            verification_judge=mock_judge,
            epic_checker=mock_epic,
        )
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()
        result = ReviewResultFactory.create()

        handler._prs.merge_pr = AsyncMock(return_value=True)
        publish_fn = AsyncMock()
        escalate_fn = AsyncMock()
        ci_gate_fn = AsyncMock(return_value=True)

        await handler.handle_approved(
            pr,
            issue,
            result,
            "diff",
            0,
            ci_gate_fn=ci_gate_fn,
            escalate_fn=escalate_fn,
            publish_fn=publish_fn,
        )

        mock_epic.check_and_close_epics.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_hook_failure_does_not_block_others(
        self, config: HydraFlowConfig
    ) -> None:
        """If AC generation fails, retrospective should still be called."""
        mock_ac = AsyncMock()
        mock_ac.generate = AsyncMock(side_effect=RuntimeError("AC failed"))
        mock_retro = AsyncMock()
        handler = _make_handler(config, ac_generator=mock_ac, retrospective=mock_retro)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()
        result = ReviewResultFactory.create()

        handler._prs.merge_pr = AsyncMock(return_value=True)
        publish_fn = AsyncMock()
        escalate_fn = AsyncMock()
        ci_gate_fn = AsyncMock(return_value=True)

        await handler.handle_approved(
            pr,
            issue,
            result,
            "diff",
            0,
            ci_gate_fn=ci_gate_fn,
            escalate_fn=escalate_fn,
            publish_fn=publish_fn,
        )

        mock_retro.record.assert_awaited_once()
