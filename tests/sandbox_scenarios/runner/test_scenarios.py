"""Parametrized sandbox-scenario runner.

The scenario harness CLI invokes this with -k or specific test ID; each
scenario module's assert_outcome is called with (api, page) fixtures.
"""

from __future__ import annotations

import os

import pytest

from tests.sandbox_scenarios.runner.loader import load_all_scenarios

# Filter out s00_smoke — that's parity-only (no assert_outcome).
_SCENARIOS = [s for s in load_all_scenarios() if hasattr(s, "assert_outcome")]


if _SCENARIOS:

    @pytest.mark.parametrize("scenario", _SCENARIOS, ids=lambda s: s.NAME)
    @pytest.mark.asyncio
    async def test_scenario(scenario, api, page) -> None:
        """Run scenario.assert_outcome with the API client + Playwright page."""
        # Optional env override: SCENARIO_NAME=sNN runs only that scenario.
        only = os.environ.get("SCENARIO_NAME")
        if only and only != scenario.NAME:
            pytest.skip(f"SCENARIO_NAME={only!r} doesn't match {scenario.NAME}")
        await scenario.assert_outcome(api, page)

else:

    @pytest.mark.skip(
        reason="No Tier-2 scenarios with assert_outcome yet (s01 lands in Task 2.5)"
    )
    def test_scenario_placeholder() -> None:
        """Placeholder while no scenarios define assert_outcome."""
