"""Tests for the WorkspaceGCLoop background worker."""

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
from workspace_gc_loop import _MAX_GC_PER_CYCLE, WorkspaceGCLoop

# Force-delete flag for branch deletion assertions
_FORCE_DEL = chr(45) + chr(68)


def _make_loop(
    tmp_path: Path,
    *,
    enabled: bool = True,
    interval: int = 600,
    active_workspaces: dict[int, str] | None = None,
    active_issue_numbers: list[int] | None = None,
    hitl_causes: dict[int, str] | None = None,
    pipeline_issues: set[int] | None = None,
) -> tuple[WorkspaceGCLoop, StateTracker, asyncio.Event]:
    """Build a WorkspaceGCLoop with test-friendly defaults."""
    deps = make_bg_loop_deps(tmp_path, enabled=enabled, workspace_gc_interval=interval)

    state = StateTracker(deps.config.state_file)
    for num, path in (active_workspaces or {}).items():
        state.set_workspace(num, path)
    if active_issue_numbers:
        state.set_active_issue_numbers(active_issue_numbers)
    for num, cause in (hitl_causes or {}).items():
        state.set_hitl_cause(num, cause)

    in_pipeline = pipeline_issues or set()

    workspaces = MagicMock()
    workspaces.destroy = AsyncMock()
    prs = MagicMock()

    loop = WorkspaceGCLoop(
        config=deps.config,
        workspaces=workspaces,
        prs=prs,
        state=state,
        deps=deps.loop_deps,
        is_in_pipeline_cb=lambda n: n in in_pipeline,
    )
    loop._issue_has_pipeline_label = AsyncMock(return_value=False)  # type: ignore[method-assign]
    loop._collect_orphaned_branches = AsyncMock(return_value=0)  # type: ignore[method-assign]
    return loop, state, deps.stop_event


class TestWorkspaceGCLoopBasics:
    def test_worker_name(self, tmp_path: Path) -> None:
        loop, _state, _stop = _make_loop(tmp_path)
        assert loop._worker_name == "workspace_gc"

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
        assert events[0].data["worker"] == "workspace_gc"
        assert events[0].data["status"] == "ok"


class TestWorktreeGCCollectsClosedIssues:
    @pytest.mark.asyncio
    async def test_gc_closed_issue_worktree(self, tmp_path: Path) -> None:
        loop, state, _stop = _make_loop(tmp_path, active_workspaces={42: "/p/42"})
        loop._get_issue_state = AsyncMock(return_value="closed")
        await loop._do_work()
        loop._workspaces.destroy.assert_awaited_once_with(42)
        assert 42 not in state.get_active_workspaces()

    @pytest.mark.asyncio
    async def test_gc_returns_collected_count(self, tmp_path: Path) -> None:
        loop, _state, _stop = _make_loop(tmp_path, active_workspaces={42: "/p/42"})
        loop._get_issue_state = AsyncMock(return_value="closed")
        result = await loop._do_work()
        assert result["collected"] >= 1

    @pytest.mark.asyncio
    async def test_state_removed_before_destroy(self, tmp_path: Path) -> None:
        loop, state, _stop = _make_loop(tmp_path, active_workspaces={42: "/p/42"})
        loop._get_issue_state = AsyncMock(return_value="closed")
        call_order: list[str] = []
        original_remove = state.remove_workspace

        def tracked_remove(num: int) -> None:
            call_order.append("remove_state")
            original_remove(num)

        state.remove_workspace = tracked_remove  # type: ignore[method-assign]

        async def tracked_destroy(num: int) -> None:
            call_order.append("destroy")

        loop._workspaces.destroy = tracked_destroy  # type: ignore[method-assign]
        await loop._do_work()
        assert call_order == ["remove_state", "destroy"]


class TestWorktreeGCSkipsActive:
    @pytest.mark.asyncio
    async def test_skips_active_issue(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(
            tmp_path, active_workspaces={42: "/p/42"}, active_issue_numbers=[42]
        )
        result = await loop._do_work()
        loop._workspaces.destroy.assert_not_awaited()
        assert result["skipped"] == 1

    @pytest.mark.asyncio
    async def test_skips_hitl_in_progress(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(
            tmp_path, active_workspaces={42: "/p/42"}, hitl_causes={42: "ci_failure"}
        )
        result = await loop._do_work()
        loop._workspaces.destroy.assert_not_awaited()
        assert result["skipped"] == 1

    @pytest.mark.asyncio
    async def test_skips_open_issue_with_pr(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path, active_workspaces={42: "/p/42"})
        loop._get_issue_state = AsyncMock(return_value="open")
        loop._has_open_pr = AsyncMock(return_value=True)
        result = await loop._do_work()
        loop._workspaces.destroy.assert_not_awaited()
        assert result["skipped"] == 1

    @pytest.mark.asyncio
    async def test_gc_open_issue_without_pr(self, tmp_path: Path) -> None:
        loop, state, _e = _make_loop(tmp_path, active_workspaces={42: "/p/42"})
        loop._get_issue_state = AsyncMock(return_value="open")
        loop._has_open_pr = AsyncMock(return_value=False)
        result = await loop._do_work()
        loop._workspaces.destroy.assert_awaited_once_with(42)
        assert result["collected"] >= 1

    @pytest.mark.asyncio
    async def test_skips_unknown_issue_state(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path, active_workspaces={42: "/p/42"})
        loop._get_issue_state = AsyncMock(return_value="unknown")
        result = await loop._do_work()
        loop._workspaces.destroy.assert_not_awaited()
        assert result["skipped"] == 1


class TestWorktreeGCSkipsRetryableIssues:
    """GC must not destroy worktrees for issues that still have retries remaining."""

    @pytest.mark.asyncio
    async def test_skips_issue_with_retries_remaining(self, tmp_path: Path) -> None:
        """Issue with 1/3 attempts used must not be GC'd."""
        loop, state, _e = _make_loop(tmp_path, active_workspaces={42: "/p/42"})
        state.increment_issue_attempts(42)  # 1 attempt used
        loop._get_issue_state = AsyncMock(return_value="open")
        result = await loop._do_work()
        loop._workspaces.destroy.assert_not_awaited()
        assert result["skipped"] == 1

    @pytest.mark.asyncio
    async def test_skips_issue_at_penultimate_attempt(self, tmp_path: Path) -> None:
        """Issue with 2/3 attempts used still has one retry left."""
        loop, state, _e = _make_loop(tmp_path, active_workspaces={42: "/p/42"})
        state.increment_issue_attempts(42)
        state.increment_issue_attempts(42)  # 2 attempts used, max is 3
        loop._get_issue_state = AsyncMock(return_value="open")
        result = await loop._do_work()
        loop._workspaces.destroy.assert_not_awaited()
        assert result["skipped"] == 1

    @pytest.mark.asyncio
    async def test_gc_allowed_after_attempts_exhausted(self, tmp_path: Path) -> None:
        """Once all attempts are used, GC should proceed normally."""
        loop, state, _e = _make_loop(tmp_path, active_workspaces={42: "/p/42"})
        for _ in range(loop._config.max_issue_attempts):
            state.increment_issue_attempts(42)  # exhaust all attempts
        loop._get_issue_state = AsyncMock(return_value="closed")
        result = await loop._do_work()
        loop._workspaces.destroy.assert_awaited_once_with(42)
        assert result["collected"] >= 1

    @pytest.mark.asyncio
    async def test_gc_allowed_when_zero_attempts(self, tmp_path: Path) -> None:
        """Issues with zero attempts (never started) are fine to GC."""
        loop, state, _e = _make_loop(tmp_path, active_workspaces={42: "/p/42"})
        # No attempts recorded
        loop._get_issue_state = AsyncMock(return_value="closed")
        result = await loop._do_work()
        loop._workspaces.destroy.assert_awaited_once_with(42)
        assert result["collected"] >= 1


class TestWorktreeGCBudgetCap:
    @pytest.mark.asyncio
    async def test_budget_caps_phase1_at_max(self, tmp_path: Path) -> None:
        wts = {i: f"/p/issue-{i}" for i in range(1, _MAX_GC_PER_CYCLE + 5)}
        loop, _s, _e = _make_loop(tmp_path, active_workspaces=wts)
        loop._get_issue_state = AsyncMock(return_value="closed")
        result = await loop._do_work()
        assert result["collected"] == _MAX_GC_PER_CYCLE
        assert loop._workspaces.destroy.await_count == _MAX_GC_PER_CYCLE

    @pytest.mark.asyncio
    async def test_budget_shared_across_phases(self, tmp_path: Path) -> None:
        wts = {i: f"/p/issue-{i}" for i in range(1, 6)}
        loop, _s, _e = _make_loop(tmp_path, active_workspaces=wts)
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
        orphan = loop._config.workspace_base / loop._config.repo_slug / "issue-99"
        orphan.mkdir(parents=True)
        loop._get_issue_state = AsyncMock(return_value="closed")
        result = await loop._do_work()
        loop._workspaces.destroy.assert_awaited_once_with(99)
        assert result["collected"] >= 1

    @pytest.mark.asyncio
    async def test_skips_non_issue_dirs(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        base = loop._config.workspace_base / loop._config.repo_slug
        (base / "random-dir").mkdir(parents=True)
        result = await loop._do_work()
        loop._workspaces.destroy.assert_not_awaited()
        assert result["collected"] == 0

    @pytest.mark.asyncio
    async def test_skips_non_numeric_issue_dirs(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        base = loop._config.workspace_base / loop._config.repo_slug
        (base / "issue-abc").mkdir(parents=True)
        await loop._do_work()
        loop._workspaces.destroy.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_returns_zero_when_base_missing(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        result = await loop._do_work()
        assert result["collected"] == 0


class TestWorktreeGCOrphanedBranches:
    @pytest.mark.asyncio
    async def test_deletes_orphaned_branches(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        loop._collect_orphaned_branches = (
            WorkspaceGCLoop._collect_orphaned_branches.__get__(loop)
        )  # type: ignore[attr-defined]
        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.side_effect = ["  agent/issue-99\n", ""]
            count = await loop._collect_orphaned_branches()
        assert count == 1
        assert m.call_args_list[1][0] == ("git", "branch", _FORCE_DEL, "agent/issue-99")

    @pytest.mark.asyncio
    async def test_skips_branches_with_active_worktree(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path, active_workspaces={99: "/p/99"})
        loop._collect_orphaned_branches = (
            WorkspaceGCLoop._collect_orphaned_branches.__get__(loop)
        )  # type: ignore[attr-defined]
        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.return_value = "  agent/issue-99\n"
            count = await loop._collect_orphaned_branches()
        assert count == 0
        assert m.await_count == 1

    @pytest.mark.asyncio
    async def test_starred_branch_parsed_correctly(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        loop._collect_orphaned_branches = (
            WorkspaceGCLoop._collect_orphaned_branches.__get__(loop)
        )  # type: ignore[attr-defined]
        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.side_effect = ["* agent/issue-77\n", ""]
            count = await loop._collect_orphaned_branches()
        assert count == 1
        assert m.call_args_list[1][0] == ("git", "branch", _FORCE_DEL, "agent/issue-77")

    @pytest.mark.asyncio
    async def test_branch_list_failure_returns_zero(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        loop._collect_orphaned_branches = (
            WorkspaceGCLoop._collect_orphaned_branches.__get__(loop)
        )  # type: ignore[attr-defined]
        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.side_effect = RuntimeError("git error")
            count = await loop._collect_orphaned_branches()
        assert count == 0

    @pytest.mark.asyncio
    async def test_skips_branch_when_labels_show_pipeline(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path, pipeline_issues=set())
        loop._collect_orphaned_branches = (
            WorkspaceGCLoop._collect_orphaned_branches.__get__(loop)
        )  # type: ignore[attr-defined]
        loop._issue_has_pipeline_label = AsyncMock(return_value=True)  # type: ignore[method-assign]
        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.return_value = "  agent/issue-99\n"
            count = await loop._collect_orphaned_branches()
        assert count == 0
        assert m.await_count == 1

    @pytest.mark.asyncio
    async def test_skips_branch_with_retries_remaining(self, tmp_path: Path) -> None:
        """Branches for retryable issues must not be deleted."""
        loop, state, _e = _make_loop(tmp_path)
        state.increment_issue_attempts(99)  # 1 attempt, retries remain
        loop._collect_orphaned_branches = (
            WorkspaceGCLoop._collect_orphaned_branches.__get__(loop)
        )  # type: ignore[attr-defined]
        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.return_value = "  agent/issue-99\n"
            count = await loop._collect_orphaned_branches()
        assert count == 0
        assert m.await_count == 1  # only the branch list call, no delete

    @pytest.mark.asyncio
    async def test_branch_budget_cap(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        loop._collect_orphaned_branches = (
            WorkspaceGCLoop._collect_orphaned_branches.__get__(loop)
        )  # type: ignore[attr-defined]
        branches = "\n".join(f"  agent/issue-{i}" for i in range(1, 10))
        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.return_value = branches
            count = await loop._collect_orphaned_branches(budget=3)
        assert count == 3
        assert m.await_count == 4


class TestWorktreeGCSubprocessArgs:
    @pytest.mark.asyncio
    async def test_get_issue_state_args(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
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
        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
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
        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.side_effect = RuntimeError("gh failed")
            result = await loop._has_open_pr(42)
        assert result is True

    @pytest.mark.asyncio
    async def test_issue_has_pipeline_label_parses_api_output(
        self, tmp_path: Path
    ) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        loop._issue_has_pipeline_label = (
            WorkspaceGCLoop._issue_has_pipeline_label.__get__(loop)
        )  # type: ignore[attr-defined]
        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.return_value = f"{loop._config.ready_label[0]}\nother-label\n"
            result = await loop._issue_has_pipeline_label(42)
        assert result is True
        args = m.call_args[0]
        assert args[0] == "gh"
        assert args[1] == "api"
        assert "issues/42" in args[2]
        assert ".labels[].name" in args

    @pytest.mark.asyncio
    async def test_issue_has_pipeline_label_fails_safe_on_api_error(
        self, tmp_path: Path
    ) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        loop._issue_has_pipeline_label = (
            WorkspaceGCLoop._issue_has_pipeline_label.__get__(loop)
        )  # type: ignore[attr-defined]
        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.side_effect = RuntimeError("gh failed")
            result = await loop._issue_has_pipeline_label(42)
        assert result is True


class TestWorktreeGCErrorHandling:
    @pytest.mark.asyncio
    async def test_api_error_skips_worktree(self, tmp_path: Path) -> None:
        loop, state, _e = _make_loop(tmp_path, active_workspaces={42: "/p/42"})
        loop._get_issue_state = AsyncMock(side_effect=RuntimeError("API failure"))
        result = await loop._do_work()
        loop._workspaces.destroy.assert_not_awaited()
        assert 42 in state.get_active_workspaces()
        assert result["skipped"] == 1

    @pytest.mark.asyncio
    async def test_destroy_error_increments_error_count(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path, active_workspaces={42: "/p/42"})
        loop._get_issue_state = AsyncMock(return_value="closed")
        loop._workspaces.destroy = AsyncMock(side_effect=RuntimeError("destroy failed"))
        result = await loop._do_work()
        assert result["errors"] == 1

    @pytest.mark.asyncio
    async def test_has_open_pr_error_skips_worktree(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path, active_workspaces={42: "/p/42"})
        loop._get_issue_state = AsyncMock(return_value="open")
        loop._has_open_pr = AsyncMock(side_effect=RuntimeError("PR check failed"))
        result = await loop._do_work()
        loop._workspaces.destroy.assert_not_awaited()
        assert result["skipped"] == 1


class TestWorktreeGCStopEvent:
    @pytest.mark.asyncio
    async def test_stop_event_halts_gc(self, tmp_path: Path) -> None:
        loop, _s, stop = _make_loop(
            tmp_path, active_workspaces={1: "/p/1", 2: "/p/2", 3: "/p/3"}
        )
        stop.set()
        result = await loop._do_work()
        loop._workspaces.destroy.assert_not_awaited()
        assert result["collected"] == 0

    @pytest.mark.asyncio
    async def test_stop_event_skips_later_phases(self, tmp_path: Path) -> None:
        loop, _s, stop = _make_loop(tmp_path, active_workspaces={42: "/p/42"})

        async def gc_and_stop(issue_number: int) -> str:
            stop.set()
            return "closed"

        loop._get_issue_state = AsyncMock(side_effect=gc_and_stop)
        result = await loop._do_work()
        assert result["collected"] == 1
        loop._collect_orphaned_branches.assert_not_awaited()


class TestWorktreeGCOrphanedDirsBudget:
    """Tests for Phase 2 budget exhaustion."""

    @pytest.mark.asyncio
    async def test_orphaned_dirs_respect_budget(self, tmp_path: Path) -> None:
        """Phase 2 stops collecting when budget is exhausted."""
        # Phase 1 collects 18, leaving budget of 2 for Phase 2
        wts = {i: f"/p/issue-{i}" for i in range(1, 19)}
        loop, _s, _e = _make_loop(tmp_path, active_workspaces=wts)
        loop._get_issue_state = AsyncMock(return_value="closed")

        # Create 5 orphaned dirs — only 2 should be collected (budget = 20 - 18)
        slug = loop._config.repo_slug
        for i in range(100, 105):
            (loop._config.workspace_base / slug / f"issue-{i}").mkdir(parents=True)

        result = await loop._do_work()
        assert result["collected"] == _MAX_GC_PER_CYCLE  # 18 + 2 = 20


class TestWorktreeGCOrphanedDirsErrors:
    """Tests for Phase 2 error handling."""

    @pytest.mark.asyncio
    async def test_orphaned_dir_destroy_failure_continues(self, tmp_path: Path) -> None:
        """A destroy failure for one orphaned dir does not stop processing others."""
        loop, _s, _e = _make_loop(tmp_path)
        slug = loop._config.repo_slug
        (loop._config.workspace_base / slug / "issue-50").mkdir(parents=True)
        (loop._config.workspace_base / slug / "issue-51").mkdir(parents=True)

        loop._get_issue_state = AsyncMock(return_value="closed")

        call_count = 0

        async def fail_then_succeed(issue_number: int) -> None:
            nonlocal call_count
            call_count += 1
            if issue_number == 50:
                raise RuntimeError("destroy failed")

        loop._workspaces.destroy = fail_then_succeed  # type: ignore[method-assign]

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
            (loop._config.workspace_base / slug / f"issue-{i}").mkdir(parents=True)

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


class TestWorktreeGCBranchActiveIssues:
    """Tests for branch skipping based on active_issue_numbers."""

    @pytest.mark.asyncio
    async def test_skips_branches_with_active_issue_number(
        self, tmp_path: Path
    ) -> None:
        """Branches for active issues (no worktree entry) are not deleted."""
        loop, _s, _e = _make_loop(tmp_path, active_issue_numbers=[99])
        loop._collect_orphaned_branches = (
            WorkspaceGCLoop._collect_orphaned_branches.__get__(loop)
        )  # type: ignore[attr-defined]
        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
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
    async def test_unsafe_for_open_issue_with_pipeline_label(
        self, tmp_path: Path
    ) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        loop._get_issue_state = AsyncMock(return_value="open")
        loop._issue_has_pipeline_label = AsyncMock(return_value=True)  # type: ignore[method-assign]
        loop._has_open_pr = AsyncMock(return_value=False)
        assert await loop._is_safe_to_gc(42) is False
        loop._has_open_pr.assert_not_awaited()

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
            tmp_path, active_workspaces={42: "/p/42"}, pipeline_issues={42}
        )
        result = await loop._do_work()
        loop._workspaces.destroy.assert_not_awaited()
        assert result["skipped"] == 1
        assert 42 in state.get_active_workspaces()

    @pytest.mark.asyncio
    async def test_collects_worktree_not_in_pipeline(self, tmp_path: Path) -> None:
        """Worktrees for issues no longer in the pipeline are collected normally."""
        loop, _s, _e = _make_loop(
            tmp_path, active_workspaces={42: "/p/42"}, pipeline_issues=set()
        )
        loop._get_issue_state = AsyncMock(return_value="closed")
        result = await loop._do_work()
        loop._workspaces.destroy.assert_awaited_once_with(42)
        assert result["collected"] >= 1

    @pytest.mark.asyncio
    async def test_skips_when_store_pipeline_stale_but_labels_show_queued(
        self, tmp_path: Path
    ) -> None:
        """GitHub labels protect queued issues even if IssueStore callback misses them."""
        loop, state, _e = _make_loop(
            tmp_path,
            active_workspaces={42: "/p/42"},
            pipeline_issues=set(),
        )
        loop._get_issue_state = AsyncMock(return_value="open")
        loop._issue_has_pipeline_label = AsyncMock(return_value=True)  # type: ignore[method-assign]
        loop._has_open_pr = AsyncMock(return_value=False)

        result = await loop._do_work()
        loop._workspaces.destroy.assert_not_awaited()
        assert result["skipped"] == 1
        assert 42 in state.get_active_workspaces()

    @pytest.mark.asyncio
    async def test_skips_orphaned_dir_for_pipeline_issue(self, tmp_path: Path) -> None:
        """Orphaned filesystem dirs for pipeline issues are not collected."""
        loop, _s, _e = _make_loop(tmp_path, pipeline_issues={99})
        orphan = loop._config.workspace_base / loop._config.repo_slug / "issue-99"
        orphan.mkdir(parents=True)
        result = await loop._do_work()
        loop._workspaces.destroy.assert_not_awaited()
        assert result["collected"] == 0

    @pytest.mark.asyncio
    async def test_skips_branch_for_pipeline_issue(self, tmp_path: Path) -> None:
        """Branches for issues in the pipeline are not deleted."""
        loop, _s, _e = _make_loop(tmp_path, pipeline_issues={99})
        loop._collect_orphaned_branches = (
            WorkspaceGCLoop._collect_orphaned_branches.__get__(loop)
        )  # type: ignore[attr-defined]
        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.return_value = "  agent/issue-99\n"
            count = await loop._collect_orphaned_branches()
        assert count == 0
        assert m.await_count == 1


class TestGCRemovesBranchStateOnWorktreeCollection:
    """Phase 1: GC'ing a worktree also removes its active_branches entry."""

    @pytest.mark.asyncio
    async def test_phase1_removes_branch_entry(self, tmp_path: Path) -> None:
        loop, state, _e = _make_loop(tmp_path, active_workspaces={42: "/p/42"})
        state.set_branch(42, "agent/issue-42")
        loop._get_issue_state = AsyncMock(return_value="closed")
        await loop._do_work()
        assert state.get_branch(42) is None

    @pytest.mark.asyncio
    async def test_phase1_noop_when_no_branch_entry(self, tmp_path: Path) -> None:
        """No error when GC'ing a worktree that has no branch entry."""
        loop, state, _e = _make_loop(tmp_path, active_workspaces={42: "/p/42"})
        loop._get_issue_state = AsyncMock(return_value="closed")
        await loop._do_work()
        assert state.get_branch(42) is None

    @pytest.mark.asyncio
    async def test_phase1_removes_branch_before_destroy(self, tmp_path: Path) -> None:
        """remove_branch must be called before destroy (crash-safe ordering)."""
        loop, state, _e = _make_loop(tmp_path, active_workspaces={42: "/p/42"})
        state.set_branch(42, "agent/issue-42")
        loop._get_issue_state = AsyncMock(return_value="closed")

        call_order: list[str] = []
        original_remove_branch = state.remove_branch

        def tracked_remove_branch(num: int) -> None:
            call_order.append("remove_branch")
            original_remove_branch(num)

        async def tracked_destroy(num: int) -> None:
            call_order.append("destroy")

        state.remove_branch = tracked_remove_branch  # type: ignore[method-assign]
        loop._workspaces.destroy = tracked_destroy  # type: ignore[method-assign]
        await loop._do_work()
        assert "remove_branch" in call_order
        assert call_order.index("remove_branch") < call_order.index("destroy")


class TestGCRemovesBranchStateOnOrphanedBranchDeletion:
    """Phase 3: deleting an orphaned branch also removes its state entry."""

    @pytest.mark.asyncio
    async def test_phase3_removes_branch_entry(self, tmp_path: Path) -> None:
        loop, state, _e = _make_loop(tmp_path)
        state.set_branch(99, "agent/issue-99")
        loop._collect_orphaned_branches = (
            WorkspaceGCLoop._collect_orphaned_branches.__get__(loop)
        )  # type: ignore[attr-defined]
        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.side_effect = ["  agent/issue-99\n", ""]
            await loop._collect_orphaned_branches()
        assert state.get_branch(99) is None


class TestGCPrunesStaleActiveBranches:
    """Phase 4: prune active_branches entries with no worktree and safe to GC."""

    @pytest.mark.asyncio
    async def test_prunes_stale_branch_without_worktree(self, tmp_path: Path) -> None:
        loop, state, _e = _make_loop(tmp_path)
        state.set_branch(42, "agent/issue-42")
        # No worktree set for issue 42
        loop._is_safe_to_gc = AsyncMock(return_value=True)
        pruned = await loop._prune_stale_branch_entries()
        assert pruned == 1
        assert state.get_branch(42) is None

    @pytest.mark.asyncio
    async def test_skips_branch_with_active_worktree(self, tmp_path: Path) -> None:
        loop, state, _e = _make_loop(tmp_path, active_workspaces={42: "/p/42"})
        state.set_branch(42, "agent/issue-42")
        loop._is_safe_to_gc = AsyncMock(return_value=True)
        pruned = await loop._prune_stale_branch_entries()
        assert pruned == 0
        assert state.get_branch(42) == "agent/issue-42"

    @pytest.mark.asyncio
    async def test_skips_branch_not_safe_to_gc(self, tmp_path: Path) -> None:
        loop, state, _e = _make_loop(tmp_path)
        state.set_branch(42, "agent/issue-42")
        loop._is_safe_to_gc = AsyncMock(return_value=False)
        pruned = await loop._prune_stale_branch_entries()
        assert pruned == 0
        assert state.get_branch(42) == "agent/issue-42"

    @pytest.mark.asyncio
    async def test_phase4_runs_in_do_work(self, tmp_path: Path) -> None:
        """Phase 4 runs as part of the full _do_work cycle."""
        loop, state, _e = _make_loop(tmp_path)
        state.set_branch(42, "agent/issue-42")
        loop._get_issue_state = AsyncMock(return_value="closed")
        # _collect_orphaned_branches is already mocked in _make_loop
        result = await loop._do_work()
        assert state.get_branch(42) is None
        assert result["collected"] >= 1

    @pytest.mark.asyncio
    async def test_exception_during_pruning_skips_entry_and_continues(
        self, tmp_path: Path
    ) -> None:
        """An exception during _is_safe_to_gc is caught; remaining entries are still pruned."""
        loop, state, _e = _make_loop(tmp_path)
        state.set_branch(10, "agent/issue-10")
        state.set_branch(20, "agent/issue-20")

        async def fail_first(issue_number: int) -> bool:
            if issue_number == 10:
                raise RuntimeError("API failure")
            return True

        loop._is_safe_to_gc = AsyncMock(side_effect=fail_first)
        pruned = await loop._prune_stale_branch_entries()
        # issue 10 raised — skipped; issue 20 succeeded — pruned
        assert pruned == 1
        assert state.get_branch(10) == "agent/issue-10"
        assert state.get_branch(20) is None


class TestCollectOrphanedBranchesPerItemIsolation:
    """Per-item try/except in _collect_orphaned_branches prevents one failure from aborting the pass."""

    @pytest.mark.asyncio
    async def test_pipeline_check_error_skips_branch_and_continues(
        self, tmp_path: Path
    ) -> None:
        """An exception in _issue_has_pipeline_label for one branch doesn't abort the loop."""
        loop, _s, _e = _make_loop(tmp_path)
        loop._collect_orphaned_branches = (
            WorkspaceGCLoop._collect_orphaned_branches.__get__(loop)
        )  # type: ignore[attr-defined]

        call_count = 0

        async def fail_for_first(issue_number: int) -> bool:
            nonlocal call_count
            call_count += 1
            if issue_number == 10:
                raise RuntimeError("API failure")
            return False

        loop._issue_has_pipeline_label = AsyncMock(side_effect=fail_for_first)  # type: ignore[method-assign]

        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.side_effect = ["  agent/issue-10\n  agent/issue-20\n", ""]
            count = await loop._collect_orphaned_branches()

        # issue-10 raised — skipped; issue-20 succeeded — deleted
        assert count == 1
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_is_in_pipeline_error_skips_branch_and_continues(
        self, tmp_path: Path
    ) -> None:
        """An exception in is_in_pipeline callback doesn't abort the loop."""
        call_log: list[int] = []

        def exploding_pipeline(n: int) -> bool:
            call_log.append(n)
            if n == 10:
                raise RuntimeError("callback boom")
            return False

        deps = make_bg_loop_deps(tmp_path, enabled=True, workspace_gc_interval=600)
        state = StateTracker(deps.config.state_file)
        loop = WorkspaceGCLoop(
            config=deps.config,
            workspaces=MagicMock(),
            prs=MagicMock(),
            state=state,
            deps=deps.loop_deps,
            is_in_pipeline_cb=exploding_pipeline,
        )
        loop._issue_has_pipeline_label = AsyncMock(return_value=False)  # type: ignore[method-assign]

        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.side_effect = ["  agent/issue-10\n  agent/issue-20\n", ""]
            count = await loop._collect_orphaned_branches()

        # issue-10 raised in pipeline check — skipped; issue-20 succeeded
        assert count == 1
        assert 10 in call_log
        assert 20 in call_log


class TestGCReraisesFatalExceptions:
    """Fatal exceptions (AuthenticationError, CreditExhaustedError, likely bugs)
    must propagate through GC except blocks instead of being swallowed as warnings.
    """

    # -- Phase 1: _do_work except block (line 73) --

    @pytest.mark.asyncio
    async def test_phase1_reraises_authentication_error(self, tmp_path: Path) -> None:
        """AuthenticationError from _is_safe_to_gc propagates out of _do_work."""
        from subprocess_util import AuthenticationError  # noqa: PLC0415

        loop, _s, _e = _make_loop(tmp_path, active_workspaces={42: "/p/42"})
        loop._get_issue_state = AsyncMock(side_effect=AuthenticationError("bad token"))
        with pytest.raises(AuthenticationError):
            await loop._do_work()

    @pytest.mark.asyncio
    async def test_phase1_reraises_attribute_error(self, tmp_path: Path) -> None:
        """AttributeError (likely bug) from _is_safe_to_gc propagates out of _do_work."""
        loop, _s, _e = _make_loop(tmp_path, active_workspaces={42: "/p/42"})
        loop._get_issue_state = AsyncMock(side_effect=AttributeError("no such attr"))
        with pytest.raises(AttributeError):
            await loop._do_work()

    # -- _is_safe_to_gc: _get_issue_state except block (line 141) --

    @pytest.mark.asyncio
    async def test_is_safe_to_gc_reraises_auth_error_from_get_issue_state(
        self, tmp_path: Path
    ) -> None:
        """AuthenticationError from _get_issue_state propagates out of _is_safe_to_gc."""
        from subprocess_util import AuthenticationError  # noqa: PLC0415

        loop, _s, _e = _make_loop(tmp_path)
        loop._get_issue_state = AsyncMock(side_effect=AuthenticationError("bad token"))
        with pytest.raises(AuthenticationError):
            await loop._is_safe_to_gc(42)

    # -- _is_safe_to_gc: _has_open_pr except block (line 163) --

    @pytest.mark.asyncio
    async def test_is_safe_to_gc_reraises_auth_error_from_has_open_pr(
        self, tmp_path: Path
    ) -> None:
        """AuthenticationError from _has_open_pr propagates out of _is_safe_to_gc."""
        from subprocess_util import AuthenticationError  # noqa: PLC0415

        loop, _s, _e = _make_loop(tmp_path)
        loop._get_issue_state = AsyncMock(return_value="open")
        loop._has_open_pr = AsyncMock(side_effect=AuthenticationError("bad token"))
        with pytest.raises(AuthenticationError):
            await loop._is_safe_to_gc(42)

    # -- _issue_has_pipeline_label except block (line 194) --

    @pytest.mark.asyncio
    async def test_issue_has_pipeline_label_reraises_auth_error(
        self, tmp_path: Path
    ) -> None:
        """AuthenticationError from run_subprocess propagates out of _issue_has_pipeline_label."""
        from subprocess_util import AuthenticationError  # noqa: PLC0415

        loop, _s, _e = _make_loop(tmp_path)
        loop._issue_has_pipeline_label = (
            WorkspaceGCLoop._issue_has_pipeline_label.__get__(loop)
        )  # type: ignore[attr-defined]
        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.side_effect = AuthenticationError("bad token")
            with pytest.raises(AuthenticationError):
                await loop._issue_has_pipeline_label(42)

    # -- _collect_orphaned_dirs except block (line 272) --

    @pytest.mark.asyncio
    async def test_collect_orphaned_dirs_reraises_auth_error(
        self, tmp_path: Path
    ) -> None:
        """AuthenticationError from _is_safe_to_gc propagates out of _collect_orphaned_dirs."""
        from subprocess_util import AuthenticationError  # noqa: PLC0415

        loop, _s, _e = _make_loop(tmp_path)
        slug = loop._config.repo_slug
        (loop._config.workspace_base / slug / "issue-50").mkdir(parents=True)
        loop._get_issue_state = AsyncMock(side_effect=AuthenticationError("bad token"))
        with pytest.raises(AuthenticationError):
            await loop._collect_orphaned_dirs({}, 10)

    @pytest.mark.asyncio
    async def test_collect_orphaned_dirs_reraises_attribute_error(
        self, tmp_path: Path
    ) -> None:
        """AttributeError (likely bug) from _is_safe_to_gc propagates out of _collect_orphaned_dirs."""
        loop, _s, _e = _make_loop(tmp_path)
        slug = loop._config.repo_slug
        (loop._config.workspace_base / slug / "issue-50").mkdir(parents=True)
        loop._get_issue_state = AsyncMock(side_effect=AttributeError("no such attr"))
        with pytest.raises(AttributeError):
            await loop._collect_orphaned_dirs({}, 10)

    # -- _collect_orphaned_branches per-item except block (line 333) --

    @pytest.mark.asyncio
    async def test_collect_orphaned_branches_reraises_auth_error(
        self, tmp_path: Path
    ) -> None:
        """AuthenticationError from _issue_has_pipeline_label propagates out of _collect_orphaned_branches."""
        from subprocess_util import AuthenticationError  # noqa: PLC0415

        loop, _s, _e = _make_loop(tmp_path)
        loop._collect_orphaned_branches = (
            WorkspaceGCLoop._collect_orphaned_branches.__get__(loop)
        )  # type: ignore[attr-defined]
        loop._issue_has_pipeline_label = AsyncMock(  # type: ignore[method-assign]
            side_effect=AuthenticationError("bad token")
        )
        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.return_value = "  agent/issue-99\n"
            with pytest.raises(AuthenticationError):
                await loop._collect_orphaned_branches()

    @pytest.mark.asyncio
    async def test_collect_orphaned_branches_reraises_attribute_error(
        self, tmp_path: Path
    ) -> None:
        """AttributeError (likely bug) in branch processing propagates."""
        loop, _s, _e = _make_loop(tmp_path)
        loop._collect_orphaned_branches = (
            WorkspaceGCLoop._collect_orphaned_branches.__get__(loop)
        )  # type: ignore[attr-defined]
        loop._issue_has_pipeline_label = AsyncMock(  # type: ignore[method-assign]
            side_effect=AttributeError("no such attr")
        )
        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.return_value = "  agent/issue-99\n"
            with pytest.raises(AttributeError):
                await loop._collect_orphaned_branches()

    # -- _prune_stale_branch_entries except block (line 358) --

    @pytest.mark.asyncio
    async def test_prune_stale_branch_entries_reraises_auth_error(
        self, tmp_path: Path
    ) -> None:
        """AuthenticationError from _is_safe_to_gc propagates out of _prune_stale_branch_entries."""
        from subprocess_util import AuthenticationError  # noqa: PLC0415

        loop, state, _e = _make_loop(tmp_path)
        state.set_branch(42, "agent/issue-42")
        loop._is_safe_to_gc = AsyncMock(side_effect=AuthenticationError("bad token"))
        with pytest.raises(AuthenticationError):
            await loop._prune_stale_branch_entries()

    @pytest.mark.asyncio
    async def test_prune_stale_branch_entries_reraises_attribute_error(
        self, tmp_path: Path
    ) -> None:
        """AttributeError (likely bug) propagates out of _prune_stale_branch_entries."""
        loop, state, _e = _make_loop(tmp_path)
        state.set_branch(42, "agent/issue-42")
        loop._is_safe_to_gc = AsyncMock(side_effect=AttributeError("no such attr"))
        with pytest.raises(AttributeError):
            await loop._prune_stale_branch_entries()

    # -- Transient errors are still caught (regression safety) --

    @pytest.mark.asyncio
    async def test_phase1_still_catches_runtime_error(self, tmp_path: Path) -> None:
        """RuntimeError (transient) is still caught, not re-raised."""
        loop, _s, _e = _make_loop(tmp_path, active_workspaces={42: "/p/42"})
        loop._get_issue_state = AsyncMock(
            side_effect=RuntimeError("transient network error")
        )
        # RuntimeError is caught in _is_safe_to_gc (returns False → skipped)
        # and does not propagate to _do_work.
        result = await loop._do_work()
        assert result["skipped"] == 1

    @pytest.mark.asyncio
    async def test_collect_orphaned_dirs_still_catches_os_error(
        self, tmp_path: Path
    ) -> None:
        """OSError (transient filesystem) is still caught in _collect_orphaned_dirs."""
        loop, _s, _e = _make_loop(tmp_path)
        slug = loop._config.repo_slug
        (loop._config.workspace_base / slug / "issue-50").mkdir(parents=True)
        loop._is_safe_to_gc = AsyncMock(side_effect=OSError("disk error"))
        collected = await loop._collect_orphaned_dirs({}, 10)
        assert collected == 0  # error was caught, not propagated

    @pytest.mark.asyncio
    async def test_prune_stale_branch_entries_still_catches_runtime_error(
        self, tmp_path: Path
    ) -> None:
        """RuntimeError (transient) is still caught in _prune_stale_branch_entries."""
        loop, state, _e = _make_loop(tmp_path)
        state.set_branch(42, "agent/issue-42")
        loop._is_safe_to_gc = AsyncMock(side_effect=RuntimeError("API failure"))
        pruned = await loop._prune_stale_branch_entries()
        assert pruned == 0  # error was caught, not propagated
