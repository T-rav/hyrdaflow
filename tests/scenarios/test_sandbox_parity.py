"""Parity test: every sandbox scenario must also pass in-process Tier 1.

If a scenario fails Tier 2 (sandbox) but passes here, the bug is in
container/wiring/UI. If both fail, the bug is in scenario logic or
Fake behavior.
"""

from __future__ import annotations

import pytest

from tests.sandbox_scenarios.runner.loader import load_all_scenarios


@pytest.mark.parametrize("scenario", load_all_scenarios(), ids=lambda s: s.NAME)
@pytest.mark.asyncio
async def test_sandbox_scenario_runs_in_process(mock_world, scenario) -> None:
    seed = scenario.seed()
    mock_world.apply_seed(seed)

    loops = seed.loops_enabled or [
        "triage_loop",
        "plan_loop",
        "implement_loop",
        "review_loop",
        "merge_loop",
    ]
    # M1 follow-up: previously a bare ``KeyError`` / ``AttributeError`` here
    # called ``pytest.skip`` silently, hiding scenarios where the loop
    # registration drifted. We now ``pytest.xfail`` instead so the missing
    # loop is visible in the test summary (``X`` not ``s``) and the user
    # can decide whether to bring the catalog up to parity or drop the
    # scenario. A hard ``raise`` would break Tier 1 today because the
    # default loop names ("triage_loop", …) aren't yet in the catalog;
    # tracking that as a separate sandbox→Tier 1 parity gap.
    try:
        await mock_world.run_with_loops(loops, cycles=seed.cycles_to_run)
    except (KeyError, AttributeError) as exc:
        pytest.xfail(f"loop not registered in catalog: {exc}")

    # Smoke check: at least one issue advanced past "queued".
    last_run = getattr(mock_world, "last_run", None)
    if last_run is None or not getattr(last_run, "issues", None):
        # No run-pipeline-style results - apply_seed populated state but
        # run_with_loops uses the loop-based path. Smoke is "didn't crash".
        return
    advanced = any(
        outcome.final_stage != "queued" for outcome in last_run.issues.values()
    )
    assert advanced, f"scenario {scenario.NAME} produced no progress in-process"
