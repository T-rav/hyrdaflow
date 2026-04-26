"""ADR-0049 — kill-switch convention for DiagramLoop."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

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


@pytest.mark.asyncio
async def test_kill_switch_skips_work(loop_deps, monkeypatch):
    pr_manager = MagicMock()
    pr_manager.create_pr = AsyncMock()
    loop = DiagramLoop(config=MagicMock(), pr_manager=pr_manager, deps=loop_deps)

    monkeypatch.setenv("HYDRAFLOW_DISABLE_DIAGRAM_LOOP", "1")
    with patch("arch.runner.emit") as mock_emit:
        result = await loop._do_work()
    assert result == {"skipped": "kill_switch"}
    mock_emit.assert_not_called()
    pr_manager.create_pr.assert_not_awaited()


@pytest.mark.asyncio
async def test_kill_switch_unset_runs_normally(loop_deps, monkeypatch):
    pr_manager = MagicMock()
    pr_manager.find_existing_issue = AsyncMock(return_value=0)
    loop = DiagramLoop(config=MagicMock(), pr_manager=pr_manager, deps=loop_deps)

    monkeypatch.delenv("HYDRAFLOW_DISABLE_DIAGRAM_LOOP", raising=False)
    from diagram_loop import _DriftResult

    monkeypatch.setattr(
        loop,
        "_regen_and_detect_drift",
        lambda: _DriftResult(has_drift=False, changed_files=[]),
    )
    result = await loop._do_work()
    assert result.get("drift") is False
