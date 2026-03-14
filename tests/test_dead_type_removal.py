"""Tests verifying that dead model types have been removed from models.py."""

from __future__ import annotations

import importlib


class TestDeadTypeRemoval:
    """Verify that RunnerResult, BatchResult, and PhaseChangePayload are no longer importable."""

    def test_runner_result_not_importable(self) -> None:
        models = importlib.import_module("models")
        assert not hasattr(models, "RunnerResult"), "RunnerResult should be removed"

    def test_batch_result_not_importable(self) -> None:
        models = importlib.import_module("models")
        assert not hasattr(models, "BatchResult"), "BatchResult should be removed"

    def test_phase_change_payload_not_importable(self) -> None:
        models = importlib.import_module("models")
        assert not hasattr(models, "PhaseChangePayload"), (
            "PhaseChangePayload should be removed"
        )

    def test_other_model_types_still_importable(self) -> None:
        """Core model types must remain available after dead code removal."""
        from models import (
            HITLResult,
            LoopResult,
            Phase,
            PlanResult,
            PRInfo,
            ReviewResult,
            Task,
            WorkerResult,
        )

        # Verify they are actual classes/types
        assert callable(Task)
        assert callable(PRInfo)
        assert callable(PlanResult)
        assert callable(WorkerResult)
        assert callable(ReviewResult)
        assert callable(HITLResult)
        assert callable(Phase)
        assert callable(LoopResult)
