from __future__ import annotations

import ast
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent import AgentRunner
from events import EventBus
from models import Task
from tests.conftest import PRInfoFactory, TaskFactory
from tests.helpers import ConfigFactory

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config(tmp_path: Path):
    return ConfigFactory.create(
        repo_root=tmp_path / "repo",
        worktree_base=tmp_path / "wt",
        state_file=tmp_path / "s.json",
    )


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def agent_task() -> Task:
    return TaskFactory.create(id=42, title="Fix something")


# ---------------------------------------------------------------------------
# AST-based exception-chaining guard
# ---------------------------------------------------------------------------


def test_except_blocks_chain_exceptions() -> None:
    """Ensure every raise inside an except block preserves the original cause."""
    offenders: list[str] = []
    for file_path in (Path(__file__).parent.parent / "src").rglob("*.py"):
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            for child in ast.walk(node):
                if not isinstance(child, ast.Raise):
                    continue
                if child.exc is None:
                    # bare ``raise`` keeps original exception context
                    continue
                if child.cause is not None:
                    continue
                offenders.append(f"{file_path}:{child.lineno}")
    assert not offenders, (
        "Exceptions raised inside except blocks must use `raise ... from ...` "
        "(or `from None` when intentional). Missing chaining at:\n"
        + "\n".join(offenders)
    )


# ---------------------------------------------------------------------------
# AgentRunner — main handler (agent.py:213)
# ---------------------------------------------------------------------------


class TestAgentRunnerExceptionChaining:
    """Test is_likely_bug gate and repr(exc) in AgentRunner.run."""

    @pytest.mark.asyncio
    async def test_likely_bug_re_raises(
        self, config, event_bus, agent_task, tmp_path: Path
    ) -> None:
        """TypeError (a likely bug) should propagate, not be swallowed."""
        runner = AgentRunner(config, event_bus)
        with (
            patch.object(
                runner,
                "_execute",
                new_callable=AsyncMock,
                side_effect=TypeError("bad arg"),
            ),
            patch.object(runner, "_save_transcript"),
            pytest.raises(TypeError, match="bad arg"),
        ):
            await runner.run(agent_task, tmp_path, "agent/issue-42")

    @pytest.mark.asyncio
    async def test_transient_error_caught_gracefully(
        self, config, event_bus, agent_task, tmp_path: Path
    ) -> None:
        """RuntimeError (transient) should be caught and stored in result."""
        runner = AgentRunner(config, event_bus)
        with (
            patch.object(
                runner,
                "_execute",
                new_callable=AsyncMock,
                side_effect=RuntimeError("subprocess crash"),
            ),
            patch.object(runner, "_save_transcript"),
        ):
            result = await runner.run(agent_task, tmp_path, "agent/issue-42")

        assert result.success is False
        assert "subprocess crash" in (result.error or "")

    @pytest.mark.asyncio
    async def test_error_stored_as_repr(
        self, config, event_bus, agent_task, tmp_path: Path
    ) -> None:
        """result.error should contain repr(exc) for richer context."""
        runner = AgentRunner(config, event_bus)
        with (
            patch.object(
                runner,
                "_execute",
                new_callable=AsyncMock,
                side_effect=RuntimeError("subprocess crash"),
            ),
            patch.object(runner, "_save_transcript"),
        ):
            result = await runner.run(agent_task, tmp_path, "agent/issue-42")

        # repr() includes the exception class name
        assert result.error is not None
        assert "RuntimeError" in result.error

    @pytest.mark.asyncio
    async def test_logger_exception_used(
        self, config, event_bus, agent_task, tmp_path: Path
    ) -> None:
        """logger.exception() should be used for the main failure log."""
        runner = AgentRunner(config, event_bus)
        with (
            patch.object(
                runner,
                "_execute",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
            ),
            patch.object(runner, "_save_transcript"),
            patch("agent.logger") as mock_logger,
        ):
            await runner.run(agent_task, tmp_path, "agent/issue-42")

        mock_logger.exception.assert_called_once()
        # The main failure message should use exception(), not error()
        assert "Agent failed" in mock_logger.exception.call_args.args[0]


# ---------------------------------------------------------------------------
# AgentRunner — helper methods (agent.py:330, 359)
# ---------------------------------------------------------------------------


class TestAgentHelperBugGates:
    """Test is_likely_bug gate in _get_review_feedback_section / _get_escalation_data."""

    @pytest.mark.asyncio
    async def test_get_review_feedback_section_reraises_bug(
        self, config, event_bus
    ) -> None:
        """TypeError in feedback loading should propagate."""
        runner = AgentRunner(config, event_bus)
        mock_insights = MagicMock()
        mock_insights.load_recent = AsyncMock(side_effect=TypeError("bad"))
        runner._insights = mock_insights
        with pytest.raises(TypeError, match="bad"):
            await runner._get_review_feedback_section()

    @pytest.mark.asyncio
    async def test_get_review_feedback_section_swallows_transient(
        self, config, event_bus
    ) -> None:
        """RuntimeError in feedback loading should return empty string."""
        runner = AgentRunner(config, event_bus)
        mock_insights = MagicMock()
        mock_insights.load_recent = AsyncMock(side_effect=RuntimeError("transient"))
        runner._insights = mock_insights
        assert await runner._get_review_feedback_section() == ""

    @pytest.mark.asyncio
    async def test_get_escalation_data_reraises_bug(self, config, event_bus) -> None:
        """KeyError in escalation loading should propagate."""
        runner = AgentRunner(config, event_bus)
        mock_insights = MagicMock()
        mock_insights.load_recent = AsyncMock(side_effect=KeyError("missing"))
        runner._insights = mock_insights
        with pytest.raises(KeyError, match="missing"):
            await runner._get_escalation_data()

    @pytest.mark.asyncio
    async def test_get_escalation_data_swallows_transient(
        self, config, event_bus
    ) -> None:
        """OSError in escalation loading should return empty list."""
        runner = AgentRunner(config, event_bus)
        mock_insights = MagicMock()
        mock_insights.load_recent = AsyncMock(side_effect=OSError("disk full"))
        runner._insights = mock_insights
        assert await runner._get_escalation_data() == []

    @pytest.mark.asyncio
    async def test_get_escalation_data_json_decode_error_reraises(
        self, config, event_bus
    ) -> None:
        """json.JSONDecodeError (a ValueError subclass) should re-raise.

        json.JSONDecodeError is a subclass of ValueError, which is in
        LIKELY_BUG_EXCEPTIONS. With the Hindsight migration, there is no
        separate json.JSONDecodeError handler — is_likely_bug treats it
        as a bug (via ValueError) and re-raises.
        """
        import json

        runner = AgentRunner(config, event_bus)
        mock_insights = MagicMock()
        mock_insights.load_recent = AsyncMock(
            side_effect=json.JSONDecodeError("bad json", "doc", 0)
        )
        runner._insights = mock_insights
        with pytest.raises(json.JSONDecodeError):
            await runner._get_escalation_data()


# ---------------------------------------------------------------------------
# PlannerRunner (planner.py:238)
# ---------------------------------------------------------------------------


class TestPlannerRunnerExceptionChaining:
    """Test is_likely_bug gate and repr(exc) in PlannerRunner.run."""

    @pytest.mark.asyncio
    async def test_likely_bug_re_raises(self, config, event_bus) -> None:
        from planner import PlannerRunner

        runner = PlannerRunner(config, event_bus)
        task = TaskFactory.create(id=10, title="Plan something")
        with (
            patch.object(
                runner,
                "_execute",
                new_callable=AsyncMock,
                side_effect=AttributeError("missing attr"),
            ),
            patch.object(runner, "_save_transcript"),
            pytest.raises(AttributeError, match="missing attr"),
        ):
            await runner.plan(task, worker_id=0)

    @pytest.mark.asyncio
    async def test_transient_error_uses_repr(self, config, event_bus) -> None:
        from planner import PlannerRunner

        runner = PlannerRunner(config, event_bus)
        task = TaskFactory.create(id=10, title="Plan something")
        with (
            patch.object(
                runner,
                "_execute",
                new_callable=AsyncMock,
                side_effect=RuntimeError("planner crash"),
            ),
            patch.object(runner, "_save_transcript"),
        ):
            result = await runner.plan(task, worker_id=0)

        assert result.success is False
        assert "RuntimeError" in (result.error or "")


# ---------------------------------------------------------------------------
# HITLRunner (hitl_runner.py:156)
# ---------------------------------------------------------------------------


class TestHITLRunnerExceptionChaining:
    """Test is_likely_bug gate and repr(exc) in HITLRunner.run."""

    @pytest.mark.asyncio
    async def test_likely_bug_re_raises(self, config, event_bus) -> None:
        from hitl_runner import HITLRunner
        from models import GitHubIssue

        runner = HITLRunner(config, event_bus)
        issue = GitHubIssue(
            number=99,
            title="HITL test",
            body="body",
            labels=["hydraflow-hitl"],
            comments=[],
        )
        with (
            patch.object(
                runner,
                "_execute",
                new_callable=AsyncMock,
                side_effect=IndexError("out of range"),
            ),
            pytest.raises(IndexError, match="out of range"),
        ):
            await runner.run(
                issue,
                correction="fix it",
                cause="ci",
                worktree_path=config.repo_root,
                worker_id=0,
            )

    @pytest.mark.asyncio
    async def test_transient_error_uses_repr(self, config, event_bus) -> None:
        from hitl_runner import HITLRunner
        from models import GitHubIssue

        runner = HITLRunner(config, event_bus)
        issue = GitHubIssue(
            number=99,
            title="HITL test",
            body="body",
            labels=["hydraflow-hitl"],
            comments=[],
        )
        with patch.object(
            runner,
            "_execute",
            new_callable=AsyncMock,
            side_effect=RuntimeError("hitl crash"),
        ):
            result = await runner.run(
                issue,
                correction="fix it",
                cause="ci",
                worktree_path=config.repo_root,
                worker_id=0,
            )

        assert result.success is False
        assert "RuntimeError" in (result.error or "")


# ---------------------------------------------------------------------------
# MergeConflictResolver (merge_conflict_resolver.py:222, 347, 367)
# ---------------------------------------------------------------------------


class TestMergeConflictResolverExceptionChaining:
    """Test is_likely_bug gate in MergeConflictResolver."""

    def _make_resolver(self, config, event_bus):
        from merge_conflict_resolver import MergeConflictResolver

        return MergeConflictResolver(
            config=config,
            worktrees=MagicMock(),
            agents=MagicMock(),
            prs=MagicMock(),
            event_bus=event_bus,
            state=MagicMock(),
            summarizer=None,
        )

    @pytest.mark.asyncio
    async def test_resolve_reraises_bug(self, config, event_bus) -> None:
        resolver = self._make_resolver(config, event_bus)
        pr = PRInfoFactory.create(number=5, issue_number=5)
        task = TaskFactory.create(id=5)

        # Mock worktrees.start_merge_main to return False (has conflicts)
        resolver._worktrees.start_merge_main = AsyncMock(return_value=False)
        resolver._publish_review_status = AsyncMock()

        # Mock agents._build_command to raise TypeError (a likely bug)
        resolver._agents._build_command = MagicMock(
            side_effect=TypeError("bad merge arg")
        )

        with pytest.raises(TypeError, match="bad merge arg"):
            await resolver.resolve_merge_conflicts(pr, task, Path("/tmp/wt"))

    @pytest.mark.asyncio
    async def test_resolve_catches_transient(self, config, event_bus) -> None:
        resolver = self._make_resolver(config, event_bus)
        pr = PRInfoFactory.create(number=5, issue_number=5)
        task = TaskFactory.create(id=5)

        # Mock worktrees.start_merge_main to return False (has conflicts)
        resolver._worktrees.start_merge_main = AsyncMock(return_value=False)
        resolver._publish_review_status = AsyncMock()
        resolver._worktrees.abort_merge = AsyncMock()

        # Mock agents._build_command to raise RuntimeError (transient)
        resolver._agents._build_command = MagicMock(
            side_effect=RuntimeError("transient")
        )

        # Mock fresh rebuild to also fail
        with patch.object(
            resolver, "fresh_branch_rebuild", new_callable=AsyncMock, return_value=False
        ):
            result = await resolver.resolve_merge_conflicts(pr, task, Path("/tmp/wt"))
        assert result.success is False

    @pytest.mark.asyncio
    async def test_summarize_narrows_to_runtime_os_error(self) -> None:
        """_maybe_summarize_conflict should only catch RuntimeError/OSError."""
        from merge_conflict_resolver import MergeConflictResolver

        resolver = MergeConflictResolver.__new__(MergeConflictResolver)
        resolver._summarizer = AsyncMock()
        resolver._summarizer.summarize_and_publish.side_effect = TypeError(
            "bug in summarizer"
        )
        with pytest.raises(TypeError, match="bug in summarizer"):
            await resolver._maybe_summarize_conflict("transcript", 1, 2)


# ---------------------------------------------------------------------------
# ImplementPhase — recording setup/finalize narrowing (implement_phase.py:215, 229)
# ---------------------------------------------------------------------------


class TestImplementPhaseRecordingNarrowing:
    """Verify that recording setup/finalize now propagates TypeError (not swallowed)."""

    @pytest.mark.asyncio
    async def test_recording_setup_propagates_type_error(
        self, config, event_bus
    ) -> None:
        """TypeError from run_recorder.start() should propagate after narrowing to (RuntimeError, OSError)."""
        from tests.helpers import make_implement_phase

        issue = TaskFactory.create(id=55, title="test issue")
        phase, mock_wt, mock_prs = make_implement_phase(config, [issue])

        mock_recorder = MagicMock()
        mock_recorder.start.side_effect = TypeError("internal recorder bug")
        phase._run_recorder = mock_recorder

        with pytest.raises(TypeError, match="internal recorder bug"):
            await phase._worker_inner(0, issue, "agent/issue-55")

    @pytest.mark.asyncio
    async def test_recording_setup_swallows_runtime_error(
        self, config, event_bus
    ) -> None:
        """RuntimeError from run_recorder.start() should be swallowed (infrastructure error)."""
        from tests.helpers import make_implement_phase

        issue = TaskFactory.create(id=55, title="test issue")
        phase, mock_wt, mock_prs = make_implement_phase(config, [issue])

        mock_recorder = MagicMock()
        mock_recorder.start.side_effect = RuntimeError("disk IO failed")
        phase._run_recorder = mock_recorder

        # Should not raise — continues with ctx=None
        result = await phase._worker_inner(0, issue, "agent/issue-55")
        assert result is not None


# ---------------------------------------------------------------------------
# Triage (triage.py:144, 405)
# ---------------------------------------------------------------------------


class TestTriageExceptionChaining:
    """Test is_likely_bug gate in TriageAgent."""

    @pytest.mark.asyncio
    async def test_evaluate_reraises_bug(self, config, event_bus) -> None:
        from triage import TriageRunner

        agent = TriageRunner(config, event_bus)
        # Title/body must be long enough to pass pre-filter
        task = TaskFactory.create(
            id=7,
            title="Fix the authentication module for SSO users",
            body="The SSO login flow is broken when users try to authenticate via SAML. "
            "This causes a 500 error on the callback endpoint.",
        )
        with (
            patch.object(
                agent,
                "_evaluate_with_llm",
                new_callable=AsyncMock,
                side_effect=KeyError("missing field"),
            ),
            patch.object(agent, "_emit_transcript", new_callable=AsyncMock),
            pytest.raises(KeyError, match="missing field"),
        ):
            await agent.evaluate(task)

    @pytest.mark.asyncio
    async def test_evaluate_catches_transient(self, config, event_bus) -> None:
        from triage import TriageRunner

        agent = TriageRunner(config, event_bus)
        task = TaskFactory.create(
            id=7,
            title="Fix the authentication module for SSO users",
            body="The SSO login flow is broken when users try to authenticate via SAML. "
            "This causes a 500 error on the callback endpoint.",
        )
        with (
            patch.object(
                agent,
                "_evaluate_with_llm",
                new_callable=AsyncMock,
                # Note: RuntimeError would be re-raised by the RuntimeError handler,
                # so use OSError as a transient non-infrastructure error
                side_effect=OSError("network timeout"),
            ),
            patch.object(agent, "_emit_transcript", new_callable=AsyncMock),
        ):
            result = await agent.evaluate(task)

        assert result.ready is False
        assert any("network timeout" in r for r in result.reasons)

    @pytest.mark.asyncio
    async def test_decompose_reraises_bug(self, config, event_bus) -> None:
        from triage import TriageRunner

        agent = TriageRunner(config, event_bus)
        task = TaskFactory.create(id=7, title="Decompose me")
        with (
            patch.object(
                agent,
                "_execute",
                new_callable=AsyncMock,
                side_effect=AttributeError("no attr"),
            ),
            patch.object(agent, "_save_transcript"),
            pytest.raises(AttributeError, match="no attr"),
        ):
            await agent.run_decomposition(task)


# ---------------------------------------------------------------------------
# VerificationJudge (verification_judge.py:107, 158)
# ---------------------------------------------------------------------------


class TestVerificationJudgeBugGates:
    """Test is_likely_bug gate in VerificationJudge."""

    @pytest.mark.asyncio
    async def test_code_validation_reraises_bug(self, config, event_bus) -> None:
        from verification_judge import VerificationJudge

        judge = VerificationJudge(config, event_bus)

        criteria_dir = config.repo_root / ".hydraflow" / "verification"
        criteria_dir.mkdir(parents=True)
        (criteria_dir / "issue-42.md").write_text(
            "## Acceptance Criteria\n- [ ] Must work\n"
        )

        with (
            patch.object(
                judge,
                "_execute",
                new_callable=AsyncMock,
                side_effect=TypeError("bad prompt arg"),
            ),
            pytest.raises(TypeError, match="bad prompt arg"),
        ):
            await judge.judge(issue_number=42, pr_number=101, diff="diff")

    @pytest.mark.asyncio
    async def test_code_validation_catches_transient(self, config, event_bus) -> None:
        from verification_judge import VerificationJudge

        judge = VerificationJudge(config, event_bus)

        criteria_dir = config.repo_root / ".hydraflow" / "verification"
        criteria_dir.mkdir(parents=True)
        (criteria_dir / "issue-42.md").write_text(
            "## Acceptance Criteria\n- [ ] Must work\n"
        )

        with patch.object(
            judge,
            "_execute",
            new_callable=AsyncMock,
            side_effect=RuntimeError("LLM timeout"),
        ):
            result = await judge.judge(issue_number=42, pr_number=101, diff="diff")

        assert result is not None
        assert result.criteria_results == []
        assert result.all_criteria_pass is False


# ---------------------------------------------------------------------------
# ADRReviewer (adr_reviewer.py:488, 590, 1003)
# ---------------------------------------------------------------------------


class TestADRReviewerBugGates:
    """Test is_likely_bug gate in ADRCouncilReviewer."""

    @pytest.mark.asyncio
    async def test_triage_routing_reraises_bug(self) -> None:
        from adr_reviewer import ADRCouncilReviewer
        from models import ADRCouncilResult, CouncilVerdict

        reviewer = ADRCouncilReviewer.__new__(ADRCouncilReviewer)
        reviewer._prs = AsyncMock()
        reviewer._prs.create_issue.side_effect = TypeError("bad arg")
        reviewer._config = MagicMock()
        reviewer._config.find_label = ["hydraflow-find"]

        result = ADRCouncilResult(
            adr_number=1,
            adr_path=Path("adr.md"),
            final_decision=CouncilVerdict.REQUEST_CHANGES,
            votes=[],
            summary="test",
        )

        with pytest.raises(TypeError, match="bad arg"):
            await reviewer._route_to_triage(result, reason="test")

    @pytest.mark.asyncio
    async def test_triage_routing_catches_transient(self) -> None:
        from adr_reviewer import ADRCouncilReviewer
        from models import ADRCouncilResult, CouncilVerdict

        reviewer = ADRCouncilReviewer.__new__(ADRCouncilReviewer)
        reviewer._prs = AsyncMock()
        reviewer._prs.create_issue.side_effect = RuntimeError("API timeout")
        reviewer._config = MagicMock()
        reviewer._config.find_label = ["hydraflow-find"]

        result = ADRCouncilResult(
            adr_number=1,
            adr_path=Path("adr.md"),
            final_decision=CouncilVerdict.REQUEST_CHANGES,
            votes=[],
            summary="test",
        )

        ok = await reviewer._route_to_triage(result, reason="test")
        assert ok is False

    @pytest.mark.asyncio
    async def test_pre_validation_failure_routing_reraises_bug(self) -> None:
        """TypeError in _route_pre_validation_failure should propagate."""
        from adr_pre_validator import ADRValidationIssue, ADRValidationResult
        from adr_reviewer import ADRCouncilReviewer

        reviewer = ADRCouncilReviewer.__new__(ADRCouncilReviewer)
        reviewer._prs = AsyncMock()
        reviewer._prs.create_issue.side_effect = TypeError("bad create_issue arg")
        reviewer._config = MagicMock()
        reviewer._config.adr_review_auto_triage = True
        reviewer._config.find_label = ["hydraflow-find"]

        validation = ADRValidationResult(
            issues=[ADRValidationIssue(code="E001", message="Missing heading")]
        )
        with pytest.raises(TypeError, match="bad create_issue arg"):
            await reviewer._route_pre_validation_failure(
                1, "Test ADR title", validation, {"auto_triaged": 0, "escalated": 0}
            )

    @pytest.mark.asyncio
    async def test_pre_validation_failure_routing_catches_transient(self) -> None:
        """RuntimeError in _route_pre_validation_failure falls back to HITL escalation."""
        from adr_pre_validator import ADRValidationIssue, ADRValidationResult
        from adr_reviewer import ADRCouncilReviewer

        reviewer = ADRCouncilReviewer.__new__(ADRCouncilReviewer)
        reviewer._prs = AsyncMock()
        # First call (auto_triage path) raises RuntimeError; second (HITL) succeeds
        reviewer._prs.create_issue.side_effect = [RuntimeError("API timeout"), 0]
        reviewer._config = MagicMock()
        reviewer._config.adr_review_auto_triage = True
        reviewer._config.find_label = ["hydraflow-find"]
        reviewer._config.hitl_label = ["hydraflow-hitl"]

        validation = ADRValidationResult(
            issues=[ADRValidationIssue(code="E001", message="Missing heading")]
        )
        stats: dict[str, int] = {"auto_triaged": 0, "escalated": 0}
        # Should not raise — falls back to HITL escalation
        await reviewer._route_pre_validation_failure(1, "Test ADR", validation, stats)
        assert stats["escalated"] == 1

    @pytest.mark.asyncio
    async def test_handle_duplicate_reraises_bug(self) -> None:
        """TypeError in _handle_duplicate should propagate."""
        from adr_reviewer import ADRCouncilReviewer
        from models import ADRCouncilResult, CouncilVerdict

        reviewer = ADRCouncilReviewer.__new__(ADRCouncilReviewer)
        reviewer._prs = AsyncMock()
        reviewer._prs.create_issue.side_effect = TypeError("bad dup arg")
        reviewer._config = MagicMock()
        reviewer._config.adr_review_auto_triage = True
        reviewer._config.find_label = ["hydraflow-find"]

        result = ADRCouncilResult(
            adr_number=2,
            adr_path=Path("adr.md"),
            final_decision=CouncilVerdict.REQUEST_CHANGES,
            votes=[],
            summary="dup",
            duplicate_detected=True,
            duplicate_of=1,
        )
        with pytest.raises(TypeError, match="bad dup arg"):
            await reviewer._handle_duplicate(
                result, {"auto_triaged": 0, "escalated": 0}
            )

    @pytest.mark.asyncio
    async def test_handle_duplicate_catches_transient(self) -> None:
        """RuntimeError in _handle_duplicate falls back to HITL escalation."""
        from adr_reviewer import ADRCouncilReviewer
        from models import ADRCouncilResult, CouncilVerdict

        reviewer = ADRCouncilReviewer.__new__(ADRCouncilReviewer)
        reviewer._prs = AsyncMock()
        reviewer._prs.create_issue.side_effect = [RuntimeError("API timeout"), 0]
        reviewer._config = MagicMock()
        reviewer._config.adr_review_auto_triage = True
        reviewer._config.find_label = ["hydraflow-find"]
        reviewer._config.hitl_label = ["hydraflow-hitl"]

        result = ADRCouncilResult(
            adr_number=2,
            adr_path=Path("adr.md"),
            final_decision=CouncilVerdict.REQUEST_CHANGES,
            votes=[],
            summary="dup",
            duplicate_detected=True,
            duplicate_of=1,
        )
        stats: dict[str, int] = {"auto_triaged": 0, "escalated": 0}
        await reviewer._handle_duplicate(result, stats)
        assert stats["escalated"] == 1


# ---------------------------------------------------------------------------
# Parametric: all is_likely_bug exception types re-raise from AgentRunner
# ---------------------------------------------------------------------------


BUG_EXCEPTIONS = [
    TypeError("type bug"),
    KeyError("key bug"),
    AttributeError("attr bug"),
    ValueError("value bug"),
    IndexError("index bug"),
    NotImplementedError("not impl"),
]


class TestAllBugExceptionsReRaise:
    """Parametric test: all LIKELY_BUG_EXCEPTIONS re-raise from AgentRunner.run."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("exc", BUG_EXCEPTIONS, ids=lambda e: type(e).__name__)
    async def test_agent_run_reraises(
        self, config, event_bus, agent_task, tmp_path: Path, exc: Exception
    ) -> None:
        runner = AgentRunner(config, event_bus)
        with (
            patch.object(
                runner,
                "_execute",
                new_callable=AsyncMock,
                side_effect=exc,
            ),
            patch.object(runner, "_save_transcript"),
            pytest.raises(type(exc)),
        ):
            await runner.run(agent_task, tmp_path, "agent/issue-42")
