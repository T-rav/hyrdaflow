"""Tests for server.py — HydraFlow server entry point."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestServerMain:
    """Tests for server.main() entry point."""

    def test_main_loads_config_and_runs(self) -> None:
        """main() should load config, set up logging, and call asyncio.run."""
        mock_config = MagicMock()
        mock_config.dashboard_enabled = True

        with (
            patch("server.setup_logging") as mock_logging,
            patch("server.load_runtime_config", return_value=mock_config),
            patch("server.asyncio.run") as mock_run,
            patch.dict("os.environ", {}, clear=False),
        ):
            from server import main

            main()
            mock_logging.assert_called_once()
            mock_run.assert_called_once()

    def test_main_respects_verbose_env(self) -> None:
        """HYDRAFLOW_VERBOSE_LOGS=1 should set DEBUG level."""
        import logging

        mock_config = MagicMock()
        mock_config.dashboard_enabled = True

        with (
            patch("server.setup_logging") as mock_logging,
            patch("server.load_runtime_config", return_value=mock_config),
            patch("server.asyncio.run"),
            patch.dict("os.environ", {"HYDRAFLOW_VERBOSE_LOGS": "1"}, clear=False),
        ):
            from server import main

            main()
            call_kwargs = mock_logging.call_args
            assert call_kwargs[1]["level"] == logging.DEBUG


class TestRunDispatch:
    """Tests for _run() dispatch logic."""

    @pytest.mark.asyncio
    async def test_run_dispatches_to_dashboard_when_enabled(self) -> None:
        mock_config = MagicMock()
        mock_config.dashboard_enabled = True

        with patch("server._run_with_dashboard") as mock_dashboard:
            from server import _run

            await _run(mock_config)
            mock_dashboard.assert_awaited_once_with(mock_config)

    @pytest.mark.asyncio
    async def test_run_dispatches_to_headless_when_disabled(self) -> None:
        mock_config = MagicMock()
        mock_config.dashboard_enabled = False

        with patch("server._run_headless") as mock_headless:
            from server import _run

            await _run(mock_config)
            mock_headless.assert_awaited_once_with(mock_config)
