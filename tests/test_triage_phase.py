"""Tests for triage_phase.py — TriagePhase."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from typing import TYPE_CHECKING

from events import EventBus
from issue_store import IssueStore
from state import StateTracker
from tests.conftest import TaskFactory
from triage_phase import TriagePhase

if TYPE_CHECKING:
    from config import HydraFlowConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_phase(
    config: HydraFlowConfig,
) -> tuple[TriagePhase, StateTracker, AsyncMock, AsyncMock, IssueStore, asyncio.Event]:
    """Build a TriagePhase with mock dependencies.

    Returns (phase, state, triage_mock, prs_mock, store, stop_event).
    """
    state = StateTracker(config.state_file)
    bus = EventBus()
    fetcher = AsyncMock()
    store = IssueStore(config, fetcher, bus)
    triage = AsyncMock()
    prs = AsyncMock()
    prs.remove_label = AsyncMock()
    prs.add_labels = AsyncMock()
    prs.swap_pipeline_labels = AsyncMock()
    prs.post_comment = AsyncMock()
    stop_event = asyncio.Event()
    phase = TriagePhase(config, state, store, triage, prs, bus, stop_event)
    return phase, state, triage, prs, store, stop_event


# ---------------------------------------------------------------------------
# Triage phase
# ---------------------------------------------------------------------------


class TestTriagePhase:
    """Tests for TriagePhase.triage_issues()."""

    @pytest.mark.asyncio
    async def test_triage_promotes_ready_issue_to_planning(
        self, config: HydraFlowConfig
    ) -> None:
        from models import TriageResult

        phase, _state, triage, prs, store, _stop = _make_phase(config)
        issue = TaskFactory.create(id=1, title="Implement feature X", body="A" * 100)

        triage.evaluate = AsyncMock(
            return_value=TriageResult(issue_number=1, ready=True)
        )
        store.get_triageable = lambda _max_count: [issue]  # type: ignore[method-assign]

        await phase.triage_issues()

        triage.evaluate.assert_awaited_once_with(issue)
        prs.transition.assert_called_once_with(1, "plan")
        prs.post_comment.assert_not_called()

    @pytest.mark.asyncio
    async def test_triage_escalates_unready_issue_to_hitl(
        self, config: HydraFlowConfig
    ) -> None:
        from models import TriageResult

        phase, _state, triage, prs, store, _stop = _make_phase(config)
        issue = TaskFactory.create(id=2, title="Fix the bug please", body="")

        triage.evaluate = AsyncMock(
            return_value=TriageResult(
                issue_number=2,
                ready=False,
                reasons=["Body is too short or empty (minimum 50 characters)"],
            )
        )
        store.get_triageable = lambda _max_count: [issue]  # type: ignore[method-assign]

        await phase.triage_issues()

        prs.swap_pipeline_labels.assert_called_once_with(2, config.hitl_label[0])
        prs.post_comment.assert_called_once()
        comment = prs.post_comment.call_args.args[1]
        assert "Needs More Information" in comment
        assert "Body is too short" in comment

    @pytest.mark.asyncio
    async def test_triage_escalation_records_hitl_origin(
        self, config: HydraFlowConfig
    ) -> None:
        """Escalating an unready issue should record find_label as HITL origin."""
        from models import TriageResult

        phase, state, triage, _prs, store, _stop = _make_phase(config)
        issue = TaskFactory.create(id=2, title="Fix the bug please", body="")

        triage.evaluate = AsyncMock(
            return_value=TriageResult(
                issue_number=2,
                ready=False,
                reasons=["Body is too short or empty (minimum 50 characters)"],
            )
        )
        store.get_triageable = lambda _max_count: [issue]  # type: ignore[method-assign]

        await phase.triage_issues()

        assert state.get_hitl_origin(2) == "hydraflow-find"

    @pytest.mark.asyncio
    async def test_triage_escalation_sets_hitl_cause(
        self, config: HydraFlowConfig
    ) -> None:
        """Escalating an unready issue should record cause in state."""
        from models import TriageResult

        phase, state, triage, _prs, store, _stop = _make_phase(config)
        issue = TaskFactory.create(id=2, title="Fix the bug please", body="")

        triage.evaluate = AsyncMock(
            return_value=TriageResult(
                issue_number=2,
                ready=False,
                reasons=["Body is too short or empty (minimum 50 characters)"],
            )
        )
        store.get_triageable = lambda _max_count: [issue]  # type: ignore[method-assign]

        await phase.triage_issues()

        assert state.get_hitl_cause(2) == "Insufficient issue detail for triage"

    @pytest.mark.asyncio
    async def test_triage_stops_when_stop_event_set(
        self, config: HydraFlowConfig
    ) -> None:
        from models import TriageResult

        phase, _state, triage, prs, store, _stop = _make_phase(config)
        issues = [
            TaskFactory.create(id=1, title="Issue one long enough", body="A" * 100),
            TaskFactory.create(id=2, title="Issue two long enough", body="B" * 100),
        ]

        call_count = 0

        async def evaluate_then_stop(issue: object) -> TriageResult:
            nonlocal call_count
            call_count += 1
            phase._stop_event.set()  # Stop after first evaluation
            return TriageResult(issue_number=1, ready=True)

        triage.evaluate = AsyncMock(side_effect=evaluate_then_stop)
        store.get_triageable = lambda _max_count: issues  # type: ignore[method-assign]

        await phase.triage_issues()

        # Only the first issue should be evaluated; second skipped due to stop
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_triage_skips_when_no_issues_found(
        self, config: HydraFlowConfig
    ) -> None:
        phase, _state, _triage, prs, store, _stop = _make_phase(config)

        store.get_triageable = lambda _max_count: []  # type: ignore[method-assign]

        await phase.triage_issues()

        prs.remove_label.assert_not_called()

    @pytest.mark.asyncio
    async def test_triage_marks_active_during_processing(
        self, config: HydraFlowConfig
    ) -> None:
        """Triage should mark issues active to prevent re-queuing by refresh."""
        from models import TriageResult

        phase, _state, triage, prs, store, _stop = _make_phase(config)
        issue = TaskFactory.create(id=1, title="Triage test", body="A" * 100)

        was_active_during_evaluate = False

        async def check_active(issue_obj: object) -> TriageResult:
            nonlocal was_active_during_evaluate
            was_active_during_evaluate = store.is_active(1)
            return TriageResult(issue_number=1, ready=True)

        triage.evaluate = AsyncMock(side_effect=check_active)
        store.get_triageable = lambda _max_count: [issue]  # type: ignore[method-assign]

        await phase.triage_issues()

        assert was_active_during_evaluate, "Issue should be marked active during triage"
        assert not store.is_active(1), "Issue should be released after triage"

    @pytest.mark.asyncio
    async def test_adr_issue_routes_to_ready_when_shape_is_valid(
        self, config: HydraFlowConfig
    ) -> None:
        phase, _state, triage, prs, store, _stop = _make_phase(config)
        issue = TaskFactory.create(
            id=77,
            title="[ADR] Adopt event-sourced state snapshots",
            body=(
                "## Context\n"
                "Current pipeline state persistence causes replay costs and stale views.\n\n"
                "## Decision\n"
                "Adopt periodic event-sourced snapshots with compaction to reduce replay.\n\n"
                "## Consequences\n"
                "Adds compaction complexity but improves startup and dashboard freshness."
            ),
        )
        store.get_triageable = lambda _max_count: [issue]  # type: ignore[method-assign]

        await phase.triage_issues()

        triage.evaluate.assert_not_awaited()
        prs.transition.assert_called_once_with(77, "ready")
        prs.post_comment.assert_not_called()

    @pytest.mark.asyncio
    async def test_adr_issue_escalates_to_hitl_when_shape_invalid(
        self, config: HydraFlowConfig
    ) -> None:
        phase, _state, triage, prs, store, _stop = _make_phase(config)
        issue = TaskFactory.create(
            id=78,
            title="[ADR] Simplify build graph",
            body="Need to simplify this soon.",
        )
        store.get_triageable = lambda _max_count: [issue]  # type: ignore[method-assign]

        await phase.triage_issues()

        triage.evaluate.assert_not_awaited()
        prs.swap_pipeline_labels.assert_called_once_with(78, config.hitl_label[0])
        prs.post_comment.assert_called_once()
        comment = prs.post_comment.call_args.args[1]
        assert "Needs More Information" in comment
        assert "Missing required ADR sections" in comment
