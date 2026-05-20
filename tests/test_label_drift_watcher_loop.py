"""Tests for LabelDriftWatcherLoop (ADR-0056).

The loop runs ``find_label_drift`` per tick and reconciles each pair via
two ``swap_pipeline_labels`` calls. We mock the PRPort directly to test
the loop's reconciliation logic in isolation; ``find_label_drift``
itself has separate coverage in ``tests/test_pr_manager_drift.py``.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from label_drift_watcher_loop import LabelDriftWatcherLoop
from models import LabelDrift


def _deps(stop: asyncio.Event) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: True,
    )


@pytest.fixture
def loop_env(tmp_path: Path):
    cfg = HydraFlowConfig(
        data_root=tmp_path, repo="hydra/hydraflow", repo_root=tmp_path
    )
    pr = AsyncMock()
    pr.find_label_drift = AsyncMock(return_value=[])
    pr.swap_pipeline_labels = AsyncMock(return_value=None)
    pr.post_comment = AsyncMock(return_value=None)
    return cfg, pr


def test_worker_name_and_default_interval(loop_env) -> None:
    cfg, pr = loop_env
    stop = asyncio.Event()
    loop = LabelDriftWatcherLoop(config=cfg, pr_manager=pr, deps=_deps(stop))
    assert loop._worker_name == "label_drift_watcher"
    assert loop._get_default_interval() == cfg.label_drift_watcher_interval


@pytest.mark.asyncio
async def test_no_drift_no_op(loop_env) -> None:
    """Empty drift list → loop returns zero stats and does not swap labels."""
    cfg, pr = loop_env
    stop = asyncio.Event()
    loop = LabelDriftWatcherLoop(config=cfg, pr_manager=pr, deps=_deps(stop))

    stats = await loop._do_work()

    assert stats == {"detected": 0, "reconciled": 0}
    pr.swap_pipeline_labels.assert_not_awaited()
    pr.post_comment.assert_not_awaited()


@pytest.mark.asyncio
async def test_detects_and_reconciles_pr_ahead_of_issue(loop_env) -> None:
    """``pr_ahead_of_issue`` drift → swap issue to review + post comment."""
    cfg, pr = loop_env
    drift = LabelDrift(
        issue=42,
        pr=100,
        pr_commits=2,
        issue_label="hydraflow-ready",
        pr_label="hydraflow-review",
        kind="pr_ahead_of_issue",
        detected_at=datetime.now(UTC),
    )
    pr.find_label_drift = AsyncMock(return_value=[drift])

    stop = asyncio.Event()
    loop = LabelDriftWatcherLoop(config=cfg, pr_manager=pr, deps=_deps(stop))

    stats = await loop._do_work()

    assert stats == {"detected": 1, "reconciled": 1}
    pr.swap_pipeline_labels.assert_awaited_once_with(42, "hydraflow-review")
    pr.post_comment.assert_awaited_once()
    body = pr.post_comment.await_args.args[1]
    assert "LabelDriftWatcher" in body
    assert "pr_ahead_of_issue" in body


@pytest.mark.asyncio
async def test_reconciles_pr_at_pre_pr_stage(loop_env) -> None:
    """``pr_at_pre_pr_stage`` drift → swap PR (not issue) to review."""
    cfg, pr = loop_env
    drift = LabelDrift(
        issue=99,
        pr=200,
        pr_commits=3,
        issue_label="hydraflow-review",
        pr_label="hydraflow-ready",
        kind="pr_at_pre_pr_stage",
        detected_at=datetime.now(UTC),
    )
    pr.find_label_drift = AsyncMock(return_value=[drift])

    stop = asyncio.Event()
    loop = LabelDriftWatcherLoop(config=cfg, pr_manager=pr, deps=_deps(stop))

    stats = await loop._do_work()

    assert stats == {"detected": 1, "reconciled": 1}
    pr.swap_pipeline_labels.assert_awaited_once_with(200, "hydraflow-review")


@pytest.mark.asyncio
async def test_idempotent_on_second_run(loop_env) -> None:
    """First run reconciles; second run with empty drift is a no-op."""
    cfg, pr = loop_env
    drift = LabelDrift(
        issue=42,
        pr=100,
        pr_commits=2,
        issue_label="hydraflow-ready",
        pr_label="hydraflow-review",
        kind="pr_ahead_of_issue",
        detected_at=datetime.now(UTC),
    )
    pr.find_label_drift = AsyncMock(side_effect=[[drift], []])

    stop = asyncio.Event()
    loop = LabelDriftWatcherLoop(config=cfg, pr_manager=pr, deps=_deps(stop))

    first = await loop._do_work()
    second = await loop._do_work()

    assert first == {"detected": 1, "reconciled": 1}
    assert second == {"detected": 0, "reconciled": 0}
    assert pr.swap_pipeline_labels.await_count == 1


@pytest.mark.asyncio
async def test_reconcile_failure_counted_separately(loop_env) -> None:
    """Per-pair reconcile error → detected counts but reconciled does not."""
    cfg, pr = loop_env
    drift = LabelDrift(
        issue=42,
        pr=100,
        pr_commits=2,
        issue_label="hydraflow-ready",
        pr_label="hydraflow-review",
        kind="pr_ahead_of_issue",
        detected_at=datetime.now(UTC),
    )
    pr.find_label_drift = AsyncMock(return_value=[drift])
    pr.swap_pipeline_labels = AsyncMock(side_effect=RuntimeError("api fail"))

    stop = asyncio.Event()
    loop = LabelDriftWatcherLoop(config=cfg, pr_manager=pr, deps=_deps(stop))

    stats = await loop._do_work()

    assert stats == {"detected": 1, "reconciled": 0}


@pytest.mark.asyncio
async def test_disabled_returns_status(loop_env) -> None:
    """Kill-switch off → loop returns ``{"status": "disabled"}`` without scanning."""
    cfg, pr = loop_env
    deps = LoopDeps(
        event_bus=EventBus(),
        stop_event=asyncio.Event(),
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: False,
    )
    loop = LabelDriftWatcherLoop(config=cfg, pr_manager=pr, deps=deps)

    stats = await loop._do_work()

    assert stats == {"status": "disabled"}
    pr.find_label_drift.assert_not_awaited()


@pytest.mark.asyncio
async def test_pr_ahead_of_issue_comment_describes_issue_move(loop_env) -> None:
    """For ``pr_ahead_of_issue`` the issue is the entity that moved — the
    comment must describe only the issue relabel, not claim both ends moved.
    See #8727."""
    cfg, pr = loop_env
    drift = LabelDrift(
        issue=42,
        pr=100,
        pr_commits=2,
        issue_label="hydraflow-ready",
        pr_label="hydraflow-review",
        kind="pr_ahead_of_issue",
        detected_at=datetime.now(UTC),
    )
    pr.find_label_drift = AsyncMock(return_value=[drift])
    stop = asyncio.Event()
    loop = LabelDriftWatcherLoop(config=cfg, pr_manager=pr, deps=_deps(stop))

    await loop._do_work()

    body = pr.post_comment.await_args.args[1]
    # The PR stayed at hydraflow-review; only the issue moved.
    assert "Both should now be aligned" not in body, (
        "Misleading: PR did not move for pr_ahead_of_issue"
    )
    assert "issue" in body.lower()


@pytest.mark.asyncio
async def test_pr_at_pre_pr_stage_comment_describes_pr_move(loop_env) -> None:
    """For ``pr_at_pre_pr_stage`` the PR is the entity that moved — the
    comment must say so. See #8727."""
    cfg, pr = loop_env
    drift = LabelDrift(
        issue=99,
        pr=200,
        pr_commits=3,
        issue_label="hydraflow-review",
        pr_label="hydraflow-ready",
        kind="pr_at_pre_pr_stage",
        detected_at=datetime.now(UTC),
    )
    pr.find_label_drift = AsyncMock(return_value=[drift])
    stop = asyncio.Event()
    loop = LabelDriftWatcherLoop(config=cfg, pr_manager=pr, deps=_deps(stop))

    await loop._do_work()

    body = pr.post_comment.await_args.args[1]
    assert "PR" in body
    assert "hydraflow-review" in body


def test_label_drift_kind_rejects_pr_behind_issue() -> None:
    """``LabelDrift.kind`` Literal must no longer accept ``pr_behind_issue``
    — the value was unreachable (no producer in find_label_drift). See #8726."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        LabelDrift(
            issue=1,
            pr=2,
            pr_commits=1,
            issue_label="hydraflow-review",
            pr_label="hydraflow-ready",
            kind="pr_behind_issue",  # type: ignore[arg-type]
            detected_at=datetime.now(UTC),
        )
