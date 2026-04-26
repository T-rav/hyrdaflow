"""Unit tests for src/diagram_loop.py:DiagramLoop.

ADR-0029 (caretaker pattern) and ADR-0049 (kill-switch convention).
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps
from diagram_loop import DiagramLoop


@pytest.fixture
def loop_deps() -> LoopDeps:
    return LoopDeps(
        event_bus=MagicMock(),
        stop_event=asyncio.Event(),
        status_cb=MagicMock(),
        enabled_cb=MagicMock(return_value=True),
        sleep_fn=AsyncMock(),
        interval_cb=MagicMock(return_value=14400),
    )


def test_constructor_sets_worker_name(loop_deps):
    config = MagicMock()
    pr_manager = MagicMock()
    loop = DiagramLoop(config=config, pr_manager=pr_manager, deps=loop_deps)
    assert loop._worker_name == "diagram-loop"


def test_default_interval_is_four_hours(loop_deps):
    loop = DiagramLoop(config=MagicMock(), pr_manager=MagicMock(), deps=loop_deps)
    assert loop._get_default_interval() == 14400


@pytest.mark.asyncio
async def test_no_drift_returns_drift_false(loop_deps, tmp_path, monkeypatch):
    pr_manager = MagicMock()
    pr_manager.find_existing_issue = AsyncMock(return_value=0)
    pr_manager.create_issue = AsyncMock(return_value=42)
    loop = DiagramLoop(config=MagicMock(), pr_manager=pr_manager, deps=loop_deps)
    loop._set_repo_root(tmp_path)

    from diagram_loop import _DriftResult

    monkeypatch.setattr(
        loop,
        "_regen_and_detect_drift",
        lambda: _DriftResult(has_drift=False, changed_files=[]),
    )
    result = await loop._do_work()
    assert result == {"drift": False}


@pytest.mark.asyncio
async def test_drift_opens_pr_and_runs_coverage(loop_deps, tmp_path, monkeypatch):
    pr_manager = MagicMock()
    pr_manager.find_existing_issue = AsyncMock(return_value=0)
    loop = DiagramLoop(config=MagicMock(), pr_manager=pr_manager, deps=loop_deps)
    loop._set_repo_root(tmp_path)

    from diagram_loop import _DriftResult

    monkeypatch.setattr(
        loop,
        "_regen_and_detect_drift",
        lambda: _DriftResult(
            has_drift=True, changed_files=["M docs/arch/generated/loops.md"]
        ),
    )

    open_pr_mock = AsyncMock(return_value="https://pr/1")
    monkeypatch.setattr(loop, "_open_or_update_regen_pr", open_pr_mock)
    coverage_mock = AsyncMock()
    monkeypatch.setattr(loop, "_ensure_coverage_issue", coverage_mock)

    result = await loop._do_work()
    assert result["drift"] is True
    assert result["pr_url"] == "https://pr/1"
    open_pr_mock.assert_awaited_once()
    coverage_mock.assert_awaited_once()
