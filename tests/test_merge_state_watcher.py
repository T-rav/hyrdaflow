"""Tests for MergeStateWatcher — auto-rebase / HITL-escalate conflicting PRs.

Closes the gap where PRs with ``mergeable=CONFLICTING`` (e.g. RC promotion
PRs cut by ``StagingPromotionLoop``, dependabot bumps, agent PRs that fell
behind ``main``) sat indefinitely because ``PRUnsticker`` only acted on PRs
already labeled ``hydraflow-hitl``. This watcher is the missing front door.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from merge_state_watcher import ConflictingPR, MergeStateWatcher


def _pr(
    number: int,
    *,
    labels: tuple[str, ...] = (),
    branch: str = "feat/foo",
) -> ConflictingPR:
    return ConflictingPR(
        number=number,
        branch=branch,
        labels=list(labels),
    )


@pytest.fixture
def fake_pr_port():
    pr = AsyncMock()
    pr.list_conflicting_prs = AsyncMock(return_value=[])
    pr.update_pr_branch = AsyncMock(return_value=True)
    pr.add_pr_labels = AsyncMock()
    pr.get_pr_mergeable = AsyncMock(return_value=True)
    return pr


async def test_no_conflicting_prs_returns_empty_stats(fake_pr_port) -> None:
    watcher = MergeStateWatcher(prs=fake_pr_port, hitl_label="hydraflow-hitl")
    stats = await watcher.unstick_conflicts()
    assert stats == {"checked": 0, "rebased": 0, "escalated": 0, "skipped": 0}
    fake_pr_port.update_pr_branch.assert_not_awaited()
    fake_pr_port.add_pr_labels.assert_not_awaited()


async def test_rebases_pr_with_no_relevant_labels(fake_pr_port) -> None:
    fake_pr_port.list_conflicting_prs.return_value = [_pr(8491, branch="rc/foo")]
    fake_pr_port.update_pr_branch.return_value = True
    fake_pr_port.get_pr_mergeable.return_value = True

    watcher = MergeStateWatcher(prs=fake_pr_port, hitl_label="hydraflow-hitl")
    stats = await watcher.unstick_conflicts()

    fake_pr_port.update_pr_branch.assert_awaited_once_with(8491)
    fake_pr_port.add_pr_labels.assert_not_awaited()
    assert stats == {"checked": 1, "rebased": 1, "escalated": 0, "skipped": 0}


async def test_skips_pr_already_labeled_hitl(fake_pr_port) -> None:
    """PRUnsticker is on it — don't double-act."""
    fake_pr_port.list_conflicting_prs.return_value = [
        _pr(8478, labels=("hydraflow-hitl",))
    ]

    watcher = MergeStateWatcher(prs=fake_pr_port, hitl_label="hydraflow-hitl")
    stats = await watcher.unstick_conflicts()

    fake_pr_port.update_pr_branch.assert_not_awaited()
    fake_pr_port.add_pr_labels.assert_not_awaited()
    assert stats == {"checked": 1, "rebased": 0, "escalated": 0, "skipped": 1}


async def test_skips_pr_in_active_review(fake_pr_port) -> None:
    """A reviewer's worktree might be in flight — leave it alone for one tick."""
    fake_pr_port.list_conflicting_prs.return_value = [
        _pr(8500, labels=("hydraflow-review",))
    ]

    watcher = MergeStateWatcher(prs=fake_pr_port, hitl_label="hydraflow-hitl")
    stats = await watcher.unstick_conflicts()

    fake_pr_port.update_pr_branch.assert_not_awaited()
    assert stats == {"checked": 1, "rebased": 0, "escalated": 0, "skipped": 1}


async def test_escalates_pr_when_rebase_does_not_resolve(fake_pr_port) -> None:
    """Real conflict — rebase didn't help. Hand to PRUnsticker via HITL label."""
    fake_pr_port.list_conflicting_prs.return_value = [_pr(8654)]
    fake_pr_port.update_pr_branch.return_value = False
    fake_pr_port.get_pr_mergeable.return_value = False

    watcher = MergeStateWatcher(prs=fake_pr_port, hitl_label="hydraflow-hitl")
    stats = await watcher.unstick_conflicts()

    fake_pr_port.update_pr_branch.assert_awaited_once_with(8654)
    fake_pr_port.add_pr_labels.assert_awaited_once_with(8654, ["hydraflow-hitl"])
    assert stats == {"checked": 1, "rebased": 0, "escalated": 1, "skipped": 0}


async def test_escalates_when_rebase_succeeds_but_pr_still_conflicting(
    fake_pr_port,
) -> None:
    """``gh pr update-branch`` returned 0 but mergeable still false — escalate."""
    fake_pr_port.list_conflicting_prs.return_value = [_pr(8478)]
    fake_pr_port.update_pr_branch.return_value = True
    fake_pr_port.get_pr_mergeable.return_value = False

    watcher = MergeStateWatcher(prs=fake_pr_port, hitl_label="hydraflow-hitl")
    stats = await watcher.unstick_conflicts()

    fake_pr_port.add_pr_labels.assert_awaited_once_with(8478, ["hydraflow-hitl"])
    assert stats["escalated"] == 1


async def test_handles_three_prs_with_mixed_outcomes(fake_pr_port) -> None:
    fake_pr_port.list_conflicting_prs.return_value = [
        _pr(1, branch="rc/foo"),
        _pr(2, labels=("hydraflow-hitl",)),
        _pr(3, branch="feat/bar"),
    ]

    async def update_pr_branch(n: int) -> bool:
        # PR 1 rebases cleanly, PR 3 fails to rebase
        return n == 1

    async def get_pr_mergeable(n: int) -> bool | None:
        return n == 1

    fake_pr_port.update_pr_branch.side_effect = update_pr_branch
    fake_pr_port.get_pr_mergeable.side_effect = get_pr_mergeable

    watcher = MergeStateWatcher(prs=fake_pr_port, hitl_label="hydraflow-hitl")
    stats = await watcher.unstick_conflicts()

    assert stats == {"checked": 3, "rebased": 1, "escalated": 1, "skipped": 1}
    # PR 1 rebased, PR 2 skipped, PR 3 escalated
    fake_pr_port.add_pr_labels.assert_awaited_once_with(3, ["hydraflow-hitl"])


async def test_continues_after_one_pr_raises(fake_pr_port) -> None:
    """A failure on one PR doesn't sink the rest of the cycle."""
    fake_pr_port.list_conflicting_prs.return_value = [_pr(1), _pr(2)]

    async def update_pr_branch(n: int) -> bool:
        if n == 1:
            raise RuntimeError("gh blew up")
        return True

    fake_pr_port.update_pr_branch.side_effect = update_pr_branch
    fake_pr_port.get_pr_mergeable.return_value = True

    watcher = MergeStateWatcher(prs=fake_pr_port, hitl_label="hydraflow-hitl")
    stats = await watcher.unstick_conflicts()

    assert stats["checked"] == 2
    assert stats["rebased"] == 1


# --- Loop wiring -------------------------------------------------------------


async def test_loop_returns_disabled_when_kill_switch_off() -> None:
    from base_background_loop import LoopDeps  # noqa: PLC0415
    from config import HydraFlowConfig  # noqa: PLC0415
    from events import EventBus  # noqa: PLC0415
    from merge_state_watcher_loop import MergeStateWatcherLoop  # noqa: PLC0415

    cfg = HydraFlowConfig(repo="acme/widgets")
    stop = asyncio.Event()
    deps = LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda name: name != "merge_state_watcher",
    )
    pr = AsyncMock()
    pr.list_conflicting_prs = AsyncMock(return_value=[])
    pr.update_pr_branch = AsyncMock()
    pr.add_pr_labels = AsyncMock()
    pr.get_pr_mergeable = AsyncMock()

    loop = MergeStateWatcherLoop(config=cfg, prs=pr, deps=deps)
    stats = await loop._do_work()
    assert stats == {"status": "disabled"}
    pr.list_conflicting_prs.assert_not_awaited()


async def test_loop_default_interval_is_ten_minutes() -> None:
    from base_background_loop import LoopDeps  # noqa: PLC0415
    from config import HydraFlowConfig  # noqa: PLC0415
    from events import EventBus  # noqa: PLC0415
    from merge_state_watcher_loop import MergeStateWatcherLoop  # noqa: PLC0415

    cfg = HydraFlowConfig(repo="acme/widgets")
    stop = asyncio.Event()
    deps = LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: True,
    )
    pr = AsyncMock()
    loop = MergeStateWatcherLoop(config=cfg, prs=pr, deps=deps)
    assert loop._worker_name == "merge_state_watcher"
    assert loop._get_default_interval() == 600


async def test_loop_delegates_to_watcher() -> None:
    from base_background_loop import LoopDeps  # noqa: PLC0415
    from config import HydraFlowConfig  # noqa: PLC0415
    from events import EventBus  # noqa: PLC0415
    from merge_state_watcher_loop import MergeStateWatcherLoop  # noqa: PLC0415

    cfg = HydraFlowConfig(repo="acme/widgets")
    stop = asyncio.Event()
    deps = LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: True,
    )
    pr = AsyncMock()
    pr.list_conflicting_prs = AsyncMock(return_value=[_pr(7, branch="feat/x")])
    pr.update_pr_branch = AsyncMock(return_value=True)
    pr.get_pr_mergeable = AsyncMock(return_value=True)
    pr.add_pr_labels = AsyncMock()

    loop = MergeStateWatcherLoop(config=cfg, prs=pr, deps=deps)
    stats = await loop._do_work()
    assert stats["checked"] == 1
    assert stats["rebased"] == 1
