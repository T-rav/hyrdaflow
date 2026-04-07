"""Tests that ImplementPhase allocates run_id, sets context, and rolls up."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest  # noqa: E402

from tests.conftest import TaskFactory, WorkerResultFactory  # noqa: E402
from tests.helpers import make_implement_phase  # noqa: E402


@pytest.mark.asyncio
async def test_implement_phase_allocates_and_ends_run(config, tmp_path):
    """After a phase run, begin_trace_run was called and end_trace_run was called."""
    issue = TaskFactory.create(id=42)

    async def fake_agent_run(issue, wt_path, branch, **kwargs):
        return WorkerResultFactory.create(
            issue_number=issue.id, success=True, workspace_path=str(wt_path)
        )

    phase, _, _ = make_implement_phase(config, [issue], agent_run=fake_agent_run)

    await phase.run_batch()

    # end_trace_run was called: next begin gets run_id 2 (one run consumed)
    assert phase._state.begin_trace_run(42, "implement") == 2


@pytest.mark.asyncio
async def test_implement_phase_rolls_up_on_agent_failure(config, tmp_path):
    """Even when the agent raises, end_trace_run is called."""
    issue = TaskFactory.create(id=99)

    async def failing_agent(issue, wt_path, branch, **kwargs):
        raise RuntimeError("boom")

    phase, _, _ = make_implement_phase(config, [issue], agent_run=failing_agent)

    await phase.run_batch()

    # end_trace_run fired in finally block: next begin gets run_id 2
    assert phase._state.begin_trace_run(99, "implement") == 2
