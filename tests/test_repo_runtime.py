"""Tests for repo_runtime.py — RepoRuntime and RepoRuntimeRegistry."""

from __future__ import annotations

import asyncio
import json
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


class TestRepoRuntimeRegistryPersistence:
    """Tests for repos.json persistence in RepoRuntimeRegistry."""

    def _runtime_patches(self):
        """Context manager stack for patching RepoRuntime dependencies."""

        def _make_bus(*_a, **_kw):
            m = MagicMock()
            m.rotate_log = AsyncMock()
            m.load_history_from_disk = AsyncMock()
            return m

        return (
            patch("repo_runtime.EventLog"),
            patch("repo_runtime.EventBus", side_effect=_make_bus),
            patch("repo_runtime.StateTracker"),
            patch("repo_runtime.HydraFlowOrchestrator"),
        )

    def test_init_with_data_root_sets_repos_file(self, tmp_path):
        registry = RepoRuntimeRegistry(data_root=tmp_path)
        assert registry._repos_file == tmp_path / "repos.json"

    def test_init_without_data_root(self):
        registry = RepoRuntimeRegistry()
        assert registry._repos_file is None

    @pytest.mark.asyncio
    async def test_register_saves_repos_json(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        registry = RepoRuntimeRegistry(data_root=data_dir)
        config = ConfigFactory.create(repo="org/alpha", repo_root=tmp_path / "alpha")

        p1, p2, p3, p4 = self._runtime_patches()
        with p1, p2, p3, p4:
            await registry.register(config)

        repos_file = data_dir / "repos.json"
        assert repos_file.exists()
        records = json.loads(repos_file.read_text())
        assert len(records) == 1
        assert records[0]["slug"] == "org-alpha"
        assert records[0]["repo"] == "org/alpha"

    @pytest.mark.asyncio
    async def test_remove_updates_repos_json(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        registry = RepoRuntimeRegistry(data_root=data_dir)
        config = ConfigFactory.create(repo="org/beta", repo_root=tmp_path / "beta")

        p1, p2, p3, p4 = self._runtime_patches()
        with p1, p2, p3, p4:
            await registry.register(config)

        registry.remove("org-beta")
        records = json.loads((data_dir / "repos.json").read_text())
        assert len(records) == 0

    def test_load_records_empty_when_no_file(self, tmp_path):
        registry = RepoRuntimeRegistry(data_root=tmp_path)
        assert registry._load_records() == []

    def test_load_records_reads_valid_json(self, tmp_path):
        repos_file = tmp_path / "repos.json"
        repos_file.write_text(
            json.dumps(
                [
                    {"slug": "org-x", "repo": "org/x", "repo_root": "/tmp/x"},
                ]
            )
        )
        registry = RepoRuntimeRegistry(data_root=tmp_path)
        records = registry._load_records()
        assert len(records) == 1
        assert records[0]["slug"] == "org-x"

    def test_load_records_handles_corrupt_json(self, tmp_path):
        repos_file = tmp_path / "repos.json"
        repos_file.write_text("{invalid json")
        registry = RepoRuntimeRegistry(data_root=tmp_path)
        assert registry._load_records() == []

    def test_load_records_skips_non_dict_entries(self, tmp_path):
        repos_file = tmp_path / "repos.json"
        repos_file.write_text(
            json.dumps(
                [
                    {"slug": "good", "repo": "org/good", "repo_root": "/tmp/good"},
                    "not-a-dict",
                    42,
                ]
            )
        )
        registry = RepoRuntimeRegistry(data_root=tmp_path)
        records = registry._load_records()
        assert len(records) == 1

    def test_load_records_no_data_root(self):
        registry = RepoRuntimeRegistry()
        assert registry._load_records() == []

    @pytest.mark.asyncio
    async def test_load_saved_restores_repos(self, tmp_path):
        repo_root = tmp_path / "myrepo"
        repo_root.mkdir()
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        repos_file = data_dir / "repos.json"
        repos_file.write_text(
            json.dumps(
                [
                    {
                        "slug": "org-myrepo",
                        "repo": "org/myrepo",
                        "repo_root": str(repo_root),
                    },
                ]
            )
        )

        base_config = ConfigFactory.create(repo="org/base", repo_root=tmp_path / "base")
        registry = RepoRuntimeRegistry(data_root=data_dir)

        p1, p2, p3, p4 = self._runtime_patches()
        with p1, p2, p3, p4:
            loaded = await registry.load_saved(base_config)

        assert loaded == 1
        assert "org-myrepo" in registry

    @pytest.mark.asyncio
    async def test_load_saved_skips_missing_repo_root(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        repos_file = data_dir / "repos.json"
        repos_file.write_text(
            json.dumps(
                [
                    {
                        "slug": "org-gone",
                        "repo": "org/gone",
                        "repo_root": "/nonexistent/path",
                    },
                ]
            )
        )
        base_config = ConfigFactory.create(repo="org/base", repo_root=tmp_path / "base")
        registry = RepoRuntimeRegistry(data_root=data_dir)
        loaded = await registry.load_saved(base_config)
        assert loaded == 0
        assert len(registry) == 0

    @pytest.mark.asyncio
    async def test_load_saved_skips_already_registered(self, tmp_path):
        repo_root = tmp_path / "dup"
        repo_root.mkdir()
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        repos_file = data_dir / "repos.json"
        repos_file.write_text(
            json.dumps(
                [
                    {"slug": "org-dup", "repo": "org/dup", "repo_root": str(repo_root)},
                ]
            )
        )

        config = ConfigFactory.create(repo="org/dup", repo_root=repo_root)
        registry = RepoRuntimeRegistry(data_root=data_dir)

        p1, p2, p3, p4 = self._runtime_patches()
        with p1, p2, p3, p4:
            await registry.register(config)
            loaded = await registry.load_saved(config)

        assert loaded == 0
        assert len(registry) == 1

    @pytest.mark.asyncio
    async def test_load_saved_skips_empty_repo_root(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        repos_file = data_dir / "repos.json"
        repos_file.write_text(
            json.dumps(
                [
                    {"slug": "bad", "repo": "org/bad", "repo_root": ""},
                ]
            )
        )
        base_config = ConfigFactory.create(repo="org/base", repo_root=tmp_path)
        registry = RepoRuntimeRegistry(data_root=data_dir)
        loaded = await registry.load_saved(base_config)
        assert loaded == 0

    def test_save_without_data_root_is_noop(self):
        registry = RepoRuntimeRegistry()
        registry._save()  # should not raise

    def test_save_creates_parent_dirs(self, tmp_path):
        nested = tmp_path / "a" / "b" / "c"
        registry = RepoRuntimeRegistry(data_root=nested)
        registry._save()
        assert (nested / "repos.json").exists()
