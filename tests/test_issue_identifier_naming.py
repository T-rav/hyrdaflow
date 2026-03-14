"""Tests for issue #2572 — standardize issue_id → issue_number naming."""

from __future__ import annotations

import inspect

from src.plan_phase import PlanPhase
from src.triage_phase import TriagePhase


class TestParameterNaming:
    """Verify renamed parameters use ``issue_number``, not ``issue_id``."""

    def test_escalate_triage_issue_uses_issue_number_param(self) -> None:
        sig = inspect.signature(TriagePhase._escalate_triage_issue)
        assert "issue_number" in sig.parameters
        assert "issue_id" not in sig.parameters

    def test_plan_log_reference_uses_issue_number_param(self) -> None:
        sig = inspect.signature(PlanPhase._plan_log_reference)
        assert "issue_number" in sig.parameters
        assert "issue_id" not in sig.parameters
