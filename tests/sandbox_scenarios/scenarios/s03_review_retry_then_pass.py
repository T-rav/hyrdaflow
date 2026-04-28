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
    timeline = await api.wait_until(
        "/api/timeline/issue/1",
        lambda p: p.get("outcome") == "merged",
        timeout=90.0,
    )
    assert timeline["outcome"] == "merged"
    history = await api.get("/api/issues/history?issue_number=1")
    review_attempts = [
        e for e in history.get("events", []) if e.get("phase") == "review"
    ]
    assert len(review_attempts) >= 2, (
        f"expected >=2 review events, got {len(review_attempts)}"
    )
