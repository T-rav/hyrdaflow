"""Tests for PRUnsticker background worker."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import GitHubIssue, HITLItem
from pr_unsticker import FailureCause, PRUnsticker, _classify_cause
from tests.conftest import make_state
from tests.helpers import ConfigFactory


def _raise_oserror(*args, **kwargs):
    raise OSError("No space left on device")


def _make_config(tmp_path: Path, **overrides) -> MagicMock:
    return ConfigFactory.create(
        repo_root=tmp_path / "repo",
        worktree_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
        **overrides,
    )


def _make_unsticker(
    tmp_path: Path,
    *,
    config=None,
    state=None,
    pr_manager=None,
    agents=None,
    worktrees=None,
    fetcher=None,
    hitl_runner=None,
    stop_event=None,
    **config_overrides,
):
    cfg = config or _make_config(tmp_path, **config_overrides)
    st = state or make_state(tmp_path)
    bus = AsyncMock()
    bus.publish = AsyncMock()
    prs = pr_manager or AsyncMock()
    ag = agents or AsyncMock()
    wt = worktrees or AsyncMock()
    ft = fetcher or AsyncMock()
    hr = hitl_runner or AsyncMock()
    se = stop_event or asyncio.Event()
    return (
        PRUnsticker(cfg, st, bus, prs, ag, wt, ft, hitl_runner=hr, stop_event=se),
        st,
        prs,
        ag,
        wt,
        ft,
        bus,
        hr,
    )


def _make_hitl_item(issue: int = 42, **kwargs) -> HITLItem:
    return HITLItem(
        issue=issue,
        title=kwargs.get("title", f"Issue #{issue}"),
        branch=kwargs.get("branch", f"agent/issue-{issue}"),
        **{k: v for k, v in kwargs.items() if k not in ("title", "branch")},
    )


class TestCauseClassification:
    """Test _classify_cause() with various cause strings."""

    def test_merge_conflict(self) -> None:
        assert (
            _classify_cause("Merge conflict with main") == FailureCause.MERGE_CONFLICT
        )
        assert _classify_cause("merge conflict") == FailureCause.MERGE_CONFLICT
        assert _classify_cause("Has CONFLICT markers") == FailureCause.MERGE_CONFLICT

    def test_ci_failure(self) -> None:
        assert (
            _classify_cause("CI failed after 2 fix attempts") == FailureCause.CI_FAILURE
        )
        assert _classify_cause("ci_failure in tests") == FailureCause.CI_FAILURE
        assert _classify_cause("check failed") == FailureCause.CI_FAILURE
        assert _classify_cause("test fail: make quality") == FailureCause.CI_FAILURE
        assert _classify_cause("lint failure") == FailureCause.CI_FAILURE
        assert _classify_cause("type errors in module") == FailureCause.CI_FAILURE

    def test_review_fix_cap(self) -> None:
        assert _classify_cause("Review fix cap exceeded") == FailureCause.REVIEW_FIX_CAP
        assert (
            _classify_cause("fix attempt limit reached") == FailureCause.REVIEW_FIX_CAP
        )
        assert _classify_cause("review cap hit") == FailureCause.REVIEW_FIX_CAP

    def test_generic(self) -> None:
        assert _classify_cause("Unknown issue") == FailureCause.GENERIC
        assert _classify_cause("") == FailureCause.GENERIC
        assert _classify_cause("Manual escalation") == FailureCause.GENERIC


class TestEmptyItems:
    @pytest.mark.asyncio
    async def test_empty_items_returns_zero_stats(self, tmp_path: Path) -> None:
        unsticker, *_ = _make_unsticker(tmp_path)
        stats = await unsticker.unstick([])
        assert stats == {
            "processed": 0,
            "resolved": 0,
            "failed": 0,
            "skipped": 0,
            "merged": 0,
        }


class TestAllCausesProcessing:
    """Verify all causes processed when unstick_all_causes=True, only conflicts when False."""

    @pytest.mark.asyncio
    async def test_all_causes_processes_everything(self, tmp_path: Path) -> None:
        unsticker, state, prs, agents, wt, fetcher, bus, _ = _make_unsticker(
            tmp_path, unstick_all_causes=True, unstick_auto_merge=False
        )

        state.set_hitl_cause(1, "Merge conflict with main")
        state.set_hitl_cause(2, "CI failure in tests")
        state.set_hitl_cause(3, "Unknown reason")

        items = [
            _make_hitl_item(issue=1),
            _make_hitl_item(issue=2),
            _make_hitl_item(issue=3),
        ]

        fetcher.fetch_issue_by_number = AsyncMock(return_value=None)

        stats = await unsticker.unstick(items)

        # All 3 should be processed when unstick_all_causes=True
        assert stats["processed"] == 3

    @pytest.mark.asyncio
    async def test_conflicts_only_when_disabled(self, tmp_path: Path) -> None:
        unsticker, state, prs, agents, wt, fetcher, bus, _ = _make_unsticker(
            tmp_path, unstick_all_causes=False, unstick_auto_merge=False
        )

        state.set_hitl_cause(1, "Merge conflict with main")
        state.set_hitl_cause(2, "CI failure in tests")
        state.set_hitl_cause(3, "Review rejected")

        items = [
            _make_hitl_item(issue=1),
            _make_hitl_item(issue=2),
            _make_hitl_item(issue=3),
        ]

        fetcher.fetch_issue_by_number = AsyncMock(return_value=None)

        stats = await unsticker.unstick(items)

        # Only issue 1 should be processed (merge conflict)
        assert stats["processed"] == 1


class TestMergeConflictFilter:
    @pytest.mark.asyncio
    async def test_filters_to_merge_conflict_causes_only(self, tmp_path: Path) -> None:
        unsticker, state, prs, agents, wt, fetcher, bus, _ = _make_unsticker(
            tmp_path, unstick_all_causes=False, unstick_auto_merge=False
        )

        state.set_hitl_cause(1, "Merge conflict with main")
        state.set_hitl_cause(2, "CI failure in tests")
        state.set_hitl_cause(3, "Review rejected")

        items = [
            _make_hitl_item(issue=1),
            _make_hitl_item(issue=2),
            _make_hitl_item(issue=3),
        ]

        fetcher.fetch_issue_by_number = AsyncMock(return_value=None)

        stats = await unsticker.unstick(items)

        assert stats["processed"] == 1

    @pytest.mark.asyncio
    async def test_is_merge_conflict_matches_various_causes(
        self, tmp_path: Path
    ) -> None:
        unsticker, *_ = _make_unsticker(tmp_path)
        assert unsticker._is_merge_conflict("Merge conflict with main")
        assert unsticker._is_merge_conflict("merge conflict")
        assert unsticker._is_merge_conflict("Has CONFLICT markers")
        assert not unsticker._is_merge_conflict("CI failure")
        assert not unsticker._is_merge_conflict("Review rejected")
        assert not unsticker._is_merge_conflict("")


class TestCleanMerge:
    @pytest.mark.asyncio
    async def test_clean_merge_resolves_without_agent(self, tmp_path: Path) -> None:
        issue = GitHubIssue(
            number=42,
            title="Test issue",
            body="body",
            labels=["hydraflow-hitl"],
        )
        unsticker, state, prs, agents, wt, fetcher, bus, _ = _make_unsticker(
            tmp_path, unstick_auto_merge=False
        )
        state.set_hitl_cause(42, "Merge conflict")
        state.set_hitl_origin(42, "hydraflow-review")

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        wt.start_merge_main = AsyncMock(return_value=True)  # Clean merge
        wt.create = AsyncMock(return_value=tmp_path / "worktrees" / "issue-42")
        prs.push_branch = AsyncMock(return_value=True)

        wt_dir = tmp_path / "worktrees" / "issue-42"
        wt_dir.mkdir(parents=True)

        stats = await unsticker.unstick([_make_hitl_item(42)])

        assert stats["resolved"] == 1
        assert stats["failed"] == 0
        agents._execute.assert_not_called()
        prs.push_branch.assert_called_once()


class TestSuccessfulResolution:
    @pytest.mark.asyncio
    async def test_successful_conflict_resolution(self, tmp_path: Path) -> None:
        issue = GitHubIssue(
            number=42,
            title="Test issue",
            body="body",
            labels=["hydraflow-hitl"],
        )
        unsticker, state, prs, agents, wt, fetcher, bus, _ = _make_unsticker(
            tmp_path, unstick_auto_merge=False
        )
        state.set_hitl_cause(42, "Merge conflict")
        state.set_hitl_origin(42, "hydraflow-review")

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        wt.start_merge_main = AsyncMock(return_value=False)
        wt.create = AsyncMock(return_value=tmp_path / "worktrees" / "issue-42")

        agents._build_command = MagicMock(return_value=["claude", "-p"])
        agents._execute = AsyncMock(return_value="resolved conflicts")
        agents._verify_result = AsyncMock(return_value=(True, "OK"))

        prs.push_branch = AsyncMock(return_value=True)

        wt_dir = tmp_path / "worktrees" / "issue-42"
        wt_dir.mkdir(parents=True)
        (tmp_path / "repo" / ".hydraflow" / "logs").mkdir(parents=True)

        stats = await unsticker.unstick([_make_hitl_item(42)])

        assert stats["resolved"] == 1
        assert stats["failed"] == 0

        prs.swap_pipeline_labels.assert_any_call(42, "hydraflow-hitl-active")
        prs.swap_pipeline_labels.assert_any_call(42, "hydraflow-review")

        assert state.get_hitl_origin(42) is None
        assert state.get_hitl_cause(42) is None


class TestFailedResolution:
    @pytest.mark.asyncio
    async def test_failed_resolution_releases_back_to_hitl(
        self, tmp_path: Path
    ) -> None:
        issue = GitHubIssue(
            number=42,
            title="Test issue",
            body="body",
            labels=["hydraflow-hitl"],
        )
        unsticker, state, prs, agents, wt, fetcher, bus, _ = _make_unsticker(
            tmp_path, max_merge_conflict_fix_attempts=2, unstick_auto_merge=False
        )
        state.set_hitl_cause(42, "Merge conflict")

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        wt.start_merge_main = AsyncMock(return_value=False)
        wt.abort_merge = AsyncMock()

        agents._build_command = MagicMock(return_value=["claude", "-p"])
        agents._execute = AsyncMock(return_value="failed transcript")
        agents._verify_result = AsyncMock(return_value=(False, "make quality failed"))

        wt_dir = tmp_path / "worktrees" / "issue-42"
        wt_dir.mkdir(parents=True)
        (tmp_path / "repo" / ".hydraflow" / "logs").mkdir(parents=True)

        stats = await unsticker.unstick([_make_hitl_item(42)])

        assert stats["failed"] == 1
        assert stats["resolved"] == 0

        prs.swap_pipeline_labels.assert_any_call(42, "hydraflow-hitl")

        comment_calls = [
            call
            for call in prs.post_comment.call_args_list
            if "could not resolve" in call.args[1].lower()
        ]
        assert len(comment_calls) == 1


class TestBatchSizeLimit:
    @pytest.mark.asyncio
    async def test_batch_size_limits_processing(self, tmp_path: Path) -> None:
        unsticker, state, prs, agents, wt, fetcher, bus, _ = _make_unsticker(
            tmp_path, pr_unstick_batch_size=2, unstick_auto_merge=False
        )

        for i in range(5):
            state.set_hitl_cause(i + 1, "Merge conflict")

        items = [_make_hitl_item(issue=i + 1) for i in range(5)]

        fetcher.fetch_issue_by_number = AsyncMock(return_value=None)

        stats = await unsticker.unstick(items)

        assert stats["processed"] == 2


class TestCIFailureResolution:
    """Mock agent, verify rebase + quality fix flow for CI failures."""

    @pytest.mark.asyncio
    async def test_ci_failure_runs_agent_with_quality_prompt(
        self, tmp_path: Path
    ) -> None:
        issue = GitHubIssue(
            number=42,
            title="Fix widget",
            body="body",
            labels=["hydraflow-hitl"],
            url="https://github.com/test-org/test-repo/issues/42",
        )
        unsticker, state, prs, agents, wt, fetcher, bus, _ = _make_unsticker(
            tmp_path, unstick_all_causes=True, unstick_auto_merge=False
        )
        state.set_hitl_cause(42, "CI failed after 2 fix attempts")
        state.set_hitl_origin(42, "hydraflow-review")

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        wt.start_merge_main = AsyncMock(return_value=True)  # Clean rebase
        wt.create = AsyncMock(return_value=tmp_path / "worktrees" / "issue-42")

        captured_prompt = None
        original_execute = AsyncMock(return_value="fixed transcript")

        async def capture_execute(cmd, prompt, wt_arg, issue_num):
            nonlocal captured_prompt
            captured_prompt = prompt
            return await original_execute(cmd, prompt, wt_arg, issue_num)

        agents._build_command = MagicMock(return_value=["claude", "-p"])
        agents._execute = capture_execute
        agents._verify_result = AsyncMock(return_value=(True, "OK"))

        prs.push_branch = AsyncMock(return_value=True)

        wt_dir = tmp_path / "worktrees" / "issue-42"
        wt_dir.mkdir(parents=True)
        (tmp_path / "repo" / ".hydraflow" / "logs").mkdir(parents=True)

        stats = await unsticker.unstick(
            [_make_hitl_item(42, prUrl="https://github.com/test-org/test-repo/pull/42")]
        )

        assert stats["resolved"] == 1
        assert captured_prompt is not None
        assert "make quality" in captured_prompt.lower()
        assert "CI" in captured_prompt


class TestGenericResolution:
    """Mock HITLRunner, verify delegation for generic causes."""

    @pytest.mark.asyncio
    async def test_generic_cause_delegates_to_hitl_runner(self, tmp_path: Path) -> None:
        from models import HITLResult

        issue = GitHubIssue(
            number=42,
            title="Fix widget",
            body="body",
            labels=["hydraflow-hitl"],
        )
        hitl_runner = AsyncMock()
        hitl_runner.run = AsyncMock(
            return_value=HITLResult(issue_number=42, success=True)
        )

        unsticker, state, prs, agents, wt, fetcher, bus, _ = _make_unsticker(
            tmp_path,
            unstick_all_causes=True,
            unstick_auto_merge=False,
            hitl_runner=hitl_runner,
        )
        state.set_hitl_cause(42, "Manual escalation by user")
        state.set_hitl_origin(42, "hydraflow-review")

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        wt.create = AsyncMock(return_value=tmp_path / "worktrees" / "issue-42")
        prs.push_branch = AsyncMock(return_value=True)

        wt_dir = tmp_path / "worktrees" / "issue-42"
        wt_dir.mkdir(parents=True)

        stats = await unsticker.unstick([_make_hitl_item(42)])

        assert stats["resolved"] == 1
        hitl_runner.run.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_generic_fails_without_hitl_runner(self, tmp_path: Path) -> None:
        issue = GitHubIssue(
            number=42,
            title="Fix widget",
            body="body",
            labels=["hydraflow-hitl"],
        )
        unsticker, state, prs, agents, wt, fetcher, bus, _ = _make_unsticker(
            tmp_path,
            unstick_all_causes=True,
            unstick_auto_merge=False,
            hitl_runner=None,
        )
        # Override to None explicitly
        unsticker._hitl_runner = None

        state.set_hitl_cause(42, "Manual escalation by user")
        state.set_hitl_origin(42, "hydraflow-review")

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        wt.create = AsyncMock(return_value=tmp_path / "worktrees" / "issue-42")

        wt_dir = tmp_path / "worktrees" / "issue-42"
        wt_dir.mkdir(parents=True)

        stats = await unsticker.unstick([_make_hitl_item(42)])

        assert stats["failed"] == 1


class TestAutoMerge:
    """Mock wait_for_ci + merge_pr, verify label swap to fixed."""

    @pytest.mark.asyncio
    async def test_auto_merge_after_fix(self, tmp_path: Path) -> None:
        issue = GitHubIssue(
            number=42,
            title="Test issue",
            body="body",
            labels=["hydraflow-hitl"],
        )
        unsticker, state, prs, agents, wt, fetcher, bus, _ = _make_unsticker(
            tmp_path, unstick_auto_merge=True
        )
        state.set_hitl_cause(42, "Merge conflict")
        state.set_hitl_origin(42, "hydraflow-review")

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        wt.start_merge_main = AsyncMock(return_value=True)  # Clean merge
        wt.create = AsyncMock(return_value=tmp_path / "worktrees" / "issue-42")
        prs.push_branch = AsyncMock(return_value=True)
        prs.wait_for_ci = AsyncMock(return_value=(True, "All checks passed"))
        prs.merge_pr = AsyncMock(return_value=True)
        prs.pull_main = AsyncMock(return_value=True)

        wt_dir = tmp_path / "worktrees" / "issue-42"
        wt_dir.mkdir(parents=True)

        stats = await unsticker.unstick([_make_hitl_item(42, pr=100)])

        assert stats["resolved"] == 1
        assert stats["merged"] == 1
        prs.merge_pr.assert_awaited_once_with(100)

        # State should be cleaned up
        assert state.get_hitl_origin(42) is None
        assert state.get_hitl_cause(42) is None


class TestAutoMergeDisabled:
    """Verify label-swap-to-origin when unstick_auto_merge=False."""

    @pytest.mark.asyncio
    async def test_no_merge_when_disabled(self, tmp_path: Path) -> None:
        issue = GitHubIssue(
            number=42,
            title="Test issue",
            body="body",
            labels=["hydraflow-hitl"],
        )
        unsticker, state, prs, agents, wt, fetcher, bus, _ = _make_unsticker(
            tmp_path, unstick_auto_merge=False
        )
        state.set_hitl_cause(42, "Merge conflict")
        state.set_hitl_origin(42, "hydraflow-review")

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        wt.start_merge_main = AsyncMock(return_value=True)
        wt.create = AsyncMock(return_value=tmp_path / "worktrees" / "issue-42")
        prs.push_branch = AsyncMock(return_value=True)

        wt_dir = tmp_path / "worktrees" / "issue-42"
        wt_dir.mkdir(parents=True)

        stats = await unsticker.unstick([_make_hitl_item(42, pr=100)])

        assert stats["resolved"] == 1
        assert stats["merged"] == 0

        # Should swap back to origin label
        prs.swap_pipeline_labels.assert_any_call(42, "hydraflow-review")
        # merge_pr should NOT have been called
        prs.merge_pr.assert_not_called()


class TestCascadingRebase:
    """Verify _re_rebase_remaining() rebases worktrees after merge."""

    @pytest.mark.asyncio
    async def test_re_rebase_calls_start_merge_main(self, tmp_path: Path) -> None:
        unsticker, state, prs, agents, wt, fetcher, bus, _ = _make_unsticker(tmp_path)

        # Create worktree dirs
        for i in [1, 2]:
            (tmp_path / "worktrees" / f"issue-{i}").mkdir(parents=True)

        remaining = [_make_hitl_item(issue=1), _make_hitl_item(issue=2)]

        wt.start_merge_main = AsyncMock(return_value=True)

        await unsticker._re_rebase_remaining(remaining)

        assert wt.start_merge_main.await_count == 2


class TestPriorityOrdering:
    """Verify merge conflicts processed before CI failures."""

    @pytest.mark.asyncio
    async def test_merge_conflicts_sorted_first(self, tmp_path: Path) -> None:
        unsticker, state, prs, agents, wt, fetcher, bus, _ = _make_unsticker(
            tmp_path, unstick_all_causes=True, unstick_auto_merge=False
        )

        state.set_hitl_cause(1, "CI failure in tests")
        state.set_hitl_cause(2, "Merge conflict with main")
        state.set_hitl_cause(3, "Unknown reason")

        items = [
            _make_hitl_item(issue=1),
            _make_hitl_item(issue=2),
            _make_hitl_item(issue=3),
        ]

        # Track processing order
        processed_order = []
        original_process = unsticker._process_item

        async def track_process(item):
            processed_order.append(item.issue)
            return await original_process(item)

        unsticker._process_item = track_process
        fetcher.fetch_issue_by_number = AsyncMock(return_value=None)

        await unsticker.unstick(items)

        # Issue 2 (merge conflict) should be first
        assert processed_order[0] == 2


class TestParallelWorkers:
    """Verify semaphore limits concurrent fixes to pr_unstick_batch_size."""

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrency(self, tmp_path: Path) -> None:
        max_workers = 2
        unsticker, state, prs, agents, wt, fetcher, bus, _ = _make_unsticker(
            tmp_path,
            pr_unstick_batch_size=max_workers,
            unstick_all_causes=True,
            unstick_auto_merge=False,
        )

        # Set up 4 items
        for i in range(1, 5):
            state.set_hitl_cause(i, "Merge conflict")

        items = [_make_hitl_item(issue=i) for i in range(1, 5)]

        # Track max concurrent executions
        concurrent = 0
        max_concurrent = 0
        lock = asyncio.Lock()

        original_process = unsticker._process_item

        async def track_concurrency(item):
            nonlocal concurrent, max_concurrent
            async with lock:
                concurrent += 1
                max_concurrent = max(max_concurrent, concurrent)
            try:
                return await original_process(item)
            finally:
                async with lock:
                    concurrent -= 1

        unsticker._process_item = track_concurrency
        fetcher.fetch_issue_by_number = AsyncMock(return_value=None)

        await unsticker.unstick(items)

        assert max_concurrent <= max_workers


class TestGoalDrivenLoop:
    """Integration test: fix A -> merge -> re-rebase B -> fix B -> merge."""

    @pytest.mark.asyncio
    async def test_sequential_merge_after_parallel_fix(self, tmp_path: Path) -> None:
        issue_a = GitHubIssue(number=1, title="Issue A", body="a", labels=[])
        issue_b = GitHubIssue(number=2, title="Issue B", body="b", labels=[])

        unsticker, state, prs, agents, wt, fetcher, bus, _ = _make_unsticker(
            tmp_path, unstick_auto_merge=True
        )

        state.set_hitl_cause(1, "Merge conflict")
        state.set_hitl_cause(2, "Merge conflict")
        state.set_hitl_origin(1, "hydraflow-review")
        state.set_hitl_origin(2, "hydraflow-review")

        fetcher.fetch_issue_by_number = AsyncMock(
            side_effect=lambda num: issue_a if num == 1 else issue_b
        )
        wt.start_merge_main = AsyncMock(return_value=True)  # Clean merges
        wt.create = AsyncMock(
            side_effect=lambda num, _branch: tmp_path / "worktrees" / f"issue-{num}"
        )
        prs.push_branch = AsyncMock(return_value=True)
        prs.wait_for_ci = AsyncMock(return_value=(True, "All checks passed"))
        prs.merge_pr = AsyncMock(return_value=True)
        prs.pull_main = AsyncMock(return_value=True)

        for i in [1, 2]:
            (tmp_path / "worktrees" / f"issue-{i}").mkdir(parents=True)

        items = [
            _make_hitl_item(issue=1, pr=101),
            _make_hitl_item(issue=2, pr=102),
        ]

        stats = await unsticker.unstick(items)

        assert stats["resolved"] == 2
        assert stats["merged"] == 2
        assert prs.merge_pr.await_count == 2
        # pull_main called between merges
        assert prs.pull_main.await_count >= 1


class TestConflictPromptUsesSharedBuilder:
    """Verify that _resolve_conflicts delegates to the shared builder."""

    @pytest.mark.asyncio
    async def test_prompt_includes_urls(self, tmp_path: Path) -> None:
        issue = GitHubIssue(
            number=42,
            title="Fix the widget",
            body="Widget description",
            labels=[],
            url="https://github.com/test-org/test-repo/issues/42",
        )
        unsticker, state, prs, agents, wt, fetcher, bus, _ = _make_unsticker(
            tmp_path, unstick_auto_merge=False
        )
        state.set_hitl_cause(42, "Merge conflict")

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        wt.start_merge_main = AsyncMock(return_value=False)
        wt.create = AsyncMock(return_value=tmp_path / "worktrees" / "issue-42")

        agents._build_command = MagicMock(return_value=["claude", "-p"])
        agents._execute = AsyncMock(return_value="transcript")
        agents._verify_result = AsyncMock(return_value=(True, "OK"))

        prs.push_branch = AsyncMock(return_value=True)

        wt_dir = tmp_path / "worktrees" / "issue-42"
        wt_dir.mkdir(parents=True)
        (tmp_path / "repo" / ".hydraflow" / "logs").mkdir(parents=True)

        pr_url = "https://github.com/test-org/test-repo/pull/42"

        captured_prompt = None
        original_execute = agents._execute

        async def capture_execute(cmd, prompt, wt_arg, issue_num):
            nonlocal captured_prompt
            captured_prompt = prompt
            return await original_execute(cmd, prompt, wt_arg, issue_num)

        agents._execute = capture_execute

        stats = await unsticker.unstick([_make_hitl_item(42, prUrl=pr_url)])

        assert stats["resolved"] == 1
        assert captured_prompt is not None
        assert "https://github.com/test-org/test-repo/issues/42" in captured_prompt
        assert pr_url in captured_prompt
        assert "merge conflicts" in captured_prompt.lower()


class TestSaveTranscript:
    def test_saves_transcript(self, tmp_path: Path) -> None:
        unsticker, *_ = _make_unsticker(tmp_path)

        (tmp_path / "repo").mkdir(parents=True, exist_ok=True)

        unsticker._save_transcript(42, 1, "transcript content here")

        path = (
            tmp_path
            / "repo"
            / ".hydraflow"
            / "logs"
            / "unsticker-issue-42-attempt-1.txt"
        )
        assert path.exists()
        assert path.read_text() == "transcript content here"

    def test_save_transcript_handles_oserror(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        unsticker, *_ = _make_unsticker(tmp_path)

        (tmp_path / "repo").mkdir(parents=True, exist_ok=True)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(Path, "write_text", _raise_oserror)
            unsticker._save_transcript(42, 1, "transcript content here")

        assert "Could not save unsticker transcript" in caplog.text


def _setup_memory_test(tmp_path: Path, *, transcript: str = "transcript"):
    """Set up shared fixtures for memory suggestion extraction tests."""
    issue = GitHubIssue(
        number=42,
        title="Test issue",
        body="body",
        labels=["hydraflow-hitl"],
    )
    unsticker, state, prs, agents, wt, fetcher, bus, _ = _make_unsticker(
        tmp_path, unstick_auto_merge=False
    )
    state.set_hitl_cause(42, "Merge conflict")
    state.set_hitl_origin(42, "hydraflow-review")

    fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
    wt.start_merge_main = AsyncMock(return_value=False)
    wt.create = AsyncMock(return_value=tmp_path / "worktrees" / "issue-42")

    agents._build_command = MagicMock(return_value=["claude", "-p"])
    agents._execute = AsyncMock(return_value=transcript)
    agents._verify_result = AsyncMock(return_value=(True, "OK"))

    prs.push_branch = AsyncMock(return_value=True)

    (tmp_path / "worktrees" / "issue-42").mkdir(parents=True)

    return unsticker, state, prs, agents, wt, fetcher, bus


class TestMemorySuggestionExtraction:
    @pytest.mark.asyncio
    async def test_unsticker_calls_file_memory_suggestion(self, tmp_path: Path) -> None:
        unsticker, *_ = _setup_memory_test(
            tmp_path, transcript="transcript with suggestion"
        )

        with patch(
            "pr_unsticker.file_memory_suggestion", new_callable=AsyncMock
        ) as mock_fms:
            stats = await unsticker.unstick([_make_hitl_item(42)])

            assert stats["resolved"] == 1
            mock_fms.assert_awaited_once_with(
                "transcript with suggestion",
                "pr_unsticker",
                "issue #42",
                unsticker._config,
                unsticker._prs,
                unsticker._state,
            )

    @pytest.mark.asyncio
    async def test_unsticker_memory_failure_does_not_propagate(
        self, tmp_path: Path
    ) -> None:
        unsticker, *_ = _setup_memory_test(tmp_path)

        with patch(
            "pr_unsticker.file_memory_suggestion",
            new_callable=AsyncMock,
            side_effect=RuntimeError("network error"),
        ):
            stats = await unsticker.unstick([_make_hitl_item(42)])

            assert stats["resolved"] == 1


class TestFreshBranchRebuild:
    """Tests for the fresh branch rebuild fallback in the unsticker."""

    @pytest.mark.asyncio
    async def test_conflict_falls_back_to_fresh_rebuild(self, tmp_path: Path) -> None:
        """Merge exhaustion → fresh rebuild is attempted and succeeds."""
        issue = GitHubIssue(
            number=42,
            title="Test issue",
            body="body",
            labels=["hydraflow-hitl"],
            url="https://github.com/test-org/test-repo/issues/42",
        )
        unsticker, state, prs, agents, wt, fetcher, bus, _ = _make_unsticker(
            tmp_path,
            max_merge_conflict_fix_attempts=1,
            enable_fresh_branch_rebuild=True,
            unstick_auto_merge=False,
        )
        state.set_hitl_cause(42, "Merge conflict")
        state.set_hitl_origin(42, "hydraflow-review")

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        wt.start_merge_main = AsyncMock(return_value=False)
        wt.abort_merge = AsyncMock()
        wt.destroy = AsyncMock()
        new_wt = tmp_path / "worktrees" / "issue-42"
        wt.create = AsyncMock(return_value=new_wt)

        # First call (merge attempt) fails, second (rebuild) succeeds
        agents._build_command = MagicMock(return_value=["claude", "-p"])
        agents._execute = AsyncMock(return_value="transcript")
        agents._verify_result = AsyncMock(
            side_effect=[(False, "quality failed"), (True, "OK")]
        )

        prs.get_pr_diff = AsyncMock(return_value="diff --git a/foo.py\n+bar")
        prs.force_push_branch = AsyncMock(return_value=True)
        prs.push_branch = AsyncMock(return_value=True)

        new_wt.mkdir(parents=True)
        (tmp_path / "repo" / ".hydraflow" / "logs").mkdir(parents=True)

        pr_url = "https://github.com/test-org/test-repo/pull/100"
        stats = await unsticker.unstick([_make_hitl_item(42, pr=100, prUrl=pr_url)])

        assert stats["resolved"] == 1
        wt.destroy.assert_awaited_once()
        prs.get_pr_diff.assert_awaited_once_with(100)
        # Should use force_push, not regular push
        prs.force_push_branch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fresh_rebuild_disabled_skips(self, tmp_path: Path) -> None:
        """Config flag off → goes straight to HITL without rebuild."""
        issue = GitHubIssue(
            number=42,
            title="Test issue",
            body="body",
            labels=["hydraflow-hitl"],
        )
        unsticker, state, prs, agents, wt, fetcher, bus, _ = _make_unsticker(
            tmp_path,
            max_merge_conflict_fix_attempts=1,
            enable_fresh_branch_rebuild=False,
            unstick_auto_merge=False,
        )
        state.set_hitl_cause(42, "Merge conflict")

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        wt.start_merge_main = AsyncMock(return_value=False)
        wt.abort_merge = AsyncMock()

        agents._build_command = MagicMock(return_value=["claude", "-p"])
        agents._execute = AsyncMock(return_value="transcript")
        agents._verify_result = AsyncMock(return_value=(False, "quality failed"))

        (tmp_path / "worktrees" / "issue-42").mkdir(parents=True)
        (tmp_path / "repo" / ".hydraflow" / "logs").mkdir(parents=True)

        stats = await unsticker.unstick([_make_hitl_item(42)])

        assert stats["failed"] == 1
        assert stats["resolved"] == 0
        # destroy should not have been called (no rebuild)
        wt.destroy.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_pr_number_threaded_to_resolve_conflicts(
        self, tmp_path: Path
    ) -> None:
        """pr_number from HITLItem flows through to _resolve_conflicts."""
        issue = GitHubIssue(
            number=42,
            title="Test issue",
            body="body",
            labels=["hydraflow-hitl"],
            url="https://github.com/test-org/test-repo/issues/42",
        )
        unsticker, state, prs, agents, wt, fetcher, bus, _ = _make_unsticker(
            tmp_path,
            max_merge_conflict_fix_attempts=1,
            enable_fresh_branch_rebuild=True,
            unstick_auto_merge=False,
        )
        state.set_hitl_cause(42, "Merge conflict")
        state.set_hitl_origin(42, "hydraflow-review")

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        wt.start_merge_main = AsyncMock(return_value=False)
        wt.abort_merge = AsyncMock()
        wt.destroy = AsyncMock()
        wt.create = AsyncMock(return_value=tmp_path / "worktrees" / "issue-42")

        agents._build_command = MagicMock(return_value=["claude", "-p"])
        agents._execute = AsyncMock(return_value="transcript")
        # Merge fails, rebuild also fails
        agents._verify_result = AsyncMock(return_value=(False, "failed"))

        prs.get_pr_diff = AsyncMock(return_value="diff content")
        prs.push_branch = AsyncMock(return_value=True)

        (tmp_path / "worktrees" / "issue-42").mkdir(parents=True)
        (tmp_path / "repo" / ".hydraflow" / "logs").mkdir(parents=True)

        pr_url = "https://github.com/test-org/test-repo/pull/200"
        await unsticker.unstick([_make_hitl_item(42, pr=200, prUrl=pr_url)])

        # get_pr_diff should have been called with the PR number
        prs.get_pr_diff.assert_awaited_once_with(200)
