"""Tests for timeline.py — TimelineBuilder event correlation and aggregation."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from events import EventBus, EventType, HydraFlowEvent
from state import StateTracker
from tests.conftest import EventFactory
from timeline import TimelineBuilder


def _ts(offset_seconds: int = 0) -> str:
    """Return an ISO timestamp offset from a fixed base time."""
    base = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
    return (base + timedelta(seconds=offset_seconds)).isoformat()


def _event(
    event_type: EventType,
    offset: int = 0,
    **data: object,
) -> HydraFlowEvent:
    """Create a HydraFlowEvent with a controlled timestamp."""
    return EventFactory.create(type=event_type, timestamp=_ts(offset), data=data)


# ---------------------------------------------------------------------------
# Event grouping
# ---------------------------------------------------------------------------


class TestGroupEventsByIssue:
    def test_single_issue(self, event_bus: EventBus) -> None:
        builder = TimelineBuilder(event_bus)
        events = [
            _event(EventType.TRIAGE_UPDATE, 0, issue=42, status="evaluating"),
            _event(EventType.TRIAGE_UPDATE, 10, issue=42, status="done"),
        ]
        grouped = builder._group_events_by_issue(events)
        assert 42 in grouped
        assert len(grouped[42]) == 2

    def test_multiple_issues(self, event_bus: EventBus) -> None:
        builder = TimelineBuilder(event_bus)
        events = [
            _event(EventType.TRIAGE_UPDATE, 0, issue=42, status="evaluating"),
            _event(EventType.TRIAGE_UPDATE, 5, issue=99, status="evaluating"),
            _event(EventType.PLANNER_UPDATE, 10, issue=42, status="planning"),
        ]
        grouped = builder._group_events_by_issue(events)
        assert len(grouped) == 2
        assert len(grouped[42]) == 2
        assert len(grouped[99]) == 1

    def test_ignores_events_without_issue(self, event_bus: EventBus) -> None:
        builder = TimelineBuilder(event_bus)
        events = [
            _event(EventType.BATCH_START, 0, batch=1),
            _event(EventType.TRIAGE_UPDATE, 5, issue=42, status="done"),
            _event(EventType.BATCH_COMPLETE, 10, batch=1),
        ]
        grouped = builder._group_events_by_issue(events)
        assert len(grouped) == 1
        assert 42 in grouped

    def test_merge_update_correlated_via_pr_created(self, event_bus: EventBus) -> None:
        builder = TimelineBuilder(event_bus)
        events = [
            _event(EventType.PR_CREATED, 0, issue=42, pr=101, branch="agent/issue-42"),
            _event(EventType.MERGE_UPDATE, 50, pr=101, status="merged"),
        ]
        grouped = builder._group_events_by_issue(events)
        assert 42 in grouped
        assert len(grouped[42]) == 2

    def test_issue_created_uses_number_field(self, event_bus: EventBus) -> None:
        builder = TimelineBuilder(event_bus)
        events = [
            _event(EventType.ISSUE_CREATED, 0, number=55, title="New issue"),
        ]
        grouped = builder._group_events_by_issue(events)
        assert 55 in grouped


# ---------------------------------------------------------------------------
# Stage building
# ---------------------------------------------------------------------------


class TestBuildStage:
    def test_triage_stage_from_triage_events(self, event_bus: EventBus) -> None:
        builder = TimelineBuilder(event_bus)
        events = [
            _event(EventType.TRIAGE_UPDATE, 0, issue=42, status="evaluating"),
            _event(EventType.TRIAGE_UPDATE, 10, issue=42, status="done"),
        ]
        stage = builder._build_stage("triage", events)
        assert stage.stage == "triage"
        assert stage.status == "done"
        assert stage.started_at == _ts(0)
        assert stage.completed_at == _ts(10)

    def test_plan_stage_from_planner_events(self, event_bus: EventBus) -> None:
        builder = TimelineBuilder(event_bus)
        events = [
            _event(EventType.PLANNER_UPDATE, 0, issue=42, status="planning"),
            _event(EventType.PLANNER_UPDATE, 30, issue=42, status="done"),
        ]
        stage = builder._build_stage("plan", events)
        assert stage.stage == "plan"
        assert stage.status == "done"

    def test_implement_stage_from_worker_events(self, event_bus: EventBus) -> None:
        builder = TimelineBuilder(event_bus)
        events = [
            _event(EventType.WORKER_UPDATE, 0, issue=42, status="running"),
            _event(EventType.WORKER_UPDATE, 60, issue=42, status="done", commits=3),
        ]
        stage = builder._build_stage("implement", events)
        assert stage.stage == "implement"
        assert stage.status == "done"
        assert stage.metadata.get("commits") == 3

    def test_review_stage_with_verdict_metadata(self, event_bus: EventBus) -> None:
        builder = TimelineBuilder(event_bus)
        events = [
            _event(EventType.REVIEW_UPDATE, 0, issue=42, pr=101, status="reviewing"),
            _event(
                EventType.REVIEW_UPDATE,
                30,
                issue=42,
                pr=101,
                status="done",
                verdict="approve",
                duration=30.0,
            ),
        ]
        stage = builder._build_stage("review", events)
        assert stage.stage == "review"
        assert stage.status == "done"
        assert stage.metadata["verdict"] == "approve"
        assert stage.metadata["duration"] == 30.0

    def test_merge_stage(self, event_bus: EventBus) -> None:
        builder = TimelineBuilder(event_bus)
        events = [
            _event(EventType.MERGE_UPDATE, 0, pr=101, status="merged"),
        ]
        stage = builder._build_stage("merge", events)
        assert stage.stage == "merge"
        assert stage.status == "done"

    def test_failed_stage(self, event_bus: EventBus) -> None:
        builder = TimelineBuilder(event_bus)
        events = [
            _event(EventType.WORKER_UPDATE, 0, issue=42, status="running"),
            _event(EventType.WORKER_UPDATE, 20, issue=42, status="failed"),
        ]
        stage = builder._build_stage("implement", events)
        assert stage.status == "failed"

    def test_in_progress_stage(self, event_bus: EventBus) -> None:
        builder = TimelineBuilder(event_bus)
        events = [
            _event(EventType.WORKER_UPDATE, 0, issue=42, status="running"),
        ]
        stage = builder._build_stage("implement", events)
        assert stage.status == "in_progress"
        assert stage.completed_at is None
        assert stage.duration_seconds is None


# ---------------------------------------------------------------------------
# Duration calculation
# ---------------------------------------------------------------------------


class TestDurationCalculation:
    def test_duration_calculated_from_timestamps(self, event_bus: EventBus) -> None:
        builder = TimelineBuilder(event_bus)
        events = [
            _event(EventType.TRIAGE_UPDATE, 0, issue=42, status="evaluating"),
            _event(EventType.TRIAGE_UPDATE, 15, issue=42, status="done"),
        ]
        stage = builder._build_stage("triage", events)
        assert stage.duration_seconds == pytest.approx(15.0)

    def test_duration_none_when_stage_in_progress(self, event_bus: EventBus) -> None:
        builder = TimelineBuilder(event_bus)
        events = [
            _event(EventType.PLANNER_UPDATE, 0, issue=42, status="planning"),
        ]
        stage = builder._build_stage("plan", events)
        assert stage.duration_seconds is None

    @pytest.mark.asyncio
    async def test_total_duration_across_stages(self, event_bus: EventBus) -> None:
        await event_bus.publish(
            _event(EventType.TRIAGE_UPDATE, 0, issue=42, status="evaluating")
        )
        await event_bus.publish(
            _event(EventType.TRIAGE_UPDATE, 10, issue=42, status="done")
        )
        await event_bus.publish(
            _event(EventType.PLANNER_UPDATE, 10, issue=42, status="planning")
        )
        await event_bus.publish(
            _event(EventType.PLANNER_UPDATE, 40, issue=42, status="done")
        )

        builder = TimelineBuilder(event_bus)
        timeline = builder.build_for_issue(42)
        assert timeline is not None
        assert timeline.total_duration_seconds == pytest.approx(40.0)


# ---------------------------------------------------------------------------
# Transcript previews
# ---------------------------------------------------------------------------


class TestTranscriptPreview:
    def test_first_and_last_lines(self, event_bus: EventBus) -> None:
        builder = TimelineBuilder(event_bus, max_transcript_lines=4)
        events = [
            _event(
                EventType.TRANSCRIPT_LINE,
                i,
                issue=42,
                line=f"Line {i}",
                source="planner",
            )
            for i in range(10)
        ]
        preview = builder._extract_transcript_preview(events)
        assert len(preview) == 4
        assert preview[0] == "Line 0"
        assert preview[1] == "Line 1"
        assert preview[2] == "Line 8"
        assert preview[3] == "Line 9"

    def test_respects_max_lines(self, event_bus: EventBus) -> None:
        builder = TimelineBuilder(event_bus, max_transcript_lines=3)
        events = [
            _event(
                EventType.TRANSCRIPT_LINE,
                i,
                issue=42,
                line=f"Line {i}",
                source="planner",
            )
            for i in range(20)
        ]
        preview = builder._extract_transcript_preview(events)
        assert len(preview) == 3

    def test_empty_when_no_transcript_lines(self, event_bus: EventBus) -> None:
        builder = TimelineBuilder(event_bus)
        events = [
            _event(EventType.WORKER_UPDATE, 0, issue=42, status="running"),
        ]
        preview = builder._extract_transcript_preview(events)
        assert preview == []

    def test_fewer_lines_than_max(self, event_bus: EventBus) -> None:
        builder = TimelineBuilder(event_bus, max_transcript_lines=10)
        events = [
            _event(
                EventType.TRANSCRIPT_LINE,
                0,
                issue=42,
                line="Only line",
                source="planner",
            ),
        ]
        preview = builder._extract_transcript_preview(events)
        assert preview == ["Only line"]


# ---------------------------------------------------------------------------
# PR linking
# ---------------------------------------------------------------------------


class TestPRLinking:
    def test_pr_info_extracted_from_pr_created_event(self, event_bus: EventBus) -> None:
        builder = TimelineBuilder(event_bus)
        events = [
            _event(
                EventType.PR_CREATED,
                0,
                issue=42,
                pr=101,
                url="https://github.com/org/repo/pull/101",
                branch="agent/issue-42",
            ),
        ]
        pr_num, pr_url, branch = builder._extract_pr_info(events)
        assert pr_num == 101
        assert pr_url == "https://github.com/org/repo/pull/101"
        assert branch == "agent/issue-42"

    def test_pr_info_none_when_no_pr_created(self, event_bus: EventBus) -> None:
        builder = TimelineBuilder(event_bus)
        events = [
            _event(EventType.TRIAGE_UPDATE, 0, issue=42, status="done"),
        ]
        pr_num, pr_url, branch = builder._extract_pr_info(events)
        assert pr_num is None
        assert pr_url == ""
        assert branch == ""


# ---------------------------------------------------------------------------
# Partial timelines (in-progress issues)
# ---------------------------------------------------------------------------


class TestPartialTimelines:
    @pytest.mark.asyncio
    async def test_partial_timeline_only_triage(self, event_bus: EventBus) -> None:
        await event_bus.publish(
            _event(EventType.TRIAGE_UPDATE, 0, issue=42, status="evaluating")
        )
        await event_bus.publish(
            _event(EventType.TRIAGE_UPDATE, 5, issue=42, status="done")
        )

        builder = TimelineBuilder(event_bus)
        timeline = builder.build_for_issue(42)
        assert timeline is not None
        assert len(timeline.stages) == 1
        assert timeline.stages[0].stage == "triage"
        assert timeline.current_stage == "triage"
        assert timeline.pr_number is None

    @pytest.mark.asyncio
    async def test_partial_timeline_plan_in_progress(self, event_bus: EventBus) -> None:
        await event_bus.publish(
            _event(EventType.TRIAGE_UPDATE, 0, issue=42, status="evaluating")
        )
        await event_bus.publish(
            _event(EventType.TRIAGE_UPDATE, 10, issue=42, status="done")
        )
        await event_bus.publish(
            _event(EventType.PLANNER_UPDATE, 10, issue=42, status="planning")
        )

        builder = TimelineBuilder(event_bus)
        timeline = builder.build_for_issue(42)
        assert timeline is not None
        assert len(timeline.stages) == 2
        assert timeline.stages[1].stage == "plan"
        assert timeline.stages[1].status == "in_progress"
        assert timeline.current_stage == "plan"

    @pytest.mark.asyncio
    async def test_full_lifecycle_timeline(self, event_bus: EventBus) -> None:
        # Triage
        await event_bus.publish(
            _event(EventType.TRIAGE_UPDATE, 0, issue=42, status="evaluating")
        )
        await event_bus.publish(
            _event(EventType.TRIAGE_UPDATE, 10, issue=42, status="done")
        )
        # Plan
        await event_bus.publish(
            _event(EventType.PLANNER_UPDATE, 10, issue=42, status="planning")
        )
        await event_bus.publish(
            _event(EventType.PLANNER_UPDATE, 40, issue=42, status="done")
        )
        # Implement
        await event_bus.publish(
            _event(EventType.WORKER_UPDATE, 40, issue=42, status="running")
        )
        await event_bus.publish(
            _event(
                EventType.PR_CREATED,
                100,
                issue=42,
                pr=101,
                url="https://github.com/org/repo/pull/101",
                branch="agent/issue-42",
            )
        )
        await event_bus.publish(
            _event(EventType.WORKER_UPDATE, 100, issue=42, status="done")
        )
        # Review
        await event_bus.publish(
            _event(EventType.REVIEW_UPDATE, 100, issue=42, pr=101, status="reviewing")
        )
        await event_bus.publish(
            _event(
                EventType.REVIEW_UPDATE,
                120,
                issue=42,
                pr=101,
                status="done",
                verdict="approve",
            )
        )
        # Merge
        await event_bus.publish(
            _event(EventType.MERGE_UPDATE, 120, pr=101, status="merged")
        )

        builder = TimelineBuilder(event_bus)
        timeline = builder.build_for_issue(42)
        assert timeline is not None
        assert len(timeline.stages) == 5
        stage_names = [s.stage for s in timeline.stages]
        assert stage_names == ["triage", "plan", "implement", "review", "merge"]
        assert timeline.current_stage == "merge"
        assert timeline.pr_number == 101
        assert timeline.branch == "agent/issue-42"
        assert timeline.total_duration_seconds == pytest.approx(120.0)
        # All stages should be done
        for stage in timeline.stages:
            assert stage.status == "done"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_build_all_returns_empty_for_no_events(self, event_bus: EventBus) -> None:
        builder = TimelineBuilder(event_bus)
        assert builder.build_all() == []

    def test_build_for_issue_returns_none_when_not_found(
        self, event_bus: EventBus
    ) -> None:
        builder = TimelineBuilder(event_bus)
        assert builder.build_for_issue(999) is None

    @pytest.mark.asyncio
    async def test_events_with_missing_data_fields_handled_gracefully(
        self, event_bus: EventBus
    ) -> None:
        await event_bus.publish(
            EventFactory.create(type=EventType.TRIAGE_UPDATE, data={})
        )
        builder = TimelineBuilder(event_bus)
        # Should not crash, should just skip events without issue numbers
        timelines = builder.build_all()
        assert timelines == []

    @pytest.mark.asyncio
    async def test_build_all_returns_sorted_by_issue_number(
        self, event_bus: EventBus
    ) -> None:
        await event_bus.publish(
            _event(EventType.TRIAGE_UPDATE, 0, issue=99, status="evaluating")
        )
        await event_bus.publish(
            _event(EventType.TRIAGE_UPDATE, 5, issue=42, status="evaluating")
        )

        builder = TimelineBuilder(event_bus)
        timelines = builder.build_all()
        assert len(timelines) == 2
        assert timelines[0].issue_number == 42
        assert timelines[1].issue_number == 99

    @pytest.mark.asyncio
    async def test_title_extracted_from_issue_created(
        self, event_bus: EventBus
    ) -> None:
        await event_bus.publish(
            _event(EventType.ISSUE_CREATED, 0, number=42, title="Fix the widget")
        )
        await event_bus.publish(
            _event(EventType.TRIAGE_UPDATE, 5, issue=42, status="done")
        )

        builder = TimelineBuilder(event_bus)
        timeline = builder.build_for_issue(42)
        assert timeline is not None
        assert timeline.title == "Fix the widget"

    @pytest.mark.asyncio
    async def test_title_empty_when_no_title_in_events(
        self, event_bus: EventBus
    ) -> None:
        await event_bus.publish(
            _event(EventType.TRIAGE_UPDATE, 0, issue=42, status="done")
        )

        builder = TimelineBuilder(event_bus)
        timeline = builder.build_for_issue(42)
        assert timeline is not None
        assert timeline.title == ""

    @pytest.mark.asyncio
    async def test_hitl_transcript_mapped_to_implement(
        self, event_bus: EventBus
    ) -> None:
        await event_bus.publish(
            _event(EventType.WORKER_UPDATE, 0, issue=42, status="running")
        )
        await event_bus.publish(
            _event(
                EventType.TRANSCRIPT_LINE,
                5,
                issue=42,
                line="HITL fix",
                source="hitl",
            )
        )

        builder = TimelineBuilder(event_bus)
        timeline = builder.build_for_issue(42)
        assert timeline is not None
        stage_names = [s.stage for s in timeline.stages]
        assert "implement" in stage_names

    @pytest.mark.asyncio
    async def test_ci_check_correlated_via_pr(self, event_bus: EventBus) -> None:
        await event_bus.publish(
            _event(EventType.PR_CREATED, 0, issue=42, pr=101, branch="agent/issue-42")
        )
        await event_bus.publish(_event(EventType.CI_CHECK, 10, pr=101, status="passed"))

        builder = TimelineBuilder(event_bus)
        timeline = builder.build_for_issue(42)
        assert timeline is not None
        # CI_CHECK maps to review stage
        stage_names = [s.stage for s in timeline.stages]
        assert "review" in stage_names

    def test_build_stage_empty_events_returns_pending(
        self, event_bus: EventBus
    ) -> None:
        builder = TimelineBuilder(event_bus)
        stage = builder._build_stage("triage", [])
        assert stage.stage == "triage"
        assert stage.status == "pending"
        assert stage.started_at is None
        assert stage.completed_at is None

    def test_unknown_transcript_source_defaults_to_implement(
        self, event_bus: EventBus
    ) -> None:
        builder = TimelineBuilder(event_bus)
        event = _event(
            EventType.TRANSCRIPT_LINE, 0, issue=42, line="output", source="unknown_src"
        )
        stage_name = builder._event_to_stage(event)
        assert stage_name == "implement"

    @pytest.mark.asyncio
    async def test_hitl_escalation_grouped_by_issue(self, event_bus: EventBus) -> None:
        await event_bus.publish(
            _event(EventType.REVIEW_UPDATE, 0, issue=42, pr=101, status="reviewing")
        )
        await event_bus.publish(
            _event(
                EventType.HITL_ESCALATION,
                10,
                issue=42,
                pr=101,
                status="escalated",
                cause="ci_failed",
            )
        )

        builder = TimelineBuilder(event_bus)
        timeline = builder.build_for_issue(42)
        assert timeline is not None
        # HITL_ESCALATION should appear in the review stage
        review_stages = [s for s in timeline.stages if s.stage == "review"]
        assert len(review_stages) == 1
        assert review_stages[0].metadata.get("hitl_cause") == "ci_failed"

    @pytest.mark.asyncio
    async def test_hitl_update_grouped_by_issue(self, event_bus: EventBus) -> None:
        await event_bus.publish(
            _event(EventType.WORKER_UPDATE, 0, issue=42, status="running")
        )
        await event_bus.publish(
            _event(
                EventType.HITL_UPDATE,
                10,
                issue=42,
                status="running",
                action="hitl_run",
            )
        )
        await event_bus.publish(
            _event(
                EventType.HITL_UPDATE,
                30,
                issue=42,
                status="done",
                action="hitl_run",
            )
        )

        builder = TimelineBuilder(event_bus)
        timeline = builder.build_for_issue(42)
        assert timeline is not None
        stage_names = [s.stage for s in timeline.stages]
        assert "implement" in stage_names


# ---------------------------------------------------------------------------
# API endpoint integration
# ---------------------------------------------------------------------------


def _make_state(tmp_path: Path) -> StateTracker:
    return StateTracker(tmp_path / "state.json")


class TestTimelineEndpoints:
    def _make_router(self, config, event_bus, tmp_path):
        from dashboard_routes import create_router
        from pr_manager import PRManager

        state = _make_state(tmp_path)
        pr_mgr = PRManager(config, event_bus)
        return create_router(
            config=config,
            event_bus=event_bus,
            state=state,
            pr_manager=pr_mgr,
            get_orchestrator=lambda: None,
            set_orchestrator=lambda o: None,
            set_run_task=lambda t: None,
            ui_dist_dir=tmp_path / "no-dist",
            template_dir=tmp_path / "no-templates",
        )

    def _find_endpoint(self, router, path):
        for route in router.routes:
            if (
                hasattr(route, "path")
                and route.path == path
                and hasattr(route, "endpoint")
            ):
                return route.endpoint
        return None

    @pytest.mark.asyncio
    async def test_timeline_all_endpoint(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        await event_bus.publish(
            _event(EventType.TRIAGE_UPDATE, 0, issue=42, status="evaluating")
        )
        await event_bus.publish(
            _event(EventType.TRIAGE_UPDATE, 10, issue=42, status="done")
        )

        router = self._make_router(config, event_bus, tmp_path)
        get_timeline = self._find_endpoint(router, "/api/timeline")
        assert get_timeline is not None

        response = await get_timeline()
        data = json.loads(response.body)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["issue_number"] == 42
        assert len(data[0]["stages"]) == 1

    @pytest.mark.asyncio
    async def test_timeline_issue_endpoint(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        await event_bus.publish(
            _event(EventType.TRIAGE_UPDATE, 0, issue=42, status="done")
        )

        router = self._make_router(config, event_bus, tmp_path)
        get_timeline_issue = self._find_endpoint(
            router, "/api/timeline/issue/{issue_num}"
        )
        assert get_timeline_issue is not None

        response = await get_timeline_issue(42)
        data = json.loads(response.body)
        assert data["issue_number"] == 42

    @pytest.mark.asyncio
    async def test_timeline_issue_endpoint_not_found(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        router = self._make_router(config, event_bus, tmp_path)
        get_timeline_issue = self._find_endpoint(
            router, "/api/timeline/issue/{issue_num}"
        )
        assert get_timeline_issue is not None

        response = await get_timeline_issue(999)
        assert response.status_code == 404
        data = json.loads(response.body)
        assert data["error"] == "Issue not found"

    def test_timeline_routes_registered(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        router = self._make_router(config, event_bus, tmp_path)
        paths = {route.path for route in router.routes if hasattr(route, "path")}
        assert "/api/timeline" in paths
        assert "/api/timeline/issue/{issue_num}" in paths
