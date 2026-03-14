"""Tests for review_phase.py complexity reduction (issue #2391).

Covers the refactored methods:
- HitlEscalation dataclass
- _run_single_review_fix()
- _handle_ci_exhaustion()
- _emit_visual_gate_telemetry()
- _handle_visual_gate_pass()
- _handle_visual_gate_failure()
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import HydraFlowConfig

from events import EventType
from models import (
    HitlEscalation,
    ReviewVerdict,
    VisualEvidence,
    VisualEvidenceItem,
)
from tests.conftest import (
    PRInfoFactory,
    ReviewResultFactory,
    TaskFactory,
)
from tests.helpers import make_review_phase

# ---------------------------------------------------------------------------
# HitlEscalation dataclass tests
# ---------------------------------------------------------------------------


class TestHitlEscalation:
    """Tests for the HitlEscalation dataclass."""

    def test_required_fields(self) -> None:
        """HitlEscalation requires issue_number, pr_number, cause, origin_label, comment."""
        esc = HitlEscalation(
            issue_number=42,
            pr_number=101,
            cause="test",
            origin_label="hydraflow-review",
            comment="Escalation comment",
        )
        assert esc.issue_number == 42
        assert esc.pr_number == 101
        assert esc.cause == "test"
        assert esc.origin_label == "hydraflow-review"
        assert esc.comment == "Escalation comment"

    def test_hitl_escalation_defaults_post_on_pr_true(self) -> None:
        """Optional fields should have sensible defaults."""
        esc = HitlEscalation(
            issue_number=1,
            pr_number=None,
            cause="c",
            origin_label="l",
            comment="m",
        )
        assert esc.post_on_pr is True
        assert esc.event_cause == ""
        assert esc.extra_event_data is None
        assert esc.task is None
        assert esc.visual_evidence is None

    def test_all_fields(self) -> None:
        """All fields should be assignable."""
        task = TaskFactory.create(id=5)
        evidence = VisualEvidence(
            items=[
                VisualEvidenceItem(screen_name="login", diff_percent=1.0, status="fail")
            ],
        )
        esc = HitlEscalation(
            issue_number=10,
            pr_number=20,
            cause="visual",
            origin_label="hydraflow-review",
            comment="blocked",
            post_on_pr=False,
            event_cause="visual_gate_failed",
            extra_event_data={"k": "v"},
            task=task,
            visual_evidence=evidence,
        )
        assert esc.post_on_pr is False
        assert esc.event_cause == "visual_gate_failed"
        assert esc.extra_event_data == {"k": "v"}
        assert esc.task is task
        assert esc.visual_evidence is evidence

    def test_pr_number_none_allowed(self) -> None:
        """pr_number=None should be valid for issue-only escalations."""
        esc = HitlEscalation(
            issue_number=1, pr_number=None, cause="c", origin_label="l", comment="m"
        )
        assert esc.pr_number is None


# ---------------------------------------------------------------------------
# _escalate_to_hitl with HitlEscalation
# ---------------------------------------------------------------------------


class TestEscalateToHitlWithDataclass:
    """Verify _escalate_to_hitl works correctly with the HitlEscalation dataclass."""

    @pytest.mark.asyncio
    async def test_basic_escalation(self, config: HydraFlowConfig) -> None:
        """Basic escalation should set state and post comment."""
        phase = make_review_phase(config)
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()

        await phase._escalate_to_hitl(
            HitlEscalation(
                issue_number=42,
                pr_number=101,
                cause="Test failure",
                origin_label="hydraflow-review",
                comment="Escalation comment",
            )
        )

        assert phase._state.get_hitl_origin(42) == "hydraflow-review"
        assert phase._state.get_hitl_cause(42) == "Test failure"
        phase._prs.post_pr_comment.assert_awaited_once_with(101, "Escalation comment")

    @pytest.mark.asyncio
    async def test_post_on_pr_false(self, config: HydraFlowConfig) -> None:
        """post_on_pr=False should post on issue instead."""
        phase = make_review_phase(config)
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.post_comment = AsyncMock()

        await phase._escalate_to_hitl(
            HitlEscalation(
                issue_number=42,
                pr_number=101,
                cause="Test",
                origin_label="hydraflow-review",
                comment="Escalation!",
                post_on_pr=False,
            )
        )

        phase._prs.post_comment.assert_awaited_once_with(42, "Escalation!")
        phase._prs.post_pr_comment.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_with_visual_evidence(self, config: HydraFlowConfig) -> None:
        """Visual evidence should be persisted in state."""
        phase = make_review_phase(config)
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()

        evidence = VisualEvidence(
            items=[
                VisualEvidenceItem(screen_name="home", diff_percent=5.0, status="fail")
            ],
        )
        await phase._escalate_to_hitl(
            HitlEscalation(
                issue_number=42,
                pr_number=101,
                cause="Visual fail",
                origin_label="hydraflow-review",
                comment="blocked",
                visual_evidence=evidence,
            )
        )

        stored = phase._state.get_hitl_visual_evidence(42)
        assert stored is not None
        assert stored.items[0].screen_name == "home"


# ---------------------------------------------------------------------------
# _run_single_review_fix tests
# ---------------------------------------------------------------------------


class TestRunSingleReviewFix:
    """Tests for the extracted _run_single_review_fix method."""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_fixes(self, config: HydraFlowConfig) -> None:
        """Should return None when fix agent makes no changes."""
        phase = make_review_phase(config)
        pr = PRInfoFactory.create()
        task = TaskFactory.create()
        wt_path = Path("/tmp/wt")
        result = ReviewResultFactory.create(
            pr_number=pr.number,
            issue_number=pr.issue_number,
            verdict=ReviewVerdict.REQUEST_CHANGES,
            summary="Fix the bugs",
        )

        fix_result = MagicMock()
        fix_result.fixes_made = False
        phase._reviewers.fix_review_findings = AsyncMock(return_value=fix_result)
        phase._bus.publish = AsyncMock()

        outcome = await phase._run_single_review_fix(pr, task, wt_path, result, 1, 0)

        assert outcome is None

    @pytest.mark.asyncio
    async def test_returns_result_when_fixes_made(
        self, config: HydraFlowConfig
    ) -> None:
        """Should return (re_result, updated_diff) when fixes are made."""
        phase = make_review_phase(config)
        pr = PRInfoFactory.create()
        task = TaskFactory.create()
        wt_path = Path("/tmp/wt")
        result = ReviewResultFactory.create(
            pr_number=pr.number,
            issue_number=pr.issue_number,
            verdict=ReviewVerdict.REQUEST_CHANGES,
            summary="Fix the bugs",
        )

        fix_result = MagicMock()
        fix_result.fixes_made = True
        phase._reviewers.fix_review_findings = AsyncMock(return_value=fix_result)
        phase._prs.push_branch = AsyncMock()
        phase._prs.get_pr_diff = AsyncMock(return_value="new diff")

        re_review_result = ReviewResultFactory.create(
            pr_number=pr.number,
            issue_number=pr.issue_number,
            verdict=ReviewVerdict.APPROVE,
            fixes_made=False,
        )
        phase._reviewers.review = AsyncMock(return_value=re_review_result)
        phase._bus.publish = AsyncMock()

        outcome = await phase._run_single_review_fix(pr, task, wt_path, result, 1, 0)

        assert outcome is not None
        re_result, diff = outcome
        assert re_result.verdict == ReviewVerdict.APPROVE
        assert diff == "new diff"

    @pytest.mark.asyncio
    async def test_pushes_again_when_review_makes_fixes(
        self, config: HydraFlowConfig
    ) -> None:
        """If re-review itself makes fixes, should push again."""
        phase = make_review_phase(config)
        pr = PRInfoFactory.create()
        task = TaskFactory.create()
        wt_path = Path("/tmp/wt")
        result = ReviewResultFactory.create(
            pr_number=pr.number,
            issue_number=pr.issue_number,
            verdict=ReviewVerdict.REQUEST_CHANGES,
        )

        fix_result = MagicMock()
        fix_result.fixes_made = True
        phase._reviewers.fix_review_findings = AsyncMock(return_value=fix_result)
        phase._prs.push_branch = AsyncMock()
        phase._prs.get_pr_diff = AsyncMock(return_value="diff")

        re_review_result = ReviewResultFactory.create(
            pr_number=pr.number,
            issue_number=pr.issue_number,
            verdict=ReviewVerdict.REQUEST_CHANGES,
            fixes_made=True,
        )
        phase._reviewers.review = AsyncMock(return_value=re_review_result)
        phase._bus.publish = AsyncMock()

        await phase._run_single_review_fix(pr, task, wt_path, result, 1, 0)

        # push_branch called twice: once for fix, once for re-review fixes
        assert phase._prs.push_branch.await_count == 2


# ---------------------------------------------------------------------------
# _handle_ci_exhaustion tests
# ---------------------------------------------------------------------------


class TestHandleCiExhaustion:
    """Tests for the extracted _handle_ci_exhaustion method."""

    @pytest.mark.asyncio
    async def test_sets_ci_passed_false(self, config: HydraFlowConfig) -> None:
        """Should set result.ci_passed to False."""
        phase = make_review_phase(config)
        pr = PRInfoFactory.create()
        task = TaskFactory.create()
        result = ReviewResultFactory.create(
            pr_number=pr.number, issue_number=pr.issue_number
        )
        result.ci_passed = True  # start True to verify it gets set False

        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()
        phase._bus.publish = AsyncMock()

        await phase._handle_ci_exhaustion(pr, task, result, "CI failed", 0)

        assert result.ci_passed is False

    @pytest.mark.asyncio
    async def test_calls_escalate_ci_failure(self, config: HydraFlowConfig) -> None:
        """Should call _escalate_ci_failure."""
        phase = make_review_phase(config)
        pr = PRInfoFactory.create()
        task = TaskFactory.create()
        result = ReviewResultFactory.create(
            pr_number=pr.number, issue_number=pr.issue_number
        )

        phase._escalate_ci_failure = AsyncMock()
        phase._bus.publish = AsyncMock()

        await phase._handle_ci_exhaustion(pr, task, result, "summary", 0)

        phase._escalate_ci_failure.assert_awaited_once_with(pr, task, "summary", 0)

    @pytest.mark.asyncio
    async def test_suggests_memory_when_transcript(
        self, config: HydraFlowConfig
    ) -> None:
        """Should call _suggest_memory when result has a transcript."""
        phase = make_review_phase(config)
        pr = PRInfoFactory.create()
        task = TaskFactory.create()
        result = ReviewResultFactory.create(
            pr_number=pr.number, issue_number=pr.issue_number
        )
        result.transcript = "some transcript"

        phase._escalate_ci_failure = AsyncMock()
        phase._suggest_memory = AsyncMock()
        phase._bus.publish = AsyncMock()

        await phase._handle_ci_exhaustion(pr, task, result, "summary", 0)

        phase._suggest_memory.assert_awaited_once_with(
            "some transcript", "ci_fix_failure", f"PR #{pr.number}"
        )


# ---------------------------------------------------------------------------
# Visual gate helper tests
# ---------------------------------------------------------------------------


class TestEmitVisualGateTelemetry:
    """Tests for the extracted _emit_visual_gate_telemetry method."""

    @pytest.mark.asyncio
    async def test_emits_event(self, config: HydraFlowConfig, event_bus) -> None:
        """Should publish a VISUAL_GATE event."""
        phase = make_review_phase(config, event_bus=event_bus)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        await phase._emit_visual_gate_telemetry(
            pr, issue, 0, "pass", "all good", 1.23, {"screenshot": "url"}
        )

        history = event_bus.get_history()
        gate_events = [e for e in history if e.type == EventType.VISUAL_GATE]
        assert len(gate_events) == 1
        payload = gate_events[0].data
        # Event data may be stored as dict or Pydantic model
        verdict = (
            payload.get("verdict") if isinstance(payload, dict) else payload.verdict
        )
        reason = payload.get("reason") if isinstance(payload, dict) else payload.reason
        assert verdict == "pass"
        assert reason == "all good"

    @pytest.mark.asyncio
    async def test_no_bus_no_error(self, config: HydraFlowConfig) -> None:
        """Should not raise when bus is None."""
        phase = make_review_phase(config)
        phase._bus = None  # type: ignore[assignment]
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        # Should not raise
        await phase._emit_visual_gate_telemetry(pr, issue, 0, "pass", "ok", 0.5, {})


class TestHandleVisualGatePass:
    """Tests for the extracted _handle_visual_gate_pass method."""

    @pytest.mark.asyncio
    async def test_sets_visual_passed(self, config: HydraFlowConfig) -> None:
        """Should set result.visual_passed to True."""
        phase = make_review_phase(config)
        pr = PRInfoFactory.create()
        result = ReviewResultFactory.create(
            pr_number=pr.number, issue_number=pr.issue_number
        )
        phase._prs.post_pr_comment = AsyncMock()

        await phase._handle_visual_gate_pass(pr, result, "pass", 1.0, {})

        assert result.visual_passed is True

    @pytest.mark.asyncio
    async def test_posts_sign_off_comment(self, config: HydraFlowConfig) -> None:
        """Should post sign-off comment on PR."""
        phase = make_review_phase(config)
        pr = PRInfoFactory.create()
        result = ReviewResultFactory.create(
            pr_number=pr.number, issue_number=pr.issue_number
        )
        phase._prs.post_pr_comment = AsyncMock()

        await phase._handle_visual_gate_pass(pr, result, "pass", 1.5, {})

        phase._prs.post_pr_comment.assert_awaited_once()
        comment = phase._prs.post_pr_comment.call_args[0][1]
        assert "PASSED" in comment
        assert "1.5s" in comment

    @pytest.mark.asyncio
    async def test_includes_artifacts_in_comment(self, config: HydraFlowConfig) -> None:
        """Should include artifact links in sign-off comment."""
        phase = make_review_phase(config)
        pr = PRInfoFactory.create()
        result = ReviewResultFactory.create(
            pr_number=pr.number, issue_number=pr.issue_number
        )
        phase._prs.post_pr_comment = AsyncMock()

        await phase._handle_visual_gate_pass(
            pr, result, "pass", 1.0, {"screenshot": "http://example.com/img.png"}
        )

        comment = phase._prs.post_pr_comment.call_args[0][1]
        assert "screenshot" in comment
        assert "http://example.com/img.png" in comment

    @pytest.mark.asyncio
    async def test_tolerates_comment_post_failure(
        self, config: HydraFlowConfig
    ) -> None:
        """Should not raise when comment posting fails."""
        phase = make_review_phase(config)
        pr = PRInfoFactory.create()
        result = ReviewResultFactory.create(
            pr_number=pr.number, issue_number=pr.issue_number
        )
        phase._prs.post_pr_comment = AsyncMock(side_effect=RuntimeError("network"))

        # Should not raise
        await phase._handle_visual_gate_pass(pr, result, "pass", 1.0, {})
        assert result.visual_passed is True


class TestHandleVisualGateFailure:
    """Tests for the extracted _handle_visual_gate_failure method."""

    @pytest.mark.asyncio
    async def test_sets_visual_passed_false(self, config: HydraFlowConfig) -> None:
        """Should set result.visual_passed to False."""
        phase = make_review_phase(config)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()
        result = ReviewResultFactory.create(
            pr_number=pr.number, issue_number=pr.issue_number
        )
        result.visual_passed = True

        phase._prs.post_pr_comment = AsyncMock()
        phase._escalate_to_hitl = AsyncMock()

        await phase._handle_visual_gate_failure(
            pr, issue, result, "fail", "diff too large"
        )

        assert result.visual_passed is False

    @pytest.mark.asyncio
    async def test_posts_block_comment(self, config: HydraFlowConfig) -> None:
        """Should post block comment on PR."""
        phase = make_review_phase(config)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()
        result = ReviewResultFactory.create(
            pr_number=pr.number, issue_number=pr.issue_number
        )

        phase._prs.post_pr_comment = AsyncMock()
        phase._escalate_to_hitl = AsyncMock()

        await phase._handle_visual_gate_failure(
            pr, issue, result, "fail", "diff too large"
        )

        phase._prs.post_pr_comment.assert_awaited_once()
        comment = phase._prs.post_pr_comment.call_args[0][1]
        assert "BLOCKED" in comment
        assert "fail" in comment

    @pytest.mark.asyncio
    async def test_escalates_to_hitl(self, config: HydraFlowConfig) -> None:
        """Should call _escalate_to_hitl with HitlEscalation."""
        phase = make_review_phase(config)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()
        result = ReviewResultFactory.create(
            pr_number=pr.number, issue_number=pr.issue_number
        )

        phase._prs.post_pr_comment = AsyncMock()
        phase._escalate_to_hitl = AsyncMock()

        await phase._handle_visual_gate_failure(
            pr, issue, result, "fail", "diff too large"
        )

        phase._escalate_to_hitl.assert_awaited_once()
        esc = phase._escalate_to_hitl.call_args[0][0]
        assert isinstance(esc, HitlEscalation)
        assert esc.issue_number == pr.issue_number
        assert esc.pr_number == pr.number
        assert esc.event_cause == "visual_gate_failed"

    @pytest.mark.asyncio
    async def test_tolerates_comment_post_failure(
        self, config: HydraFlowConfig
    ) -> None:
        """Should still escalate even when comment posting fails."""
        phase = make_review_phase(config)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()
        result = ReviewResultFactory.create(
            pr_number=pr.number, issue_number=pr.issue_number
        )

        phase._prs.post_pr_comment = AsyncMock(side_effect=OSError("network"))
        phase._escalate_to_hitl = AsyncMock()

        await phase._handle_visual_gate_failure(pr, issue, result, "warn", "minor diff")

        # Escalation should still happen
        phase._escalate_to_hitl.assert_awaited_once()
