"""Tests for post_merge_handler.py — PostMergeHandler class."""

from __future__ import annotations

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
from tests.conftest import IssueFactory, PRInfoFactory, ReviewResultFactory


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
        issue = IssueFactory.create()
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
    async def test_handle_approved_escalates_on_merge_failure(
        self, config: HydraFlowConfig
    ) -> None:
        """When merge fails, should escalate to HITL."""
        handler = _make_handler(config)
        pr = PRInfoFactory.create()
        issue = IssueFactory.create()
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
        issue = IssueFactory.create()
        pr = PRInfoFactory.create()

        result = handler._get_judge_result(issue, pr, None)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_judge_result_converts_verdict(
        self, config: HydraFlowConfig
    ) -> None:
        """Should convert JudgeVerdict into JudgeResult."""
        handler = _make_handler(config)
        issue = IssueFactory.create()
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
        issue = IssueFactory.create()
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
    async def test_hook_failure_does_not_block_others(
        self, config: HydraFlowConfig
    ) -> None:
        """If AC generation fails, retrospective should still be called."""
        mock_ac = AsyncMock()
        mock_ac.generate = AsyncMock(side_effect=RuntimeError("AC failed"))
        mock_retro = AsyncMock()
        handler = _make_handler(config, ac_generator=mock_ac, retrospective=mock_retro)
        pr = PRInfoFactory.create()
        issue = IssueFactory.create()
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
