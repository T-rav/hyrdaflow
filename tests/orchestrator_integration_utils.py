"""Testing harness with scripted orchestrator phases."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from config import HydraFlowConfig
from issue_store import IssueStore
from models import (
    GitHubIssue,
    PlanResult,
    PRInfo,
    ReviewResult,
    ReviewVerdict,
    Task,
    WorkerResult,
)
from subprocess_util import CreditExhaustedError


class FakeRunner:
    """Minimal runner stub with terminate() and _active_procs."""

    def __init__(self) -> None:
        self._active_procs: set[int] = set()

    def terminate(self) -> None:
        self._active_procs.clear()


class FakeBackgroundLoop:
    """Background loop stub that records invocations."""

    def __init__(self) -> None:
        self.run_count = 0

    async def run(self) -> None:
        self.run_count += 1
        await asyncio.sleep(0)


class FakeWorktreeManager:
    """Tracks worktree cleanup calls."""

    def __init__(self) -> None:
        self.cleaned: list[int] = []
        self.created: list[int] = []

    async def create(self, issue_number: int, branch: str) -> Path:
        self.created.append(issue_number)
        return Path(f"/tmp/worktree-{issue_number}")

    def cleanup(self, issue_number: int) -> None:
        self.cleaned.append(issue_number)

    def discard(self, issue_number: int) -> None:
        self.cleaned.append(issue_number)

    async def sanitize_repo(self) -> None:
        pass


class StaticTaskFetcher:
    """Task fetcher stub used by IssueStore."""

    async def fetch_all(self) -> list[Task]:
        return []


@dataclass
class PipelineScript:
    """Declarative routing for scripted orchestrator tests."""

    triage_routes: dict[int, str] = field(default_factory=dict)
    plan_routes: dict[int, str] = field(default_factory=dict)
    implement_behaviors: dict[int, str] = field(default_factory=dict)
    review_behaviors: dict[int, str] = field(default_factory=dict)
    hitl_resolutions: dict[int, str] = field(default_factory=dict)
    credit_resume_seconds: float = 0.01

    def triage_for(self, issue_id: int) -> str:
        return self.triage_routes.get(issue_id, "plan")

    def plan_for(self, issue_id: int) -> str:
        return self.plan_routes.get(issue_id, "ready")

    def implement_for(self, issue_id: int) -> str:
        return self.implement_behaviors.get(issue_id, "success")

    def review_for(self, issue_id: int) -> str:
        return self.review_behaviors.get(issue_id, "merge")

    def hitl_for(self, issue_id: int) -> str:
        return self.hitl_resolutions.get(issue_id, "plan")


class ScriptedGitHub:
    """Tracks PRs opened by the scripted implementer."""

    def __init__(self) -> None:
        self._next_pr = 1000
        self._prs: dict[int, PRInfo] = {}

    def open_pr(self, issue: Task) -> PRInfo:
        pr = PRInfo(
            number=self._next_pr,
            issue_number=issue.id,
            branch=f"agent/issue-{issue.id}",
            url=f"https://example.test/pr/{self._next_pr}",
            draft=False,
        )
        self._next_pr += 1
        self._prs[issue.id] = pr
        return pr

    def get_pr(self, issue_id: int) -> PRInfo | None:
        return self._prs.get(issue_id)

    def active_issue_numbers(self) -> Iterable[int]:
        return self._prs.keys()


class ScriptedReviewFetcher:
    """Fetches reviewable PRs for scripted scenarios."""

    def __init__(self, github: ScriptedGitHub) -> None:
        self._github = github

    async def fetch_issues_by_labels(
        self, labels: list[str], *, limit: int = 50
    ) -> list[GitHubIssue]:
        return []

    async def fetch_reviewable_prs(
        self,
        _active_in_store: set[int],
        *,
        prefetched_issues: list[GitHubIssue] | None = None,
    ) -> tuple[list[PRInfo], list[GitHubIssue]]:
        issues = prefetched_issues or []
        prs: list[PRInfo] = []
        matched_issues: list[GitHubIssue] = []
        for issue in issues:
            pr = self._github.get_pr(issue.number)
            if pr is None:
                continue
            prs.append(pr)
            matched_issues.append(issue)
        return prs, matched_issues


class ScriptedTriagePhase:
    """Moves issues from find -> plan (or hitl) based on script."""

    def __init__(
        self, config: HydraFlowConfig, store: IssueStore, script: PipelineScript
    ) -> None:
        self._config = config
        self._store = store
        self._script = script
        self.processed: list[int] = []

    async def triage_issues(self) -> int:
        issues = self._store.get_triageable(self._config.batch_size)
        for issue in issues:
            route = self._script.triage_for(issue.id)
            self.processed.append(issue.id)
            if route == "hitl":
                self._store.enqueue_transition(issue, "hitl")
            else:
                self._store.enqueue_transition(issue, "plan")
        return len(issues)


class ScriptedPlanPhase:
    """Moves issues from plan -> ready (or hitl) based on script."""

    def __init__(
        self, config: HydraFlowConfig, store: IssueStore, script: PipelineScript
    ) -> None:
        self._config = config
        self._store = store
        self._script = script

    async def plan_issues(self) -> list[PlanResult]:
        issues = self._store.get_plannable(self._config.batch_size)
        results: list[PlanResult] = []
        for issue in issues:
            route = self._script.plan_for(issue.id)
            if route == "hitl":
                self._store.enqueue_transition(issue, "hitl")
                results.append(
                    PlanResult(
                        issue_number=issue.id,
                        success=False,
                        error="escalated to hitl",
                    )
                )
            else:
                self._store.enqueue_transition(issue, "ready")
                results.append(
                    PlanResult(
                        issue_number=issue.id,
                        success=True,
                        plan=f"Plan for issue {issue.id}",
                    )
                )
        return results


class ScriptedImplementPhase:
    """Runs scripted implementations."""

    def __init__(
        self,
        config: HydraFlowConfig,
        store: IssueStore,
        script: PipelineScript,
        worktrees: FakeWorktreeManager,
        github: ScriptedGitHub,
    ) -> None:
        self._config = config
        self._store = store
        self._script = script
        self._worktrees = worktrees
        self._github = github

    async def run_batch(
        self,
        issues: list[Task] | None = None,
    ) -> tuple[list[WorkerResult], list[Task]]:
        if issues is None:
            issues = self._store.get_implementable(2 * self._config.max_workers)
        results: list[WorkerResult] = []
        if not issues:
            return results, []
        for issue in issues:
            behavior = self._script.implement_for(issue.id)
            branch = f"agent/issue-{issue.id}"
            if behavior == "credit_pause":
                resume = datetime.now(UTC) + timedelta(
                    seconds=self._script.credit_resume_seconds
                )
                raise CreditExhaustedError("credits exhausted", resume_at=resume)
            if behavior == "hitl":
                self._store.enqueue_transition(issue, "hitl")
                results.append(
                    WorkerResult(
                        issue_number=issue.id,
                        branch=branch,
                        success=False,
                        error="escalated",
                    )
                )
                continue
            if behavior == "fail":
                # Intentional: consume issue from queue without re-enqueuing,
                # simulating a terminal failure (worktree cleaned, issue dropped).
                self._worktrees.cleanup(issue.id)
                results.append(
                    WorkerResult(
                        issue_number=issue.id,
                        branch=branch,
                        success=False,
                        error="implementation failed",
                    )
                )
                continue
            self._store.enqueue_transition(issue, "review")
            self._github.open_pr(issue)
            results.append(
                WorkerResult(
                    issue_number=issue.id,
                    branch=branch,
                    success=True,
                )
            )
        return results, issues


class ScriptedReviewPhase:
    """Scripted review that merges PRs immediately."""

    def __init__(self, script: PipelineScript, github: ScriptedGitHub) -> None:
        self._script = script
        self._github = github

    async def review_adrs(self, _issues: list[GitHubIssue]) -> list[ReviewResult]:
        return []

    async def review_prs(
        self, prs: list[PRInfo], issues: list[Task]
    ) -> list[ReviewResult]:
        results: list[ReviewResult] = []
        for issue, pr in zip(issues, prs, strict=True):
            action = self._script.review_for(issue.id)
            merged = action == "merge"
            results.append(
                ReviewResult(
                    pr_number=pr.number,
                    issue_number=issue.id,
                    verdict=ReviewVerdict.APPROVE if merged else ReviewVerdict.COMMENT,
                    summary="Merged" if merged else "Needs work",
                    merged=merged,
                    ci_passed=True,
                )
            )
            if merged:
                self._github._prs.pop(issue.id, None)
        return results


class ScriptedHITLPhase:
    """Processes scripted HITL corrections."""

    def __init__(self, store: IssueStore, script: PipelineScript) -> None:
        self._store = store
        self._script = script
        self._corrections: dict[int, str] = {}
        self._active_hitl_issues: set[int] = set()

    @property
    def active_hitl_issues(self) -> set[int]:
        return self._active_hitl_issues

    @property
    def hitl_corrections(self) -> dict[int, str]:
        return self._corrections

    def get_status(self, issue_number: int) -> str:
        if issue_number in self._active_hitl_issues:
            return "processing"
        if issue_number in self._corrections:
            return "pending"
        return "unknown"

    def submit_correction(self, issue_number: int, correction: str) -> None:
        self._corrections[issue_number] = correction

    def skip_issue(self, issue_number: int) -> None:
        self._corrections.pop(issue_number, None)

    async def attempt_auto_fixes(self, hitl_issues: list) -> None:
        pass

    async def process_corrections(self) -> None:
        pending = dict(self._corrections)
        self._corrections.clear()
        for issue_number in pending:
            self._active_hitl_issues.add(issue_number)
            stage = self._script.hitl_for(issue_number)
            task = self._store.get_cached(issue_number)
            if task is None:
                self._active_hitl_issues.discard(issue_number)
                continue
            self._store.enqueue_transition(task, stage)
            self._active_hitl_issues.discard(issue_number)


def _make_pr_manager_stub() -> Any:
    """Create a PR manager stub with async no-ops."""
    stub = SimpleNamespace()
    async_methods = [
        "ensure_labels_exist",
        "pull_main",
        "swap_pipeline_labels",
        "post_comment",
        "close_task",
        "create_task",
        "push_branch",
        "remove_label",
        "transition",
    ]
    for name in async_methods:
        setattr(stub, name, AsyncMock())
    return stub


def build_scripted_services(
    config: HydraFlowConfig,
    event_bus: Any,
    state: Any,
    stop_event: asyncio.Event,
    callbacks: Any,
    *,
    script: PipelineScript,
) -> SimpleNamespace:
    """Return a fake ServiceRegistry wired with scripted phases."""
    worktrees = FakeWorktreeManager()
    github = ScriptedGitHub()

    store = IssueStore(config, StaticTaskFetcher(), event_bus)

    services = SimpleNamespace()
    services.worktrees = worktrees
    services.subprocess_runner = MagicMock()
    services.agents = FakeRunner()
    services.planners = FakeRunner()
    services.prs = _make_pr_manager_stub()
    services.reviewers = FakeRunner()
    services.hitl_runner = FakeRunner()
    services.triage = FakeRunner()
    services.summarizer = MagicMock()
    services.fetcher = ScriptedReviewFetcher(github)
    services.store = store
    services.triager = ScriptedTriagePhase(config, store, script)
    services.planner_phase = ScriptedPlanPhase(config, store, script)
    services.hitl_phase = ScriptedHITLPhase(store, script)
    services.run_recorder = MagicMock()
    services.implementer = ScriptedImplementPhase(
        config,
        store,
        script,
        worktrees,
        github,
    )
    services.metrics_manager = MagicMock()
    services.pr_unsticker = MagicMock()
    services.memory_sync = MagicMock()
    services.retrospective = MagicMock()
    services.ac_generator = MagicMock()
    services.verification_judge = MagicMock()
    services.epic_checker = MagicMock()
    services.reviewer = ScriptedReviewPhase(script, github)
    services.memory_sync_bg = FakeBackgroundLoop()
    services.metrics_sync_bg = FakeBackgroundLoop()
    services.pr_unsticker_loop = FakeBackgroundLoop()
    services.manifest_refresh_loop = FakeBackgroundLoop()
    services.report_issue_loop = FakeBackgroundLoop()
    services.epic_manager = MagicMock()
    services.epic_monitor_loop = FakeBackgroundLoop()
    services.worktree_gc_loop = FakeBackgroundLoop()
    services.runs_gc_loop = FakeBackgroundLoop()
    services.adr_reviewer_loop = FakeBackgroundLoop()
    services.crate_manager = SimpleNamespace(
        active_crate_number=None,
        check_and_advance=AsyncMock(),
        auto_package_if_needed=AsyncMock(),
    )
    return services
