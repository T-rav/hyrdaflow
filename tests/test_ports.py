"""Structural conformance tests for hexagonal port interfaces.

These tests assert that the concrete infrastructure adapters satisfy their
respective port protocols via runtime_checkable isinstance checks AND via
inspect.signature comparison.

isinstance() with runtime_checkable only verifies that methods *exist* on the
class — it does NOT verify that parameter names, types, or counts match.
The signature tests in TestPRPortSignatures / TestWorkspacePortSignatures catch
those mismatches before they cause runtime errors.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ports import IssueFetcherPort, IssueStorePort, PRPort, WorkspacePort

# ---------------------------------------------------------------------------
# PRPort
# ---------------------------------------------------------------------------


class TestPortsModuleDocstring:
    """The ports.py module docstring must reference the correct protocol names."""

    def test_no_task_source_reference(self) -> None:
        """The removed TaskSource protocol must not appear in the docstring."""
        import ports

        assert "TaskSource" not in (ports.__doc__ or ""), (
            "ports.py docstring still references the removed TaskSource protocol"
        )

    def test_task_fetcher_transitioner_in_docstring(self) -> None:
        """The diagram must reference TaskFetcher / TaskTransitioner."""
        import ports

        assert "TaskFetcher / TaskTransitioner" in (ports.__doc__ or ""), (
            "ports.py docstring is missing TaskFetcher / TaskTransitioner"
        )


class TestPRPortConformance:
    """PRManager must satisfy the PRPort protocol."""

    def test_pr_manager_satisfies_pr_port(self) -> None:
        """PRManager is a structural subtype of PRPort."""
        from pr_manager import PRManager

        # Build minimal PRManager without hitting GitHub
        config = MagicMock()
        config.repo = "org/repo"
        config.gh_token = None
        config.dry_run = False
        event_bus = MagicMock()

        mgr = PRManager(config, event_bus)
        assert isinstance(mgr, PRPort), (
            "PRManager no longer satisfies the PRPort protocol. "
            "Check that all methods declared in PRPort exist on PRManager."
        )

    def test_async_mock_satisfies_pr_port(self) -> None:
        """An AsyncMock spec'd to PRPort is accepted as PRPort (test helper check)."""
        mock: PRPort = AsyncMock(spec=PRPort)  # type: ignore[assignment]
        assert isinstance(mock, PRPort)


# ---------------------------------------------------------------------------
# WorkspacePort
# ---------------------------------------------------------------------------


class TestWorkspacePortConformance:
    """WorkspaceManager must satisfy the WorkspacePort protocol."""

    def test_worktree_manager_satisfies_worktree_port(self) -> None:
        """WorkspaceManager is a structural subtype of WorkspacePort."""
        from workspace import WorkspaceManager

        config = MagicMock()
        config.worktree_base = Path("/tmp/wt")
        config.repo_root = Path("/tmp/repo")
        config.main_branch = "main"
        config.git_command_timeout = 30

        mgr = WorkspaceManager(config)
        assert isinstance(mgr, WorkspacePort), (
            "WorkspaceManager no longer satisfies the WorkspacePort protocol. "
            "Check that all methods declared in WorkspacePort exist on WorkspaceManager."
        )

    def test_async_mock_satisfies_worktree_port(self) -> None:
        """An AsyncMock spec'd to WorkspacePort is accepted as WorkspacePort."""
        mock: WorkspacePort = AsyncMock(spec=WorkspacePort)  # type: ignore[assignment]
        assert isinstance(mock, WorkspacePort)


# ---------------------------------------------------------------------------
# Port method coverage
# ---------------------------------------------------------------------------


class TestPRPortMethods:
    """All methods declared in PRPort exist on the concrete PRManager."""

    _REQUIRED_METHODS = [
        "push_branch",
        "create_pr",
        "merge_pr",
        "get_pr_diff",
        "wait_for_ci",
        "add_labels",
        "remove_label",
        "swap_pipeline_labels",
        "post_comment",
        "submit_review",
        "fetch_ci_failure_logs",
        "fetch_code_scanning_alerts",
        "close_issue",
        "create_issue",
        "list_hitl_items",
        "find_open_pr_for_branch",
        "branch_has_diff_from_main",
        "expected_pr_title",
        "update_pr_title",
        "get_pr_diff_names",
        "get_pr_approvers",
        "get_pr_head_sha",
        "get_pr_mergeable",
        "post_pr_comment",
        "list_issues_by_label",
        "get_issue_state",
        "get_issue_updated_at",
        "update_issue_body",
        "get_latest_ci_status",
        "get_dependabot_alerts",
        "pull_main",
        "upload_screenshot",
    ]

    @pytest.mark.parametrize("method", _REQUIRED_METHODS)
    def test_method_exists_on_pr_manager(self, method: str) -> None:
        from pr_manager import PRManager

        assert hasattr(PRManager, method), (
            f"PRManager is missing '{method}' which is declared in PRPort"
        )


class TestWorkspacePortMethods:
    """All methods declared in WorkspacePort exist on the concrete WorkspaceManager."""

    _REQUIRED_METHODS = [
        "create",
        "destroy",
        "destroy_all",
        "merge_main",
        "get_conflicting_files",
        "reset_to_main",
        "post_work_cleanup",
        "abort_merge",
        "start_merge_main",
    ]

    @pytest.mark.parametrize("method", _REQUIRED_METHODS)
    def test_method_exists_on_worktree_manager(self, method: str) -> None:
        from workspace import WorkspaceManager

        assert hasattr(WorkspaceManager, method), (
            f"WorkspaceManager is missing '{method}' which is declared in WorkspacePort"
        )


# ---------------------------------------------------------------------------
# Signature validation — isinstance() is not enough
# ---------------------------------------------------------------------------
#
# runtime_checkable isinstance() only checks that methods exist, NOT that their
# parameter names / counts / types match.  These tests compare
# inspect.signature() between the port and the concrete implementation so that
# signature drift is caught before it causes runtime errors.


def _port_params(port_cls: type, method: str) -> dict[str, inspect.Parameter]:
    """Return the non-self parameters of *method* on *port_cls*."""
    sig = inspect.signature(getattr(port_cls, method))
    return {k: v for k, v in sig.parameters.items() if k != "self"}


def _impl_params(impl_cls: type, method: str) -> dict[str, inspect.Parameter]:
    """Return the non-self parameters of *method* on *impl_cls*."""
    sig = inspect.signature(getattr(impl_cls, method))
    return {k: v for k, v in sig.parameters.items() if k != "self"}


def _assert_param_names_match(port_cls: type, impl_cls: type, method: str) -> None:
    """Raise AssertionError if parameter names differ between port and impl."""
    port_p = _port_params(port_cls, method)
    impl_p = _impl_params(impl_cls, method)
    assert set(port_p) == set(impl_p), (
        f"{impl_cls.__name__}.{method} parameter mismatch with {port_cls.__name__}.\n"
        f"  Port params:  {list(port_p)}\n"
        f"  Impl params:  {list(impl_p)}\n"
        f"Update ports.py to match the concrete implementation."
    )


class TestPRPortSignatures:
    """PRPort method signatures must exactly match PRManager's implementations."""

    _SIGNED_METHODS = [
        "push_branch",
        "create_pr",
        "merge_pr",
        "get_pr_diff",
        "wait_for_ci",
        "add_labels",
        "remove_label",
        "swap_pipeline_labels",
        "post_comment",
        "submit_review",
        "fetch_ci_failure_logs",
        "fetch_code_scanning_alerts",
        "close_issue",
        "create_issue",
        "list_hitl_items",
        "find_open_pr_for_branch",
        "branch_has_diff_from_main",
        "expected_pr_title",
        "update_pr_title",
        "get_pr_diff_names",
        "get_pr_approvers",
        "get_pr_head_sha",
        "get_pr_mergeable",
        "post_pr_comment",
        "list_issues_by_label",
        "get_issue_state",
        "get_issue_updated_at",
        "update_issue_body",
        "get_latest_ci_status",
        "get_dependabot_alerts",
        "pull_main",
        "upload_screenshot",
    ]

    @pytest.mark.parametrize("method", _SIGNED_METHODS)
    def test_signature_matches_pr_manager(self, method: str) -> None:
        from pr_manager import PRManager

        result = _assert_param_names_match(PRPort, PRManager, method)
        assert result is None  # raises AssertionError on mismatch


class TestWorkspacePortSignatures:
    """WorkspacePort method signatures must exactly match WorkspaceManager's."""

    _SIGNED_METHODS = [
        "create",
        "destroy",
        "destroy_all",
        "merge_main",
        "get_conflicting_files",
        "reset_to_main",
        "post_work_cleanup",
        "abort_merge",
        "start_merge_main",
    ]

    @pytest.mark.parametrize("method", _SIGNED_METHODS)
    def test_signature_matches_worktree_manager(self, method: str) -> None:
        from workspace import WorkspaceManager

        result = _assert_param_names_match(WorkspacePort, WorkspaceManager, method)
        assert result is None  # raises AssertionError on mismatch


# ---------------------------------------------------------------------------
# IssueStorePort
# ---------------------------------------------------------------------------


class TestIssueStorePortConformance:
    """IssueStore must satisfy the IssueStorePort protocol."""

    def test_issue_store_satisfies_port(self) -> None:
        """IssueStore is a structural subtype of IssueStorePort."""
        from events import EventBus
        from issue_store import IssueStore
        from task_source import TaskFetcher

        config = MagicMock()
        config.data_poll_interval = 30
        config.find_label = ["hydraflow-find"]
        config.planner_label = ["hydraflow-plan"]
        config.ready_label = ["hydraflow-ready"]
        config.review_label = ["hydraflow-review"]
        config.hitl_label = ["hydraflow-hitl"]
        config.hitl_active_label = ["hydraflow-hitl-active"]
        config.epic_child_label = []

        fetcher = AsyncMock(spec=TaskFetcher)
        bus = EventBus()

        store = IssueStore(config, fetcher, bus)
        assert isinstance(store, IssueStorePort), (
            "IssueStore no longer satisfies the IssueStorePort protocol. "
            "Check that all methods declared in IssueStorePort exist on IssueStore."
        )

    def test_async_mock_satisfies_issue_store_port(self) -> None:
        """An AsyncMock spec'd to IssueStorePort is accepted."""
        mock: IssueStorePort = AsyncMock(spec=IssueStorePort)  # type: ignore[assignment]
        assert isinstance(mock, IssueStorePort)


class TestIssueStorePortMethods:
    """All methods declared in IssueStorePort exist on IssueStore."""

    _REQUIRED_METHODS = [
        "get_triageable",
        "get_plannable",
        "get_implementable",
        "get_reviewable",
        "enqueue_transition",
        "mark_active",
        "mark_complete",
        "mark_merged",
        "release_in_flight",
        "is_active",
        "enrich_with_comments",
    ]

    @pytest.mark.parametrize("method", _REQUIRED_METHODS)
    def test_method_exists_on_issue_store(self, method: str) -> None:
        from issue_store import IssueStore

        assert hasattr(IssueStore, method), (
            f"IssueStore is missing '{method}' which is declared in IssueStorePort"
        )


class TestIssueStorePortSignatures:
    """IssueStorePort method signatures must match IssueStore's implementations."""

    _SIGNED_METHODS = [
        "get_triageable",
        "get_plannable",
        "get_implementable",
        "get_reviewable",
        "enqueue_transition",
        "mark_active",
        "mark_complete",
        "mark_merged",
        "release_in_flight",
        "is_active",
        "enrich_with_comments",
    ]

    @pytest.mark.parametrize("method", _SIGNED_METHODS)
    def test_signature_matches_issue_store(self, method: str) -> None:
        from issue_store import IssueStore

        result = _assert_param_names_match(IssueStorePort, IssueStore, method)
        assert result is None


# ---------------------------------------------------------------------------
# IssueFetcherPort
# ---------------------------------------------------------------------------


class TestIssueFetcherPortConformance:
    """IssueFetcher must satisfy the IssueFetcherPort protocol."""

    def test_issue_fetcher_satisfies_port(self) -> None:
        """IssueFetcher is a structural subtype of IssueFetcherPort."""
        from issue_fetcher import IssueFetcher

        config = MagicMock()
        config.repo = "org/repo"
        config.gh_token = None
        config.dry_run = False
        config.data_poll_interval = 30
        config.collaborator_cache_ttl = 600
        config.collaborator_check_enabled = False

        fetcher = IssueFetcher(config)
        assert isinstance(fetcher, IssueFetcherPort), (
            "IssueFetcher no longer satisfies the IssueFetcherPort protocol. "
            "Check that all methods declared in IssueFetcherPort exist on IssueFetcher."
        )

    def test_async_mock_satisfies_issue_fetcher_port(self) -> None:
        """An AsyncMock spec'd to IssueFetcherPort is accepted."""
        mock: IssueFetcherPort = AsyncMock(spec=IssueFetcherPort)  # type: ignore[assignment]
        assert isinstance(mock, IssueFetcherPort)


class TestIssueFetcherPortMethods:
    """All methods declared in IssueFetcherPort exist on IssueFetcher."""

    _REQUIRED_METHODS = [
        "fetch_issue_by_number",
        "fetch_issues_by_labels",
    ]

    @pytest.mark.parametrize("method", _REQUIRED_METHODS)
    def test_method_exists_on_issue_fetcher(self, method: str) -> None:
        from issue_fetcher import IssueFetcher

        assert hasattr(IssueFetcher, method), (
            f"IssueFetcher is missing '{method}' which is declared in IssueFetcherPort"
        )


class TestIssueFetcherPortSignatures:
    """IssueFetcherPort method signatures must match IssueFetcher's implementations."""

    _SIGNED_METHODS = [
        "fetch_issue_by_number",
        "fetch_issues_by_labels",
    ]

    @pytest.mark.parametrize("method", _SIGNED_METHODS)
    def test_signature_matches_issue_fetcher(self, method: str) -> None:
        from issue_fetcher import IssueFetcher

        result = _assert_param_names_match(IssueFetcherPort, IssueFetcher, method)
        assert result is None
