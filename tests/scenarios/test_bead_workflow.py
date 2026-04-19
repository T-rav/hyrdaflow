"""End-to-end bead workflow scenarios using FakeBeads.

Prod-code bead lifecycle
------------------------
- **Plan phase** (`plan_phase.py:283`): if ``beads_manager`` is set and
  ``result.plan`` is non-empty, calls ``_create_beads_from_plan``.
  That method calls ``extract_phases(plan)`` from ``task_graph``; if phases
  are found it calls ``create_from_phases`` which creates one bead per phase
  and wires dependencies.  The ``{phase_id: bead_id}`` mapping is stored in
  state via ``set_bead_mapping``.
- **Implement phase** (`implement_phase.py:577-580`): reads the bead mapping
  from state.  If a mapping exists, calls ``beads_manager.init(wt_path)`` and
  passes ``bead_mapping`` to the agent runner.  ``claim``/``close`` are NOT
  called by prod code — those are executed by the real ``bd`` CLI subprocess
  inside the container.  ``FakeDocker`` does not emulate CLI bead calls, so
  tasks stay in their created state after the pipeline.
- **Review phase** (`review_phase.py:1082-1113`): reads the mapping from
  state and builds a ``bead_tasks`` context list (hardcoded ``status='closed'``
  — an assumption, not a real query).  No ``BeadsManager`` methods are called.

The plan text **must** contain phase headers matching the regex
``### P{N} — Name`` for ``extract_phases`` to return phases.  The default
``PlanResultFactory`` plan string does NOT contain these headers, so the plan
must be explicitly set.
"""

from __future__ import annotations

import pytest

from tests.conftest import PlanResultFactory
from tests.scenarios.fakes.fake_beads import FakeBeads
from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.git_worktree_fixture import init_test_worktree

pytestmark = pytest.mark.scenario

# ---------------------------------------------------------------------------
# A valid Task Graph plan — two phases with a dependency chain.
# extract_phases() requires "### P{N} — <name>" headers.
# ---------------------------------------------------------------------------
_TASK_GRAPH_PLAN = """\
## Plan

Add feature X in two phases.

## Task Graph

### P1 — Data model
**Files:** src/models.py
**Tests:**
- model fields are correct
**Depends on:** none

### P2 — API endpoint
**Files:** src/api.py
**Tests:**
- endpoint returns 200
**Depends on:** P1
"""


async def test_B1_bead_workflow_end_to_end(tmp_path) -> None:
    """Plan creates beads → implement init fires → bead mapping in state.

    Pipeline bead behaviour (matched to prod reality):

    1. FakeBeads is wired into MockWorld/PipelineHarness.
    2. Plan phase detects Task Graph phases in the plan text and calls
       ``create_from_phases`` → one bead per phase is stored in FakeBeads.
    3. Implement phase calls ``beads_manager.init`` (because a bead mapping
       now exists in state).
    4. ``claim``/``close`` are NOT called by prod code — those are agent
       subprocess concerns.  After the pipeline the tasks remain in their
       created state.
    5. Review phase reads the mapping from state but calls no FakeBeads
       methods, so bead state is unchanged.

    If any of the three invariants above break, the corresponding assertion
    fails with a diagnostic message pointing to the relevant prod-code site.
    """
    beads = FakeBeads()
    world = MockWorld(tmp_path, use_real_agent_runner=True, beads_manager=beads)
    world.add_issue(1, "add feature X", "body", labels=["hydraflow-ready"])

    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    init_test_worktree(worktree_cwd)

    # Provide a plan whose text contains Task Graph phase headers.
    plan = PlanResultFactory.create(
        issue_number=1,
        success=True,
        plan=_TASK_GRAPH_PLAN,
    )
    world._llm.script_plan(1, [plan])

    # Script the Docker fake so the agent runner sees a successful run with
    # at least one commit (required by AgentRunner._verify_result).
    world.docker.script_run_with_commits(
        events=[{"type": "result", "success": True, "exit_code": 0}],
        commits=[("x.py", "ok")],
        cwd=worktree_cwd,
    )

    result = await world.run_pipeline()

    # ------------------------------------------------------------------
    # Assertion 1: FakeBeads was initialised by the implement phase.
    # Triggered at implement_phase.py:580 when a bead mapping is in state.
    # If False, the plan phase may not have stored a mapping (check A2).
    # ------------------------------------------------------------------
    assert beads._initialized is True, (
        "FakeBeads.init was never called — implement phase only calls init "
        "when a bead mapping exists in state (implement_phase.py:577-580). "
        "This means plan phase did not produce a mapping (check A2 below)."
    )

    # ------------------------------------------------------------------
    # Assertion 2: Two beads were created (one per Task Graph phase).
    # Triggered by plan_phase._create_beads_from_plan via create_from_phases.
    # The plan text above has two P{N} headers → two phases → two beads.
    # ------------------------------------------------------------------
    assert beads.task_count() == 2, (
        f"Expected 2 bead tasks (one per plan phase), got {beads.task_count()}. "
        "plan_phase.py:411 calls create_from_phases only when extract_phases "
        "finds '### P{N} — Name' headers. Check the plan text format."
    )

    # ------------------------------------------------------------------
    # Assertion 3: Dependency wiring — P2 depends on P1.
    # FakeBeads.add_dependency records the edge; verify by inspecting the
    # internal _tasks dict.  P2 is the second bead created (bd-fake-2).
    # ------------------------------------------------------------------
    task_ids = beads.task_ids()
    assert len(task_ids) == 2  # matches A2
    p1_bead_id, p2_bead_id = task_ids[0], task_ids[1]
    p2_internal = beads._tasks[p2_bead_id]
    assert p1_bead_id in p2_internal.depends_on, (
        f"P2 bead ({p2_bead_id}) should depend on P1 bead ({p1_bead_id}). "
        f"Actual depends_on: {p2_internal.depends_on}"
    )

    # ------------------------------------------------------------------
    # Assertion 4: Tasks remain in 'open' state after the pipeline.
    # claim/close are NOT called by prod pipeline code — they are bd CLI
    # subprocess calls made inside the container, which FakeDocker does not
    # emulate.  If status is not 'open', the fake or prod code changed.
    # ------------------------------------------------------------------
    for tid, task in beads._tasks.items():
        assert task.status == "open", (
            f"Bead {tid} status is {task.status!r}; expected 'open' because "
            "prod code never calls BeadsManager.claim/close — those are agent "
            "subprocess calls (bd CLI inside container)."
        )

    # ------------------------------------------------------------------
    # Assertion 5: Pipeline completed (issue is tracked in result).
    # ------------------------------------------------------------------
    assert result.issue(1) is not None, "Pipeline returned no outcome for issue #1"


async def test_B1_no_beads_without_task_graph_headers(tmp_path) -> None:
    """Plan text without Task Graph headers → no beads created, no crash.

    Validates the guard at plan_phase.py:401 — if extract_phases returns []
    the method returns early; FakeBeads.create_from_phases is never called so
    task_count() stays at 0 and _initialized stays False.
    """
    beads = FakeBeads()
    world = MockWorld(tmp_path, use_real_agent_runner=True, beads_manager=beads)
    world.add_issue(2, "plain task", "body", labels=["hydraflow-ready"])

    worktree_cwd = tmp_path / "worktrees" / "issue-2"
    init_test_worktree(worktree_cwd)

    # Default plan text — no "### P{N} — ..." headers → extract_phases → []
    plain_plan = PlanResultFactory.create(
        issue_number=2,
        success=True,
        plan="## Plan\n\n1. Do the thing\n2. Test the thing",
    )
    world._llm.script_plan(2, [plain_plan])

    world.docker.script_run_with_commits(
        events=[{"type": "result", "success": True, "exit_code": 0}],
        commits=[("y.py", "ok")],
        cwd=worktree_cwd,
    )

    result = await world.run_pipeline()

    # No phases → no beads → no init
    assert beads.task_count() == 0, (
        "Expected 0 beads when plan text has no Task Graph headers. "
        f"Got {beads.task_count()} — check plan_phase._create_beads_from_plan."
    )
    assert beads._initialized is False, (
        "FakeBeads.init should not be called when no bead mapping was stored. "
        "implement_phase.py:577 gates init on get_bead_mapping returning truthy."
    )
    assert result.issue(2) is not None, "Pipeline returned no outcome for issue #2"
