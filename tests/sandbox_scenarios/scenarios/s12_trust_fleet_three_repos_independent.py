"""s12 — 3 repos in registry, each with 1 issue; all process independently."""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s12_trust_fleet_three_repos_independent"
DESCRIPTION = (
    "Multi-repo fleet: 3 repos process independently; Wiki tab shows entries from all."
)


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        repos=[
            ("acme/repo-a", "/workspace/repo-a"),
            ("acme/repo-b", "/workspace/repo-b"),
            ("acme/repo-c", "/workspace/repo-c"),
        ],
        issues=[
            {"number": 1, "title": "t", "body": "b", "labels": ["hydraflow-ready"]},
            {"number": 2, "title": "t", "body": "b", "labels": ["hydraflow-ready"]},
            {"number": 3, "title": "t", "body": "b", "labels": ["hydraflow-ready"]},
        ],
        scripts={
            "plan": {n: [{"success": True}] for n in (1, 2, 3)},
            "implement": {
                n: [{"success": True, "branch": f"hf/issue-{n}"}] for n in (1, 2, 3)
            },
            "review": {n: [{"verdict": "approve"}] for n in (1, 2, 3)},
        },
        cycles_to_run=8,
    )


async def assert_outcome(api, page) -> None:
    for n in (1, 2, 3):
        timeline = await api.wait_until(
            f"/api/timeline/issue/{n}",
            lambda p: p.get("outcome") == "merged",
            timeout=120.0,
        )
        assert timeline["outcome"] == "merged"

    await page.goto("/")
    await page.click("text=Wiki")
    # All three repos surface in the Wiki tab.
    for slug in ("repo-a", "repo-b", "repo-c"):
        await page.wait_for_selector(f"text=acme/{slug}", timeout=10_000)
