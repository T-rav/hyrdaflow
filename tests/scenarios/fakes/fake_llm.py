"""Scripted LLM runner fakes for scenario testing.

FakeLLM provides per-phase, per-issue result sequences. Each runner method
pops the next result from a deque. When the deque is empty, a default
success result is returned.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

from models import EpicDecompResult, ReviewVerdict
from tests.conftest import (
    PlanResultFactory,
    ReviewResultFactory,
    TriageResultFactory,
    WorkerResultFactory,
)


class _ScriptedRunner:
    """Base for a runner that returns scripted results by issue number."""

    def __init__(self) -> None:
        self._scripts: dict[int, deque[Any]] = {}

    def _add_script(self, issue_number: int, results: list[Any]) -> None:
        self._scripts[issue_number] = deque(results)

    def add_script(self, issue_number: int, results: list[Any]) -> None:
        self._add_script(issue_number, results)

    def _pop(self, issue_number: int, default_factory: Callable[[], Any]) -> Any:
        q = self._scripts.get(issue_number)
        if q:
            return q.popleft()
        return default_factory()

    def set_tracing_context(self, _context: Any) -> None:
        pass

    def clear_tracing_context(self) -> None:
        pass


class _FakeTriageRunner(_ScriptedRunner):
    async def evaluate(self, issue: Any, _worker_id: int = 0) -> Any:
        issue_number = getattr(issue, "id", getattr(issue, "number", 0))
        return self._pop(
            issue_number,
            lambda: TriageResultFactory.create(issue_number=issue_number, ready=True),
        )

    async def run_decomposition(self, _task: Any) -> EpicDecompResult:
        # Real decomposition is not exercised in scenario tests; return a
        # no-op result so triage_phase.py can safely read should_decompose.
        return EpicDecompResult(should_decompose=False)


class _FakePlannerRunner(_ScriptedRunner):
    async def plan(
        self, task: Any, _worker_id: int = 0, _research_context: str = ""
    ) -> Any:
        issue_number = getattr(task, "id", getattr(task, "number", 0))
        return self._pop(
            issue_number,
            lambda: PlanResultFactory.create(issue_number=issue_number, success=True),
        )

    async def run_gap_review(
        self,
        _epic_number: int,
        _child_plans: dict[Any, Any],
        _child_titles: dict[Any, Any],
    ) -> str:
        return ""


class _FakeAgentRunner(_ScriptedRunner):
    async def run(
        self,
        task: Any,
        worktree_path: Path,
        branch: str,
        _worker_id: int = 0,
        _review_feedback: str = "",
        _prior_failure: str = "",
        _bead_mapping: dict[str, str] | None = None,
    ) -> Any:
        issue_number = getattr(task, "id", getattr(task, "number", 0))
        return self._pop(
            issue_number,
            lambda: WorkerResultFactory.create(
                issue_number=issue_number,
                branch=branch,
                workspace_path=str(worktree_path),
                success=True,
                commits=1,
            ),
        )


class _FakeReviewRunner(_ScriptedRunner):
    async def review(
        self,
        pr: Any,
        issue: Any,
        _worktree_path: Path,
        _diff: str,
        _worker_id: int = 0,
        _code_scanning_alerts: list[Any] | None = None,
        _bead_tasks: list[Any] | None = None,
    ) -> Any:
        issue_number = getattr(issue, "id", getattr(issue, "number", 0))
        pr_number = getattr(pr, "number", 0)
        return self._pop(
            issue_number,
            lambda: ReviewResultFactory.create(
                pr_number=pr_number,
                issue_number=issue_number,
                verdict=ReviewVerdict.APPROVE,
                merged=True,
                ci_passed=True,
            ),
        )

    async def fix_ci(
        self,
        pr: Any,
        issue: Any,
        _worktree_path: Path,
        _failure_summary: str,
        **_kwargs: Any,
    ) -> Any:
        issue_number = getattr(issue, "id", getattr(issue, "number", 0))
        pr_number = getattr(pr, "number", 0)
        return ReviewResultFactory.create(
            pr_number=pr_number,
            issue_number=issue_number,
            verdict=ReviewVerdict.APPROVE,
            ci_passed=True,
        )


class FakeLLM:
    """Composable scripted LLM runners for all pipeline phases."""

    def __init__(self) -> None:
        self.triage_runner = _FakeTriageRunner()
        self.planners = _FakePlannerRunner()
        self.agents = _FakeAgentRunner()
        self.reviewers = _FakeReviewRunner()

    def script_triage(self, issue_number: int, results: list[Any]) -> None:
        self.triage_runner.add_script(issue_number, results)

    def script_plan(self, issue_number: int, results: list[Any]) -> None:
        self.planners.add_script(issue_number, results)

    def script_implement(self, issue_number: int, results: list[Any]) -> None:
        self.agents.add_script(issue_number, results)

    def script_review(self, issue_number: int, results: list[Any]) -> None:
        self.reviewers.add_script(issue_number, results)
