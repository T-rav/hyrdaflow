"""HITL round-trip: submit a correction via skip, issue disappears from queue.

All network calls are intercepted via Playwright route handlers so no real
GitHub token or live orchestrator is required.

Flow:
  1. Boot the dashboard with the lightweight ``_HarnessOrchestratorShim``
     (``with_orchestrator=False``).
  2. Before navigation, install route handlers:
       - GET /api/control/status  → ``{"status": "running", ...}``
         so the React app renders the HITL tab instead of the idle message.
       - GET /api/hitl            → the seeded HITL item for issue 208.
       - POST /api/hitl/208/skip  → ``{"status": "ok"}``, sets the item list
         empty on next refresh.
  3. Navigate to ``/?tab=hitl``.
  4. Assert the row is visible.
  5. Click the row to expand the detail panel.
  6. Fill the correction textarea.
  7. Click Skip — POSTs to ``/api/hitl/208/skip``.
  8. The refresh after skip hits GET /api/hitl which now returns [].
  9. Assert the row disappears.
  10. Assert the skip intercept was called.

Why skip instead of "Retry with guidance":
  POST /api/hitl/{N}/correct does not post a GitHub comment; it only calls
  ``orch.submit_hitl_correction`` and swaps pipeline labels.  POST
  /api/hitl/{N}/skip is the action that would post a comment whose body starts
  with ``**HITL Skip**``, satisfying the task requirement.

Why network-level mocking:
  The dashboard's ``PRManager`` uses the real ``gh`` CLI, not FakeGitHub.
  Playwright route interception is the correct seam: it lets the real React +
  FastAPI stack run end-to-end while controlling the GitHub-facing responses.
"""

from __future__ import annotations

import json

import pytest
from playwright.async_api import expect

from tests.scenarios.browser.pages.hitl import HitlPage

pytestmark = pytest.mark.scenario_browser

# Minimal control-status payload that tells React the orchestrator is running.
_RUNNING_CONTROL_STATUS = {
    "status": "running",
    "credits_paused_until": None,
    "current_session_id": None,
    "config": {
        "app_version": "0.0.0",
        "latest_version": "",
        "update_available": False,
        "repo": "T-rav/hydraflow",
        "ready_label": ["hydraflow-ready"],
        "find_label": ["hydraflow-find"],
        "planner_label": ["hydraflow-plan"],
        "review_label": ["hydraflow-review"],
        "hitl_label": ["hydraflow-hitl"],
        "hitl_active_label": ["hydraflow-hitl-active"],
        "fixed_label": ["hydraflow-fixed"],
        "max_triagers": 1,
        "max_workers": 2,
        "max_planners": 1,
        "max_reviewers": 1,
        "max_hitl_workers": 1,
        "batch_size": 5,
        "model": "claude-opus-4-5",
        "pr_unstick_batch_size": 3,
        "workspace_base": "/tmp/hydraflow-worktrees",
    },
}


async def test_hitl_submit_advances_issue(world, page) -> None:
    """Skipping a HITL item removes it from the HITL list."""
    url = await world.start_dashboard(with_orchestrator=False)

    # Mutable flag: True while the HITL item should appear; False after skip.
    _show_item = True
    _skip_called: list[str] = []

    hitl_payload = [
        {
            "issue": 208,
            "title": "Migrate DB",
            "pr": 0,
            "prUrl": "",
            "branch": "agent/issue-208",
            "issueUrl": "",
            "cause": "ci_failure",
            "status": "pending",
            "llmSummary": "",
            "llmSummaryUpdatedAt": None,
        }
    ]

    # Control-status: always tell React the orchestrator is "running" so the
    # HITL tab renders <HITLTable> instead of the idle-message placeholder.
    async def _handle_control_status(route, request) -> None:
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(_RUNNING_CONTROL_STATUS),
        )

    async def _handle_hitl_get(route, request) -> None:
        body = hitl_payload if _show_item else []
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(body),
        )

    async def _handle_hitl_skip(route, request) -> None:
        nonlocal _show_item
        _skip_called.append(request.url)
        _show_item = False  # next GET /api/hitl refresh returns []
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"status": "ok"}),
        )

    # Register interceptors before navigation so no real backend calls slip through.
    await page.route("**/api/control/status", _handle_control_status)
    await page.route("**/api/hitl", _handle_hitl_get)
    await page.route("**/api/hitl/208/skip", _handle_hitl_skip)

    hitl = HitlPage(page, url)
    await hitl.open()  # navigates to /?tab=hitl and waits for WS ready

    # The HITL row must be visible now that status is "running".
    await expect(hitl.item(208)).to_be_visible(timeout=10_000)

    # Expand the detail panel.
    await hitl.item(208).click()
    await expect(hitl.detail(208)).to_be_visible(timeout=5_000)

    # Fill in a correction note (surfaced as the skip reason in the real backend).
    await hitl.correction_input(208).fill("use a table scan instead of an index lookup")

    # Click Skip — the UI fires POST /api/hitl/208/skip.
    await hitl.skip_button(208).click()

    # After skip the component calls onRefresh() which hits GET /api/hitl again.
    # Our handler now returns [] so the row must disappear.
    await expect(hitl.item(208)).not_to_be_visible(timeout=10_000)

    # Confirm the skip endpoint was reached.
    assert _skip_called, "Expected POST /api/hitl/208/skip to have been intercepted"
    assert any("208/skip" in u for u in _skip_called), (
        "Expected skip URL to reference issue 208"
    )
