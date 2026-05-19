"""Unit tests for CostBudgetWatcherLoop (advisor-a03 coverage gap).

Closes the unit-test gap identified in the coverage-matrix audit.
The canonical name ``test_cost_budget_watcher_loop.py`` satisfies the
``_unit_check`` naming pattern used by the coverage-matrix generator.

Substantive behavioural tests live in ``test_cost_budget_watcher_scenario.py``
(filed before the naming convention was settled). This module adds a
lightweight smoke test that confirms the loop constructs successfully and
honours the ``daily_cost_budget_usd = None`` (unlimited) short-circuit —
the concrete signal that closes the matrix gap.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cost_budget_watcher_loop import CostBudgetWatcherLoop


def _make_loop(cap: float | None = None) -> CostBudgetWatcherLoop:
    config = MagicMock()
    config.daily_cost_budget_usd = cap
    config.cost_budget_watcher_loop_enabled = True
    state = MagicMock()
    state.get_cost_budget_killed_workers.return_value = set()
    pr_manager = AsyncMock()
    deps = MagicMock()
    loop = CostBudgetWatcherLoop(
        config=config,
        pr_manager=pr_manager,
        state=state,
        deps=deps,
    )
    bg = MagicMock()
    bg.is_enabled.return_value = True
    loop.set_bg_workers(bg)
    return loop


@pytest.mark.asyncio
async def test_unlimited_mode_returns_action_unlimited() -> None:
    """``daily_cost_budget_usd = None`` → action=unlimited, no I/O."""
    loop = _make_loop(cap=None)
    with patch("cost_budget_watcher_loop.build_rolling_24h") as mock_build:
        result = await loop._do_work()  # noqa: SLF001
    mock_build.assert_not_called()
    assert result == {"action": "unlimited"}


@pytest.mark.asyncio
async def test_under_cap_returns_ok() -> None:
    """Spend below cap → action=ok, nothing disabled."""
    loop = _make_loop(cap=50.0)
    with patch("cost_budget_watcher_loop.build_rolling_24h") as mock_build:
        mock_build.return_value = {"total": {"cost_usd": 20.0}}
        result = await loop._do_work()  # noqa: SLF001
    assert result["action"] == "ok"
    assert result["cap"] == 50.0
    assert result["total"] == 20.0
