"""s04 — PR opens with red CI, ci-fix runner intervenes, CI green, merged."""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s04_ci_red_then_fixed"
DESCRIPTION = "Red CI → ci-fix → green CI → merged."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        issues=[
            {"number": 1, "title": "t", "body": "b", "labels": ["hydraflow-ready"]}
        ],
        prs=[
            {
                "number": 100,
                "issue_number": 1,
                "branch": "hf/issue-1",
                "ci_status": "fail",
                "merged": False,
                "labels": [],
            }
        ],
        scripts={
            "plan": {1: [{"success": True}]},
            "implement": {1: [{"success": True, "branch": "hf/issue-1"}]},
            "fix_ci": {1: [{"success": True, "ci_status_after": "pass"}]},
            "review": {1: [{"verdict": "approve"}]},
        },
        cycles_to_run=10,
    )


async def assert_outcome(api, page) -> None:
    timeline = await api.wait_until(
        "/api/timeline/issue/1",
        lambda p: p.get("outcome") == "merged",
        timeout=120.0,
    )
    assert timeline["outcome"] == "merged"
