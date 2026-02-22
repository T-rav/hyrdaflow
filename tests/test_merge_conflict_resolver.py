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

from events import EventBus
from merge_conflict_resolver import MergeConflictResolver
from state import StateTracker
from tests.conftest import IssueFactory, PRInfoFactory


def _make_resolver(config: HydraFlowConfig, *, agents=None) -> MergeConflictResolver:
    """Build a MergeConflictResolver with standard mock dependencies."""
    state = StateTracker(config.state_file)
    return MergeConflictResolver(
        config=config,
        worktrees=AsyncMock(),
        agents=agents,
        prs=AsyncMock(),
        bus=EventBus(),
        state=state,
        summarizer=None,
    )


class TestMergeConflictResolver:
    """Tests for the MergeConflictResolver class."""

    @pytest.mark.asyncio
    async def test_merge_with_main_clean_merge(self, config: HydraFlowConfig) -> None:
        """When merge_main succeeds, should push and return True."""
        resolver = _make_resolver(config)
        pr = PRInfoFactory.create()
        issue = IssueFactory.create()

        resolver._worktrees.merge_main = AsyncMock(return_value=True)
        resolver._prs.push_branch = AsyncMock(return_value=True)
        publish_fn = AsyncMock()
        escalate_fn = AsyncMock()

        result = await resolver.merge_with_main(
            pr,
            issue,
            config.worktree_base / "issue-42",
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
        resolver = _make_resolver(config)
        pr = PRInfoFactory.create()
        issue = IssueFactory.create()

        resolver._worktrees.merge_main = AsyncMock(return_value=False)
        publish_fn = AsyncMock()
        escalate_fn = AsyncMock()

        result = await resolver.merge_with_main(
            pr,
            issue,
            config.worktree_base / "issue-42",
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
        resolver = _make_resolver(config)
        pr = PRInfoFactory.create()
        issue = IssueFactory.create()

        result = await resolver.resolve_merge_conflicts(
            pr, issue, config.worktree_base / "issue-42", worker_id=0
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_resolve_returns_true_on_clean_merge(
        self, config: HydraFlowConfig
    ) -> None:
        """If start_merge_main returns True (no conflicts), return True."""
        mock_agents = AsyncMock()
        resolver = _make_resolver(config, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = IssueFactory.create()

        resolver._worktrees.start_merge_main = AsyncMock(return_value=True)

        result = await resolver.resolve_merge_conflicts(
            pr, issue, config.worktree_base / "issue-42", worker_id=0
        )

        assert result is True
        mock_agents._execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_resolve_runs_agent_on_conflicts(
        self, config: HydraFlowConfig
    ) -> None:
        """Should run the agent and verify quality when there are conflicts."""
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript")
        mock_agents._verify_result = AsyncMock(return_value=(True, ""))
        resolver = _make_resolver(config, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = IssueFactory.create()

        resolver._worktrees.start_merge_main = AsyncMock(return_value=False)

        result = await resolver.resolve_merge_conflicts(
            pr, issue, config.worktree_base / "issue-42", worker_id=0
        )

        assert result is True
        mock_agents._build_command.assert_called_once()
        mock_agents._execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_saves_transcript(self, config: HydraFlowConfig) -> None:
        """A transcript file should be saved for each attempt."""
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript content")
        mock_agents._verify_result = AsyncMock(return_value=(True, ""))
        resolver = _make_resolver(config, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = IssueFactory.create()

        resolver._worktrees.start_merge_main = AsyncMock(return_value=False)

        await resolver.resolve_merge_conflicts(
            pr, issue, config.worktree_base / "issue-42", worker_id=0
        )

        log_dir = config.repo_root / ".hydraflow" / "logs"
        assert (log_dir / "conflict-pr-101-attempt-1.txt").exists()
