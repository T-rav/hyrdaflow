"""Tests for deep-nesting refactoring (issue #2574).

Validates that the extracted helpers and flattened functions preserve
identical behaviour while reducing nesting depth.
"""

from __future__ import annotations

import logging
from datetime import UTC
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from config import _validate_field_bounds
from dashboard_routes import (
    _DONE_STATUS_MAP,
    _STATUS_DRIVEN_TYPES,
    _normalise_event_status,
)
from events import EventLog, EventType, HydraFlowEvent

# ---------------------------------------------------------------------------
# config._validate_field_bounds
# ---------------------------------------------------------------------------


class TestValidateFieldBounds:
    """Tests for the extracted _validate_field_bounds helper."""

    def test_value_within_bounds_returns_true(self) -> None:
        """A value inside [ge, le] passes validation."""
        # max_planners has ge=1, le=50
        assert _validate_field_bounds("max_planners", "HF_MAX_PLANNERS", 5) is True

    def test_value_below_ge_raises(self) -> None:
        """A value below the ge constraint raises ValueError."""
        with pytest.raises(ValueError, match="below minimum"):
            _validate_field_bounds("max_planners", "HF_MAX_PLANNERS", 0)

    def test_value_above_le_raises(self) -> None:
        """A value above the le constraint raises ValueError."""
        with pytest.raises(ValueError, match="above maximum"):
            _validate_field_bounds("max_planners", "HF_MAX_PLANNERS", 999)

    def test_warn_only_below_ge_returns_false(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """warn_only=True logs a warning and returns False instead of raising."""
        with caplog.at_level(logging.WARNING):
            result = _validate_field_bounds(
                "max_planners", "HF_MAX_PLANNERS", 0, warn_only=True
            )
        assert result is False
        assert "below minimum" in caplog.text

    def test_warn_only_above_le_returns_false(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """warn_only=True for above-le logs a warning and returns False."""
        with caplog.at_level(logging.WARNING):
            result = _validate_field_bounds(
                "max_planners", "HF_MAX_PLANNERS", 999, warn_only=True
            )
        assert result is False
        assert "above maximum" in caplog.text

    def test_warn_only_within_bounds_returns_true(self) -> None:
        """warn_only=True still returns True when value is valid."""
        assert (
            _validate_field_bounds("max_planners", "HF_MAX_PLANNERS", 5, warn_only=True)
            is True
        )

    def test_field_without_constraints_passes(self) -> None:
        """A field with no ge/le metadata passes any value."""
        # repo (str field) has no numeric bounds
        assert _validate_field_bounds("repo", "HF_REPO", "anything") is True


# ---------------------------------------------------------------------------
# dashboard_routes._normalise_event_status (dispatch-table refactor)
# ---------------------------------------------------------------------------


class TestNormaliseEventStatusDispatch:
    """Tests for the dispatch-table based _normalise_event_status."""

    def test_merge_update_merged(self) -> None:
        assert (
            _normalise_event_status(EventType.MERGE_UPDATE, {"status": "merged"})
            == "merged"
        )

    def test_merge_update_not_merged(self) -> None:
        assert (
            _normalise_event_status(EventType.MERGE_UPDATE, {"status": "pending"})
            is None
        )

    def test_hitl_escalation(self) -> None:
        assert _normalise_event_status(EventType.HITL_ESCALATION, {}) == "hitl"

    def test_hitl_update_resolved(self) -> None:
        assert (
            _normalise_event_status(EventType.HITL_UPDATE, {"status": "resolved"})
            == "reviewed"
        )

    def test_hitl_update_other(self) -> None:
        assert (
            _normalise_event_status(EventType.HITL_UPDATE, {"status": "pending"})
            == "hitl"
        )

    def test_pr_created(self) -> None:
        assert _normalise_event_status(EventType.PR_CREATED, {}) == "in_review"

    def test_review_update_done(self) -> None:
        assert (
            _normalise_event_status(EventType.REVIEW_UPDATE, {"status": "done"})
            == "reviewed"
        )

    def test_review_update_failed(self) -> None:
        assert (
            _normalise_event_status(EventType.REVIEW_UPDATE, {"status": "failed"})
            == "failed"
        )

    def test_review_update_active(self) -> None:
        assert (
            _normalise_event_status(EventType.REVIEW_UPDATE, {"status": "running"})
            == "active"
        )

    @pytest.mark.parametrize(
        ("event_type", "expected_done"),
        [
            (EventType.WORKER_UPDATE, "implemented"),
            (EventType.PLANNER_UPDATE, "planned"),
            (EventType.TRIAGE_UPDATE, "triaged"),
        ],
        ids=["worker", "planner", "triage"],
    )
    def test_status_driven_done(
        self, event_type: EventType, expected_done: str
    ) -> None:
        """'done' status maps to the type-specific completion string."""
        assert _normalise_event_status(event_type, {"status": "done"}) == expected_done

    @pytest.mark.parametrize(
        "event_type",
        [EventType.WORKER_UPDATE, EventType.PLANNER_UPDATE, EventType.TRIAGE_UPDATE],
    )
    def test_status_driven_failed(self, event_type: EventType) -> None:
        assert _normalise_event_status(event_type, {"status": "failed"}) == "failed"

    @pytest.mark.parametrize(
        "event_type",
        [EventType.WORKER_UPDATE, EventType.PLANNER_UPDATE, EventType.TRIAGE_UPDATE],
    )
    def test_status_driven_active(self, event_type: EventType) -> None:
        assert _normalise_event_status(event_type, {"status": "running"}) == "active"

    def test_unknown_event_type_returns_none(self) -> None:
        assert (
            _normalise_event_status(EventType.PHASE_CHANGE, {"status": "done"}) is None
        )

    def test_done_status_map_and_driven_types_are_synced(self) -> None:
        """_STATUS_DRIVEN_TYPES is derived from _DONE_STATUS_MAP, so they can't diverge."""
        assert frozenset(_DONE_STATUS_MAP) == _STATUS_DRIVEN_TYPES


# ---------------------------------------------------------------------------
# events.EventLog._parse_event_line
# ---------------------------------------------------------------------------


class TestParseEventLine:
    """Tests for the extracted _parse_event_line helper."""

    def test_valid_line_returns_event(self) -> None:
        event = HydraFlowEvent(
            type=EventType.PHASE_CHANGE,
            timestamp="2025-01-01T00:00:00",
            data={},
        )
        line = event.model_dump_json()
        result = EventLog._parse_event_line(line, 1, Path("/fake"), since=None)
        assert result is not None
        assert result.type == EventType.PHASE_CHANGE

    def test_corrupt_line_returns_none(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            result = EventLog._parse_event_line(
                "not-valid-json{{{", 5, Path("/fake/events.jsonl"), since=None
            )
        assert result is None
        assert "Skipping corrupt event log line 5" in caplog.text

    def test_since_filters_old_events(self) -> None:
        from datetime import datetime

        event = HydraFlowEvent(
            type=EventType.PHASE_CHANGE,
            timestamp="2025-01-01T00:00:00+00:00",
            data={},
        )
        line = event.model_dump_json()
        since = datetime(2025, 6, 1, tzinfo=UTC)
        result = EventLog._parse_event_line(line, 1, Path("/fake"), since=since)
        assert result is None

    def test_since_keeps_recent_events(self) -> None:
        from datetime import datetime

        event = HydraFlowEvent(
            type=EventType.PHASE_CHANGE,
            timestamp="2025-07-01T00:00:00+00:00",
            data={},
        )
        line = event.model_dump_json()
        since = datetime(2025, 6, 1, tzinfo=UTC)
        result = EventLog._parse_event_line(line, 1, Path("/fake"), since=since)
        assert result is not None

    def test_since_keeps_events_with_unparseable_timestamp(self) -> None:
        from datetime import datetime

        event = HydraFlowEvent(
            type=EventType.PHASE_CHANGE,
            timestamp="not-a-timestamp",
            data={},
        )
        line = event.model_dump_json()
        since = datetime(2025, 6, 1, tzinfo=UTC)
        result = EventLog._parse_event_line(line, 1, Path("/fake"), since=since)
        assert result is not None


# ---------------------------------------------------------------------------
# epic.EpicManager._enrich_from_github / _enrich_from_branch
# ---------------------------------------------------------------------------


class TestEnrichFromGithub:
    """Tests for the extracted _enrich_from_github helper."""

    @pytest.mark.asyncio
    async def test_runtime_error_is_caught(self, tmp_path: Path) -> None:
        """RuntimeError from fetch is caught; child_info unchanged."""
        from epic import EpicChildInfo

        manager = _make_simple_epic_manager(tmp_path)
        manager._fetcher.fetch_issue_by_number = AsyncMock(
            side_effect=RuntimeError("fetch failed")
        )
        child_info = EpicChildInfo(
            issue_number=1, url="https://github.com/o/r/issues/1"
        )
        await manager._enrich_from_github(child_info, 1, "hydraflow-fixed")
        assert child_info.title == ""  # unchanged

    @pytest.mark.asyncio
    async def test_none_issue_returns_early(self, tmp_path: Path) -> None:
        """When fetch returns None, child_info is unchanged."""
        from epic import EpicChildInfo

        manager = _make_simple_epic_manager(tmp_path)
        manager._fetcher.fetch_issue_by_number = AsyncMock(return_value=None)
        child_info = EpicChildInfo(
            issue_number=1, url="https://github.com/o/r/issues/1"
        )
        await manager._enrich_from_github(child_info, 1, "hydraflow-fixed")
        assert child_info.title == ""

    @pytest.mark.asyncio
    async def test_sets_title_from_github(self, tmp_path: Path) -> None:
        """Title is populated from GitHub issue data."""
        from epic import EpicChildInfo
        from models import GitHubIssue

        manager = _make_simple_epic_manager(tmp_path)
        gh_issue = GitHubIssue(id=1, number=1, title="Test Issue", labels=[], body="")
        manager._fetcher.fetch_issue_by_number = AsyncMock(return_value=gh_issue)
        child_info = EpicChildInfo(
            issue_number=1, url="https://github.com/o/r/issues/1"
        )
        await manager._enrich_from_github(child_info, 1, "hydraflow-fixed")
        assert child_info.title == "Test Issue"

    @pytest.mark.asyncio
    async def test_skips_stage_derivation_when_stage_already_set(
        self, tmp_path: Path
    ) -> None:
        """When current_stage is already set, stage derivation is skipped."""
        from epic import EpicChildInfo, EpicChildStatus
        from models import GitHubIssue

        manager = _make_simple_epic_manager(tmp_path)
        gh_issue = GitHubIssue(
            id=1, number=1, title="Test", labels=["hydraflow-ready"], body=""
        )
        manager._fetcher.fetch_issue_by_number = AsyncMock(return_value=gh_issue)
        child_info = EpicChildInfo(
            issue_number=1, url="https://github.com/o/r/issues/1"
        )
        child_info.current_stage = "merged"
        child_info.status = EpicChildStatus.DONE
        await manager._enrich_from_github(child_info, 1, "")
        # Stage should remain unchanged
        assert child_info.current_stage == "merged"
        assert child_info.status == EpicChildStatus.DONE


class TestEnrichFromBranch:
    """Tests for the extracted _enrich_from_branch helper."""

    @pytest.mark.asyncio
    async def test_no_branch_returns_early(self, tmp_path: Path) -> None:
        """When no branch is recorded, child_info is unchanged."""
        from epic import EpicChildInfo

        manager = _make_simple_epic_manager(tmp_path)
        child_info = EpicChildInfo(
            issue_number=1, url="https://github.com/o/r/issues/1"
        )
        await manager._enrich_from_branch(child_info, 1)
        assert child_info.branch == ""

    @pytest.mark.asyncio
    async def test_runtime_error_on_pr_fetch_is_caught(self, tmp_path: Path) -> None:
        """RuntimeError from find_open_pr_for_branch is caught."""
        from epic import EpicChildInfo

        manager = _make_simple_epic_manager(tmp_path)
        manager._state.set_branch(1, "issue-1")
        manager._prs.find_open_pr_for_branch = AsyncMock(
            side_effect=RuntimeError("pr fetch failed")
        )
        child_info = EpicChildInfo(
            issue_number=1, url="https://github.com/o/r/issues/1"
        )
        await manager._enrich_from_branch(child_info, 1)
        assert child_info.branch == "issue-1"
        assert child_info.pr_number is None

    @pytest.mark.asyncio
    async def test_none_pr_info_returns_early(self, tmp_path: Path) -> None:
        """When find_open_pr_for_branch returns None, PR fields unchanged."""
        from epic import EpicChildInfo

        manager = _make_simple_epic_manager(tmp_path)
        manager._state.set_branch(1, "issue-1")
        manager._prs.find_open_pr_for_branch = AsyncMock(return_value=None)
        child_info = EpicChildInfo(
            issue_number=1, url="https://github.com/o/r/issues/1"
        )
        await manager._enrich_from_branch(child_info, 1)
        assert child_info.branch == "issue-1"
        assert child_info.pr_number is None


# ---------------------------------------------------------------------------
# dashboard_routes._parse_metrics_lines
# ---------------------------------------------------------------------------


class TestParseMetricsLines:
    """Tests for the extracted _parse_metrics_lines helper."""

    def test_valid_jsonl_lines(self) -> None:
        from dashboard_routes import _parse_metrics_lines

        line = '{"timestamp":"2025-01-01T00:00:00","data":{}}'
        result = _parse_metrics_lines([line])
        assert len(result) == 1

    def test_blank_lines_are_skipped(self) -> None:
        from dashboard_routes import _parse_metrics_lines

        result = _parse_metrics_lines(["", "  ", "\n"])
        assert result == []

    def test_corrupt_lines_are_skipped(self, caplog: pytest.LogCaptureFixture) -> None:
        from dashboard_routes import _parse_metrics_lines

        with caplog.at_level(logging.DEBUG):
            result = _parse_metrics_lines(["not-valid-json"])
        assert result == []
        assert "Skipping corrupt metrics snapshot line" in caplog.text

    def test_mixed_valid_and_corrupt(self) -> None:
        from dashboard_routes import _parse_metrics_lines

        valid = '{"timestamp":"2025-01-01T00:00:00","data":{}}'
        result = _parse_metrics_lines([valid, "bad", "", valid])
        assert len(result) == 2


# ---------------------------------------------------------------------------
# dashboard_routes._validate_repo_request_types
# ---------------------------------------------------------------------------


class TestValidateRepoRequestTypes:
    """Tests for the extracted _validate_repo_request_types helper."""

    def test_valid_string_path_returns_none(self) -> None:
        from dashboard_routes import _validate_repo_request_types

        assert _validate_repo_request_types({"path": "/some/path"}) is None

    def test_non_string_path_returns_error(self) -> None:
        from dashboard_routes import _validate_repo_request_types

        assert _validate_repo_request_types({"path": 123}) == "path must be a string"

    def test_non_string_repo_path_returns_error(self) -> None:
        from dashboard_routes import _validate_repo_request_types

        assert (
            _validate_repo_request_types({"repo_path": ["a"]})
            == "path must be a string"
        )

    def test_nested_req_non_string_returns_error(self) -> None:
        from dashboard_routes import _validate_repo_request_types

        assert (
            _validate_repo_request_types({"req": {"path": 42}})
            == "path must be a string"
        )

    def test_no_path_keys_returns_none(self) -> None:
        from dashboard_routes import _validate_repo_request_types

        assert _validate_repo_request_types({"other": "value"}) is None

    def test_none_values_are_ok(self) -> None:
        from dashboard_routes import _validate_repo_request_types

        assert _validate_repo_request_types({"path": None, "repo_path": None}) is None


# ---------------------------------------------------------------------------
# dashboard_routes._log_ws_error and _replay_ws_history
# ---------------------------------------------------------------------------


class TestLogWsError:
    """Tests for the extracted _log_ws_error helper."""

    def test_disconnect_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        from dashboard_routes import _log_ws_error

        with caplog.at_level(logging.WARNING):
            _log_ws_error(ConnectionResetError("reset"), "history replay")
        assert "WebSocket disconnect during history replay" in caplog.text

    def test_non_disconnect_logs_error(self, caplog: pytest.LogCaptureFixture) -> None:
        from dashboard_routes import _log_ws_error

        with caplog.at_level(logging.ERROR):
            _log_ws_error(ValueError("oops"), "live streaming")
        assert "WebSocket error during live streaming" in caplog.text


class TestReplayWsHistory:
    """Tests for the extracted _replay_ws_history helper."""

    @pytest.mark.asyncio
    async def test_successful_replay_returns_true(self) -> None:
        from dashboard_routes import _replay_ws_history
        from events import EventType, HydraFlowEvent

        ws = AsyncMock()
        ws.send_text = AsyncMock()
        events = [
            HydraFlowEvent(
                type=EventType.PHASE_CHANGE, timestamp="2025-01-01T00:00:00", data={}
            )
        ]
        result = await _replay_ws_history(ws, events)
        assert result is True
        ws.send_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_history_returns_true(self) -> None:
        from dashboard_routes import _replay_ws_history

        ws = AsyncMock()
        result = await _replay_ws_history(ws, [])
        assert result is True

    @pytest.mark.asyncio
    async def test_broken_connection_returns_false(self) -> None:
        from dashboard_routes import _replay_ws_history
        from events import EventType, HydraFlowEvent

        ws = AsyncMock()
        ws.send_text = AsyncMock(side_effect=ConnectionResetError("gone"))
        events = [
            HydraFlowEvent(
                type=EventType.PHASE_CHANGE, timestamp="2025-01-01T00:00:00", data={}
            )
        ]
        result = await _replay_ws_history(ws, events)
        assert result is False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_simple_epic_manager(tmp_path: Path):  # noqa: ANN202
    """Build a minimal EpicManager with mocked dependencies."""
    from epic import EpicManager
    from tests.conftest import make_state
    from tests.helpers import ConfigFactory

    config = ConfigFactory.create(
        epic_label=["hydraflow-epic"],
        hitl_label=["hydraflow-hitl"],
    )
    state = make_state(tmp_path)
    prs = AsyncMock()
    fetcher = AsyncMock()
    fetcher.fetch_issue_by_number = AsyncMock(return_value=None)
    bus = AsyncMock()
    bus.publish = AsyncMock()
    manager = EpicManager(config, state, prs, fetcher, bus)
    return manager
