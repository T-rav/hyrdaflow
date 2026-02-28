"""Tests for PRUnsticker background worker."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import ConflictResolutionResult, GitHubIssue, HITLItem
from pr_unsticker import FailureCause, PRUnsticker, _classify_cause
from tests.conftest import make_state
from tests.helpers import ConfigFactory


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
    resolver=None,
    troubleshooting_store=None,
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
    rs = resolver or AsyncMock()
    # save_conflict_transcript is sync; override the auto-generated AsyncMock
    # attribute so callers don't produce "coroutine never awaited" warnings.
    rs.save_conflict_transcript = MagicMock()
    return (
        PRUnsticker(
            cfg,
            st,
            bus,
            prs,
            ag,
            wt,
            ft,
            hitl_runner=hr,
            stop_event=se,
            resolver=rs,
            troubleshooting_store=troubleshooting_store,
        ),
        st,
        prs,
        ag,
        wt,
        ft,
        bus,
        hr,
        rs,
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

    def test_classify_cause_merge_conflict_returns_merge_conflict(self) -> None:
        assert (
            _classify_cause("Merge conflict with main") == FailureCause.MERGE_CONFLICT
        )
        assert _classify_cause("merge conflict") == FailureCause.MERGE_CONFLICT
        assert _classify_cause("Has CONFLICT markers") == FailureCause.MERGE_CONFLICT

    def test_classify_cause_ci_timeout(self) -> None:
        assert _classify_cause("Timeout after 600s") == FailureCause.CI_TIMEOUT
        assert (
            _classify_cause("timed out waiting for checks") == FailureCause.CI_TIMEOUT
        )

    def test_timeout_takes_priority_over_ci_failure(self) -> None:
        # Cause strings like "CI failed after 2 fix attempt(s): Timeout after 600s"
        # contain both "ci fail" and "timeout" — timeout should win.
        cause = "CI failed after 2 fix attempt(s): Timeout after 600s"
        assert _classify_cause(cause) == FailureCause.CI_TIMEOUT

    def test_classify_cause_ci_failure_returns_ci_failure(self) -> None:
        assert (
            _classify_cause("CI failed after 2 fix attempts") == FailureCause.CI_FAILURE
        )
        assert _classify_cause("ci_failure in tests") == FailureCause.CI_FAILURE
        assert _classify_cause("check failed") == FailureCause.CI_FAILURE
        assert _classify_cause("test fail: make quality") == FailureCause.CI_FAILURE
        assert _classify_cause("lint failure") == FailureCause.CI_FAILURE
        assert _classify_cause("type errors in module") == FailureCause.CI_FAILURE

    def test_classify_cause_review_fix_cap_returns_review_fix_cap(self) -> None:
        assert _classify_cause("Review fix cap exceeded") == FailureCause.REVIEW_FIX_CAP
        assert (
            _classify_cause("fix attempt limit reached") == FailureCause.REVIEW_FIX_CAP
        )
        assert _classify_cause("review cap hit") == FailureCause.REVIEW_FIX_CAP

    def test_classify_cause_unknown_input_returns_generic(self) -> None:
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
        unsticker, state, prs, agents, wt, fetcher, bus, _, resolver = _make_unsticker(
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
        unsticker, state, prs, agents, wt, fetcher, bus, _, resolver = _make_unsticker(
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
        unsticker, state, prs, agents, wt, fetcher, bus, _, resolver = _make_unsticker(
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
    async def test_clean_merge_resolves_via_resolver(self, tmp_path: Path) -> None:
        issue = GitHubIssue(
            number=42,
            title="Test issue",
            body="body",
            labels=["hydraflow-hitl"],
        )
        unsticker, state, prs, agents, wt, fetcher, bus, _, resolver = _make_unsticker(
            tmp_path, unstick_auto_merge=False
        )
        state.set_hitl_cause(42, "Merge conflict")
        state.set_hitl_origin(42, "hydraflow-review")

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        wt.create = AsyncMock(return_value=tmp_path / "worktrees" / "issue-42")
        prs.push_branch = AsyncMock(return_value=True)

        # Resolver reports clean merge (no rebuild)
        resolver.resolve_merge_conflicts = AsyncMock(
            return_value=ConflictResolutionResult(success=True, used_rebuild=False)
        )

        wt_dir = tmp_path / "worktrees" / "issue-42"
        wt_dir.mkdir(parents=True)

        stats = await unsticker.unstick([_make_hitl_item(42)])

        assert stats["resolved"] == 1
        assert stats["failed"] == 0
        resolver.resolve_merge_conflicts.assert_awaited_once()
        prs.push_branch.assert_called_once()


class TestSuccessfulResolution:
    @pytest.mark.asyncio
    async def test_successful_conflict_resolution_delegates_to_resolver(
        self, tmp_path: Path
    ) -> None:
        issue = GitHubIssue(
            number=42,
            title="Test issue",
            body="body",
            labels=["hydraflow-hitl"],
        )
        unsticker, state, prs, agents, wt, fetcher, bus, _, resolver = _make_unsticker(
            tmp_path, unstick_auto_merge=False
        )
        state.set_hitl_cause(42, "Merge conflict")
        state.set_hitl_origin(42, "hydraflow-review")

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        wt.create = AsyncMock(return_value=tmp_path / "worktrees" / "issue-42")
        prs.push_branch = AsyncMock(return_value=True)

        # Resolver succeeds without rebuild
        resolver.resolve_merge_conflicts = AsyncMock(
            return_value=ConflictResolutionResult(success=True, used_rebuild=False)
        )

        wt_dir = tmp_path / "worktrees" / "issue-42"
        wt_dir.mkdir(parents=True)

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
        unsticker, state, prs, agents, wt, fetcher, bus, _, resolver = _make_unsticker(
            tmp_path, unstick_auto_merge=False
        )
        state.set_hitl_cause(42, "Merge conflict")

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        wt.create = AsyncMock(return_value=tmp_path / "worktrees" / "issue-42")

        # Resolver fails
        resolver.resolve_merge_conflicts = AsyncMock(
            return_value=ConflictResolutionResult(success=False, used_rebuild=False)
        )

        wt_dir = tmp_path / "worktrees" / "issue-42"
        wt_dir.mkdir(parents=True)

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
        unsticker, state, prs, agents, wt, fetcher, bus, _, resolver = _make_unsticker(
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
        unsticker, state, prs, agents, wt, fetcher, bus, _, resolver = _make_unsticker(
            tmp_path, unstick_all_causes=True, unstick_auto_merge=False
        )
        state.set_hitl_cause(42, "CI failed after 2 fix attempts")
        state.set_hitl_origin(42, "hydraflow-review")

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        wt.start_merge_main = AsyncMock(return_value=True)  # Clean rebase
        wt.create = AsyncMock(return_value=tmp_path / "worktrees" / "issue-42")

        captured_prompt = None
        original_execute = AsyncMock(return_value="fixed transcript")

        async def capture_execute(cmd, prompt, wt_arg, issue_num, **kwargs):
            nonlocal captured_prompt
            captured_prompt = prompt
            return await original_execute(cmd, prompt, wt_arg, issue_num, **kwargs)

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

        unsticker, state, prs, agents, wt, fetcher, bus, _, resolver = _make_unsticker(
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
        unsticker, state, prs, agents, wt, fetcher, bus, _, resolver = _make_unsticker(
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
        unsticker, state, prs, agents, wt, fetcher, bus, _, resolver = _make_unsticker(
            tmp_path, unstick_auto_merge=True
        )
        state.set_hitl_cause(42, "Merge conflict")
        state.set_hitl_origin(42, "hydraflow-review")

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        wt.create = AsyncMock(return_value=tmp_path / "worktrees" / "issue-42")
        prs.push_branch = AsyncMock(return_value=True)
        prs.wait_for_ci = AsyncMock(return_value=(True, "All checks passed"))
        prs.merge_pr = AsyncMock(return_value=True)
        prs.pull_main = AsyncMock(return_value=True)

        # Resolver reports clean merge
        resolver.resolve_merge_conflicts = AsyncMock(
            return_value=ConflictResolutionResult(success=True, used_rebuild=False)
        )

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
        unsticker, state, prs, agents, wt, fetcher, bus, _, resolver = _make_unsticker(
            tmp_path, unstick_auto_merge=False
        )
        state.set_hitl_cause(42, "Merge conflict")
        state.set_hitl_origin(42, "hydraflow-review")

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        wt.create = AsyncMock(return_value=tmp_path / "worktrees" / "issue-42")
        prs.push_branch = AsyncMock(return_value=True)

        # Resolver reports clean merge
        resolver.resolve_merge_conflicts = AsyncMock(
            return_value=ConflictResolutionResult(success=True, used_rebuild=False)
        )

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
        unsticker, state, prs, agents, wt, fetcher, bus, _, resolver = _make_unsticker(
            tmp_path
        )

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
        unsticker, state, prs, agents, wt, fetcher, bus, _, resolver = _make_unsticker(
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
        unsticker, state, prs, agents, wt, fetcher, bus, _, resolver = _make_unsticker(
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


class TestPromptTelemetry:
    """Verify unsticker prompt telemetry is attached to agent calls."""

    @pytest.mark.asyncio
    async def test_ci_fix_telemetry_includes_pruned_chars(self, tmp_path: Path) -> None:
        unsticker, state, _prs, agents, wt, _fetcher, _bus, _hr, _resolver = (
            _make_unsticker(tmp_path)
        )
        issue = GitHubIssue(number=42, title="Fix CI", body="body", labels=[])
        state.set_hitl_cause(42, "x" * 6000)

        wt.start_merge_main = AsyncMock(return_value=True)
        agents._build_command = MagicMock(return_value=["cmd"])
        agents._execute = AsyncMock(return_value="done")
        agents._verify_result = AsyncMock(return_value=(True, ""))

        ok = await unsticker._resolve_ci_or_quality(
            42,
            issue,
            tmp_path / "worktrees" / "issue-42",
            "agent/issue-42",
            "https://example.com/pull/1",
        )
        assert ok is True
        telemetry = agents._execute.await_args.kwargs["telemetry_stats"]
        assert telemetry["pruned_chars_total"] > 0


class TestGoalDrivenLoop:
    """Integration test: fix A -> merge -> re-rebase B -> fix B -> merge."""

    @pytest.mark.asyncio
    async def test_sequential_merge_after_parallel_fix(self, tmp_path: Path) -> None:
        issue_a = GitHubIssue(number=1, title="Issue A", body="a", labels=[])
        issue_b = GitHubIssue(number=2, title="Issue B", body="b", labels=[])

        unsticker, state, prs, agents, wt, fetcher, bus, _, resolver = _make_unsticker(
            tmp_path, unstick_auto_merge=True
        )

        state.set_hitl_cause(1, "Merge conflict")
        state.set_hitl_cause(2, "Merge conflict")
        state.set_hitl_origin(1, "hydraflow-review")
        state.set_hitl_origin(2, "hydraflow-review")

        fetcher.fetch_issue_by_number = AsyncMock(
            side_effect=lambda num: issue_a if num == 1 else issue_b
        )
        wt.start_merge_main = AsyncMock(return_value=True)
        wt.create = AsyncMock(
            side_effect=lambda num, _branch: tmp_path / "worktrees" / f"issue-{num}"
        )
        prs.push_branch = AsyncMock(return_value=True)
        prs.wait_for_ci = AsyncMock(return_value=(True, "All checks passed"))
        prs.merge_pr = AsyncMock(return_value=True)
        prs.pull_main = AsyncMock(return_value=True)

        # Resolver reports clean merge for both
        resolver.resolve_merge_conflicts = AsyncMock(
            return_value=ConflictResolutionResult(success=True, used_rebuild=False)
        )

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


class TestMergeConflictDelegation:
    """Verify that merge conflict resolution delegates to the resolver with correct args."""

    @pytest.mark.asyncio
    async def test_merge_conflict_delegates_to_resolver_with_correct_pr_info(
        self, tmp_path: Path
    ) -> None:
        issue = GitHubIssue(
            number=42,
            title="Fix the widget",
            body="Widget description",
            labels=[],
            url="https://github.com/test-org/test-repo/issues/42",
        )
        unsticker, state, prs, agents, wt, fetcher, bus, _, resolver = _make_unsticker(
            tmp_path, unstick_auto_merge=False
        )
        state.set_hitl_cause(42, "Merge conflict")
        state.set_hitl_origin(42, "hydraflow-review")

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        wt.create = AsyncMock(return_value=tmp_path / "worktrees" / "issue-42")
        prs.push_branch = AsyncMock(return_value=True)

        resolver.resolve_merge_conflicts = AsyncMock(
            return_value=ConflictResolutionResult(success=True, used_rebuild=False)
        )

        wt_dir = tmp_path / "worktrees" / "issue-42"
        wt_dir.mkdir(parents=True)

        pr_url = "https://github.com/test-org/test-repo/pull/100"
        await unsticker.unstick([_make_hitl_item(42, pr=100, prUrl=pr_url)])

        resolver.resolve_merge_conflicts.assert_awaited_once()
        call_args = resolver.resolve_merge_conflicts.call_args

        pr_info = call_args.args[0]
        assert pr_info.number == 100
        assert pr_info.issue_number == 42
        assert pr_info.url == pr_url
        assert pr_info.branch == "agent/issue-42"

    @pytest.mark.asyncio
    async def test_merge_conflict_uses_pr_unsticker_source(
        self, tmp_path: Path
    ) -> None:
        issue = GitHubIssue(
            number=42,
            title="Test issue",
            body="body",
            labels=["hydraflow-hitl"],
        )
        unsticker, state, prs, agents, wt, fetcher, bus, _, resolver = _make_unsticker(
            tmp_path, unstick_auto_merge=False
        )
        state.set_hitl_cause(42, "Merge conflict")
        state.set_hitl_origin(42, "hydraflow-review")

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        wt.create = AsyncMock(return_value=tmp_path / "worktrees" / "issue-42")
        prs.push_branch = AsyncMock(return_value=True)

        resolver.resolve_merge_conflicts = AsyncMock(
            return_value=ConflictResolutionResult(success=True, used_rebuild=False)
        )

        (tmp_path / "worktrees" / "issue-42").mkdir(parents=True)

        await unsticker.unstick([_make_hitl_item(42)])

        call_kwargs = resolver.resolve_merge_conflicts.call_args.kwargs
        assert call_kwargs["source"] == "pr_unsticker"
        assert call_kwargs["worker_id"] is None


class TestFreshBranchRebuild:
    """Tests for fresh branch rebuild delegation via the resolver."""

    @pytest.mark.asyncio
    async def test_conflict_falls_back_to_fresh_rebuild_via_resolver(
        self, tmp_path: Path
    ) -> None:
        """Resolver returns (True, True) indicating rebuild was used."""
        issue = GitHubIssue(
            number=42,
            title="Test issue",
            body="body",
            labels=["hydraflow-hitl"],
            url="https://github.com/test-org/test-repo/issues/42",
        )
        unsticker, state, prs, agents, wt, fetcher, bus, _, resolver = _make_unsticker(
            tmp_path, unstick_auto_merge=False
        )
        state.set_hitl_cause(42, "Merge conflict")
        state.set_hitl_origin(42, "hydraflow-review")

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        wt.create = AsyncMock(return_value=tmp_path / "worktrees" / "issue-42")

        # Resolver used fresh rebuild
        resolver.resolve_merge_conflicts = AsyncMock(
            return_value=ConflictResolutionResult(success=True, used_rebuild=True)
        )
        prs.force_push_branch = AsyncMock(return_value=True)

        wt_dir = tmp_path / "worktrees" / "issue-42"
        wt_dir.mkdir(parents=True)

        pr_url = "https://github.com/test-org/test-repo/pull/100"
        stats = await unsticker.unstick([_make_hitl_item(42, pr=100, prUrl=pr_url)])

        assert stats["resolved"] == 1
        # Should use force_push since rebuild was used
        prs.force_push_branch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_resolver_failure_releases_to_hitl(self, tmp_path: Path) -> None:
        """Resolver returns (False, False) — should release back to HITL."""
        issue = GitHubIssue(
            number=42,
            title="Test issue",
            body="body",
            labels=["hydraflow-hitl"],
        )
        unsticker, state, prs, agents, wt, fetcher, bus, _, resolver = _make_unsticker(
            tmp_path, unstick_auto_merge=False
        )
        state.set_hitl_cause(42, "Merge conflict")

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        wt.create = AsyncMock(return_value=tmp_path / "worktrees" / "issue-42")

        resolver.resolve_merge_conflicts = AsyncMock(
            return_value=ConflictResolutionResult(success=False, used_rebuild=False)
        )

        (tmp_path / "worktrees" / "issue-42").mkdir(parents=True)

        stats = await unsticker.unstick([_make_hitl_item(42)])

        assert stats["failed"] == 1
        assert stats["resolved"] == 0
        prs.swap_pipeline_labels.assert_any_call(42, "hydraflow-hitl")


class TestResolverNoneEdgeCases:
    """Tests for edge cases when the resolver is not configured (resolver=None)."""

    @pytest.mark.asyncio
    async def test_merge_conflict_without_resolver_fails_and_releases_to_hitl(
        self, tmp_path: Path
    ) -> None:
        """When resolver is None and cause is MERGE_CONFLICT, return failure and release to HITL."""
        issue = GitHubIssue(
            number=42,
            title="Test issue",
            body="body",
            labels=["hydraflow-hitl"],
        )
        unsticker, state, prs, agents, wt, fetcher, bus, _, _ = _make_unsticker(
            tmp_path, unstick_all_causes=False, unstick_auto_merge=False
        )
        # Explicitly remove the resolver to test the None path
        unsticker._resolver = None

        state.set_hitl_cause(42, "Merge conflict with main")
        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        wt.create = AsyncMock(return_value=tmp_path / "worktrees" / "issue-42")

        (tmp_path / "worktrees" / "issue-42").mkdir(parents=True)

        stats = await unsticker.unstick([_make_hitl_item(42)])

        assert stats["failed"] == 1
        assert stats["resolved"] == 0
        # Should release back to HITL
        prs.swap_pipeline_labels.assert_any_call(42, "hydraflow-hitl")


def _setup_ci_fix_memory_test(tmp_path: Path, *, transcript: str = "transcript"):
    """Set up shared fixtures for memory suggestion tests on the CI fix path."""
    issue = GitHubIssue(
        number=42,
        title="Test issue",
        body="body",
        labels=["hydraflow-hitl"],
        url="https://github.com/test-org/test-repo/issues/42",
    )
    unsticker, state, prs, agents, wt, fetcher, bus, _, resolver = _make_unsticker(
        tmp_path, unstick_all_causes=True, unstick_auto_merge=False
    )
    state.set_hitl_cause(42, "CI failed after 2 fix attempts")
    state.set_hitl_origin(42, "hydraflow-review")

    fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
    wt.start_merge_main = AsyncMock(return_value=True)  # Clean rebase
    wt.create = AsyncMock(return_value=tmp_path / "worktrees" / "issue-42")

    agents._build_command = MagicMock(return_value=["claude", "-p"])
    agents._execute = AsyncMock(return_value=transcript)
    agents._verify_result = AsyncMock(return_value=(True, "OK"))

    prs.push_branch = AsyncMock(return_value=True)

    (tmp_path / "worktrees" / "issue-42").mkdir(parents=True)
    (tmp_path / "repo" / ".hydraflow" / "logs").mkdir(parents=True)

    return unsticker, state, prs, agents, wt, fetcher, bus


class TestMemorySuggestionExtraction:
    @pytest.mark.asyncio
    async def test_ci_fix_uses_safe_file_memory_suggestion(
        self, tmp_path: Path
    ) -> None:
        unsticker, *_ = _setup_ci_fix_memory_test(
            tmp_path, transcript="transcript with suggestion"
        )

        with patch(
            "pr_unsticker.safe_file_memory_suggestion", new_callable=AsyncMock
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


class TestCITimeoutResolution:
    """Tests for CI_TIMEOUT cause type and test-isolation fix strategy."""

    @pytest.mark.asyncio
    async def test_ci_timeout_runs_isolation_then_agent(self, tmp_path: Path) -> None:
        """Full flow: isolation mock -> agent capture -> verify prompt content."""
        issue = GitHubIssue(
            number=42,
            title="Fix hanging test",
            body="body",
            labels=["hydraflow-hitl"],
            url="https://github.com/test-org/test-repo/issues/42",
        )
        unsticker, state, prs, agents, wt, fetcher, bus, _, resolver = _make_unsticker(
            tmp_path, unstick_all_causes=True, unstick_auto_merge=False
        )
        state.set_hitl_cause(42, "CI failed after 2 fix attempt(s): Timeout after 600s")
        state.set_hitl_origin(42, "hydraflow-review")

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        wt.start_merge_main = AsyncMock(return_value=True)
        wt.create = AsyncMock(return_value=tmp_path / "worktrees" / "issue-42")

        # Mock run_simple for test isolation — simulate timeout
        agents._runner = MagicMock()
        agents._runner.run_simple = AsyncMock(side_effect=TimeoutError("timed out"))

        captured_prompt = None
        original_execute = AsyncMock(return_value="fixed transcript")

        async def capture_execute(cmd, prompt, wt_arg, issue_meta, **kwargs):
            nonlocal captured_prompt
            captured_prompt = prompt
            return await original_execute(cmd, prompt, wt_arg, issue_meta, **kwargs)

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
        # Prompt should mention timeout/hanging
        assert (
            "hanging" in captured_prompt.lower() or "timeout" in captured_prompt.lower()
        )
        assert "AsyncMock" in captured_prompt

    @pytest.mark.asyncio
    async def test_ci_timeout_prompt_contains_isolation_guidance(
        self, tmp_path: Path
    ) -> None:
        """The prompt should contain isolation output and common hang causes."""
        issue = GitHubIssue(
            number=42,
            title="Fix CI",
            body="body",
            labels=[],
            url="https://github.com/test-org/test-repo/issues/42",
        )
        unsticker, state, *_ = _make_unsticker(tmp_path)
        state.set_hitl_cause(42, "CI failed: Timeout after 600s")

        isolation_output = "pytest timed out after 120s — a test is hanging."
        prompt, stats = unsticker._build_ci_timeout_fix_prompt(
            issue,
            "https://github.com/test-org/test-repo/pull/42",
            "CI failed: Timeout after 600s",
            isolation_output,
        )

        assert "AsyncMock" in prompt
        assert "hanging" in prompt.lower()
        assert "120s" in prompt
        assert "timed out" in prompt
        assert "make quality" in prompt.lower()
        # Language-agnostic guidance
        assert "polling loop" in prompt.lower()
        # "Fix ALL instances" guidance
        assert "all instances" in prompt.lower()

    @pytest.mark.asyncio
    async def test_ci_timeout_isolation_failure_still_runs_agent(
        self, tmp_path: Path
    ) -> None:
        """When test isolation errors out, the agent should still run with fallback info."""
        issue = GitHubIssue(
            number=42,
            title="Fix CI",
            body="body",
            labels=["hydraflow-hitl"],
            url="https://github.com/test-org/test-repo/issues/42",
        )
        unsticker, state, prs, agents, wt, fetcher, bus, _, resolver = _make_unsticker(
            tmp_path, unstick_all_causes=True, unstick_auto_merge=False
        )
        state.set_hitl_cause(42, "CI failed after 1 fix attempt(s): Timeout after 600s")
        state.set_hitl_origin(42, "hydraflow-review")

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        wt.start_merge_main = AsyncMock(return_value=True)
        wt.create = AsyncMock(return_value=tmp_path / "worktrees" / "issue-42")

        # Mock run_simple to raise a generic error (not TimeoutError)
        agents._runner = MagicMock()
        agents._runner.run_simple = AsyncMock(
            side_effect=FileNotFoundError("pytest not found")
        )

        captured_prompt = None

        async def capture_execute(cmd, prompt, wt_arg, issue_meta, **kwargs):
            nonlocal captured_prompt
            captured_prompt = prompt
            return "transcript"

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
        # Fallback message should be in the prompt
        assert "isolation failed" in captured_prompt.lower()

    @pytest.mark.asyncio
    async def test_ci_timeout_exhausts_max_attempts(self, tmp_path: Path) -> None:
        """After max_ci_timeout_fix_attempts failures, returns False."""
        issue = GitHubIssue(
            number=42,
            title="Fix CI",
            body="body",
            labels=["hydraflow-hitl"],
            url="https://github.com/test-org/test-repo/issues/42",
        )
        unsticker, state, prs, agents, wt, fetcher, bus, _, resolver = _make_unsticker(
            tmp_path,
            unstick_all_causes=True,
            unstick_auto_merge=False,
            max_ci_timeout_fix_attempts=2,
        )
        state.set_hitl_cause(42, "CI failed after 2 fix attempt(s): Timeout after 600s")
        state.set_hitl_origin(42, "hydraflow-review")

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        wt.start_merge_main = AsyncMock(return_value=True)
        wt.create = AsyncMock(return_value=tmp_path / "worktrees" / "issue-42")

        # Mock isolation
        agents._runner = MagicMock()
        agents._runner.run_simple = AsyncMock(side_effect=TimeoutError("timed out"))

        agents._build_command = MagicMock(return_value=["claude", "-p"])
        agents._execute = AsyncMock(return_value="transcript")
        # Verification always fails
        agents._verify_result = AsyncMock(return_value=(False, "tests still hang"))
        prs.push_branch = AsyncMock(return_value=True)

        wt_dir = tmp_path / "worktrees" / "issue-42"
        wt_dir.mkdir(parents=True)
        (tmp_path / "repo" / ".hydraflow" / "logs").mkdir(parents=True)

        stats = await unsticker.unstick(
            [_make_hitl_item(42, prUrl="https://github.com/test-org/test-repo/pull/42")]
        )

        assert stats["failed"] == 1
        assert stats["resolved"] == 0
        # Agent should have been called max_ci_timeout_fix_attempts times
        assert agents._execute.await_count == 2

    def test_ci_timeout_priority_ordering(self) -> None:
        """CI_TIMEOUT should sort before CI_FAILURE in priority."""
        from pr_unsticker import _CAUSE_PRIORITY

        assert (
            _CAUSE_PRIORITY[FailureCause.CI_TIMEOUT]
            < _CAUSE_PRIORITY[FailureCause.CI_FAILURE]
        )
        assert (
            _CAUSE_PRIORITY[FailureCause.MERGE_CONFLICT]
            < _CAUSE_PRIORITY[FailureCause.CI_TIMEOUT]
        )

    @pytest.mark.asyncio
    async def test_ci_timeout_injects_learned_patterns(self, tmp_path: Path) -> None:
        """Learned patterns from the store appear in the agent prompt."""
        from troubleshooting_store import (
            TroubleshootingPattern,
            TroubleshootingPatternStore,
        )

        store = TroubleshootingPatternStore(tmp_path / "memory")
        store.append_pattern(
            TroubleshootingPattern(
                language="python",
                pattern_name="truthy_asyncmock",
                description="AsyncMock returns truthy MagicMock",
                fix_strategy="Set return_value to falsy",
                frequency=5,
            )
        )

        issue = GitHubIssue(
            number=42,
            title="Fix hanging test",
            body="body",
            labels=["hydraflow-hitl"],
            url="https://github.com/test-org/test-repo/issues/42",
        )
        unsticker, state, prs, agents, wt, fetcher, bus, _, resolver = _make_unsticker(
            tmp_path,
            unstick_all_causes=True,
            unstick_auto_merge=False,
            troubleshooting_store=store,
        )
        state.set_hitl_cause(42, "Timeout after 600s")
        state.set_hitl_origin(42, "hydraflow-review")

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        wt.start_merge_main = AsyncMock(return_value=True)
        wt.create = AsyncMock(return_value=tmp_path / "worktrees" / "issue-42")

        agents._runner = MagicMock()
        agents._runner.run_simple = AsyncMock(side_effect=TimeoutError("timed out"))

        captured_prompt = None

        async def capture_execute(cmd, prompt, wt_arg, issue_meta, **kwargs):
            nonlocal captured_prompt
            captured_prompt = prompt
            return "transcript"

        agents._build_command = MagicMock(return_value=["claude", "-p"])
        agents._execute = capture_execute
        agents._verify_result = AsyncMock(return_value=(True, "OK"))
        prs.push_branch = AsyncMock(return_value=True)

        wt_dir = tmp_path / "worktrees" / "issue-42"
        wt_dir.mkdir(parents=True)
        (tmp_path / "repo" / ".hydraflow" / "logs").mkdir(parents=True)

        with patch.object(unsticker, "_detect_language", return_value="python"):
            await unsticker.unstick(
                [
                    _make_hitl_item(
                        42, prUrl="https://github.com/test-org/test-repo/pull/42"
                    )
                ]
            )

        assert captured_prompt is not None
        assert "Learned Patterns from Previous Fixes" in captured_prompt
        assert "truthy_asyncmock" in captured_prompt
        assert "5x" in captured_prompt

    @pytest.mark.asyncio
    async def test_ci_timeout_persists_pattern_on_success(self, tmp_path: Path) -> None:
        """Successful fix with structured block persists pattern to store."""
        from troubleshooting_store import TroubleshootingPatternStore

        store = TroubleshootingPatternStore(tmp_path / "memory")

        transcript_with_pattern = """Fixed the hanging test.

TROUBLESHOOTING_PATTERN_START
pattern_name: missing_event_set
description: asyncio.Event never gets set causing await to hang
fix_strategy: Call event.set() in test teardown
TROUBLESHOOTING_PATTERN_END

Done."""

        issue = GitHubIssue(
            number=42,
            title="Fix hanging test",
            body="body",
            labels=["hydraflow-hitl"],
            url="https://github.com/test-org/test-repo/issues/42",
        )
        unsticker, state, prs, agents, wt, fetcher, bus, _, resolver = _make_unsticker(
            tmp_path,
            unstick_all_causes=True,
            unstick_auto_merge=False,
            troubleshooting_store=store,
        )
        state.set_hitl_cause(42, "Timeout after 600s")
        state.set_hitl_origin(42, "hydraflow-review")

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        wt.start_merge_main = AsyncMock(return_value=True)
        wt.create = AsyncMock(return_value=tmp_path / "worktrees" / "issue-42")

        agents._runner = MagicMock()
        agents._runner.run_simple = AsyncMock(side_effect=TimeoutError("timed out"))

        agents._build_command = MagicMock(return_value=["claude", "-p"])
        agents._execute = AsyncMock(return_value=transcript_with_pattern)
        agents._verify_result = AsyncMock(return_value=(True, "OK"))
        prs.push_branch = AsyncMock(return_value=True)

        wt_dir = tmp_path / "worktrees" / "issue-42"
        wt_dir.mkdir(parents=True)
        (tmp_path / "repo" / ".hydraflow" / "logs").mkdir(parents=True)

        with patch.object(unsticker, "_detect_language", return_value="python"):
            stats = await unsticker.unstick(
                [
                    _make_hitl_item(
                        42, prUrl="https://github.com/test-org/test-repo/pull/42"
                    )
                ]
            )

        assert stats["resolved"] == 1
        patterns = store.load_patterns()
        assert len(patterns) == 1
        assert patterns[0].pattern_name == "missing_event_set"
        assert patterns[0].language == "python"
        assert 42 in patterns[0].source_issues

    @pytest.mark.asyncio
    async def test_ci_timeout_works_without_store(self, tmp_path: Path) -> None:
        """Backward compat: store=None still works (no crash, no patterns)."""
        issue = GitHubIssue(
            number=42,
            title="Fix hanging test",
            body="body",
            labels=["hydraflow-hitl"],
            url="https://github.com/test-org/test-repo/issues/42",
        )
        # No troubleshooting_store passed — defaults to None
        unsticker, state, prs, agents, wt, fetcher, bus, _, resolver = _make_unsticker(
            tmp_path,
            unstick_all_causes=True,
            unstick_auto_merge=False,
        )
        state.set_hitl_cause(42, "Timeout after 600s")
        state.set_hitl_origin(42, "hydraflow-review")

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        wt.start_merge_main = AsyncMock(return_value=True)
        wt.create = AsyncMock(return_value=tmp_path / "worktrees" / "issue-42")

        agents._runner = MagicMock()
        agents._runner.run_simple = AsyncMock(side_effect=TimeoutError("timed out"))
        agents._build_command = MagicMock(return_value=["claude", "-p"])
        agents._execute = AsyncMock(return_value="transcript")
        agents._verify_result = AsyncMock(return_value=(True, "OK"))
        prs.push_branch = AsyncMock(return_value=True)

        wt_dir = tmp_path / "worktrees" / "issue-42"
        wt_dir.mkdir(parents=True)
        (tmp_path / "repo" / ".hydraflow" / "logs").mkdir(parents=True)

        stats = await unsticker.unstick(
            [_make_hitl_item(42, prUrl="https://github.com/test-org/test-repo/pull/42")]
        )
        assert stats["resolved"] == 1

    def test_ci_timeout_prompt_includes_pattern_emission_instructions(
        self, tmp_path: Path
    ) -> None:
        """Prompt tells the agent to emit TROUBLESHOOTING_PATTERN_START/END block."""
        issue = GitHubIssue(
            number=42,
            title="Fix CI",
            body="body",
            labels=[],
            url="https://github.com/test-org/test-repo/issues/42",
        )
        unsticker, *_ = _make_unsticker(tmp_path)

        prompt, _ = unsticker._build_ci_timeout_fix_prompt(
            issue,
            "https://github.com/test-org/test-repo/pull/42",
            "Timeout after 600s",
            "test output",
        )

        assert "TROUBLESHOOTING_PATTERN_START" in prompt
        assert "TROUBLESHOOTING_PATTERN_END" in prompt
        assert "pattern_name:" in prompt
        assert "description:" in prompt
        assert "fix_strategy:" in prompt

    @pytest.mark.asyncio
    async def test_ci_timeout_reflection_extracts_novel_pattern(
        self, tmp_path: Path
    ) -> None:
        """When agent doesn't emit a block, reflection model extracts a pattern."""
        from troubleshooting_store import TroubleshootingPatternStore

        store = TroubleshootingPatternStore(tmp_path / "memory")

        # Transcript with NO explicit TROUBLESHOOTING_PATTERN block
        transcript_no_block = "Fixed the test by adding return_value=False to the mock."

        issue = GitHubIssue(
            number=42,
            title="Fix hanging test",
            body="body",
            labels=["hydraflow-hitl"],
            url="https://github.com/test-org/test-repo/issues/42",
        )
        unsticker, state, prs, agents, wt, fetcher, bus, _, resolver = _make_unsticker(
            tmp_path,
            unstick_all_causes=True,
            unstick_auto_merge=False,
            troubleshooting_store=store,
        )
        state.set_hitl_cause(42, "Timeout after 600s")
        state.set_hitl_origin(42, "hydraflow-review")

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        wt.start_merge_main = AsyncMock(return_value=True)
        wt.create = AsyncMock(return_value=tmp_path / "worktrees" / "issue-42")

        agents._runner = MagicMock()
        agents._runner.run_simple = AsyncMock(side_effect=TimeoutError("timed out"))
        agents._build_command = MagicMock(return_value=["claude", "-p"])
        agents._execute = AsyncMock(return_value=transcript_no_block)
        agents._verify_result = AsyncMock(return_value=(True, "OK"))
        prs.push_branch = AsyncMock(return_value=True)

        wt_dir = tmp_path / "worktrees" / "issue-42"
        wt_dir.mkdir(parents=True)
        (tmp_path / "repo" / ".hydraflow" / "logs").mkdir(parents=True)

        # Mock the reflection model to return a novel pattern
        from execution import SimpleResult

        reflection_output = """
TROUBLESHOOTING_PATTERN_START
pattern_name: mock_missing_return_value
description: Mock without return_value causes truthy evaluation in bool context
fix_strategy: Set return_value=False on the mock
TROUBLESHOOTING_PATTERN_END
"""
        reflection_result = SimpleResult(
            stdout=reflection_output, stderr="", returncode=0
        )

        # The first run_simple call is for isolation (TimeoutError),
        # the second is for reflection (returns the pattern)
        agents._runner.run_simple = AsyncMock(
            side_effect=[TimeoutError("timed out"), reflection_result]
        )

        with patch.object(unsticker, "_detect_language", return_value="python"):
            stats = await unsticker.unstick(
                [
                    _make_hitl_item(
                        42, prUrl="https://github.com/test-org/test-repo/pull/42"
                    )
                ]
            )

        assert stats["resolved"] == 1
        patterns = store.load_patterns()
        names = [p.pattern_name for p in patterns]
        assert "mock_missing_return_value" in names

    @pytest.mark.asyncio
    async def test_ci_timeout_reflection_skips_known_pattern(
        self, tmp_path: Path
    ) -> None:
        """Reflection returns NO_NEW_PATTERN when the pattern is already known."""
        from troubleshooting_store import TroubleshootingPatternStore

        store = TroubleshootingPatternStore(tmp_path / "memory")

        issue = GitHubIssue(
            number=42,
            title="Fix hanging test",
            body="body",
            labels=["hydraflow-hitl"],
            url="https://github.com/test-org/test-repo/issues/42",
        )
        unsticker, state, prs, agents, wt, fetcher, bus, _, resolver = _make_unsticker(
            tmp_path,
            unstick_all_causes=True,
            unstick_auto_merge=False,
            troubleshooting_store=store,
        )
        state.set_hitl_cause(42, "Timeout after 600s")
        state.set_hitl_origin(42, "hydraflow-review")

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        wt.start_merge_main = AsyncMock(return_value=True)
        wt.create = AsyncMock(return_value=tmp_path / "worktrees" / "issue-42")

        agents._runner = MagicMock()
        agents._build_command = MagicMock(return_value=["claude", "-p"])
        agents._execute = AsyncMock(return_value="Fixed by setting return_value.")
        agents._verify_result = AsyncMock(return_value=(True, "OK"))
        prs.push_branch = AsyncMock(return_value=True)

        wt_dir = tmp_path / "worktrees" / "issue-42"
        wt_dir.mkdir(parents=True)
        (tmp_path / "repo" / ".hydraflow" / "logs").mkdir(parents=True)

        from execution import SimpleResult

        # Reflection says nothing novel
        agents._runner.run_simple = AsyncMock(
            side_effect=[
                TimeoutError("timed out"),
                SimpleResult(stdout="NO_NEW_PATTERN", stderr="", returncode=0),
            ]
        )

        with patch.object(unsticker, "_detect_language", return_value="python"):
            await unsticker.unstick(
                [
                    _make_hitl_item(
                        42, prUrl="https://github.com/test-org/test-repo/pull/42"
                    )
                ]
            )

        # No new patterns should have been added
        assert store.load_patterns() == []

    @pytest.mark.asyncio
    async def test_ci_timeout_reflection_failure_does_not_crash(
        self, tmp_path: Path
    ) -> None:
        """If the reflection model fails, the fix still succeeds."""
        from troubleshooting_store import TroubleshootingPatternStore

        store = TroubleshootingPatternStore(tmp_path / "memory")

        issue = GitHubIssue(
            number=42,
            title="Fix hanging test",
            body="body",
            labels=["hydraflow-hitl"],
            url="https://github.com/test-org/test-repo/issues/42",
        )
        unsticker, state, prs, agents, wt, fetcher, bus, _, resolver = _make_unsticker(
            tmp_path,
            unstick_all_causes=True,
            unstick_auto_merge=False,
            troubleshooting_store=store,
        )
        state.set_hitl_cause(42, "Timeout after 600s")
        state.set_hitl_origin(42, "hydraflow-review")

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        wt.start_merge_main = AsyncMock(return_value=True)
        wt.create = AsyncMock(return_value=tmp_path / "worktrees" / "issue-42")

        agents._runner = MagicMock()
        agents._build_command = MagicMock(return_value=["claude", "-p"])
        agents._execute = AsyncMock(return_value="Fixed it.")
        agents._verify_result = AsyncMock(return_value=(True, "OK"))
        prs.push_branch = AsyncMock(return_value=True)

        wt_dir = tmp_path / "worktrees" / "issue-42"
        wt_dir.mkdir(parents=True)
        (tmp_path / "repo" / ".hydraflow" / "logs").mkdir(parents=True)

        # Reflection model times out
        agents._runner.run_simple = AsyncMock(
            side_effect=[
                TimeoutError("timed out"),
                TimeoutError("reflection timed out"),
            ]
        )

        with patch.object(unsticker, "_detect_language", return_value="python"):
            stats = await unsticker.unstick(
                [
                    _make_hitl_item(
                        42, prUrl="https://github.com/test-org/test-repo/pull/42"
                    )
                ]
            )

        # Fix still succeeds even though reflection failed
        assert stats["resolved"] == 1
