"""Shared fixtures and factories for HydraFlow tests."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ADR-0052: Sandbox-tier scenarios run only inside the docker-compose stack
# (`docker-compose.sandbox.yml`). They use their own pytest.ini with a
# hard-coded `--confcutdir=/work/tests/sandbox_scenarios` that resolves only
# inside the playwright container. Skipping them at collection time here keeps
# host-side `pytest tests/` and `make quality` green; CI runs them via the
# dedicated `sandbox` job (`scripts/sandbox_scenario.py`).
collect_ignore_glob = ["sandbox_scenarios/*"]


def pytest_runtest_teardown(item: pytest.Item, nextitem: pytest.Item | None) -> None:  # noqa: ARG001 — nextitem required by pytest hook signature
    """Fail any test that leaves a ``MagicMock/`` directory in the repo root.

    Caused by passing a bare ``MagicMock()`` where production code expects a
    ``Path`` / config and calls ``.mkdir()`` on the result — the str() of the
    mock becomes the first path segment (``MagicMock``), subsequent
    attribute-access calls become further segments (``mock.data_path()``),
    and the real filesystem picks them up. The dirs then get swept into
    commits accidentally.

    Fail fast so the offending test is immediately obvious. The remediation
    is usually ``MagicMock(spec=HydraFlowConfig)`` or a real
    ``tmp_path``-backed config (see ``ConfigFactory``).
    """
    root = Path(item.config.rootpath)
    polluted = root / "MagicMock"
    if polluted.exists():
        shutil.rmtree(polluted, ignore_errors=True)
        pytest.fail(
            f"Mock-path pollution: test {item.nodeid} left {polluted} on disk. "
            "A MagicMock was used where a Path/config was expected. "
            "Use `MagicMock(spec=HydraFlowConfig)` or a real tmp_path-backed config."
        )


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
def _reset_otel_tracer_provider():
    """Reset the OTel global tracer-provider state between tests.

    ``trace.set_tracer_provider`` is guarded by a ``Once`` object that
    prevents re-assignment after the first call.  Tests that install an
    ``InMemorySpanExporter`` need a fresh provider each run; this fixture
    resets both the provider reference and the ``Once._done`` flag so that
    each test starts from a clean slate.

    This directly mutates private OTel internals — the same coupling
    trade-off accepted for ``_reset_gh_semaphore``.
    """
    from opentelemetry import trace as _trace
    from src.telemetry.spans import _get_tracer

    yield
    # Teardown: undo whatever the test installed and clear our tracer cache
    # so the next test resolves Tracer instances against its fresh provider.
    _trace._TRACER_PROVIDER = None  # noqa: SLF001
    _trace._TRACER_PROVIDER_SET_ONCE._done = False  # noqa: SLF001
    _get_tracer.cache_clear()


@pytest.fixture(autouse=True)
def _disable_hitl_summary_autowarm(config) -> None:
    """Keep route tests deterministic unless a test explicitly opts in."""
    config.transcript_summarization_enabled = False


# --- Config Fixtures ---


@pytest.fixture
def config(tmp_path: Path) -> HydraFlowConfig:
    return ConfigFactory.create(
        repo_root=tmp_path / "repo",
        workspace_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )


@pytest.fixture
def dry_config(tmp_path: Path) -> HydraFlowConfig:
    return ConfigFactory.create(
        dry_run=True,
        repo_root=tmp_path / "repo",
        workspace_base=tmp_path / "worktrees",
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
        author: str | None = None,
        state: GitHubIssueState | None = None,
        milestone_number: int | None = None,
        created_at: str | None = None,
    ):
        from models import GitHubIssue  # noqa: F811

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
        if author is not None:
            kwargs["author"] = author
        if state is not None:
            kwargs["state"] = state
        if milestone_number is not None:
            kwargs["milestone_number"] = milestone_number
        if created_at is not None:
            kwargs["created_at"] = created_at
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
        created_at: str = "",
        metadata: dict[str, Any] | None = None,
        parent_epic: int | None = None,
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
            created_at=created_at,
            metadata=metadata if metadata is not None else {},
            parent_epic=parent_epic,
        )


# --- Worker Result Factory ---
#
# WorkerResultFactory, PlanResultFactory, PRInfoFactory, ReviewResultFactory,
# and TriageResultFactory now live in src/mockworld/fakes/_factories.py
# (re-exported below for back-compat) so that the Fakes (FakeGitHub, FakeLLM)
# can import them without a ``src→tests`` dependency. PR B's docker container
# does not COPY tests/, so any ``from tests.conftest`` import in src/ would
# fail at module load.
# noqa: F401 — these names are re-exported for back-compat. Many tests
# import directly via ``from tests.conftest import PRInfoFactory`` etc.;
# removing the names here would break them. The ``E402`` noqa is because
# this import follows session-scoped fixture definitions, which is
# intentional in this file.
from mockworld.fakes._factories import (  # noqa: E402, F401
    PlanResultFactory,
    PRInfoFactory,
    ReviewResultFactory,
    TriageResultFactory,
    WorkerResultFactory,
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

    def with_workspace_path(self, value: str) -> WorkerResultBuilder:
        self._kwargs["workspace_path"] = value
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
# (PlanResultFactory now lives in src/mockworld/fakes/_factories.py;
# the import above re-exports it under this module's namespace.)


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
# (PRInfoFactory now lives in src/mockworld/fakes/_factories.py;
# the import above re-exports it under this module's namespace.)


# --- Review Result Factory ---
# (ReviewResultFactory now lives in src/mockworld/fakes/_factories.py;
# the import above re-exports it under this module's namespace.)


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

    def with_commit_stat(self, value: str) -> ReviewResultBuilder:
        self._kwargs["commit_stat"] = value
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

    def with_files_changed(self, value: list[str]) -> ReviewResultBuilder:
        self._kwargs["files_changed"] = value
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
# (TriageResultFactory now lives in src/mockworld/fakes/_factories.py;
# the import above re-exports it under this module's namespace.)


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
    orch = MagicMock()
    orch.human_input_requests = requests if requests is not None else {}
    orch.provide_human_input = MagicMock()
    orch.running = running
    orch.run_status = run_status
    orch.current_session_id = None
    orch.credits_paused_until = None
    orch.stop = AsyncMock()
    orch.request_stop = AsyncMock()
    orch.is_bg_worker_enabled = MagicMock(return_value=running)
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
        from models import ReviewVerdict as RV

        # Reviewer mock
        mock_reviewers = AsyncMock()
        if self._review_side_effect:
            mock_reviewers.review = self._review_side_effect
        else:
            verdict = self._verdict if self._verdict is not None else RV.APPROVE
            result = self._review_result or ReviewResultFactory.create(
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
        self._orch._svc.workspaces = mock_wt

        # Create worktree directory
        wt = self._config.workspace_base / f"issue-{self._issue_number}"
        wt.mkdir(parents=True, exist_ok=True)

        return mock_reviewers, mock_prs, mock_wt


def write_plugin_skill(
    cache_root: Path,
    marketplace: str,
    plugin: str,
    skill: str,
    *,
    name: str | None = None,
    description: str | None = None,
    frontmatter: str | None = None,
    version: str = "1.0.0",
) -> Path:
    """Create a SKILL.md under the real cache layout and return its path.

    Layout: ``<cache_root>/<marketplace>/<plugin>/<version>/skills/<skill>/SKILL.md``.
    Shared helper used by plugin-skill-registry and preflight-plugins tests.
    """
    skill_dir = cache_root / marketplace / plugin / version / "skills" / skill
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_md = skill_dir / "SKILL.md"
    if frontmatter is not None:
        content = f"---\n{frontmatter}\n---\n\nBody here.\n"
    else:
        content = (
            "---\n"
            f"name: {name or skill}\n"
            f"description: {description or f'{skill} description'}\n"
            "---\n\nBody here.\n"
        )
    skill_md.write_text(content)
    return skill_md
