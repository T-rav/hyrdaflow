"""Unit tests verifying WorkspaceManager port methods are decorated with @port_span.

The plan originally targeted a `run_git` method, but no such method exists on
`WorkspaceManager` or in the `WorkspacePort` Protocol. Instead we decorate the
two highest-traffic real port methods: `create` (workspace setup) and
`merge_main` (the merge path where docker-corruption gotchas live).
"""

from __future__ import annotations


def test_workspace_create_is_decorated():
    from src.workspace import WorkspaceManager

    method = getattr(WorkspaceManager, "create", None)
    assert method is not None, "WorkspaceManager has no create method"
    assert hasattr(method, "__wrapped__"), (
        "WorkspaceManager.create is not decorated with @port_span()"
    )


def test_workspace_merge_main_is_decorated():
    from src.workspace import WorkspaceManager

    method = getattr(WorkspaceManager, "merge_main", None)
    assert method is not None, "WorkspaceManager has no merge_main method"
    assert hasattr(method, "__wrapped__"), (
        "WorkspaceManager.merge_main is not decorated with @port_span()"
    )
