"""Tests for dashboard — websocket."""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING
from unittest.mock import patch

from events import EventBus, EventType, HydraFlowEvent
from tests.conftest import EventFactory

if TYPE_CHECKING:
    from config import HydraFlowConfig

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

        with patch("dashboard_routes._routes.logger") as mock_logger:
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

        with patch("dashboard_routes._routes.logger") as mock_logger:
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

        with patch("dashboard_routes._routes.logger") as mock_logger:
            with client.websocket_connect("/ws"):
                # Just connect and disconnect normally
                pass

            # logger.warning should NOT have been called with WebSocket error messages
            for call in mock_logger.warning.call_args_list:
                assert "WebSocket error" not in str(call)
