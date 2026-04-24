"""Verify all 20 phase-1+3b loops register via the catalog."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests.scenarios.catalog import LoopCatalog
from tests.scenarios.catalog.loop_registrations import ensure_registered

ALL_LOOPS = (
    # phase 1 (6)
    "ci_monitor",
    "stale_issue_gc",
    "dependabot_merge",
    "pr_unsticker",
    "health_monitor",
    "workspace_gc",
    # phase 3b (14)
    "runs_gc",
    "retrospective",
    "adr_reviewer",
    "github_cache",
    "repo_wiki",
    "sentry",
    "memory_sync",
    "diagnostic",
    "code_grooming",
    "report_issue",
    "epic_sweeper",
    "security_patch",
    "stale_issue",
    "epic_monitor",
    "wiki_rot_detector",
    # trust-arch caretaker fleet (§4.5–§4.8)
    "flake_tracker",
    "skill_prompt_eval",
    "fake_coverage_auditor",
    "rc_budget",
    # trust-arch meta + attribution (§4.3 + §12.1)
    "staging_bisect",
    "trust_fleet_sanity",
    # trust-arch contract refresh (§4.2)
    "contract_refresh",
    # trust-arch corpus learning (§4.1 v2)
    "corpus_learning",
)


@pytest.fixture(autouse=True)
def _ensure_registered() -> Iterator[None]:
    ensure_registered()
    yield


@pytest.mark.parametrize("name", ALL_LOOPS)
def test_loop_registered(name: str) -> None:
    assert LoopCatalog.is_registered(name), f"{name!r} not registered"
