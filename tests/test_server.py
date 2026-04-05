"""Tests for server.py — HydraFlow server entry point."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# The dotenv package may not be installed in the test environment.  Ensure a
# mock module is always available so that ``from dotenv import load_dotenv``
# inside ``server.main()`` succeeds during tests.
if "dotenv" not in sys.modules:
    _fake_dotenv = types.ModuleType("dotenv")
    _fake_dotenv.load_dotenv = lambda *a, **kw: None  # type: ignore[attr-defined]
    sys.modules["dotenv"] = _fake_dotenv


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
            patch("server._init_sentry"),
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
            patch("server._init_sentry"),
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

        # Private-method patch: _run_with_dashboard is a heavyweight
        # server-starting function that binds ports and blocks forever;
        # extracting it as an injectable dependency would be over-engineering.
        with patch("server._run_with_dashboard") as mock_dashboard:
            from server import _run

            await _run(mock_config)
            mock_dashboard.assert_awaited_once_with(mock_config)

    @pytest.mark.asyncio
    async def test_run_dispatches_to_headless_when_disabled(self) -> None:
        mock_config = MagicMock()
        mock_config.dashboard_enabled = False

        # Private-method patch: _run_headless is a heavyweight
        # server-starting function that blocks forever; see comment above.
        with patch("server._run_headless") as mock_headless:
            from server import _run

            await _run(mock_config)
            mock_headless.assert_awaited_once_with(mock_config)


class TestDetectSubmoduleParent:
    def test_returns_parent_when_git_is_file(self, tmp_path: Path) -> None:
        parent = tmp_path / "parent"
        parent.mkdir()
        (parent / ".git").mkdir()

        submodule = parent / "hydraflow"
        submodule.mkdir()
        (submodule / ".git").write_text("gitdir: ../.git/modules/hydraflow\n")

        from server import _detect_submodule_parent

        assert _detect_submodule_parent(submodule) == parent

    def test_returns_none_when_git_is_dir(self, tmp_path: Path) -> None:
        repo = tmp_path / "standalone"
        repo.mkdir()
        (repo / ".git").mkdir()

        from server import _detect_submodule_parent

        assert _detect_submodule_parent(repo) is None

    def test_returns_none_when_parent_has_no_git(self, tmp_path: Path) -> None:
        submodule = tmp_path / "orphan"
        submodule.mkdir()
        (submodule / ".git").write_text("gitdir: somewhere\n")

        from server import _detect_submodule_parent

        assert _detect_submodule_parent(submodule) is None
