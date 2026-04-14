"""Verify the six phase-1 loops register via the catalog."""

from __future__ import annotations

import pytest

from tests.scenarios.catalog import LoopCatalog
from tests.scenarios.catalog.loop_registrations import ensure_registered

PHASE1_LOOPS = (
    "ci_monitor",
    "stale_issue_gc",
    "dependabot_merge",
    "pr_unsticker",
    "health_monitor",
    "workspace_gc",
)


@pytest.fixture(autouse=True)
def _ensure_phase1_registered() -> None:
    ensure_registered()


@pytest.mark.parametrize("name", PHASE1_LOOPS)
def test_loop_registered(name: str) -> None:
    assert LoopCatalog.is_registered(name), f"{name!r} not registered"
