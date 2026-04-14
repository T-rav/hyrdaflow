"""Central registrations for the 6 phase-1 background loops.

Each block mirrors the instantiation logic from ``mock_world._make_loop``.
Phase 2 expands this to 20 loops. Phase 1 keeps behavior identical — only
the wiring mechanism changes.

Importing this module is a side effect: decorators run, registry fills.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from tests.scenarios.catalog import LoopCatalog, register_loop


def _build_ci_monitor(ports: dict[str, Any], config: Any, deps: Any) -> Any:
    from ci_monitor_loop import CIMonitorLoop  # noqa: PLC0415

    return CIMonitorLoop(config=config, pr_manager=ports["github"], deps=deps)


def _build_stale_issue_gc(ports: dict[str, Any], config: Any, deps: Any) -> Any:
    from stale_issue_gc_loop import StaleIssueGCLoop  # noqa: PLC0415

    return StaleIssueGCLoop(config=config, pr_manager=ports["github"], deps=deps)


def _build_dependabot_merge(ports: dict[str, Any], config: Any, deps: Any) -> Any:
    from dependabot_merge_loop import DependabotMergeLoop  # noqa: PLC0415
    from models import DependabotMergeSettings  # noqa: PLC0415

    cache = ports.get("dependabot_cache")
    state = ports.get("dependabot_state")
    if cache is None:
        cache = MagicMock()
        cache.get_open_prs.return_value = []
        ports["dependabot_cache"] = cache
    if state is None:
        state = MagicMock()
        state.get_dependabot_merge_settings.return_value = DependabotMergeSettings()
        state.get_dependabot_merge_processed.return_value = set()
        ports["dependabot_state"] = state
    return DependabotMergeLoop(
        config=config,
        cache=cache,
        prs=ports["github"],
        state=state,
        deps=deps,
    )


def _build_pr_unsticker(ports: dict[str, Any], config: Any, deps: Any) -> Any:
    from pr_unsticker_loop import PRUnstickerLoop  # noqa: PLC0415

    unsticker = MagicMock()
    unsticker.unstick = AsyncMock(
        side_effect=lambda items: {"resolved": 0, "skipped": len(items)}
    )
    return PRUnstickerLoop(
        config=config,
        pr_unsticker=unsticker,
        prs=ports["github"],
        deps=deps,
    )


def _build_health_monitor(ports: dict[str, Any], config: Any, deps: Any) -> Any:
    from health_monitor_loop import HealthMonitorLoop  # noqa: PLC0415

    return HealthMonitorLoop(config=config, deps=deps, prs=ports["github"])


def _build_workspace_gc(ports: dict[str, Any], config: Any, deps: Any) -> Any:
    from workspace_gc_loop import WorkspaceGCLoop  # noqa: PLC0415

    state = ports.get("workspace_gc_state")
    if state is None:
        state = MagicMock()
        state.get_active_workspaces.return_value = {}
        state.get_active_issue_numbers.return_value = set()
        state.get_active_branches.return_value = {}
        state.get_hitl_cause.return_value = None
        state.get_issue_attempts.return_value = 0
        ports["workspace_gc_state"] = state
    return WorkspaceGCLoop(
        config=config,
        workspaces=ports["workspace"],
        prs=ports["github"],
        state=state,
        deps=deps,
    )


_BUILDERS: dict[str, Any] = {
    "ci_monitor": _build_ci_monitor,
    "stale_issue_gc": _build_stale_issue_gc,
    "dependabot_merge": _build_dependabot_merge,
    "pr_unsticker": _build_pr_unsticker,
    "health_monitor": _build_health_monitor,
    "workspace_gc": _build_workspace_gc,
}


def ensure_registered() -> None:
    """Idempotent: register any phase-1 loops that aren't already registered.

    Call this from any test that depends on the registry being populated,
    since ``LoopCatalog.reset()`` in unit tests wipes registrations.
    """
    for name, builder in _BUILDERS.items():
        if not LoopCatalog.is_registered(name):
            register_loop(name)(builder)


# Register on import (side effect).
ensure_registered()
