"""Shared fixtures and factories for HydraFlow tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure source modules are importable from src/ layout.
_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))
sys.path.insert(0, str(_REPO_ROOT))

import subprocess_util  # noqa: E402
from tests.helpers import ConfigFactory  # noqa: E402

if TYPE_CHECKING:
    from ci_scaffold import CIScaffoldResult
    from config import HydraFlowConfig
    from events import HydraFlowEvent
    from models import (
        AnalysisResult,
        GitHubIssue,
        GitHubIssueState,
        HITLResult,
        NewIssueSpec,
        PlanResult,
        PRInfo,
        ReviewResult,
        ReviewVerdict,
        TriageResult,
        WorkerResult,
    )
    from orchestrator import HydraFlowOrchestrator
    from state import StateTracker
    from test_scaffold import TestScaffoldResult


# --- Session-scoped environment setup ---
#
# NOTE ON GLOBAL STATE MUTATION:
# The fixtures below intentionally mutate global state (os.environ and
# module-level private variables) to create a hermetic test environment.
#
# - ``setup_test_environment`` removes HYDRAFLOW_*/HYDRA_*/GIT_* env vars so
#   that tests don't accidentally read the host's configuration.  A
#   ``finally`` block restores original values after all tests in the session
#   complete.  An abnormal process termination (SIGKILL, segfault) will kill
#   the pytest process before the ``finally`` runs, but since the environment
#   is process-local, it cannot affect any other process — this is an
#   acceptable trade-off.
#
# - ``_reset_gh_semaphore`` clears module-level private state in
#   subprocess_util to prevent cross-test leakage of semaphore/rate-limit
#   state.  This couples tests to internal implementation details; if those
#   internals are renamed, this fixture must be updated accordingly.


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Set minimal env vars and isolate tests from host configuration.

    Removes all ``HYDRAFLOW_*``, ``HYDRA_*``, and select ``GIT_*`` variables
    from ``os.environ`` for the duration of the test session, then restores
    them in a ``finally`` block.  This is intentional global state mutation
    required for test isolation — see module-level note above.
    """
    test_env = {
        "HOME": "/tmp/hydraflow-test",
        "GH_TOKEN": "test-token",
    }
    hydra_keys = {
        key: os.environ[key]
        for key in list(os.environ)
        if key.startswith(("HYDRAFLOW_", "HYDRA_"))
    }
    git_keys = {}
    for key in (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
    ):
        if key in os.environ:
            git_keys[key] = os.environ.pop(key)
    for key in hydra_keys:
        os.environ.pop(key, None)
    try:
        with patch.dict(os.environ, test_env, clear=False):
            yield
    finally:
        os.environ.update(hydra_keys)
        os.environ.update(git_keys)


@pytest.fixture(autouse=True)
def _reset_gh_semaphore():
    """Reset the global gh semaphore and rate-limit state between tests.

    This directly mutates module-level private state in ``subprocess_util``
    (``_gh_semaphore`` and ``_rate_limit_until``) to prevent cross-test
    leakage.  See module-level note above regarding the coupling trade-off.
    """
    subprocess_util._gh_semaphore = None
    subprocess_util._rate_limit_until = None
    yield
    subprocess_util._gh_semaphore = None
    subprocess_util._rate_limit_until = None


@pytest.fixture(autouse=True)
def _disable_hitl_summary_autowarm(config) -> None:
    """Keep route tests deterministic unless a test explicitly opts in."""
    config.transcript_summarization_enabled = False
    config.gh_token = ""


# --- Config Fixtures ---


@pytest.fixture
def config(tmp_path: Path) -> HydraFlowConfig:
    """A HydraFlowConfig using tmp_path for all file operations."""

    return ConfigFactory.create(
        repo_root=tmp_path / "repo",
        worktree_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )


@pytest.fixture
def dry_config(tmp_path: Path) -> HydraFlowConfig:
    """A HydraFlowConfig in dry-run mode."""
    return ConfigFactory.create(
        dry_run=True,
        repo_root=tmp_path / "repo",
        worktree_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )


# --- Issue Factory ---


class IssueFactory:
    """Factory for GitHubIssue instances."""

    @staticmethod
    def create(
        *,
        number: int = 42,
        title: str = "Fix the frobnicator",
        body: str = "The frobnicator is broken. Please fix it.",
        labels: list[str] | None = None,
        comments: list[str] | None = None,
        url: str | None = None,
        state: GitHubIssueState | None = None,
    ):
        from models import GitHubIssue

        kwargs: dict[str, Any] = {
            "number": number,
            "title": title,
            "body": body,
            "labels": labels if labels is not None else ["ready"],
            "comments": comments if comments is not None else [],
            "url": url
            if url is not None
            else f"https://github.com/test-org/test-repo/issues/{number}",
        }
        if state is not None:
            kwargs["state"] = state
        return GitHubIssue(**kwargs)


@pytest.fixture
def issue() -> GitHubIssue:
    return IssueFactory.create()


# --- Task Factory ---


class TaskFactory:
    """Factory for Task instances."""

    @staticmethod
    def create(
        *,
        id: int = 42,
        title: str = "Fix the frobnicator",
        body: str = "The frobnicator is broken. Please fix it.",
        tags: list[str] | None = None,
        comments: list[str] | None = None,
        source_url: str | None = None,
        links: list[Any] | None = None,
        complexity_score: int = 0,
    ):
        from models import Task

        return Task(
            id=id,
            title=title,
            body=body,
            tags=tags if tags is not None else ["ready"],
            comments=comments if comments is not None else [],
            source_url=source_url
            if source_url is not None
            else f"https://github.com/test-org/test-repo/issues/{id}",
            links=links if links is not None else [],
            complexity_score=complexity_score,
        )


# --- Worker Result Factory ---


class WorkerResultFactory:
    """Factory for WorkerResult instances."""

    @staticmethod
    def create(
        *,
        issue_number: int = 42,
        branch: str = "agent/issue-42",
        success: bool | None = None,
        transcript: str | None = None,
        commits: int | None = None,
        worktree_path: str | None = None,
        error: str | None = None,
        duration_seconds: float | None = None,
        pre_quality_review_attempts: int | None = None,
        quality_fix_attempts: int | None = None,
        pr_info: PRInfo | None = None,
        use_defaults: bool = False,
    ):
        """Create a WorkerResult instance.

        By default (``use_defaults=False``), factory-defined hardcoded values are
        applied for all unspecified optional fields (e.g. ``success=True``,
        ``transcript="Implemented the feature."``).

        With ``use_defaults=True``, only explicitly provided keyword arguments are
        forwarded to the constructor and the underlying Pydantic model's own field
        defaults are used for everything else.  Prefer this mode when you need a
        minimal/sparse object to test model-level behaviour or when factory defaults
        would incorrectly satisfy a field under test.
        """
        from models import WorkerResult

        if use_defaults:
            kwargs: dict[str, Any] = {
                "issue_number": issue_number,
                "branch": branch,
            }
            if worktree_path is not None:
                kwargs["worktree_path"] = worktree_path
            if success is not None:
                kwargs["success"] = success
            if error is not None:
                kwargs["error"] = error
            if transcript is not None:
                kwargs["transcript"] = transcript
            if commits is not None:
                kwargs["commits"] = commits
            if duration_seconds is not None:
                kwargs["duration_seconds"] = duration_seconds
            if pre_quality_review_attempts is not None:
                kwargs["pre_quality_review_attempts"] = pre_quality_review_attempts
            if quality_fix_attempts is not None:
                kwargs["quality_fix_attempts"] = quality_fix_attempts
            if pr_info is not None:
                kwargs["pr_info"] = pr_info
            return WorkerResult(**kwargs)

        return WorkerResult(
            issue_number=issue_number,
            branch=branch,
            worktree_path=(
                worktree_path
                if worktree_path is not None
                else "/tmp/worktrees/issue-42"
            ),
            success=True if success is None else success,
            error=error,
            transcript=(
                transcript if transcript is not None else "Implemented the feature."
            ),
            commits=commits if commits is not None else 1,
            duration_seconds=(
                duration_seconds if duration_seconds is not None else 0.0
            ),
            pre_quality_review_attempts=(
                pre_quality_review_attempts
                if pre_quality_review_attempts is not None
                else 0
            ),
            quality_fix_attempts=(
                quality_fix_attempts if quality_fix_attempts is not None else 0
            ),
            pr_info=pr_info,
        )


class WorkerResultBuilder:
    """Fluent builder for WorkerResult instances."""

    def __init__(self) -> None:
        self._kwargs: dict[str, Any] = {}
        self._use_model_defaults: bool = False

    def with_model_defaults(self) -> WorkerResultBuilder:
        """Use Pydantic model defaults instead of factory hardcoded values."""
        self._use_model_defaults = True
        return self

    def with_issue_number(self, value: int) -> WorkerResultBuilder:
        self._kwargs["issue_number"] = value
        return self

    def with_branch(self, value: str) -> WorkerResultBuilder:
        self._kwargs["branch"] = value
        return self

    def with_success(self, value: bool) -> WorkerResultBuilder:
        self._kwargs["success"] = value
        return self

    def with_transcript(self, value: str) -> WorkerResultBuilder:
        self._kwargs["transcript"] = value
        return self

    def with_commits(self, value: int) -> WorkerResultBuilder:
        self._kwargs["commits"] = value
        return self

    def with_worktree_path(self, value: str) -> WorkerResultBuilder:
        self._kwargs["worktree_path"] = value
        return self

    def with_error(self, value: str) -> WorkerResultBuilder:
        self._kwargs["error"] = value
        return self

    def with_duration_seconds(self, value: float) -> WorkerResultBuilder:
        self._kwargs["duration_seconds"] = value
        return self

    def with_pre_quality_review_attempts(self, value: int) -> WorkerResultBuilder:
        self._kwargs["pre_quality_review_attempts"] = value
        return self

    def with_quality_fix_attempts(self, value: int) -> WorkerResultBuilder:
        self._kwargs["quality_fix_attempts"] = value
        return self

    def with_pr_info(self, value: PRInfo) -> WorkerResultBuilder:
        self._kwargs["pr_info"] = value
        return self

    def build(self) -> WorkerResult:
        """Build the WorkerResult using the factory."""
        return WorkerResultFactory.create(
            use_defaults=self._use_model_defaults, **self._kwargs
        )


# --- Plan Result Factory ---


class PlanResultFactory:
    """Factory for PlanResult instances."""

    @staticmethod
    def create(
        *,
        issue_number: int = 42,
        success: bool | None = None,
        plan: str | None = None,
        summary: str | None = None,
        error: str | None = None,
        transcript: str | None = None,
        duration_seconds: float | None = None,
        new_issues: list[NewIssueSpec] | None = None,
        validation_errors: list[str] | None = None,
        retry_attempted: bool | None = None,
        already_satisfied: bool | None = None,
        actionability_score: int | None = None,
        actionability_rank: str | None = None,
        epic_number: int | None = None,
        use_defaults: bool = False,
    ):
        """Create a PlanResult instance.

        By default (``use_defaults=False``), factory-defined hardcoded values are
        applied for all unspecified optional fields (e.g. ``success=True``,
        ``plan="## Plan\\n\\n1. Do the thing\\n2. Test the thing"``).

        With ``use_defaults=True``, only explicitly provided keyword arguments are
        forwarded to the constructor and the underlying Pydantic model's own field
        defaults are used for everything else.  Prefer this mode when you need a
        minimal/sparse object to test model-level behaviour or when factory defaults
        would incorrectly satisfy a field under test.
        """
        from models import PlanResult

        if use_defaults:
            kwargs: dict[str, Any] = {"issue_number": issue_number}
            if success is not None:
                kwargs["success"] = success
            if plan is not None:
                kwargs["plan"] = plan
            if summary is not None:
                kwargs["summary"] = summary
            if error is not None:
                kwargs["error"] = error
            if transcript is not None:
                kwargs["transcript"] = transcript
            if duration_seconds is not None:
                kwargs["duration_seconds"] = duration_seconds
            if new_issues is not None:
                kwargs["new_issues"] = list(new_issues)
            if validation_errors is not None:
                kwargs["validation_errors"] = list(validation_errors)
            if retry_attempted is not None:
                kwargs["retry_attempted"] = retry_attempted
            if already_satisfied is not None:
                kwargs["already_satisfied"] = already_satisfied
            if actionability_score is not None:
                kwargs["actionability_score"] = actionability_score
            if actionability_rank is not None:
                kwargs["actionability_rank"] = actionability_rank
            if epic_number is not None:
                kwargs["epic_number"] = epic_number
            return PlanResult(**kwargs)

        success_value = True if success is None else success
        plan_value = (
            plan
            if plan is not None
            else "## Plan\n\n1. Do the thing\n2. Test the thing"
        )
        summary_value = (
            summary if summary is not None else "Plan to implement the feature"
        )
        transcript_value = (
            transcript
            if transcript is not None
            else "PLAN_START\n## Plan\n\n1. Do the thing\nPLAN_END\nSUMMARY: Plan to implement the feature"
        )
        duration_value = duration_seconds if duration_seconds is not None else 10.0
        retry_value = False if retry_attempted is None else retry_attempted
        already_satisfied_value = (
            False if already_satisfied is None else already_satisfied
        )
        actionability_score_value = (
            actionability_score if actionability_score is not None else 0
        )
        actionability_rank_value = (
            actionability_rank if actionability_rank is not None else "unknown"
        )
        epic_number_value = epic_number if epic_number is not None else 0

        return PlanResult(
            issue_number=issue_number,
            success=success_value,
            plan=plan_value,
            summary=summary_value,
            error=error,
            transcript=transcript_value,
            duration_seconds=duration_value,
            new_issues=list(new_issues) if new_issues is not None else [],
            validation_errors=list(validation_errors)
            if validation_errors is not None
            else [],
            retry_attempted=retry_value,
            already_satisfied=already_satisfied_value,
            actionability_score=actionability_score_value,
            actionability_rank=actionability_rank_value,
            epic_number=epic_number_value,
        )


class PlanResultBuilder:
    """Fluent builder for PlanResult instances."""

    def __init__(self) -> None:
        self._kwargs: dict[str, Any] = {}
        self._use_model_defaults: bool = False

    def with_model_defaults(self) -> PlanResultBuilder:
        """Use Pydantic model defaults instead of factory hardcoded values."""
        self._use_model_defaults = True
        return self

    def with_issue_number(self, value: int) -> PlanResultBuilder:
        self._kwargs["issue_number"] = value
        return self

    def with_success(self, value: bool) -> PlanResultBuilder:
        self._kwargs["success"] = value
        return self

    def with_plan(self, value: str) -> PlanResultBuilder:
        self._kwargs["plan"] = value
        return self

    def with_summary(self, value: str) -> PlanResultBuilder:
        self._kwargs["summary"] = value
        return self

    def with_error(self, value: str) -> PlanResultBuilder:
        self._kwargs["error"] = value
        return self

    def with_transcript(self, value: str) -> PlanResultBuilder:
        self._kwargs["transcript"] = value
        return self

    def with_duration_seconds(self, value: float) -> PlanResultBuilder:
        self._kwargs["duration_seconds"] = value
        return self

    def with_new_issues(self, value: list[NewIssueSpec]) -> PlanResultBuilder:
        self._kwargs["new_issues"] = value
        return self

    def with_validation_errors(self, value: list[str]) -> PlanResultBuilder:
        self._kwargs["validation_errors"] = value
        return self

    def with_retry_attempted(self, value: bool) -> PlanResultBuilder:
        self._kwargs["retry_attempted"] = value
        return self

    def with_already_satisfied(self, value: bool) -> PlanResultBuilder:
        self._kwargs["already_satisfied"] = value
        return self

    def with_actionability_score(self, value: int) -> PlanResultBuilder:
        self._kwargs["actionability_score"] = value
        return self

    def with_actionability_rank(self, value: str) -> PlanResultBuilder:
        self._kwargs["actionability_rank"] = value
        return self

    def with_epic_number(self, value: int) -> PlanResultBuilder:
        self._kwargs["epic_number"] = value
        return self

    def build(self) -> PlanResult:
        """Build the PlanResult using the factory."""
        return PlanResultFactory.create(
            use_defaults=self._use_model_defaults, **self._kwargs
        )


# --- PR Info Factory ---


class PRInfoFactory:
    """Factory for PRInfo instances."""

    @staticmethod
    def create(
        *,
        number: int = 101,
        issue_number: int = 42,
        branch: str = "agent/issue-42",
        url: str = "https://github.com/test-org/test-repo/pull/101",
        draft: bool = False,
    ):
        from models import PRInfo

        return PRInfo(
            number=number,
            issue_number=issue_number,
            branch=branch,
            url=url,
            draft=draft,
        )


# --- Review Result Factory ---


class ReviewResultFactory:
    """Factory for ReviewResult instances."""

    @staticmethod
    def create(
        *,
        pr_number: int = 101,
        issue_number: int = 42,
        verdict: ReviewVerdict | None = None,
        success: bool | None = None,
        summary: str | None = None,
        fixes_made: bool | None = None,
        transcript: str | None = None,
        merged: bool | None = None,
        duration_seconds: float | None = None,
        ci_passed: bool | None = None,
        ci_fix_attempts: int | None = None,
        error: str | None = None,
        visual_passed: bool | None = None,
        use_defaults: bool = False,
    ) -> ReviewResult:
        """Create a ReviewResult instance.

        By default (``use_defaults=False``), factory-defined hardcoded values are
        applied for all unspecified optional fields (e.g. ``verdict=APPROVE``,
        ``summary="Looks good."``).

        With ``use_defaults=True``, only explicitly provided keyword arguments are
        forwarded to the constructor and the underlying Pydantic model's own field
        defaults are used for everything else.
        """
        from models import ReviewResult as RR
        from models import ReviewVerdict as RV

        if use_defaults:
            kwargs: dict[str, Any] = {
                "pr_number": pr_number,
                "issue_number": issue_number,
            }
            if verdict is not None:
                kwargs["verdict"] = verdict
            if success is not None:
                kwargs["success"] = success
            if summary is not None:
                kwargs["summary"] = summary
            if fixes_made is not None:
                kwargs["fixes_made"] = fixes_made
            if transcript is not None:
                kwargs["transcript"] = transcript
            if merged is not None:
                kwargs["merged"] = merged
            if duration_seconds is not None:
                kwargs["duration_seconds"] = duration_seconds
            if ci_passed is not None:
                kwargs["ci_passed"] = ci_passed
            if ci_fix_attempts is not None:
                kwargs["ci_fix_attempts"] = ci_fix_attempts
            if error is not None:
                kwargs["error"] = error
            if visual_passed is not None:
                kwargs["visual_passed"] = visual_passed
            return RR(**kwargs)

        return RR(
            pr_number=pr_number,
            issue_number=issue_number,
            verdict=verdict if verdict is not None else RV.APPROVE,
            success=success if success is not None else False,
            summary=summary if summary is not None else "Looks good.",
            error=error,
            fixes_made=fixes_made if fixes_made is not None else False,
            transcript=(
                transcript if transcript is not None else "THOROUGH_REVIEW_COMPLETE"
            ),
            merged=merged if merged is not None else False,
            duration_seconds=(
                duration_seconds if duration_seconds is not None else 0.0
            ),
            ci_passed=ci_passed,
            ci_fix_attempts=(ci_fix_attempts if ci_fix_attempts is not None else 0),
            visual_passed=visual_passed,
        )


class ReviewResultBuilder:
    """Fluent builder for ReviewResult instances."""

    def __init__(self) -> None:
        self._kwargs: dict[str, Any] = {}
        self._use_model_defaults: bool = False

    def with_model_defaults(self) -> ReviewResultBuilder:
        """Use Pydantic model defaults instead of factory hardcoded values."""
        self._use_model_defaults = True
        return self

    def with_pr_number(self, value: int) -> ReviewResultBuilder:
        self._kwargs["pr_number"] = value
        return self

    def with_issue_number(self, value: int) -> ReviewResultBuilder:
        self._kwargs["issue_number"] = value
        return self

    def with_verdict(self, value: ReviewVerdict) -> ReviewResultBuilder:
        self._kwargs["verdict"] = value
        return self

    def with_success(self, value: bool) -> ReviewResultBuilder:
        self._kwargs["success"] = value
        return self

    def with_error(self, value: str) -> ReviewResultBuilder:
        self._kwargs["error"] = value
        return self

    def with_summary(self, value: str) -> ReviewResultBuilder:
        self._kwargs["summary"] = value
        return self

    def with_fixes_made(self, value: bool) -> ReviewResultBuilder:
        self._kwargs["fixes_made"] = value
        return self

    def with_transcript(self, value: str) -> ReviewResultBuilder:
        self._kwargs["transcript"] = value
        return self

    def with_merged(self, value: bool) -> ReviewResultBuilder:
        self._kwargs["merged"] = value
        return self

    def with_duration_seconds(self, value: float) -> ReviewResultBuilder:
        self._kwargs["duration_seconds"] = value
        return self

    def with_ci_passed(self, value: bool) -> ReviewResultBuilder:
        self._kwargs["ci_passed"] = value
        return self

    def with_ci_fix_attempts(self, value: int) -> ReviewResultBuilder:
        self._kwargs["ci_fix_attempts"] = value
        return self

    def with_visual_passed(self, value: bool) -> ReviewResultBuilder:
        self._kwargs["visual_passed"] = value
        return self

    def build(self) -> ReviewResult:
        """Build the ReviewResult using the factory."""
        return ReviewResultFactory.create(
            use_defaults=self._use_model_defaults, **self._kwargs
        )


# --- HITL Result Factory ---


class HITLResultFactory:
    """Factory for HITLResult instances."""

    @staticmethod
    def create(
        *,
        issue_number: int = 42,
        success: bool = True,
        error: str | None = None,
        transcript: str = "",
        duration_seconds: float = 0.0,
    ) -> HITLResult:
        from models import HITLResult as HR

        return HR(
            issue_number=issue_number,
            success=success,
            error=error,
            transcript=transcript,
            duration_seconds=duration_seconds,
        )


# --- Event Factory ---


class EventFactory:
    """Factory for HydraFlowEvent instances."""

    @staticmethod
    def create(
        *,
        type: Any = None,
        timestamp: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> HydraFlowEvent:
        from events import EventType as ET
        from events import HydraFlowEvent as HE

        return HE(
            type=type if type is not None else ET.PHASE_CHANGE,
            timestamp=timestamp if timestamp is not None else "",
            data=data if data is not None else {},
        )


# --- Triage Result Factory ---


class TriageResultFactory:
    """Factory for TriageResult instances."""

    @staticmethod
    def create(
        *,
        issue_number: int = 42,
        ready: bool = True,
        reasons: list[str] | None = None,
    ) -> TriageResult:
        from models import TriageResult as TR

        return TR(
            issue_number=issue_number,
            ready=ready,
            reasons=reasons if reasons is not None else [],
        )


# --- Analysis Result Factory ---


class AnalysisResultFactory:
    """Factory for AnalysisResult instances."""

    @staticmethod
    def create(
        *,
        issue_number: int = 42,
        sections: list[Any] | None = None,
    ) -> AnalysisResult:
        from models import AnalysisResult as AR
        from models import AnalysisSection, AnalysisVerdict

        if sections is None:
            sections = [
                AnalysisSection(
                    name="File Validation",
                    verdict=AnalysisVerdict.PASS,
                    details=["All files exist."],
                ),
            ]
        return AR(
            issue_number=issue_number,
            sections=sections,
        )

    @staticmethod
    def create_section(
        *,
        name: str = "File Validation",
        verdict: Any | None = None,
        details: list[str] | None = None,
    ) -> Any:
        from models import AnalysisSection, AnalysisVerdict

        return AnalysisSection(
            name=name,
            verdict=verdict if verdict is not None else AnalysisVerdict.PASS,
            details=details if details is not None else [],
        )


# --- Test Scaffold Result Factory ---


class TestScaffoldResultFactory:
    """Factory for TestScaffoldResult instances."""

    __test__ = False

    @staticmethod
    def create(
        *,
        created_dirs: list[str] | None = None,
        created_files: list[str] | None = None,
        modified_files: list[str] | None = None,
        skipped: bool = False,
        skip_reason: str = "",
        language: str = "python",
    ) -> TestScaffoldResult:
        from test_scaffold import TestScaffoldResult

        return TestScaffoldResult(
            created_dirs=created_dirs if created_dirs is not None else [],
            created_files=created_files if created_files is not None else [],
            modified_files=modified_files if modified_files is not None else [],
            skipped=skipped,
            skip_reason=skip_reason,
            language=language,
        )


# --- CI Scaffold Result Factory ---


class CIScaffoldResultFactory:
    """Factory for CIScaffoldResult instances."""

    @staticmethod
    def create(
        *,
        created: bool = True,
        skipped: bool = False,
        skip_reason: str = "",
        language: str = "python",
        workflow_path: str = ".github/workflows/quality.yml",
    ) -> CIScaffoldResult:
        from ci_scaffold import CIScaffoldResult as CS

        return CS(
            created=created,
            skipped=skipped,
            skip_reason=skip_reason,
            language=language,
            workflow_path=workflow_path,
        )


# --- State Fixture ---


@pytest.fixture
def state(tmp_path: Path):
    from state import StateTracker

    return StateTracker(tmp_path / "state.json")


# --- State Factory ---


def make_state(tmp_path: Path) -> StateTracker:
    """Create a StateTracker backed by a temp file."""
    from state import StateTracker as ST

    return ST(tmp_path / "state.json")


# --- Event Bus Fixture ---


@pytest.fixture
def event_bus():
    from events import EventBus

    return EventBus()


# --- Orchestrator Mock ---


def make_orchestrator_mock(
    requests: dict | None = None,
    running: bool = False,
    run_status: str = "idle",
) -> MagicMock:
    """Return a minimal orchestrator mock."""
    orch = MagicMock()
    orch.human_input_requests = requests if requests is not None else {}
    orch.provide_human_input = MagicMock()
    orch.running = running
    orch.run_status = run_status
    orch.current_session_id = None
    orch.credits_paused_until = None
    orch.stop = AsyncMock()
    orch.request_stop = AsyncMock()
    return orch


# --- Subprocess Mock ---


class SubprocessMockBuilder:
    """Fluent builder for mocking asyncio.create_subprocess_exec."""

    def __init__(self) -> None:
        self._returncode = 0
        self._stdout = b""
        self._stderr = b""

    def with_returncode(self, code: int) -> SubprocessMockBuilder:
        self._returncode = code
        return self

    def with_stdout(self, data: str | bytes) -> SubprocessMockBuilder:
        self._stdout = data.encode() if isinstance(data, str) else data
        return self

    def with_stderr(self, data: str | bytes) -> SubprocessMockBuilder:
        self._stderr = data.encode() if isinstance(data, str) else data
        return self

    def build(self) -> AsyncMock:
        """Build a mock for asyncio.create_subprocess_exec."""
        mock_proc = AsyncMock()
        mock_proc.returncode = self._returncode
        mock_proc.communicate = AsyncMock(return_value=(self._stdout, self._stderr))
        mock_proc.wait = AsyncMock(return_value=self._returncode)

        mock_create = AsyncMock(return_value=mock_proc)
        return mock_create


# --- Review Mock Builder ---


class ReviewMockBuilder:
    """Fluent builder for _review_prs test mocks."""

    def __init__(self, orch: HydraFlowOrchestrator, config: HydraFlowConfig) -> None:
        self._orch = orch
        self._config = config
        self._verdict: ReviewVerdict | None = None
        self._review_result: ReviewResult | None = None
        self._review_side_effect: Any = None
        self._merge_return: bool = True
        self._diff_text: str = "diff text"
        self._issue_number: int = 42
        self._pr_methods: dict[str, Any] = {}

    def with_verdict(self, verdict: ReviewVerdict) -> ReviewMockBuilder:
        self._verdict = verdict
        return self

    def with_review_result(self, result: ReviewResult) -> ReviewMockBuilder:
        self._review_result = result
        return self

    def with_review_side_effect(self, side_effect: Any) -> ReviewMockBuilder:
        self._review_side_effect = side_effect
        return self

    def with_merge_return(self, value: bool) -> ReviewMockBuilder:
        self._merge_return = value
        return self

    def with_issue_number(self, number: int) -> ReviewMockBuilder:
        self._issue_number = number
        return self

    def with_pr_method(self, name: str, mock: Any) -> ReviewMockBuilder:
        """Override a specific mock_prs method."""
        self._pr_methods[name] = mock
        return self

    def build(self) -> tuple[AsyncMock, AsyncMock, AsyncMock]:
        """Wire mocks into orch and return (mock_reviewers, mock_prs, mock_wt)."""
        from models import ReviewResult as RR
        from models import ReviewVerdict as RV

        # Reviewer mock
        mock_reviewers = AsyncMock()
        if self._review_side_effect:
            mock_reviewers.review = self._review_side_effect
        else:
            verdict = self._verdict if self._verdict is not None else RV.APPROVE
            result = self._review_result or RR(
                pr_number=101,
                issue_number=self._issue_number,
                verdict=verdict,
                summary="Looks good.",
                fixes_made=False,
            )
            mock_reviewers.review = AsyncMock(return_value=result)
        self._orch._svc.reviewers = mock_reviewers

        # PR manager mock
        mock_prs = AsyncMock()
        mock_prs.get_pr_diff = AsyncMock(return_value=self._diff_text)
        mock_prs.push_branch = AsyncMock(return_value=True)
        mock_prs.merge_pr = AsyncMock(return_value=self._merge_return)
        mock_prs.remove_label = AsyncMock()
        mock_prs.add_labels = AsyncMock()
        mock_prs.post_pr_comment = AsyncMock()
        mock_prs.submit_review = AsyncMock(return_value=True)
        mock_prs.pull_main = AsyncMock()
        for name, mock in self._pr_methods.items():
            setattr(mock_prs, name, mock)
        self._orch._svc.prs = mock_prs

        # Worktree mock
        mock_wt = AsyncMock()
        mock_wt.destroy = AsyncMock()
        self._orch._svc.worktrees = mock_wt

        # Create worktree directory
        wt = self._config.worktree_base / f"issue-{self._issue_number}"
        wt.mkdir(parents=True, exist_ok=True)

        return mock_reviewers, mock_prs, mock_wt
