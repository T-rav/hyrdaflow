"""Tests for epic API models, event types, and endpoint registration."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from events import EventType
from models import EpicChildInfo, EpicDetail, EpicProgress, EpicReadiness


class TestEpicEventTypes:
    """Verify the 4 new epic event types are registered."""

    def test_epic_progress_event_exists(self) -> None:
        assert EventType.EPIC_PROGRESS == "epic_progress"

    def test_epic_ready_event_exists(self) -> None:
        assert EventType.EPIC_READY == "epic_ready"

    def test_epic_releasing_event_exists(self) -> None:
        assert EventType.EPIC_RELEASING == "epic_releasing"

    def test_epic_released_event_exists(self) -> None:
        assert EventType.EPIC_RELEASED == "epic_released"

    def test_existing_epic_update_still_exists(self) -> None:
        assert EventType.EPIC_UPDATE == "epic_update"


class TestEpicReadinessModel:
    """Tests for the EpicReadiness model."""

    def test_defaults(self) -> None:
        readiness = EpicReadiness()
        assert readiness.all_implemented is False
        assert readiness.all_approved is False
        assert readiness.all_ci_passing is False
        assert readiness.no_conflicts is False
        assert readiness.changelog_ready is False
        assert readiness.version is None

    def test_all_ready(self) -> None:
        readiness = EpicReadiness(
            all_implemented=True,
            all_approved=True,
            all_ci_passing=True,
            no_conflicts=True,
            changelog_ready=True,
            version="1.2.0",
        )
        assert readiness.all_implemented is True
        assert readiness.version == "1.2.0"

    def test_serialization(self) -> None:
        readiness = EpicReadiness(all_implemented=True, version="2.0")
        data = readiness.model_dump()
        assert data["all_implemented"] is True
        assert data["version"] == "2.0"


class TestEpicChildInfoEnriched:
    """Tests for the enriched EpicChildInfo fields."""

    def test_new_fields_have_defaults(self) -> None:
        child = EpicChildInfo(issue_number=42)
        assert child.pr_number is None
        assert child.pr_url == ""
        assert child.pr_state is None
        assert child.branch == ""
        assert child.ci_status is None
        assert child.review_status is None
        assert child.time_in_stage_seconds == 0
        assert child.stage_entered_at == ""
        assert child.worker is None
        assert child.mergeable is None
        assert child.current_stage == ""
        assert child.status == "queued"

    def test_all_fields_set(self) -> None:
        child = EpicChildInfo(
            issue_number=42,
            title="Test",
            url="https://github.com/org/repo/issues/42",
            current_stage="implement",
            status="running",
            pr_number=99,
            pr_url="https://github.com/org/repo/pull/99",
            pr_state="open",
            branch="agent/issue-42",
            ci_status="passing",
            review_status="approved",
            time_in_stage_seconds=3600,
            stage_entered_at="2026-01-01T00:00:00Z",
            worker="worker-1",
            mergeable=True,
        )
        assert child.pr_number == 99
        assert child.current_stage == "implement"
        assert child.status == "running"
        assert child.ci_status == "passing"
        assert child.review_status == "approved"
        assert child.mergeable is True

    def test_serialization_includes_new_fields(self) -> None:
        child = EpicChildInfo(
            issue_number=42,
            pr_number=99,
            ci_status="failing",
        )
        data = child.model_dump()
        assert "pr_number" in data
        assert "ci_status" in data
        assert "current_stage" in data
        assert "status" in data
        assert data["pr_number"] == 99
        assert data["ci_status"] == "failing"


class TestEpicDetailEnriched:
    """Tests for the enriched EpicDetail model."""

    def test_new_fields_have_defaults(self) -> None:
        detail = EpicDetail(epic_number=100)
        assert detail.merged_children == 0
        assert detail.active_children == 0
        assert detail.queued_children == 0
        assert detail.merge_strategy == "independent"
        assert detail.readiness == EpicReadiness()
        assert detail.release is None

    def test_all_new_fields(self) -> None:
        readiness = EpicReadiness(all_implemented=True)
        detail = EpicDetail(
            epic_number=100,
            merged_children=3,
            active_children=1,
            queued_children=2,
            merge_strategy="bundled",
            readiness=readiness,
            release={"version": "1.0", "tag": "v1.0"},
        )
        assert detail.merged_children == 3
        assert detail.merge_strategy == "bundled"
        assert detail.readiness.all_implemented is True
        assert detail.release == {"version": "1.0", "tag": "v1.0"}

    def test_serialization_includes_readiness(self) -> None:
        detail = EpicDetail(
            epic_number=100,
            readiness=EpicReadiness(all_ci_passing=True),
        )
        data = detail.model_dump()
        assert "readiness" in data
        assert data["readiness"]["all_ci_passing"] is True
        assert "merge_strategy" in data
        assert "merged_children" in data

    def test_children_with_enriched_fields(self) -> None:
        children = [
            EpicChildInfo(
                issue_number=10,
                current_stage="merged",
                status="done",
                pr_number=42,
            ),
            EpicChildInfo(
                issue_number=20,
                current_stage="implement",
                status="running",
                ci_status="passing",
            ),
        ]
        detail = EpicDetail(
            epic_number=100,
            children=children,
            merged_children=1,
            active_children=1,
        )
        data = detail.model_dump()
        assert len(data["children"]) == 2
        assert data["children"][0]["pr_number"] == 42
        assert data["children"][1]["ci_status"] == "passing"


class TestEpicProgressEnriched:
    """Tests for the enriched EpicProgress model."""

    def test_merge_strategy_default(self) -> None:
        progress = EpicProgress(epic_number=100)
        assert progress.merge_strategy == "independent"

    def test_merge_strategy_set(self) -> None:
        progress = EpicProgress(epic_number=100, merge_strategy="bundled")
        assert progress.merge_strategy == "bundled"

    def test_serialization_includes_merge_strategy(self) -> None:
        progress = EpicProgress(epic_number=100, merge_strategy="ordered")
        data = progress.model_dump()
        assert data["merge_strategy"] == "ordered"


class TestWebSocketForwarding:
    """Verify that epic events are forwarded via WebSocket (EventBus).

    The WebSocket handler in dashboard_routes.py forwards ALL events from
    the EventBus. These tests verify the events are publishable and have
    the correct structure.
    """

    @pytest.mark.asyncio
    async def test_epic_events_publishable(self) -> None:
        from events import EventBus, HydraFlowEvent

        bus = EventBus()
        queue = bus.subscribe()

        for event_type in [
            EventType.EPIC_PROGRESS,
            EventType.EPIC_READY,
            EventType.EPIC_RELEASING,
            EventType.EPIC_RELEASED,
        ]:
            await bus.publish(
                HydraFlowEvent(
                    type=event_type,
                    data={"epic_number": 100, "test": True},
                )
            )

        received = []
        while not queue.empty():
            received.append(queue.get_nowait())

        assert len(received) == 4
        types = [e.type for e in received]
        assert EventType.EPIC_PROGRESS in types
        assert EventType.EPIC_READY in types
        assert EventType.EPIC_RELEASING in types
        assert EventType.EPIC_RELEASED in types

    @pytest.mark.asyncio
    async def test_epic_event_serializable(self) -> None:
        from events import HydraFlowEvent

        event = HydraFlowEvent(
            type=EventType.EPIC_PROGRESS,
            data={
                "epic_number": 100,
                "progress": EpicDetail(
                    epic_number=100,
                    merged_children=2,
                    readiness=EpicReadiness(all_implemented=True),
                ).model_dump(),
            },
        )
        json_str = event.model_dump_json()
        assert "epic_progress" in json_str
        assert "100" in json_str


class TestStageFromLabels:
    """Tests for the _stage_from_labels helper."""

    def test_review_label(self, config) -> None:
        from epic import _stage_from_labels

        assert _stage_from_labels(config.review_label, config) == "review"

    def test_ready_label(self, config) -> None:
        from epic import _stage_from_labels

        assert _stage_from_labels(config.ready_label, config) == "implement"

    def test_plan_label(self, config) -> None:
        from epic import _stage_from_labels

        assert _stage_from_labels(config.planner_label, config) == "plan"

    def test_find_label(self, config) -> None:
        from epic import _stage_from_labels

        assert _stage_from_labels(config.find_label, config) == "triage"

    def test_fixed_label(self, config) -> None:
        from epic import _stage_from_labels

        assert _stage_from_labels(config.fixed_label, config) == "merged"

    def test_no_matching_label(self, config) -> None:
        from epic import _stage_from_labels

        assert _stage_from_labels(["unrelated-label"], config) == ""

    def test_empty_labels(self, config) -> None:
        from epic import _stage_from_labels

        assert _stage_from_labels([], config) == ""
