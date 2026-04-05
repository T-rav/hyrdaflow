"""Tests for ImplementPhase transcript/memory post-run hooks."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

if TYPE_CHECKING:
    from config import HydraFlowConfig
from implement_phase import ImplementPhase
from state import StateTracker
from tests.conftest import WorkerResultFactory
from tests.helpers import make_worker_result


def _build_phase(config: HydraFlowConfig) -> ImplementPhase:
    """Build an ImplementPhase with minimal mocks for hook testing."""
    summarizer = MagicMock()
    summarizer.summarize_and_comment = AsyncMock()
    phase = ImplementPhase(
        config=config,
        state=StateTracker(config.state_file),
        workspaces=MagicMock(),
        agents=MagicMock(),
        prs=MagicMock(),
        store=MagicMock(),
        stop_event=asyncio.Event(),
        transcript_summarizer=summarizer,
    )
    return phase


class TestPostImplTranscript:
    """Tests for _post_impl_transcript — memory suggestion + transcript summary."""

    @pytest.mark.asyncio
    async def test_calls_memory_suggestion_and_summarize(
        self, config: HydraFlowConfig
    ) -> None:
        """Happy path: both memory suggestion and summarize are called."""
        phase = _build_phase(config)
        result = make_worker_result(issue_number=42, transcript="some transcript")

        with patch(
            "phase_utils.file_memory_suggestion", new_callable=AsyncMock
        ) as mock_mem:
            await phase._post_impl_transcript(result, status="success")
            mock_mem.assert_awaited_once()
        phase._summarizer.summarize_and_comment.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_memory_suggestion_failure_does_not_block_summarize(
        self, config: HydraFlowConfig
    ) -> None:
        """Exception in memory suggestion must not prevent summarize."""
        phase = _build_phase(config)
        result = make_worker_result(issue_number=1, transcript="transcript")

        with patch(
            "phase_utils.file_memory_suggestion",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            await phase._post_impl_transcript(result, status="success")
        phase._summarizer.summarize_and_comment.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_summarize_failure_does_not_propagate(
        self, config: HydraFlowConfig
    ) -> None:
        """Exception in summarize must not propagate to caller."""
        phase = _build_phase(config)
        phase._summarizer.summarize_and_comment = AsyncMock(
            side_effect=RuntimeError("summarize failed")
        )
        result = make_worker_result(issue_number=99, transcript="transcript")

        with patch("phase_utils.file_memory_suggestion", new_callable=AsyncMock):
            # Should not raise
            await phase._post_impl_transcript(result, status="completed")
        phase._summarizer.summarize_and_comment.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_skips_summarize_when_issue_number_zero(
        self, config: HydraFlowConfig
    ) -> None:
        """When issue_number is 0, summarize is skipped."""
        phase = _build_phase(config)
        result = make_worker_result(issue_number=0, transcript="transcript")

        with patch(
            "phase_utils.file_memory_suggestion", new_callable=AsyncMock
        ) as mock_mem:
            await phase._post_impl_transcript(result, status="completed")
            mock_mem.assert_awaited_once()
        phase._summarizer.summarize_and_comment.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_all_when_no_transcript(self, config: HydraFlowConfig) -> None:
        """When transcript is empty, both hooks are skipped."""
        phase = _build_phase(config)
        result = make_worker_result(issue_number=42, transcript="")

        with patch(
            "phase_utils.file_memory_suggestion", new_callable=AsyncMock
        ) as mock_mem:
            await phase._post_impl_transcript(result, status="success")
            mock_mem.assert_not_awaited()
        phase._summarizer.summarize_and_comment.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_passes_correct_args_to_memory_suggestion(
        self, config: HydraFlowConfig
    ) -> None:
        """Verify argument forwarding to file_memory_suggestion."""
        phase = _build_phase(config)
        result = make_worker_result(issue_number=7, transcript="tx")

        with patch(
            "phase_utils.file_memory_suggestion", new_callable=AsyncMock
        ) as mock_mem:
            await phase._post_impl_transcript(result, status="failed")
            mock_mem.assert_awaited_once_with("tx", "implementer", "issue #7", ANY)

    @pytest.mark.asyncio
    async def test_passes_correct_args_to_summarize(
        self, config: HydraFlowConfig
    ) -> None:
        """Verify argument forwarding to summarize_and_comment."""
        phase = _build_phase(config)
        result = WorkerResultFactory.create(
            issue_number=7, transcript="tx", duration_seconds=3.5
        )

        with patch("phase_utils.file_memory_suggestion", new_callable=AsyncMock):
            await phase._post_impl_transcript(result, status="failed")
        call_kwargs = phase._summarizer.summarize_and_comment.call_args.kwargs
        assert call_kwargs["transcript"] == "tx"
        assert call_kwargs["issue_number"] == 7
        assert call_kwargs["phase"] == "implement"
        assert call_kwargs["status"] == "failed"
        assert call_kwargs["duration_seconds"] == 3.5

    @pytest.mark.asyncio
    async def test_skips_summarize_when_no_summarizer(
        self, config: HydraFlowConfig
    ) -> None:
        """When no transcript_summarizer is provided, summarize is skipped."""
        phase = ImplementPhase(
            config=config,
            state=StateTracker(config.state_file),
            workspaces=MagicMock(),
            agents=MagicMock(),
            prs=MagicMock(),
            store=MagicMock(),
            stop_event=asyncio.Event(),
            # No transcript_summarizer
        )
        result = make_worker_result(issue_number=42, transcript="transcript")

        with patch("phase_utils.file_memory_suggestion", new_callable=AsyncMock):
            # Should not raise — summarizer is None
            await phase._post_impl_transcript(result, status="success")


class TestImplLogReference:
    """Tests for _impl_log_reference helper."""

    def test_returns_display_path(self, config: HydraFlowConfig) -> None:
        phase = _build_phase(config)
        ref = phase._impl_log_reference(42)
        assert "issue-42.txt" in ref
