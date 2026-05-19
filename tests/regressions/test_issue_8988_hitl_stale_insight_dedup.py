"""Regression for issue #8988 — RetrospectiveLoop must not file duplicate
``[HITL] Stale review insight: <category>`` issues every tick.

Before the fix, ``RetrospectiveLoop._handle_verify_proposals`` filed a fresh
issue on **every** tick a category was stale, with no open-issue check.  Four
duplicates were closed manually on 2026-05-19 (``Missing or insufficient test
coverage`` was filed multiple times for the same recurring pattern).

The contract guarded here:

1. Same category stale across N ticks → 1 ``create_issue`` + N-1 ``post_comment``.
2. ``[HITL] Stale review insight:`` fallback at
   ``src/review_phase/_phase.py:3216`` follows the same dedup contract.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from retrospective_loop import RetrospectiveLoop
from retrospective_queue import QueueItem, QueueKind
from tests.helpers import make_bg_loop_deps


def _make_loop_with_prs(
    tmp_path: Path,
) -> tuple[RetrospectiveLoop, MagicMock, MagicMock, MagicMock]:
    """Return (loop, insights, queue, prs) with PRPort mocks wired."""
    deps = make_bg_loop_deps(tmp_path, enabled=True)

    retro = MagicMock()
    retro._load_recent = MagicMock(return_value=[])
    retro._detect_patterns = AsyncMock()

    insights = MagicMock()
    insights.load_recent = MagicMock(return_value=[])
    insights.get_proposed_categories = MagicMock(return_value=set())

    queue = MagicMock()
    queue.load = MagicMock(return_value=[])
    queue.acknowledge = MagicMock()

    prs = MagicMock()
    prs.create_issue = AsyncMock(return_value=4242)
    prs.find_existing_issue = AsyncMock(return_value=0)
    prs.list_closed_issues_by_label = AsyncMock(return_value=[])
    prs.post_comment = AsyncMock()

    loop = RetrospectiveLoop(
        config=deps.config,
        deps=deps.loop_deps,
        retrospective=retro,
        insights=insights,
        queue=queue,
        prs=prs,
    )
    return loop, insights, queue, prs


class TestStaleHITLDedupRegression:
    """Issue #8988 regression — guards the dedup contract end-to-end."""

    @pytest.mark.asyncio
    async def test_five_ticks_one_issue_four_comments(self, tmp_path: Path) -> None:
        loop, insights, queue, prs = _make_loop_with_prs(tmp_path)
        insights.load_recent.return_value = []

        # After the first create, GitHub returns the open issue number.
        def find_side_effect(_title: str) -> int:
            return 4242 if prs.create_issue.await_count > 0 else 0

        prs.find_existing_issue.side_effect = find_side_effect

        with (
            patch(
                "review_insights.verify_proposals",
                return_value=["missing_tests"],
            ),
            patch(
                "review_insights.CATEGORY_DESCRIPTIONS",
                {"missing_tests": "Missing test coverage"},
            ),
            patch("review_insights._PROPOSAL_STALE_DAYS", 30),
        ):
            from datetime import timedelta

            base = datetime(2026, 5, 19, 0, 0, 0, tzinfo=UTC)
            for tick_idx in range(5):
                fake_now = base + timedelta(hours=2 * tick_idx)
                queue.load.return_value = [QueueItem(kind=QueueKind.VERIFY_PROPOSALS)]
                with patch("retrospective_loop._now_utc", return_value=fake_now):
                    await loop._do_work()

        assert prs.create_issue.await_count == 1
        assert prs.post_comment.await_count == 4
        for call in prs.post_comment.await_args_list:
            assert call.args[0] == 4242

    @pytest.mark.asyncio
    async def test_closed_then_re_armed(self, tmp_path: Path) -> None:
        """Human close → next stale tick files fresh."""
        from datetime import timedelta

        loop, insights, queue, prs = _make_loop_with_prs(tmp_path)
        insights.load_recent.return_value = []

        with (
            patch(
                "review_insights.verify_proposals",
                return_value=["missing_tests"],
            ),
            patch(
                "review_insights.CATEGORY_DESCRIPTIONS",
                {"missing_tests": "Missing test coverage"},
            ),
            patch("review_insights._PROPOSAL_STALE_DAYS", 30),
        ):
            # Tick 1 — file new issue
            prs.find_existing_issue.return_value = 0
            queue.load.return_value = [QueueItem(kind=QueueKind.VERIFY_PROPOSALS)]
            with patch(
                "retrospective_loop._now_utc",
                return_value=datetime(2026, 5, 19, 0, 0, 0, tzinfo=UTC),
            ):
                await loop._do_work()

            assert prs.create_issue.await_count == 1
            # Tick 2 — human closes #4242, next stale tick must re-arm
            prs.list_closed_issues_by_label.return_value = [
                {
                    "number": 4242,
                    "title": "[HITL] Stale review insight: Missing test coverage",
                    "body": "",
                    "updated_at": "2026-05-19T01:00:00Z",
                }
            ]
            queue.load.return_value = [QueueItem(kind=QueueKind.VERIFY_PROPOSALS)]
            with patch(
                "retrospective_loop._now_utc",
                return_value=datetime(2026, 5, 19, 0, 0, 0, tzinfo=UTC)
                + timedelta(days=1),
            ):
                await loop._do_work()

            assert prs.create_issue.await_count == 2


class TestReviewPhaseFallbackDedup:
    """Mirror site — ``src/review_phase/_phase.py:3216`` (fallback branch)
    must also dedup when a HITL stale-insight issue is already open.
    """

    @pytest.mark.asyncio
    async def test_fallback_branch_dedups_via_find_existing_issue(self) -> None:
        """The fallback path (no retrospective_queue wired) must comment on
        an existing open HITL issue rather than file a duplicate."""
        from models import ReviewVerdict
        from tests.conftest import ConfigFactory, ReviewResultFactory
        from tests.helpers import make_review_phase

        config = ConfigFactory.create()
        phase = make_review_phase(config, default_mocks=True)
        # Disable the queue so we go down the fallback branch.
        phase._retrospective_queue = None

        # Wire up dedup-aware port mocks.
        phase._prs.find_existing_issue = AsyncMock(return_value=7777)
        phase._prs.post_comment = AsyncMock()
        phase._prs.create_task = AsyncMock()

        result = ReviewResultFactory.create(verdict=ReviewVerdict.REQUEST_CHANGES)

        mock_insights = MagicMock()
        mock_insights.load_recent.return_value = []
        mock_insights.get_proposed_categories.return_value = set()
        phase._insights = mock_insights

        with (
            patch("review_phase.analyze_patterns", return_value=[]),
            patch(
                "review_phase._phase.verify_proposals",
                return_value=["missing_tests"],
            ),
            patch(
                "review_phase._phase.CATEGORY_DESCRIPTIONS",
                {"missing_tests": "Missing test coverage"},
            ),
            patch("review_phase._phase._PROPOSAL_STALE_DAYS", 30),
        ):
            await phase._record_review_insight(result)

        # Existing open issue → comment, do NOT create a new task.
        phase._prs.post_comment.assert_awaited_once()
        assert phase._prs.post_comment.await_args.args[0] == 7777
        phase._prs.create_task.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_fallback_window_guard_skips_back_to_back_filings(self) -> None:
        """Review #8992 S2 fix: two PR reviews completing back-to-back for
        the same stale category must not both file — the in-memory
        ``_hitl_filed_at`` window guard short-circuits the second call
        before it can race ``find_existing_issue``.
        """
        from models import ReviewVerdict
        from tests.conftest import ConfigFactory, ReviewResultFactory
        from tests.helpers import make_review_phase

        config = ConfigFactory.create()
        phase = make_review_phase(config, default_mocks=True)
        phase._retrospective_queue = None

        # First call: no open issue → would file. Second call: same
        # category, no open issue *yet* (GH search hasn't indexed) →
        # must be short-circuited by the window guard.
        phase._prs.find_existing_issue = AsyncMock(return_value=None)
        phase._prs.post_comment = AsyncMock()
        phase._prs.create_task = AsyncMock()

        result = ReviewResultFactory.create(verdict=ReviewVerdict.REQUEST_CHANGES)

        mock_insights = MagicMock()
        mock_insights.load_recent.return_value = []
        mock_insights.get_proposed_categories.return_value = set()
        phase._insights = mock_insights

        with (
            patch("review_phase.analyze_patterns", return_value=[]),
            patch(
                "review_phase._phase.verify_proposals",
                return_value=["missing_tests"],
            ),
            patch(
                "review_phase._phase.CATEGORY_DESCRIPTIONS",
                {"missing_tests": "Missing test coverage"},
            ),
            patch("review_phase._phase._PROPOSAL_STALE_DAYS", 30),
        ):
            # First tick: fires through to create_task.
            await phase._record_review_insight(result)
            # Second tick (back-to-back, same category): blocked by guard.
            await phase._record_review_insight(result)

        # Only one task created — window guard skipped the second tick.
        assert phase._prs.create_task.await_count == 1


class TestRetrospectiveLoopGuardCrashWindow:
    """Review #8992 S1 fix: the in-memory ``_hitl_filed_at`` guard must
    be populated BEFORE the ``await create_issue``, not after — otherwise
    a crash between the GitHub write and the assignment leaves the
    just-filed issue with no in-memory guard on restart.
    """

    @pytest.mark.asyncio
    async def test_guard_is_set_before_create_issue_await(
        self, tmp_path: Path
    ) -> None:
        from retrospective_loop import RetrospectiveLoop  # noqa: PLC0415

        loop, insights, _queue, prs = _make_loop_with_prs(tmp_path)
        prs.find_existing_issue = AsyncMock(return_value=None)
        prs.post_comment = AsyncMock()

        # Sentinel that captures the guard value at the moment of the await.
        captured: dict[str, datetime | None] = {"value_at_await": None}

        async def capture_create_issue(_title, _body, _labels):
            captured["value_at_await"] = loop._hitl_filed_at.get(
                "missing_tests"
            )
            return 9999

        prs.create_issue = AsyncMock(side_effect=capture_create_issue)

        insights.load_recent.return_value = []

        with patch(
            "review_insights.verify_proposals",
            return_value=["missing_tests"],
        ):
            await loop._handle_verify_proposals()

        # The guard was set *before* the await completed — fixing
        # the crash-window race.
        assert captured["value_at_await"] is not None
