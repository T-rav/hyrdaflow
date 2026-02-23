"""Integration tests for harness insight recording in pipeline phases."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import HydraFlowConfig

from harness_insights import FailureCategory, HarnessInsightStore

# ---------------------------------------------------------------------------
# PlanPhase integration
# ---------------------------------------------------------------------------


class TestPlanPhaseHarnessRecording:
    """Tests that PlanPhase records failures to the harness insight store."""

    def test_record_harness_failure_appends_to_store(
        self, config: HydraFlowConfig
    ) -> None:
        from plan_phase import PlanPhase

        memory_dir = config.repo_root / ".hydraflow" / "memory"
        store = HarnessInsightStore(memory_dir)
        phase = PlanPhase(
            config=config,
            state=MagicMock(),
            store=MagicMock(),
            planners=MagicMock(),
            prs=AsyncMock(),
            bus=MagicMock(),
            stop_event=MagicMock(),
            harness_insights=store,
        )

        phase._record_harness_failure(
            42,
            FailureCategory.PLAN_VALIDATION,
            "Missing required sections: ## Files to Modify",
        )

        records = store.load_recent()
        assert len(records) == 1
        assert records[0].issue_number == 42
        assert records[0].category == FailureCategory.PLAN_VALIDATION
        assert records[0].stage == "plan"

    def test_record_harness_failure_noop_when_no_store(
        self, config: HydraFlowConfig
    ) -> None:
        """No crash when harness_insights is None."""
        from plan_phase import PlanPhase

        phase = PlanPhase(
            config=config,
            state=MagicMock(),
            store=MagicMock(),
            planners=MagicMock(),
            prs=AsyncMock(),
            bus=MagicMock(),
            stop_event=MagicMock(),
            harness_insights=None,
        )

        # Should not raise
        phase._record_harness_failure(
            42,
            FailureCategory.PLAN_VALIDATION,
            "Some error",
        )

    def test_record_harness_failure_extracts_subcategories(
        self, config: HydraFlowConfig
    ) -> None:
        from plan_phase import PlanPhase

        memory_dir = config.repo_root / ".hydraflow" / "memory"
        store = HarnessInsightStore(memory_dir)
        phase = PlanPhase(
            config=config,
            state=MagicMock(),
            store=MagicMock(),
            planners=MagicMock(),
            prs=AsyncMock(),
            bus=MagicMock(),
            stop_event=MagicMock(),
            harness_insights=store,
        )

        phase._record_harness_failure(
            42,
            FailureCategory.PLAN_VALIDATION,
            "Missing test coverage section; lint format issues",
        )

        records = store.load_recent()
        assert len(records) == 1
        # Should extract subcategories from the details
        assert any(
            sub in records[0].subcategories for sub in ["missing_tests", "lint_error"]
        )


# ---------------------------------------------------------------------------
# ImplementPhase integration
# ---------------------------------------------------------------------------


class TestImplementPhaseHarnessRecording:
    """Tests that ImplementPhase records failures to the harness insight store."""

    def test_record_harness_failure_appends_to_store(
        self, config: HydraFlowConfig
    ) -> None:
        from implement_phase import ImplementPhase

        memory_dir = config.repo_root / ".hydraflow" / "memory"
        store = HarnessInsightStore(memory_dir)
        phase = ImplementPhase(
            config=config,
            state=MagicMock(),
            worktrees=MagicMock(),
            agents=MagicMock(),
            prs=AsyncMock(),
            store=MagicMock(),
            stop_event=MagicMock(),
            harness_insights=store,
        )

        phase._record_harness_failure(
            55,
            FailureCategory.QUALITY_GATE,
            "ruff lint error: missing import",
        )

        records = store.load_recent()
        assert len(records) == 1
        assert records[0].issue_number == 55
        assert records[0].category == FailureCategory.QUALITY_GATE
        assert records[0].stage == "implement"
        assert "lint_error" in records[0].subcategories

    def test_record_harness_failure_noop_when_no_store(
        self, config: HydraFlowConfig
    ) -> None:
        from implement_phase import ImplementPhase

        phase = ImplementPhase(
            config=config,
            state=MagicMock(),
            worktrees=MagicMock(),
            agents=MagicMock(),
            prs=AsyncMock(),
            store=MagicMock(),
            stop_event=MagicMock(),
            harness_insights=None,
        )

        phase._record_harness_failure(
            55,
            FailureCategory.QUALITY_GATE,
            "Some error",
        )


# ---------------------------------------------------------------------------
# ReviewPhase integration
# ---------------------------------------------------------------------------


class TestReviewPhaseHarnessRecording:
    """Tests that ReviewPhase records failures to the harness insight store."""

    def test_record_harness_failure_appends_to_store(
        self, config: HydraFlowConfig
    ) -> None:
        from review_phase import ReviewPhase

        memory_dir = config.repo_root / ".hydraflow" / "memory"
        store = HarnessInsightStore(memory_dir)
        phase = ReviewPhase(
            config=config,
            state=MagicMock(),
            worktrees=MagicMock(),
            reviewers=MagicMock(),
            prs=AsyncMock(),
            stop_event=MagicMock(),
            store=MagicMock(),
            harness_insights=store,
        )

        phase._record_harness_failure(
            66,
            FailureCategory.REVIEW_REJECTION,
            "Missing error handling and test coverage",
            pr_number=200,
        )

        records = store.load_recent()
        assert len(records) == 1
        assert records[0].issue_number == 66
        assert records[0].pr_number == 200
        assert records[0].category == FailureCategory.REVIEW_REJECTION
        assert records[0].stage == "review"

    def test_record_harness_failure_noop_when_no_store(
        self, config: HydraFlowConfig
    ) -> None:
        from review_phase import ReviewPhase

        phase = ReviewPhase(
            config=config,
            state=MagicMock(),
            worktrees=MagicMock(),
            reviewers=MagicMock(),
            prs=AsyncMock(),
            stop_event=MagicMock(),
            store=MagicMock(),
            harness_insights=None,
        )

        phase._record_harness_failure(
            66,
            FailureCategory.CI_FAILURE,
            "CI failed",
            pr_number=200,
        )

    def test_ci_failure_recording(self, config: HydraFlowConfig) -> None:
        from review_phase import ReviewPhase

        memory_dir = config.repo_root / ".hydraflow" / "memory"
        store = HarnessInsightStore(memory_dir)
        phase = ReviewPhase(
            config=config,
            state=MagicMock(),
            worktrees=MagicMock(),
            reviewers=MagicMock(),
            prs=AsyncMock(),
            stop_event=MagicMock(),
            store=MagicMock(),
            harness_insights=store,
        )

        phase._record_harness_failure(
            77,
            FailureCategory.CI_FAILURE,
            "CI failed after 2 fix attempts: pytest test failures",
            pr_number=300,
        )

        records = store.load_recent()
        assert len(records) == 1
        assert records[0].category == FailureCategory.CI_FAILURE
        assert "test_failure" in records[0].subcategories
