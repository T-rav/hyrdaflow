"""Tests for review_phase.py — merge and conflict resolution."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import HydraFlowConfig

from models import ConflictResolutionResult
from tests.conftest import (
    PRInfoFactory,
    TaskFactory,
)
from tests.helpers import make_review_phase

# ---------------------------------------------------------------------------
# _resolve_merge_conflicts
# ---------------------------------------------------------------------------


class TestResolveMergeConflicts:
    """Tests for the _resolve_merge_conflicts method."""

    @pytest.mark.asyncio
    async def test_returns_false_when_no_agents(self, config: HydraFlowConfig) -> None:
        """Without an agent runner, should return False immediately."""
        phase = make_review_phase(config)  # No agents
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        result = await phase._resolve_merge_conflicts(
            pr, issue, config.worktree_base / "issue-42", worker_id=0
        )

        assert result == ConflictResolutionResult(success=False, used_rebuild=False)

    @pytest.mark.asyncio
    async def test_returns_true_when_start_merge_is_clean(
        self, config: HydraFlowConfig
    ) -> None:
        """If start_merge_main returns True (no conflicts), return True."""
        mock_agents = AsyncMock()
        phase = make_review_phase(config, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        phase._worktrees.start_merge_main = AsyncMock(return_value=True)

        result = await phase._resolve_merge_conflicts(
            pr, issue, config.worktree_base / "issue-42", worker_id=0
        )

        assert result == ConflictResolutionResult(success=True, used_rebuild=False)
        # Agent should NOT have been invoked
        mock_agents._execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_runs_agent_and_verifies_on_conflicts(
        self, config: HydraFlowConfig
    ) -> None:
        """Should run the agent and verify quality when there are conflicts."""
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript")
        mock_agents._verify_result = AsyncMock(return_value=(True, ""))
        phase = make_review_phase(config, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        phase._worktrees.start_merge_main = AsyncMock(return_value=False)

        result = await phase._resolve_merge_conflicts(
            pr, issue, config.worktree_base / "issue-42", worker_id=0
        )

        assert result == ConflictResolutionResult(success=True, used_rebuild=False)
        mock_agents._build_command.assert_called_once()
        mock_agents._execute.assert_awaited_once()
        mock_agents._verify_result.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_aborts_merge_on_agent_exception(
        self, config: HydraFlowConfig
    ) -> None:
        """On agent exception on all attempts, should abort merge and return False."""
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(side_effect=RuntimeError("agent crashed"))
        phase = make_review_phase(config, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        phase._worktrees.start_merge_main = AsyncMock(return_value=False)
        phase._worktrees.abort_merge = AsyncMock()

        result = await phase._resolve_merge_conflicts(
            pr, issue, config.worktree_base / "issue-42", worker_id=0
        )

        assert result.success is False
        # abort_merge called between retries + final abort
        assert phase._worktrees.abort_merge.await_count >= 1

    @pytest.mark.asyncio
    async def test_retries_on_verify_failure(self, config: HydraFlowConfig) -> None:
        """Should retry when verify fails, and succeed on second attempt."""
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript")
        mock_agents._verify_result = AsyncMock(
            side_effect=[(False, "quality failed"), (True, "")]
        )
        phase = make_review_phase(config, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        phase._worktrees.start_merge_main = AsyncMock(return_value=False)
        phase._worktrees.abort_merge = AsyncMock()

        result = await phase._resolve_merge_conflicts(
            pr, issue, config.worktree_base / "issue-42", worker_id=0
        )

        assert result == ConflictResolutionResult(success=True, used_rebuild=False)
        assert mock_agents._execute.await_count == 2
        assert mock_agents._verify_result.await_count == 2

    @pytest.mark.asyncio
    async def test_exhausts_all_attempts_then_returns_false(
        self, config: HydraFlowConfig
    ) -> None:
        """When all attempts fail verification, should return False."""
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(
            enable_fresh_branch_rebuild=False,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript")
        mock_agents._verify_result = AsyncMock(return_value=(False, "quality failed"))
        phase = make_review_phase(cfg, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        phase._worktrees.start_merge_main = AsyncMock(return_value=False)
        phase._worktrees.abort_merge = AsyncMock()

        result = await phase._resolve_merge_conflicts(
            pr, issue, cfg.worktree_base / "issue-42", worker_id=0
        )

        assert result == ConflictResolutionResult(success=False, used_rebuild=False)
        # Default is 3 attempts
        assert mock_agents._execute.await_count == 3
        assert mock_agents._verify_result.await_count == 3

    @pytest.mark.asyncio
    async def test_feeds_error_to_retry_prompt(self, config: HydraFlowConfig) -> None:
        """On retry, the prompt should include the previous error."""
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript")
        mock_agents._verify_result = AsyncMock(
            side_effect=[(False, "ruff check failed"), (True, "")]
        )
        phase = make_review_phase(config, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        phase._worktrees.start_merge_main = AsyncMock(return_value=False)
        phase._worktrees.abort_merge = AsyncMock()

        await phase._resolve_merge_conflicts(
            pr, issue, config.worktree_base / "issue-42", worker_id=0
        )

        # Second call to _execute should have received a prompt with the error
        second_call_args = mock_agents._execute.call_args_list[1]
        prompt_arg = second_call_args.args[1]
        assert "ruff check failed" in prompt_arg
        assert "Previous Attempt Failed" in prompt_arg

    @pytest.mark.asyncio
    async def test_aborts_merge_between_retries(self, config: HydraFlowConfig) -> None:
        """abort_merge should be called before attempt 2+."""
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript")
        mock_agents._verify_result = AsyncMock(
            side_effect=[(False, "failed"), (True, "")]
        )
        phase = make_review_phase(config, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        phase._worktrees.start_merge_main = AsyncMock(return_value=False)
        phase._worktrees.abort_merge = AsyncMock()

        await phase._resolve_merge_conflicts(
            pr, issue, config.worktree_base / "issue-42", worker_id=0
        )

        # abort_merge called once before attempt 2
        phase._worktrees.abort_merge.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_saves_transcript_per_attempt(self, config: HydraFlowConfig) -> None:
        """A transcript file should be saved for each attempt."""
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript content")
        mock_agents._verify_result = AsyncMock(
            side_effect=[(False, "failed"), (True, "")]
        )
        phase = make_review_phase(config, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        phase._worktrees.start_merge_main = AsyncMock(return_value=False)
        phase._worktrees.abort_merge = AsyncMock()

        await phase._resolve_merge_conflicts(
            pr, issue, config.worktree_base / "issue-42", worker_id=0
        )

        log_dir = config.repo_root / ".hydraflow" / "logs"
        assert (log_dir / "merge_conflict-pr-101-attempt-1.txt").exists()
        assert (log_dir / "merge_conflict-pr-101-attempt-2.txt").exists()

    @pytest.mark.asyncio
    async def test_respects_config_max_attempts(self, config: HydraFlowConfig) -> None:
        """Should honor a custom max_merge_conflict_fix_attempts value."""
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(
            max_merge_conflict_fix_attempts=1,
            enable_fresh_branch_rebuild=False,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript")
        mock_agents._verify_result = AsyncMock(return_value=(False, "quality failed"))
        phase = make_review_phase(cfg, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        phase._worktrees.start_merge_main = AsyncMock(return_value=False)
        phase._worktrees.abort_merge = AsyncMock()

        result = await phase._resolve_merge_conflicts(
            pr, issue, cfg.worktree_base / "issue-42", worker_id=0
        )

        assert result == ConflictResolutionResult(success=False, used_rebuild=False)
        assert mock_agents._execute.await_count == 1

    @pytest.mark.asyncio
    async def test_zero_attempts_returns_false(self, config: HydraFlowConfig) -> None:
        """With max_merge_conflict_fix_attempts=0, should return False without trying."""
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(
            max_merge_conflict_fix_attempts=0,
            enable_fresh_branch_rebuild=False,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        mock_agents = AsyncMock()
        phase = make_review_phase(cfg, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        phase._worktrees.start_merge_main = AsyncMock(return_value=False)
        phase._worktrees.abort_merge = AsyncMock()

        result = await phase._resolve_merge_conflicts(
            pr, issue, cfg.worktree_base / "issue-42", worker_id=0
        )

        assert result == ConflictResolutionResult(success=False, used_rebuild=False)
        mock_agents._execute.assert_not_awaited()
        # Final abort_merge should still be called
        phase._worktrees.abort_merge.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_conflict_resolution_calls_file_memory_suggestion(
        self, config: HydraFlowConfig
    ) -> None:
        """safe_file_memory_suggestion should be called with the conflict transcript."""
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript with suggestion")
        mock_agents._verify_result = AsyncMock(return_value=(True, ""))
        phase = make_review_phase(config, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        phase._worktrees.start_merge_main = AsyncMock(return_value=False)

        with patch(
            "merge_conflict_resolver.safe_file_memory_suggestion",
            new_callable=AsyncMock,
        ) as mock_fms:
            await phase._resolve_merge_conflicts(
                pr, issue, config.worktree_base / "issue-42", worker_id=0
            )

            mock_fms.assert_awaited_once_with(
                "transcript with suggestion",
                "merge_conflict",
                f"PR #{pr.number}",
                phase._config,
                phase._prs,
                phase._state,
            )

    @pytest.mark.asyncio
    async def test_conflict_resolution_memory_failure_does_not_propagate(
        self, config: HydraFlowConfig
    ) -> None:
        """Exceptions from file_memory_suggestion must not break conflict resolution."""
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript")
        mock_agents._verify_result = AsyncMock(return_value=(True, ""))
        phase = make_review_phase(config, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        phase._worktrees.start_merge_main = AsyncMock(return_value=False)

        with patch(
            "phase_utils.file_memory_suggestion",
            new_callable=AsyncMock,
            side_effect=RuntimeError("network error"),
        ):
            result = await phase._resolve_merge_conflicts(
                pr, issue, config.worktree_base / "issue-42", worker_id=0
            )

            assert result == ConflictResolutionResult(success=True, used_rebuild=False)


class TestMergeWithMain:
    """Unit tests for the _merge_with_main helper."""

    @pytest.mark.asyncio
    async def test_returns_true_on_clean_merge(self, config: HydraFlowConfig) -> None:
        """When merge_main succeeds, should push and return True."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._worktrees.merge_main = AsyncMock(return_value=True)
        phase._prs.push_branch = AsyncMock(return_value=True)

        result = await phase._merge_with_main(
            pr, issue, config.worktree_base / "issue-42", 0
        )

        assert result is True
        phase._prs.push_branch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_true_after_conflict_resolution(
        self, config: HydraFlowConfig
    ) -> None:
        """When merge fails but conflict resolution succeeds, should return True."""
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript")
        mock_agents._verify_result = AsyncMock(return_value=(True, ""))
        phase = make_review_phase(config, agents=mock_agents)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._worktrees.merge_main = AsyncMock(return_value=False)
        phase._worktrees.start_merge_main = AsyncMock(return_value=False)
        phase._prs.push_branch = AsyncMock(return_value=True)

        result = await phase._merge_with_main(
            pr, issue, config.worktree_base / "issue-42", 0
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_and_escalates_on_failure(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """When conflict resolution fails, should escalate and return False."""
        phase = make_review_phase(config, event_bus=event_bus)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._worktrees.merge_main = AsyncMock(return_value=False)
        phase._prs.push_branch = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()

        result = await phase._merge_with_main(
            pr, issue, config.worktree_base / "issue-42", 0
        )

        assert result is False
        assert phase._state.get_hitl_origin(42) == "hydraflow-review"
