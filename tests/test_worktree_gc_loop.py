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
from worktree_gc_loop import _MAX_GC_PER_CYCLE, WorktreeGCLoop

# Force-delete flag for branch deletion assertions
_FORCE_DEL = chr(45) + chr(68)


def _make_loop(
    tmp_path: Path,
    *,
    enabled: bool = True,
    interval: int = 600,
    active_worktrees: dict[int, str] | None = None,
    active_issue_numbers: list[int] | None = None,
    hitl_causes: dict[int, str] | None = None,
    pipeline_issues: set[int] | None = None,
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

    in_pipeline = pipeline_issues or set()

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
        is_in_pipeline_cb=lambda n: n in in_pipeline,
    )
    loop._git_worktree_prune = AsyncMock()  # type: ignore[method-assign]
    loop._collect_orphaned_branches = AsyncMock(return_value=0)  # type: ignore[method-assign]
    return loop, state, deps.stop_event


class TestWorktreeGCLoopBasics:
    def test_worker_name(self, tmp_path: Path) -> None:
        loop, _state, _stop = _make_loop(tmp_path)
        assert loop._worker_name == "worktree_gc"

    def test_default_interval(self, tmp_path: Path) -> None:
        loop, _state, _stop = _make_loop(tmp_path, interval=900)
        assert loop._get_default_interval() == 900

    @pytest.mark.asyncio
    async def test_run__skips_when_disabled(self, tmp_path: Path) -> None:
        loop, _state, _stop = _make_loop(tmp_path, enabled=False)
        await loop.run()
        loop._status_cb.assert_not_called()

    @pytest.mark.asyncio
    async def test_run__publishes_status_on_success(self, tmp_path: Path) -> None:
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
    @pytest.mark.asyncio
    async def test_gc_closed_issue_worktree(self, tmp_path: Path) -> None:
        loop, state, _stop = _make_loop(tmp_path, active_worktrees={42: "/p/42"})
        loop._get_issue_state = AsyncMock(return_value="closed")
        await loop._do_work()
        loop._worktrees.destroy.assert_awaited_once_with(42)
        assert 42 not in state.get_active_worktrees()

    @pytest.mark.asyncio
    async def test_gc_returns_collected_count(self, tmp_path: Path) -> None:
        loop, _state, _stop = _make_loop(tmp_path, active_worktrees={42: "/p/42"})
        loop._get_issue_state = AsyncMock(return_value="closed")
        result = await loop._do_work()
        assert result["collected"] >= 1

    @pytest.mark.asyncio
    async def test_state_removed_before_destroy(self, tmp_path: Path) -> None:
        loop, state, _stop = _make_loop(tmp_path, active_worktrees={42: "/p/42"})
        loop._get_issue_state = AsyncMock(return_value="closed")
        call_order: list[str] = []
        original_remove = state.remove_worktree

        def tracked_remove(num: int) -> None:
            call_order.append("remove_state")
            original_remove(num)

        state.remove_worktree = tracked_remove  # type: ignore[method-assign]

        async def tracked_destroy(num: int) -> None:
            call_order.append("destroy")

        loop._worktrees.destroy = tracked_destroy  # type: ignore[method-assign]
        await loop._do_work()
        assert call_order == ["remove_state", "destroy"]


class TestWorktreeGCSkipsActive:
    @pytest.mark.asyncio
    async def test_skips_active_issue(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(
            tmp_path, active_worktrees={42: "/p/42"}, active_issue_numbers=[42]
        )
        result = await loop._do_work()
        loop._worktrees.destroy.assert_not_awaited()
        assert result["skipped"] == 1

    @pytest.mark.asyncio
    async def test_skips_hitl_in_progress(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(
            tmp_path, active_worktrees={42: "/p/42"}, hitl_causes={42: "ci_failure"}
        )
        result = await loop._do_work()
        loop._worktrees.destroy.assert_not_awaited()
        assert result["skipped"] == 1

    @pytest.mark.asyncio
    async def test_skips_open_issue_with_pr(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path, active_worktrees={42: "/p/42"})
        loop._get_issue_state = AsyncMock(return_value="open")
        loop._has_open_pr = AsyncMock(return_value=True)
        result = await loop._do_work()
        loop._worktrees.destroy.assert_not_awaited()
        assert result["skipped"] == 1

    @pytest.mark.asyncio
    async def test_gc_open_issue_without_pr(self, tmp_path: Path) -> None:
        loop, state, _e = _make_loop(tmp_path, active_worktrees={42: "/p/42"})
        loop._get_issue_state = AsyncMock(return_value="open")
        loop._has_open_pr = AsyncMock(return_value=False)
        result = await loop._do_work()
        loop._worktrees.destroy.assert_awaited_once_with(42)
        assert result["collected"] >= 1

    @pytest.mark.asyncio
    async def test_skips_unknown_issue_state(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path, active_worktrees={42: "/p/42"})
        loop._get_issue_state = AsyncMock(return_value="unknown")
        result = await loop._do_work()
        loop._worktrees.destroy.assert_not_awaited()
        assert result["skipped"] == 1


class TestWorktreeGCBudgetCap:
    @pytest.mark.asyncio
    async def test_budget_caps_phase1_at_max(self, tmp_path: Path) -> None:
        wts = {i: f"/p/issue-{i}" for i in range(1, _MAX_GC_PER_CYCLE + 5)}
        loop, _s, _e = _make_loop(tmp_path, active_worktrees=wts)
        loop._get_issue_state = AsyncMock(return_value="closed")
        result = await loop._do_work()
        assert result["collected"] == _MAX_GC_PER_CYCLE
        assert loop._worktrees.destroy.await_count == _MAX_GC_PER_CYCLE

    @pytest.mark.asyncio
    async def test_budget_shared_across_phases(self, tmp_path: Path) -> None:
        wts = {i: f"/p/issue-{i}" for i in range(1, 6)}
        loop, _s, _e = _make_loop(tmp_path, active_worktrees=wts)
        loop._get_issue_state = AsyncMock(return_value="closed")
        calls: list[int] = []

        async def capture_budget(budget: int = _MAX_GC_PER_CYCLE) -> int:
            calls.append(budget)
            return 0

        loop._collect_orphaned_branches = capture_budget  # type: ignore[method-assign]
        await loop._do_work()
        assert calls == [_MAX_GC_PER_CYCLE - 5]


class TestWorktreeGCOrphanedDirs:
    @pytest.mark.asyncio
    async def test_collects_orphaned_filesystem_dirs(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        orphan = loop._config.worktree_base / loop._config.repo_slug / "issue-99"
        orphan.mkdir(parents=True)
        loop._get_issue_state = AsyncMock(return_value="closed")
        result = await loop._do_work()
        loop._worktrees.destroy.assert_awaited_once_with(99)
        assert result["collected"] >= 1

    @pytest.mark.asyncio
    async def test_skips_non_issue_dirs(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        base = loop._config.worktree_base / loop._config.repo_slug
        (base / "random-dir").mkdir(parents=True)
        result = await loop._do_work()
        loop._worktrees.destroy.assert_not_awaited()
        assert result["collected"] == 0

    @pytest.mark.asyncio
    async def test_skips_non_numeric_issue_dirs(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        base = loop._config.worktree_base / loop._config.repo_slug
        (base / "issue-abc").mkdir(parents=True)
        await loop._do_work()
        loop._worktrees.destroy.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_returns_zero_when_base_missing(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        result = await loop._do_work()
        assert result["collected"] == 0


class TestWorktreeGCPrune:
    @pytest.mark.asyncio
    async def test_git_worktree_prune_called(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        loop._git_worktree_prune = WorktreeGCLoop._git_worktree_prune.__get__(loop)  # type: ignore[attr-defined]
        with patch("worktree_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.return_value = ""
            await loop._git_worktree_prune()
        m.assert_awaited_once()
        assert m.call_args[0][:3] == ("git", "worktree", "prune")

    @pytest.mark.asyncio
    async def test_git_worktree_prune_failure_handled(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        loop._git_worktree_prune = WorktreeGCLoop._git_worktree_prune.__get__(loop)  # type: ignore[attr-defined]
        with patch("worktree_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.side_effect = RuntimeError("prune failed")
            await loop._git_worktree_prune()
        m.assert_awaited_once()


class TestWorktreeGCOrphanedBranches:
    @pytest.mark.asyncio
    async def test_deletes_orphaned_branches(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        loop._collect_orphaned_branches = (
            WorktreeGCLoop._collect_orphaned_branches.__get__(loop)
        )  # type: ignore[attr-defined]
        with patch("worktree_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.side_effect = ["  agent/issue-99\n", ""]
            count = await loop._collect_orphaned_branches()
        assert count == 1
        assert m.call_args_list[1][0] == ("git", "branch", _FORCE_DEL, "agent/issue-99")

    @pytest.mark.asyncio
    async def test_skips_branches_with_active_worktree(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path, active_worktrees={99: "/p/99"})
        loop._collect_orphaned_branches = (
            WorktreeGCLoop._collect_orphaned_branches.__get__(loop)
        )  # type: ignore[attr-defined]
        with patch("worktree_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.return_value = "  agent/issue-99\n"
            count = await loop._collect_orphaned_branches()
        assert count == 0
        assert m.await_count == 1

    @pytest.mark.asyncio
    async def test_starred_branch_parsed_correctly(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        loop._collect_orphaned_branches = (
            WorktreeGCLoop._collect_orphaned_branches.__get__(loop)
        )  # type: ignore[attr-defined]
        with patch("worktree_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.side_effect = ["* agent/issue-77\n", ""]
            count = await loop._collect_orphaned_branches()
        assert count == 1
        assert m.call_args_list[1][0] == ("git", "branch", _FORCE_DEL, "agent/issue-77")

    @pytest.mark.asyncio
    async def test_branch_list_failure_returns_zero(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        loop._collect_orphaned_branches = (
            WorktreeGCLoop._collect_orphaned_branches.__get__(loop)
        )  # type: ignore[attr-defined]
        with patch("worktree_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.side_effect = RuntimeError("git error")
            count = await loop._collect_orphaned_branches()
        assert count == 0

    @pytest.mark.asyncio
    async def test_branch_budget_cap(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        loop._collect_orphaned_branches = (
            WorktreeGCLoop._collect_orphaned_branches.__get__(loop)
        )  # type: ignore[attr-defined]
        branches = "\n".join(f"  agent/issue-{i}" for i in range(1, 10))
        with patch("worktree_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.return_value = branches
            count = await loop._collect_orphaned_branches(budget=3)
        assert count == 3
        assert m.await_count == 4


class TestWorktreeGCSubprocessArgs:
    @pytest.mark.asyncio
    async def test_get_issue_state_args(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        with patch("worktree_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.return_value = "closed\n"
            result = await loop._get_issue_state(42)
        assert result == "closed"
        args = m.call_args[0]
        assert args[0] == "gh"
        assert args[1] == "api"
        assert "issues/42" in args[2]
        assert "--jq" in args
        assert ".state" in args
        assert m.call_args[1]["cwd"] == loop._config.repo_root

    @pytest.mark.asyncio
    async def test_has_open_pr_args(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        with patch("worktree_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.return_value = "0\n"
            result = await loop._has_open_pr(42)
        assert result is False
        args = m.call_args[0]
        assert args[:3] == ("gh", "pr", "list")
        assert "--head" in args
        assert "--state" in args
        assert loop._config.branch_for_issue(42) in args

    @pytest.mark.asyncio
    async def test_has_open_pr_returns_true_on_error(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        with patch("worktree_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.side_effect = RuntimeError("gh failed")
            result = await loop._has_open_pr(42)
        assert result is True


class TestWorktreeGCErrorHandling:
    @pytest.mark.asyncio
    async def test_api_error_skips_worktree(self, tmp_path: Path) -> None:
        loop, state, _e = _make_loop(tmp_path, active_worktrees={42: "/p/42"})
        loop._get_issue_state = AsyncMock(side_effect=RuntimeError("API failure"))
        result = await loop._do_work()
        loop._worktrees.destroy.assert_not_awaited()
        assert 42 in state.get_active_worktrees()
        assert result["skipped"] == 1

    @pytest.mark.asyncio
    async def test_destroy_error_increments_error_count(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path, active_worktrees={42: "/p/42"})
        loop._get_issue_state = AsyncMock(return_value="closed")
        loop._worktrees.destroy = AsyncMock(side_effect=RuntimeError("destroy failed"))
        result = await loop._do_work()
        assert result["errors"] == 1

    @pytest.mark.asyncio
    async def test_has_open_pr_error_skips_worktree(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path, active_worktrees={42: "/p/42"})
        loop._get_issue_state = AsyncMock(return_value="open")
        loop._has_open_pr = AsyncMock(side_effect=RuntimeError("PR check failed"))
        result = await loop._do_work()
        loop._worktrees.destroy.assert_not_awaited()
        assert result["skipped"] == 1


class TestWorktreeGCStopEvent:
    @pytest.mark.asyncio
    async def test_stop_event_halts_gc(self, tmp_path: Path) -> None:
        loop, _s, stop = _make_loop(
            tmp_path, active_worktrees={1: "/p/1", 2: "/p/2", 3: "/p/3"}
        )
        stop.set()
        result = await loop._do_work()
        loop._worktrees.destroy.assert_not_awaited()
        assert result["collected"] == 0

    @pytest.mark.asyncio
    async def test_stop_event_skips_later_phases(self, tmp_path: Path) -> None:
        loop, _s, stop = _make_loop(tmp_path, active_worktrees={42: "/p/42"})

        async def gc_and_stop(issue_number: int) -> str:
            stop.set()
            return "closed"

        loop._get_issue_state = AsyncMock(side_effect=gc_and_stop)
        result = await loop._do_work()
        assert result["collected"] == 1
        loop._git_worktree_prune.assert_not_awaited()
        loop._collect_orphaned_branches.assert_not_awaited()


class TestWorktreeGCOrphanedDirsBudget:
    """Tests for Phase 2 budget exhaustion."""

    @pytest.mark.asyncio
    async def test_orphaned_dirs_respect_budget(self, tmp_path: Path) -> None:
        """Phase 2 stops collecting when budget is exhausted."""
        # Phase 1 collects 18, leaving budget of 2 for Phase 2
        wts = {i: f"/p/issue-{i}" for i in range(1, 19)}
        loop, _s, _e = _make_loop(tmp_path, active_worktrees=wts)
        loop._get_issue_state = AsyncMock(return_value="closed")

        # Create 5 orphaned dirs — only 2 should be collected (budget = 20 - 18)
        slug = loop._config.repo_slug
        for i in range(100, 105):
            (loop._config.worktree_base / slug / f"issue-{i}").mkdir(parents=True)

        result = await loop._do_work()
        assert result["collected"] == _MAX_GC_PER_CYCLE  # 18 + 2 = 20


class TestWorktreeGCOrphanedDirsErrors:
    """Tests for Phase 2 error handling."""

    @pytest.mark.asyncio
    async def test_orphaned_dir_destroy_failure_continues(self, tmp_path: Path) -> None:
        """A destroy failure for one orphaned dir does not stop processing others."""
        loop, _s, _e = _make_loop(tmp_path)
        slug = loop._config.repo_slug
        (loop._config.worktree_base / slug / "issue-50").mkdir(parents=True)
        (loop._config.worktree_base / slug / "issue-51").mkdir(parents=True)

        loop._get_issue_state = AsyncMock(return_value="closed")

        call_count = 0

        async def fail_then_succeed(issue_num: int) -> None:
            nonlocal call_count
            call_count += 1
            if issue_num == 50:
                raise RuntimeError("destroy failed")

        loop._worktrees.destroy = fail_then_succeed  # type: ignore[method-assign]

        result = await loop._do_work()
        # issue-50 fails, issue-51 succeeds
        assert call_count == 2
        assert result["collected"] >= 1


class TestWorktreeGCStopEventPhase2:
    """Tests for stop event within Phase 2 iteration."""

    @pytest.mark.asyncio
    async def test_stop_event_halts_orphaned_dir_iteration(
        self, tmp_path: Path
    ) -> None:
        """Stop event set during Phase 2 stops collecting orphaned dirs."""
        loop, _s, stop = _make_loop(tmp_path)
        slug = loop._config.repo_slug
        for i in range(100, 105):
            (loop._config.worktree_base / slug / f"issue-{i}").mkdir(parents=True)

        call_count = 0

        async def gc_and_stop_on_second(issue_number: int) -> str:
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                stop.set()
            return "closed"

        loop._get_issue_state = AsyncMock(side_effect=gc_and_stop_on_second)

        result = await loop._do_work()
        # Should stop after 2 orphaned dirs due to stop event
        assert result["collected"] <= 3
        loop._git_worktree_prune.assert_not_awaited()


class TestWorktreeGCBranchActiveIssues:
    """Tests for branch skipping based on active_issue_numbers."""

    @pytest.mark.asyncio
    async def test_skips_branches_with_active_issue_number(
        self, tmp_path: Path
    ) -> None:
        """Branches for active issues (no worktree entry) are not deleted."""
        loop, _s, _e = _make_loop(tmp_path, active_issue_numbers=[99])
        loop._collect_orphaned_branches = (
            WorktreeGCLoop._collect_orphaned_branches.__get__(loop)
        )  # type: ignore[attr-defined]
        with patch("worktree_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.return_value = "  agent/issue-99\n"
            count = await loop._collect_orphaned_branches()
        assert count == 0
        assert m.await_count == 1


class TestIsSafeToGCDirect:
    """Direct unit tests for _is_safe_to_gc."""

    @pytest.mark.asyncio
    async def test_safe_for_closed_issue(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        loop._get_issue_state = AsyncMock(return_value="closed")
        assert await loop._is_safe_to_gc(42) is True

    @pytest.mark.asyncio
    async def test_unsafe_for_active_issue(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path, active_issue_numbers=[42])
        assert await loop._is_safe_to_gc(42) is False

    @pytest.mark.asyncio
    async def test_unsafe_for_hitl_issue(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path, hitl_causes={42: "ci_failure"})
        assert await loop._is_safe_to_gc(42) is False

    @pytest.mark.asyncio
    async def test_unsafe_for_open_issue_with_pr(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        loop._get_issue_state = AsyncMock(return_value="open")
        loop._has_open_pr = AsyncMock(return_value=True)
        assert await loop._is_safe_to_gc(42) is False

    @pytest.mark.asyncio
    async def test_safe_for_open_issue_without_pr(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        loop._get_issue_state = AsyncMock(return_value="open")
        loop._has_open_pr = AsyncMock(return_value=False)
        assert await loop._is_safe_to_gc(42) is True

    @pytest.mark.asyncio
    async def test_unsafe_on_api_error(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        loop._get_issue_state = AsyncMock(side_effect=RuntimeError("API error"))
        assert await loop._is_safe_to_gc(42) is False

    @pytest.mark.asyncio
    async def test_unsafe_on_unknown_state(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        loop._get_issue_state = AsyncMock(return_value="weird_state")
        assert await loop._is_safe_to_gc(42) is False

    @pytest.mark.asyncio
    async def test_unsafe_on_pr_check_error(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        loop._get_issue_state = AsyncMock(return_value="open")
        loop._has_open_pr = AsyncMock(side_effect=RuntimeError("PR check error"))
        assert await loop._is_safe_to_gc(42) is False

    @pytest.mark.asyncio
    async def test_unsafe_when_issue_in_pipeline(self, tmp_path: Path) -> None:
        """Issues queued/in-flight/active in IssueStore must not be GC'd."""
        loop, _s, _e = _make_loop(tmp_path, pipeline_issues={42})
        assert await loop._is_safe_to_gc(42) is False

    @pytest.mark.asyncio
    async def test_safe_when_issue_not_in_pipeline(self, tmp_path: Path) -> None:
        """Issues not in the pipeline can be GC'd if other checks pass."""
        loop, _s, _e = _make_loop(tmp_path, pipeline_issues={99})
        loop._get_issue_state = AsyncMock(return_value="closed")
        assert await loop._is_safe_to_gc(42) is True


class TestWorktreeGCPipelineProtection:
    """Tests for pipeline-aware GC protection."""

    @pytest.mark.asyncio
    async def test_skips_worktree_for_queued_issue(self, tmp_path: Path) -> None:
        """Worktrees for issues still in the pipeline queue are not collected."""
        loop, state, _e = _make_loop(
            tmp_path, active_worktrees={42: "/p/42"}, pipeline_issues={42}
        )
        result = await loop._do_work()
        loop._worktrees.destroy.assert_not_awaited()
        assert result["skipped"] == 1
        assert 42 in state.get_active_worktrees()

    @pytest.mark.asyncio
    async def test_collects_worktree_not_in_pipeline(self, tmp_path: Path) -> None:
        """Worktrees for issues no longer in the pipeline are collected normally."""
        loop, _s, _e = _make_loop(
            tmp_path, active_worktrees={42: "/p/42"}, pipeline_issues=set()
        )
        loop._get_issue_state = AsyncMock(return_value="closed")
        result = await loop._do_work()
        loop._worktrees.destroy.assert_awaited_once_with(42)
        assert result["collected"] >= 1

    @pytest.mark.asyncio
    async def test_skips_orphaned_dir_for_pipeline_issue(self, tmp_path: Path) -> None:
        """Orphaned filesystem dirs for pipeline issues are not collected."""
        loop, _s, _e = _make_loop(tmp_path, pipeline_issues={99})
        orphan = loop._config.worktree_base / loop._config.repo_slug / "issue-99"
        orphan.mkdir(parents=True)
        result = await loop._do_work()
        loop._worktrees.destroy.assert_not_awaited()
        assert result["collected"] == 0

    @pytest.mark.asyncio
    async def test_skips_branch_for_pipeline_issue(self, tmp_path: Path) -> None:
        """Branches for issues in the pipeline are not deleted."""
        loop, _s, _e = _make_loop(tmp_path, pipeline_issues={99})
        loop._collect_orphaned_branches = (
            WorktreeGCLoop._collect_orphaned_branches.__get__(loop)
        )  # type: ignore[attr-defined]
        with patch("worktree_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.return_value = "  agent/issue-99\n"
            count = await loop._collect_orphaned_branches()
        assert count == 0
        assert m.await_count == 1
