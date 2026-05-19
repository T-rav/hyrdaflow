"""Tests for the RetrospectiveLoop background worker."""

from __future__ import annotations

import pytest
from pydantic import ValidationError


class TestRetrospectiveIntervalConfig:
    def test_default_interval(self) -> None:
        from config import HydraFlowConfig

        cfg = HydraFlowConfig()
        assert cfg.retrospective_interval == 1800

    def test_rejects_below_minimum(self) -> None:
        from config import HydraFlowConfig

        with pytest.raises(ValidationError):
            HydraFlowConfig(retrospective_interval=10)

    def test_accepts_valid_value(self) -> None:
        from config import HydraFlowConfig

        cfg = HydraFlowConfig(retrospective_interval=3600)
        assert cfg.retrospective_interval == 3600


# ---------------------------------------------------------------------------
# RetrospectiveLoop tests
# ---------------------------------------------------------------------------

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from events import EventType
from retrospective_loop import RetrospectiveLoop
from retrospective_queue import QueueItem, QueueKind
from tests.helpers import make_bg_loop_deps


def _make_loop(
    tmp_path: Path,
    *,
    with_prs: bool = False,
) -> tuple[RetrospectiveLoop, MagicMock, MagicMock, MagicMock, MagicMock | None]:
    """Build loop with mocks. Returns (loop, retro_mock, insights_mock, queue_mock, prs_mock)."""
    deps = make_bg_loop_deps(tmp_path, enabled=True)

    retro = MagicMock()
    retro._load_recent = MagicMock(return_value=[])
    retro._detect_patterns = AsyncMock()

    insights = MagicMock()
    insights.load_recent = MagicMock(return_value=[])
    insights.get_proposed_categories = MagicMock(return_value=set())
    insights.mark_category_proposed = MagicMock()
    insights.record_proposal = MagicMock()

    queue = MagicMock()
    queue.load = MagicMock(return_value=[])
    queue.acknowledge = MagicMock()

    prs: MagicMock | None = None
    if with_prs:
        prs = MagicMock()
        prs.create_issue = AsyncMock(return_value=0)
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
    return loop, retro, insights, queue, prs


class TestDoWorkEmptyQueue:
    @pytest.mark.asyncio
    async def test_returns_zero_counts(self, tmp_path: Path) -> None:
        loop, _, _, queue, _ = _make_loop(tmp_path)
        queue.load.return_value = []

        result = await loop._do_work()

        assert result == {"processed": 0, "patterns_filed": 0, "stale_proposals": 0}

    @pytest.mark.asyncio
    async def test_does_not_acknowledge_anything(self, tmp_path: Path) -> None:
        loop, _, _, queue, _ = _make_loop(tmp_path)
        queue.load.return_value = []

        await loop._do_work()

        queue.acknowledge.assert_not_called()


class TestDoWorkProcessesItems:
    @pytest.mark.asyncio
    async def test_processes_retro_pattern_item(self, tmp_path: Path) -> None:
        loop, retro, _, queue, _ = _make_loop(tmp_path)
        item = QueueItem(kind=QueueKind.RETRO_PATTERNS, issue_number=42)
        queue.load.return_value = [item]

        await loop._do_work()

        retro._detect_patterns.assert_awaited_once()
        queue.acknowledge.assert_called_once_with([item.id])

    @pytest.mark.asyncio
    async def test_processes_review_pattern_item(self, tmp_path: Path) -> None:
        loop, _, insights, queue, _ = _make_loop(tmp_path)
        item = QueueItem(kind=QueueKind.REVIEW_PATTERNS, pr_number=99)
        queue.load.return_value = [item]

        await loop._do_work()

        insights.load_recent.assert_called()
        queue.acknowledge.assert_called_once_with([item.id])

    @pytest.mark.asyncio
    async def test_processes_verify_proposals_item(self, tmp_path: Path) -> None:
        loop, _, insights, queue, _ = _make_loop(tmp_path)
        item = QueueItem(kind=QueueKind.VERIFY_PROPOSALS)
        queue.load.return_value = [item]

        await loop._do_work()

        queue.acknowledge.assert_called_once_with([item.id])

    @pytest.mark.asyncio
    async def test_publishes_event_per_item(self, tmp_path: Path) -> None:
        loop, _, _, queue, _ = _make_loop(tmp_path)
        item = QueueItem(kind=QueueKind.RETRO_PATTERNS, issue_number=42)
        queue.load.return_value = [item]

        await loop._do_work()

        events = [
            e
            for e in loop._bus.get_history()
            if e.type == EventType.RETROSPECTIVE_UPDATE
        ]
        assert len(events) >= 1
        assert events[0].data.get("status") == "processed"


class TestDoWorkErrorHandling:
    @pytest.mark.asyncio
    async def test_failed_item_not_acknowledged(self, tmp_path: Path) -> None:
        loop, retro, _, queue, _ = _make_loop(tmp_path)
        item = QueueItem(kind=QueueKind.RETRO_PATTERNS, issue_number=42)
        queue.load.return_value = [item]
        retro._detect_patterns.side_effect = RuntimeError("boom")

        result = await loop._do_work()

        queue.acknowledge.assert_not_called()
        assert result is not None
        assert result["processed"] == 0


class TestReviewPatternIssueFiling:
    """_handle_review_patterns files issues for detected patterns."""

    @pytest.mark.asyncio
    async def test_files_issue_for_new_pattern(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        loop, _, insights, queue, prs = _make_loop(tmp_path, with_prs=True)
        assert prs is not None
        item = QueueItem(kind=QueueKind.REVIEW_PATTERNS, pr_number=99)
        queue.load.return_value = [item]

        fake_record = MagicMock()
        fake_record.verdict = "REQUEST_CHANGES"
        fake_record.categories = ["missing_tests"]
        insights.load_recent.return_value = [fake_record]
        insights.get_proposed_categories.return_value = set()

        with (
            patch(
                "review_insights.analyze_patterns",
                return_value=[("missing_tests", 3, [fake_record])],
            ),
            patch("review_insights.build_insight_issue_body", return_value="body"),
            patch(
                "review_insights.CATEGORY_DESCRIPTIONS",
                {"missing_tests": "Missing test coverage"},
            ),
        ):
            await loop._do_work()

        prs.create_issue.assert_awaited_once()
        insights.mark_category_proposed.assert_called_once_with("missing_tests")
        insights.record_proposal.assert_called_once_with("missing_tests", pre_count=3)

    @pytest.mark.asyncio
    async def test_skips_already_proposed_category(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        loop, _, insights, queue, prs = _make_loop(tmp_path, with_prs=True)
        assert prs is not None
        item = QueueItem(kind=QueueKind.REVIEW_PATTERNS, pr_number=99)
        queue.load.return_value = [item]

        fake_record = MagicMock()
        insights.load_recent.return_value = [fake_record]
        insights.get_proposed_categories.return_value = {"missing_tests"}

        with (
            patch(
                "review_insights.analyze_patterns",
                return_value=[("missing_tests", 3, [fake_record])],
            ),
            patch("review_insights.CATEGORY_DESCRIPTIONS", {}),
        ):
            await loop._do_work()

        prs.create_issue.assert_not_awaited()


class TestVerifyProposalEscalation:
    """_handle_verify_proposals escalates stale proposals to HITL."""

    @pytest.mark.asyncio
    async def test_files_hitl_issue_for_stale_proposal(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        loop, _, insights, queue, prs = _make_loop(tmp_path, with_prs=True)
        assert prs is not None
        item = QueueItem(kind=QueueKind.VERIFY_PROPOSALS)
        queue.load.return_value = [item]
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
            await loop._do_work()

        prs.create_issue.assert_awaited_once()
        call_args = prs.create_issue.call_args
        assert "HITL" in call_args[0][0]
        assert "missing_tests" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_no_prs_logs_warning_no_crash(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        loop, _, insights, queue, _ = _make_loop(tmp_path, with_prs=False)
        item = QueueItem(kind=QueueKind.VERIFY_PROPOSALS)
        queue.load.return_value = [item]
        insights.load_recent.return_value = []

        with (
            patch(
                "review_insights.verify_proposals",
                return_value=["stale_cat"],
            ),
            patch("review_insights.CATEGORY_DESCRIPTIONS", {}),
            patch("review_insights._PROPOSAL_STALE_DAYS", 30),
        ):
            result = await loop._do_work()

        # Should still process (not crash), just not file issues
        assert result is not None
        assert result["processed"] == 1


class TestMultipleItemBatch:
    """Processing multiple items in a single cycle."""

    @pytest.mark.asyncio
    async def test_processes_mixed_items(self, tmp_path: Path) -> None:
        loop, retro, _, queue, _ = _make_loop(tmp_path)
        items = [
            QueueItem(kind=QueueKind.RETRO_PATTERNS, issue_number=1),
            QueueItem(kind=QueueKind.RETRO_PATTERNS, issue_number=2),
        ]
        queue.load.return_value = items

        result = await loop._do_work()

        assert result is not None
        assert result["processed"] == 2
        assert retro._detect_patterns.await_count == 2
        queue.acknowledge.assert_called_once_with([items[0].id, items[1].id])


class TestStaleHITLDedup:
    """Issue #8988 — dedup [HITL] Stale review insight: <category> filings.

    Behaviors guarded:
      1. Same category stale across N ticks → 1 open issue + N-1 comments.
      2. Closed-and-re-armed: stale → file → human closes → stale again → new file.
      3. In-memory `_hitl_filed_at` window guard prevents same-tick double-file
         even when the open-issue lookup races.
    """

    @pytest.mark.asyncio
    async def test_five_stale_ticks_one_issue_four_comments(
        self, tmp_path: Path
    ) -> None:
        """5 ticks of the same stale category → create_issue called once,
        post_comment called 4 times (ticks 2..5 comment on the open one)."""
        from unittest.mock import patch

        loop, _, insights, queue, prs = _make_loop(tmp_path, with_prs=True)
        assert prs is not None
        item = QueueItem(kind=QueueKind.VERIFY_PROPOSALS)
        insights.load_recent.return_value = []

        # First call creates issue #4242. Subsequent find_existing_issue
        # calls discover it as open.
        prs.create_issue.return_value = 4242

        def find_existing_side_effect(title: str) -> int:
            # Mimics gh: returns 0 before create, 4242 after.
            return 4242 if prs.create_issue.await_count > 0 else 0

        prs.find_existing_issue.side_effect = find_existing_side_effect

        # Each tick must re-load the queue (load is sync).  We reset queue
        # state between ticks because acknowledge() clears nothing in the
        # mock — but we need queue.load() to return the same item every tick.
        queue.load.return_value = [item]

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
            # Advance simulated time per tick so the window-guard does not
            # block the 5 ticks (default window is 1 hour).
            from datetime import UTC, datetime, timedelta

            base = datetime(2026, 5, 19, 0, 0, 0, tzinfo=UTC)
            for tick_idx in range(5):
                fake_now = base + timedelta(hours=2 * tick_idx)
                with patch(
                    "retrospective_loop._now_utc",
                    return_value=fake_now,
                ):
                    # New item id per tick so acknowledge tracking is clean
                    item2 = QueueItem(kind=QueueKind.VERIFY_PROPOSALS)
                    queue.load.return_value = [item2]
                    await loop._do_work()

        assert prs.create_issue.await_count == 1, (
            f"expected exactly 1 create_issue, got {prs.create_issue.await_count}"
        )
        assert prs.post_comment.await_count == 4, (
            f"expected 4 follow-up comments, got {prs.post_comment.await_count}"
        )
        # The four comments must target the open issue #4242
        for call in prs.post_comment.await_args_list:
            assert call.args[0] == 4242

    @pytest.mark.asyncio
    async def test_closed_then_re_armed_files_new_issue(self, tmp_path: Path) -> None:
        """Closed HITL issue → category stale again → 1 NEW issue filed.

        Mirrors FakeCoverageAuditorLoop._reconcile_closed_escalations:
        a closed escalation resets dedup so the category re-arms.
        """
        from datetime import UTC, datetime
        from unittest.mock import patch

        loop, _, insights, queue, prs = _make_loop(tmp_path, with_prs=True)
        assert prs is not None
        insights.load_recent.return_value = []

        prs.create_issue.return_value = 5000

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
            # ---- Tick 1: file new issue ----
            queue.load.return_value = [QueueItem(kind=QueueKind.VERIFY_PROPOSALS)]
            prs.find_existing_issue.return_value = 0  # nothing open
            with patch(
                "retrospective_loop._now_utc",
                return_value=datetime(2026, 5, 19, 0, 0, 0, tzinfo=UTC),
            ):
                await loop._do_work()

            assert prs.create_issue.await_count == 1
            assert prs.post_comment.await_count == 0

            # ---- Tick 2: human has closed #5000 ----
            # find_existing_issue now returns 0 (no OPEN one), but the loop
            # also checks list_closed_issues_by_label to re-arm the in-memory
            # window-tracker.
            queue.load.return_value = [QueueItem(kind=QueueKind.VERIFY_PROPOSALS)]
            prs.find_existing_issue.return_value = 0
            prs.list_closed_issues_by_label.return_value = [
                {
                    "number": 5000,
                    "title": "[HITL] Stale review insight: Missing test coverage",
                    "body": "",
                    "updated_at": "2026-05-19T01:00:00Z",
                }
            ]
            # Ensure we are outside the window guard (default 1h)
            with patch(
                "retrospective_loop._now_utc",
                return_value=datetime(2026, 5, 20, 0, 0, 0, tzinfo=UTC),
            ):
                await loop._do_work()

            assert prs.create_issue.await_count == 2, (
                f"expected re-armed file, got {prs.create_issue.await_count}"
            )

    @pytest.mark.asyncio
    async def test_window_guard_blocks_double_file_within_window(
        self, tmp_path: Path
    ) -> None:
        """Two ticks within the dedup window must not double-file even if
        find_existing_issue races and returns 0 both times."""
        from datetime import UTC, datetime
        from unittest.mock import patch

        loop, _, insights, queue, prs = _make_loop(tmp_path, with_prs=True)
        assert prs is not None
        insights.load_recent.return_value = []

        prs.create_issue.return_value = 9001
        prs.find_existing_issue.return_value = 0  # always race-lose

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
            queue.load.return_value = [QueueItem(kind=QueueKind.VERIFY_PROPOSALS)]
            with patch(
                "retrospective_loop._now_utc",
                return_value=datetime(2026, 5, 19, 0, 0, 0, tzinfo=UTC),
            ):
                await loop._do_work()

            assert prs.create_issue.await_count == 1

            # Five minutes later — still well inside default window.
            queue.load.return_value = [QueueItem(kind=QueueKind.VERIFY_PROPOSALS)]
            with patch(
                "retrospective_loop._now_utc",
                return_value=datetime(2026, 5, 19, 0, 5, 0, tzinfo=UTC),
            ):
                await loop._do_work()

            assert prs.create_issue.await_count == 1, (
                "Window guard must prevent second file inside the cooldown"
            )
