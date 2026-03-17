"""Tests for dashboard — websocket."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from events import EventBus, EventType, HydraFlowEvent
from models import HITLItem
from tests.conftest import EventFactory, make_orchestrator_mock, make_state

if TYPE_CHECKING:
    from config import HydraFlowConfig


@pytest.fixture(autouse=True)
def _disable_hitl_summary_autowarm(config: HydraFlowConfig) -> None:
    """Avoid background HITL summary warm tasks in dashboard smoke tests."""
    config.transcript_summarization_enabled = False
    config.gh_token = ""


# ---------------------------------------------------------------------------
# WebSocket /ws
# ---------------------------------------------------------------------------


class TestWebSocketEndpoint:
    """Tests for the WebSocket /ws endpoint."""

    def test_websocket_connects_successfully(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        with client.websocket_connect("/ws") as ws:
            # Verify the WebSocket session has send/receive capabilities,
            # confirming the /ws endpoint accepted the connection.
            assert hasattr(ws, "receive_text") and hasattr(ws, "send_text")

    def test_websocket_receives_history_on_connect(
        self, config: HydraFlowConfig, event_bus, state
    ) -> None:
        import json

        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        async def publish_events() -> None:
            await event_bus.publish(
                EventFactory.create(type=EventType.PHASE_CHANGE, data={"phase": "plan"})
            )
            await event_bus.publish(
                EventFactory.create(
                    type=EventType.PHASE_CHANGE, data={"phase": "implement"}
                )
            )

        asyncio.run(publish_events())

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        with client.websocket_connect("/ws") as ws:
            msg1 = json.loads(ws.receive_text())
            msg2 = json.loads(ws.receive_text())

        assert msg1["type"] == "phase_change"
        assert msg1["data"]["phase"] == "plan"
        assert msg2["type"] == "phase_change"
        assert msg2["data"]["phase"] == "implement"

    def test_websocket_history_events_are_valid_json(
        self, config: HydraFlowConfig, event_bus, state
    ) -> None:
        import json

        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        async def publish() -> None:
            await event_bus.publish(
                EventFactory.create(
                    type=EventType.WORKER_UPDATE,
                    data={"issue": 42, "status": "running"},
                )
            )

        asyncio.run(publish())

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        with client.websocket_connect("/ws") as ws:
            raw = ws.receive_text()

        parsed = json.loads(raw)
        assert "type" in parsed
        assert "timestamp" in parsed
        assert "data" in parsed
        assert parsed["type"] == "worker_update"
        assert parsed["data"]["issue"] == 42

    def test_websocket_receives_live_event(
        self, config: HydraFlowConfig, event_bus, state
    ) -> None:
        import json

        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        event = EventFactory.create(type=EventType.PR_CREATED, data={"pr": 99})

        original_subscribe = event_bus.subscribe

        def subscribe_with_preload(
            *_args: object, **_kwargs: object
        ) -> asyncio.Queue[HydraFlowEvent]:
            queue = original_subscribe()
            queue.put_nowait(event)
            return queue

        event_bus.subscribe = subscribe_with_preload  # type: ignore[assignment]

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        with client.websocket_connect("/ws") as ws:
            msg = json.loads(ws.receive_text())

        assert msg["type"] == "pr_created"
        assert msg["data"]["pr"] == 99

    def test_websocket_subscribes_to_event_bus_on_connect(
        self, config: HydraFlowConfig, event_bus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        event = EventFactory.create(type=EventType.PHASE_CHANGE, data={"x": 1})

        original_subscribe = event_bus.subscribe

        def subscribe_with_preload(
            *_args: object, **_kwargs: object
        ) -> asyncio.Queue[HydraFlowEvent]:
            queue = original_subscribe()
            queue.put_nowait(event)
            return queue

        event_bus.subscribe = subscribe_with_preload  # type: ignore[assignment]

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        with client.websocket_connect("/ws") as ws:
            ws.receive_text()
            assert len(event_bus._subscribers) >= 1

    def test_websocket_unsubscribes_on_disconnect(
        self, config: HydraFlowConfig, event_bus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        event = EventFactory.create(type=EventType.PHASE_CHANGE, data={"x": 1})
        unsubscribe_called = threading.Event()

        original_subscribe = event_bus.subscribe
        original_unsubscribe = event_bus.unsubscribe

        def subscribe_with_preload(
            *_args: object, **_kwargs: object
        ) -> asyncio.Queue[HydraFlowEvent]:
            queue = original_subscribe()
            # Preload one event so receive_text() returns immediately, ensuring
            # the handler has entered its live-streaming loop before disconnect.
            queue.put_nowait(event)
            return queue

        event_bus.subscribe = subscribe_with_preload  # type: ignore[assignment]

        def unsubscribe_and_signal(
            queue: asyncio.Queue[HydraFlowEvent],
        ) -> None:
            original_unsubscribe(queue)
            unsubscribe_called.set()

        event_bus.unsubscribe = unsubscribe_and_signal  # type: ignore[assignment]

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        with client.websocket_connect("/ws") as ws:
            ws.receive_text()

        # Wait for the background ASGI thread to unsubscribe its queue deterministically
        assert unsubscribe_called.wait(timeout=5), (
            "unsubscribe was not called within 5s"
        )
        # Also verify the unsubscribe actually mutated _subscribers (not just that it was called)
        assert len(event_bus._subscribers) == 0, (
            f"Expected 0 subscribers after disconnect, got {len(event_bus._subscribers)}"
        )

    def test_multiple_websocket_clients_receive_same_history(
        self, config: HydraFlowConfig, event_bus, state
    ) -> None:
        import json

        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        async def publish_events() -> None:
            await event_bus.publish(
                EventFactory.create(type=EventType.PHASE_CHANGE, data={"phase": "plan"})
            )
            await event_bus.publish(
                EventFactory.create(type=EventType.PHASE_CHANGE, data={"phase": "plan"})
            )

        asyncio.run(publish_events())

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)

        with client.websocket_connect("/ws") as ws1:
            msgs1 = [json.loads(ws1.receive_text()) for _ in range(2)]

        with client.websocket_connect("/ws") as ws2:
            msgs2 = [json.loads(ws2.receive_text()) for _ in range(2)]

        assert msgs1[0]["type"] == msgs2[0]["type"]
        assert msgs1[0]["data"] == msgs2[0]["data"]
        assert msgs1[1]["type"] == msgs2[1]["type"]
        assert msgs1[1]["data"] == msgs2[1]["data"]

    def test_websocket_sends_multiple_history_events_in_order(
        self, config: HydraFlowConfig, event_bus, state
    ) -> None:
        import json

        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        async def publish_events() -> None:
            await event_bus.publish(
                EventFactory.create(type=EventType.PHASE_CHANGE, data={"step": 1})
            )
            await event_bus.publish(
                EventFactory.create(type=EventType.PHASE_CHANGE, data={"step": 2})
            )
            await event_bus.publish(
                EventFactory.create(type=EventType.WORKER_UPDATE, data={"step": 3})
            )

        asyncio.run(publish_events())

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        with client.websocket_connect("/ws") as ws:
            msgs = [json.loads(ws.receive_text()) for _ in range(3)]

        assert msgs[0]["type"] == "phase_change"
        assert msgs[1]["type"] == "phase_change"
        assert msgs[2]["type"] == "worker_update"
        assert msgs[0]["data"]["step"] == 1
        assert msgs[1]["data"]["step"] == 2
        assert msgs[2]["data"]["step"] == 3


# ---------------------------------------------------------------------------
# GET /api/hitl
# ---------------------------------------------------------------------------


class TestHITLRoute:
    """Tests for the GET /api/hitl route."""

    def test_hitl_returns_200(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        with patch("pr_manager.PRManager.list_hitl_items", return_value=[]):
            response = client.get("/api/hitl")

        assert response.status_code == 200

    def test_hitl_returns_empty_list_when_no_issues(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        with patch("pr_manager.PRManager.list_hitl_items", return_value=[]):
            response = client.get("/api/hitl")

        assert response.json() == []

    def test_hitl_returns_issues_with_pr_info(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        mock_items = [
            HITLItem(
                issue=42,
                title="Fix widget",
                issueUrl="https://github.com/org/repo/issues/42",
                pr=99,
                prUrl="https://github.com/org/repo/pull/99",
                branch="agent/issue-42",
            ),
        ]

        client = TestClient(app)
        with patch("pr_manager.PRManager.list_hitl_items", return_value=mock_items):
            response = client.get("/api/hitl")

        body = response.json()
        assert len(body) == 1
        assert body[0]["issue"] == 42
        assert body[0]["title"] == "Fix widget"
        assert body[0]["pr"] == 99
        assert body[0]["branch"] == "agent/issue-42"

    def test_hitl_returns_empty_on_gh_failure(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        # PRManager.list_hitl_items handles errors internally, returns []
        with patch("pr_manager.PRManager.list_hitl_items", return_value=[]):
            response = client.get("/api/hitl")

        assert response.json() == []

    def test_hitl_shows_zero_pr_when_no_pr_found(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        mock_items = [
            HITLItem(
                issue=10,
                title="Broken thing",
                issueUrl="",
                pr=0,
                prUrl="",
                branch="agent/issue-10",
            ),
        ]

        client = TestClient(app)
        with patch("pr_manager.PRManager.list_hitl_items", return_value=mock_items):
            response = client.get("/api/hitl")

        body = response.json()
        assert len(body) == 1
        assert body[0]["pr"] == 0
        assert body[0]["prUrl"] == ""


# ---------------------------------------------------------------------------
# POST /api/hitl/{issue}/correct
# ---------------------------------------------------------------------------


class TestHITLCorrectEndpoint:
    """Tests for the POST /api/hitl/{issue}/correct route."""

    def test_correct_returns_ok_with_orchestrator(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        orch.submit_hitl_correction = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with patch("pr_manager.PRManager.swap_pipeline_labels", new_callable=AsyncMock):
            response = client.post(
                "/api/hitl/42/correct",
                json={"correction": "Mock the DB connection"},
            )

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_correct_calls_orchestrator_submit(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        orch.submit_hitl_correction = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with patch("pr_manager.PRManager.swap_pipeline_labels", new_callable=AsyncMock):
            client.post(
                "/api/hitl/42/correct",
                json={"correction": "Fix the test"},
            )

        orch.submit_hitl_correction.assert_called_once_with(42, "Fix the test")

    def test_correct_returns_400_without_orchestrator(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=None)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.post(
            "/api/hitl/42/correct",
            json={"correction": "Something"},
        )

        assert response.status_code == 400
        assert response.json() == {"status": "no orchestrator"}

    def test_correct_publishes_hitl_update_event(
        self, config: HydraFlowConfig, event_bus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        orch.submit_hitl_correction = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with patch("pr_manager.PRManager.swap_pipeline_labels", new_callable=AsyncMock):
            client.post(
                "/api/hitl/42/correct",
                json={"correction": "Fix it"},
            )

        history = event_bus.get_history()
        hitl_events = [e for e in history if e.type.value == "hitl_update"]
        assert len(hitl_events) == 1
        assert hitl_events[0].data["issue"] == 42
        assert hitl_events[0].data["status"] == "processing"
        assert hitl_events[0].data["action"] == "correct"

    def test_correct_rejects_empty_correction(
        self, config: HydraFlowConfig, event_bus: EventBus, tmp_path: Path
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        state = make_state(tmp_path)
        orch = make_orchestrator_mock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.post(
            "/api/hitl/42/correct",
            json={"correction": ""},
        )

        assert response.status_code == 400
        assert "must not be empty" in response.json()["detail"]

    def test_correct_rejects_whitespace_only_correction(
        self, config: HydraFlowConfig, event_bus: EventBus, tmp_path: Path
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        state = make_state(tmp_path)
        orch = make_orchestrator_mock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.post(
            "/api/hitl/42/correct",
            json={"correction": "   "},
        )

        assert response.status_code == 400
        assert "must not be empty" in response.json()["detail"]

    def test_correct_rejects_null_correction(
        self, config: HydraFlowConfig, event_bus: EventBus, tmp_path: Path
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        state = make_state(tmp_path)
        orch = make_orchestrator_mock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.post(
            "/api/hitl/42/correct",
            json={"correction": None},
        )

        assert response.status_code == 400
        assert "must not be empty" in response.json()["detail"]


# ---------------------------------------------------------------------------
# POST /api/hitl/{issue}/skip
# ---------------------------------------------------------------------------


class TestHITLSkipEndpoint:
    """Tests for the POST /api/hitl/{issue}/skip route."""

    def test_skip_returns_ok_with_orchestrator(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        orch.skip_hitl_issue = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with (
            patch("pr_manager.PRManager.remove_label", new_callable=AsyncMock),
            patch("pr_manager.PRManager.close_issue", new_callable=AsyncMock),
            patch("pr_manager.PRManager.post_comment", new_callable=AsyncMock),
        ):
            response = client.post("/api/hitl/42/skip", json={"reason": "not needed"})

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_skip_calls_orchestrator_skip(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        orch.skip_hitl_issue = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with (
            patch("pr_manager.PRManager.remove_label", new_callable=AsyncMock),
            patch("pr_manager.PRManager.close_issue", new_callable=AsyncMock),
            patch("pr_manager.PRManager.post_comment", new_callable=AsyncMock),
        ):
            client.post("/api/hitl/42/skip", json={"reason": "not needed"})

        orch.skip_hitl_issue.assert_called_once_with(42)

    def test_skip_returns_400_without_orchestrator(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=None)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.post("/api/hitl/42/skip", json={"reason": "not needed"})

        assert response.status_code == 400
        assert response.json() == {"status": "no orchestrator"}

    def test_skip_publishes_hitl_update_event(
        self, config: HydraFlowConfig, event_bus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        orch.skip_hitl_issue = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with (
            patch("pr_manager.PRManager.remove_label", new_callable=AsyncMock),
            patch("pr_manager.PRManager.close_issue", new_callable=AsyncMock),
            patch("pr_manager.PRManager.post_comment", new_callable=AsyncMock),
        ):
            client.post("/api/hitl/42/skip", json={"reason": "not needed"})

        history = event_bus.get_history()
        hitl_events = [e for e in history if e.type.value == "hitl_update"]
        assert len(hitl_events) == 1
        assert hitl_events[0].data["issue"] == 42
        assert hitl_events[0].data["status"] == "resolved"
        assert hitl_events[0].data["action"] == "skip"

    def test_skip_removes_hitl_origin_from_state(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        state.set_hitl_origin(42, "hydraflow-review")
        orch = make_orchestrator_mock()
        orch.skip_hitl_issue = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with (
            patch("pr_manager.PRManager.remove_label", new_callable=AsyncMock),
            patch("pr_manager.PRManager.close_issue", new_callable=AsyncMock),
            patch("pr_manager.PRManager.post_comment", new_callable=AsyncMock),
        ):
            client.post("/api/hitl/42/skip", json={"reason": "not needed"})

        assert state.get_hitl_origin(42) is None


# ---------------------------------------------------------------------------
# POST /api/hitl/{issue}/close
# ---------------------------------------------------------------------------


class TestHITLCloseEndpoint:
    """Tests for the POST /api/hitl/{issue}/close route."""

    def test_close_returns_ok_with_orchestrator(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        orch.skip_hitl_issue = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with (
            patch("pr_manager.PRManager.close_issue", new_callable=AsyncMock),
            patch("pr_manager.PRManager.post_comment", new_callable=AsyncMock),
        ):
            response = client.post("/api/hitl/42/close", json={"reason": "duplicate"})

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_close_calls_orchestrator_skip(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        orch.skip_hitl_issue = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with (
            patch("pr_manager.PRManager.close_issue", new_callable=AsyncMock),
            patch("pr_manager.PRManager.post_comment", new_callable=AsyncMock),
        ):
            client.post("/api/hitl/42/close", json={"reason": "duplicate"})

        orch.skip_hitl_issue.assert_called_once_with(42)

    def test_close_returns_400_without_orchestrator(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=None)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.post("/api/hitl/42/close", json={"reason": "duplicate"})

        assert response.status_code == 400
        assert response.json() == {"status": "no orchestrator"}

    def test_close_publishes_hitl_update_event(
        self, config: HydraFlowConfig, event_bus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        orch.skip_hitl_issue = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with (
            patch("pr_manager.PRManager.close_issue", new_callable=AsyncMock),
            patch("pr_manager.PRManager.post_comment", new_callable=AsyncMock),
        ):
            client.post("/api/hitl/42/close", json={"reason": "duplicate"})

        history = event_bus.get_history()
        hitl_events = [e for e in history if e.type.value == "hitl_update"]
        assert len(hitl_events) == 1
        assert hitl_events[0].data["issue"] == 42
        assert hitl_events[0].data["status"] == "resolved"
        assert hitl_events[0].data["action"] == "close"

    def test_close_removes_hitl_origin_from_state(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        state.set_hitl_origin(42, "hydraflow-review")
        orch = make_orchestrator_mock()
        orch.skip_hitl_issue = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with (
            patch("pr_manager.PRManager.close_issue", new_callable=AsyncMock),
            patch("pr_manager.PRManager.post_comment", new_callable=AsyncMock),
        ):
            client.post("/api/hitl/42/close", json={"reason": "duplicate"})

        assert state.get_hitl_origin(42) is None


# ---------------------------------------------------------------------------
# POST /api/hitl/{issue}/approve-memory
# ---------------------------------------------------------------------------


class TestHITLApproveMemoryEndpoint:
    """Tests for the POST /api/hitl/{issue}/approve-memory route."""

    def test_approve_memory_returns_ok_with_orchestrator(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        orch.skip_hitl_issue = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with (
            patch("pr_manager.PRManager.remove_label", new_callable=AsyncMock),
            patch("pr_manager.PRManager.add_labels", new_callable=AsyncMock),
        ):
            response = client.post("/api/hitl/42/approve-memory")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_approve_memory_calls_orchestrator_skip(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        orch.skip_hitl_issue = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with (
            patch("pr_manager.PRManager.remove_label", new_callable=AsyncMock),
            patch("pr_manager.PRManager.add_labels", new_callable=AsyncMock),
        ):
            client.post("/api/hitl/42/approve-memory")

        orch.skip_hitl_issue.assert_called_once_with(42)

    def test_approve_memory_works_without_orchestrator(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=None)
        app = dashboard.create_app()

        client = TestClient(app)
        with (
            patch("pr_manager.PRManager.remove_label", new_callable=AsyncMock),
            patch("pr_manager.PRManager.add_labels", new_callable=AsyncMock),
        ):
            response = client.post("/api/hitl/42/approve-memory")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_approve_memory_publishes_hitl_update_event(
        self, config: HydraFlowConfig, event_bus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        orch.skip_hitl_issue = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with (
            patch("pr_manager.PRManager.remove_label", new_callable=AsyncMock),
            patch("pr_manager.PRManager.add_labels", new_callable=AsyncMock),
        ):
            client.post("/api/hitl/42/approve-memory")

        history = event_bus.get_history()
        hitl_events = [e for e in history if e.type.value == "hitl_update"]
        assert len(hitl_events) == 1
        assert hitl_events[0].data["issue"] == 42
        assert hitl_events[0].data["status"] == "resolved"
        assert hitl_events[0].data["action"] == "approved_as_memory"

    def test_approve_memory_removes_hitl_origin(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        state.set_hitl_origin(42, "hydraflow-improve")
        orch = make_orchestrator_mock()
        orch.skip_hitl_issue = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with (
            patch("pr_manager.PRManager.remove_label", new_callable=AsyncMock),
            patch("pr_manager.PRManager.add_labels", new_callable=AsyncMock),
        ):
            client.post("/api/hitl/42/approve-memory")

        assert state.get_hitl_origin(42) is None

    def test_approve_memory_removes_hitl_cause(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        state.set_hitl_cause(42, "Memory suggestion")
        orch = make_orchestrator_mock()
        orch.skip_hitl_issue = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with (
            patch("pr_manager.PRManager.remove_label", new_callable=AsyncMock),
            patch("pr_manager.PRManager.add_labels", new_callable=AsyncMock),
        ):
            client.post("/api/hitl/42/approve-memory")

        assert state.get_hitl_cause(42) is None

    def test_approve_memory_adds_memory_label(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        orch.skip_hitl_issue = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with (
            patch("pr_manager.PRManager.remove_label", new_callable=AsyncMock),
            patch(
                "pr_manager.PRManager.add_labels", new_callable=AsyncMock
            ) as mock_add,
        ):
            client.post("/api/hitl/42/approve-memory")

        mock_add.assert_called_once_with(42, ["hydraflow-memory"])

    def test_approve_memory_removes_improve_and_hitl_labels(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        orch.skip_hitl_issue = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with (
            patch(
                "pr_manager.PRManager.remove_label", new_callable=AsyncMock
            ) as mock_remove,
            patch("pr_manager.PRManager.add_labels", new_callable=AsyncMock),
        ):
            client.post("/api/hitl/42/approve-memory")

        # Should remove both improve and hitl labels
        removed_labels = [call.args[1] for call in mock_remove.call_args_list]
        assert "hydraflow-improve" in removed_labels
        assert "hydraflow-hitl" in removed_labels


# ---------------------------------------------------------------------------
# POST /api/hitl/{issue}/approve-process
# ---------------------------------------------------------------------------


class TestHITLApproveProcessEndpoint:
    """Tests for the POST /api/hitl/{issue}/approve-process route."""

    def test_bug_report_routes_to_find_label(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        """Bug reports approved from HITL go to triage first."""
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        orch.skip_hitl_issue = MagicMock()
        state.set_hitl_cause(42, "Bug report detected — awaiting human review")
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        swapped: list[tuple[int, str]] = []

        async def _fake_swap(issue_number: int, label: str, **_kw: object) -> None:
            swapped.append((issue_number, label))

        with (
            patch("pr_manager.PRManager.swap_pipeline_labels", side_effect=_fake_swap),
            patch("pr_manager.PRManager.post_comment", new_callable=AsyncMock),
        ):
            response = client.post("/api/hitl/42/approve-process")

        assert response.status_code == 200
        assert swapped == [(42, config.find_label[0])]

    def test_epic_routes_to_find_label(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        """Epic issues approved from HITL also go to triage first."""
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        orch.skip_hitl_issue = MagicMock()
        state.set_hitl_cause(42, "Epic detected — awaiting human review")
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        swapped: list[tuple[int, str]] = []

        async def _fake_swap(issue_number: int, label: str, **_kw: object) -> None:
            swapped.append((issue_number, label))

        with (
            patch("pr_manager.PRManager.swap_pipeline_labels", side_effect=_fake_swap),
            patch("pr_manager.PRManager.post_comment", new_callable=AsyncMock),
        ):
            response = client.post("/api/hitl/42/approve-process")

        assert response.status_code == 200
        assert swapped == [(42, config.find_label[0])]

    def test_returns_400_without_orchestrator(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()
        client = TestClient(app)
        response = client.post("/api/hitl/42/approve-process")
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# GET /api/hitl enriched with status
# ---------------------------------------------------------------------------


class TestHITLEnrichedRoute:
    """Tests for the enriched GET /api/hitl response with status."""

    def test_hitl_includes_status_from_orchestrator(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        orch.get_hitl_status = MagicMock(return_value="processing")
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        mock_items = [
            HITLItem(issue=42, title="Fix widget", branch="agent/issue-42"),
        ]

        client = TestClient(app)
        with patch("pr_manager.PRManager.list_hitl_items", return_value=mock_items):
            response = client.get("/api/hitl")

        body = response.json()
        assert len(body) == 1
        assert body[0]["status"] == "processing"
        orch.get_hitl_status.assert_called_once_with(42)

    def test_hitl_defaults_status_when_no_orchestrator(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=None)
        app = dashboard.create_app()

        mock_items = [
            HITLItem(issue=42, title="Fix widget", branch="agent/issue-42"),
        ]

        client = TestClient(app)
        with patch("pr_manager.PRManager.list_hitl_items", return_value=mock_items):
            response = client.get("/api/hitl")

        body = response.json()
        assert len(body) == 1
        assert body[0]["status"] == "pending"

    def test_hitl_includes_cause_and_status_fields(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        mock_items = [
            HITLItem(
                issue=42,
                title="Fix widget",
                branch="agent/issue-42",
                cause="CI failure",
                status="pending",
            ),
        ]

        client = TestClient(app)
        with patch("pr_manager.PRManager.list_hitl_items", return_value=mock_items):
            response = client.get("/api/hitl")

        body = response.json()
        assert "cause" in body[0]
        assert "status" in body[0]
        assert body[0]["cause"] == "CI failure"


# ---------------------------------------------------------------------------
# WebSocket error logging
# ---------------------------------------------------------------------------


class TestWebSocketErrorLogging:
    """Tests that unexpected WebSocket errors are logged, not silently swallowed."""

    def test_websocket_logs_error_on_history_replay_bug(
        self, config: HydraFlowConfig, event_bus, state
    ) -> None:
        """When send_text raises a non-disconnect error during history replay, logger.error is called."""
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        # Publish an event so history is non-empty
        async def publish() -> None:
            await event_bus.publish(
                EventFactory.create(type=EventType.PHASE_CHANGE, data={"batch": 1})
            )

        asyncio.run(publish())

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()
        client = TestClient(app)

        with patch("dashboard_routes.logger") as mock_logger:
            with (
                patch(
                    "starlette.websockets.WebSocket.send_text",
                    side_effect=RuntimeError("serialization failed"),
                ),
                client.websocket_connect("/ws"),
            ):
                pass

            mock_logger.error.assert_any_call(
                "WebSocket error during history replay: %s",
                "RuntimeError",
                exc_info=True,
            )

    def test_websocket_logs_error_on_live_stream_bug(
        self, config: HydraFlowConfig, event_bus, state
    ) -> None:
        """When send_text raises a non-disconnect error during live streaming, logger.error is called."""
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()
        client = TestClient(app)

        # Pre-populate a queue with one event so queue.get() returns immediately
        event = EventFactory.create(type=EventType.PHASE_CHANGE, data={"x": 1})
        pre_populated_queue: asyncio.Queue[HydraFlowEvent] = asyncio.Queue()
        pre_populated_queue.put_nowait(event)

        with patch("dashboard_routes.logger") as mock_logger:
            # subscribe() returns the pre-populated queue (no history, so
            # send_text is only called during the live streaming phase)
            with (
                patch.object(event_bus, "subscribe", return_value=pre_populated_queue),
                patch.object(event_bus, "get_history", return_value=[]),
                patch(
                    "starlette.websockets.WebSocket.send_text",
                    side_effect=RuntimeError("live stream send failed"),
                ),
                client.websocket_connect("/ws"),
            ):
                pass

            mock_logger.error.assert_any_call(
                "WebSocket error during live streaming: %s",
                "RuntimeError",
                exc_info=True,
            )

    def test_websocket_disconnect_not_logged(
        self, config: HydraFlowConfig, event_bus, state
    ) -> None:
        """WebSocketDisconnect should be handled silently (no warning logged)."""
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()
        client = TestClient(app)

        with patch("dashboard_routes.logger") as mock_logger:
            with client.websocket_connect("/ws"):
                # Just connect and disconnect normally
                pass

            # logger.warning should NOT have been called with WebSocket error messages
            for call in mock_logger.warning.call_args_list:
                assert "WebSocket error" not in str(call)
