"""Tests for PRUnsticker background worker."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import GitHubIssue, HITLItem
from pr_unsticker import PRUnsticker
from state import StateTracker
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


def _make_state(tmp_path: Path) -> StateTracker:
    return StateTracker(tmp_path / "state.json")


def _make_unsticker(
    tmp_path: Path,
    *,
    config=None,
    state=None,
    pr_manager=None,
    agents=None,
    worktrees=None,
    fetcher=None,
    **config_overrides,
):
    cfg = config or _make_config(tmp_path, **config_overrides)
    st = state or _make_state(tmp_path)
    bus = AsyncMock()
    bus.publish = AsyncMock()
    prs = pr_manager or AsyncMock()
    ag = agents or AsyncMock()
    wt = worktrees or AsyncMock()
    ft = fetcher or AsyncMock()
    return PRUnsticker(cfg, st, bus, prs, ag, wt, ft), st, prs, ag, wt, ft, bus


def _make_hitl_item(issue: int = 42, **kwargs) -> HITLItem:
    return HITLItem(
        issue=issue,
        title=kwargs.get("title", f"Issue #{issue}"),
        branch=kwargs.get("branch", f"agent/issue-{issue}"),
        **{k: v for k, v in kwargs.items() if k not in ("title", "branch")},
    )


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
        }


class TestMergeConflictFilter:
    @pytest.mark.asyncio
    async def test_filters_to_merge_conflict_causes_only(self, tmp_path: Path) -> None:
        unsticker, state, prs, agents, wt, fetcher, bus = _make_unsticker(tmp_path)

        # Set up causes: only item 1 has merge conflict
        state.set_hitl_cause(1, "Merge conflict with main")
        state.set_hitl_cause(2, "CI failure in tests")
        state.set_hitl_cause(3, "Review rejected")

        items = [
            _make_hitl_item(issue=1),
            _make_hitl_item(issue=2),
            _make_hitl_item(issue=3),
        ]

        # Make the fetcher return None so _process_item fails fast
        fetcher.fetch_issue_by_number = AsyncMock(return_value=None)

        stats = await unsticker.unstick(items)

        # Only issue 1 should be processed (merge conflict)
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
        from models import GitHubIssue

        issue = GitHubIssue(
            number=42,
            title="Test issue",
            body="body",
            labels=["hydraflow-hitl"],
        )
        unsticker, state, prs, agents, wt, fetcher, bus = _make_unsticker(tmp_path)
        state.set_hitl_cause(42, "Merge conflict")
        state.set_hitl_origin(42, "hydraflow-review")

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        wt.start_merge_main = AsyncMock(return_value=True)  # Clean merge
        wt.create = AsyncMock(return_value=tmp_path / "worktrees" / "issue-42")
        prs.push_branch = AsyncMock(return_value=True)

        # Create worktree dir so it "exists"
        wt_dir = tmp_path / "worktrees" / "issue-42"
        wt_dir.mkdir(parents=True)

        stats = await unsticker.unstick([_make_hitl_item(42)])

        assert stats["resolved"] == 1
        assert stats["failed"] == 0
        # Agent should NOT have been called
        agents._execute.assert_not_called()
        # Branch should have been pushed
        prs.push_branch.assert_called_once()


class TestSuccessfulResolution:
    @pytest.mark.asyncio
    async def test_successful_conflict_resolution(self, tmp_path: Path) -> None:
        from models import GitHubIssue

        issue = GitHubIssue(
            number=42,
            title="Test issue",
            body="body",
            labels=["hydraflow-hitl"],
        )
        unsticker, state, prs, agents, wt, fetcher, bus = _make_unsticker(tmp_path)
        state.set_hitl_cause(42, "Merge conflict")
        state.set_hitl_origin(42, "hydraflow-review")

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        wt.start_merge_main = AsyncMock(return_value=False)  # Conflicts exist
        wt.create = AsyncMock(return_value=tmp_path / "worktrees" / "issue-42")

        agents._build_command = MagicMock(return_value=["claude", "-p"])
        agents._execute = AsyncMock(return_value="resolved conflicts")
        agents._verify_result = AsyncMock(return_value=(True, "OK"))

        prs.push_branch = AsyncMock(return_value=True)

        # Create worktree dir
        wt_dir = tmp_path / "worktrees" / "issue-42"
        wt_dir.mkdir(parents=True)

        # Also create .hydraflow/logs for transcript saving
        (tmp_path / "repo" / ".hydraflow" / "logs").mkdir(parents=True)

        stats = await unsticker.unstick([_make_hitl_item(42)])

        assert stats["resolved"] == 1
        assert stats["failed"] == 0

        # Verify label swaps via swap_pipeline_labels
        prs.swap_pipeline_labels.assert_any_call(42, "hydraflow-hitl-active")
        prs.swap_pipeline_labels.assert_any_call(42, "hydraflow-review")

        # Verify state cleared
        assert state.get_hitl_origin(42) is None
        assert state.get_hitl_cause(42) is None


class TestFailedResolution:
    @pytest.mark.asyncio
    async def test_failed_resolution_releases_back_to_hitl(
        self, tmp_path: Path
    ) -> None:
        from models import GitHubIssue

        issue = GitHubIssue(
            number=42,
            title="Test issue",
            body="body",
            labels=["hydraflow-hitl"],
        )
        unsticker, state, prs, agents, wt, fetcher, bus = _make_unsticker(
            tmp_path, max_merge_conflict_fix_attempts=2
        )
        state.set_hitl_cause(42, "Merge conflict")

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        wt.start_merge_main = AsyncMock(return_value=False)
        wt.abort_merge = AsyncMock()

        agents._build_command = MagicMock(return_value=["claude", "-p"])
        agents._execute = AsyncMock(return_value="failed transcript")
        agents._verify_result = AsyncMock(return_value=(False, "make quality failed"))

        # Create worktree dir
        wt_dir = tmp_path / "worktrees" / "issue-42"
        wt_dir.mkdir(parents=True)
        (tmp_path / "repo" / ".hydraflow" / "logs").mkdir(parents=True)

        stats = await unsticker.unstick([_make_hitl_item(42)])

        assert stats["failed"] == 1
        assert stats["resolved"] == 0

        # Should swap back to hydraflow-hitl label
        prs.swap_pipeline_labels.assert_any_call(42, "hydraflow-hitl")

        # Comment should mention failure
        comment_calls = [
            call
            for call in prs.post_comment.call_args_list
            if "could not resolve" in call.args[1].lower()
        ]
        assert len(comment_calls) == 1


class TestBatchSizeLimit:
    @pytest.mark.asyncio
    async def test_batch_size_limits_processing(self, tmp_path: Path) -> None:
        unsticker, state, prs, agents, wt, fetcher, bus = _make_unsticker(
            tmp_path, pr_unstick_batch_size=2
        )

        # All items have merge conflict cause
        for i in range(5):
            state.set_hitl_cause(i + 1, "Merge conflict")

        items = [_make_hitl_item(issue=i + 1) for i in range(5)]

        # Fetcher returns None so processing fails fast
        fetcher.fetch_issue_by_number = AsyncMock(return_value=None)

        stats = await unsticker.unstick(items)

        # Only 2 should be processed (batch size)
        assert stats["processed"] == 2


class TestConflictPromptUsesSharedBuilder:
    """Verify that _resolve_conflicts delegates to the shared builder."""

    @pytest.mark.asyncio
    async def test_prompt_includes_urls(self, tmp_path: Path) -> None:
        from models import GitHubIssue

        issue = GitHubIssue(
            number=42,
            title="Fix the widget",
            body="Widget description",
            labels=[],
            url="https://github.com/test-org/test-repo/issues/42",
        )
        unsticker, state, prs, agents, wt, fetcher, bus = _make_unsticker(tmp_path)
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

        # Capture the prompt passed to agent._execute
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

        # Create the repo root so .hydraflow/logs can be created
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
    unsticker, state, prs, agents, wt, fetcher, bus = _make_unsticker(tmp_path)
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
