"""Tests for confidence scoring integration in ReviewPhase."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from events import EventBus, EventType
from models import PRInfo, ReviewResult, ReviewVerdict, Task
from tests.helpers import ConfigFactory


def _make_review_phase(
    tmp_path: Path,
    *,
    mode: str = "observe",
    bus: EventBus | None = None,
):
    """Build a ReviewPhase with minimal dependencies for confidence tests."""
    from review_phase import ReviewPhase

    config = ConfigFactory.create(
        repo_root=tmp_path / "repo",
        state_file=tmp_path / "state.json",
        release_confidence_mode=mode,
    )
    (tmp_path / "repo").mkdir(parents=True, exist_ok=True)

    state = MagicMock()
    lifetime = MagicMock()
    lifetime.total_review_approvals = 80
    lifetime.total_review_request_changes = 20
    state.get_lifetime_stats.return_value = lifetime

    worktrees = MagicMock()
    reviewers = MagicMock()
    prs = MagicMock()
    prs.post_pr_comment = AsyncMock()
    stop_event = asyncio.Event()
    store = MagicMock()
    event_bus = bus or EventBus()

    phase = ReviewPhase(
        config=config,
        state=state,
        worktrees=worktrees,
        reviewers=reviewers,
        prs=prs,
        stop_event=stop_event,
        store=store,
        event_bus=event_bus,
    )
    return phase, event_bus


def _make_pr() -> PRInfo:
    return PRInfo(
        number=42,
        issue_number=10,
        branch="feature-branch",
        title="Add feature",
        url="https://github.com/test/test/pull/42",
    )


def _make_task() -> Task:
    return Task(
        id=10,
        title="Add feature",
        complexity_score=3,
    )


def _make_result() -> ReviewResult:
    return ReviewResult(
        pr_number=42,
        issue_number=10,
        verdict=ReviewVerdict.APPROVE,
        success=True,
        ci_passed=True,
        ci_fix_attempts=0,
        visual_passed=True,
        fixes_made=False,
        files_changed=["src/foo.py"],
    )


@pytest.mark.asyncio
class TestComputeAndLogConfidence:
    async def test_observe_mode_publishes_events(self, tmp_path: Path) -> None:
        phase, bus = _make_review_phase(tmp_path, mode="observe")
        pr = _make_pr()
        task = _make_task()
        result = _make_result()

        await phase._compute_and_log_confidence(
            pr,
            task,
            result,
            "diff content\n",
            worker_id=1,
        )

        history = bus.get_history()
        types = [e.type for e in history]
        assert EventType.CONFIDENCE_SCORE in types
        assert EventType.RELEASE_DECISION in types

    async def test_off_mode_skips_scoring(self, tmp_path: Path) -> None:
        phase, bus = _make_review_phase(tmp_path, mode="off")
        pr = _make_pr()
        task = _make_task()
        result = _make_result()

        await phase._compute_and_log_confidence(
            pr,
            task,
            result,
            "diff\n",
            worker_id=1,
        )

        history = bus.get_history()
        assert len(history) == 0

    async def test_confidence_event_has_score(self, tmp_path: Path) -> None:
        phase, bus = _make_review_phase(tmp_path, mode="observe")
        pr = _make_pr()
        task = _make_task()
        result = _make_result()

        await phase._compute_and_log_confidence(
            pr,
            task,
            result,
            "diff\n",
            worker_id=1,
        )

        conf_events = [
            e for e in bus.get_history() if e.type == EventType.CONFIDENCE_SCORE
        ]
        assert len(conf_events) == 1
        data = conf_events[0].data
        assert "score" in data
        assert 0.0 <= data["score"] <= 1.0
        assert data["pr"] == 42
        assert data["issue"] == 10

    async def test_decision_event_has_action(self, tmp_path: Path) -> None:
        phase, bus = _make_review_phase(tmp_path, mode="observe")
        pr = _make_pr()
        task = _make_task()
        result = _make_result()

        await phase._compute_and_log_confidence(
            pr,
            task,
            result,
            "diff\n",
            worker_id=1,
        )

        dec_events = [
            e for e in bus.get_history() if e.type == EventType.RELEASE_DECISION
        ]
        assert len(dec_events) == 1
        data = dec_events[0].data
        assert "action" in data
        assert data["mode"] == "observe"


class TestCollectConfidenceSignals:
    def test_extracts_signals_from_result(self, tmp_path: Path) -> None:
        phase, _ = _make_review_phase(tmp_path, mode="observe")
        task = _make_task()
        result = _make_result()

        signals = phase._collect_confidence_signals(task, result, None)

        assert signals.complexity_score == 3
        assert signals.review_verdict == ReviewVerdict.APPROVE
        assert signals.ci_passed is True
        assert signals.visual_passed is True
        assert signals.code_scanning_alert_count == 0

    def test_counts_code_scanning_alerts(self, tmp_path: Path) -> None:
        from models import CodeScanningAlert

        phase, _ = _make_review_phase(tmp_path, mode="observe")
        task = _make_task()
        result = _make_result()
        alerts = [
            CodeScanningAlert(number=1, severity="high"),
            CodeScanningAlert(number=2, severity="medium"),
        ]

        signals = phase._collect_confidence_signals(task, result, alerts)
        assert signals.code_scanning_alert_count == 2


class TestCollectRiskDimensions:
    def test_extracts_dimensions(self, tmp_path: Path) -> None:
        phase, _ = _make_review_phase(tmp_path, mode="observe")
        task = _make_task()
        result = _make_result()

        dims = phase._collect_risk_dimensions(result, "some diff\n", task, None)

        assert isinstance(dims.files_changed, list)
        assert dims.diff_line_count >= 0

    def test_detects_epic_child(self, tmp_path: Path) -> None:
        phase, _ = _make_review_phase(tmp_path, mode="observe")
        task = Task(id=10, title="Child", parent_epic=5)
        result = _make_result()

        dims = phase._collect_risk_dimensions(result, "diff\n", task, None)
        assert dims.is_epic_child is True
