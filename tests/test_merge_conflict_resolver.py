"""Tests for merge_conflict_resolver.py — MergeConflictResolver class."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import HydraFlowConfig

from models import ConflictResolutionResult
from tests.conftest import PRInfoFactory, TaskFactory
from tests.helpers import ConfigFactory, make_conflict_resolver


class TestMergeConflictResolver:
    """Tests for the MergeConflictResolver class."""

    @pytest.mark.asyncio
    async def test_merge_with_main_clean_merge(self, config: HydraFlowConfig) -> None:
        """When merge_main succeeds, should push and return True."""
        resolver = make_conflict_resolver(config)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        resolver._worktrees.merge_main = AsyncMock(return_value=True)
        resolver._prs.push_branch = AsyncMock(return_value=True)
        publish_fn = AsyncMock()
        escalate_fn = AsyncMock()

        result = await resolver.merge_with_main(
            pr,
            issue,
            config.worktree_path_for_issue(42),
            0,
            escalate_fn=escalate_fn,
            publish_fn=publish_fn,
        )

        assert result is True
        resolver._prs.push_branch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_merge_with_main_escalates_on_failure(
        self, config: HydraFlowConfig
    ) -> None:
        """When conflict resolution fails, should escalate and return False."""
        resolver = make_conflict_resolver(config)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        resolver._worktrees.merge_main = AsyncMock(return_value=False)
        publish_fn = AsyncMock()
        escalate_fn = AsyncMock()

        result = await resolver.merge_with_main(
            pr,
            issue,
            config.worktree_path_for_issue(42),
            0,
            escalate_fn=escalate_fn,
            publish_fn=publish_fn,
        )

        assert result is False
        escalate_fn.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_resolve_returns_false_when_no_agents(
        self, config: HydraFlowConfig
    ) -> None:
        """Without an agent runner, should return False immediately."""
        resolver = make_conflict_resolver(config)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        result = await resolver.resolve_merge_conflicts(
            pr, issue, config.worktree_path_for_issue(42), worker_id=0
        )

        assert result == ConflictResolutionResult(success=False, used_rebuild=False)

    @pytest.mark.asyncio
    async def test_resolve_returns_true_on_clean_merge(
        self, config: HydraFlowConfig
    ) -> None:
        """If start_merge_main returns True (no conflicts), return True."""
        mock_agents = AsyncMock()
        resolver = make_conflict_resolver(config, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        resolver._worktrees.start_merge_main = AsyncMock(return_value=True)

        result = await resolver.resolve_merge_conflicts(
            pr, issue, config.worktree_path_for_issue(42), worker_id=0
        )

        assert result == ConflictResolutionResult(success=True, used_rebuild=False)
        mock_agents._execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_resolve_runs_agent_on_conflicts(
        self, config: HydraFlowConfig
    ) -> None:
        """Should run the agent and verify quality when there are conflicts."""
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript")
        mock_agents._verify_result = AsyncMock(return_value=(True, ""))
        resolver = make_conflict_resolver(config, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        resolver._worktrees.start_merge_main = AsyncMock(return_value=False)

        result = await resolver.resolve_merge_conflicts(
            pr, issue, config.worktree_path_for_issue(42), worker_id=0
        )

        assert result == ConflictResolutionResult(success=True, used_rebuild=False)
        mock_agents._build_command.assert_called_once()
        mock_agents._execute.assert_awaited_once()
        telemetry = mock_agents._execute.await_args.kwargs["telemetry_stats"]
        assert "pruned_chars_total" in telemetry

    @pytest.mark.asyncio
    async def test_saves_transcript(self, config: HydraFlowConfig) -> None:
        """A transcript file should be saved for each attempt."""
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript content")
        mock_agents._verify_result = AsyncMock(return_value=(True, ""))
        resolver = make_conflict_resolver(config, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        resolver._worktrees.start_merge_main = AsyncMock(return_value=False)

        await resolver.resolve_merge_conflicts(
            pr, issue, config.worktree_path_for_issue(42), worker_id=0
        )

        log_dir = config.repo_root / ".hydraflow" / "logs"
        assert (log_dir / "merge_conflict-pr-101-attempt-1.txt").exists()


class TestSourceParameter:
    """Tests for the source parameter in resolve_merge_conflicts and fresh_branch_rebuild."""

    @pytest.mark.asyncio
    async def test_save_transcript_uses_source_prefix(
        self, config: HydraFlowConfig
    ) -> None:
        """Verify that transcripts use the source parameter for filename prefix."""
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript content")
        mock_agents._verify_result = AsyncMock(return_value=(True, ""))
        resolver = make_conflict_resolver(config, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        resolver._worktrees.start_merge_main = AsyncMock(return_value=False)

        await resolver.resolve_merge_conflicts(
            pr,
            issue,
            config.worktree_path_for_issue(42),
            worker_id=0,
            source="pr_unsticker",
        )

        log_dir = config.repo_root / ".hydraflow" / "logs"
        assert (log_dir / "pr_unsticker-pr-101-attempt-1.txt").exists()

    @pytest.mark.asyncio
    async def test_source_passed_to_memory_suggestion(
        self, config: HydraFlowConfig
    ) -> None:
        """Verify safe_file_memory_suggestion gets the correct source string."""
        from unittest.mock import patch

        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript")
        mock_agents._verify_result = AsyncMock(return_value=(True, ""))
        resolver = make_conflict_resolver(config, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        resolver._worktrees.start_merge_main = AsyncMock(return_value=False)

        with patch(
            "merge_conflict_resolver.safe_file_memory_suggestion",
            new_callable=AsyncMock,
        ) as mock_fms:
            await resolver.resolve_merge_conflicts(
                pr,
                issue,
                config.worktree_path_for_issue(42),
                worker_id=0,
                source="test_source",
            )

            mock_fms.assert_awaited_once()
            assert mock_fms.call_args.args[1] == "test_source"


class TestWorkerIdNone:
    """Tests for worker_id=None behavior (PRUnsticker delegation)."""

    @pytest.mark.asyncio
    async def test_resolve_with_worker_id_none_skips_status_publish(
        self, config: HydraFlowConfig
    ) -> None:
        """Verify no REVIEW_UPDATE events when worker_id is None."""
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript")
        mock_agents._verify_result = AsyncMock(return_value=(True, ""))
        resolver = make_conflict_resolver(config, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        resolver._worktrees.start_merge_main = AsyncMock(return_value=False)

        # Spy on the event bus
        publish_calls = []
        original_publish = resolver._bus.publish

        async def track_publish(event):
            publish_calls.append(event)
            return await original_publish(event)

        resolver._bus.publish = track_publish

        await resolver.resolve_merge_conflicts(
            pr, issue, config.worktree_path_for_issue(42), worker_id=None
        )

        # No REVIEW_UPDATE events should have been published
        review_events = [
            e
            for e in publish_calls
            if hasattr(e, "type") and e.type.value == "review_update"
        ]
        assert review_events == []

    @pytest.mark.asyncio
    async def test_resolve_with_worker_id_publishes_status(
        self, config: HydraFlowConfig
    ) -> None:
        """Verify REVIEW_UPDATE events are published when worker_id is provided."""
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript")
        mock_agents._verify_result = AsyncMock(return_value=(True, ""))
        resolver = make_conflict_resolver(config, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        resolver._worktrees.start_merge_main = AsyncMock(return_value=False)

        publish_calls = []
        original_publish = resolver._bus.publish

        async def track_publish(event):
            publish_calls.append(event)
            return await original_publish(event)

        resolver._bus.publish = track_publish

        await resolver.resolve_merge_conflicts(
            pr, issue, config.worktree_path_for_issue(42), worker_id=1
        )

        # Should have published at least one REVIEW_UPDATE event
        review_events = [
            e
            for e in publish_calls
            if hasattr(e, "type") and e.type.value == "review_update"
        ]
        assert len(review_events) >= 1


class TestSaveTranscriptOSError:
    """Tests for OSError handling in _save_conflict_transcript."""

    def test_save_transcript_handles_oserror(
        self, config: HydraFlowConfig, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Verify OSError is caught and logged."""
        resolver = make_conflict_resolver(config)

        def _raise_oserror(*args, **kwargs):
            raise OSError("No space left on device")

        import pytest as _pytest

        with _pytest.MonkeyPatch.context() as mp:
            mp.setattr(Path, "write_text", _raise_oserror)
            resolver.save_conflict_transcript(101, 42, 1, "transcript content")

        assert "Could not save conflict transcript" in caplog.text

    def test_save_transcript_uses_source_in_filename(
        self, config: HydraFlowConfig
    ) -> None:
        """Verify the source parameter is used in the filename."""
        resolver = make_conflict_resolver(config)
        resolver.save_conflict_transcript(101, 42, 1, "content", source="my_source")
        log_dir = config.repo_root / ".hydraflow" / "logs"
        assert (log_dir / "my_source-pr-101-attempt-1.txt").exists()


class TestFreshBranchRebuild:
    """Tests for the fresh branch rebuild fallback."""

    @pytest.mark.asyncio
    async def test_fresh_rebuild_called_after_merge_exhaustion(
        self, tmp_path: Path
    ) -> None:
        """All merge attempts fail → rebuild is attempted."""
        cfg = ConfigFactory.create(
            max_merge_conflict_fix_attempts=1,
            enable_fresh_branch_rebuild=True,
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript")
        # First call (merge attempt) fails, second call (rebuild) succeeds
        mock_agents._verify_result = AsyncMock(
            side_effect=[(False, "quality failed"), (True, "")]
        )
        resolver = make_conflict_resolver(cfg, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        resolver._worktrees.start_merge_main = AsyncMock(return_value=False)
        resolver._worktrees.abort_merge = AsyncMock()
        resolver._worktrees.destroy = AsyncMock()
        resolver._worktrees.create = AsyncMock(
            return_value=tmp_path / "worktrees" / "issue-42"
        )
        resolver._prs.get_pr_diff = AsyncMock(return_value="diff --git a/foo.py\n+bar")

        result = await resolver.resolve_merge_conflicts(
            pr, issue, tmp_path / "worktrees" / "issue-42", worker_id=0
        )

        assert result.success is True
        assert result.used_rebuild is True
        resolver._worktrees.destroy.assert_awaited_once()
        resolver._worktrees.create.assert_awaited_once()
        resolver._prs.get_pr_diff.assert_awaited_once_with(pr.number)

    @pytest.mark.asyncio
    async def test_fresh_rebuild_succeeds(self, tmp_path: Path) -> None:
        """Full rebuild flow: get diff, destroy, create, agent, verify."""
        cfg = ConfigFactory.create(
            enable_fresh_branch_rebuild=True,
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="rebuilt transcript")
        mock_agents._verify_result = AsyncMock(return_value=(True, ""))
        resolver = make_conflict_resolver(cfg, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        new_wt = tmp_path / "worktrees" / "issue-42"
        resolver._worktrees.destroy = AsyncMock()
        resolver._worktrees.create = AsyncMock(return_value=new_wt)
        resolver._prs.get_pr_diff = AsyncMock(return_value="diff content")

        result = await resolver.fresh_branch_rebuild(pr, issue, worker_id=0)

        assert result is True
        resolver._worktrees.destroy.assert_awaited_once_with(pr.issue_number)
        resolver._worktrees.create.assert_awaited_once_with(pr.issue_number, pr.branch)
        mock_agents._build_command.assert_called_once_with(new_wt)
        mock_agents._execute.assert_awaited_once()
        mock_agents._verify_result.assert_awaited_once()
        telemetry = mock_agents._execute.await_args.kwargs["telemetry_stats"]
        assert "pruned_chars_total" in telemetry

    @pytest.mark.asyncio
    async def test_fresh_rebuild_skipped_when_disabled(self, tmp_path: Path) -> None:
        """Config flag off → returns False directly."""
        cfg = ConfigFactory.create(
            enable_fresh_branch_rebuild=False,
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mock_agents = AsyncMock()
        resolver = make_conflict_resolver(cfg, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        result = await resolver.fresh_branch_rebuild(pr, issue, worker_id=0)

        assert result is False
        mock_agents._execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_fresh_rebuild_skipped_when_no_agents(self, tmp_path: Path) -> None:
        """No agent runner → returns False."""
        cfg = ConfigFactory.create(
            enable_fresh_branch_rebuild=True,
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        resolver = make_conflict_resolver(cfg, agents=None)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        result = await resolver.fresh_branch_rebuild(pr, issue, worker_id=0)

        assert result is False

    @pytest.mark.asyncio
    async def test_fresh_rebuild_skipped_when_empty_diff(self, tmp_path: Path) -> None:
        """Empty diff → returns False without creating worktree."""
        cfg = ConfigFactory.create(
            enable_fresh_branch_rebuild=True,
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mock_agents = AsyncMock()
        resolver = make_conflict_resolver(cfg, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        resolver._prs.get_pr_diff = AsyncMock(return_value="")

        result = await resolver.fresh_branch_rebuild(pr, issue, worker_id=0)

        assert result is False
        resolver._worktrees.destroy.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_fresh_rebuild_uses_force_push(self, tmp_path: Path) -> None:
        """After rebuild, merge_with_main should use force_push_branch."""
        cfg = ConfigFactory.create(
            max_merge_conflict_fix_attempts=1,
            enable_fresh_branch_rebuild=True,
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript")
        # Merge attempt fails, rebuild succeeds
        mock_agents._verify_result = AsyncMock(
            side_effect=[(False, "failed"), (True, "")]
        )
        resolver = make_conflict_resolver(cfg, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        new_wt = tmp_path / "worktrees" / "issue-42"
        resolver._worktrees.merge_main = AsyncMock(return_value=False)
        resolver._worktrees.start_merge_main = AsyncMock(return_value=False)
        resolver._worktrees.abort_merge = AsyncMock()
        resolver._worktrees.destroy = AsyncMock()
        resolver._worktrees.create = AsyncMock(return_value=new_wt)
        resolver._prs.get_pr_diff = AsyncMock(return_value="diff content")
        resolver._prs.push_branch = AsyncMock(return_value=True)
        resolver._prs.force_push_branch = AsyncMock(return_value=True)

        publish_fn = AsyncMock()
        escalate_fn = AsyncMock()

        result = await resolver.merge_with_main(
            pr,
            issue,
            new_wt,
            0,
            escalate_fn=escalate_fn,
            publish_fn=publish_fn,
        )

        assert result is True
        resolver._prs.force_push_branch.assert_awaited_once()
        resolver._prs.push_branch.assert_not_awaited()
