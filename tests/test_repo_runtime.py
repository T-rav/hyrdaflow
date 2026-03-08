"""Tests for repo_runtime.py — RepoRuntime and RepoRuntimeRegistry."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models import RepoRuntimeInfo
from repo_runtime import RepoRuntime, RepoRuntimeRegistry
from tests.helpers import ConfigFactory


class TestRepoRuntimeInfo:
    def test_runtime_info_has_expected_defaults(self):
        info = RepoRuntimeInfo(slug="owner-repo")
        assert info.slug == "owner-repo"
        assert info.running is False
        assert info.session_id is None
        assert info.uptime_seconds == 0.0

    def test_with_values(self):
        info = RepoRuntimeInfo(
            slug="org-proj",
            repo="org/proj",
            running=True,
            session_id="sess-1",
            uptime_seconds=123.4,
        )
        assert info.running is True
        assert info.session_id == "sess-1"


class TestRepoRuntime:
    def test_slug_from_repo(self, tmp_path):
        config = ConfigFactory.create(repo="acme/widgets", repo_root=tmp_path)
        with (
            patch("repo_runtime.EventLog"),
            patch("repo_runtime.EventBus"),
            patch("repo_runtime.StateTracker"),
            patch("repo_runtime.HydraFlowOrchestrator"),
        ):
            runtime = RepoRuntime(config)
        assert runtime.slug == "acme-widgets"

    def test_slug_fallback_to_dir_name(self, tmp_path):
        config = ConfigFactory.create(repo="", repo_root=tmp_path)
        with (
            patch("repo_runtime.EventLog"),
            patch("repo_runtime.EventBus"),
            patch("repo_runtime.StateTracker"),
            patch("repo_runtime.HydraFlowOrchestrator"),
        ):
            runtime = RepoRuntime(config)
        assert runtime.slug == tmp_path.name

    def test_properties_expose_internals(self, tmp_path):
        config = ConfigFactory.create(repo_root=tmp_path)
        with (
            patch("repo_runtime.EventLog"),
            patch("repo_runtime.EventBus") as mock_bus_cls,
            patch("repo_runtime.StateTracker") as mock_state_cls,
            patch("repo_runtime.HydraFlowOrchestrator") as mock_orch_cls,
        ):
            runtime = RepoRuntime(config)
        assert runtime.config is config
        assert runtime.event_bus is mock_bus_cls.return_value
        assert runtime.state is mock_state_cls.return_value
        assert runtime.orchestrator is mock_orch_cls.return_value

    def test_running_delegates_to_orchestrator(self, tmp_path):
        config = ConfigFactory.create(repo_root=tmp_path)
        with (
            patch("repo_runtime.EventLog"),
            patch("repo_runtime.EventBus"),
            patch("repo_runtime.StateTracker"),
            patch("repo_runtime.HydraFlowOrchestrator") as mock_orch_cls,
        ):
            mock_orch_cls.return_value.running = True
            runtime = RepoRuntime(config)
        assert runtime.running is True

    @pytest.mark.asyncio
    async def test_create_initializes_event_log(self, tmp_path):
        config = ConfigFactory.create(repo_root=tmp_path)
        mock_bus = MagicMock()
        mock_bus.rotate_log = AsyncMock()
        mock_bus.load_history_from_disk = AsyncMock()
        with (
            patch("repo_runtime.EventLog"),
            patch("repo_runtime.EventBus", return_value=mock_bus),
            patch("repo_runtime.StateTracker"),
            patch("repo_runtime.HydraFlowOrchestrator"),
        ):
            runtime = await RepoRuntime.create(config)
        mock_bus.rotate_log.assert_awaited_once()
        mock_bus.load_history_from_disk.assert_awaited_once()
        assert runtime.slug

    @pytest.mark.asyncio
    async def test_start_creates_background_task(self, tmp_path):
        config = ConfigFactory.create(repo_root=tmp_path)
        mock_orch = MagicMock()
        mock_orch.run = AsyncMock()
        mock_orch.running = False
        with (
            patch("repo_runtime.EventLog"),
            patch("repo_runtime.EventBus"),
            patch("repo_runtime.StateTracker"),
            patch("repo_runtime.HydraFlowOrchestrator", return_value=mock_orch),
        ):
            runtime = RepoRuntime(config)
        await runtime.start()
        assert runtime._task is not None
        # Let the event loop tick so the task runs
        await asyncio.sleep(0)
        mock_orch.run.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stop_stops_orchestrator(self, tmp_path):
        config = ConfigFactory.create(repo_root=tmp_path)
        mock_orch = MagicMock()
        mock_orch.stop = AsyncMock()
        mock_orch.running = False
        with (
            patch("repo_runtime.EventLog"),
            patch("repo_runtime.EventBus"),
            patch("repo_runtime.StateTracker"),
            patch("repo_runtime.HydraFlowOrchestrator", return_value=mock_orch),
        ):
            runtime = RepoRuntime(config)
        await runtime.stop()
        mock_orch.stop.assert_awaited_once()

    def test_repo_runtime_repr_contains_slug(self, tmp_path):
        config = ConfigFactory.create(repo="org/proj", repo_root=tmp_path)
        with (
            patch("repo_runtime.EventLog"),
            patch("repo_runtime.EventBus"),
            patch("repo_runtime.StateTracker"),
            patch("repo_runtime.HydraFlowOrchestrator") as mock_orch_cls,
        ):
            mock_orch_cls.return_value.running = False
            runtime = RepoRuntime(config)
        r = repr(runtime)
        assert "org-proj" in r
        assert "stopped" in r


class TestRepoRuntimeRegistry:
    @pytest.mark.asyncio
    async def test_register_and_get(self, tmp_path):
        config = ConfigFactory.create(repo="org/alpha", repo_root=tmp_path)
        registry = RepoRuntimeRegistry()
        mock_bus = MagicMock()
        mock_bus.rotate_log = AsyncMock()
        mock_bus.load_history_from_disk = AsyncMock()
        with (
            patch("repo_runtime.EventLog"),
            patch("repo_runtime.EventBus", return_value=mock_bus),
            patch("repo_runtime.StateTracker"),
            patch("repo_runtime.HydraFlowOrchestrator"),
        ):
            runtime = await registry.register(config)
        assert registry.get("org-alpha") is runtime
        assert "org-alpha" in registry
        assert len(registry) == 1
        assert registry.slugs == ["org-alpha"]

    @pytest.mark.asyncio
    async def test_register_duplicate_raises(self, tmp_path):
        config = ConfigFactory.create(repo="org/beta", repo_root=tmp_path)
        registry = RepoRuntimeRegistry()
        mock_bus = MagicMock()
        mock_bus.rotate_log = AsyncMock()
        mock_bus.load_history_from_disk = AsyncMock()
        with (
            patch("repo_runtime.EventLog"),
            patch("repo_runtime.EventBus", return_value=mock_bus),
            patch("repo_runtime.StateTracker"),
            patch("repo_runtime.HydraFlowOrchestrator"),
        ):
            await registry.register(config)
            with pytest.raises(ValueError, match="already registered"):
                await registry.register(config)

    @pytest.mark.asyncio
    async def test_remove_deregisters_and_stops_runtime(self, tmp_path):
        config = ConfigFactory.create(repo="org/gamma", repo_root=tmp_path)
        registry = RepoRuntimeRegistry()
        mock_bus = MagicMock()
        mock_bus.rotate_log = AsyncMock()
        mock_bus.load_history_from_disk = AsyncMock()
        with (
            patch("repo_runtime.EventLog"),
            patch("repo_runtime.EventBus", return_value=mock_bus),
            patch("repo_runtime.StateTracker"),
            patch("repo_runtime.HydraFlowOrchestrator"),
        ):
            await registry.register(config)
        removed = registry.remove("org-gamma")
        assert removed is not None
        assert registry.get("org-gamma") is None
        assert len(registry) == 0

    @pytest.mark.asyncio
    async def test_stop_all(self, tmp_path):
        registry = RepoRuntimeRegistry()
        configs = [
            ConfigFactory.create(repo=f"org/repo-{i}", repo_root=tmp_path / f"r{i}")
            for i in range(2)
        ]
        for c in configs:
            c.repo_root.mkdir(parents=True, exist_ok=True)
        runtimes = []

        def _make_orch(*_a, **_kw):
            m = MagicMock()
            m.stop = AsyncMock()
            m.running = False
            return m

        def _make_bus(*_a, **_kw):
            m = MagicMock()
            m.rotate_log = AsyncMock()
            m.load_history_from_disk = AsyncMock()
            return m

        with (
            patch("repo_runtime.EventLog"),
            patch("repo_runtime.EventBus", side_effect=_make_bus),
            patch("repo_runtime.StateTracker"),
            patch("repo_runtime.HydraFlowOrchestrator", side_effect=_make_orch),
        ):
            for c in configs:
                rt = await registry.register(c)
                runtimes.append(rt)
        await registry.stop_all()
        for rt in runtimes:
            rt.orchestrator.stop.assert_awaited_once()

    def test_get_missing_returns_none(self):
        registry = RepoRuntimeRegistry()
        assert registry.get("nonexistent") is None

    def test_remove_missing_returns_none(self):
        registry = RepoRuntimeRegistry()
        assert registry.remove("nonexistent") is None

    def test_registry_repr_shows_runtime_count(self):
        registry = RepoRuntimeRegistry()
        assert "runtimes=0" in repr(registry)

    @pytest.mark.asyncio
    async def test_two_runtimes_isolated(self, tmp_path):
        """Two runtimes for different repos have independent state."""
        registry = RepoRuntimeRegistry()
        config_a = ConfigFactory.create(repo="org/repo-a", repo_root=tmp_path / "a")
        config_b = ConfigFactory.create(repo="org/repo-b", repo_root=tmp_path / "b")
        config_a.repo_root.mkdir(parents=True, exist_ok=True)
        config_b.repo_root.mkdir(parents=True, exist_ok=True)

        def _make_bus(*_a, **_kw):
            m = MagicMock()
            m.rotate_log = AsyncMock()
            m.load_history_from_disk = AsyncMock()
            return m

        with (
            patch("repo_runtime.EventLog"),
            patch("repo_runtime.EventBus", side_effect=_make_bus),
            patch("repo_runtime.StateTracker"),
            patch(
                "repo_runtime.HydraFlowOrchestrator",
                side_effect=lambda *a, **kw: MagicMock(),
            ),
        ):
            rt_a = await registry.register(config_a)
            rt_b = await registry.register(config_b)
        assert rt_a.slug != rt_b.slug
        assert rt_a.orchestrator is not rt_b.orchestrator
        assert rt_a.event_bus is not rt_b.event_bus
        assert len(registry) == 2
