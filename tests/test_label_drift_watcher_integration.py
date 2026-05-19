"""End-to-end integration: LabelDriftWatcherLoop against FakeGitHub.

Wires the loop to the in-memory ``FakeGitHub`` (which implements ``PRPort``
including ``find_label_drift`` and ``swap_pipeline_labels``) and verifies
a single tick detects+reconciles ``pr_ahead_of_issue`` drift in the
seeded world.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from label_drift_watcher_loop import LabelDriftWatcherLoop
from mockworld.fakes import FakeGitHub


def _deps(stop: asyncio.Event) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *_a, **_k: None,
        enabled_cb=lambda _name: True,
    )


@pytest.mark.asyncio
async def test_loop_reconciles_pr_ahead_of_issue_against_fake(tmp_path: Path) -> None:
    """Seed FakeGitHub with drift; one tick reconciles it; second tick is no-op."""
    cfg = HydraFlowConfig(data_root=tmp_path, repo="owner/repo", repo_root=tmp_path)

    gh = FakeGitHub()
    # Issue stuck at hydraflow-ready while linked PR has commits and is
    # at hydraflow-review — classic pr_ahead_of_issue drift.
    gh.add_issue(42, "feature work", "body", labels=["hydraflow-ready"])
    gh.add_pr(number=100, issue_number=42, branch="hf/issue-42")
    gh.add_pr_label(100, "hydraflow-review")

    loop = LabelDriftWatcherLoop(config=cfg, pr_manager=gh, deps=_deps(asyncio.Event()))

    first = await loop._do_work()
    assert first == {"detected": 1, "reconciled": 1}
    # Issue label pulled forward to hydraflow-review (PR's stage).
    assert "hydraflow-review" in gh._issues[42].labels
    assert "hydraflow-ready" not in gh._issues[42].labels

    second = await loop._do_work()
    assert second == {"detected": 0, "reconciled": 0}, (
        "second tick must be a no-op once drift is reconciled"
    )


@pytest.mark.asyncio
async def test_loop_no_op_on_clean_world(tmp_path: Path) -> None:
    """Aligned issue/PR labels → no drift, no swap, no comment."""
    cfg = HydraFlowConfig(data_root=tmp_path, repo="owner/repo", repo_root=tmp_path)

    gh = FakeGitHub()
    gh.add_issue(7, "aligned", "body", labels=["hydraflow-review"])
    gh.add_pr(number=70, issue_number=7, branch="hf/issue-7")
    gh.add_pr_label(70, "hydraflow-review")

    loop = LabelDriftWatcherLoop(config=cfg, pr_manager=gh, deps=_deps(asyncio.Event()))

    stats = await loop._do_work()

    assert stats == {"detected": 0, "reconciled": 0}
    # No comments posted — quiet on clean worlds.
    assert gh._comments == []
