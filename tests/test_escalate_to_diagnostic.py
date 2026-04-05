"""Tests for escalate_to_diagnostic helper."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from models import EscalationContext
from phase_utils import escalate_to_diagnostic


class TestEscalateToDiagnostic:
    @pytest.fixture
    def mock_state(self):
        return MagicMock()

    @pytest.fixture
    def mock_prs(self):
        prs = AsyncMock()
        prs.swap_pipeline_labels = AsyncMock()
        return prs

    @pytest.mark.asyncio
    async def test_stores_context_and_swaps_label(self, mock_state, mock_prs) -> None:
        ctx = EscalationContext(cause="CI failed", origin_phase="review")
        await escalate_to_diagnostic(
            mock_state,
            mock_prs,
            issue_number=42,
            context=ctx,
            origin_label="hydraflow-review",
            diagnose_label="hydraflow-diagnose",
        )
        mock_state.set_escalation_context.assert_called_once_with(42, ctx)
        mock_state.set_hitl_origin.assert_called_once_with(42, "hydraflow-review")
        mock_state.set_hitl_cause.assert_called_once_with(42, "CI failed")
        mock_state.record_hitl_escalation.assert_called_once()
        mock_prs.swap_pipeline_labels.assert_awaited_once_with(42, "hydraflow-diagnose")

    @pytest.mark.asyncio
    async def test_swaps_to_diagnose_not_hitl(self, mock_state, mock_prs) -> None:
        ctx = EscalationContext(cause="test", origin_phase="implement")
        await escalate_to_diagnostic(
            mock_state,
            mock_prs,
            issue_number=10,
            context=ctx,
            origin_label="hydraflow-ready",
            diagnose_label="hydraflow-diagnose",
        )
        label_arg = mock_prs.swap_pipeline_labels.call_args[0][1]
        assert label_arg == "hydraflow-diagnose"
        assert "hitl" not in label_arg
