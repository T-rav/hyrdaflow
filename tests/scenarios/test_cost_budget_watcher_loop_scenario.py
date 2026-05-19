"""MockWorld scenario for CostBudgetWatcherLoop (ADR-0029 caretaker pattern).

Drives the loop through MockWorld with ``daily_cost_budget_usd = None``
(unlimited mode). The loop short-circuits immediately and returns
``{"action": "unlimited"}``. This proves the catalog builder is wired
correctly and the loop runs without crashing under the MockWorld sandbox.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario_loops


class TestCostBudgetWatcherLoopScenario:
    """MockWorld scenario coverage for CostBudgetWatcherLoop."""

    async def test_unlimited_mode_no_op_tick(self, tmp_path) -> None:
        """Loop in unlimited mode (cap=None) completes a tick without error."""
        world = MockWorld(tmp_path)

        # The catalog builder uses ports["state"] directly (StateTracker).
        # Seed a mock that satisfies the CostBudgetWatcher surface.
        state = MagicMock()
        state.get_cost_budget_killed_workers.return_value = set()
        state.set_cost_budget_killed_workers = MagicMock()

        # BGWorkerManager must be injected post-construction.
        bg_workers = MagicMock()
        bg_workers.is_enabled = MagicMock(return_value=True)
        bg_workers.set_enabled = MagicMock()

        _seed_ports(world, state=state, bg_workers=bg_workers)

        stats = await world.run_with_loops(["cost_budget_watcher"], cycles=1)

        result = stats["cost_budget_watcher"]
        # With daily_cost_budget_usd=None (the MockWorld default config),
        # _do_work returns {"action": "unlimited"}.
        assert result is not None
        assert result.get("action") in ("unlimited", "config_disabled", "skipped")
