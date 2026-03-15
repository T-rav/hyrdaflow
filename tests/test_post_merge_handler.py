"""Tests for post_merge_handler.py — PostMergeHandler class."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

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
from tests.helpers import ConfigFactory


def _make_handler(
    config: HydraFlowConfig,
    *,
    ac_generator=None,
    retrospective=None,
    verification_judge=None,
    epic_checker=None,
    update_bg_worker_status=None,
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
        update_bg_worker_status=update_bg_worker_status,
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
        handler._prs.close_issue.assert_awaited_once_with(pr.issue_number)

    @pytest.mark.asyncio
    async def test_handle_approved_closes_issue_after_merge(
        self, config: HydraFlowConfig
    ) -> None:
        """After successful merge, close_issue should be called with the correct issue number."""
        handler = _make_handler(config)
        pr = PRInfoFactory.create(number=99, issue_number=55)
        issue = TaskFactory.create(id=55)
        result = ReviewResultFactory.create()

        handler._prs.merge_pr = AsyncMock(return_value=True)

        await handler.handle_approved(
            pr,
            issue,
            result,
            "diff",
            0,
            ci_gate_fn=AsyncMock(return_value=True),
            escalate_fn=AsyncMock(),
            publish_fn=AsyncMock(),
        )

        handler._prs.close_issue.assert_awaited_once_with(55)

    @pytest.mark.asyncio
    async def test_handle_approved_does_not_close_issue_on_merge_failure(
        self, config: HydraFlowConfig
    ) -> None:
        """When merge fails, close_issue should NOT be called."""
        handler = _make_handler(config)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()
        result = ReviewResultFactory.create()

        handler._prs.merge_pr = AsyncMock(return_value=False)

        await handler.handle_approved(
            pr,
            issue,
            result,
            "diff",
            0,
            ci_gate_fn=AsyncMock(return_value=True),
            escalate_fn=AsyncMock(),
            publish_fn=AsyncMock(),
        )

        handler._prs.close_issue.assert_not_awaited()

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
    async def test_handle_approved_merge_failure_conflict_sets_conflict_cause(
        self, config: HydraFlowConfig
    ) -> None:
        """When mergeability reports conflicts, escalation cause includes merge conflict."""
        handler = _make_handler(config)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()
        result = ReviewResultFactory.create()

        handler._prs.merge_pr = AsyncMock(return_value=False)
        handler._prs.get_pr_mergeable = AsyncMock(return_value=False)
        publish_fn = AsyncMock()
        escalate_fn = AsyncMock()

        await handler.handle_approved(
            pr,
            issue,
            result,
            "diff",
            0,
            ci_gate_fn=AsyncMock(return_value=True),
            escalate_fn=escalate_fn,
            publish_fn=publish_fn,
        )

        esc = escalate_fn.await_args.args[0]
        assert esc.cause == "PR merge failed on GitHub: merge conflict"
        assert "merge conflicts" in esc.comment

    @pytest.mark.asyncio
    async def test_handle_approved_merge_failure_non_conflict_sets_blocked_cause(
        self, config: HydraFlowConfig
    ) -> None:
        """When mergeability is true, escalation cause marks non-conflict merge block."""
        handler = _make_handler(config)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()
        result = ReviewResultFactory.create()

        handler._prs.merge_pr = AsyncMock(return_value=False)
        handler._prs.get_pr_mergeable = AsyncMock(return_value=True)
        publish_fn = AsyncMock()
        escalate_fn = AsyncMock()

        await handler.handle_approved(
            pr,
            issue,
            result,
            "diff",
            0,
            ci_gate_fn=AsyncMock(return_value=True),
            escalate_fn=escalate_fn,
            publish_fn=publish_fn,
        )

        esc = escalate_fn.await_args.args[0]
        assert esc.cause == "PR merge failed on GitHub: merge blocked (non-conflict)"

    @pytest.mark.asyncio
    async def test_handle_approved_merge_conflict_attempts_auto_fix_and_retries_merge(
        self, config: HydraFlowConfig
    ) -> None:
        """On merge conflict, standard review path should attempt auto-fix before HITL."""
        handler = _make_handler(config)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()
        result = ReviewResultFactory.create()

        handler._prs.merge_pr = AsyncMock(side_effect=[False, True])
        handler._prs.get_pr_mergeable = AsyncMock(return_value=False)
        publish_fn = AsyncMock()
        escalate_fn = AsyncMock()
        merge_conflict_fix_fn = AsyncMock(return_value=True)

        await handler.handle_approved(
            pr,
            issue,
            result,
            "diff",
            0,
            ci_gate_fn=AsyncMock(return_value=True),
            escalate_fn=escalate_fn,
            publish_fn=publish_fn,
            merge_conflict_fix_fn=merge_conflict_fix_fn,
        )

        merge_conflict_fix_fn.assert_awaited_once_with(pr, issue, 0)
        assert handler._prs.merge_pr.await_count == 2
        escalate_fn.assert_not_awaited()
        assert result.merged is True

    @pytest.mark.asyncio
    async def test_handle_approved_merge_conflict_fix_failure_escalates(
        self, config: HydraFlowConfig
    ) -> None:
        """If standard auto-fix fails, merge conflict should still escalate to HITL."""
        handler = _make_handler(config)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()
        result = ReviewResultFactory.create()

        handler._prs.merge_pr = AsyncMock(return_value=False)
        handler._prs.get_pr_mergeable = AsyncMock(return_value=False)
        escalate_fn = AsyncMock()
        merge_conflict_fix_fn = AsyncMock(return_value=False)

        await handler.handle_approved(
            pr,
            issue,
            result,
            "diff",
            0,
            ci_gate_fn=AsyncMock(return_value=True),
            escalate_fn=escalate_fn,
            publish_fn=AsyncMock(),
            merge_conflict_fix_fn=merge_conflict_fix_fn,
        )

        merge_conflict_fix_fn.assert_awaited_once_with(pr, issue, 0)
        esc = escalate_fn.await_args.args[0]
        assert esc.cause == "PR merge failed on GitHub: merge conflict"

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
    async def test_updates_retrospective_bg_status_after_merge(
        self, config: HydraFlowConfig
    ) -> None:
        """Retrospective runs should publish a background worker status update."""
        mock_retro = AsyncMock()
        status_cb = MagicMock()
        handler = _make_handler(
            config,
            retrospective=mock_retro,
            update_bg_worker_status=status_cb,
        )
        pr = PRInfoFactory.create(number=55, issue_number=66)
        issue = TaskFactory.create(id=66)
        result = ReviewResultFactory.create()

        handler._prs.merge_pr = AsyncMock(return_value=True)

        await handler.handle_approved(
            pr,
            issue,
            result,
            "diff",
            0,
            ci_gate_fn=AsyncMock(return_value=True),
            escalate_fn=AsyncMock(),
            publish_fn=AsyncMock(),
        )

        status_cb.assert_called_with(
            "retrospective",
            "ok",
            {"issue_number": 66, "pr_number": 55},
        )

    @pytest.mark.asyncio
    async def test_updates_retrospective_bg_status_error_when_retro_fails(
        self, config: HydraFlowConfig
    ) -> None:
        """Retrospective failure should still publish error worker status."""
        mock_retro = AsyncMock()
        mock_retro.record.side_effect = RuntimeError("retro boom")
        status_cb = MagicMock()
        handler = _make_handler(
            config,
            retrospective=mock_retro,
            update_bg_worker_status=status_cb,
        )
        pr = PRInfoFactory.create(number=55, issue_number=66)
        issue = TaskFactory.create(id=66)
        result = ReviewResultFactory.create()

        handler._prs.merge_pr = AsyncMock(return_value=True)

        await handler.handle_approved(
            pr,
            issue,
            result,
            "diff",
            0,
            ci_gate_fn=AsyncMock(return_value=True),
            escalate_fn=AsyncMock(),
            publish_fn=AsyncMock(),
        )

        status_cb.assert_called_with(
            "retrospective",
            "error",
            {"issue_number": 66, "pr_number": 55},
        )

    @pytest.mark.asyncio
    async def test_retrospective_status_callback_failure_is_swallowed(
        self, config: HydraFlowConfig, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Status callback errors must not break post-merge hooks."""
        mock_retro = AsyncMock()
        status_cb = MagicMock(side_effect=RuntimeError("status boom"))
        handler = _make_handler(
            config,
            retrospective=mock_retro,
            update_bg_worker_status=status_cb,
        )
        pr = PRInfoFactory.create(number=55, issue_number=66)
        issue = TaskFactory.create(id=66)
        result = ReviewResultFactory.create()

        handler._prs.merge_pr = AsyncMock(return_value=True)

        with caplog.at_level(logging.WARNING, logger="hydraflow.post_merge_handler"):
            await handler.handle_approved(
                pr,
                issue,
                result,
                "diff",
                0,
                ci_gate_fn=AsyncMock(return_value=True),
                escalate_fn=AsyncMock(),
                publish_fn=AsyncMock(),
            )

        assert result.merged is True
        assert any("status callback failed" in r.message for r in caplog.records)

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
        # Verification issue should use verify_label, not hitl_label.
        call_args = handler._prs.create_issue.call_args
        assert config.verify_label[0] in call_args[0][2]
        # Should record VERIFY_PENDING outcome with verification_issue_number.
        outcome = handler._state.get_outcome(issue.id)
        assert outcome is not None
        assert outcome.outcome.value == "verify_pending"
        assert outcome.verification_issue_number == 42

    @pytest.mark.asyncio
    async def test_verification_issue_uses_verify_label_not_hitl(
        self, config: HydraFlowConfig
    ) -> None:
        """Verification issues must use verify_label, not hitl_label."""
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
            verification_instructions="Open the app and check the output",
        )
        mock_judge = AsyncMock()
        mock_judge.judge = AsyncMock(return_value=verdict)
        handler = _make_handler(config, verification_judge=mock_judge)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()
        result = ReviewResultFactory.create()

        handler._prs.merge_pr = AsyncMock(return_value=True)
        handler._prs.create_issue = AsyncMock(return_value=99)
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

        # Label used should be verify_label, not hitl_label
        call_args = handler._prs.create_issue.call_args
        assert config.verify_label[0] in call_args[0][2]
        assert config.hitl_label[0] not in call_args[0][2]
        # Should NOT set hitl_origin (verify issues aren't HITL items)
        assert handler._state.get_hitl_origin(99) is None

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


class TestSafeHookFailureVisibility:
    """Tests for _safe_hook failure recording, alerting, and commenting."""

    @pytest.mark.asyncio
    async def test_safe_hook_records_failure_in_state(
        self, config: HydraFlowConfig
    ) -> None:
        """When a hook fails, failure should be recorded in state."""
        state = StateTracker(config.state_file)
        handler = PostMergeHandler(
            config=config,
            state=state,
            prs=AsyncMock(),
            event_bus=EventBus(),
            ac_generator=None,
            retrospective=None,
            verification_judge=None,
            epic_checker=None,
        )

        async def _failing_coro() -> None:
            msg = "Connection timeout"
            raise RuntimeError(msg)

        await handler._safe_hook("AC generation", _failing_coro(), 42)

        failures = state.get_hook_failures(42)
        assert len(failures) == 1
        assert failures[0].hook_name == "AC generation"
        assert "Connection timeout" in failures[0].error

    @pytest.mark.asyncio
    async def test_safe_hook_publishes_system_alert(
        self, config: HydraFlowConfig
    ) -> None:
        """When a hook fails, a SYSTEM_ALERT event should be published."""
        from events import EventType

        bus = EventBus()
        state = StateTracker(config.state_file)
        handler = PostMergeHandler(
            config=config,
            state=state,
            prs=AsyncMock(),
            event_bus=bus,
            ac_generator=None,
            retrospective=None,
            verification_judge=None,
            epic_checker=None,
        )

        async def _failing_coro() -> None:
            msg = "Test error"
            raise RuntimeError(msg)

        await handler._safe_hook("test_hook", _failing_coro(), 42)

        alerts = [e for e in bus.get_history() if e.type == EventType.SYSTEM_ALERT]
        assert len(alerts) == 1
        assert "test_hook" in alerts[0].data["message"]
        assert alerts[0].data["source"] == "post_merge_hook"

    @pytest.mark.asyncio
    async def test_safe_hook_posts_comment_on_failure(
        self, config: HydraFlowConfig
    ) -> None:
        """When a hook fails, a comment should be posted on the issue."""
        prs = AsyncMock()
        state = StateTracker(config.state_file)
        handler = PostMergeHandler(
            config=config,
            state=state,
            prs=prs,
            event_bus=EventBus(),
            ac_generator=None,
            retrospective=None,
            verification_judge=None,
            epic_checker=None,
        )

        async def _failing_coro() -> None:
            msg = "DB error"
            raise RuntimeError(msg)

        await handler._safe_hook("retrospective", _failing_coro(), 42)

        prs.post_comment.assert_awaited_once()
        comment = prs.post_comment.call_args.args[1]
        assert "retrospective" in comment
        assert "DB error" in comment


class TestMergeOutcomeRecording:
    """Tests for merge outcome recording in handle_approved."""

    @pytest.mark.asyncio
    async def test_merge_records_outcome(self, config: HydraFlowConfig) -> None:
        """Successful merge should record a MERGED outcome in state."""
        from models import IssueOutcomeType

        state = StateTracker(config.state_file)
        handler = PostMergeHandler(
            config=config,
            state=state,
            prs=AsyncMock(),
            event_bus=EventBus(),
            ac_generator=None,
            retrospective=None,
            verification_judge=None,
            epic_checker=None,
        )
        pr = PRInfoFactory.create(number=10, issue_number=42)
        issue = TaskFactory.create(id=42)
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

        outcome = state.get_outcome(42)
        assert outcome is not None
        assert outcome.outcome == IssueOutcomeType.MERGED
        assert outcome.pr_number == 10
        assert outcome.phase == "review"


# ---------------------------------------------------------------------------
# _safe_hook recovery — secondary crash protection
# ---------------------------------------------------------------------------


class TestSafeHookRecovery:
    """Tests that _safe_hook survives secondary failures in error handling."""

    @pytest.mark.asyncio
    async def test_safe_hook_record_failure_survives_secondary_crash(
        self, config: HydraFlowConfig
    ) -> None:
        """If record_hook_failure raises, _safe_hook should not propagate."""
        handler = _make_handler(config)
        handler._state.record_hook_failure = MagicMock(
            side_effect=RuntimeError("disk full")
        )

        async def failing_coro():
            raise ValueError("original error")

        result = await handler._safe_hook("test_hook", failing_coro(), 42)
        assert result is None  # Should not propagate

    @pytest.mark.asyncio
    async def test_safe_hook_bus_publish_survives_crash(
        self, config: HydraFlowConfig
    ) -> None:
        """If bus.publish raises, _safe_hook should not propagate."""
        handler = _make_handler(config)
        handler._bus.publish = AsyncMock(side_effect=RuntimeError("bus broken"))

        async def failing_coro():
            raise ValueError("original error")

        result = await handler._safe_hook("test_hook", failing_coro(), 42)
        assert result is None  # Should not propagate

    @pytest.mark.asyncio
    async def test_safe_hook_logs_original_and_secondary_errors(
        self, config: HydraFlowConfig, caplog
    ) -> None:
        """Both the original and secondary errors should be logged."""
        handler = _make_handler(config)
        handler._state.record_hook_failure = MagicMock(
            side_effect=RuntimeError("secondary crash")
        )

        async def failing_coro():
            raise ValueError("original error")

        with caplog.at_level(logging.DEBUG, logger="hydraflow.post_merge_handler"):
            await handler._safe_hook("test_hook", failing_coro(), 42)

        # Original error should be logged as WARNING
        assert any("test_hook failed" in r.message for r in caplog.records)
        # Secondary error (record_hook_failure crash) should also be logged
        assert any("Failed to record hook failure" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_safe_hook_publishes_event_even_when_record_failure_crashes(
        self, config: HydraFlowConfig
    ) -> None:
        """bus.publish should still be called even if record_hook_failure raises."""
        handler = _make_handler(config)
        handler._state.record_hook_failure = MagicMock(
            side_effect=RuntimeError("disk full")
        )
        handler._bus.publish = AsyncMock()

        async def failing_coro():
            raise ValueError("original error")

        await handler._safe_hook("test_hook", failing_coro(), 42)

        # bus.publish should still have been called despite record_hook_failure crash
        handler._bus.publish.assert_awaited_once()
        event_data = handler._bus.publish.call_args.args[0].data
        assert event_data["hook_name"] == "test_hook"
        assert event_data["issue"] == 42


# ---------------------------------------------------------------------------
# Visual gate in handle_approved
# ---------------------------------------------------------------------------


class TestVisualGateInHandleApproved:
    """Tests for visual gate integration in handle_approved."""

    @pytest.mark.asyncio
    async def test_visual_gate_disabled_skips_check(
        self, config: HydraFlowConfig
    ) -> None:
        """When visual_gate_enabled is False, merge proceeds without calling gate fn."""
        handler = _make_handler(config)
        handler._prs.merge_pr = AsyncMock(return_value=True)
        ci_gate_fn = AsyncMock(return_value=True)
        visual_gate_fn = AsyncMock(return_value=True)

        await handler.handle_approved(
            PRInfoFactory.create(),
            TaskFactory.create(),
            ReviewResultFactory.create(),
            "diff",
            0,
            ci_gate_fn=ci_gate_fn,
            escalate_fn=AsyncMock(),
            publish_fn=AsyncMock(),
            visual_gate_fn=visual_gate_fn,
        )

        # Gate disabled by default — visual_gate_fn should not be called
        visual_gate_fn.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_visual_gate_enabled_pass_allows_merge(
        self, config: HydraFlowConfig
    ) -> None:
        """When visual gate is enabled and passes, merge proceeds."""
        cfg = ConfigFactory.create(
            visual_gate_enabled=True,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        handler = _make_handler(cfg)
        handler._prs.merge_pr = AsyncMock(return_value=True)
        result = ReviewResultFactory.create()
        visual_gate_fn = AsyncMock(return_value=True)

        await handler.handle_approved(
            PRInfoFactory.create(),
            TaskFactory.create(),
            result,
            "diff",
            0,
            ci_gate_fn=AsyncMock(return_value=True),
            escalate_fn=AsyncMock(),
            publish_fn=AsyncMock(),
            visual_gate_fn=visual_gate_fn,
        )

        visual_gate_fn.assert_awaited_once()
        assert result.merged is True

    @pytest.mark.asyncio
    async def test_visual_gate_enabled_fail_blocks_merge(
        self, config: HydraFlowConfig
    ) -> None:
        """When visual gate is enabled and fails, merge is blocked."""
        cfg = ConfigFactory.create(
            visual_gate_enabled=True,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        handler = _make_handler(cfg)
        handler._prs.merge_pr = AsyncMock(return_value=True)
        result = ReviewResultFactory.create()
        visual_gate_fn = AsyncMock(return_value=False)

        await handler.handle_approved(
            PRInfoFactory.create(),
            TaskFactory.create(),
            result,
            "diff",
            0,
            ci_gate_fn=AsyncMock(return_value=True),
            escalate_fn=AsyncMock(),
            publish_fn=AsyncMock(),
            visual_gate_fn=visual_gate_fn,
        )

        visual_gate_fn.assert_awaited_once()
        assert result.merged is False
        handler._prs.merge_pr.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_visual_gate_enabled_no_fn_blocks_merge(
        self, config: HydraFlowConfig
    ) -> None:
        """When visual gate enabled but no fn provided, merge is blocked."""
        cfg = ConfigFactory.create(
            visual_gate_enabled=True,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        handler = _make_handler(cfg)
        handler._prs.merge_pr = AsyncMock(return_value=True)
        result = ReviewResultFactory.create()

        await handler.handle_approved(
            PRInfoFactory.create(),
            TaskFactory.create(),
            result,
            "diff",
            0,
            ci_gate_fn=AsyncMock(return_value=True),
            escalate_fn=AsyncMock(),
            publish_fn=AsyncMock(),
            # No visual_gate_fn provided
        )

        assert result.merged is False
        handler._prs.merge_pr.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_visual_gate_enabled_no_fn_emits_audit_event(
        self, config: HydraFlowConfig
    ) -> None:
        """When visual gate enabled but no fn provided, an audit event is emitted."""
        cfg = ConfigFactory.create(
            visual_gate_enabled=True,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        handler = _make_handler(cfg)
        handler._prs.merge_pr = AsyncMock(return_value=True)
        handler._bus.publish = AsyncMock()
        result = ReviewResultFactory.create()
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        await handler.handle_approved(
            pr,
            issue,
            result,
            "diff",
            0,
            ci_gate_fn=AsyncMock(return_value=True),
            escalate_fn=AsyncMock(),
            publish_fn=AsyncMock(),
            # No visual_gate_fn provided
        )

        # Merge is blocked when no visual_gate_fn is provided
        assert result.merged is False
        handler._prs.merge_pr.assert_not_awaited()
        # Verify an audit event was published for the blocked gate
        published_events = [
            call.args[0] for call in handler._bus.publish.call_args_list
        ]
        gate_events = [
            e for e in published_events if e.data.get("verdict") == "blocked"
        ]
        assert len(gate_events) == 1, "Expected one VISUAL_GATE blocked audit event"
        assert gate_events[0].data["pr"] == pr.number
        assert gate_events[0].data["issue"] == issue.id


# ---------------------------------------------------------------------------
# Narrowed exception handling — programming errors propagate
# ---------------------------------------------------------------------------


class TestNarrowedExceptionHandling:
    """Verify that programming errors (TypeError, AttributeError) propagate
    instead of being silently swallowed after narrowing except clauses."""

    @pytest.mark.asyncio
    async def test_safe_hook_propagates_type_error(
        self, config: HydraFlowConfig
    ) -> None:
        """TypeError in a hook coroutine must propagate through _safe_hook."""
        handler = _make_handler(config)

        async def _bad_coro() -> str:
            raise TypeError("unexpected None argument")

        with pytest.raises(TypeError, match="unexpected None argument"):
            await handler._safe_hook("test hook", _bad_coro(), issue_number=1)

    @pytest.mark.asyncio
    async def test_safe_hook_propagates_attribute_error(
        self, config: HydraFlowConfig
    ) -> None:
        """AttributeError in a hook coroutine must propagate through _safe_hook."""
        handler = _make_handler(config)

        async def _bad_coro() -> str:
            raise AttributeError("obj has no attribute 'foo'")

        with pytest.raises(AttributeError, match="obj has no attribute"):
            await handler._safe_hook("test hook", _bad_coro(), issue_number=1)

    @pytest.mark.asyncio
    async def test_safe_hook_still_catches_runtime_error(
        self, config: HydraFlowConfig
    ) -> None:
        """RuntimeError should still be caught and return None."""
        handler = _make_handler(config)

        async def _fail() -> str:
            raise RuntimeError("subprocess failed")

        result = await handler._safe_hook("test hook", _fail(), issue_number=1)
        assert result is None

    @pytest.mark.asyncio
    async def test_safe_hook_still_catches_os_error(
        self, config: HydraFlowConfig
    ) -> None:
        """OSError should still be caught and return None."""
        handler = _make_handler(config)

        async def _fail() -> str:
            raise OSError("disk full")

        result = await handler._safe_hook("test hook", _fail(), issue_number=1)
        assert result is None

    @pytest.mark.asyncio
    async def test_safe_hook_still_catches_value_error(
        self, config: HydraFlowConfig
    ) -> None:
        """ValueError (including json.JSONDecodeError) should still be caught."""
        handler = _make_handler(config)

        async def _fail() -> str:
            raise ValueError("invalid JSON")

        result = await handler._safe_hook("test hook", _fail(), issue_number=1)
        assert result is None

    @pytest.mark.asyncio
    async def test_notify_epic_approval_propagates_type_error(
        self, config: HydraFlowConfig
    ) -> None:
        """TypeError in epic approval notification must propagate."""
        handler = _make_handler(config)
        mock_epic_manager = AsyncMock()
        mock_epic_manager.find_parent_epics = MagicMock(return_value=[100])
        mock_epic_manager.on_child_approved = AsyncMock(
            side_effect=TypeError("bad arg")
        )
        handler._epic_manager = mock_epic_manager

        with pytest.raises(TypeError, match="bad arg"):
            await handler._notify_epic_approval(42)

    @pytest.mark.asyncio
    async def test_notify_epic_approval_catches_runtime_error(
        self, config: HydraFlowConfig
    ) -> None:
        """RuntimeError in epic approval notification should be caught."""
        handler = _make_handler(config)
        mock_epic_manager = AsyncMock()
        mock_epic_manager.find_parent_epics = MagicMock(return_value=[100])
        mock_epic_manager.on_child_approved = AsyncMock(
            side_effect=RuntimeError("API down")
        )
        handler._epic_manager = mock_epic_manager

        # Should not raise — RuntimeError is caught
        await handler._notify_epic_approval(42)
        mock_epic_manager.on_child_approved.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_notify_epic_approval_catches_os_error(
        self, config: HydraFlowConfig
    ) -> None:
        """OSError in epic approval notification should be caught."""
        handler = _make_handler(config)
        mock_epic_manager = AsyncMock()
        mock_epic_manager.find_parent_epics = MagicMock(return_value=[100])
        mock_epic_manager.on_child_approved = AsyncMock(
            side_effect=OSError("network unreachable")
        )
        handler._epic_manager = mock_epic_manager

        # Should not raise — OSError is caught
        await handler._notify_epic_approval(42)
        mock_epic_manager.on_child_approved.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_post_inference_comment_propagates_type_error(
        self, config: HydraFlowConfig
    ) -> None:
        """TypeError in post_comment during inference totals must propagate."""
        handler = _make_handler(config)
        handler._prompt_telemetry.get_pr_totals = lambda _pr: {
            "inference_calls": 1,
            "total_tokens": 100,
            "total_est_tokens": 100,
            "actual_usage_calls": 0,
        }
        handler._prs.post_comment = AsyncMock(
            side_effect=TypeError("bad argument type")
        )
        pr = PRInfoFactory.create(number=10, issue_number=5)
        issue = TaskFactory.create(id=5)

        with pytest.raises(TypeError, match="bad argument type"):
            await handler._post_inference_totals_comment(pr, issue)

    @pytest.mark.asyncio
    async def test_post_inference_comment_catches_runtime_error(
        self, config: HydraFlowConfig
    ) -> None:
        """RuntimeError in post_comment during inference totals should be caught."""
        handler = _make_handler(config)
        handler._prompt_telemetry.get_pr_totals = lambda _pr: {
            "inference_calls": 1,
            "total_tokens": 100,
            "total_est_tokens": 100,
            "actual_usage_calls": 0,
        }
        handler._prs.post_comment = AsyncMock(side_effect=RuntimeError("API error"))
        pr = PRInfoFactory.create(number=10, issue_number=5)
        issue = TaskFactory.create(id=5)

        # Should not raise — RuntimeError is caught
        await handler._post_inference_totals_comment(pr, issue)
        handler._prs.post_comment.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_post_inference_comment_catches_value_error(
        self, config: HydraFlowConfig
    ) -> None:
        """ValueError (e.g. json.JSONDecodeError) in post_comment should be caught."""
        handler = _make_handler(config)
        handler._prompt_telemetry.get_pr_totals = lambda _pr: {
            "inference_calls": 1,
            "total_tokens": 100,
            "total_est_tokens": 100,
            "actual_usage_calls": 0,
        }
        handler._prs.post_comment = AsyncMock(side_effect=ValueError("invalid JSON"))
        pr = PRInfoFactory.create(number=10, issue_number=5)
        issue = TaskFactory.create(id=5)

        # Should not raise — ValueError is caught
        await handler._post_inference_totals_comment(pr, issue)
        handler._prs.post_comment.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_retrospective_propagates_type_error(
        self, config: HydraFlowConfig
    ) -> None:
        """TypeError in retrospective.record() must propagate through post-merge hooks."""
        mock_retro = AsyncMock()
        mock_retro.record.side_effect = TypeError("missing required arg")
        handler = _make_handler(config, retrospective=mock_retro)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()
        result = ReviewResultFactory.create()

        handler._prs.merge_pr = AsyncMock(return_value=True)

        with pytest.raises(TypeError, match="missing required arg"):
            await handler.handle_approved(
                pr,
                issue,
                result,
                "diff",
                0,
                ci_gate_fn=AsyncMock(return_value=True),
                escalate_fn=AsyncMock(),
                publish_fn=AsyncMock(),
            )

    @pytest.mark.asyncio
    async def test_status_callback_propagates_attribute_error(
        self, config: HydraFlowConfig
    ) -> None:
        """AttributeError in status callback must propagate."""
        mock_retro = AsyncMock()
        status_cb = MagicMock(side_effect=AttributeError("no attr"))
        handler = _make_handler(
            config,
            retrospective=mock_retro,
            update_bg_worker_status=status_cb,
        )
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()
        result = ReviewResultFactory.create()

        handler._prs.merge_pr = AsyncMock(return_value=True)

        with pytest.raises(AttributeError, match="no attr"):
            await handler.handle_approved(
                pr,
                issue,
                result,
                "diff",
                0,
                ci_gate_fn=AsyncMock(return_value=True),
                escalate_fn=AsyncMock(),
                publish_fn=AsyncMock(),
            )

    @pytest.mark.asyncio
    async def test_safe_hook_inner_post_comment_catches_os_error(
        self, config: HydraFlowConfig
    ) -> None:
        """OSError from post_comment inside _safe_hook must not propagate."""
        handler = _make_handler(config)
        handler._prs.post_comment = AsyncMock(side_effect=OSError("broken pipe"))

        async def _fail() -> str:
            raise RuntimeError("hook failure")

        # Should not raise even though post_comment raises OSError
        result = await handler._safe_hook("test hook", _fail(), issue_number=1)
        assert result is None

    @pytest.mark.asyncio
    async def test_post_inference_comment_catches_os_error(
        self, config: HydraFlowConfig
    ) -> None:
        """OSError in post_comment during inference totals should be caught."""
        handler = _make_handler(config)
        handler._prompt_telemetry.get_pr_totals = lambda _pr: {
            "inference_calls": 1,
            "total_tokens": 100,
            "total_est_tokens": 100,
            "actual_usage_calls": 0,
        }
        handler._prs.post_comment = AsyncMock(side_effect=OSError("connection reset"))
        pr = PRInfoFactory.create(number=10, issue_number=5)
        issue = TaskFactory.create(id=5)

        # Should not raise — OSError is now caught
        await handler._post_inference_totals_comment(pr, issue)
        handler._prs.post_comment.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_safe_hook_chain_isolation(self, config: HydraFlowConfig) -> None:
        """When record_hook_failure fails, bus.publish and post_comment still run."""
        state_mock = MagicMock()
        state_mock.record_hook_failure = MagicMock(side_effect=RuntimeError("db down"))
        bus_mock = AsyncMock()
        prs_mock = AsyncMock()
        handler = PostMergeHandler(
            config=config,
            state=state_mock,
            prs=prs_mock,
            event_bus=bus_mock,
            ac_generator=None,
            retrospective=None,
            verification_judge=None,
            epic_checker=None,
        )

        async def _fail() -> str:
            raise RuntimeError("hook failed")

        result = await handler._safe_hook("test hook", _fail(), issue_number=1)
        assert result is None
        state_mock.record_hook_failure.assert_called_once()
        bus_mock.publish.assert_awaited_once()
        prs_mock.post_comment.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_safe_hook_bus_publish_failure_still_calls_post_comment(
        self, config: HydraFlowConfig
    ) -> None:
        """When bus.publish fails, post_comment must still be called (full chain)."""
        state_mock = MagicMock()
        bus_mock = AsyncMock()
        bus_mock.publish = AsyncMock(side_effect=RuntimeError("bus unavailable"))
        prs_mock = AsyncMock()
        handler = PostMergeHandler(
            config=config,
            state=state_mock,
            prs=prs_mock,
            event_bus=bus_mock,
            ac_generator=None,
            retrospective=None,
            verification_judge=None,
            epic_checker=None,
        )

        async def _fail() -> str:
            raise RuntimeError("hook failed")

        result = await handler._safe_hook("test hook", _fail(), issue_number=1)
        assert result is None
        bus_mock.publish.assert_awaited_once()
        prs_mock.post_comment.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_retrospective_runtime_error_is_swallowed(
        self, config: HydraFlowConfig, caplog: pytest.LogCaptureFixture
    ) -> None:
        """RuntimeError from retrospective.record must be caught and logged."""
        mock_retro = AsyncMock()
        mock_retro.record = AsyncMock(side_effect=RuntimeError("db unavailable"))
        handler = _make_handler(config, retrospective=mock_retro)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()
        result = ReviewResultFactory.create()

        handler._prs.merge_pr = AsyncMock(return_value=True)

        with caplog.at_level(logging.WARNING, logger="hydraflow.post_merge_handler"):
            await handler.handle_approved(
                pr,
                issue,
                result,
                "diff",
                0,
                ci_gate_fn=AsyncMock(return_value=True),
                escalate_fn=AsyncMock(),
                publish_fn=AsyncMock(),
            )
        mock_retro.record.assert_awaited_once()
        assert any("retrospective failed" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_notify_epic_approval_catches_value_error(
        self, config: HydraFlowConfig
    ) -> None:
        """ValueError in epic approval notification should be caught."""
        handler = _make_handler(config)
        mock_epic_manager = AsyncMock()
        mock_epic_manager.find_parent_epics = MagicMock(return_value=[100])
        mock_epic_manager.on_child_approved = AsyncMock(
            side_effect=ValueError("malformed response")
        )
        handler._epic_manager = mock_epic_manager

        # Should not raise — ValueError is now caught
        await handler._notify_epic_approval(42)
        mock_epic_manager.on_child_approved.assert_awaited_once()
