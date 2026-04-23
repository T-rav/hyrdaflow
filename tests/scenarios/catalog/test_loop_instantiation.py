"""Smoke test — every registered loop can be instantiated with mock deps."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.scenarios.catalog import LoopCatalog
from tests.scenarios.catalog.loop_registrations import ensure_registered

ALL_LOOPS = (
    "ci_monitor",
    "stale_issue_gc",
    "dependabot_merge",
    "pr_unsticker",
    "health_monitor",
    "workspace_gc",
    "runs_gc",
    "retrospective",
    "adr_reviewer",
    "github_cache",
    "repo_wiki",
    "sentry",
    "diagnostic",
    "code_grooming",
    "report_issue",
    "epic_sweeper",
    "security_patch",
    "stale_issue",
    "epic_monitor",
)


@pytest.fixture(autouse=True)
def _ensure_registered() -> Iterator[None]:
    ensure_registered()
    yield


@pytest.mark.parametrize("name", ALL_LOOPS)
def test_loop_instantiates(tmp_path: Path, name: str) -> None:
    """Every loop builder returns an instance — no TypeError from signature drift.

    We test instantiation only (not _do_work) so that async/mock issues in
    _do_work don't surface here as false positives.
    """
    from tests.helpers import make_bg_loop_deps  # noqa: PLC0415

    bg = make_bg_loop_deps(tmp_path)

    from base_background_loop import LoopDeps  # noqa: PLC0415

    loop_deps = LoopDeps(
        event_bus=bg.bus,
        stop_event=bg.stop_event,
        status_cb=bg.status_cb,
        enabled_cb=bg.enabled_cb,
        sleep_fn=AsyncMock(),
    )

    github_fake = MagicMock()
    ports: dict = {
        "github": github_fake,
        "workspace": MagicMock(),
        "hindsight": MagicMock(),
        "sentry": MagicMock(),
        "clock": MagicMock(),
    }

    try:
        instance = LoopCatalog.instantiate(
            name, ports=ports, config=bg.config, deps=loop_deps
        )
    except TypeError as exc:
        pytest.fail(
            f"TypeError when instantiating {name!r} — constructor signature drifted: {exc}"
        )

    assert instance is not None, f"{name!r} builder returned None"
