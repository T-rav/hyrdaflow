"""Sandbox-e2e scenario for MergeStateWatcherLoop (advisor-rxi).

Two minimal ticks (Pattern B — direct instantiation):

* ``test_conflicting_pr_gets_rebased`` — one conflicting PR with no
  skip-labels; ``update_pr_branch`` succeeds and the loop returns
  ``checked=1, rebased=1``.
* ``test_no_conflicting_prs_returns_zero_counts`` — empty conflict list;
  all counters zero.

Pattern B is required because ``run_with_loops`` always forces
``ports["github"] = world._github`` (FakeGitHub), which does not implement
``list_conflicting_prs``.  Direct instantiation avoids that override.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps
from events import EventBus
from merge_state_watcher import ConflictingPR
from merge_state_watcher_loop import MergeStateWatcherLoop
from tests.helpers import ConfigFactory

pytestmark = pytest.mark.scenario_loops


def _make_loop(tmp_path, fake_prs):
    """Instantiate MergeStateWatcherLoop with a controlled fake PRPort."""
    config = ConfigFactory.create(repo_root=tmp_path / "repo")
    bus = EventBus()
    stop_event = asyncio.Event()
    stop_event.set()
    deps = LoopDeps(
        event_bus=bus,
        stop_event=stop_event,
        status_cb=MagicMock(),
        enabled_cb=lambda _: True,
        sleep_fn=AsyncMock(),
    )
    return MergeStateWatcherLoop(config=config, prs=fake_prs, deps=deps)


class TestMergeStateWatcherScenario:
    """advisor-rxi — sandbox-e2e for MergeStateWatcherLoop."""

    async def test_conflicting_pr_gets_rebased(self, tmp_path) -> None:
        """One conflicting PR with no skip-labels -> update_pr_branch called, rebased=1."""
        fake_prs = MagicMock()
        fake_prs.list_conflicting_prs = AsyncMock(
            return_value=[ConflictingPR(number=77, branch="feat/thing", labels=[])]
        )
        fake_prs.update_pr_branch = AsyncMock(return_value=True)
        # After update_pr_branch succeeds, the loop checks mergeability.
        # Returning True means the conflict is resolved -> "rebased" path taken.
        fake_prs.get_pr_mergeable = AsyncMock(return_value=True)
        fake_prs.add_pr_labels = AsyncMock(return_value=None)

        loop = _make_loop(tmp_path, fake_prs)
        result = await loop._do_work()

        assert result is not None, result
        assert result["checked"] == 1
        assert result["rebased"] == 1
        assert result["escalated"] == 0
        fake_prs.update_pr_branch.assert_awaited_once_with(77)

    async def test_no_conflicting_prs_returns_zero_counts(self, tmp_path) -> None:
        """No conflicting PRs -> all counters zero, update_pr_branch not called."""
        fake_prs = MagicMock()
        fake_prs.list_conflicting_prs = AsyncMock(return_value=[])
        fake_prs.update_pr_branch = AsyncMock(return_value=True)

        loop = _make_loop(tmp_path, fake_prs)
        result = await loop._do_work()

        assert result is not None, result
        assert result["checked"] == 0
        assert result["rebased"] == 0
        fake_prs.update_pr_branch.assert_not_awaited()
