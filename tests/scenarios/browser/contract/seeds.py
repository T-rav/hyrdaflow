"""Deterministic seed helpers for contract snapshot tests.

Mirrors ``src/ui/e2e/fixtures/seed-state.js`` so visual baselines can be
compared against the JS suite (Task 14) before the JS harness is deleted.
"""

from __future__ import annotations

from tests.scenarios.fakes.mock_world import MockWorld


def seed_populated_pipeline(world: MockWorld) -> MockWorld:
    """Seed an active-pipeline world with 10 issues across phases + 3 merged PRs.

    Stage mapping (IssueStore internal names):
      - "find"   → triage queue  (hydraflow-find label)
      - "plan"   → plan queue    (hydraflow-plan label)
      - "ready"  → implement queue (hydraflow-ready label)
      - "review" → review queue  (hydraflow-review label)
      - "hitl"   → HITL set      (hydraflow-hitl-review label)

    Note: "triage" and "implement" are NOT valid enqueue_transition stages;
    use "find" and "ready" respectively.
    """
    from tests.conftest import TaskFactory  # noqa: PLC0415

    gh = world.github
    harness = world._harness

    def _seed(num: int, title: str, labels: list[str], stage: str) -> None:
        gh.add_issue(num, title, "...", labels=labels)
        task = TaskFactory.create(id=num, title=title, body="...", tags=labels)
        harness.seed_issue(task, stage=stage)

    # Triage (internal stage: "find")
    _seed(201, "Add rate limiting to API", ["hydraflow-find"], "find")
    _seed(202, "Refactor auth middleware", ["hydraflow-find"], "find")

    # Plan
    _seed(203, "Implement search indexing", ["hydraflow-plan"], "plan")

    # Implement (internal stage: "ready")
    _seed(204, "Add CSV export to reports", ["hydraflow-ready"], "ready")
    _seed(205, "Dark mode toggle", ["hydraflow-ready"], "ready")
    _seed(206, "Fix pagination offset bug", ["hydraflow-ready"], "ready")

    # Review
    _seed(207, "Upgrade Node runtime to v22", ["hydraflow-review"], "review")

    # HITL
    _seed(208, "Migrate legacy DB schema", ["hydraflow-hitl-review"], "hitl")

    # Merged (closed) — not seeded into the active pipeline store, but GH knows
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
