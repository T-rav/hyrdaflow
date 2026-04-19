"""Deterministic seed helpers for contract snapshot tests.

Mirrors ``src/ui/e2e/fixtures/seed-state.js`` so visual baselines can be
compared against the JS suite (Task 14) before the JS harness is deleted.
"""

from __future__ import annotations

from tests.scenarios.fakes.mock_world import MockWorld


def seed_populated_pipeline(world: MockWorld) -> MockWorld:
    """Seed an active-pipeline world with 10 issues across phases + 3 merged PRs."""
    gh = world.github

    # Triage
    gh.add_issue(201, "Add rate limiting to API", "...", labels=["hydraflow-find"])
    gh.add_issue(202, "Refactor auth middleware", "...", labels=["hydraflow-find"])

    # Plan
    gh.add_issue(203, "Implement search indexing", "...", labels=["hydraflow-plan"])

    # Implement
    gh.add_issue(204, "Add CSV export to reports", "...", labels=["hydraflow-ready"])
    gh.add_issue(205, "Dark mode toggle", "...", labels=["hydraflow-ready"])
    gh.add_issue(206, "Fix pagination offset bug", "...", labels=["hydraflow-ready"])

    # Review
    gh.add_issue(207, "Upgrade Node runtime to v22", "...", labels=["hydraflow-review"])

    # HITL
    gh.add_issue(
        208, "Migrate legacy DB schema", "...", labels=["hydraflow-hitl-review"]
    )

    # Merged (closed)
    for num, title in (
        (190, "Add health-check endpoint"),
        (191, "Update CI badge in README"),
        (192, "Fix CORS headers"),
    ):
        gh.add_issue(num, title, "...", labels=["hydraflow-done"])
        gh.issue(num).state = "closed"

    # PRs
    gh.add_pr(
        number=301,
        issue_number=207,
        branch="agent/issue-207",
        ci_status="pass",
        merged=False,
    )
    gh.add_pr(
        number=290,
        issue_number=190,
        branch="agent/issue-190",
        ci_status="pass",
        merged=True,
    )
    gh.add_pr(
        number=291,
        issue_number=191,
        branch="agent/issue-191",
        ci_status="pass",
        merged=True,
    )
    return world


def seed_empty_pipeline(world: MockWorld) -> MockWorld:
    """No-op: world is already empty at construction time."""
    return world
