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

from models import ConflictResolutionResult, HitlEscalation, LoopResult
from tests.conftest import PRInfoFactory, TaskFactory
from tests.helpers import ConfigFactory, make_conflict_resolver


class TestMergeConflictResolver:
    @pytest.mark.asyncio
    async def test_merge_with_main_clean_merge(self, config: HydraFlowConfig) -> None:
        """When merge_main succeeds, should push and return True."""
        resolver = make_conflict_resolver(config)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        resolver._workspaces.merge_main = AsyncMock(return_value=True)
        resolver._prs.push_branch = AsyncMock(return_value=True)
        publish_fn = AsyncMock()
        escalate_fn = AsyncMock()

        result = await resolver.merge_with_main(
            pr,
            issue,
            config.workspace_path_for_issue(42),
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

        resolver._workspaces.merge_main = AsyncMock(return_value=False)
        publish_fn = AsyncMock()
        escalate_fn = AsyncMock()

        result = await resolver.merge_with_main(
            pr,
            issue,
            config.workspace_path_for_issue(42),
            0,
            escalate_fn=escalate_fn,
            publish_fn=publish_fn,
        )

        assert result is False
        escalate_fn.assert_awaited_once()
        esc = escalate_fn.await_args.args[0]
        assert isinstance(esc, HitlEscalation)
        assert esc.cause == "Merge conflict with main branch"
        assert esc.pr_number == pr.number
        assert esc.issue_number == pr.issue_number

    @pytest.mark.asyncio
    async def test_resolve_returns_false_when_no_agents(
        self, config: HydraFlowConfig
    ) -> None:
        """Without an agent runner, should return False immediately."""
        resolver = make_conflict_resolver(config)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        result = await resolver.resolve_merge_conflicts(
            pr, issue, config.workspace_path_for_issue(42), worker_id=0
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

        resolver._workspaces.start_merge_main = AsyncMock(return_value=True)

        result = await resolver.resolve_merge_conflicts(
            pr, issue, config.workspace_path_for_issue(42), worker_id=0
        )

        assert result == ConflictResolutionResult(success=True, used_rebuild=False)
        mock_agents._execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_resolve_runs_agent_on_conflicts(
        self, config: HydraFlowConfig
    ) -> None:
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript")
        mock_agents._verify_result = AsyncMock(
            return_value=LoopResult(passed=True, summary="")
        )
        resolver = make_conflict_resolver(config, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        resolver._workspaces.start_merge_main = AsyncMock(return_value=False)

        result = await resolver.resolve_merge_conflicts(
            pr, issue, config.workspace_path_for_issue(42), worker_id=0
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
        mock_agents._verify_result = AsyncMock(
            return_value=LoopResult(passed=True, summary="")
        )
        resolver = make_conflict_resolver(config, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        resolver._workspaces.start_merge_main = AsyncMock(return_value=False)

        await resolver.resolve_merge_conflicts(
            pr, issue, config.workspace_path_for_issue(42), worker_id=0
        )

        log_dir = config.repo_root / ".hydraflow" / "logs"
        assert (log_dir / "merge_conflict-pr-101-attempt-1.txt").exists()


class TestSourceParameter:
    @pytest.mark.asyncio
    async def test_save_transcript_uses_source_prefix(
        self, config: HydraFlowConfig
    ) -> None:
        """Verify that transcripts use the source parameter for filename prefix."""
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript content")
        mock_agents._verify_result = AsyncMock(
            return_value=LoopResult(passed=True, summary="")
        )
        resolver = make_conflict_resolver(config, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        resolver._workspaces.start_merge_main = AsyncMock(return_value=False)

        await resolver.resolve_merge_conflicts(
            pr,
            issue,
            config.workspace_path_for_issue(42),
            worker_id=0,
            source="pr_unsticker",
        )

        log_dir = config.repo_root / ".hydraflow" / "logs"
        assert (log_dir / "pr_unsticker-pr-101-attempt-1.txt").exists()

    @pytest.mark.asyncio
    async def test_source_passed_to_memory_suggestion(
        self, config: HydraFlowConfig
    ) -> None:
        """Verify _suggest_memory gets the correct source string."""
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript")
        mock_agents._verify_result = AsyncMock(
            return_value=LoopResult(passed=True, summary="")
        )
        resolver = make_conflict_resolver(config, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        resolver._workspaces.start_merge_main = AsyncMock(return_value=False)
        resolver._suggest_memory = AsyncMock()

        await resolver.resolve_merge_conflicts(
            pr,
            issue,
            config.workspace_path_for_issue(42),
            worker_id=0,
            source="test_source",
        )

        resolver._suggest_memory.assert_awaited_once()
        assert resolver._suggest_memory.call_args.args[1] == "test_source"


class TestWorkerIdNone:
    @pytest.mark.asyncio
    async def test_resolve_with_worker_id_none_skips_status_publish(
        self, config: HydraFlowConfig
    ) -> None:
        """Verify no REVIEW_UPDATE events when worker_id is None."""
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript")
        mock_agents._verify_result = AsyncMock(
            return_value=LoopResult(passed=True, summary="")
        )
        resolver = make_conflict_resolver(config, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        resolver._workspaces.start_merge_main = AsyncMock(return_value=False)

        # Spy on the event bus
        publish_calls = []
        original_publish = resolver._bus.publish

        async def track_publish(event):
            publish_calls.append(event)
            return await original_publish(event)

        resolver._bus.publish = track_publish

        await resolver.resolve_merge_conflicts(
            pr, issue, config.workspace_path_for_issue(42), worker_id=None
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
        mock_agents._verify_result = AsyncMock(
            return_value=LoopResult(passed=True, summary="")
        )
        resolver = make_conflict_resolver(config, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        resolver._workspaces.start_merge_main = AsyncMock(return_value=False)

        publish_calls = []
        original_publish = resolver._bus.publish

        async def track_publish(event):
            publish_calls.append(event)
            return await original_publish(event)

        resolver._bus.publish = track_publish

        await resolver.resolve_merge_conflicts(
            pr, issue, config.workspace_path_for_issue(42), worker_id=1
        )

        # Should have published at least one REVIEW_UPDATE event
        review_events = [
            e
            for e in publish_calls
            if hasattr(e, "type") and e.type.value == "review_update"
        ]
        assert len(review_events) >= 1


class TestSaveTranscriptOSError:
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
    @pytest.mark.asyncio
    async def test_fresh_rebuild_called_after_merge_exhaustion(
        self, tmp_path: Path
    ) -> None:
        """All merge attempts fail → rebuild is attempted."""
        cfg = ConfigFactory.create(
            max_merge_conflict_fix_attempts=1,
            enable_fresh_branch_rebuild=True,
            repo_root=tmp_path / "repo",
            workspace_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript")
        # First call (merge attempt) fails, second call (rebuild) succeeds
        mock_agents._verify_result = AsyncMock(
            side_effect=[
                LoopResult(passed=False, summary="quality failed"),
                LoopResult(passed=True, summary=""),
            ]
        )
        resolver = make_conflict_resolver(cfg, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        resolver._workspaces.start_merge_main = AsyncMock(return_value=False)
        resolver._workspaces.abort_merge = AsyncMock()
        resolver._workspaces.destroy = AsyncMock()
        resolver._workspaces.create = AsyncMock(
            return_value=tmp_path / "worktrees" / "issue-42"
        )
        resolver._prs.get_pr_diff = AsyncMock(return_value="diff --git a/foo.py\n+bar")

        result = await resolver.resolve_merge_conflicts(
            pr, issue, tmp_path / "worktrees" / "issue-42", worker_id=0
        )

        assert result.success is True
        assert result.used_rebuild is True
        resolver._workspaces.destroy.assert_awaited_once()
        resolver._workspaces.create.assert_awaited_once()
        resolver._prs.get_pr_diff.assert_awaited_once_with(pr.number)

    @pytest.mark.asyncio
    async def test_fresh_rebuild_succeeds(self, tmp_path: Path) -> None:
        """Full rebuild flow: get diff, destroy, create, agent, verify."""
        cfg = ConfigFactory.create(
            enable_fresh_branch_rebuild=True,
            repo_root=tmp_path / "repo",
            workspace_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="rebuilt transcript")
        mock_agents._verify_result = AsyncMock(
            return_value=LoopResult(passed=True, summary="")
        )
        resolver = make_conflict_resolver(cfg, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        new_wt = cfg.workspace_path_for_issue(pr.issue_number)
        resolver._workspaces.destroy = AsyncMock()
        resolver._workspaces.create = AsyncMock(return_value=new_wt)
        resolver._prs.get_pr_diff = AsyncMock(return_value="diff content")

        result = await resolver.fresh_branch_rebuild(pr, issue, worker_id=0)

        assert result is True
        resolver._workspaces.destroy.assert_awaited_once_with(pr.issue_number)
        resolver._workspaces.create.assert_awaited_once_with(pr.issue_number, pr.branch)
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
            workspace_base=tmp_path / "worktrees",
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
            workspace_base=tmp_path / "worktrees",
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
            workspace_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mock_agents = AsyncMock()
        resolver = make_conflict_resolver(cfg, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        resolver._prs.get_pr_diff = AsyncMock(return_value="")

        result = await resolver.fresh_branch_rebuild(pr, issue, worker_id=0)

        assert result is False
        resolver._workspaces.destroy.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_fresh_rebuild_uses_force_flag(self, tmp_path: Path) -> None:
        """After rebuild, merge_with_main should force push via push_branch(force=True)."""
        cfg = ConfigFactory.create(
            max_merge_conflict_fix_attempts=1,
            enable_fresh_branch_rebuild=True,
            repo_root=tmp_path / "repo",
            workspace_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript")
        # Merge attempt fails, rebuild succeeds
        mock_agents._verify_result = AsyncMock(
            side_effect=[
                LoopResult(passed=False, summary="failed"),
                LoopResult(passed=True, summary=""),
            ]
        )
        resolver = make_conflict_resolver(cfg, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        new_wt = cfg.workspace_path_for_issue(pr.issue_number)
        resolver._workspaces.merge_main = AsyncMock(return_value=False)
        resolver._workspaces.start_merge_main = AsyncMock(return_value=False)
        resolver._workspaces.abort_merge = AsyncMock()
        resolver._workspaces.destroy = AsyncMock()
        resolver._workspaces.create = AsyncMock(return_value=new_wt)
        resolver._prs.get_pr_diff = AsyncMock(return_value="diff content")
        resolver._prs.push_branch = AsyncMock(return_value=True)

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
        resolver._prs.push_branch.assert_awaited_once_with(
            cfg.workspace_path_for_issue(pr.issue_number), pr.branch, force=True
        )


# ---------------------------------------------------------------------------
# PR title update after fresh rebuild
# ---------------------------------------------------------------------------


class TestFreshRebuildTitleUpdate:
    """Ensure fresh_branch_rebuild updates the PR title to canonical format."""

    @pytest.mark.asyncio
    async def test_updates_title_on_success(self, tmp_path: Path) -> None:
        """After successful fresh rebuild, PR title should be updated via PRPort."""
        from pr_manager import PRManager

        cfg = ConfigFactory.create(
            enable_fresh_branch_rebuild=True,
            repo_root=tmp_path / "repo",
            workspace_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="rebuilt transcript")
        mock_agents._verify_result = AsyncMock(
            return_value=LoopResult(passed=True, summary="")
        )
        resolver = make_conflict_resolver(cfg, agents=mock_agents)
        pr = PRInfoFactory.create(number=200, issue_number=77)
        issue = TaskFactory.create(id=77, title="Fix the gizmo")

        new_wt = cfg.workspace_path_for_issue(pr.issue_number)
        resolver._workspaces.destroy = AsyncMock()
        resolver._workspaces.create = AsyncMock(return_value=new_wt)
        resolver._prs.get_pr_diff = AsyncMock(return_value="diff content")
        resolver._prs.update_pr_title = AsyncMock(return_value=True)
        # Resolver now uses self._prs.expected_pr_title (PRPort protocol)
        expected_title = PRManager.expected_pr_title(77, "Fix the gizmo")
        resolver._prs.expected_pr_title = PRManager.expected_pr_title

        result = await resolver.fresh_branch_rebuild(pr, issue, worker_id=0)

        assert result is True
        resolver._prs.update_pr_title.assert_awaited_once_with(200, expected_title)

    @pytest.mark.asyncio
    async def test_no_title_update_on_failure(self, tmp_path: Path) -> None:
        """When fresh rebuild verification fails, title should not be updated."""
        cfg = ConfigFactory.create(
            enable_fresh_branch_rebuild=True,
            repo_root=tmp_path / "repo",
            workspace_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="failed transcript")
        mock_agents._verify_result = AsyncMock(
            return_value=LoopResult(passed=False, summary="quality check failed")
        )
        resolver = make_conflict_resolver(cfg, agents=mock_agents)
        pr = PRInfoFactory.create(number=200, issue_number=77)
        issue = TaskFactory.create(id=77, title="Fix the gizmo")

        new_wt = cfg.workspace_path_for_issue(pr.issue_number)
        resolver._workspaces.destroy = AsyncMock()
        resolver._workspaces.create = AsyncMock(return_value=new_wt)
        resolver._prs.get_pr_diff = AsyncMock(return_value="diff content")
        resolver._prs.update_pr_title = AsyncMock(return_value=True)

        result = await resolver.fresh_branch_rebuild(pr, issue, worker_id=0)

        assert result is False
        resolver._prs.update_pr_title.assert_not_awaited()


# ---------------------------------------------------------------------------
# Architecture layering tests (#5919)
# ---------------------------------------------------------------------------


class TestArchitectureLayering:
    """Verify merge_conflict_resolver does not import from Application/Runner layers."""

    def test_no_agent_import(self) -> None:
        """merge_conflict_resolver must not import AgentRunner directly."""
        import merge_conflict_resolver as mod

        source = Path(mod.__file__).read_text()
        assert "from agent import" not in source
        assert "import agent" not in source.split("\n")[0]

    def test_no_phase_utils_import(self) -> None:
        """merge_conflict_resolver must not import from phase_utils."""
        import merge_conflict_resolver as mod

        source = Path(mod.__file__).read_text()
        assert "from phase_utils import" not in source

    def test_constructor_accepts_agent_port(self) -> None:
        """Constructor should accept AgentPort (not AgentRunner) for agents param."""
        import inspect

        from merge_conflict_resolver import MergeConflictResolver

        sig = inspect.signature(MergeConflictResolver.__init__)
        agents_param = sig.parameters["agents"]
        annotation_str = str(agents_param.annotation)
        assert "AgentPort" in annotation_str
        assert "AgentRunner" not in annotation_str

    @pytest.mark.asyncio
    async def test_suggest_memory_callback_invoked(
        self, config: HydraFlowConfig
    ) -> None:
        """Injected suggest_memory callback should be called on success."""
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript")
        mock_agents._verify_result = AsyncMock(
            return_value=LoopResult(passed=True, summary="")
        )
        suggest_fn = AsyncMock()
        resolver = make_conflict_resolver(
            config, agents=mock_agents, suggest_memory=suggest_fn
        )
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()
        resolver._workspaces.start_merge_main = AsyncMock(return_value=False)

        await resolver.resolve_merge_conflicts(
            pr, issue, config.workspace_path_for_issue(42), worker_id=0
        )

        suggest_fn.assert_awaited_once()
        assert suggest_fn.call_args.args[0] == "transcript"

    @pytest.mark.asyncio
    async def test_suggest_memory_none_does_not_raise(
        self, config: HydraFlowConfig
    ) -> None:
        """When suggest_memory is None, resolve should still succeed."""
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript")
        mock_agents._verify_result = AsyncMock(
            return_value=LoopResult(passed=True, summary="")
        )
        resolver = make_conflict_resolver(
            config, agents=mock_agents, suggest_memory=None
        )
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()
        resolver._workspaces.start_merge_main = AsyncMock(return_value=False)

        result = await resolver.resolve_merge_conflicts(
            pr, issue, config.workspace_path_for_issue(42), worker_id=0
        )

        assert result == ConflictResolutionResult(success=True, used_rebuild=False)

    @pytest.mark.asyncio
    async def test_publish_review_status_uses_event_bus_directly(
        self, config: HydraFlowConfig
    ) -> None:
        """_publish_review_status should emit events via EventBus without phase_utils."""
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript")
        mock_agents._verify_result = AsyncMock(
            return_value=LoopResult(passed=True, summary="")
        )
        resolver = make_conflict_resolver(config, agents=mock_agents)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()
        resolver._workspaces.start_merge_main = AsyncMock(return_value=False)

        # Track events
        from events import EventType

        published = []
        original = resolver._bus.publish

        async def track(event):
            published.append(event)
            return await original(event)

        resolver._bus.publish = track

        await resolver.resolve_merge_conflicts(
            pr, issue, config.workspace_path_for_issue(42), worker_id=1
        )

        review_events = [e for e in published if e.type == EventType.REVIEW_UPDATE]
        assert len(review_events) >= 1
        assert review_events[0].data["role"] == "reviewer"

    @pytest.mark.asyncio
    async def test_fresh_rebuild_uses_prs_expected_pr_title(
        self, tmp_path: Path
    ) -> None:
        """fresh_branch_rebuild should call self._prs.expected_pr_title, not PRManager."""
        cfg = ConfigFactory.create(
            enable_fresh_branch_rebuild=True,
            repo_root=tmp_path / "repo",
            workspace_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="rebuilt transcript")
        mock_agents._verify_result = AsyncMock(
            return_value=LoopResult(passed=True, summary="")
        )
        resolver = make_conflict_resolver(cfg, agents=mock_agents)
        pr = PRInfoFactory.create(number=200, issue_number=77)
        issue = TaskFactory.create(id=77, title="Fix the gizmo")

        new_wt = cfg.workspace_path_for_issue(pr.issue_number)
        resolver._workspaces.destroy = AsyncMock()
        resolver._workspaces.create = AsyncMock(return_value=new_wt)
        resolver._prs.get_pr_diff = AsyncMock(return_value="diff content")
        resolver._prs.update_pr_title = AsyncMock(return_value=True)
        resolver._prs.expected_pr_title = lambda n, t: f"Fixes #{n}: {t}"

        result = await resolver.fresh_branch_rebuild(pr, issue, worker_id=0)

        assert result is True
        resolver._prs.update_pr_title.assert_awaited_once_with(
            200, "Fixes #77: Fix the gizmo"
        )
