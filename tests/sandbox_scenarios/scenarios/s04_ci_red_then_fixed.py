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
    # /api/timeline/issue/N has no `outcome` field — use /api/issues/history
    # like s01_happy_single_issue.
    def _merged(payload: dict) -> bool:
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return False
        for item in items:
            if not isinstance(item, dict) or item.get("issue_number") != 1:
                continue
            outcome = item.get("outcome") or {}
            if isinstance(outcome, dict) and outcome.get("outcome") == "merged":
                return True
        return False

    await api.wait_until(
        "/api/issues/history?limit=500",
        _merged,
        timeout=120.0,
    )
