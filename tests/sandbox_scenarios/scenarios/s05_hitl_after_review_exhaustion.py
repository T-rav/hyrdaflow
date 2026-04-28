"""s05 — 3 review failures → issue surfaces in HITL tab."""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s05_hitl_after_review_exhaustion"
DESCRIPTION = "3 review failures → HITL tab shows issue with request-changes button."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        issues=[
            {"number": 1, "title": "t", "body": "b", "labels": ["hydraflow-ready"]}
        ],
        scripts={
            "plan": {1: [{"success": True}]},
            "implement": {1: [{"success": True, "branch": "hf/issue-1"}] * 4},
            "review": {
                1: [
                    {"verdict": "request_changes", "comments": ["bad 1"]},
                    {"verdict": "request_changes", "comments": ["bad 2"]},
                    {"verdict": "request_changes", "comments": ["bad 3"]},
                ]
            },
        },
        cycles_to_run=10,
    )


async def assert_outcome(api, page) -> None:
    hitl = await api.wait_until(
        "/api/hitl",
        lambda p: any(item.get("number") == 1 for item in p.get("items", [])),
        timeout=120.0,
    )
    assert any(i.get("number") == 1 for i in hitl["items"])

    await page.goto("/")
    await page.click("text=HITL")
    await page.wait_for_selector("[data-testid='hitl-row-1']", timeout=10_000)
    button = page.locator("[data-testid='hitl-row-1'] button:has-text('request')")
    assert await button.is_visible()
