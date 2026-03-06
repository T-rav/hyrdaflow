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

from tests.helpers import ConfigFactory  # noqa: E402

if TYPE_CHECKING:
    from ci_scaffold import CIScaffoldResult
    from config import HydraFlowConfig
    from events import HydraFlowEvent
    from lint_scaffold import LintScaffoldResult
    from models import (
        AnalysisResult,
        GitHubIssue,
        HITLResult,
        NewIssueSpec,
        PRInfo,
        ReviewResult,
        ReviewVerdict,
        TriageResult,
    )
    from orchestrator import HydraFlowOrchestrator
    from state import StateTracker
    from test_scaffold import TestScaffoldResult


# --- Session-scoped environment setup ---


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Set minimal env vars and prevent real subprocess calls."""
    test_env = {
        "HOME": "/tmp/hydraflow-test",
        "GH_TOKEN": "test-token",
    }
    hydra_keys = {
        key: os.environ[key]
        for key in list(os.environ)
        if key.startswith(("HYDRAFLOW_", "HYDRA_"))
    }
    for key in hydra_keys:
        os.environ.pop(key, None)
    try:
        with patch.dict(os.environ, test_env, clear=False):
            yield
    finally:
        os.environ.update(hydra_keys)


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
        url: str = "",
    ):
        from models import GitHubIssue

        return GitHubIssue(
            number=number,
            title=title,
            body=body,
            labels=labels or ["ready"],
            comments=comments or [],
            url=url or f"https://github.com/test-org/test-repo/issues/{number}",
        )


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
        source_url: str = "",
        links: list[Any] | None = None,
    ):
        from models import Task

        return Task(
            id=id,
            title=title,
            body=body,
            tags=tags or ["ready"],
            comments=comments or [],
            source_url=source_url
            or f"https://github.com/test-org/test-repo/issues/{id}",
            links=links if links is not None else [],
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
        summary: str = "Looks good.",
        fixes_made: bool = False,
        transcript: str = "THOROUGH_REVIEW_COMPLETE",
        merged: bool = False,
        duration_seconds: float = 0.0,
        ci_passed: bool | None = None,
        ci_fix_attempts: int = 0,
    ) -> ReviewResult:
        from models import ReviewResult as RR
        from models import ReviewVerdict as RV

        return RR(
            pr_number=pr_number,
            issue_number=issue_number,
            verdict=verdict if verdict is not None else RV.APPROVE,
            summary=summary,
            fixes_made=fixes_made,
            transcript=transcript,
            merged=merged,
            duration_seconds=duration_seconds,
            ci_passed=ci_passed,
            ci_fix_attempts=ci_fix_attempts,
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
            timestamp=timestamp or "",
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
            reasons=reasons or [],
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
            verdict=verdict or AnalysisVerdict.PASS,
            details=details or [],
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
            created_dirs=created_dirs or [],
            created_files=created_files or [],
            modified_files=modified_files or [],
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


# --- Lint Scaffold Result Factory ---


class LintScaffoldResultFactory:
    """Factory for LintScaffoldResult instances."""

    @staticmethod
    def create(
        *,
        scaffolded: list[str] | None = None,
        skipped: list[str] | None = None,
        modified_files: list[str] | None = None,
        created_files: list[str] | None = None,
        language: str = "python",
    ) -> LintScaffoldResult:
        from lint_scaffold import LintScaffoldResult

        return LintScaffoldResult(
            scaffolded=scaffolded or [],
            skipped=skipped or [],
            modified_files=modified_files or [],
            created_files=created_files or [],
            language=language,
        )


# --- Orchestrator Mock ---


def make_orchestrator_mock(
    requests: dict | None = None,
    running: bool = False,
    run_status: str = "idle",
) -> MagicMock:
    """Return a minimal orchestrator mock."""
    orch = MagicMock()
    orch.human_input_requests = requests or {}
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
        self._orch._reviewers = mock_reviewers

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
        self._orch._prs = mock_prs

        # Worktree mock
        mock_wt = AsyncMock()
        mock_wt.destroy = AsyncMock()
        self._orch._worktrees = mock_wt

        # Create worktree directory
        wt = self._config.worktree_base / f"issue-{self._issue_number}"
        wt.mkdir(parents=True, exist_ok=True)

        return mock_reviewers, mock_prs, mock_wt
