"""s02_batch_three_issues — 3 issues progress in parallel through the pipeline."""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s02_batch_three_issues"
DESCRIPTION = "3 issues batch-implemented; Work Stream tab shows all progressing."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        repos=[("owner/repo", "/workspace/repo")],
        issues=[
            {
                "number": n,
                "title": f"task {n}",
                "body": "b",
                "labels": ["hydraflow-ready"],
            }
            for n in (1, 2, 3)
        ],
        scripts={
            "plan": {n: [{"success": True}] for n in (1, 2, 3)},
            "implement": {
                n: [{"success": True, "branch": f"hf/issue-{n}"}] for n in (1, 2, 3)
            },
            "review": {n: [{"verdict": "approve"}] for n in (1, 2, 3)},
        },
        cycles_to_run=20,
    )


async def assert_outcome(api, page) -> None:
    # /api/timeline/issue/N doesn't expose an `outcome` field — IssueTimeline
    # lacks it. The dashboard's /api/issues/history endpoint exposes the
    # IssueHistoryEntry payload (same source the Outcomes tab consumes), so
    # this is the same shape as s01_happy_single_issue.assert_outcome.
    def _has_merged_issue(payload: dict, n: int) -> bool:
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return False
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("issue_number") != n:
                continue
            outcome = item.get("outcome") or {}
            if isinstance(outcome, dict) and outcome.get("outcome") == "merged":
                return True
        return False

    for n in (1, 2, 3):
        await api.wait_until(
            "/api/issues/history?limit=500",
            lambda p, _n=n: _has_merged_issue(p, _n),
            timeout=60.0,
        )

    await page.goto("/")
    await page.click("text=Work Stream")
    for n in (1, 2, 3):
        await page.wait_for_selector(
            f"[data-testid='stream-issue-{n}']", timeout=10_000
        )
