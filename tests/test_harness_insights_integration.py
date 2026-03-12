"""Integration tests for harness insight recording via phase_utils."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from harness_insights import FailureCategory, HarnessInsightStore
from models import PipelineStage
from phase_utils import record_harness_failure

# ---------------------------------------------------------------------------
# Plan stage integration
# ---------------------------------------------------------------------------


class TestPlanStageHarnessRecording:
    """Tests that record_harness_failure works for the plan stage."""

    @pytest.mark.asyncio
    async def test_appends_plan_failure_to_store(self) -> None:
        mock_hindsight = AsyncMock()
        store = HarnessInsightStore(hindsight=mock_hindsight)
        store.record_failure = AsyncMock()

        await record_harness_failure(
            store,
            42,
            FailureCategory.PLAN_VALIDATION,
            "Missing required sections: ## Files to Modify",
            stage=PipelineStage.PLAN,
        )

        store.record_failure.assert_called_once()
        record = store.record_failure.call_args[0][0]
        assert record.issue_number == 42
        assert record.category == FailureCategory.PLAN_VALIDATION
        assert record.stage == "plan"

    @pytest.mark.asyncio
    async def test_noop_when_no_store(self) -> None:
        """No crash when harness_insights is None."""
        await record_harness_failure(
            None,
            42,
            FailureCategory.PLAN_VALIDATION,
            "Some error",
            stage=PipelineStage.PLAN,
        )

    @pytest.mark.asyncio
    async def test_extracts_subcategories(self) -> None:
        mock_hindsight = AsyncMock()
        store = HarnessInsightStore(hindsight=mock_hindsight)
        store.record_failure = AsyncMock()

        await record_harness_failure(
            store,
            42,
            FailureCategory.PLAN_VALIDATION,
            "Missing test coverage section; lint format issues",
            stage=PipelineStage.PLAN,
        )

        store.record_failure.assert_called_once()
        record = store.record_failure.call_args[0][0]
        assert any(
            sub in record.subcategories for sub in ["missing_tests", "lint_error"]
        )


# ---------------------------------------------------------------------------
# Implement stage integration
# ---------------------------------------------------------------------------


class TestImplementStageHarnessRecording:
    """Tests that record_harness_failure works for the implement stage."""

    @pytest.mark.asyncio
    async def test_appends_implement_failure_to_store(self) -> None:
        mock_hindsight = AsyncMock()
        store = HarnessInsightStore(hindsight=mock_hindsight)
        store.record_failure = AsyncMock()

        await record_harness_failure(
            store,
            55,
            FailureCategory.QUALITY_GATE,
            "ruff lint error: missing import",
            stage=PipelineStage.IMPLEMENT,
        )

        store.record_failure.assert_called_once()
        record = store.record_failure.call_args[0][0]
        assert record.issue_number == 55
        assert record.category == FailureCategory.QUALITY_GATE
        assert record.stage == "implement"
        assert "lint_error" in record.subcategories

    @pytest.mark.asyncio
    async def test_noop_when_no_store(self) -> None:
        await record_harness_failure(
            None,
            55,
            FailureCategory.QUALITY_GATE,
            "Some error",
            stage=PipelineStage.IMPLEMENT,
        )


# ---------------------------------------------------------------------------
# Review stage integration
# ---------------------------------------------------------------------------


class TestReviewStageHarnessRecording:
    """Tests that record_harness_failure works for the review stage."""

    @pytest.mark.asyncio
    async def test_appends_review_failure_with_pr_number(self) -> None:
        mock_hindsight = AsyncMock()
        store = HarnessInsightStore(hindsight=mock_hindsight)
        store.record_failure = AsyncMock()

        await record_harness_failure(
            store,
            66,
            FailureCategory.REVIEW_REJECTION,
            "Missing error handling and test coverage",
            stage=PipelineStage.REVIEW,
            pr_number=200,
        )

        store.record_failure.assert_called_once()
        record = store.record_failure.call_args[0][0]
        assert record.issue_number == 66
        assert record.pr_number == 200
        assert record.category == FailureCategory.REVIEW_REJECTION
        assert record.stage == "review"

    @pytest.mark.asyncio
    async def test_noop_when_no_store(self) -> None:
        await record_harness_failure(
            None,
            66,
            FailureCategory.CI_FAILURE,
            "CI failed",
            stage=PipelineStage.REVIEW,
            pr_number=200,
        )

    @pytest.mark.asyncio
    async def test_ci_failure_recording(self) -> None:
        mock_hindsight = AsyncMock()
        store = HarnessInsightStore(hindsight=mock_hindsight)
        store.record_failure = AsyncMock()

        await record_harness_failure(
            store,
            77,
            FailureCategory.CI_FAILURE,
            "CI failed after 2 fix attempts: pytest test failures",
            stage=PipelineStage.REVIEW,
            pr_number=300,
        )

        store.record_failure.assert_called_once()
        record = store.record_failure.call_args[0][0]
        assert record.category == FailureCategory.CI_FAILURE
        assert "test_failure" in record.subcategories
