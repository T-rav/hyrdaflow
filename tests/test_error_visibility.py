"""Tests for issue #2401 — improved error visibility in dashboard, metrics, and crate modules."""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from events import EventBus

# ---------------------------------------------------------------------------
# _is_likely_disconnect helper
# ---------------------------------------------------------------------------


class TestIsLikelyDisconnect:
    """Tests for the _is_likely_disconnect helper in dashboard_routes."""

    def _call(self, exc: BaseException) -> bool:
        from dashboard_routes import _is_likely_disconnect

        return _is_likely_disconnect(exc)

    def test_connection_reset_is_disconnect(self) -> None:
        assert self._call(ConnectionResetError()) is True

    def test_connection_aborted_is_disconnect(self) -> None:
        assert self._call(ConnectionAbortedError()) is True

    def test_broken_pipe_is_disconnect(self) -> None:
        assert self._call(BrokenPipeError()) is True

    def test_value_error_is_not_disconnect(self) -> None:
        assert self._call(ValueError("oops")) is False

    def test_runtime_error_is_not_disconnect(self) -> None:
        assert self._call(RuntimeError("bug")) is False

    def test_type_name_websocket_disconnect(self) -> None:
        """Classes named WebSocketDisconnect are treated as disconnects."""

        class WebSocketDisconnect(Exception):
            pass

        assert self._call(WebSocketDisconnect()) is True

    def test_type_name_connection_closed_error(self) -> None:
        class ConnectionClosedError(Exception):
            pass

        assert self._call(ConnectionClosedError()) is True

    def test_type_name_connection_closed_ok(self) -> None:
        class ConnectionClosedOK(Exception):
            pass

        assert self._call(ConnectionClosedOK()) is True


# ---------------------------------------------------------------------------
# dashboard_routes: milestone fetch log level
# ---------------------------------------------------------------------------


class TestMilestoneFetchLogLevel:
    """Milestone fetch failure should log at WARNING, not DEBUG."""

    def test_source_uses_warning_not_debug(self) -> None:
        """Verify the except block uses logger.warning for milestone fetch."""
        import inspect

        import dashboard_routes

        source = inspect.getsource(dashboard_routes.create_router)
        # Find the milestone fetch handler
        idx = source.find("Failed to fetch milestones for crate titles")
        assert idx != -1, "Expected log message not found in create_router"
        # Check that the preceding logger call is .warning, not .debug
        context = source[max(0, idx - 80) : idx]
        assert "logger.warning" in context, (
            f"Expected logger.warning before milestone message, got: {context!r}"
        )


# ---------------------------------------------------------------------------
# dashboard_routes: HITL summary failure message
# ---------------------------------------------------------------------------


class TestHitlSummaryFailureMessage:
    """HITL summary failure should include the actual exception type."""

    def _make_router(self, config, event_bus, state, tmp_path):
        from dashboard_routes import create_router
        from pr_manager import PRManager

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

    @pytest.mark.asyncio
    async def test_hitl_summary_failure_includes_exception_type(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """_warm_hitl_summary records '{TypeName}: {message}' when an exception occurs."""
        import asyncio

        from dashboard_routes import create_router
        from models import HITLItem
        from pr_manager import PRManager

        # Enable the summarisation path so _warm_hitl_summary is triggered.
        config.transcript_summarization_enabled = True
        config.dry_run = False
        config.gh_token = "test-token"

        calls: list[tuple[int, str]] = []
        original_set = state.set_hitl_summary_failure

        def tracking_set(issue_number: int, message: str) -> None:
            calls.append((issue_number, message))
            return original_set(issue_number, message)

        state.set_hitl_summary_failure = tracking_set

        with patch("dashboard_routes.IssueFetcher") as mock_fetcher_cls:
            mock_fetcher = MagicMock()
            # Raise from fetch_issue_by_number so the exception propagates to
            # _warm_hitl_summary's except block (not caught inside _compute_hitl_summary).
            mock_fetcher.fetch_issue_by_number = AsyncMock(
                side_effect=RuntimeError("upstream API failed")
            )
            mock_fetcher_cls.return_value = mock_fetcher

            pr_mgr = PRManager(config, event_bus)
            hitl_item = HITLItem(issue=99, title="Fix CI failure", pr=111)
            pr_mgr.list_hitl_items = AsyncMock(return_value=[hitl_item])  # type: ignore[method-assign]

            router = create_router(
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

            get_hitl = None
            for route in router.routes:
                if (
                    hasattr(route, "path")
                    and route.path == "/api/hitl"
                    and hasattr(route, "endpoint")
                ):
                    get_hitl = route.endpoint
                    break

            assert get_hitl is not None
            await get_hitl()
            # Yield twice to ensure the background asyncio.create_task completes.
            await asyncio.sleep(0)
            await asyncio.sleep(0)

        assert len(calls) >= 1, "Expected set_hitl_summary_failure to be called"
        issue_num, message = calls[0]
        assert issue_num == 99
        assert message.startswith("RuntimeError:")
        assert "upstream API failed" in message


# ---------------------------------------------------------------------------
# dashboard_routes: history cache warm-up log level
# ---------------------------------------------------------------------------


class TestHistoryCacheWarmUpLogLevel:
    """History cache warm-up failure should log at WARNING."""

    def test_source_uses_warning_not_debug(self) -> None:
        """Verify the except block uses logger.warning for history cache warm-up."""
        import inspect

        import dashboard_routes

        source = inspect.getsource(dashboard_routes.create_router)
        idx = source.find("History cache warm-up failed")
        assert idx != -1, "Expected log message not found in create_router"
        context = source[max(0, idx - 80) : idx]
        assert "logger.warning" in context, (
            f"Expected logger.warning before cache warm-up message, got: {context!r}"
        )


# ---------------------------------------------------------------------------
# dashboard_routes: WebSocket disconnect vs bug differentiation
# ---------------------------------------------------------------------------


class TestWebSocketDisconnectDifferentiation:
    """WebSocket handlers should log ERROR for bugs and WARNING for disconnects."""

    def _make_router(self, config, event_bus, state, tmp_path):
        from dashboard_routes import create_router
        from pr_manager import PRManager

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

    @pytest.mark.asyncio
    async def test_websocket_history_replay_disconnect_logs_warning(
        self, config, event_bus, state, tmp_path, caplog
    ) -> None:
        """ConnectionResetError during history replay logs WARNING."""
        from events import HydraFlowEvent

        await event_bus.publish(
            HydraFlowEvent(type="system_alert", data={"test": True})
        )
        router = self._make_router(config, event_bus, state, tmp_path)

        endpoint = None
        for route in router.routes:
            if hasattr(route, "path") and route.path == "/ws":
                endpoint = route.endpoint
                break
        assert endpoint is not None

        mock_ws = AsyncMock()
        mock_ws.send_text = AsyncMock(side_effect=ConnectionResetError("gone"))

        q: asyncio.Queue = asyncio.Queue()
        q.get = AsyncMock(side_effect=Exception("should not reach"))  # type: ignore[method-assign]

        with (
            patch.object(event_bus, "subscription") as mock_sub,
            caplog.at_level(logging.WARNING, logger="hydraflow.dashboard"),
        ):
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=q)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_sub.return_value = mock_ctx
            await endpoint(mock_ws)

        assert "disconnect" in caplog.text.lower()
        assert "ERROR" not in caplog.text

    @pytest.mark.asyncio
    async def test_websocket_history_replay_bug_logs_error(
        self, config, event_bus, state, tmp_path, caplog
    ) -> None:
        """ValueError during history replay logs ERROR (likely bug)."""
        from events import HydraFlowEvent

        await event_bus.publish(
            HydraFlowEvent(type="system_alert", data={"test": True})
        )
        router = self._make_router(config, event_bus, state, tmp_path)

        endpoint = None
        for route in router.routes:
            if hasattr(route, "path") and route.path == "/ws":
                endpoint = route.endpoint
                break
        assert endpoint is not None

        mock_ws = AsyncMock()
        mock_ws.send_text = AsyncMock(side_effect=ValueError("unexpected"))

        q: asyncio.Queue = asyncio.Queue()
        q.get = AsyncMock(side_effect=Exception("should not reach"))  # type: ignore[method-assign]

        with (
            patch.object(event_bus, "subscription") as mock_sub,
            caplog.at_level(logging.DEBUG, logger="hydraflow.dashboard"),
        ):
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=q)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_sub.return_value = mock_ctx
            await endpoint(mock_ws)

        assert "error" in caplog.text.lower()

    @pytest.mark.asyncio
    async def test_websocket_live_stream_disconnect_logs_warning(
        self, config, event_bus, state, tmp_path, caplog
    ) -> None:
        """BrokenPipeError during live streaming logs WARNING."""
        router = self._make_router(config, event_bus, state, tmp_path)

        endpoint = None
        for route in router.routes:
            if hasattr(route, "path") and route.path == "/ws":
                endpoint = route.endpoint
                break
        assert endpoint is not None

        from events import HydraFlowEvent

        mock_ws = AsyncMock()
        event = HydraFlowEvent(type="system_alert", data={"x": 1})

        # Put an event in the queue; send_text will raise on the live stream send
        q2: asyncio.Queue = asyncio.Queue()
        await q2.put(event)

        mock_ws.send_text = AsyncMock(side_effect=BrokenPipeError("gone"))

        with (
            patch.object(event_bus, "subscription") as mock_sub,
            caplog.at_level(logging.WARNING, logger="hydraflow.dashboard"),
        ):
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=q2)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_sub.return_value = mock_ctx
            await endpoint(mock_ws)

        assert "disconnect" in caplog.text.lower()

    @pytest.mark.asyncio
    async def test_websocket_live_stream_bug_logs_error(
        self, config, event_bus, state, tmp_path, caplog
    ) -> None:
        """Non-disconnect exception during live streaming logs ERROR."""
        router = self._make_router(config, event_bus, state, tmp_path)

        endpoint = None
        for route in router.routes:
            if hasattr(route, "path") and route.path == "/ws":
                endpoint = route.endpoint
                break
        assert endpoint is not None

        from events import HydraFlowEvent

        mock_ws = AsyncMock()
        event = HydraFlowEvent(type="system_alert", data={"x": 1})

        q3: asyncio.Queue = asyncio.Queue()
        await q3.put(event)

        mock_ws.send_text = AsyncMock(
            side_effect=ValueError("unexpected serialization error")
        )

        with (
            patch.object(event_bus, "subscription") as mock_sub,
            caplog.at_level(logging.DEBUG, logger="hydraflow.dashboard"),
        ):
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=q3)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_sub.return_value = mock_ctx
            await endpoint(mock_ws)

        assert "error" in caplog.text.lower()
        assert "ERROR" in caplog.text


# ---------------------------------------------------------------------------
# metrics_manager: exc_info on warnings
# ---------------------------------------------------------------------------


class TestMetricsManagerExcInfo:
    """Metrics manager warnings should include exc_info=True."""

    def _make_manager(self, state, event_bus):
        from metrics_manager import MetricsManager

        config = MagicMock()
        config.repo = "test/repo"
        config.dry_run = False
        config.data_path = MagicMock(return_value="/tmp/test")

        prs = MagicMock()
        prs.get_label_counts = AsyncMock(side_effect=RuntimeError("API down"))
        prs.post_comment = AsyncMock()
        prs.create_issue = AsyncMock(return_value=42)

        mgr = MetricsManager(config, state, prs, event_bus)
        return mgr, prs

    @pytest.mark.asyncio
    async def test_label_count_failure_logs_with_exc_info(
        self, state, event_bus, caplog
    ) -> None:
        """get_label_counts failure should log with exc_info=True."""
        mgr, _ = self._make_manager(state, event_bus)

        with caplog.at_level(logging.WARNING, logger="hydraflow.metrics_manager"):
            await mgr._build_snapshot()

        assert "Could not fetch GitHub label counts" in caplog.text
        # exc_info=True means the traceback is included
        assert "RuntimeError" in caplog.text

    @pytest.mark.asyncio
    async def test_metrics_issue_search_failure_logs_with_exc_info(
        self, state, event_bus, caplog
    ) -> None:
        """Issue search failure should log with exc_info=True."""
        from metrics_manager import MetricsManager

        config = MagicMock()
        config.repo = "test/repo"
        config.dry_run = False
        config.data_path = MagicMock(return_value="/tmp/test")

        prs = MagicMock()
        prs.get_label_counts = AsyncMock(
            return_value={"open_by_label": {}, "total_closed": 0, "total_merged": 0}
        )
        prs.create_issue = AsyncMock(return_value=99)

        mgr = MetricsManager(config, state, prs, event_bus)

        # Ensure state returns None so the label search path is triggered
        with (
            patch.object(state, "get_metrics_issue_number", return_value=None),
            patch("issue_fetcher.IssueFetcher") as mock_fetcher_cls,
            caplog.at_level(logging.WARNING, logger="hydraflow.metrics_manager"),
        ):
            mock_fetcher = MagicMock()
            mock_fetcher.fetch_issues_by_labels = AsyncMock(
                side_effect=RuntimeError("search failed")
            )
            mock_fetcher_cls.return_value = mock_fetcher

            await mgr._ensure_metrics_issue()

        assert "Could not search for metrics issue by label" in caplog.text
        assert "RuntimeError" in caplog.text

    @pytest.mark.asyncio
    async def test_snapshot_post_failure_logs_warning(
        self, state, event_bus, caplog
    ) -> None:
        """post_comment failure should log WARNING with exc_info."""
        from metrics_manager import MetricsManager

        config = MagicMock()
        config.repo = "test/repo"
        config.dry_run = False
        config.data_path = MagicMock(return_value="/tmp/test")

        prs = MagicMock()
        prs.get_label_counts = AsyncMock(
            return_value={"open_by_label": {}, "total_closed": 0, "total_merged": 0}
        )
        prs.post_comment = AsyncMock(side_effect=RuntimeError("post failed"))
        prs.create_issue = AsyncMock(return_value=42)

        mgr = MetricsManager(config, state, prs, event_bus)
        state.record_issue_completed()

        with (
            patch.object(
                mgr, "_ensure_metrics_issue", new_callable=AsyncMock, return_value=42
            ),
            patch.object(mgr, "_save_to_local_cache"),
            caplog.at_level(logging.WARNING, logger="hydraflow.metrics_manager"),
        ):
            result = await mgr.sync()

        assert result["status"] == "cached_locally"
        assert result["reason"] == "post_failed"
        assert "Failed to post metrics snapshot" in caplog.text
        assert "RuntimeError" in caplog.text

    @pytest.mark.asyncio
    async def test_corrupt_json_comment_logs_warning(
        self, state, event_bus, caplog
    ) -> None:
        """Corrupt JSON in metrics comments should log WARNING with exc_info."""
        from metrics_manager import MetricsManager

        config = MagicMock()
        config.repo = "test/repo"
        config.dry_run = False
        config.data_path = MagicMock(return_value="/tmp/test")

        prs = MagicMock()
        mgr = MetricsManager(config, state, prs, event_bus)

        comments = [
            "```json\n{invalid json}\n```",
            "no json here",
        ]

        with (
            patch("issue_fetcher.IssueFetcher") as mock_fetcher_cls,
            caplog.at_level(logging.WARNING, logger="hydraflow.metrics_manager"),
        ):
            mock_fetcher = MagicMock()
            mock_fetcher.fetch_issue_comments = AsyncMock(return_value=comments)
            mock_fetcher_cls.return_value = mock_fetcher

            # Set state to return issue number so it doesn't short-circuit
            with patch.object(state, "get_metrics_issue_number", return_value=42):
                result = await mgr.fetch_history_from_issue()

        assert "Skipping corrupt metrics comment" in caplog.text
        assert len(result) == 0


# ---------------------------------------------------------------------------
# crate_manager: exc_info on warnings
# ---------------------------------------------------------------------------


class TestCrateManagerExcInfo:
    """Crate manager warnings should include exc_info=True."""

    def _make_manager(
        self, *, auto_crate: bool = False, active_crate: int | None = None
    ):
        from crate_manager import CrateManager
        from tests.helpers import ConfigFactory

        config = ConfigFactory.create()
        config.auto_crate = auto_crate

        st = MagicMock()
        st.get_active_crate_number.return_value = active_crate
        st.set_active_crate_number = MagicMock()

        pr_manager = AsyncMock()
        bus = EventBus()
        cm = CrateManager(config, st, pr_manager, bus)
        return cm, st, pr_manager, bus

    @pytest.mark.asyncio
    async def test_milestone_list_failure_logs_warning_with_exc_info(
        self, caplog
    ) -> None:
        """list_milestones failure in _next_crate_title logs WARNING with exc_info."""
        cm, _, pr_mgr, _ = self._make_manager()
        pr_mgr.list_milestones = AsyncMock(side_effect=RuntimeError("API down"))

        with caplog.at_level(logging.WARNING, logger="hydraflow.crate_manager"):
            title = await cm._next_crate_title()

        assert "Could not list milestones" in caplog.text
        assert "RuntimeError" in caplog.text
        # Should still return a valid title
        assert title  # non-empty

    @pytest.mark.asyncio
    async def test_issue_milestone_assign_failure_logs_with_exc_info(
        self, caplog
    ) -> None:
        """set_issue_milestone failure logs WARNING with exc_info."""
        from models import Crate
        from tests.conftest import TaskFactory

        cm, _, pr_mgr, _ = self._make_manager(auto_crate=True)
        pr_mgr.list_milestones = AsyncMock(return_value=[])
        pr_mgr.create_milestone = AsyncMock(
            return_value=Crate(number=1, title="test", open_issues=0, state="open")
        )
        pr_mgr.set_issue_milestone = AsyncMock(
            side_effect=RuntimeError("assign failed")
        )

        tasks = [TaskFactory.create(id=10)]

        with caplog.at_level(logging.WARNING, logger="hydraflow.crate_manager"):
            await cm.auto_package_if_needed(tasks)

        assert "Failed to assign issue" in caplog.text
        assert "RuntimeError" in caplog.text
