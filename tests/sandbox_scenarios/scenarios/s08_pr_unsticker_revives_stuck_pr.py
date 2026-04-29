"""s08 — PR with no activity → PRUnstickerLoop triggers auto-resync."""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s08_pr_unsticker_revives_stuck_pr"
DESCRIPTION = "Stale PR detected → auto-resync triggers → PR moves."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        issues=[
            {
                "number": 1,
                "title": "t",
                "body": "b",
                "labels": ["hydraflow-implementing"],
            }
        ],
        prs=[
            {
                "number": 100,
                "issue_number": 1,
                "branch": "hf/issue-1",
                "ci_status": "pass",
                "merged": False,
                "labels": ["wip"],
            }
        ],
        loops_enabled=["pr_unsticker"],
        cycles_to_run=4,
    )


async def assert_outcome(api, page) -> None:
    history = await api.wait_until(
        "/api/timeline/issue/1",
        lambda p: any(
            e.get("event") == "pr_unsticker_resync" for e in p.get("events", [])
        ),
        timeout=60.0,
    )
    assert any(e.get("event") == "pr_unsticker_resync" for e in history["events"])
