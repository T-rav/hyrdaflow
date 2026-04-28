"""s09 — dependabot PR with green CI → auto-merged."""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s09_dependabot_auto_merge"
DESCRIPTION = "Dependabot PR + green CI → DependabotMergeLoop merges without human."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        prs=[
            {
                "number": 100,
                "issue_number": 0,
                "branch": "dependabot/npm/foo-1.2.3",
                "ci_status": "pass",
                "merged": False,
                "labels": ["dependencies"],
            }
        ],
        loops_enabled=["dependabot_merge"],
        cycles_to_run=3,
    )


async def assert_outcome(api, page) -> None:
    prs = await api.wait_until(
        "/api/prs",
        lambda p: any(
            item.get("number") == 100 and item.get("merged") is True
            for item in p.get("prs", [])
        ),
        timeout=45.0,
    )
    pr = next(p for p in prs["prs"] if p["number"] == 100)
    assert pr["merged"] is True
