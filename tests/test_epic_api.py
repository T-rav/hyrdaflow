"""Tests for epic API models, event types, and endpoint registration."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

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

    def test_epic_readiness_has_expected_defaults(self) -> None:
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

    def test_epic_readiness_roundtrip_via_model_dump(self) -> None:
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


class TestEpicEndpoints:
    """Tests for epic API endpoint handlers."""

    def _make_router(self, config, event_bus, state, tmp_path, get_orch):
        from dashboard_routes import create_router
        from pr_manager import PRManager

        pr_mgr = PRManager(config, event_bus)
        return create_router(
            config=config,
            event_bus=event_bus,
            state=state,
            pr_manager=pr_mgr,
            get_orchestrator=get_orch,
            set_orchestrator=lambda o: None,
            set_run_task=lambda t: None,
            ui_dist_dir=tmp_path / "no-dist",
            template_dir=tmp_path / "no-templates",
        )

    def _find_endpoint(self, router, path, method="GET"):
        for route in router.routes:
            if not hasattr(route, "path") or route.path != path:
                continue
            if not hasattr(route, "methods"):
                continue
            if method in route.methods:
                return route.endpoint
        return None

    @pytest.mark.asyncio
    async def test_get_epics_returns_empty_when_no_orchestrator(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        router = self._make_router(config, event_bus, state, tmp_path, lambda: None)
        endpoint = self._find_endpoint(router, "/api/epics")
        assert endpoint is not None

        response = await endpoint()
        data = json.loads(response.body)
        assert data == []

    @pytest.mark.asyncio
    async def test_get_epics_returns_details(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json
        from unittest.mock import MagicMock

        mock_orch = MagicMock()
        mock_detail = EpicDetail(
            epic_number=100,
            title="v1.0",
            merged_children=2,
            readiness=EpicReadiness(all_implemented=True),
        )
        mock_orch._epic_manager = MagicMock()
        mock_orch._epic_manager.get_all_detail = AsyncMock(return_value=[mock_detail])

        router = self._make_router(
            config, event_bus, state, tmp_path, lambda: mock_orch
        )
        endpoint = self._find_endpoint(router, "/api/epics")

        response = await endpoint()
        data = json.loads(response.body)
        assert len(data) == 1
        assert data[0]["epic_number"] == 100
        assert data[0]["merged_children"] == 2
        assert data[0]["readiness"]["all_implemented"] is True

    @pytest.mark.asyncio
    async def test_get_epic_detail_returns_404_when_not_found(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json
        from unittest.mock import MagicMock

        mock_orch = MagicMock()
        mock_orch._epic_manager = MagicMock()
        mock_orch._epic_manager.get_detail = AsyncMock(return_value=None)

        router = self._make_router(
            config, event_bus, state, tmp_path, lambda: mock_orch
        )
        endpoint = self._find_endpoint(router, "/api/epics/{epic_number}")

        response = await endpoint(999)
        assert response.status_code == 404
        data = json.loads(response.body)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_get_epic_detail_returns_detail(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json
        from unittest.mock import MagicMock

        mock_detail = EpicDetail(
            epic_number=100,
            title="v1.0",
            merge_strategy="bundled",
            children=[
                EpicChildInfo(issue_number=10, current_stage="merged", status="done"),
            ],
        )
        mock_orch = MagicMock()
        mock_orch._epic_manager = MagicMock()
        mock_orch._epic_manager.get_detail = AsyncMock(return_value=mock_detail)

        router = self._make_router(
            config, event_bus, state, tmp_path, lambda: mock_orch
        )
        endpoint = self._find_endpoint(router, "/api/epics/{epic_number}")

        response = await endpoint(100)
        data = json.loads(response.body)
        assert data["epic_number"] == 100
        assert data["merge_strategy"] == "bundled"
        assert len(data["children"]) == 1
        assert data["children"][0]["current_stage"] == "merged"

    @pytest.mark.asyncio
    async def test_trigger_release_returns_503_when_no_orchestrator(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        router = self._make_router(config, event_bus, state, tmp_path, lambda: None)
        endpoint = self._find_endpoint(
            router, "/api/epics/{epic_number}/release", method="POST"
        )
        assert endpoint is not None

        response = await endpoint(100)
        assert response.status_code == 503
        data = json.loads(response.body)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_trigger_release_returns_job_id(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json
        from unittest.mock import MagicMock

        mock_orch = MagicMock()
        mock_orch._epic_manager = MagicMock()
        mock_orch._epic_manager.trigger_release = AsyncMock(
            return_value={"job_id": "release-100-123", "status": "started"}
        )

        router = self._make_router(
            config, event_bus, state, tmp_path, lambda: mock_orch
        )
        endpoint = self._find_endpoint(
            router, "/api/epics/{epic_number}/release", method="POST"
        )

        response = await endpoint(100)
        data = json.loads(response.body)
        assert data["job_id"] == "release-100-123"
        assert data["status"] == "started"

    @pytest.mark.asyncio
    async def test_trigger_release_returns_400_on_error(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json
        from unittest.mock import MagicMock

        mock_orch = MagicMock()
        mock_orch._epic_manager = MagicMock()
        mock_orch._epic_manager.trigger_release = AsyncMock(
            return_value={"error": "epic not found", "status": "failed"}
        )

        router = self._make_router(
            config, event_bus, state, tmp_path, lambda: mock_orch
        )
        endpoint = self._find_endpoint(
            router, "/api/epics/{epic_number}/release", method="POST"
        )

        response = await endpoint(999)
        assert response.status_code == 400
        data = json.loads(response.body)
        assert data["error"] == "epic not found"


class TestMergeableEnrichment:
    """Tests for mergeable field population in _enrich_pr_status."""

    @pytest.mark.asyncio
    async def test_mergeable_set_true(self) -> None:
        """_enrich_pr_status populates mergeable=True from PRManager."""
        from epic import EpicManager

        prs = AsyncMock()
        prs.get_pr_checks = AsyncMock(return_value=[])
        prs.get_pr_reviews = AsyncMock(return_value=[])
        prs.get_pr_mergeable = AsyncMock(return_value=True)

        child = EpicChildInfo(issue_number=42)
        mgr = EpicManager.__new__(EpicManager)
        mgr._prs = prs

        await mgr._enrich_pr_status(child, 99)
        assert child.mergeable is True

    @pytest.mark.asyncio
    async def test_mergeable_set_false(self) -> None:
        """_enrich_pr_status populates mergeable=False for conflicted PRs."""
        from epic import EpicManager

        prs = AsyncMock()
        prs.get_pr_checks = AsyncMock(return_value=[])
        prs.get_pr_reviews = AsyncMock(return_value=[])
        prs.get_pr_mergeable = AsyncMock(return_value=False)

        child = EpicChildInfo(issue_number=42)
        mgr = EpicManager.__new__(EpicManager)
        mgr._prs = prs

        await mgr._enrich_pr_status(child, 99)
        assert child.mergeable is False

    @pytest.mark.asyncio
    async def test_mergeable_none_on_error(self) -> None:
        """_enrich_pr_status leaves mergeable=None on API failure."""
        from epic import EpicManager

        prs = AsyncMock()
        prs.get_pr_checks = AsyncMock(return_value=[])
        prs.get_pr_reviews = AsyncMock(return_value=[])
        prs.get_pr_mergeable = AsyncMock(side_effect=RuntimeError("API error"))

        child = EpicChildInfo(issue_number=42)
        mgr = EpicManager.__new__(EpicManager)
        mgr._prs = prs

        await mgr._enrich_pr_status(child, 99)
        assert child.mergeable is None

    @pytest.mark.asyncio
    async def test_readiness_uses_mergeable_data(self) -> None:
        """_compute_readiness correctly uses mergeable=False to set no_conflicts=False."""
        from epic import EpicManager

        children = [
            EpicChildInfo(
                issue_number=10,
                pr_number=42,
                ci_status="passing",
                review_status="approved",
                mergeable=False,
            ),
        ]

        mgr = EpicManager.__new__(EpicManager)
        from models import EpicState

        epic = EpicState(
            epic_number=100,
            title="v1.0 Release",
            child_issues=[10],
        )

        readiness = mgr._compute_readiness(children, epic)
        assert readiness.no_conflicts is False

    @pytest.mark.asyncio
    async def test_readiness_passes_when_all_mergeable(self) -> None:
        """_compute_readiness sets no_conflicts=True when all PRs are mergeable."""
        from epic import EpicManager

        children = [
            EpicChildInfo(
                issue_number=10,
                pr_number=42,
                ci_status="passing",
                review_status="approved",
                mergeable=True,
            ),
        ]

        mgr = EpicManager.__new__(EpicManager)
        from models import EpicState

        epic = EpicState(
            epic_number=100,
            title="v1.0 Release",
            child_issues=[10],
        )

        readiness = mgr._compute_readiness(children, epic)
        assert readiness.no_conflicts is True
