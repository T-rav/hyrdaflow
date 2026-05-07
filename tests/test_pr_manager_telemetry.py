"""Unit tests verifying PRManager port methods emit @port_span."""

from __future__ import annotations


def test_pr_manager_create_pr_is_decorated():
    """Structural check — create_pr carries @port_span."""
    from src.pr_manager import PRManager

    method = getattr(PRManager, "create_pr", None)
    assert method is not None, "PRManager has no create_pr method"
    assert hasattr(method, "__wrapped__"), (
        f"{method.__qualname__} is not decorated with @port_span()"
    )


def test_pr_manager_merge_pr_is_decorated():
    """Structural check — merge_pr carries @port_span."""
    from src.pr_manager import PRManager

    method = getattr(PRManager, "merge_pr", None)
    if method is None:
        import pytest

        pytest.skip("PRManager has no merge_pr method")
    assert hasattr(method, "__wrapped__"), (
        f"{method.__qualname__} is not decorated with @port_span()"
    )


def test_pr_manager_create_issue_is_decorated():
    """Structural check — create_issue carries @port_span."""
    from src.pr_manager import PRManager

    method = getattr(PRManager, "create_issue", None)
    if method is None:
        import pytest

        pytest.skip("PRManager has no create_issue method")
    assert hasattr(method, "__wrapped__"), (
        f"{method.__qualname__} is not decorated with @port_span()"
    )


def test_pr_manager_push_branch_is_decorated():
    """Structural check — push_branch carries @port_span."""
    from src.pr_manager import PRManager

    method = getattr(PRManager, "push_branch", None)
    if method is None:
        import pytest

        pytest.skip("PRManager has no push_branch method")
    assert hasattr(method, "__wrapped__"), (
        f"{method.__qualname__} is not decorated with @port_span()"
    )
