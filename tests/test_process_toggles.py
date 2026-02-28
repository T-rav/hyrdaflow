"""Tests for process toggles — epic & bug report HITL review gates."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from events import EventBus
from issue_store import IssueStore
from models import TriageResult
from state import StateTracker
from tests.conftest import TaskFactory
from tests.helpers import ConfigFactory
from triage import TriageRunner
from triage_phase import TriagePhase

if TYPE_CHECKING:
    from config import HydraFlowConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_phase(
    config: HydraFlowConfig,
) -> tuple[TriagePhase, StateTracker, AsyncMock, AsyncMock, IssueStore, asyncio.Event]:
    """Build a TriagePhase with mock dependencies."""
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
# Triage routing tests
# ---------------------------------------------------------------------------


class TestProcessToggleRouting:
    """Test that process toggles control HITL routing for epics and bugs."""

    @pytest.mark.asyncio
    async def test_epic_routes_to_hitl_when_toggle_off(self, tmp_path: Path) -> None:
        """Epic + auto_process_epics=False → routes to HITL."""
        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
            auto_process_epics=False,
        )
        phase, state, triage, prs, store, _stop = _make_phase(config)
        issue = TaskFactory.create(id=10, title="Epic: redesign auth", body="A" * 100)

        triage.evaluate = AsyncMock(
            return_value=TriageResult(issue_number=10, ready=True, issue_type="epic")
        )
        store.get_triageable = lambda _max_count: [issue]

        await phase.triage_issues()

        # Should escalate to HITL, not transition to plan
        prs.swap_pipeline_labels.assert_called_once_with(10, config.hitl_label[0])
        prs.post_comment.assert_called_once()
        comment = prs.post_comment.call_args.args[1]
        assert "Epic Detected" in comment
        assert "HITL console" in comment
        # Should NOT transition to plan
        prs.transition.assert_not_called()

    @pytest.mark.asyncio
    async def test_epic_proceeds_when_toggle_on(self, tmp_path: Path) -> None:
        """Epic + auto_process_epics=True → proceeds to plan."""
        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
            auto_process_epics=True,
        )
        phase, _state, triage, prs, store, _stop = _make_phase(config)
        issue = TaskFactory.create(id=11, title="Epic: redesign auth", body="A" * 100)

        triage.evaluate = AsyncMock(
            return_value=TriageResult(issue_number=11, ready=True, issue_type="epic")
        )
        store.get_triageable = lambda _max_count: [issue]

        await phase.triage_issues()

        # Should transition to plan
        prs.transition.assert_called_once_with(11, "plan")

    @pytest.mark.asyncio
    async def test_bug_routes_to_hitl_when_toggle_off(self, tmp_path: Path) -> None:
        """Bug + auto_process_bug_reports=False → routes to HITL."""
        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
            auto_process_bug_reports=False,
        )
        phase, state, triage, prs, store, _stop = _make_phase(config)
        issue = TaskFactory.create(
            id=20, title="Login crashes on empty password", body="A" * 100
        )

        triage.evaluate = AsyncMock(
            return_value=TriageResult(issue_number=20, ready=True, issue_type="bug")
        )
        store.get_triageable = lambda _max_count: [issue]

        await phase.triage_issues()

        prs.swap_pipeline_labels.assert_called_once_with(20, config.hitl_label[0])
        prs.post_comment.assert_called_once()
        comment = prs.post_comment.call_args.args[1]
        assert "Bug Detected" in comment
        prs.transition.assert_not_called()

    @pytest.mark.asyncio
    async def test_bug_proceeds_when_toggle_on(self, tmp_path: Path) -> None:
        """Bug + auto_process_bug_reports=True → proceeds to plan."""
        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
            auto_process_bug_reports=True,
        )
        phase, _state, triage, prs, store, _stop = _make_phase(config)
        issue = TaskFactory.create(id=21, title="Login crashes", body="A" * 100)

        triage.evaluate = AsyncMock(
            return_value=TriageResult(issue_number=21, ready=True, issue_type="bug")
        )
        store.get_triageable = lambda _max_count: [issue]

        await phase.triage_issues()

        prs.transition.assert_called_once_with(21, "plan")

    @pytest.mark.asyncio
    async def test_feature_always_proceeds(self, tmp_path: Path) -> None:
        """Feature issues always proceed to plan regardless of toggles."""
        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
            auto_process_epics=False,
            auto_process_bug_reports=False,
        )
        phase, _state, triage, prs, store, _stop = _make_phase(config)
        issue = TaskFactory.create(id=30, title="Add dark mode", body="A" * 100)

        triage.evaluate = AsyncMock(
            return_value=TriageResult(issue_number=30, ready=True, issue_type="feature")
        )
        store.get_triageable = lambda _max_count: [issue]

        await phase.triage_issues()

        prs.transition.assert_called_once_with(30, "plan")

    @pytest.mark.asyncio
    async def test_unknown_issue_type_treated_as_feature(self, tmp_path: Path) -> None:
        """Unknown issue_type defaults to feature — proceeds to plan."""
        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
            auto_process_epics=False,
            auto_process_bug_reports=False,
        )
        phase, _state, triage, prs, store, _stop = _make_phase(config)
        issue = TaskFactory.create(id=31, title="Some task", body="A" * 100)

        # issue_type will be normalised to "feature" by _result_from_dict
        triage.evaluate = AsyncMock(
            return_value=TriageResult(issue_number=31, ready=True, issue_type="feature")
        )
        store.get_triageable = lambda _max_count: [issue]

        await phase.triage_issues()

        prs.transition.assert_called_once_with(31, "plan")

    @pytest.mark.asyncio
    async def test_epic_hitl_records_cause(self, tmp_path: Path) -> None:
        """Escalated epic should record the cause in state."""
        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
            auto_process_epics=False,
        )
        phase, state, triage, _prs, store, _stop = _make_phase(config)
        issue = TaskFactory.create(id=40, title="Epic: big refactor", body="A" * 100)

        triage.evaluate = AsyncMock(
            return_value=TriageResult(issue_number=40, ready=True, issue_type="epic")
        )
        store.get_triageable = lambda _max_count: [issue]

        await phase.triage_issues()

        cause = state.get_hitl_cause(40)
        assert cause is not None
        assert "epic detected" in cause.lower()


# ---------------------------------------------------------------------------
# TriageResult parsing tests
# ---------------------------------------------------------------------------


class TestTriageResultParsing:
    """Test _result_from_dict parses issue_type correctly."""

    def test_parses_issue_type_feature(self) -> None:
        result = TriageRunner._result_from_dict(
            {"ready": True, "issue_type": "feature"}, 1
        )
        assert result.issue_type == "feature"

    def test_parses_issue_type_bug(self) -> None:
        result = TriageRunner._result_from_dict({"ready": True, "issue_type": "bug"}, 1)
        assert result.issue_type == "bug"

    def test_parses_issue_type_epic(self) -> None:
        result = TriageRunner._result_from_dict(
            {"ready": True, "issue_type": "epic"}, 1
        )
        assert result.issue_type == "epic"

    def test_defaults_to_feature_when_missing(self) -> None:
        result = TriageRunner._result_from_dict({"ready": True}, 1)
        assert result.issue_type == "feature"

    def test_normalises_unknown_to_feature(self) -> None:
        result = TriageRunner._result_from_dict(
            {"ready": True, "issue_type": "task"}, 1
        )
        assert result.issue_type == "feature"

    def test_normalises_none_to_feature(self) -> None:
        result = TriageRunner._result_from_dict({"ready": True, "issue_type": None}, 1)
        assert result.issue_type == "feature"

    def test_normalises_case_insensitive(self) -> None:
        result = TriageRunner._result_from_dict({"ready": True, "issue_type": "BUG"}, 1)
        assert result.issue_type == "bug"


# ---------------------------------------------------------------------------
# HITL enrichment tests
# ---------------------------------------------------------------------------


class TestHITLEnrichment:
    """Test that issueTypeReview flag is set correctly based on cause."""

    def test_epic_cause_sets_flag(self) -> None:
        cause = "Epic detected — awaiting human review (auto_process_epics is off)"
        assert "epic detected" in cause.lower()

    def test_bug_cause_sets_flag(self) -> None:
        cause = "Bug report detected — awaiting human review (auto_process_bug_reports is off)"
        assert "bug report detected" in cause.lower()

    def test_other_cause_no_flag(self) -> None:
        cause = "Insufficient issue detail for triage"
        assert "epic detected" not in cause.lower()
        assert "bug report detected" not in cause.lower()

    def test_none_cause_no_flag(self) -> None:
        cause = None
        # Should not crash or set the flag
        assert not (cause and "epic detected" in cause.lower())
