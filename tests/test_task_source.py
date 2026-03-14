"""Tests for task_source protocol conformance and concrete implementations.

Covers:
- Runtime-checkable protocol conformance for TaskFetcher and TaskTransitioner
- Signature matching between protocols and concrete implementations
- Functional delegation tests for GitHubTaskFetcher.fetch_all
- Functional delegation tests for PRManager.transition, close_task, create_task
"""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest

from task_source import TaskFetcher, TaskTransitioner

# ---------------------------------------------------------------------------
# Stub implementations for protocol runtime-checkable tests
# ---------------------------------------------------------------------------


class _FetcherImpl:
    async def fetch_all(self):
        return []


class _TransitionerImpl:
    async def transition(
        self, issue_number: int, new_stage: str, *, pr_number: int | None = None
    ) -> None:
        return None

    async def post_comment(self, issue_number: int, body: str) -> None:
        return None

    async def close_task(self, issue_number: int) -> None:
        return None

    async def create_task(
        self, title: str, body: str, labels: list[str] | None = None
    ) -> int:
        return 1


# ---------------------------------------------------------------------------
# Protocol runtime-checkable tests
# ---------------------------------------------------------------------------


def test_task_source_protocols_are_runtime_checkable() -> None:
    assert isinstance(_FetcherImpl(), TaskFetcher)
    assert isinstance(_TransitionerImpl(), TaskTransitioner)


# ---------------------------------------------------------------------------
# GitHubTaskFetcher conformance
# ---------------------------------------------------------------------------


class TestGitHubTaskFetcherConformance:
    """GitHubTaskFetcher must satisfy the TaskFetcher protocol."""

    def test_isinstance_conforms_to_task_fetcher(self) -> None:
        """GitHubTaskFetcher passes isinstance(fetcher, TaskFetcher)."""
        from issue_fetcher import GitHubTaskFetcher

        fetcher = GitHubTaskFetcher(MagicMock())
        assert isinstance(fetcher, TaskFetcher)

    def test_fetch_all_signature_matches_protocol(self) -> None:
        """fetch_all parameter names must match the protocol definition."""
        from issue_fetcher import GitHubTaskFetcher

        proto_sig = inspect.signature(TaskFetcher.fetch_all)
        impl_sig = inspect.signature(GitHubTaskFetcher.fetch_all)

        proto_params = {k for k in proto_sig.parameters if k != "self"}
        impl_params = {k for k in impl_sig.parameters if k != "self"}
        assert proto_params == impl_params, (
            f"fetch_all signature mismatch: protocol={proto_params}, impl={impl_params}"
        )


# ---------------------------------------------------------------------------
# GitHubTaskFetcher functional tests
# ---------------------------------------------------------------------------


class TestGitHubTaskFetcherFunctional:
    """GitHubTaskFetcher.fetch_all delegates to IssueFetcher and converts results."""

    @pytest.mark.asyncio
    async def test_fetch_all_delegates_and_converts_to_tasks(self) -> None:
        """fetch_all calls fetch_all_hydraflow_issues and converts via to_task()."""
        from issue_fetcher import GitHubTaskFetcher

        mock_issue = MagicMock()
        mock_task = MagicMock()
        mock_issue.to_task.return_value = mock_task

        inner_fetcher = MagicMock()
        inner_fetcher.fetch_all_hydraflow_issues = AsyncMock(return_value=[mock_issue])

        fetcher = GitHubTaskFetcher(inner_fetcher)
        result = await fetcher.fetch_all()

        inner_fetcher.fetch_all_hydraflow_issues.assert_awaited_once()
        mock_issue.to_task.assert_called_once()
        assert result == [mock_task]

    @pytest.mark.asyncio
    async def test_fetch_all_returns_empty_when_no_issues(self) -> None:
        """fetch_all returns [] when no issues exist."""
        from issue_fetcher import GitHubTaskFetcher

        inner_fetcher = MagicMock()
        inner_fetcher.fetch_all_hydraflow_issues = AsyncMock(return_value=[])

        fetcher = GitHubTaskFetcher(inner_fetcher)
        result = await fetcher.fetch_all()

        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_all_converts_multiple_issues(self) -> None:
        """fetch_all converts each issue to a Task via to_task()."""
        from issue_fetcher import GitHubTaskFetcher

        issues = []
        expected_tasks = []
        for _i in range(3):
            mock_issue = MagicMock()
            mock_task = MagicMock()
            mock_issue.to_task.return_value = mock_task
            issues.append(mock_issue)
            expected_tasks.append(mock_task)

        inner_fetcher = MagicMock()
        inner_fetcher.fetch_all_hydraflow_issues = AsyncMock(return_value=issues)

        fetcher = GitHubTaskFetcher(inner_fetcher)
        result = await fetcher.fetch_all()

        assert len(result) == 3
        assert result == expected_tasks
        for issue in issues:
            issue.to_task.assert_called_once()


# ---------------------------------------------------------------------------
# PRManager TaskTransitioner conformance
# ---------------------------------------------------------------------------


class TestPRManagerTransitionerConformance:
    """PRManager must satisfy the TaskTransitioner protocol."""

    def _make_pr_manager(self) -> object:
        from pr_manager import PRManager

        config = MagicMock()
        config.repo = "org/repo"
        config.gh_token = None
        config.dry_run = False
        event_bus = MagicMock()
        return PRManager(config, event_bus)

    def test_isinstance_conforms_to_task_transitioner(self) -> None:
        """PRManager passes isinstance(mgr, TaskTransitioner)."""
        mgr = self._make_pr_manager()
        assert isinstance(mgr, TaskTransitioner)

    _TRANSITIONER_METHODS = ["transition", "post_comment", "close_task", "create_task"]

    @pytest.mark.parametrize("method", _TRANSITIONER_METHODS)
    def test_signature_matches_protocol(self, method: str) -> None:
        """Parameter names of each method must match the protocol definition."""
        from pr_manager import PRManager

        proto_sig = inspect.signature(getattr(TaskTransitioner, method))
        impl_sig = inspect.signature(getattr(PRManager, method))

        proto_params = {k for k in proto_sig.parameters if k != "self"}
        impl_params = {k for k in impl_sig.parameters if k != "self"}
        assert proto_params == impl_params, (
            f"{method} signature mismatch: protocol={proto_params}, impl={impl_params}"
        )


# ---------------------------------------------------------------------------
# PRManager TaskTransitioner functional delegation tests
# ---------------------------------------------------------------------------


class TestPRManagerTransitionerDelegation:
    """PRManager.transition/close_task/create_task delegate to underlying methods."""

    def _make_pr_manager(self) -> object:
        from pr_manager import PRManager

        config = MagicMock()
        config.repo = "org/repo"
        config.gh_token = None
        config.dry_run = False
        config.find_label = ["hydraflow-find"]
        config.planner_label = ["hydraflow-plan"]
        config.ready_label = ["hydraflow-ready"]
        config.review_label = ["hydraflow-review"]
        config.hitl_label = ["hydraflow-hitl"]
        event_bus = MagicMock()
        return PRManager(config, event_bus)

    @pytest.mark.asyncio
    async def test_transition_delegates_to_swap_pipeline_labels(self) -> None:
        """transition() calls swap_pipeline_labels with the correct label."""
        mgr = self._make_pr_manager()
        mgr.swap_pipeline_labels = AsyncMock()  # type: ignore[attr-defined]

        await mgr.transition(42, "ready", pr_number=7)  # type: ignore[union-attr]

        mgr.swap_pipeline_labels.assert_awaited_once_with(  # type: ignore[attr-defined]
            42, "hydraflow-ready", pr_number=7
        )

    @pytest.mark.asyncio
    async def test_transition_uses_plan_label(self) -> None:
        """transition('plan') resolves to the planner_label config value."""
        mgr = self._make_pr_manager()
        mgr.swap_pipeline_labels = AsyncMock()  # type: ignore[attr-defined]

        await mgr.transition(10, "plan")  # type: ignore[union-attr]

        mgr.swap_pipeline_labels.assert_awaited_once_with(  # type: ignore[attr-defined]
            10, "hydraflow-plan", pr_number=None
        )

    @pytest.mark.asyncio
    async def test_close_task_delegates_to_close_issue(self) -> None:
        """close_task() calls close_issue with the issue number."""
        mgr = self._make_pr_manager()
        mgr.close_issue = AsyncMock()  # type: ignore[attr-defined]

        await mgr.close_task(99)  # type: ignore[union-attr]

        mgr.close_issue.assert_awaited_once_with(99)  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_create_task_delegates_to_create_issue(self) -> None:
        """create_task() calls create_issue and returns its result."""
        mgr = self._make_pr_manager()
        mgr.create_issue = AsyncMock(return_value=123)  # type: ignore[attr-defined]

        result = await mgr.create_task("title", "body", labels=["bug"])  # type: ignore[union-attr]

        mgr.create_issue.assert_awaited_once_with("title", "body", ["bug"])  # type: ignore[attr-defined]
        assert result == 123

    @pytest.mark.asyncio
    async def test_create_task_without_labels(self) -> None:
        """create_task() passes None labels through to create_issue."""
        mgr = self._make_pr_manager()
        mgr.create_issue = AsyncMock(return_value=456)  # type: ignore[attr-defined]

        result = await mgr.create_task("t", "b")  # type: ignore[union-attr]

        mgr.create_issue.assert_awaited_once_with("t", "b", None)  # type: ignore[attr-defined]
        assert result == 456
