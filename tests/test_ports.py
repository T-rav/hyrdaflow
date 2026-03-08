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

from ports import PRPort, WorkspacePort

# ---------------------------------------------------------------------------
# PRPort
# ---------------------------------------------------------------------------


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
    ]

    @pytest.mark.parametrize("method", _SIGNED_METHODS)
    def test_signature_matches_pr_manager(self, method: str) -> None:
        from pr_manager import PRManager

        _assert_param_names_match(PRPort, PRManager, method)


class TestWorkspacePortSignatures:
    """WorkspacePort method signatures must exactly match WorkspaceManager's."""

    _SIGNED_METHODS = [
        "create",
        "destroy",
        "destroy_all",
        "merge_main",
        "get_conflicting_files",
    ]

    @pytest.mark.parametrize("method", _SIGNED_METHODS)
    def test_signature_matches_worktree_manager(self, method: str) -> None:
        from workspace import WorkspaceManager

        _assert_param_names_match(WorkspacePort, WorkspaceManager, method)
