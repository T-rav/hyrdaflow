"""Integration tests that exercise HydraFlow's filesystem-heavy components."""

from __future__ import annotations

import logging
import stat
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import worktree as worktree_module
from base_runner import BaseRunner
from context_cache import ContextSectionCache
from events import EventBus
from file_util import atomic_write
from manifest import ProjectManifestManager
from memory import load_memory_digest
from state import StateTracker
from tests.helpers import ConfigFactory
from worktree import WorktreeManager


class DummyRunner(BaseRunner):
    """Minimal BaseRunner subclass for exercising transcript persistence."""

    _log = logging.getLogger("tests.integration.fileio")


def _make_config(tmp_path: Path, **overrides):
    """Create a HydraFlowConfig rooted at *tmp_path* with optional overrides."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    worktree_base = tmp_path / "worktrees"
    worktree_base.mkdir()
    params: dict[str, Any] = {"repo_root": repo_root, "worktree_base": worktree_base}
    params.update(overrides)
    return ConfigFactory.create(**params)


def test_atomic_write_handles_concurrent_writers(tmp_path: Path) -> None:
    target = tmp_path / "state.json"
    payloads = [f"payload-{idx}\n" * 200 for idx in range(6)]
    barrier = threading.Barrier(len(payloads))
    errors: list[BaseException] = []

    def writer(data: str) -> None:
        try:
            barrier.wait(timeout=2)
        except threading.BrokenBarrierError:
            return
        try:
            atomic_write(target, data)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=len(payloads)) as executor:
        for payload in payloads:
            executor.submit(writer, payload)

    assert not errors, f"atomic_write raised: {errors}"
    written = target.read_text()
    assert written in payloads


def test_atomic_write_raises_on_readonly_directory(readonly_dir: Path) -> None:
    target = readonly_dir / "blocked.txt"
    with pytest.raises(OSError):
        atomic_write(target, "cannot write here")


def test_state_tracker_round_trip_and_corrupt_recovery(
    state_tracker_factory,
) -> None:
    tracker: StateTracker = state_tracker_factory()
    tracker.set_worktree(17, "/tmp/worktree-17")
    tracker.mark_issue(17, "in-progress")

    reloaded = StateTracker(tracker._path)  # noqa: SLF001
    assert reloaded.get_active_worktrees() == {17: "/tmp/worktree-17"}
    assert reloaded._data.processed_issues["17"] == "in-progress"  # noqa: SLF001

    tracker._path.write_text('{"processed_issues": {"17": "half')  # noqa: SLF001
    recovered = StateTracker(tracker._path)  # noqa: SLF001
    assert recovered.get_active_worktrees() == {}
    assert recovered._data.processed_issues == {}  # noqa: SLF001


def test_context_section_cache_persists_and_invalidates(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    cache = ContextSectionCache(config)
    source = config.repo_root / "manifest.md"
    source.write_text("first")
    calls: list[str] = []

    def loader(_) -> str:
        calls.append("called")
        return source.read_text()

    content, hit = cache.get_or_load(key="manifest", source_path=source, loader=loader)
    assert content == "first"
    assert hit is False
    assert len(calls) == 1

    content, hit = cache.get_or_load(key="manifest", source_path=source, loader=loader)
    assert content == "first"
    assert hit is True
    assert len(calls) == 1

    source.write_text("second")
    content, hit = cache.get_or_load(key="manifest", source_path=source, loader=loader)
    assert content == "second"
    assert hit is False
    assert len(calls) == 2


def test_manifest_manager_write_and_refresh(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    manager = ProjectManifestManager(config)
    digest = manager.write("# manifest\n")
    assert manager.manifest_path.read_text() == "# manifest\n"
    assert manager.needs_refresh(digest) is False
    manager.manifest_path.write_text("# manifest\nextra\n")
    assert manager.needs_refresh(digest) is True


def test_load_memory_digest_truncates_large_files(tmp_path: Path) -> None:
    config = _make_config(tmp_path, max_memory_prompt_chars=512)
    digest_path = config.data_path("memory", "digest.md")
    digest_path.parent.mkdir(parents=True, exist_ok=True)
    digest_path.write_text("x" * 1200)
    result = load_memory_digest(config)
    assert result.endswith("\n\n\u2026(truncated)")
    assert result.startswith("x")
    assert len(result) == config.max_memory_prompt_chars + len("\n\n\u2026(truncated)")


def test_worktree_env_setup_symlinks_and_copies(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    repo_root = config.repo_root
    wt_path = tmp_path / "wt-host"
    wt_path.mkdir()

    env_src = repo_root / ".env"
    env_src.write_text("TOKEN=123")
    settings_src = repo_root / ".claude"
    settings_src.mkdir(parents=True, exist_ok=True)
    settings_file = settings_src / "settings.local.json"
    settings_file.write_text('{"foo": "bar"}')
    node_modules_src = repo_root / "ui" / "node_modules"
    node_modules_src.mkdir(parents=True, exist_ok=True)
    (node_modules_src / "package.json").write_text("{}")

    manager = WorktreeManager(config)
    manager._setup_env(wt_path)

    env_dst = wt_path / ".env"
    assert env_dst.is_symlink()
    assert env_dst.resolve() == env_src.resolve()

    settings_dst = wt_path / ".claude" / "settings.local.json"
    assert settings_dst.read_text() == settings_file.read_text()

    node_modules_dst = wt_path / "ui" / "node_modules"
    assert node_modules_dst.is_symlink()
    assert node_modules_dst.resolve() == node_modules_src.resolve()


def test_worktree_env_setup_skips_missing_sources(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    wt_path = tmp_path / "wt-missing"
    wt_path.mkdir()
    manager = WorktreeManager(config)
    manager._setup_env(wt_path)
    assert not (wt_path / ".env").exists()
    assert not (wt_path / ".claude").exists()
    assert not (wt_path / "ui" / "node_modules").exists()


def test_worktree_env_setup_docker_copies_and_updates_gitignore(tmp_path: Path) -> None:
    config = _make_config(tmp_path, execution_mode="docker")
    repo_root = config.repo_root
    wt_path = tmp_path / "wt-docker"
    wt_path.mkdir()

    env_src = repo_root / ".env"
    env_src.write_text("TOKEN=abc")
    settings_src = repo_root / ".claude"
    settings_src.mkdir(parents=True, exist_ok=True)
    settings = settings_src / "settings.local.json"
    settings.write_text("{}")
    node_modules_src = repo_root / "ui" / "node_modules"
    node_modules_src.mkdir(parents=True, exist_ok=True)
    (node_modules_src / "artifact.txt").write_text("node-cache")

    manager = WorktreeManager(config)
    manager._setup_env(wt_path)

    env_dst = wt_path / ".env"
    assert env_dst.is_file()
    assert not env_dst.is_symlink()
    assert env_dst.read_text() == "TOKEN=abc"

    node_modules_dst = wt_path / "ui" / "node_modules"
    assert node_modules_dst.is_dir()
    assert not node_modules_dst.is_symlink()
    assert (node_modules_dst / "artifact.txt").read_text() == "node-cache"

    gitignore = wt_path / ".gitignore"
    gitignore_lines = [ln.strip() for ln in gitignore.read_text().splitlines()]
    assert ".env" in gitignore_lines


@pytest.mark.asyncio
async def test_install_hooks_docker_copies_hooks(monkeypatch, tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    repo_root = config.repo_root
    githooks = repo_root / ".githooks"
    githooks.mkdir()
    hook_src = githooks / "pre-commit"
    hook_src.write_text("#!/bin/sh\necho ok\n")
    wt_path = tmp_path / "wt-hooks"
    wt_path.mkdir()
    hooks_dir = tmp_path / "git-hooks"

    monkeypatch.setattr(
        worktree_module,
        "run_subprocess",
        AsyncMock(return_value=str(hooks_dir)),
    )

    manager = WorktreeManager(config)
    await manager._install_hooks_docker(wt_path)

    hook_dst = hooks_dir / "pre-commit"
    assert hook_dst.read_text() == hook_src.read_text()
    mode = hook_dst.stat().st_mode
    assert mode & stat.S_IXUSR
    assert mode & stat.S_IXGRP
    assert mode & stat.S_IXOTH


def test_base_runner_save_transcript_creates_logs(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    runner = DummyRunner(config=config, event_bus=EventBus(), runner=MagicMock())
    runner._save_transcript("implement", 42, "hello world")
    log_file = config.log_dir / "implement-42.txt"
    assert log_file.read_text() == "hello world"


def test_base_runner_warns_when_log_dir_unwritable(
    tmp_path: Path, readonly_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    config = _make_config(tmp_path)
    object.__setattr__(config, "data_root", readonly_dir)
    runner = DummyRunner(config=config, event_bus=EventBus(), runner=MagicMock())
    with caplog.at_level(logging.WARNING):
        runner._save_transcript("implement", 7, "body")
    assert "Could not save transcript" in caplog.text
