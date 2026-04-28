"""s01_happy_single_issue — single issue → triage → plan → implement → review → merge.

Tier 2 sandbox scenario. Verifies the full assembly line works end-to-end:
- API: /api/issues/history reports outcome.outcome == "merged" for issue 1
  (the dashboard's IssueHistoryEntry payload — same data the Outcomes UI tab
   consumes; chosen over /api/timeline/issue/N because IssueTimeline doesn't
   carry an `outcome` field).
- UI: Outcomes tab shows the merged outcome row for issue 1.
- UI: MOCKWORLD banner is visible (proves the duck-typed FakeLLM signaled
  the dashboard via the `_is_fake_adapter` flag).
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s01_happy_single_issue"
DESCRIPTION = (
    "Single hydraflow-ready issue → full pipeline → merged. Outcomes tab shows it."
)


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        repos=[("owner/repo", "/workspace/repo")],
        issues=[
            {
                "number": 1,
                "title": "Add hello world",
                "body": "Implement a hello-world function in src/hello.py",
                "labels": ["hydraflow-ready"],
            },
        ],
        scripts={
            "plan": {1: [{"success": True, "task_count": 1}]},
            "implement": {1: [{"success": True, "branch": "hf/issue-1"}]},
            "review": {1: [{"verdict": "approve", "comments": []}]},
        },
        cycles_to_run=4,
    )


async def assert_outcome(api, page) -> None:
    """End-to-end assertions: API confirms merged + UI renders the row."""

    # API assertion — eventually consistent: poll history until issue 1
    # carries an outcome of "merged". The dashboard's /api/issues/history
    # endpoint exposes the IssueHistoryEntry payload that the Outcomes UI
    # also consumes, so this is the same source of truth as the visual check.
    def _has_merged_issue_1(payload: dict) -> bool:
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return False
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("issue_number") != 1:
                continue
            outcome = item.get("outcome") or {}
            if isinstance(outcome, dict) and outcome.get("outcome") == "merged":
                return True
        return False

    history = await api.wait_until(
        "/api/issues/history?limit=500",
        _has_merged_issue_1,
        timeout=30.0,
    )
    items = history.get("items") if isinstance(history, dict) else None
    assert isinstance(items, list), f"history payload missing items: {history!r}"
    matching = [i for i in items if isinstance(i, dict) and i.get("issue_number") == 1]
    assert matching, f"no issue_number=1 entry in history: {history!r}"
    outcome = matching[0].get("outcome") or {}
    assert outcome.get("outcome") == "merged", f"got {matching[0]!r}"

    # UI assertion — Outcomes tab renders the merged outcome row.
    await page.goto("/")
    await page.click("text=Outcomes")
    await page.wait_for_selector("[data-testid='outcome-row-1']", timeout=10_000)
    text = await page.locator("[data-testid='outcome-row-1']").text_content()
    assert "merged" in (text or "").lower(), f"got {text!r}"

    # MOCKWORLD banner is visible (proves duck-typing wiring works — the
    # dashboard reads `_is_fake_adapter` off FakeLLM and exposes it as
    # mockworldActive in the WS state payload).
    banner = page.locator("[data-testid='mockworld-banner']")
    assert await banner.is_visible()
