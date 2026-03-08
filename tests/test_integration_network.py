"""Integration tests for HTTP and WebSocket operations.

Covers: hf_cli/update_check.py (cache persistence, version comparison),
        dashboard.py (FastAPI WebSocket streaming via real TestClient),
        hf_cli/supervisor_service.py (TCP port allocation, slug sanitization).
"""

from __future__ import annotations

import asyncio
import json
import socket
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# hf_cli/update_check.py — cache I/O
# ---------------------------------------------------------------------------


class TestUpdateCheckCache:
    """Integration tests for update_check.py cache persistence."""

    def test_write_and_read_cache(self, tmp_path: Path) -> None:
        from hf_cli.update_check import _read_cache, _write_cache

        cache_path = tmp_path / "cache.json"
        payload = {
            "checked_at": int(time.time()),
            "current_version": "1.0.0",
            "latest_version": "1.1.0",
        }
        _write_cache(payload, cache_path)
        result = _read_cache(cache_path)
        assert result == payload

    def test_read_cache_missing_file(self, tmp_path: Path) -> None:
        from hf_cli.update_check import _read_cache

        assert _read_cache(tmp_path / "nonexistent.json") is None

    def test_read_cache_invalid_json(self, tmp_path: Path) -> None:
        from hf_cli.update_check import _read_cache

        cache_path = tmp_path / "bad.json"
        cache_path.write_text("{not json!!!")
        assert _read_cache(cache_path) is None

    def test_read_cache_non_dict(self, tmp_path: Path) -> None:
        from hf_cli.update_check import _read_cache

        cache_path = tmp_path / "array.json"
        cache_path.write_text("[1, 2, 3]")
        assert _read_cache(cache_path) is None

    def test_write_cache_creates_parent_dirs(self, tmp_path: Path) -> None:
        from hf_cli.update_check import _write_cache

        cache_path = tmp_path / "nested" / "dir" / "cache.json"
        _write_cache({"key": "value"}, cache_path)
        assert cache_path.exists()

    def test_load_cached_update_result_roundtrip(self, tmp_path: Path) -> None:
        from hf_cli.update_check import _write_cache, load_cached_update_result

        cache_path = tmp_path / "cache.json"
        _write_cache(
            {
                "checked_at": int(time.time()),
                "current_version": "1.0.0",
                "latest_version": "1.2.0",
            },
            cache_path,
        )
        result = load_cached_update_result("1.0.0", cache_path)
        assert result is not None
        assert result.current_version == "1.0.0"
        assert result.latest_version == "1.2.0"
        assert result.update_available is True

    def test_load_cached_result_no_update(self, tmp_path: Path) -> None:
        from hf_cli.update_check import _write_cache, load_cached_update_result

        cache_path = tmp_path / "cache.json"
        _write_cache(
            {
                "checked_at": int(time.time()),
                "current_version": "2.0.0",
                "latest_version": "1.0.0",
            },
            cache_path,
        )
        result = load_cached_update_result("2.0.0", cache_path)
        assert result is not None
        assert result.update_available is False

    def test_load_cached_result_missing_file(self, tmp_path: Path) -> None:
        from hf_cli.update_check import load_cached_update_result

        assert load_cached_update_result("1.0.0", tmp_path / "nope.json") is None

    def test_cached_check_uses_fresh_cache(self, tmp_path: Path) -> None:
        """check_for_updates_cached returns cached result when fresh."""
        from hf_cli.update_check import _write_cache, check_for_updates_cached

        cache_path = tmp_path / "cache.json"
        _write_cache(
            {
                "checked_at": int(time.time()),
                "current_version": "0.0.0-test",
                "latest_version": "99.0.0",
            },
            cache_path,
        )
        with patch("hf_cli.update_check.get_app_version", return_value="0.0.0-test"):
            result = check_for_updates_cached(path=cache_path, max_age_seconds=3600)
        assert result.latest_version == "99.0.0"
        assert result.update_available is True

    def test_cached_check_stale_cache_triggers_network(self, tmp_path: Path) -> None:
        """check_for_updates_cached fetches from network when cache is stale."""
        from hf_cli.update_check import _write_cache, check_for_updates_cached

        cache_path = tmp_path / "cache.json"
        _write_cache(
            {
                "checked_at": int(time.time()) - 99999,
                "current_version": "0.0.0-test",
                "latest_version": "1.0.0",
            },
            cache_path,
        )
        with (
            patch("hf_cli.update_check.get_app_version", return_value="0.0.0-test"),
            patch(
                "hf_cli.update_check._fetch_latest_pypi_version",
                return_value="2.0.0",
            ),
        ):
            result = check_for_updates_cached(path=cache_path, max_age_seconds=1)
        assert result.latest_version == "2.0.0"


# ---------------------------------------------------------------------------
# hf_cli/update_check.py — version comparison helpers
# ---------------------------------------------------------------------------


class TestVersionComparison:
    """Integration tests for version key parsing and comparison."""

    def test_version_key_basic(self) -> None:
        from hf_cli.update_check import _version_key

        assert _version_key("1.2.3") == (1, 2, 3)

    def test_version_key_single(self) -> None:
        from hf_cli.update_check import _version_key

        assert _version_key("5") == (5,)

    def test_version_key_with_prerelease(self) -> None:
        from hf_cli.update_check import _version_key

        # "1.2.3rc1" -> should extract numeric parts
        key = _version_key("1.2.3rc1")
        assert key[:2] == (1, 2)

    def test_version_key_all_alpha(self) -> None:
        from hf_cli.update_check import _version_key

        assert _version_key("alpha") == ()

    def test_is_newer_basic(self) -> None:
        from hf_cli.update_check import _is_newer

        assert _is_newer("2.0.0", "1.0.0") is True
        assert _is_newer("1.0.0", "2.0.0") is False
        assert _is_newer("1.0.0", "1.0.0") is False

    def test_is_newer_patch(self) -> None:
        from hf_cli.update_check import _is_newer

        assert _is_newer("1.0.1", "1.0.0") is True

    def test_is_newer_fallback_for_non_numeric(self) -> None:
        from hf_cli.update_check import _is_newer

        # When both keys are empty, falls back to string inequality
        assert _is_newer("alpha", "beta") is True  # "alpha" != "beta"
        assert _is_newer("same", "same") is False


# ---------------------------------------------------------------------------
# hf_cli/update_check.py — live check with mocked network
# ---------------------------------------------------------------------------


class TestCheckForUpdates:
    """Integration tests for check_for_updates with mocked PyPI."""

    def test_network_error_returns_gracefully(self) -> None:
        from hf_cli.update_check import check_for_updates

        with (
            patch("hf_cli.update_check.get_app_version", return_value="1.0.0"),
            patch(
                "hf_cli.update_check._fetch_latest_pypi_version",
                side_effect=OSError("network down"),
            ),
        ):
            result = check_for_updates()
        assert result.error is not None
        assert result.latest_version is None
        assert result.update_available is False

    def test_successful_check(self) -> None:
        from hf_cli.update_check import check_for_updates

        with (
            patch("hf_cli.update_check.get_app_version", return_value="1.0.0"),
            patch(
                "hf_cli.update_check._fetch_latest_pypi_version",
                return_value="2.0.0",
            ),
        ):
            result = check_for_updates()
        assert result.error is None
        assert result.latest_version == "2.0.0"
        assert result.update_available is True


# ---------------------------------------------------------------------------
# dashboard.py — FastAPI WebSocket integration
# ---------------------------------------------------------------------------


class TestDashboardHttp:
    """Integration tests for the dashboard HTTP endpoints."""

    def test_stats_endpoint(self, tmp_path: Path) -> None:
        """GET /api/stats returns a JSON response."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from events import EventBus
        from state import StateTracker
        from tests.helpers import ConfigFactory, make_dashboard_router

        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
        )
        event_bus = EventBus()
        state = StateTracker(tmp_path / "state.json")

        router, _pr = make_dashboard_router(config, event_bus, state, tmp_path)
        app = FastAPI()
        app.include_router(router)

        with TestClient(app) as client:
            resp = client.get("/api/stats")
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, dict)

    def test_state_endpoint(self, tmp_path: Path) -> None:
        """GET /api/state returns the state tracker data."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from events import EventBus
        from state import StateTracker
        from tests.helpers import ConfigFactory, make_dashboard_router

        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
        )
        event_bus = EventBus()
        state = StateTracker(tmp_path / "state.json")
        state.mark_issue(42, "planned")

        router, _pr = make_dashboard_router(config, event_bus, state, tmp_path)
        app = FastAPI()
        app.include_router(router)

        with TestClient(app) as client:
            resp = client.get("/api/state")
            assert resp.status_code == 200
            data = resp.json()
            assert data["processed_issues"]["42"] == "planned"

    def test_event_history_endpoint(self, tmp_path: Path) -> None:
        """GET /api/events returns event history as a list."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from events import EventBus
        from state import StateTracker
        from tests.helpers import ConfigFactory, make_dashboard_router

        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
        )
        event_bus = EventBus()
        state = StateTracker(tmp_path / "state.json")

        router, _pr = make_dashboard_router(config, event_bus, state, tmp_path)
        app = FastAPI()
        app.include_router(router)

        with TestClient(app) as client:
            resp = client.get("/api/events")
            assert resp.status_code == 200
            events = resp.json()
            assert isinstance(events, list)


# ---------------------------------------------------------------------------
# hf_cli/supervisor_service.py — TCP port and slug helpers
# ---------------------------------------------------------------------------


class TestSupervisorHelpers:
    """Integration tests for supervisor_service utility functions."""

    def test_find_free_port_returns_usable_port(self) -> None:
        from hf_cli.supervisor_service import _find_free_port

        port = _find_free_port()
        assert isinstance(port, int)
        assert port > 0

        # Verify the port is actually usable
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", port))

    def test_find_free_port_returns_different_ports(self) -> None:
        from hf_cli.supervisor_service import _find_free_port

        ports = {_find_free_port() for _ in range(5)}
        # Nearly all should differ; allow at most one collision in case of rapid reuse
        assert len(ports) >= 4

    def test_slug_for_log_filename_sanitizes(self) -> None:
        from hf_cli.supervisor_service import _slug_for_log_filename

        assert _slug_for_log_filename("my-org/my-repo") == "my-org-my-repo"
        assert _slug_for_log_filename("a/b\\c") == "a-b-c"
        assert _slug_for_log_filename("hello world!@#") == "hello-world"
        assert _slug_for_log_filename("") == "repo"

    def test_slug_for_log_filename_strips_leading_dot(self) -> None:
        from hf_cli.supervisor_service import _slug_for_log_filename

        result = _slug_for_log_filename(".hidden")
        assert not result.startswith(".")

    def test_slug_for_repo(self) -> None:
        from hf_cli.supervisor_service import _slug_for_repo

        assert _slug_for_repo(Path("/home/user/my-project")) == "my-project"
        assert _slug_for_repo(Path("/repos/hello world")) == "hello-world"


# ---------------------------------------------------------------------------
# hf_cli/supervisor_service.py — TCP handler integration
# ---------------------------------------------------------------------------


class TestSupervisorTcpHandler:
    """Integration tests for the supervisor TCP request handler."""

    @pytest.mark.asyncio
    async def test_ping_action(self) -> None:
        from hf_cli.supervisor_service import _handle

        reader = asyncio.StreamReader()
        reader.feed_data(json.dumps({"action": "ping"}).encode() + b"\n")
        reader.feed_eof()

        writer = AsyncMock()
        written_data = bytearray()

        def capture_write(data: bytes) -> None:
            written_data.extend(data)

        writer.write = capture_write
        writer.drain = AsyncMock()
        writer.close = MagicMock()
        writer.wait_closed = AsyncMock()

        await _handle(reader, writer)

        response = json.loads(written_data.decode().strip())
        assert response["status"] == "ok"
        assert writer.close.called
        assert writer.wait_closed.called

    @pytest.mark.asyncio
    async def test_unknown_action(self) -> None:
        from hf_cli.supervisor_service import _handle

        reader = asyncio.StreamReader()
        reader.feed_data(json.dumps({"action": "nonexistent"}).encode() + b"\n")
        reader.feed_eof()

        writer = AsyncMock()
        written_data = bytearray()

        def capture_write(data: bytes) -> None:
            written_data.extend(data)

        writer.write = capture_write
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
    async def test_empty_request(self) -> None:
        from hf_cli.supervisor_service import _handle

        reader = asyncio.StreamReader()
        reader.feed_data(b"")
        reader.feed_eof()

        writer = AsyncMock()
        writer.close = MagicMock()
        writer.wait_closed = AsyncMock()

        await _handle(reader, writer)
        writer.close.assert_called_once()
        writer.wait_closed.assert_called_once()


# ---------------------------------------------------------------------------
# dashboard.py — _auto_start_supervisor_enabled
# ---------------------------------------------------------------------------


class TestAutoStartSupervisor:
    """Integration tests for _auto_start_supervisor_enabled env var parsing."""

    def test_defaults_to_true(self) -> None:
        from dashboard import _auto_start_supervisor_enabled

        with patch.dict("os.environ", {}, clear=True):
            assert _auto_start_supervisor_enabled() is True

    def test_truthy_values(self) -> None:
        from dashboard import _auto_start_supervisor_enabled

        for val in ("1", "true", "yes", "on", "True", "YES"):
            with patch.dict(
                "os.environ",
                {"HYDRAFLOW_AUTO_START_SUPERVISOR": val},
                clear=True,
            ):
                assert _auto_start_supervisor_enabled() is True, f"Failed for {val!r}"

    def test_falsy_values(self) -> None:
        from dashboard import _auto_start_supervisor_enabled

        for val in ("0", "false", "no", "off", "False", "NO"):
            with patch.dict(
                "os.environ",
                {"HYDRAFLOW_AUTO_START_SUPERVISOR": val},
                clear=True,
            ):
                assert _auto_start_supervisor_enabled() is False, f"Failed for {val!r}"

    def test_legacy_env_var(self) -> None:
        from dashboard import _auto_start_supervisor_enabled

        with patch.dict(
            "os.environ",
            {"HF_AUTO_START_SUPERVISOR": "0"},
            clear=True,
        ):
            assert _auto_start_supervisor_enabled() is False

    def test_invalid_value_defaults_to_true(self) -> None:
        from dashboard import _auto_start_supervisor_enabled

        with patch.dict(
            "os.environ",
            {"HYDRAFLOW_AUTO_START_SUPERVISOR": "maybe"},
            clear=True,
        ):
            assert _auto_start_supervisor_enabled() is True
