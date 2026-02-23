"""Shared fixtures and factories for HydraFlow tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure hydraflow package is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.helpers import ConfigFactory  # noqa: E402

if TYPE_CHECKING:
    from typing import Any

    from ci_scaffold import CIScaffoldResult
    from config import HydraFlowConfig
    from events import HydraFlowEvent
    from lint_scaffold import LintScaffoldResult
    from models import (
        AnalysisResult,
        GitHubIssue,
        HITLResult,
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


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Set minimal env vars and prevent real subprocess calls."""
    test_env = {
        "HOME": "/tmp/hydraflow-test",
        "GH_TOKEN": "test-token",
    }
    with patch.dict(os.environ, test_env, clear=False):
        yield


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


# --- Worker Result Factory ---


class WorkerResultFactory:
    """Factory for WorkerResult instances."""

    @staticmethod
    def create(
        *,
        issue_number: int = 42,
        branch: str = "agent/issue-42",
        success: bool = True,
        transcript: str = "Implemented the feature.",
        commits: int = 1,
        worktree_path: str = "/tmp/worktrees/issue-42",
    ):
        from models import WorkerResult

        return WorkerResult(
            issue_number=issue_number,
            branch=branch,
            success=success,
            transcript=transcript,
            commits=commits,
            worktree_path=worktree_path,
        )


@pytest.fixture
def worker_result() -> WorkerResult:
    return WorkerResultFactory.create()


# --- Plan Result Factory ---


class PlanResultFactory:
    """Factory for PlanResult instances."""

    @staticmethod
    def create(
        *,
        issue_number: int = 42,
        success: bool = True,
        plan: str = "## Plan\n\n1. Do the thing\n2. Test the thing",
        summary: str = "Plan to implement the feature",
        error: str | None = None,
        transcript: str = "PLAN_START\n## Plan\n\n1. Do the thing\nPLAN_END\nSUMMARY: Plan to implement the feature",
        duration_seconds: float = 10.0,
    ):
        from models import PlanResult

        return PlanResult(
            issue_number=issue_number,
            success=success,
            plan=plan,
            summary=summary,
            error=error,
            transcript=transcript,
            duration_seconds=duration_seconds,
        )


@pytest.fixture
def plan_result() -> PlanResult:
    return PlanResultFactory.create()


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


@pytest.fixture
def pr_info() -> PRInfo:
    return PRInfoFactory.create()


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
            type=type if type is not None else ET.BATCH_START,
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


# --- HITL Runner Fixture ---


@pytest.fixture
def hitl_runner(config, event_bus):
    from hitl_runner import HITLRunner

    return HITLRunner(config, event_bus)


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
    orch.stop = AsyncMock()
    orch.request_stop = AsyncMock()
    return orch


@pytest.fixture
def orchestrator_mock():
    return make_orchestrator_mock()


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


@pytest.fixture
def subprocess_mock() -> SubprocessMockBuilder:
    """Return a builder for subprocess mocks."""
    return SubprocessMockBuilder()


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
