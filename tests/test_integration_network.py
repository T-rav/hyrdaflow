"""Integration tests for HTTP and network operations.

Tests real network I/O for:
- hf_cli/update_check.py PyPI version checks (mocked HTTP)
- hf_cli/supervisor_service.py TCP socket connections
- dashboard.py FastAPI WebSocket streaming
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.helpers import ConfigFactory

# ---------------------------------------------------------------------------
# update_check.py: PyPI version check with mocked HTTP
# ---------------------------------------------------------------------------


class TestUpdateCheckNetworkIntegration:
    """Integration tests for update check with real cache + mocked HTTP."""

    def test_check_for_updates_cached_full_cycle(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Full cycle: no cache -> fetch -> write cache -> read cache on next call."""
        from hf_cli import update_check

        cache_path = tmp_path / "update-check.json"
        monkeypatch.setattr(update_check, "get_app_version", lambda: "1.0.0")

        fetch_count = 0

        def fake_fetch(timeout_seconds: float) -> str:
            nonlocal fetch_count
            fetch_count += 1
            return "2.0.0"

        monkeypatch.setattr(update_check, "_fetch_latest_pypi_version", fake_fetch)

        # First call: no cache, should fetch
        result1 = update_check.check_for_updates_cached(
            timeout_seconds=1.0, max_age_seconds=3600, path=cache_path
        )
        assert result1.update_available is True
        assert result1.latest_version == "2.0.0"
        assert fetch_count == 1
        assert cache_path.exists()

        # Second call: cache is fresh, should NOT fetch
        result2 = update_check.check_for_updates_cached(
            timeout_seconds=1.0, max_age_seconds=3600, path=cache_path
        )
        assert result2.update_available is True
        assert result2.latest_version == "2.0.0"
        assert fetch_count == 1  # No additional fetch

    def test_check_for_updates_network_error_returns_error(self, monkeypatch) -> None:
        """Network errors should be captured in the result, not raised."""
        from hf_cli import update_check

        monkeypatch.setattr(update_check, "get_app_version", lambda: "1.0.0")

        import httpx

        def boom(timeout_seconds: float) -> str:
            raise httpx.ConnectError("Connection refused")

        monkeypatch.setattr(update_check, "_fetch_latest_pypi_version", boom)

        result = update_check.check_for_updates(timeout_seconds=0.5)
        assert result.update_available is False
        assert result.error is not None
        assert "Connection refused" in result.error

    def test_check_for_updates_timeout_returns_error(self, monkeypatch) -> None:
        """Timeout during fetch should be captured as an error."""
        from hf_cli import update_check

        monkeypatch.setattr(update_check, "get_app_version", lambda: "1.0.0")

        import httpx

        def boom(timeout_seconds: float) -> str:
            raise httpx.ReadTimeout("Read timed out")

        monkeypatch.setattr(update_check, "_fetch_latest_pypi_version", boom)

        result = update_check.check_for_updates(timeout_seconds=0.5)
        assert result.update_available is False
        assert result.error is not None


# ---------------------------------------------------------------------------
# supervisor_service.py: TCP socket protocol
# ---------------------------------------------------------------------------


class TestSupervisorTCPIntegration:
    """Integration tests for the supervisor TCP JSON protocol."""

    @pytest.mark.asyncio
    async def test_ping_command(self, tmp_path: Path) -> None:
        """Supervisor should respond to ping with ok status."""
        from hf_cli.supervisor_service import _handle

        reader = asyncio.StreamReader()
        reader.feed_data(json.dumps({"action": "ping"}).encode() + b"\n")
        reader.feed_eof()

        writer = MagicMock()
        written_data = bytearray()
        writer.write = written_data.extend
        writer.drain = AsyncMock()
        writer.close = MagicMock()
        writer.wait_closed = AsyncMock()

        await _handle(reader, writer)

        response = json.loads(written_data.decode().strip())
        assert response["status"] == "ok"
        assert writer.close.called
        assert writer.wait_closed.called

    @pytest.mark.asyncio
    async def test_unknown_action(self, tmp_path: Path) -> None:
        """Unknown actions should return an error response."""
        from hf_cli.supervisor_service import _handle

        reader = asyncio.StreamReader()
        reader.feed_data(json.dumps({"action": "nonexistent"}).encode() + b"\n")
        reader.feed_eof()

        writer = MagicMock()
        written_data = bytearray()
        writer.write = written_data.extend
        writer.drain = AsyncMock()
        writer.close = MagicMock()
        writer.wait_closed = AsyncMock()

        await _handle(reader, writer)

        response = json.loads(written_data.decode().strip())
        assert response["status"] == "error"
        assert "unknown action" in response["error"]
        assert writer.close.called
        assert writer.wait_closed.called

    @pytest.mark.asyncio
    async def test_list_repos_empty(self) -> None:
        """list_repos should return empty list when no repos are running."""
        from hf_cli.supervisor_service import RUNNERS, _handle

        # Ensure RUNNERS is clean
        original = dict(RUNNERS)
        RUNNERS.clear()
        try:
            reader = asyncio.StreamReader()
            reader.feed_data(json.dumps({"action": "list_repos"}).encode() + b"\n")
            reader.feed_eof()

            writer = MagicMock()
            written_data = bytearray()
            writer.write = written_data.extend
            writer.drain = AsyncMock()
            writer.close = MagicMock()
            writer.wait_closed = AsyncMock()

            await _handle(reader, writer)

            response = json.loads(written_data.decode().strip())
            assert response["status"] == "ok"
            assert isinstance(response["repos"], list)
            assert writer.close.called
            assert writer.wait_closed.called
        finally:
            RUNNERS.clear()
            RUNNERS.update(original)

    @pytest.mark.asyncio
    async def test_add_repo_missing_path(self) -> None:
        """add_repo without path should return an error."""
        from hf_cli.supervisor_service import _handle

        reader = asyncio.StreamReader()
        reader.feed_data(json.dumps({"action": "add_repo"}).encode() + b"\n")
        reader.feed_eof()

        writer = MagicMock()
        written_data = bytearray()
        writer.write = written_data.extend
        writer.drain = AsyncMock()
        writer.close = MagicMock()
        writer.wait_closed = AsyncMock()

        await _handle(reader, writer)

        response = json.loads(written_data.decode().strip())
        assert response["status"] == "error"
        assert "Missing path" in response["error"]
        assert writer.close.called
        assert writer.wait_closed.called

    @pytest.mark.asyncio
    async def test_add_repo_nonexistent_path(self) -> None:
        """add_repo with non-existent path should return an error."""
        from hf_cli.supervisor_service import _handle

        reader = asyncio.StreamReader()
        reader.feed_data(
            json.dumps(
                {"action": "add_repo", "path": "/nonexistent/repo/path"}
            ).encode()
            + b"\n"
        )
        reader.feed_eof()

        writer = MagicMock()
        written_data = bytearray()
        writer.write = written_data.extend
        writer.drain = AsyncMock()
        writer.close = MagicMock()
        writer.wait_closed = AsyncMock()

        await _handle(reader, writer)

        response = json.loads(written_data.decode().strip())
        assert response["status"] == "error"
        assert "not found" in response["error"].lower()
        assert writer.close.called
        assert writer.wait_closed.called

    @pytest.mark.asyncio
    async def test_register_repo(self, tmp_path: Path) -> None:
        """register_repo should register without starting a process."""
        from hf_cli.supervisor_service import _handle

        reader = asyncio.StreamReader()
        reader.feed_data(
            json.dumps({"action": "register_repo", "path": str(tmp_path)}).encode()
            + b"\n"
        )
        reader.feed_eof()

        writer = MagicMock()
        written_data = bytearray()
        writer.write = written_data.extend
        writer.drain = AsyncMock()
        writer.close = MagicMock()
        writer.wait_closed = AsyncMock()

        await _handle(reader, writer)

        response = json.loads(written_data.decode().strip())
        assert response["status"] == "ok"
        assert "slug" in response
        assert writer.close.called
        assert writer.wait_closed.called

    @pytest.mark.asyncio
    async def test_remove_repo_missing_params(self) -> None:
        """remove_repo without path or slug should return error."""
        from hf_cli.supervisor_service import _handle

        reader = asyncio.StreamReader()
        reader.feed_data(json.dumps({"action": "remove_repo"}).encode() + b"\n")
        reader.feed_eof()

        writer = MagicMock()
        written_data = bytearray()
        writer.write = written_data.extend
        writer.drain = AsyncMock()
        writer.close = MagicMock()
        writer.wait_closed = AsyncMock()

        await _handle(reader, writer)

        response = json.loads(written_data.decode().strip())
        assert response["status"] == "error"
        assert writer.close.called
        assert writer.wait_closed.called

    @pytest.mark.asyncio
    async def test_empty_request_handled_gracefully(self) -> None:
        """An empty request should not crash the handler."""
        from hf_cli.supervisor_service import _handle

        reader = asyncio.StreamReader()
        reader.feed_data(b"")
        reader.feed_eof()

        writer = MagicMock()
        writer.write = MagicMock()
        writer.drain = AsyncMock()
        writer.close = MagicMock()
        writer.wait_closed = AsyncMock()

        # Should not raise; early-return path still cleans up the writer
        await _handle(reader, writer)
        assert writer.close.called
        assert writer.wait_closed.called

    @pytest.mark.asyncio
    async def test_invalid_json_request(self) -> None:
        """Invalid JSON should return an error response."""
        from hf_cli.supervisor_service import _handle

        reader = asyncio.StreamReader()
        reader.feed_data(b"not valid json\n")
        reader.feed_eof()

        writer = MagicMock()
        written_data = bytearray()
        writer.write = written_data.extend
        writer.drain = AsyncMock()
        writer.close = MagicMock()
        writer.wait_closed = AsyncMock()

        await _handle(reader, writer)

        response = json.loads(written_data.decode().strip())
        assert response["status"] == "error"
        assert writer.close.called
        assert writer.wait_closed.called


# ---------------------------------------------------------------------------
# supervisor_service.py: port and process helpers
# ---------------------------------------------------------------------------


class TestSupervisorHelpers:
    """Integration tests for supervisor helper functions."""

    def test_find_free_port_returns_usable_port(self) -> None:
        """_find_free_port should return a port that can be bound to."""
        import socket

        from hf_cli.supervisor_service import _find_free_port

        port = _find_free_port()
        assert isinstance(port, int)
        assert port > 0

        # Verify the port is actually available
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", port))

    def test_slug_for_repo_normalizes_spaces(self) -> None:
        """_slug_for_repo should replace spaces with hyphens."""
        from hf_cli.supervisor_service import _slug_for_repo

        assert _slug_for_repo(Path("/home/user/my project")) == "my-project"

    def test_repo_log_file_creates_directory(self) -> None:
        """_repo_log_file should produce a valid log path."""
        from hf_cli.supervisor_service import _repo_log_file

        log_path = _repo_log_file("test-repo", 9001)
        assert "test-repo" in str(log_path)
        assert "9001" in str(log_path)
        assert str(log_path).endswith(".log")


# ---------------------------------------------------------------------------
# dashboard.py: FastAPI WebSocket streaming
# ---------------------------------------------------------------------------


class TestDashboardWebSocketIntegration:
    """Integration tests for the dashboard WebSocket endpoint."""

    @pytest.fixture
    def dashboard_app(self, tmp_path: Path):
        """Create a FastAPI test app for the dashboard."""
        try:
            from fastapi import FastAPI  # noqa: F401
        except ImportError:
            pytest.skip("FastAPI not installed")

        from dashboard import HydraFlowDashboard
        from events import EventBus
        from state import StateTracker

        config = ConfigFactory.create(
            repo_root=tmp_path,
            dashboard_enabled=True,
            dashboard_port=15556,
        )
        bus = EventBus()
        state = StateTracker(tmp_path / "state.json")

        dashboard = HydraFlowDashboard(config, bus, state)
        app = dashboard.create_app()
        return app, bus

    def test_api_state_endpoint(self, dashboard_app) -> None:
        """GET /api/state should return JSON state data."""
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("FastAPI test client not available")

        app, _bus = dashboard_app
        client = TestClient(app)
        response = client.get("/api/state")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)

    def test_api_stats_endpoint(self, dashboard_app) -> None:
        """GET /api/stats should return stats data."""
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("FastAPI test client not available")

        app, _bus = dashboard_app
        client = TestClient(app)
        response = client.get("/api/stats")
        assert response.status_code == 200

    def test_websocket_connects_and_receives_history(self, dashboard_app) -> None:
        """WebSocket should connect and send history events."""
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("FastAPI test client not available")

        from events import EventType, HydraFlowEvent

        app, bus = dashboard_app

        # Publish an event before connecting so it's in history
        event = HydraFlowEvent(type=EventType.TRIAGE_UPDATE, data={"issue": 42})
        loop = asyncio.new_event_loop()
        loop.run_until_complete(bus.publish(event))
        loop.close()

        client = TestClient(app)
        with client.websocket_connect("/ws") as ws:
            # Should receive history event
            data = ws.receive_json()
            assert data["type"] == "triage_update"

    def test_websocket_receives_live_events(self, dashboard_app) -> None:
        """WebSocket should stream live events published after connection."""
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("FastAPI test client not available")

        import threading

        from events import EventType, HydraFlowEvent

        app, bus = dashboard_app
        client = TestClient(app)

        with client.websocket_connect("/ws") as ws:
            # Publish a live event from a separate thread
            def publish_event():
                loop = asyncio.new_event_loop()
                loop.run_until_complete(
                    bus.publish(
                        HydraFlowEvent(
                            type=EventType.PLANNER_UPDATE, data={"issue": 99}
                        )
                    )
                )
                loop.close()

            t = threading.Thread(target=publish_event)
            t.start()
            t.join()

            data = ws.receive_json()
            assert data["type"] == "planner_update"

    def test_root_endpoint_returns_200(self, dashboard_app) -> None:
        """GET / should return 200."""
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("FastAPI test client not available")

        app, _bus = dashboard_app
        client = TestClient(app)
        response = client.get("/")
        assert response.status_code == 200

    def test_spa_catchall_returns_404_for_api_paths(self, dashboard_app) -> None:
        """SPA catchall should not catch api/ paths."""
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("FastAPI test client not available")

        app, _bus = dashboard_app
        client = TestClient(app)
        response = client.get("/api/nonexistent")
        assert response.status_code == 404
