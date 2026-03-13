"""TDD Agent Isolation — per-phase RED/GREEN/VALIDATE orchestration.

For Task Graph plans, runs each phase through a TDD cycle:
  RED   — write failing tests (restricted to test files)
  GREEN — implement to make tests pass (restricted to source files)
  VALIDATE — run the full test suite

Config-gated via ``tdd_isolation_enabled`` (default False).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from models import Task, TDDPhaseResult, WorkerResult
from task_graph import TaskGraphPhase, extract_phases, has_task_graph

if TYPE_CHECKING:
    from agent import AgentRunner
    from config import HydraFlowConfig
    from execution import SubprocessRunner

logger = logging.getLogger("hydraflow.tdd_orchestrator")


class TDDOrchestrator:
    """Runs per-phase TDD isolation for Task Graph plans.

    Each :class:`TaskGraphPhase` is executed as:
      1. **RED** — agent writes failing tests only
      2. **GREEN** — agent implements to pass those tests
      3. **VALIDATE** — ``make test`` confirms the suite passes

    If any phase exceeds ``tdd_max_remediation_loops`` the orchestrator
    falls back to a single-agent run for the entire issue.
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        agents: AgentRunner,
        runner: SubprocessRunner,
    ) -> None:
        self._config = config
        self._agents = agents
        self._runner = runner

    async def run_phased(
        self,
        task: Task,
        wt_path: Path,
        branch: str,
        plan: str,
        worker_id: int = 0,
    ) -> WorkerResult:
        """Run TDD isolation for each phase in *plan*.

        Returns a :class:`WorkerResult`.  Falls back to single-agent
        when isolation is disabled, the plan has no task graph, or a
        phase fails beyond the remediation cap.
        """
        if not self._config.tdd_isolation_enabled:
            logger.debug("TDD isolation disabled — falling back to single-agent")
            return await self._fallback(task, wt_path, branch, worker_id)

        if not has_task_graph(plan):
            logger.debug("No Task Graph found — falling back to single-agent")
            return await self._fallback(task, wt_path, branch, worker_id)

        phases = extract_phases(plan)
        if not phases:
            logger.debug("Task Graph has no phases — falling back to single-agent")
            return await self._fallback(task, wt_path, branch, worker_id)

        ordered = topological_sort(phases)
        phase_results: list[TDDPhaseResult] = []

        for phase in ordered:
            result = await self._run_phase(task, wt_path, branch, phase, worker_id)
            phase_results.append(result)

            if not result.validate_success:
                logger.warning(
                    "Phase %s failed validation after %d remediation attempts — "
                    "falling back to single-agent",
                    phase.id,
                    result.remediation_attempts,
                )
                return await self._fallback(task, wt_path, branch, worker_id)

        logger.info(
            "TDD isolation complete for issue #%d: %d phases passed",
            task.id,
            len(phase_results),
        )
        return WorkerResult(
            issue_number=task.id,
            branch=branch,
            worktree_path=str(wt_path),
            success=True,
            commits=len(phase_results),
        )

    async def _run_phase(
        self,
        task: Task,
        wt_path: Path,
        branch: str,
        phase: TaskGraphPhase,
        worker_id: int,
    ) -> TDDPhaseResult:
        """Execute RED/GREEN/VALIDATE for a single phase."""
        max_loops = self._config.tdd_max_remediation_loops
        result = TDDPhaseResult(phase_id=phase.id)

        # RED — write failing tests
        red_prompt = self._build_red_prompt(task, phase)
        red_ok = await self._run_step(wt_path, red_prompt, worker_id)
        result.red_success = red_ok

        if not red_ok:
            return result

        # GREEN — implement to pass tests
        green_prompt = self._build_green_prompt(task, phase)
        green_ok = await self._run_step(wt_path, green_prompt, worker_id)
        result.green_success = green_ok

        if not green_ok:
            return result

        # VALIDATE — run test suite
        for attempt in range(max_loops + 1):
            validate_ok = await self._run_validate(wt_path)
            if validate_ok:
                result.validate_success = True
                result.remediation_attempts = attempt
                return result

            if attempt < max_loops:
                result.remediation_attempts = attempt + 1
                fix_prompt = self._build_fix_prompt(task, phase, attempt + 1)
                fix_ok = await self._run_step(wt_path, fix_prompt, worker_id)
                if not fix_ok:
                    return result

        result.remediation_attempts = max_loops
        return result

    async def _run_step(self, wt_path: Path, prompt: str, worker_id: int) -> bool:
        """Run a single agent step.  Returns True on success."""
        try:
            result = await self._runner.run_simple(
                ["claude", "-p", "--output-format", "text"],
                cwd=str(wt_path),
                timeout=self._config.agent_timeout,
                stdin_data=prompt,
            )
            return result.returncode == 0
        except (TimeoutError, OSError):
            logger.warning("Agent step failed in %s", wt_path, exc_info=True)
            return False

    async def _run_validate(self, wt_path: Path) -> bool:
        """Run ``make test`` in the worktree.  Returns True on success."""
        try:
            result = await self._runner.run_simple(
                ["make", "test"],
                cwd=str(wt_path),
                timeout=self._config.quality_timeout,
            )
            return result.returncode == 0
        except (TimeoutError, FileNotFoundError, OSError):
            logger.warning("Validation failed in %s", wt_path, exc_info=True)
            return False

    async def _fallback(
        self, task: Task, wt_path: Path, branch: str, worker_id: int
    ) -> WorkerResult:
        """Fall back to a single-agent implementation run."""
        return await self._agents.run(task, wt_path, branch, worker_id=worker_id)

    # --- Prompt builders ---

    @staticmethod
    def _build_red_prompt(task: Task, phase: TaskGraphPhase) -> str:
        """Build a RED-step prompt: write failing tests only."""
        files_list = "\n".join(f"- `{f}`" for f in phase.files) or "- (none specified)"
        tests_list = "\n".join(f"- {t}" for t in phase.tests) or "- (none specified)"
        return (
            f"## RED Step — {phase.name}\n\n"
            f"Issue #{task.id}: {task.title}\n\n"
            f"You are in the RED phase of TDD. Write FAILING tests only.\n\n"
            f"### Constraints\n"
            f"- ONLY create or modify files in `tests/`\n"
            f"- Do NOT modify any source/implementation files\n"
            f"- Tests MUST fail (they test behavior that doesn't exist yet)\n"
            f"- Commit your test files when done\n\n"
            f"### Target Files\n{files_list}\n\n"
            f"### Behavioral Specs to Test\n{tests_list}\n"
        )

    @staticmethod
    def _build_green_prompt(task: Task, phase: TaskGraphPhase) -> str:
        """Build a GREEN-step prompt: implement to pass tests."""
        files_list = "\n".join(f"- `{f}`" for f in phase.files) or "- (none specified)"
        return (
            f"## GREEN Step — {phase.name}\n\n"
            f"Issue #{task.id}: {task.title}\n\n"
            f"You are in the GREEN phase of TDD. Implement the minimum code "
            f"to make all failing tests pass.\n\n"
            f"### Constraints\n"
            f"- ONLY modify source/implementation files (NOT test files)\n"
            f"- Write the minimum code to pass the tests\n"
            f"- Commit your changes when done\n\n"
            f"### Files to Modify\n{files_list}\n"
        )

    @staticmethod
    def _build_fix_prompt(task: Task, phase: TaskGraphPhase, attempt: int) -> str:
        """Build a remediation prompt after a failed validation."""
        return (
            f"## Fix Step — {phase.name} (attempt {attempt})\n\n"
            f"Issue #{task.id}: {task.title}\n\n"
            f"The test suite failed after the GREEN step. Fix the failing tests "
            f"by modifying implementation code (not test code).\n\n"
            f"Run `make test` to verify your fixes, then commit.\n"
        )


def topological_sort(phases: list[TaskGraphPhase]) -> list[TaskGraphPhase]:
    """Sort phases respecting dependency order.

    Phases with no dependencies come first.  If dependencies are
    missing or circular, the function falls back to the original order.
    """
    by_id = {p.id: p for p in phases}
    visited: set[str] = set()
    result: list[TaskGraphPhase] = []
    in_progress: set[str] = set()

    def _visit(pid: str) -> bool:
        if pid in visited:
            return True
        if pid in in_progress:
            return False  # cycle
        in_progress.add(pid)
        phase = by_id.get(pid)
        if phase is None:
            return True  # missing dep — skip
        for dep in phase.depends_on:
            if not _visit(dep):
                return False
        in_progress.discard(pid)
        visited.add(pid)
        result.append(phase)
        return True

    for p in phases:
        if not _visit(p.id):
            logger.warning("Cycle detected in task graph — using original order")
            return list(phases)

    return result
