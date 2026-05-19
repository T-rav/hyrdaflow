"""s03 — review fails attempt 1, passes attempt 2; ends merged."""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s03_review_retry_then_pass"
DESCRIPTION = "Review fails attempt 1, passes attempt 2; issue ends merged."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        issues=[
            {"number": 1, "title": "t", "body": "b", "labels": ["hydraflow-ready"]}
        ],
        scripts={
            "plan": {1: [{"success": True}]},
            "implement": {
                1: [
                    {"success": True, "branch": "hf/issue-1"},
                    {"success": True, "branch": "hf/issue-1"},
                ]
            },
            "review": {
                1: [
                    {"verdict": "request-changes", "comments": ["fix the indent"]},
                    {"verdict": "approve"},
                ]
            },
        },
        cycles_to_run=8,
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
        timeout=90.0,
    )
