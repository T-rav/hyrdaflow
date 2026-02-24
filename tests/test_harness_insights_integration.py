"""Integration tests for harness insight recording via phase_utils."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import HydraFlowConfig

from harness_insights import FailureCategory, HarnessInsightStore
from phase_utils import record_harness_failure

# ---------------------------------------------------------------------------
# Plan stage integration
# ---------------------------------------------------------------------------


class TestPlanStageHarnessRecording:
    """Tests that record_harness_failure works for the plan stage."""

    def test_appends_plan_failure_to_store(self, config: HydraFlowConfig) -> None:
        memory_dir = config.repo_root / ".hydraflow" / "memory"
        store = HarnessInsightStore(memory_dir)

        record_harness_failure(
            store,
            42,
            FailureCategory.PLAN_VALIDATION,
            "Missing required sections: ## Files to Modify",
            stage="plan",
        )

        records = store.load_recent()
        assert len(records) == 1
        assert records[0].issue_number == 42
        assert records[0].category == FailureCategory.PLAN_VALIDATION
        assert records[0].stage == "plan"

    def test_noop_when_no_store(self) -> None:
        """No crash when harness_insights is None."""
        record_harness_failure(
            None,
            42,
            FailureCategory.PLAN_VALIDATION,
            "Some error",
            stage="plan",
        )

    def test_extracts_subcategories(self, config: HydraFlowConfig) -> None:
        memory_dir = config.repo_root / ".hydraflow" / "memory"
        store = HarnessInsightStore(memory_dir)

        record_harness_failure(
            store,
            42,
            FailureCategory.PLAN_VALIDATION,
            "Missing test coverage section; lint format issues",
            stage="plan",
        )

        records = store.load_recent()
        assert len(records) == 1
        assert any(
            sub in records[0].subcategories for sub in ["missing_tests", "lint_error"]
        )


# ---------------------------------------------------------------------------
# Implement stage integration
# ---------------------------------------------------------------------------


class TestImplementStageHarnessRecording:
    """Tests that record_harness_failure works for the implement stage."""

    def test_appends_implement_failure_to_store(self, config: HydraFlowConfig) -> None:
        memory_dir = config.repo_root / ".hydraflow" / "memory"
        store = HarnessInsightStore(memory_dir)

        record_harness_failure(
            store,
            55,
            FailureCategory.QUALITY_GATE,
            "ruff lint error: missing import",
            stage="implement",
        )

        records = store.load_recent()
        assert len(records) == 1
        assert records[0].issue_number == 55
        assert records[0].category == FailureCategory.QUALITY_GATE
        assert records[0].stage == "implement"
        assert "lint_error" in records[0].subcategories

    def test_noop_when_no_store(self) -> None:
        record_harness_failure(
            None,
            55,
            FailureCategory.QUALITY_GATE,
            "Some error",
            stage="implement",
        )


# ---------------------------------------------------------------------------
# Review stage integration
# ---------------------------------------------------------------------------


class TestReviewStageHarnessRecording:
    """Tests that record_harness_failure works for the review stage."""

    def test_appends_review_failure_with_pr_number(
        self, config: HydraFlowConfig
    ) -> None:
        memory_dir = config.repo_root / ".hydraflow" / "memory"
        store = HarnessInsightStore(memory_dir)

        record_harness_failure(
            store,
            66,
            FailureCategory.REVIEW_REJECTION,
            "Missing error handling and test coverage",
            stage="review",
            pr_number=200,
        )

        records = store.load_recent()
        assert len(records) == 1
        assert records[0].issue_number == 66
        assert records[0].pr_number == 200
        assert records[0].category == FailureCategory.REVIEW_REJECTION
        assert records[0].stage == "review"

    def test_noop_when_no_store(self) -> None:
        record_harness_failure(
            None,
            66,
            FailureCategory.CI_FAILURE,
            "CI failed",
            stage="review",
            pr_number=200,
        )

    def test_ci_failure_recording(self, config: HydraFlowConfig) -> None:
        memory_dir = config.repo_root / ".hydraflow" / "memory"
        store = HarnessInsightStore(memory_dir)

        record_harness_failure(
            store,
            77,
            FailureCategory.CI_FAILURE,
            "CI failed after 2 fix attempts: pytest test failures",
            stage="review",
            pr_number=300,
        )

        records = store.load_recent()
        assert len(records) == 1
        assert records[0].category == FailureCategory.CI_FAILURE
        assert "test_failure" in records[0].subcategories
