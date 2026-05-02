"""Tests for ReviewPhase transcript/memory post-run hooks."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

if TYPE_CHECKING:
    from config import HydraFlowConfig
from events import EventBus
from review_phase import ReviewPhase
from state import StateTracker
from tests.conftest import ReviewResultFactory
from tests.helpers import make_review_result


def _build_phase(config: HydraFlowConfig) -> ReviewPhase:
    """Build a ReviewPhase with minimal mocks for hook testing."""
    summarizer = MagicMock()
    summarizer.summarize_and_comment = AsyncMock()
    phase = ReviewPhase(
        config=config,
        state=StateTracker(config.state_file),
        workspaces=MagicMock(),
        reviewers=MagicMock(),
        prs=MagicMock(),
        stop_event=asyncio.Event(),
        store=MagicMock(),
        conflict_resolver=MagicMock(),
        post_merge=MagicMock(),
        event_bus=EventBus(),
        transcript_summarizer=summarizer,
    )
    return phase


class TestPostReviewTranscriptHooks:
    @pytest.mark.asyncio
    async def test_calls_hooks_for_transcripts(self, config: HydraFlowConfig) -> None:
        """Review results with transcripts trigger memory + summarize."""
        phase = _build_phase(config)
        results = [
            ReviewResultFactory.create(
                pr_number=10,
                issue_number=1,
                transcript="reviewed code",
                merged=False,
                ci_passed=True,
                duration_seconds=30.0,
            ),
        ]

        with patch("phase_utils.file_memory_suggestion", new_callable=AsyncMock):
            await phase.post_review_transcript_hooks(results)

        phase._summarizer.summarize_and_comment.assert_awaited_once()
        call_kwargs = phase._summarizer.summarize_and_comment.call_args.kwargs
        assert call_kwargs["phase"] == "review"
        assert call_kwargs["status"] == "completed"

    @pytest.mark.asyncio
    async def test_skips_hooks_for_empty_transcript(
        self, config: HydraFlowConfig
    ) -> None:
        phase = _build_phase(config)
        results = [
            ReviewResultFactory.create(
                pr_number=10,
                issue_number=1,
                transcript="",
                merged=False,
                duration_seconds=0.0,
            ),
        ]

        with patch("phase_utils.file_memory_suggestion", new_callable=AsyncMock):
            await phase.post_review_transcript_hooks(results)

        phase._summarizer.summarize_and_comment.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_status_failed_on_ci_failure(self, config: HydraFlowConfig) -> None:
        phase = _build_phase(config)
        results = [
            ReviewResultFactory.create(
                pr_number=10,
                issue_number=1,
                transcript="CI failed",
                merged=False,
                ci_passed=False,
                duration_seconds=10.0,
            ),
        ]

        with patch("phase_utils.file_memory_suggestion", new_callable=AsyncMock):
            await phase.post_review_transcript_hooks(results)

        call_kwargs = phase._summarizer.summarize_and_comment.call_args.kwargs
        assert call_kwargs["status"] == "failed"

    @pytest.mark.asyncio
    async def test_status_success_on_merge(self, config: HydraFlowConfig) -> None:
        phase = _build_phase(config)
        results = [
            ReviewResultFactory.create(
                pr_number=10,
                issue_number=1,
                transcript="merged successfully",
                merged=True,
                duration_seconds=15.0,
            ),
        ]

        with patch("phase_utils.file_memory_suggestion", new_callable=AsyncMock):
            await phase.post_review_transcript_hooks(results)

        call_kwargs = phase._summarizer.summarize_and_comment.call_args.kwargs
        assert call_kwargs["status"] == "success"

    @pytest.mark.asyncio
    async def test_skips_summarize_when_issue_number_zero(
        self, config: HydraFlowConfig
    ) -> None:
        phase = _build_phase(config)
        results = [
            ReviewResultFactory.create(
                pr_number=101,
                issue_number=0,
                transcript="some transcript",
                merged=False,
                duration_seconds=5.0,
            ),
        ]

        with patch(
            "phase_utils.file_memory_suggestion", new_callable=AsyncMock
        ) as mock_mem:
            await phase.post_review_transcript_hooks(results)
            mock_mem.assert_awaited_once()
        phase._summarizer.summarize_and_comment.assert_not_awaited()


class TestPostReviewTranscript:
    @pytest.mark.asyncio
    async def test_memory_suggestion_failure_does_not_block_summarize(
        self, config: HydraFlowConfig
    ) -> None:
        phase = _build_phase(config)
        result = make_review_result(
            pr_number=10, issue_number=1, transcript="transcript"
        )

        with patch(
            "phase_utils.file_memory_suggestion",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            await phase._post_review_transcript(result, status="completed")
        phase._summarizer.summarize_and_comment.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_summarize_failure_does_not_propagate(
        self, config: HydraFlowConfig
    ) -> None:
        phase = _build_phase(config)
        phase._summarizer.summarize_and_comment = AsyncMock(
            side_effect=RuntimeError("summarize failed")
        )
        result = make_review_result(
            pr_number=10, issue_number=99, transcript="transcript"
        )

        with patch("phase_utils.file_memory_suggestion", new_callable=AsyncMock):
            # Should not raise
            await phase._post_review_transcript(result, status="completed")
        phase._summarizer.summarize_and_comment.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_passes_correct_args_to_memory_suggestion(
        self, config: HydraFlowConfig
    ) -> None:
        phase = _build_phase(config)
        result = make_review_result(pr_number=50, issue_number=7, transcript="tx")

        with patch(
            "phase_utils.file_memory_suggestion", new_callable=AsyncMock
        ) as mock_mem:
            await phase._post_review_transcript(result, status="completed")
            mock_mem.assert_awaited_once_with("tx", "reviewer", "PR #50", ANY)

    @pytest.mark.asyncio
    async def test_passes_correct_args_to_summarize(
        self, config: HydraFlowConfig
    ) -> None:
        phase = _build_phase(config)
        result = ReviewResultFactory.create(
            pr_number=50, issue_number=7, transcript="tx", duration_seconds=3.5
        )

        with patch("phase_utils.file_memory_suggestion", new_callable=AsyncMock):
            await phase._post_review_transcript(result, status="failed")
        call_kwargs = phase._summarizer.summarize_and_comment.call_args.kwargs
        assert call_kwargs["transcript"] == "tx"
        assert call_kwargs["issue_number"] == 7
        assert call_kwargs["phase"] == "review"
        assert call_kwargs["status"] == "failed"
        assert call_kwargs["duration_seconds"] == 3.5

    @pytest.mark.asyncio
    async def test_skips_summarize_when_no_summarizer(
        self, config: HydraFlowConfig
    ) -> None:
        phase = ReviewPhase(
            config=config,
            state=StateTracker(config.state_file),
            workspaces=MagicMock(),
            reviewers=MagicMock(),
            prs=MagicMock(),
            stop_event=asyncio.Event(),
            store=MagicMock(),
            conflict_resolver=MagicMock(),
            post_merge=MagicMock(),
            # No transcript_summarizer
        )
        result = make_review_result(
            pr_number=10, issue_number=42, transcript="transcript"
        )

        with patch("phase_utils.file_memory_suggestion", new_callable=AsyncMock):
            await phase._post_review_transcript(result, status="success")


class TestReviewLogReference:
    def test_returns_display_path(self, config: HydraFlowConfig) -> None:
        phase = _build_phase(config)
        ref = phase._review_log_reference(101)
        assert "review-pr-101.txt" in ref
