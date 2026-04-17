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
        self._last_scripted: dict[int, Any] = {}

    def _add_script(self, issue_number: int, results: list[Any]) -> None:
        self._scripts[issue_number] = deque(results)
        # Clear any stale last-scripted so the new script takes precedence
        self._last_scripted.pop(issue_number, None)

    def add_script(self, issue_number: int, results: list[Any]) -> None:
        self._add_script(issue_number, results)

    def _pop(self, issue_number: int, default_factory: Callable[[], Any]) -> Any:
        q = self._scripts.get(issue_number)
        if q:
            result = q.popleft()
            self._last_scripted[issue_number] = result
            return result
        # Deque empty — repeat last scripted result if we had one
        if issue_number in self._last_scripted:
            return self._last_scripted[issue_number]
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
        self,
        task: Any,
        *,
        worker_id: int = 0,
        research_context: str = "",
        **_unused: Any,
    ) -> Any:
        _ = (worker_id, research_context)
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
    def __init__(self) -> None:
        super().__init__()
        self._streams: dict[int, list[Any]] = {}
        self._prior_failures: dict[int, list[str]] = {}

    async def run(
        self,
        task: Any,
        worktree_path: Path,
        branch: str,
        *,
        worker_id: int = 0,
        review_feedback: str = "",
        prior_failure: str = "",
        bead_mapping: dict[str, str] | None = None,
        **_unused: Any,
    ) -> Any:
        _ = (worker_id, review_feedback, bead_mapping)
        issue_number = getattr(task, "id", getattr(task, "number", 0))
        if prior_failure:
            self._prior_failures.setdefault(issue_number, []).append(prior_failure)
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

    def script_stream(self, issue_number: int, events: list[Any]) -> None:
        self._streams[issue_number] = list(events)

    def events_for(self, issue_number: int) -> list[Any]:
        return list(self._streams.get(issue_number, []))

    def prior_failures_seen_for(self, issue_number: int) -> list[str]:
        return list(self._prior_failures.get(issue_number, []))


class _FakeReviewRunner(_ScriptedRunner):
    async def review(
        self,
        pr: Any,
        issue: Any,
        _worktree_path: Path,
        _diff: str,
        *,
        worker_id: int = 0,
        code_scanning_alerts: list[Any] | None = None,
        bead_tasks: list[Any] | None = None,
        **_unused: Any,
    ) -> Any:
        _ = (worker_id, code_scanning_alerts, bead_tasks)
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
