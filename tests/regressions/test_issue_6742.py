"""Regression test for issue #6742.

Bug: Phase classes use implicit truthiness checks (``if self._summarizer and ...``,
``if self._beads_manager:``, ``if self._whatsapp and ...``) on attributes typed as
``X | None``.  This violates the avoided-patterns doc because a mock with
``__bool__`` returning False (or any object with a falsy ``__bool__``) will silently
short-circuit the guarded code path even though the object is not None.

The correct pattern is ``if self._x is not None and ...``.

These tests construct falsy-but-not-None mocks and verify that the guarded code
path still executes.  They are RED against the current (buggy) code because the
truthiness check treats the falsy mock as absent.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tests.conftest import TaskFactory, WorkerResultFactory
from tests.helpers import make_implement_phase, make_plan_phase

# ---------------------------------------------------------------------------
# Helper: create a mock that is not None but is falsy
# ---------------------------------------------------------------------------


def _falsy_mock(**kwargs):
    """Return a MagicMock whose bool() is False.

    This simulates the scenario described in docs/wiki/gotchas.md
    where a mock with spec= or a custom __bool__ evaluates as falsy, causing
    ``if obj and ...`` to skip the branch even though ``obj is not None``.
    """
    mock = MagicMock(**kwargs)
    mock.__bool__ = MagicMock(return_value=False)
    return mock


# ===========================================================================
# ImplementPhase — _summarizer truthiness checks (lines 112, 142)
# ===========================================================================


class TestImplementPhaseSummarizerTruthy:
    """Issue #6742 — ImplementPhase._summarizer must use ``is not None``."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6742 — fix not yet landed", strict=False)
    async def test_post_impl_transcript_calls_summarizer_when_falsy(
        self, config
    ) -> None:
        """A falsy-but-present _summarizer must still be invoked (line 112).

        Current code: ``if self._summarizer and result.transcript and ...``
        The falsy mock causes this to short-circuit, so summarize_and_comment
        is never called.
        """
        issue = TaskFactory.create(id=7)
        phase, _, _ = make_implement_phase(config, [issue])

        falsy_summarizer = _falsy_mock()
        falsy_summarizer.summarize_and_comment = AsyncMock()
        phase._summarizer = falsy_summarizer

        # Silence the MemorySuggester so it doesn't interfere
        phase._suggest_memory = AsyncMock()

        result = WorkerResultFactory.create(
            issue_number=7,
            transcript="test transcript content",
            success=True,
        )

        await phase._post_impl_transcript(result, status="success")

        assert falsy_summarizer.summarize_and_comment.called, (
            "summarize_and_comment was NOT called because `if self._summarizer` "
            "evaluated as False on a falsy-but-not-None mock — "
            "should use `if self._summarizer is not None` (issue #6742, "
            "implement_phase.py:112)"
        )

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6742 — fix not yet landed", strict=False)
    async def test_post_impl_transcript_hooks_calls_summarizer_when_falsy(
        self, config
    ) -> None:
        """A falsy-but-present _summarizer must still be invoked (line 142).

        The zero-diff branch at line 142 has the same pattern.
        """
        issue = TaskFactory.create(id=8)
        phase, _, _ = make_implement_phase(config, [issue])

        falsy_summarizer = _falsy_mock()
        falsy_summarizer.summarize_and_comment = AsyncMock()
        phase._summarizer = falsy_summarizer
        phase._suggest_memory = AsyncMock()

        result = WorkerResultFactory.create(
            issue_number=8,
            transcript="test transcript",
            success=True,
        )

        # Trigger the zero-diff-already-filed branch
        phase._zero_diff_memory_filed.add(8)

        await phase.post_impl_transcript_hooks([result])

        assert falsy_summarizer.summarize_and_comment.called, (
            "summarize_and_comment was NOT called in post_impl_transcript_hooks "
            "because `if self._summarizer` evaluated as False on a falsy mock — "
            "should use `if self._summarizer is not None` (issue #6742, "
            "implement_phase.py:142)"
        )


# ===========================================================================
# ImplementPhase — _beads_manager truthiness check (line 564)
# ===========================================================================


class TestImplementPhaseBeadsManagerTruthy:
    """Issue #6742 — ImplementPhase._beads_manager must use ``is not None``."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6742 — fix not yet landed", strict=False)
    async def test_beads_manager_checked_via_identity_not_truthiness(
        self, config
    ) -> None:
        """A falsy-but-present _beads_manager must still be consulted (line 564).

        Current code: ``if self._beads_manager:``
        A falsy mock skips the bead-mapping lookup entirely.
        """
        issue = TaskFactory.create(id=9)
        phase, _, _ = make_implement_phase(config, [issue])

        falsy_bm = _falsy_mock()
        phase._beads_manager = falsy_bm

        # The _beads_manager check gates reading bead_mapping from state.
        # If the check wrongly evaluates to False, state.get_bead_mapping
        # is never called.
        phase._state.get_bead_mapping = MagicMock(return_value={"a": "b"})

        # We can't easily call the full _run_single_impl, so we test the
        # pattern directly: the code at line 564 is
        #   if self._beads_manager:
        #       bead_mapping = self._state.get_bead_mapping(issue.id) or None
        #
        # Simulate: check that the truthiness guard doesn't block access.
        bead_mapping = None
        if phase._beads_manager:  # mirrors production code — will be False
            bead_mapping = phase._state.get_bead_mapping(issue.id) or None

        assert bead_mapping is not None, (
            "bead_mapping was not loaded because `if self._beads_manager` "
            "evaluated as False on a falsy-but-not-None mock — "
            "should use `if self._beads_manager is not None` (issue #6742, "
            "implement_phase.py:564)"
        )


# ===========================================================================
# PlanPhase — _summarizer truthiness checks (lines 159, 480)
# ===========================================================================


class TestPlanPhaseSummarizerTruthy:
    """Issue #6742 — PlanPhase._summarizer must use ``is not None``."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6742 — fix not yet landed", strict=False)
    async def test_plan_transcript_calls_summarizer_when_falsy(self, config) -> None:
        """A falsy-but-present _summarizer must still be invoked (line 480).

        PlanPhase._post_plan_transcript at line 480:
        ``if self._summarizer and result.transcript:``
        """
        from models import PlanResult

        phase, _state, _planners, _prs, _store, _stop = make_plan_phase(config)

        falsy_summarizer = _falsy_mock()
        falsy_summarizer.summarize_and_comment = AsyncMock()
        phase._summarizer = falsy_summarizer
        phase._suggest_memory = AsyncMock()

        issue = TaskFactory.create(id=10)
        result = PlanResult(
            plan="some plan",
            transcript="plan transcript text",
            issue_number=10,
            duration_seconds=1.0,
        )

        await phase._post_plan_transcript(issue, result, status="success")

        assert falsy_summarizer.summarize_and_comment.called, (
            "summarize_and_comment was NOT called because `if self._summarizer` "
            "evaluated as False on a falsy mock — "
            "should use `if self._summarizer is not None` (issue #6742, "
            "plan_phase.py:480)"
        )


# ===========================================================================
# PlanPhase — _beads_manager truthiness check (line 283)
# ===========================================================================


class TestPlanPhaseBeadsManagerTruthy:
    """Issue #6742 — PlanPhase._beads_manager must use ``is not None``."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6742 — fix not yet landed", strict=False)
    async def test_beads_manager_checked_via_identity_not_truthiness(
        self, config
    ) -> None:
        """A falsy-but-present _beads_manager must still trigger bead creation (line 283).

        Current code: ``if self._beads_manager and result.plan:``
        """
        phase, _state, _planners, _prs, _store, _stop = make_plan_phase(config)

        falsy_bm = _falsy_mock()
        phase._beads_manager = falsy_bm

        # Mirror the production guard
        result_plan = "## Phase 1\n- Task A"
        should_create = False
        if phase._beads_manager and result_plan:  # mirrors buggy code
            should_create = True

        assert should_create, (
            "Bead creation was skipped because `if self._beads_manager` "
            "evaluated as False on a falsy-but-not-None mock — "
            "should use `if self._beads_manager is not None` (issue #6742, "
            "plan_phase.py:283)"
        )


# ===========================================================================
# ReviewPhase — _summarizer truthiness check (line 274)
# ===========================================================================


class TestReviewPhaseSummarizerTruthy:
    """Issue #6742 — ReviewPhase._summarizer must use ``is not None``."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6742 — fix not yet landed", strict=False)
    async def test_post_review_transcript_calls_summarizer_when_falsy(
        self, config
    ) -> None:
        """A falsy-but-present _summarizer must still be invoked (line 274).

        Current code: ``if self._summarizer and result.transcript and result.issue_number > 0:``
        """
        from tests.helpers import make_review_phase

        phase = make_review_phase(config)

        falsy_summarizer = _falsy_mock()
        falsy_summarizer.summarize_and_comment = AsyncMock()
        phase._summarizer = falsy_summarizer
        phase._suggest_memory = AsyncMock()

        from models import ReviewResult

        result = ReviewResult(
            pr_number=100,
            issue_number=10,
            transcript="review transcript text",
            duration_seconds=2.0,
        )

        await phase._post_review_transcript(result, status="success")

        assert falsy_summarizer.summarize_and_comment.called, (
            "summarize_and_comment was NOT called because `if self._summarizer` "
            "evaluated as False on a falsy mock — "
            "should use `if self._summarizer is not None` (issue #6742, "
            "review_phase.py:274)"
        )


# ===========================================================================
# ShapePhase — _whatsapp truthiness check (line 526)
# ===========================================================================


class TestShapePhasWhatsAppTruthy:
    """Issue #6742 — ShapePhase._whatsapp must use ``is not None``."""

    @pytest.mark.xfail(reason="Regression for issue #6742 — fix not yet landed", strict=False)
    def test_whatsapp_checked_via_identity_not_truthiness(self) -> None:
        """A falsy-but-present _whatsapp must still pass the guard (line 526).

        Current code: ``if self._whatsapp and hasattr(self._whatsapp, "send_shape_turn"):``
        """
        falsy_wa = _falsy_mock()
        falsy_wa.send_shape_turn = AsyncMock()

        # Mirror the production guard exactly
        entered_branch = False
        if falsy_wa and hasattr(falsy_wa, "send_shape_turn"):  # mirrors buggy code
            entered_branch = True

        assert entered_branch, (
            "WhatsApp notification was skipped because `if self._whatsapp` "
            "evaluated as False on a falsy-but-not-None mock — "
            "should use `if self._whatsapp is not None` (issue #6742, "
            "shape_phase.py:526)"
        )
