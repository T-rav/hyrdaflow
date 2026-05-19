"""Tests for the ImplementPhase two-stage spec-compliance review (ADR-0063 W5).

Covers:
- The default reviewer parses subagent JSON output (compliant / gaps / degraded).
- The ImplementPhase invokes the reviewer on failed attempts, persists gaps
  into ``WorkerResultMeta.spec_review_gaps``, and the next attempt's
  ``prior_failure`` carries those gaps.
- Kill-switch (``implement_two_stage_review_enabled=False``) disables the flow.
- Zero-diff branches are picked up by the reviewer and surfaced as gaps.
- Attempt-cap-with-context: the gaps survive into the next attempt's prompt.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import Task, WorkerResult
from tests.conftest import TaskFactory, WorkerResultFactory
from tests.helpers import ConfigFactory, ImplementPhaseMockBuilder

# ---------------------------------------------------------------------------
# DefaultSpecComplianceReviewer
# ---------------------------------------------------------------------------


class _StubRunner:
    """Records calls and returns a fixed payload."""

    def __init__(self, payload: str, *, exc: Exception | None = None) -> None:
        self._payload = payload
        self._exc = exc
        self.calls: list[dict[str, str]] = []

    async def run(self, *, model: str, subagent_type: str, prompt: str) -> str:
        self.calls.append(
            {"model": model, "subagent_type": subagent_type, "prompt": prompt}
        )
        if self._exc is not None:
            raise self._exc
        return self._payload


class TestDefaultSpecComplianceReviewer:
    @pytest.mark.asyncio
    async def test_compliant_verdict_is_parsed(self) -> None:
        from implement_spec_reviewer import (
            DefaultSpecComplianceReviewer,
            SpecReviewInput,
        )

        payload = (
            '```json\n{"compliant": true, "gaps": [], "reasoning": "matches spec"}\n```'
        )
        reviewer = DefaultSpecComplianceReviewer(_StubRunner(payload))
        result = await reviewer.review(
            SpecReviewInput(
                issue_number=1,
                issue_title="t",
                issue_body="b",
                plan="p",
                diff="diff --git a/x b/x\n+ new",
                commits=1,
                error="",
            )
        )
        assert result.compliant is True
        assert result.gaps == []
        assert result.degraded is False

    @pytest.mark.asyncio
    async def test_gaps_are_parsed_and_force_compliant_false(self) -> None:
        from implement_spec_reviewer import (
            DefaultSpecComplianceReviewer,
            SpecReviewInput,
        )

        # Reviewer claims compliant but lists gaps — gaps win.
        payload = (
            '{"compliant": true, '
            '"gaps": ["missing implement_two_stage_review_enabled flag"], '
            '"reasoning": "config field absent"}'
        )
        reviewer = DefaultSpecComplianceReviewer(_StubRunner(payload))
        result = await reviewer.review(
            SpecReviewInput(
                issue_number=1,
                issue_title="t",
                issue_body="b",
                plan="p",
                diff="",
                commits=0,
                error="",
            )
        )
        assert result.compliant is False
        assert result.gaps == ["missing implement_two_stage_review_enabled flag"]
        assert "config field absent" in result.reasoning

    @pytest.mark.asyncio
    async def test_runner_exception_returns_degraded(self) -> None:
        from implement_spec_reviewer import (
            DefaultSpecComplianceReviewer,
            SpecReviewInput,
        )

        reviewer = DefaultSpecComplianceReviewer(
            _StubRunner("", exc=RuntimeError("subagent crashed"))
        )
        result = await reviewer.review(
            SpecReviewInput(
                issue_number=1,
                issue_title="t",
                issue_body="b",
                plan="p",
                diff="",
                commits=0,
                error="",
            )
        )
        assert result.degraded is True
        assert result.compliant is True
        assert result.gaps == []

    @pytest.mark.asyncio
    async def test_unparseable_payload_returns_degraded(self) -> None:
        from implement_spec_reviewer import (
            DefaultSpecComplianceReviewer,
            SpecReviewInput,
        )

        reviewer = DefaultSpecComplianceReviewer(
            _StubRunner("not json at all just prose")
        )
        result = await reviewer.review(
            SpecReviewInput(
                issue_number=1,
                issue_title="t",
                issue_body="b",
                plan="p",
                diff="",
                commits=0,
                error="",
            )
        )
        assert result.degraded is True

    @pytest.mark.asyncio
    async def test_zero_diff_appears_in_prompt(self) -> None:
        """The reviewer's prompt should explicitly state that the diff is empty
        when no changes were produced — so zero-diff is a first-class
        finding mode, not an implicit one.
        """
        from implement_spec_reviewer import (
            DefaultSpecComplianceReviewer,
            SpecReviewInput,
        )

        runner = _StubRunner('{"compliant": false, "gaps": ["nothing changed"]}')
        reviewer = DefaultSpecComplianceReviewer(runner)
        await reviewer.review(
            SpecReviewInput(
                issue_number=1,
                issue_title="t",
                issue_body="b",
                plan="p",
                diff="",
                commits=0,
                error="",
            )
        )
        prompt = runner.calls[0]["prompt"]
        assert "no diff" in prompt.lower()
        assert "zero changes" in prompt.lower()


# ---------------------------------------------------------------------------
# format_gaps_for_prior_failure
# ---------------------------------------------------------------------------


class TestFormatGapsForPriorFailure:
    def test_empty_gaps_returns_empty_string(self) -> None:
        from implement_spec_reviewer import format_gaps_for_prior_failure

        assert format_gaps_for_prior_failure([]) == ""

    def test_gaps_render_as_bulleted_list(self) -> None:
        from implement_spec_reviewer import format_gaps_for_prior_failure

        text = format_gaps_for_prior_failure(["gap A", "gap B"], reasoning="explained")
        assert "gap A" in text
        assert "gap B" in text
        assert "explained" in text
        assert text.startswith("Spec-compliance gaps from prior attempt:")


# ---------------------------------------------------------------------------
# ImplementPhase wiring — kill switch and reviewer dispatch
# ---------------------------------------------------------------------------


class _FakeSpecReviewer:
    """Records calls and returns a scripted SpecReviewResult."""

    def __init__(self, result) -> None:  # noqa: ANN001
        self._result = result
        self.calls = []

    async def review(self, inp):  # noqa: ANN001, ANN202
        self.calls.append(inp)
        return self._result


class TestSpecReviewKillSwitch:
    @pytest.mark.asyncio
    async def test_reviewer_not_called_when_flag_off(self, tmp_path: Path) -> None:
        from implement_spec_reviewer import SpecReviewResult

        config = ConfigFactory.create(
            implement_two_stage_review_enabled=False,
            repo_root=tmp_path / "repo",
            workspace_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        issue = TaskFactory.create()
        result = WorkerResultFactory.create(
            success=False,
            error="No commits found on branch",
            commits=0,
        )
        reviewer = _FakeSpecReviewer(
            SpecReviewResult(compliant=False, gaps=["should not be called"])
        )
        phase, _, _ = (
            ImplementPhaseMockBuilder(config)
            .with_issues([issue])
            .with_spec_reviewer(reviewer)
            .build()
        )

        await phase._run_spec_compliance_review(issue, result)

        assert reviewer.calls == []

    @pytest.mark.asyncio
    async def test_reviewer_not_called_when_no_reviewer_wired(
        self, tmp_path: Path
    ) -> None:
        """When no reviewer is wired (production fallback), the flow is a no-op."""
        config = ConfigFactory.create(
            implement_two_stage_review_enabled=True,
            repo_root=tmp_path / "repo",
            workspace_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        issue = TaskFactory.create()
        result = WorkerResultFactory.create(success=False, error="x", commits=0)
        phase, _, _ = ImplementPhaseMockBuilder(config).with_issues([issue]).build()
        # Should not raise, should not error.
        await phase._run_spec_compliance_review(issue, result)


class TestSpecReviewPersistence:
    @pytest.mark.asyncio
    async def test_gaps_persisted_into_meta(self, tmp_path: Path) -> None:
        from implement_spec_reviewer import SpecReviewResult

        config = ConfigFactory.create(
            max_issue_attempts=3,
            repo_root=tmp_path / "repo",
            workspace_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        issue = TaskFactory.create(id=4242)
        result = WorkerResultFactory.create(
            issue_number=4242,
            success=False,
            error="No commits found on branch",
            commits=0,
        )
        reviewer = _FakeSpecReviewer(
            SpecReviewResult(
                compliant=False,
                gaps=["did not add the requested env-var override"],
                reasoning="only modified tests, no source change",
            )
        )
        phase, _, mock_prs = (
            ImplementPhaseMockBuilder(config)
            .with_issues([issue])
            .with_spec_reviewer(reviewer)
            .build()
        )
        # Simulate one prior attempt already recorded.
        phase._state.increment_issue_attempts(4242)

        await phase._run_spec_compliance_review(issue, result)

        meta = phase._state.get_worker_result_meta(4242)
        gaps_text = meta.get("spec_review_gaps", "")
        assert "did not add the requested env-var override" in gaps_text
        assert "only modified tests" in gaps_text
        # Comment was posted to the issue with the gaps section.
        comment_bodies = [c.args[1] for c in mock_prs.post_comment.call_args_list]
        assert any("Spec-Compliance Review" in b for b in comment_bodies)
        # Reviewer received the right inputs.
        assert len(reviewer.calls) == 1
        assert reviewer.calls[0].issue_number == 4242
        assert reviewer.calls[0].commits == 0

    @pytest.mark.asyncio
    async def test_compliant_review_does_not_persist_gaps(self, tmp_path: Path) -> None:
        from implement_spec_reviewer import SpecReviewResult

        config = ConfigFactory.create(
            max_issue_attempts=3,
            repo_root=tmp_path / "repo",
            workspace_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        issue = TaskFactory.create(id=4242)
        result = WorkerResultFactory.create(
            issue_number=4242, success=False, error="quality-gate failed", commits=2
        )
        reviewer = _FakeSpecReviewer(SpecReviewResult(compliant=True))
        phase, _, _ = (
            ImplementPhaseMockBuilder(config)
            .with_issues([issue])
            .with_spec_reviewer(reviewer)
            .build()
        )
        phase._state.increment_issue_attempts(4242)

        await phase._run_spec_compliance_review(issue, result)

        meta = phase._state.get_worker_result_meta(4242)
        assert "spec_review_gaps" not in meta or not meta.get("spec_review_gaps")

    @pytest.mark.asyncio
    async def test_degraded_review_does_not_persist_gaps(self, tmp_path: Path) -> None:
        from implement_spec_reviewer import SpecReviewResult

        config = ConfigFactory.create(
            max_issue_attempts=3,
            repo_root=tmp_path / "repo",
            workspace_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        issue = TaskFactory.create(id=4242)
        result = WorkerResultFactory.create(
            issue_number=4242, success=False, error="x", commits=0
        )
        # A degraded result has compliant=True, gaps=[], degraded=True
        reviewer = _FakeSpecReviewer(
            SpecReviewResult(compliant=True, gaps=[], degraded=True)
        )
        phase, _, _ = (
            ImplementPhaseMockBuilder(config)
            .with_issues([issue])
            .with_spec_reviewer(reviewer)
            .build()
        )
        phase._state.increment_issue_attempts(4242)

        await phase._run_spec_compliance_review(issue, result)

        meta = phase._state.get_worker_result_meta(4242)
        assert not meta.get("spec_review_gaps")

    @pytest.mark.asyncio
    async def test_reviewer_skipped_at_attempt_cap(self, tmp_path: Path) -> None:
        """When the next call would escalate to HITL, don't waste a subagent
        dispatch on gathering gaps that will never be read.
        """
        from implement_spec_reviewer import SpecReviewResult

        config = ConfigFactory.create(
            max_issue_attempts=2,
            repo_root=tmp_path / "repo",
            workspace_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        issue = TaskFactory.create(id=4242)
        result = WorkerResultFactory.create(
            issue_number=4242, success=False, error="x", commits=0
        )
        reviewer = _FakeSpecReviewer(SpecReviewResult(compliant=False, gaps=["x"]))
        phase, _, _ = (
            ImplementPhaseMockBuilder(config)
            .with_issues([issue])
            .with_spec_reviewer(reviewer)
            .build()
        )
        # Bump attempts to the cap.
        phase._state.increment_issue_attempts(4242)
        phase._state.increment_issue_attempts(4242)
        assert phase._state.get_issue_attempts(4242) == 2

        await phase._run_spec_compliance_review(issue, result)

        assert reviewer.calls == []


class TestSpecReviewFeedsNextAttempt:
    @pytest.mark.asyncio
    async def test_gaps_fed_into_prior_failure_on_next_attempt(
        self, tmp_path: Path
    ) -> None:
        """End-to-end: a failed attempt persists gaps; the next attempt's
        ``prior_failure`` contains those gaps.
        """
        config = ConfigFactory.create(
            max_issue_attempts=3,
            repo_root=tmp_path / "repo",
            workspace_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        issue = TaskFactory.create(id=4242)
        captured: list[str] = []

        async def capturing_agent(
            issue: Task,
            wt_path: Path,
            branch: str,
            worker_id: int = 0,
            review_feedback: str = "",
            prior_failure: str = "",
        ) -> WorkerResult:
            captured.append(prior_failure)
            return WorkerResultFactory.create(
                issue_number=issue.id, success=True, workspace_path=str(wt_path)
            )

        phase, _, _ = ImplementPhaseMockBuilder(config).with_issues([issue]).build()

        # Simulate: prior attempt recorded an error AND the spec reviewer
        # captured gaps for it.
        phase._state.set_worker_result_meta(
            4242,
            {
                "error": "No commits found on branch",
                "spec_review_gaps": "Spec-compliance gaps from prior attempt:\n- did not implement feature X",
            },
        )

        # Now run the next attempt directly through _run_implementation, which
        # is what receives the prior_failure construction.
        phase._agents.run = capturing_agent  # type: ignore[method-assign]
        await phase._run_implementation(issue, "agent/issue-4242", 0, "")

        assert len(captured) == 1
        assert "did not implement feature X" in captured[0]
        assert "Runner error: No commits found on branch" in captured[0]

    @pytest.mark.asyncio
    async def test_gaps_only_when_no_runner_error(self, tmp_path: Path) -> None:
        """Spec gaps without a runner error still get fed forward."""
        config = ConfigFactory.create(
            max_issue_attempts=3,
            repo_root=tmp_path / "repo",
            workspace_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        issue = TaskFactory.create(id=99)
        captured: list[str] = []

        async def capturing_agent(
            issue: Task,
            wt_path: Path,
            branch: str,
            worker_id: int = 0,
            review_feedback: str = "",
            prior_failure: str = "",
        ) -> WorkerResult:
            captured.append(prior_failure)
            return WorkerResultFactory.create(
                issue_number=issue.id, success=True, workspace_path=str(wt_path)
            )

        phase, _, _ = ImplementPhaseMockBuilder(config).with_issues([issue]).build()

        phase._state.set_worker_result_meta(
            99,
            {
                "error": None,
                "spec_review_gaps": (
                    "Spec-compliance gaps from prior attempt:\n- forgot kill-switch"
                ),
            },
        )

        phase._agents.run = capturing_agent  # type: ignore[method-assign]
        await phase._run_implementation(issue, "agent/issue-99", 0, "")

        assert captured[0].startswith("Spec-compliance gaps from prior attempt:")
        assert "forgot kill-switch" in captured[0]
        assert "Runner error" not in captured[0]


class TestHandleImplementationResultDispatchesReview:
    @pytest.mark.asyncio
    async def test_zero_commit_failure_triggers_reviewer(self, tmp_path: Path) -> None:
        """The end-to-end failure-result handler dispatches the reviewer for
        zero-commit failures (the canonical zero-diff failure mode).
        """
        from implement_spec_reviewer import SpecReviewResult

        config = ConfigFactory.create(
            max_issue_attempts=3,
            repo_root=tmp_path / "repo",
            workspace_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        issue = TaskFactory.create(id=4242)
        result = WorkerResultFactory.create(
            issue_number=4242,
            success=False,
            error="No commits found on branch",
            commits=0,
            workspace_path=str(config.workspace_path_for_issue(4242)),
        )
        reviewer = _FakeSpecReviewer(
            SpecReviewResult(compliant=False, gaps=["produced zero diff against spec"])
        )
        phase, _, _ = (
            ImplementPhaseMockBuilder(config)
            .with_issues([issue])
            .with_spec_reviewer(reviewer)
            .build()
        )
        phase._state.increment_issue_attempts(4242)

        await phase._handle_implementation_result(issue, result, is_retry=False)

        assert len(reviewer.calls) == 1
        meta = phase._state.get_worker_result_meta(4242)
        assert "produced zero diff against spec" in meta.get("spec_review_gaps", "")

    @pytest.mark.asyncio
    async def test_blocking_skill_failure_with_commits_triggers_reviewer(
        self, tmp_path: Path
    ) -> None:
        """A non-zero-commit failure (e.g. blocking skill) also runs the reviewer."""
        from implement_spec_reviewer import SpecReviewResult

        config = ConfigFactory.create(
            max_issue_attempts=3,
            repo_root=tmp_path / "repo",
            workspace_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        issue = TaskFactory.create(id=4242)
        wt_path = config.workspace_path_for_issue(4242)
        result = WorkerResultFactory.create(
            issue_number=4242,
            success=False,
            error="diff-sanity failed: Missing implementation",
            commits=2,
            workspace_path=str(wt_path),
        )
        reviewer = _FakeSpecReviewer(
            SpecReviewResult(compliant=False, gaps=["only modified tests"])
        )
        phase, _, _ = (
            ImplementPhaseMockBuilder(config)
            .with_issues([issue])
            .with_spec_reviewer(reviewer)
            .build()
        )
        phase._state.increment_issue_attempts(4242)

        await phase._handle_implementation_result(issue, result, is_retry=False)

        assert len(reviewer.calls) == 1

    @pytest.mark.asyncio
    async def test_successful_result_does_not_trigger_reviewer(
        self, tmp_path: Path
    ) -> None:
        """The reviewer is only for failed attempts."""
        from implement_spec_reviewer import SpecReviewResult

        config = ConfigFactory.create(
            max_issue_attempts=3,
            repo_root=tmp_path / "repo",
            workspace_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        issue = TaskFactory.create(id=4242)
        wt_path = config.workspace_path_for_issue(4242)
        result = WorkerResultFactory.create(
            issue_number=4242,
            success=True,
            commits=3,
            workspace_path=str(wt_path),
        )
        reviewer = _FakeSpecReviewer(
            SpecReviewResult(compliant=False, gaps=["should not be called"])
        )
        phase, _, _ = (
            ImplementPhaseMockBuilder(config)
            .with_issues([issue])
            .with_spec_reviewer(reviewer)
            .build()
        )

        await phase._handle_implementation_result(issue, result, is_retry=False)

        assert reviewer.calls == []
