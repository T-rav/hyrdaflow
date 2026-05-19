"""Regression: broad ``except Exception`` blocks must NOT swallow ``CreditExhaustedError``.

Slice #3 + #5.0 audit found 7 loops with broad except blocks that would eat
CreditExhaustedError, causing the loop to burn attempt budget against an
exhausted billing signal. This file guards a representative loop; the
same reraise_on_credit_or_bug pattern covers all 7.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Match the project's PYTHONPATH=src convention used by make quality.
# Mixing `from src.X` and `from X` imports would load some modules under
# two different paths, producing distinct class objects and breaking
# isinstance checks (e.g. reraise_on_credit_or_bug uses bare imports).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from subprocess_util import CreditExhaustedError
from tests.helpers import make_bg_loop_deps

# ---------------------------------------------------------------------------
# CorpusLearningLoop — wraps gh issue list subprocess + escape-signal query
# ---------------------------------------------------------------------------


class TestCorpusLearningCreditExhaustedReraise:
    """CreditExhaustedError raised inside corpus learning broad-except paths must
    propagate, not be swallowed."""

    def _make_loop(self, tmp_path: Path):
        from corpus_learning_loop import CorpusLearningLoop
        from dedup_store import DedupStore

        deps = make_bg_loop_deps(tmp_path)
        pr_manager = AsyncMock()
        pr_manager.list_issues_by_label = AsyncMock(return_value=[])
        dedup = DedupStore(
            "corpus_learning",
            deps.config.data_root / "memory" / "corpus_learning_dedup.json",
        )
        state = MagicMock()
        state.increment_corpus_validation_attempts = MagicMock(return_value=3)
        state.reset_corpus_validation_attempts = MagicMock()

        loop = CorpusLearningLoop(
            config=deps.config,
            prs=pr_manager,
            dedup=dedup,
            state=state,
            deps=deps.loop_deps,
        )
        return loop, pr_manager

    @pytest.mark.asyncio
    async def test_credit_exhausted_propagates_through_escape_signal_query(
        self, tmp_path: Path
    ) -> None:
        """CreditExhaustedError raised by _list_escape_signals must not be swallowed
        by the broad except in _do_work."""
        from unittest.mock import patch

        loop, _ = self._make_loop(tmp_path)

        with (
            patch.object(
                loop,
                "_list_escape_signals",
                new_callable=AsyncMock,
                side_effect=CreditExhaustedError("credits exhausted"),
            ),
            pytest.raises(CreditExhaustedError, match="credits exhausted"),
        ):
            await loop._do_work()

    @pytest.mark.asyncio
    async def test_credit_exhausted_propagates_through_create_issue(
        self, tmp_path: Path
    ) -> None:
        """CreditExhaustedError raised by create_issue in _record_validation_failure
        must propagate out of the broad except that guards it."""
        from corpus_learning_loop import EscapeSignal, ValidationResult

        loop, pr_manager = self._make_loop(tmp_path)
        pr_manager.create_issue = AsyncMock(
            side_effect=CreditExhaustedError("credits exhausted during issue creation")
        )

        signal = EscapeSignal(
            issue_number=99,
            title="test: escape",
            body="",
            updated_at="2026-01-01T00:00:00Z",
            label="skill-escape",
        )
        result = ValidationResult(ok=False, failing_gate="harness", reason="diff empty")

        with pytest.raises(
            CreditExhaustedError, match="credits exhausted during issue creation"
        ):
            await loop._record_validation_failure(signal, result)


# ---------------------------------------------------------------------------
# PlanReviewer — wraps _run_review_subprocess (LLM call)
# ---------------------------------------------------------------------------


class TestPlanReviewerCreditExhaustedReraise:
    """CreditExhaustedError raised by the review subprocess must propagate
    out of the broad except in PlanReviewer.review()."""

    @pytest.mark.asyncio
    async def test_credit_exhausted_propagates_through_review_subprocess(self) -> None:
        from unittest.mock import patch

        from models import PlanResult, Task
        from plan_reviewer import PlanReviewer

        @dataclass
        class _StubConfig:
            dry_run: bool = False
            repo_root: Path = Path("/tmp")
            state_dir: Path = Path("/tmp/state")
            log_dir: Path = Path("/tmp/logs")
            transcript_dir: Path = Path("/tmp/transcripts")

        reviewer = PlanReviewer.__new__(PlanReviewer)
        reviewer._config = _StubConfig()  # type: ignore[assignment]
        reviewer._bus = AsyncMock()  # type: ignore[assignment]

        task = Task(id=42, title="t", body="b")
        plan = PlanResult(
            issue_number=42, success=True, plan="PLAN_START\nstep\nPLAN_END"
        )

        with (
            patch.object(
                PlanReviewer,
                "_run_review_subprocess",
                side_effect=CreditExhaustedError("credits exhausted in plan review"),
            ),
            pytest.raises(
                CreditExhaustedError, match="credits exhausted in plan review"
            ),
        ):
            await reviewer.review(task, plan)


# ---------------------------------------------------------------------------
# BugReproducer — wraps _run_reproducer_subprocess (LLM call)
# ---------------------------------------------------------------------------


class TestBugReproducerCreditExhaustedReraise:
    """CreditExhaustedError raised by the reproducer subprocess must propagate
    out of the broad except in BugReproducer.reproduce()."""

    @pytest.mark.asyncio
    async def test_credit_exhausted_propagates_through_reproducer_subprocess(
        self,
    ) -> None:
        from unittest.mock import patch

        from bug_reproducer import BugReproducer
        from models import Task

        @dataclass
        class _StubConfig:
            dry_run: bool = False
            repo_root: Path = Path("/tmp")
            state_dir: Path = Path("/tmp/state")
            log_dir: Path = Path("/tmp/logs")
            transcript_dir: Path = Path("/tmp/transcripts")

        reproducer = BugReproducer.__new__(BugReproducer)
        reproducer._config = _StubConfig()  # type: ignore[assignment]
        reproducer._bus = AsyncMock()  # type: ignore[assignment]

        task = Task(id=99, title="Bug", body="repro me")

        with (
            patch.object(
                BugReproducer,
                "_run_reproducer_subprocess",
                side_effect=CreditExhaustedError("credits exhausted in bug reproducer"),
            ),
            pytest.raises(
                CreditExhaustedError, match="credits exhausted in bug reproducer"
            ),
        ):
            await reproducer.reproduce(task)


# ---------------------------------------------------------------------------
# IssueStore — wraps TaskFetcher.fetch_all (GitHub poll)
# ---------------------------------------------------------------------------


class TestIssueStoreCreditExhaustedReraise:
    """CreditExhaustedError raised by fetch_all must propagate out of the broad
    except in IssueStore.refresh()."""

    @pytest.mark.asyncio
    async def test_credit_exhausted_propagates_through_refresh(
        self, tmp_path: Path
    ) -> None:
        from events import EventBus
        from issue_store import IssueStore

        deps = make_bg_loop_deps(tmp_path)
        fetcher = MagicMock()
        fetcher.fetch_all = AsyncMock(
            side_effect=CreditExhaustedError("credits exhausted in issue store refresh")
        )
        store = IssueStore(deps.config, fetcher, EventBus())

        with pytest.raises(
            CreditExhaustedError, match="credits exhausted in issue store refresh"
        ):
            await store.refresh()


# ---------------------------------------------------------------------------
# MetricsManager — wraps pr_manager.get_label_counts (gh subprocess)
# ---------------------------------------------------------------------------


class TestMetricsManagerCreditExhaustedReraise:
    """CreditExhaustedError raised by get_label_counts must propagate out of
    the broad except in MetricsManager._build_snapshot()."""

    @pytest.mark.asyncio
    async def test_credit_exhausted_propagates_through_build_snapshot(
        self, tmp_path: Path
    ) -> None:
        from events import EventBus
        from metrics_manager import MetricsManager
        from models import LifetimeStats

        deps = make_bg_loop_deps(tmp_path)
        state = MagicMock()
        state.get_lifetime_stats = MagicMock(return_value=LifetimeStats())
        pr_manager = AsyncMock()
        pr_manager.get_label_counts = AsyncMock(
            side_effect=CreditExhaustedError(
                "credits exhausted in metrics get_label_counts"
            )
        )
        manager = MetricsManager(deps.config, state, pr_manager, EventBus())

        with pytest.raises(
            CreditExhaustedError, match="credits exhausted in metrics get_label_counts"
        ):
            await manager._build_snapshot(None)


# ---------------------------------------------------------------------------
# RetrospectiveLoop — _do_work catches process-item exceptions, and
# _reconcile_closed_hitl_issues catches list_closed_issues_by_label
# ---------------------------------------------------------------------------


class TestRetrospectiveLoopCreditExhaustedReraise:
    """CreditExhaustedError raised inside RetrospectiveLoop's broad-except sites
    must propagate, not be swallowed."""

    def _make_loop(self, tmp_path: Path):
        from retrospective_loop import RetrospectiveLoop

        deps = make_bg_loop_deps(tmp_path)
        retro = MagicMock()
        insights = MagicMock()
        queue = MagicMock()
        prs = AsyncMock()
        loop = RetrospectiveLoop(
            config=deps.config,
            deps=deps.loop_deps,
            retrospective=retro,
            insights=insights,
            queue=queue,
            prs=prs,
        )
        return loop, queue, prs

    @pytest.mark.asyncio
    async def test_credit_exhausted_propagates_through_process_item(
        self, tmp_path: Path
    ) -> None:
        from unittest.mock import patch

        loop, queue, _ = self._make_loop(tmp_path)
        item = MagicMock()
        item.id = "item-1"
        item.kind = "retro"
        queue.load = MagicMock(return_value=[item])

        with (
            patch.object(
                loop,
                "_process_item",
                new_callable=AsyncMock,
                side_effect=CreditExhaustedError(
                    "credits exhausted in retro process_item"
                ),
            ),
            pytest.raises(
                CreditExhaustedError, match="credits exhausted in retro process_item"
            ),
        ):
            await loop._do_work()

    @pytest.mark.asyncio
    async def test_credit_exhausted_propagates_through_reconcile_closed_hitl(
        self, tmp_path: Path
    ) -> None:
        from datetime import UTC, datetime

        loop, _, prs = self._make_loop(tmp_path)
        prs.list_closed_issues_by_label = AsyncMock(
            side_effect=CreditExhaustedError(
                "credits exhausted in list_closed_issues_by_label"
            )
        )
        # Seed the in-memory window so the early-return on empty doesn't fire.
        loop._hitl_filed_at["recurring_feedback"] = datetime.now(UTC)

        with pytest.raises(
            CreditExhaustedError,
            match="credits exhausted in list_closed_issues_by_label",
        ):
            await loop._reconcile_closed_hitl_issues()


# ---------------------------------------------------------------------------
# ReportIssueLoop — cost-budget sweep (peek_report=None branch)
# ---------------------------------------------------------------------------


class TestReportIssueLoopCreditExhaustedReraise:
    """CreditExhaustedError raised inside the cost-budget sweep must propagate
    out of the broad except guarding the rollup read."""

    @pytest.mark.asyncio
    async def test_credit_exhausted_propagates_through_cost_budget_sweep(
        self, tmp_path: Path
    ) -> None:
        from unittest.mock import patch

        from report_issue_loop import ReportIssueLoop

        deps = make_bg_loop_deps(tmp_path)
        state = MagicMock()
        state.peek_report = MagicMock(return_value=None)
        pr_manager = AsyncMock()

        loop = ReportIssueLoop(
            config=deps.config,
            state=state,
            pr_manager=pr_manager,
            deps=deps.loop_deps,
        )

        async def _noop_sweep() -> int:
            return 0

        with (
            patch.object(
                loop, "_sweep_stale_reports", new_callable=AsyncMock, return_value=0
            ),
            patch.object(
                loop, "_sync_filed_reports", new_callable=AsyncMock, return_value=0
            ),
            patch(
                "report_issue_loop.build_rolling_24h",
                side_effect=CreditExhaustedError(
                    "credits exhausted in cost budget sweep"
                ),
            ),
            pytest.raises(
                CreditExhaustedError, match="credits exhausted in cost budget sweep"
            ),
        ):
            _ = _noop_sweep  # keep helper name referenced for clarity
            await loop._do_work()
