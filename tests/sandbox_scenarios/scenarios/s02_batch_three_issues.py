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
        cycles_to_run=6,
    )


async def assert_outcome(api, page) -> None:
    for n in (1, 2, 3):
        timeline = await api.wait_until(
            f"/api/timeline/issue/{n}",
            lambda p: p.get("outcome") == "merged",
            timeout=60.0,
        )
        assert timeline["outcome"] == "merged"

    await page.goto("/")
    await page.click("text=Work Stream")
    for n in (1, 2, 3):
        await page.wait_for_selector(
            f"[data-testid='stream-issue-{n}']", timeout=10_000
        )
