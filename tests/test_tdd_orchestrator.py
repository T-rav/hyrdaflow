"""Tests for tdd_orchestrator.py — per-phase TDD isolation."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from models import Task, TDDPhaseResult, WorkerResult
from task_graph import TaskGraphPhase
from tdd_orchestrator import TDDOrchestrator, topological_sort
from tests.helpers import ConfigFactory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TASK_GRAPH_PLAN = """\
## Task Graph

### P1 — Data Model
**Files:** `src/models.py`
**Tests:**
- Task model validates fields
**Depends on:** None

### P2 — API Layer
**Files:** `src/api.py`
**Tests:**
- GET /tasks returns list
**Depends on:** P1
"""

NO_TASK_GRAPH_PLAN = "## Implementation Steps\n\n1. Do the thing\n"


def _make_orchestrator(config=None, *, tdd_enabled=True, max_loops=4):
    if config is None:
        config = ConfigFactory.create()
    config.tdd_isolation_enabled = tdd_enabled
    config.tdd_max_remediation_loops = max_loops
    agents = AsyncMock()
    agents.run = AsyncMock(
        return_value=WorkerResult(
            issue_number=1, branch="agent/issue-1", success=True, commits=1
        )
    )
    runner = AsyncMock()
    return TDDOrchestrator(config, agents, runner), agents, runner


def _make_task(task_id=1):
    return Task(id=task_id, title="Add feature")


def _make_runner_success(runner):
    """Configure runner.run_simple to return success."""
    result = MagicMock()
    result.returncode = 0
    runner.run_simple = AsyncMock(return_value=result)


def _make_runner_fail_then_succeed(runner, fail_count=1):
    """Configure runner.run_simple to fail N times then succeed."""
    results = []
    for _ in range(fail_count):
        r = MagicMock()
        r.returncode = 1
        results.append(r)
    success = MagicMock()
    success.returncode = 0
    results.append(success)
    runner.run_simple = AsyncMock(side_effect=results * 10)  # enough for all calls


# ---------------------------------------------------------------------------
# topological_sort
# ---------------------------------------------------------------------------


class TestTopologicalSort:
    def test_no_deps(self):
        phases = [
            TaskGraphPhase(id="P1", name="P1 — A", files=[], tests=[], depends_on=[]),
            TaskGraphPhase(id="P2", name="P2 — B", files=[], tests=[], depends_on=[]),
        ]
        result = topological_sort(phases)
        assert [p.id for p in result] == ["P1", "P2"]

    def test_respects_deps(self):
        phases = [
            TaskGraphPhase(
                id="P2", name="P2 — B", files=[], tests=[], depends_on=["P1"]
            ),
            TaskGraphPhase(id="P1", name="P1 — A", files=[], tests=[], depends_on=[]),
        ]
        result = topological_sort(phases)
        assert [p.id for p in result] == ["P1", "P2"]

    def test_cycle_returns_original_order(self):
        phases = [
            TaskGraphPhase(
                id="P1", name="P1 — A", files=[], tests=[], depends_on=["P2"]
            ),
            TaskGraphPhase(
                id="P2", name="P2 — B", files=[], tests=[], depends_on=["P1"]
            ),
        ]
        result = topological_sort(phases)
        assert [p.id for p in result] == ["P1", "P2"]

    def test_missing_dep_skipped(self):
        phases = [
            TaskGraphPhase(
                id="P1", name="P1 — A", files=[], tests=[], depends_on=["P99"]
            ),
        ]
        result = topological_sort(phases)
        assert [p.id for p in result] == ["P1"]

    def test_single_phase(self):
        phases = [
            TaskGraphPhase(id="P1", name="P1 — A", files=[], tests=[], depends_on=[]),
        ]
        result = topological_sort(phases)
        assert len(result) == 1

    def test_diamond_deps(self):
        phases = [
            TaskGraphPhase(id="P1", name="P1", files=[], tests=[], depends_on=[]),
            TaskGraphPhase(id="P2", name="P2", files=[], tests=[], depends_on=["P1"]),
            TaskGraphPhase(id="P3", name="P3", files=[], tests=[], depends_on=["P1"]),
            TaskGraphPhase(
                id="P4", name="P4", files=[], tests=[], depends_on=["P2", "P3"]
            ),
        ]
        result = topological_sort(phases)
        ids = [p.id for p in result]
        assert ids.index("P1") < ids.index("P2")
        assert ids.index("P1") < ids.index("P3")
        assert ids.index("P2") < ids.index("P4")
        assert ids.index("P3") < ids.index("P4")


# ---------------------------------------------------------------------------
# TDDOrchestrator.run_phased
# ---------------------------------------------------------------------------


class TestTDDOrchestrator:
    @pytest.mark.asyncio
    async def test_disabled_falls_back(self):
        orch, agents, _runner = _make_orchestrator(tdd_enabled=False)
        task = _make_task()
        result = await orch.run_phased(task, Path("/tmp/wt"), "branch", TASK_GRAPH_PLAN)
        agents.run.assert_awaited_once()
        assert result.success is True

    @pytest.mark.asyncio
    async def test_no_task_graph_falls_back(self):
        orch, agents, _runner = _make_orchestrator()
        task = _make_task()
        result = await orch.run_phased(
            task, Path("/tmp/wt"), "branch", NO_TASK_GRAPH_PLAN
        )
        agents.run.assert_awaited_once()
        assert result.success is True

    @pytest.mark.asyncio
    async def test_happy_path_all_phases_pass(self):
        orch, _agents, runner = _make_orchestrator()
        _make_runner_success(runner)
        task = _make_task()
        result = await orch.run_phased(task, Path("/tmp/wt"), "branch", TASK_GRAPH_PLAN)
        assert result.success is True
        assert result.commits == 2  # 2 phases

    @pytest.mark.asyncio
    async def test_red_failure_triggers_fallback(self):
        orch, agents, runner = _make_orchestrator()
        # RED step fails immediately
        fail_result = MagicMock()
        fail_result.returncode = 1
        runner.run_simple = AsyncMock(return_value=fail_result)

        task = _make_task()
        await orch.run_phased(task, Path("/tmp/wt"), "branch", TASK_GRAPH_PLAN)
        # Should have fallen back to single-agent
        agents.run.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_validate_failure_remediates(self):
        orch, _agents, runner = _make_orchestrator(max_loops=2)
        # RED succeeds, GREEN succeeds, first VALIDATE fails, fix succeeds,
        # second VALIDATE succeeds — for EACH phase
        call_count = 0

        async def _run_simple(cmd, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            # For make test calls (VALIDATE), fail on 3rd call (first validate)
            if "make" in cmd:
                # First make test fails, second succeeds
                if call_count == 3:
                    result.returncode = 1
                else:
                    result.returncode = 0
            else:
                result.returncode = 0
            return result

        runner.run_simple = AsyncMock(side_effect=_run_simple)
        task = _make_task()

        # Use a plan with just one phase to simplify counting
        one_phase_plan = (
            "## Task Graph\n\n"
            "### P1 — Model\n"
            "**Files:** `src/models.py`\n"
            "**Tests:**\n- validates fields\n"
            "**Depends on:** None\n"
        )
        result = await orch.run_phased(task, Path("/tmp/wt"), "branch", one_phase_plan)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_max_remediation_exceeded_falls_back(self):
        orch, agents, runner = _make_orchestrator(max_loops=1)
        call_count = 0

        async def _run_simple(cmd, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if "make" in cmd:
                result.returncode = 1  # always fail validation
            else:
                result.returncode = 0  # RED/GREEN/fix succeed
            return result

        runner.run_simple = AsyncMock(side_effect=_run_simple)
        task = _make_task()

        one_phase_plan = (
            "## Task Graph\n\n"
            "### P1 — Model\n"
            "**Files:** `src/models.py`\n"
            "**Tests:**\n- validates fields\n"
            "**Depends on:** None\n"
        )
        await orch.run_phased(task, Path("/tmp/wt"), "branch", one_phase_plan)
        # Should have fallen back
        agents.run.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_empty_phases_falls_back(self):
        orch, agents, _runner = _make_orchestrator()
        task = _make_task()
        # Plan has Task Graph header but no phases
        empty_plan = "## Task Graph\n\nNo phases defined.\n"
        await orch.run_phased(task, Path("/tmp/wt"), "branch", empty_plan)
        agents.run.assert_awaited_once()


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


class TestPromptBuilding:
    def test_red_prompt_contains_constraints(self):
        task = _make_task()
        phase = TaskGraphPhase(
            id="P1",
            name="P1 — Data Model",
            files=["src/models.py"],
            tests=["Task model validates fields"],
            depends_on=[],
        )
        prompt = TDDOrchestrator._build_red_prompt(task, phase)
        assert "RED" in prompt
        assert "tests/" in prompt
        assert "src/models.py" in prompt
        assert "Task model validates fields" in prompt
        assert "Do NOT modify any source" in prompt

    def test_green_prompt_contains_constraints(self):
        task = _make_task()
        phase = TaskGraphPhase(
            id="P1",
            name="P1 — Data Model",
            files=["src/models.py"],
            tests=[],
            depends_on=[],
        )
        prompt = TDDOrchestrator._build_green_prompt(task, phase)
        assert "GREEN" in prompt
        assert "src/models.py" in prompt
        assert "NOT test files" in prompt

    def test_fix_prompt_includes_attempt(self):
        task = _make_task()
        phase = TaskGraphPhase(
            id="P1", name="P1 — Model", files=[], tests=[], depends_on=[]
        )
        prompt = TDDOrchestrator._build_fix_prompt(task, phase, 2)
        assert "attempt 2" in prompt
        assert "make test" in prompt


# ---------------------------------------------------------------------------
# TDDPhaseResult model
# ---------------------------------------------------------------------------


class TestTDDPhaseResult:
    def test_defaults(self):
        result = TDDPhaseResult(phase_id="P1")
        assert result.red_success is False
        assert result.green_success is False
        assert result.validate_success is False
        assert result.remediation_attempts == 0

    def test_all_success(self):
        result = TDDPhaseResult(
            phase_id="P1",
            red_success=True,
            green_success=True,
            validate_success=True,
        )
        assert result.validate_success is True
