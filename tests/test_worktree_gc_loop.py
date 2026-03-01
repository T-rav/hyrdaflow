"""Tests for the WorktreeGCLoop background worker."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from events import EventType
from state import StateTracker
from tests.helpers import make_bg_loop_deps
from worktree_gc_loop import WorktreeGCLoop


def _make_loop(
    tmp_path: Path,
    *,
    enabled: bool = True,
    interval: int = 600,
    active_worktrees: dict[int, str] | None = None,
    active_issue_numbers: list[int] | None = None,
    hitl_causes: dict[int, str] | None = None,
) -> tuple[WorktreeGCLoop, StateTracker, asyncio.Event]:
    """Build a WorktreeGCLoop with test-friendly defaults."""
    deps = make_bg_loop_deps(tmp_path, enabled=enabled, worktree_gc_interval=interval)

    state = StateTracker(deps.config.state_file)
    for num, path in (active_worktrees or {}).items():
        state.set_worktree(num, path)
    if active_issue_numbers:
        state.set_active_issue_numbers(active_issue_numbers)
    for num, cause in (hitl_causes or {}).items():
        state.set_hitl_cause(num, cause)

    worktrees = MagicMock()
    worktrees.destroy = AsyncMock()

    prs = MagicMock()

    loop = WorktreeGCLoop(
        config=deps.config,
        worktrees=worktrees,
        prs=prs,
        state=state,
        event_bus=deps.bus,
        stop_event=deps.stop_event,
        status_cb=deps.status_cb,
        enabled_cb=deps.enabled_cb,
        sleep_fn=deps.sleep_fn,
        interval_cb=None,
    )
    # Stub out subprocess-calling methods by default so unit tests
    # don't hit the real filesystem/git.  Individual tests override
    # these when they want to verify prune/branch behaviour.
    loop._git_worktree_prune = AsyncMock()  # type: ignore[method-assign]
    loop._collect_orphaned_branches = AsyncMock(return_value=0)  # type: ignore[method-assign]
    return loop, state, deps.stop_event


class TestWorktreeGCLoopBasics:
    """Basic loop lifecycle tests."""

    def test_worker_name(self, tmp_path: Path) -> None:
        """Worker name is 'worktree_gc'."""
        loop, _state, _stop = _make_loop(tmp_path)
        assert loop._worker_name == "worktree_gc"

    def test_default_interval(self, tmp_path: Path) -> None:
        """Default interval comes from config.worktree_gc_interval."""
        loop, _state, _stop = _make_loop(tmp_path, interval=900)
        assert loop._get_default_interval() == 900

    @pytest.mark.asyncio
    async def test_run__skips_when_disabled(self, tmp_path: Path) -> None:
        """The loop skips work when the enabled callback returns False."""
        loop, _state, _stop = _make_loop(tmp_path, enabled=False)

        await loop.run()

        loop._status_cb.assert_not_called()

    @pytest.mark.asyncio
    async def test_run__publishes_status_on_success(self, tmp_path: Path) -> None:
        """The loop publishes a BACKGROUND_WORKER_STATUS event on success."""
        loop, _state, _stop = _make_loop(tmp_path)

        with patch.object(
            loop,
            "_do_work",
            new_callable=AsyncMock,
            return_value={"collected": 0, "skipped": 0, "errors": 0},
        ):
            await loop.run()

        events = [
            e
            for e in loop._bus.get_history()
            if e.type == EventType.BACKGROUND_WORKER_STATUS
        ]
        assert len(events) >= 1
        assert events[0].data["worker"] == "worktree_gc"
        assert events[0].data["status"] == "ok"


class TestWorktreeGCCollectsClosedIssues:
    """Tests for GC of worktrees whose issues are closed."""

    @pytest.mark.asyncio
    async def test_gc_closed_issue_worktree(self, tmp_path: Path) -> None:
        """Worktrees for closed issues are destroyed and removed from state."""
        loop, state, _stop = _make_loop(
            tmp_path,
            active_worktrees={42: "/some/path/issue-42"},
        )

        loop._get_issue_state = AsyncMock(return_value="closed")

        await loop._do_work()

        loop._worktrees.destroy.assert_awaited_once_with(42)
        assert 42 not in state.get_active_worktrees()

    @pytest.mark.asyncio
    async def test_gc_returns_collected_count(self, tmp_path: Path) -> None:
        """_do_work returns stats with collected count."""
        loop, _state, _stop = _make_loop(
            tmp_path,
            active_worktrees={42: "/some/path/issue-42"},
        )

        loop._get_issue_state = AsyncMock(return_value="closed")

        result = await loop._do_work()

        assert result["collected"] >= 1


class TestWorktreeGCSkipsActive:
    """Tests for skipping active worktrees."""

    @pytest.mark.asyncio
    async def test_skips_active_issue(self, tmp_path: Path) -> None:
        """Worktrees for issues in active_issue_numbers are skipped."""
        loop, _state, _stop = _make_loop(
            tmp_path,
            active_worktrees={42: "/some/path/issue-42"},
            active_issue_numbers=[42],
        )

        result = await loop._do_work()

        loop._worktrees.destroy.assert_not_awaited()
        assert result["skipped"] == 1

    @pytest.mark.asyncio
    async def test_skips_hitl_in_progress(self, tmp_path: Path) -> None:
        """Worktrees for issues with HITL cause are skipped."""
        loop, _state, _stop = _make_loop(
            tmp_path,
            active_worktrees={42: "/some/path/issue-42"},
            hitl_causes={42: "ci_failure"},
        )

        result = await loop._do_work()

        loop._worktrees.destroy.assert_not_awaited()
        assert result["skipped"] == 1

    @pytest.mark.asyncio
    async def test_skips_open_issue_with_pr(self, tmp_path: Path) -> None:
        """Worktrees for open issues with an open PR are skipped."""
        loop, _state, _stop = _make_loop(
            tmp_path,
            active_worktrees={42: "/some/path/issue-42"},
        )

        loop._get_issue_state = AsyncMock(return_value="open")
        loop._has_open_pr = AsyncMock(return_value=True)

        result = await loop._do_work()

        loop._worktrees.destroy.assert_not_awaited()
        assert result["skipped"] == 1

    @pytest.mark.asyncio
    async def test_gc_open_issue_without_pr(self, tmp_path: Path) -> None:
        """Worktrees for open issues with no open PR are collected."""
        loop, state, _stop = _make_loop(
            tmp_path,
            active_worktrees={42: "/some/path/issue-42"},
        )

        loop._get_issue_state = AsyncMock(return_value="open")
        loop._has_open_pr = AsyncMock(return_value=False)

        result = await loop._do_work()

        loop._worktrees.destroy.assert_awaited_once_with(42)
        assert result["collected"] >= 1


class TestWorktreeGCOrphanedDirs:
    """Tests for orphaned filesystem worktree cleanup."""

    @pytest.mark.asyncio
    async def test_collects_orphaned_filesystem_dirs(self, tmp_path: Path) -> None:
        """Orphaned issue-* dirs not in state are collected."""
        loop, _state, _stop = _make_loop(tmp_path)

        # Create orphaned dir on filesystem
        repo_slug = loop._config.repo_slug
        orphan_dir = loop._config.worktree_base / repo_slug / "issue-99"
        orphan_dir.mkdir(parents=True)

        loop._get_issue_state = AsyncMock(return_value="closed")

        result = await loop._do_work()

        loop._worktrees.destroy.assert_awaited_once_with(99)
        assert result["collected"] >= 1


class TestWorktreeGCPrune:
    """Tests for git worktree prune."""

    @pytest.mark.asyncio
    async def test_git_worktree_prune_called(self, tmp_path: Path) -> None:
        """git worktree prune is called each cycle."""
        loop, _state, _stop = _make_loop(tmp_path)
        # Restore real method for this test
        loop._git_worktree_prune = WorktreeGCLoop._git_worktree_prune.__get__(loop)  # type: ignore[attr-defined]

        with patch(
            "worktree_gc_loop.run_subprocess", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = ""
            await loop._git_worktree_prune()

        mock_run.assert_awaited_once()
        args = mock_run.call_args[0]
        assert args[:3] == ("git", "worktree", "prune")


class TestWorktreeGCOrphanedBranches:
    """Tests for orphaned branch cleanup."""

    @pytest.mark.asyncio
    async def test_deletes_orphaned_branches(self, tmp_path: Path) -> None:
        """Local agent/issue-* branches with no worktree are deleted."""
        loop, _state, _stop = _make_loop(tmp_path)
        # Restore real method for this test
        loop._collect_orphaned_branches = (
            WorktreeGCLoop._collect_orphaned_branches.__get__(loop)
        )  # type: ignore[attr-defined]

        with patch(
            "worktree_gc_loop.run_subprocess", new_callable=AsyncMock
        ) as mock_run:
            # First call: git branch --list returns orphaned branch
            # Second call: git branch -D deletes it
            mock_run.side_effect = [
                "  agent/issue-99\n",
                "",
            ]
            count = await loop._collect_orphaned_branches()

        assert count == 1
        # Second call should be the delete
        delete_call = mock_run.call_args_list[1]
        assert delete_call[0] == ("git", "branch", "-D", "agent/issue-99")

    @pytest.mark.asyncio
    async def test_skips_branches_with_active_worktree(self, tmp_path: Path) -> None:
        """Branches for issues with active worktrees are not deleted."""
        loop, _state, _stop = _make_loop(
            tmp_path,
            active_worktrees={99: "/some/path/issue-99"},
        )
        # Restore real method for this test
        loop._collect_orphaned_branches = (
            WorktreeGCLoop._collect_orphaned_branches.__get__(loop)
        )  # type: ignore[attr-defined]

        with patch(
            "worktree_gc_loop.run_subprocess", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = "  agent/issue-99\n"
            count = await loop._collect_orphaned_branches()

        assert count == 0
        # Only one call (listing) — no delete
        assert mock_run.await_count == 1


class TestWorktreeGCErrorHandling:
    """Tests for graceful error handling."""

    @pytest.mark.asyncio
    async def test_api_error_skips_worktree(self, tmp_path: Path) -> None:
        """GitHub API errors cause the worktree to be skipped, not GC'd."""
        loop, state, _stop = _make_loop(
            tmp_path,
            active_worktrees={42: "/some/path/issue-42"},
        )

        loop._get_issue_state = AsyncMock(side_effect=RuntimeError("API failure"))

        result = await loop._do_work()

        loop._worktrees.destroy.assert_not_awaited()
        assert 42 in state.get_active_worktrees()
        assert result["skipped"] == 1

    @pytest.mark.asyncio
    async def test_destroy_error_increments_error_count(self, tmp_path: Path) -> None:
        """Errors during worktree destroy are counted."""
        loop, _state, _stop = _make_loop(
            tmp_path,
            active_worktrees={42: "/some/path/issue-42"},
        )

        loop._get_issue_state = AsyncMock(return_value="closed")
        loop._worktrees.destroy = AsyncMock(side_effect=RuntimeError("destroy failed"))

        result = await loop._do_work()

        assert result["errors"] == 1


class TestWorktreeGCStopEvent:
    """Tests for early exit on stop event."""

    @pytest.mark.asyncio
    async def test_stop_event_halts_gc(self, tmp_path: Path) -> None:
        """Setting the stop event mid-cycle halts GC processing."""
        loop, _state, stop_event = _make_loop(
            tmp_path,
            active_worktrees={1: "/p/issue-1", 2: "/p/issue-2", 3: "/p/issue-3"},
        )
        stop_event.set()

        result = await loop._do_work()

        # With stop set, no worktrees should be processed
        loop._worktrees.destroy.assert_not_awaited()
        assert result["collected"] == 0
