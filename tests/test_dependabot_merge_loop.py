"""Tests for the DependabotMergeLoop background worker."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from dependabot_merge_loop import DependabotMergeLoop
from events import EventType
from models import DependabotMergeSettings, PRListItem
from tests.helpers import make_bg_loop_deps


def _make_pr(
    pr: int, author: str = "dependabot[bot]", title: str = "Bump foo"
) -> PRListItem:
    """Build a minimal PRListItem for testing."""
    return PRListItem(
        pr=pr,
        author=author,
        title=title,
        url=f"https://github.com/o/r/pull/{pr}",
    )


def _make_state(
    *,
    authors: list[str] | None = None,
    failure_strategy: str = "skip",
    processed: set[int] | None = None,
) -> MagicMock:
    """Build a mock StateTracker with bot PR methods."""
    state = MagicMock()
    settings = DependabotMergeSettings(
        authors=authors or ["dependabot[bot]"],
        failure_strategy=failure_strategy,
    )
    state.get_dependabot_merge_settings.return_value = settings
    state.get_dependabot_merge_processed.return_value = processed or set()
    return state


def _make_loop(
    tmp_path: Path,
    *,
    enabled: bool = True,
    interval: int = 60,
    open_prs: list[PRListItem] | None = None,
    ci_result: tuple[bool, str] = (True, "All checks passed"),
    merge_result: bool = True,
    failure_strategy: str = "skip",
    processed: set[int] | None = None,
    authors: list[str] | None = None,
) -> tuple[DependabotMergeLoop, asyncio.Event, MagicMock, MagicMock, MagicMock]:
    """Build a DependabotMergeLoop with test-friendly defaults.

    Returns (loop, stop_event, cache_mock, prs_mock, state_mock).
    """
    deps = make_bg_loop_deps(
        tmp_path, enabled=enabled, dependabot_merge_interval=interval
    )

    cache = MagicMock()
    cache.get_open_prs.return_value = open_prs or []

    prs = MagicMock()
    prs.wait_for_ci = AsyncMock(return_value=ci_result)
    prs.submit_review = AsyncMock(return_value=True)
    prs.merge_pr = AsyncMock(return_value=merge_result)
    prs.add_labels = AsyncMock()
    prs.post_comment = AsyncMock()
    prs.close_issue = AsyncMock()

    state = _make_state(
        authors=authors,
        failure_strategy=failure_strategy,
        processed=processed,
    )

    loop = DependabotMergeLoop(
        config=deps.config,
        cache=cache,
        prs=prs,
        state=state,
        deps=deps.loop_deps,
    )
    return loop, deps.stop_event, cache, prs, state


class TestDependabotMergeLoopInterval:
    def test_default_interval_uses_config(self, tmp_path: Path) -> None:
        """_get_default_interval returns config.dependabot_merge_interval."""
        loop, *_ = _make_loop(tmp_path, interval=120)
        assert loop._get_default_interval() == 120


class TestDependabotMergeLoopDoWork:
    @pytest.mark.asyncio
    async def test_no_bot_prs_returns_zeros(self, tmp_path: Path) -> None:
        """When no open PRs match bot authors, all counters are zero."""
        loop, *_ = _make_loop(tmp_path, open_prs=[])
        result = await loop._do_work()
        assert result == {"merged": 0, "skipped": 0, "failed": 0}

    @pytest.mark.asyncio
    async def test_non_bot_author_ignored(self, tmp_path: Path) -> None:
        """PRs from non-bot authors are not processed."""
        loop, _, _, prs, _ = _make_loop(
            tmp_path,
            open_prs=[_make_pr(1, author="human-dev")],
        )
        result = await loop._do_work()
        assert result == {"merged": 0, "skipped": 0, "failed": 0}
        prs.wait_for_ci.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_already_processed_skipped(self, tmp_path: Path) -> None:
        """PRs already in the processed set are not re-checked."""
        loop, _, _, prs, _ = _make_loop(
            tmp_path,
            open_prs=[_make_pr(42)],
            processed={42},
        )
        result = await loop._do_work()
        assert result == {"merged": 0, "skipped": 0, "failed": 0}
        prs.wait_for_ci.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_ci_green_approves_and_merges(self, tmp_path: Path) -> None:
        """When CI passes, the PR is approved and merged."""
        loop, _, _, prs, state = _make_loop(
            tmp_path,
            open_prs=[_make_pr(10)],
            ci_result=(True, "All checks passed"),
        )

        result = await loop._do_work()

        assert result["merged"] == 1
        prs.submit_review.assert_awaited_once()
        prs.merge_pr.assert_awaited_once_with(10, auto_rebase=True)
        state.add_dependabot_merge_processed.assert_called_once_with(10)

    @pytest.mark.asyncio
    async def test_ci_green_merge_fails(self, tmp_path: Path) -> None:
        """When CI passes but merge fails, it counts as failed."""
        loop, _, _, prs, state = _make_loop(
            tmp_path,
            open_prs=[_make_pr(10)],
            ci_result=(True, "All checks passed"),
            merge_result=False,
        )

        result = await loop._do_work()

        assert result["failed"] == 1
        assert result["merged"] == 0
        state.add_dependabot_merge_processed.assert_not_called()

    @pytest.mark.asyncio
    async def test_ci_pending_skips(self, tmp_path: Path) -> None:
        """When CI times out (still pending), the PR is skipped for retry."""
        loop, _, _, prs, state = _make_loop(
            tmp_path,
            open_prs=[_make_pr(10)],
            ci_result=(False, "CI timed out after 60s"),
        )

        result = await loop._do_work()

        assert result["skipped"] == 1
        assert result["merged"] == 0
        prs.merge_pr.assert_not_awaited()
        state.add_dependabot_merge_processed.assert_not_called()

    @pytest.mark.asyncio
    async def test_ci_failed_strategy_skip(self, tmp_path: Path) -> None:
        """failure_strategy=skip leaves the PR open without tracking."""
        loop, _, _, prs, state = _make_loop(
            tmp_path,
            open_prs=[_make_pr(10)],
            ci_result=(False, "2/5 checks failed: lint, test"),
            failure_strategy="skip",
        )

        result = await loop._do_work()

        assert result["skipped"] == 1
        prs.merge_pr.assert_not_awaited()
        state.add_dependabot_merge_processed.assert_not_called()

    @pytest.mark.asyncio
    async def test_ci_failed_strategy_hitl(self, tmp_path: Path) -> None:
        """failure_strategy=hitl adds labels and comments, then tracks."""
        loop, _, _, prs, state = _make_loop(
            tmp_path,
            open_prs=[_make_pr(10)],
            ci_result=(False, "2/5 checks failed: lint, test"),
            failure_strategy="hitl",
        )

        result = await loop._do_work()

        assert result["failed"] == 1
        prs.add_labels.assert_awaited_once()
        prs.post_comment.assert_awaited_once()
        state.add_dependabot_merge_processed.assert_called_once_with(10)

    @pytest.mark.asyncio
    async def test_ci_failed_strategy_close(self, tmp_path: Path) -> None:
        """failure_strategy=close comments and closes the PR, then tracks."""
        loop, _, _, prs, state = _make_loop(
            tmp_path,
            open_prs=[_make_pr(10)],
            ci_result=(False, "2/5 checks failed: lint, test"),
            failure_strategy="close",
        )

        result = await loop._do_work()

        assert result["failed"] == 1
        prs.post_comment.assert_awaited_once()
        prs.close_issue.assert_awaited_once_with(10)
        state.add_dependabot_merge_processed.assert_called_once_with(10)

    @pytest.mark.asyncio
    async def test_multiple_bot_prs_processed(self, tmp_path: Path) -> None:
        """Multiple bot PRs are each processed independently."""
        loop, _, _, prs, state = _make_loop(
            tmp_path,
            open_prs=[_make_pr(1), _make_pr(2), _make_pr(3)],
            ci_result=(True, "All checks passed"),
        )

        result = await loop._do_work()

        assert result["merged"] == 3
        assert prs.merge_pr.await_count == 3

    @pytest.mark.asyncio
    async def test_author_matching_case_insensitive(self, tmp_path: Path) -> None:
        """Bot author matching is case-insensitive."""
        loop, _, _, prs, _ = _make_loop(
            tmp_path,
            open_prs=[_make_pr(1, author="Dependabot[bot]")],
            authors=["dependabot[bot]"],
            ci_result=(True, "All checks passed"),
        )

        result = await loop._do_work()

        assert result["merged"] == 1

    @pytest.mark.asyncio
    async def test_custom_bot_authors(self, tmp_path: Path) -> None:
        """Custom bot authors from settings are respected."""
        loop, _, _, prs, _ = _make_loop(
            tmp_path,
            open_prs=[
                _make_pr(1, author="renovate[bot]"),
                _make_pr(2, author="dependabot[bot]"),
            ],
            authors=["renovate[bot]"],
            ci_result=(True, "All checks passed"),
        )

        result = await loop._do_work()

        # Only renovate PR should match
        assert result["merged"] == 1
        prs.merge_pr.assert_awaited_once_with(1, auto_rebase=True)


class TestDependabotMergeLoopRun:
    @pytest.mark.asyncio
    async def test_run_publishes_worker_status_event(self, tmp_path: Path) -> None:
        """The loop publishes a BACKGROUND_WORKER_STATUS event on success."""
        loop, *_ = _make_loop(tmp_path)

        await loop.run()

        events = [
            e
            for e in loop._bus.get_history()
            if e.type == EventType.BACKGROUND_WORKER_STATUS
        ]
        assert len(events) >= 1
        data = events[0].data
        assert data["worker"] == "dependabot_merge"
        assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_run_skips_when_disabled(self, tmp_path: Path) -> None:
        """The loop skips work when the enabled callback returns False."""
        loop, *_ = _make_loop(tmp_path, enabled=False)

        await loop.run()

        loop._status_cb.assert_not_called()
