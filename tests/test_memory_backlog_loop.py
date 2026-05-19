"""Tests for MemoryBacklogLoop (ADR-0057)."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from memory_backlog_loop import MemoryBacklogLoop
from memory_backlog_mirror import load_mirror_entry


def _deps(stop: asyncio.Event, *, enabled: bool = True) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: enabled,
    )


def _write_mirror_entry(
    dir_: Path,
    slug: str,
    *,
    status: str = "pending",
    issue: int | None = None,
) -> Path:
    front = {
        "source": f"feedback_{slug.replace('-', '_')}.md",
        "name": f"Test rule {slug}",
        "description": f"desc for {slug}",
        "status": status,
        "issue": issue,
        "promoted_in": None,
        "wontfix_reason": None,
        "created": "2026-05-07",
    }
    p = dir_ / f"{slug}.md"
    p.write_text(
        f"---\n{yaml.safe_dump(front, sort_keys=False).rstrip()}\n---\n\n"
        f"Rule: do the thing.\n\n**Why:** because.\n"
    )
    return p


@pytest.fixture
def env(tmp_path: Path):
    """Build a (config, state, pr, dedup, mirror_dir) tuple for tests."""
    repo_root = tmp_path
    mirror_dir = repo_root / "docs" / "wiki" / "memory-feedback"
    mirror_dir.mkdir(parents=True)

    cfg = HydraFlowConfig(
        data_root=tmp_path / ".hydraflow",
        repo="hydra/hydraflow",
        repo_root=repo_root,
    )
    state = MagicMock()
    state.get_memory_backlog_attempts.return_value = 0
    state.inc_memory_backlog_attempts.return_value = 1
    pr = AsyncMock()
    pr.create_issue = AsyncMock(return_value=42)
    dedup = MagicMock()
    dedup.get.return_value = set()
    return cfg, state, pr, dedup, mirror_dir


def _make_loop(env, *, enabled: bool = True) -> MemoryBacklogLoop:
    cfg, state, pr, dedup, _ = env
    return MemoryBacklogLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        deps=_deps(asyncio.Event(), enabled=enabled),
    )


@pytest.mark.asyncio
async def test_kill_switch_returns_disabled(env) -> None:
    loop = _make_loop(env, enabled=False)
    result = await loop._do_work()
    assert result == {"status": "disabled"}
    _, _, pr, _, _ = env
    pr.create_issue.assert_not_called()


@pytest.mark.asyncio
async def test_no_mirror_dir_returns_quietly(env) -> None:
    _, _, pr, _, mirror_dir = env
    shutil.rmtree(mirror_dir)
    loop = _make_loop(env)
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    result = await loop._do_work()
    assert result["status"] == "no-mirror-dir"
    pr.create_issue.assert_not_called()


@pytest.mark.asyncio
async def test_pending_entry_files_one_issue_and_updates_frontmatter(
    env,
) -> None:
    _, state, pr, dedup, mirror_dir = env
    entry_path = _write_mirror_entry(mirror_dir, "feedback-alpha")
    pr.create_issue.return_value = 4242
    loop = _make_loop(env)
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    loop._commit_mirror_updates = AsyncMock(return_value=None)

    result = await loop._do_work()

    assert result == {
        "status": "ok",
        "filed": 1,
        "skipped": 0,
        "escalated": 0,
    }
    pr.create_issue.assert_awaited_once()
    after = load_mirror_entry(entry_path)
    assert after.status == "issue-open"
    assert after.issue == 4242
    state.inc_memory_backlog_attempts.assert_called_once_with(
        "memory_backlog:feedback-alpha"
    )
    dedup.set_all.assert_called()
    final_dedup = dedup.set_all.call_args.args[0]
    assert "memory_backlog:feedback-alpha" in final_dedup


@pytest.mark.asyncio
async def test_already_dedup_skips(env) -> None:
    _, _, pr, dedup, mirror_dir = env
    _write_mirror_entry(mirror_dir, "feedback-beta")
    dedup.get.return_value = {"memory_backlog:feedback-beta"}
    loop = _make_loop(env)
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)

    result = await loop._do_work()

    assert result == {
        "status": "ok",
        "filed": 0,
        "skipped": 1,
        "escalated": 0,
    }
    pr.create_issue.assert_not_called()


@pytest.mark.asyncio
async def test_third_attempt_escalates(env) -> None:
    _, state, pr, _, mirror_dir = env
    _write_mirror_entry(mirror_dir, "feedback-gamma")
    state.inc_memory_backlog_attempts.return_value = 3  # >= _MAX_ATTEMPTS
    pr.create_issue.return_value = 99
    loop = _make_loop(env)
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)

    result = await loop._do_work()

    assert result == {
        "status": "ok",
        "filed": 0,
        "skipped": 0,
        "escalated": 1,
    }
    pr.create_issue.assert_awaited_once()
    call_args = pr.create_issue.await_args
    assert "feedback-gamma" in call_args.args[0]
    labels = call_args.args[2]
    assert "hitl-escalation" in labels
    assert any("memory-backlog-stuck" in lab for lab in labels)


@pytest.mark.asyncio
async def test_wontfix_and_promoted_entries_skipped(env) -> None:
    """Loop only acts on `pending` entries — not wontfix/promoted/issue-open."""
    _, _, pr, _, mirror_dir = env
    _write_mirror_entry(mirror_dir, "fb-wontfix", status="wontfix")
    _write_mirror_entry(mirror_dir, "fb-promoted", status="promoted")
    _write_mirror_entry(mirror_dir, "fb-open", status="issue-open", issue=11)
    loop = _make_loop(env)
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)

    result = await loop._do_work()

    assert result == {
        "status": "ok",
        "filed": 0,
        "skipped": 0,
        "escalated": 0,
    }
    pr.create_issue.assert_not_called()


def test_default_interval_matches_config(env) -> None:
    cfg, _, _, _, _ = env
    loop = _make_loop(env)
    assert loop._get_default_interval() == cfg.memory_backlog_interval_seconds
    assert loop._get_default_interval() == 86_400  # 24h


@pytest.mark.asyncio
async def test_filing_commits_frontmatter_to_git(env) -> None:
    """The pending → issue-open frontmatter update lands as a git commit.

    Per ADR-0057, status transitions live in git history — not just on
    disk. Without the commit, frontmatter edits accumulate as unstaged
    modifications in the orchestrator's working tree.
    """
    cfg, _, pr, _, mirror_dir = env
    # Initialize a real git repo in tmp_path so the loop's git commands work.
    subprocess.run(["git", "init", "-q"], cwd=cfg.repo_root, check=True)
    # Stage + commit the mirror dir so subsequent updates are diffable.
    _write_mirror_entry(mirror_dir, "feedback-zeta")
    subprocess.run(["git", "add", "-A"], cwd=cfg.repo_root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=cfg.repo_root, check=True)
    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=cfg.repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    pr.create_issue.return_value = 4321
    loop = _make_loop(env)
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)

    await loop._do_work()

    head_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=cfg.repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert head_sha != base_sha, "loop did not create a commit"

    title = subprocess.run(
        ["git", "log", "-1", "--format=%s"],
        cwd=cfg.repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert "memory-backlog" in title
    assert "#4321" in title

    # Working tree should be clean — the frontmatter update is committed.
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=cfg.repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert status == "", f"unexpected dirty working tree: {status}"


@pytest.mark.asyncio
async def test_no_commit_when_nothing_filed(env) -> None:
    """Tick that filed zero issues should NOT make a git commit."""
    _, _, pr, dedup, mirror_dir = env
    _write_mirror_entry(mirror_dir, "feedback-already-open")
    dedup.get.return_value = {"memory_backlog:feedback-already-open"}  # already filed

    loop = _make_loop(env)
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    loop._commit_mirror_updates = AsyncMock(return_value=None)

    result = await loop._do_work()

    assert result["filed"] == 0
    pr.create_issue.assert_not_called()
    loop._commit_mirror_updates.assert_not_called()
