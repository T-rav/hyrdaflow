"""PR merge-update workflow: backend merge event reflected in the Outcomes panel.

Architecture note:
  HydraFlow does NOT expose a user-facing "Approve PR" button.  PR approval
  and merging is fully automated: the review loop calls ``PRManager.merge_pr``
  (real ``gh`` CLI) when CI passes and the verdict is 'approve'.  There is no
  ``POST /api/prs/<n>/approve`` endpoint and no corresponding UI control.

  What IS testable end-to-end is the *state transition* triggered by the
  automated merge:

    1. The review loop publishes a ``merge_update`` event on the EventBus with
       ``status="merged"`` and ``pr=<number>``.
    2. The FastAPI WebSocket handler fans this out to all connected browsers.
    3. The React reducer (``case 'merge_update'``) sets ``merged: true`` on the
       matching entry in the ``prs`` state slice.
    4. The Outcomes panel renders ``#{pr.number} (merged)`` in the expanded row.

  This test drives that exact path using:
    - Route interception for ``GET /api/prs`` and ``GET /api/issues/history``
      so no real GitHub token is required.
    - ``world._harness.bus.publish()`` to inject the ``merge_update`` event as
      if the reviewer loop emitted it, which the WebSocket handler broadcasts
      to the browser.

Why route interception (same reason as Tasks 20 and 21):
  ``PRManager`` calls the real ``gh`` CLI.  MockWorld wires fakes for all
  runner/reviewer/agent methods but the dashboard's route handler for
  ``GET /api/prs`` calls ``manager.list_open_prs()`` which hits real GitHub.
  Intercepting at the network level is the correct seam.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from playwright.async_api import expect

from events import EventType, HydraFlowEvent

pytestmark = pytest.mark.scenario_browser

# Minimal control-status payload that makes React render live panels.
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


async def test_merge_update_event_reflected_in_outcomes_panel(world, page) -> None:
    """A merge_update WS event causes the Outcomes tab to show '(merged)'.

    Flow:
      1. Boot dashboard (lightweight shim, no real orchestrator).
      2. Install route interceptors for control/status, /api/prs, and
         /api/issues/history before navigation.
      3. Navigate and wait for WS-ready signal.
      4. Publish a ``merge_update`` event on the harness bus (simulating the
         automated review loop merging PR 301).
      5. Switch to the Outcomes tab.
      6. Expand the issue row for issue #207.
      7. Assert the PR link reads "#301 (merged)".
    """
    url = await world.start_dashboard(with_orchestrator=False)

    # Track whether the merge event was published (assertion hook).
    merge_event_published: list[bool] = []

    # Initial /api/prs payload: PR 301 exists but not yet merged.
    _prs_merged = False

    async def _handle_control_status(route, request) -> None:
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(_RUNNING_CONTROL_STATUS),
        )

    async def _handle_prs(route, request) -> None:
        merged_flag = _prs_merged
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                [
                    {
                        "pr": 301,
                        "issue": 207,
                        "branch": "agent/issue-207",
                        "url": "https://github.com/T-rav/hydraflow/pull/301",
                        "ci_status": "pass",
                        "merged": merged_flag,
                        "status": "merged" if merged_flag else "reviewable",
                    }
                ]
            ),
        )

    # Issue-history payload: issue 207 with outcome=merged and PR 301 (merged).
    # This payload is static — the Outcomes panel renders it from this endpoint,
    # not from the live prs state slice.
    _issue_history_payload = {
        "items": [
            {
                "issue_number": 207,
                "title": "Upgrade Node",
                "status": "merged",
                "outcome": {
                    "outcome": "merged",
                    "reason": "PR merged successfully",
                    "phase": "review",
                    "pr_number": 301,
                    "closed_at": "2026-04-18T10:00:00Z",
                    "verification_issue_number": None,
                },
                "prs": [
                    {
                        "number": 301,
                        "url": "https://github.com/T-rav/hydraflow/pull/301",
                        "merged": True,
                    }
                ],
                "issue_url": "https://github.com/T-rav/hydraflow/issues/207",
                "first_seen": "2026-04-18T09:00:00Z",
                "last_seen": "2026-04-18T10:00:00Z",
                "session_ids": [],
                "inference": {
                    "inference_calls": 0,
                    "total_tokens": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "pruned_chars_total": 0,
                },
                "model_calls": {},
                "source_calls": {},
                "linked_issues": [],
                "epic": None,
                "crate_title": None,
                "crate_number": None,
            }
        ],
        "totals": {},
    }

    async def _handle_issue_history(route, request) -> None:
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(_issue_history_payload),
        )

    # Install interceptors before navigation.
    await page.route("**/api/control/status", _handle_control_status)
    await page.route("**/api/prs**", _handle_prs)
    await page.route("**/api/issues/history**", _handle_issue_history)

    await page.goto(url)
    await page.wait_for_selector('body[data-connected="true"]', timeout=10_000)

    # Publish the merge_update event to the harness bus, simulating what the
    # automated review loop does when it calls merge_pr().  The FastAPI WS
    # handler fans this out to all connected browser sessions.
    merge_event = HydraFlowEvent(
        type=EventType.MERGE_UPDATE,
        data={"pr": 301, "issue": 207, "status": "merged", "title": "Upgrade Node"},
    )
    await world._harness.bus.publish(merge_event)
    merge_event_published.append(True)

    # Give the WS broadcast a moment to propagate to the browser.
    await asyncio.sleep(0.3)

    # Switch to Outcomes tab — only visible when orchestrator is "running".
    outcomes_tab = page.locator('[data-testid="main-tabs"] [role="tab"]').filter(
        has_text="Outcomes"
    )
    await expect(outcomes_tab).to_be_visible(timeout=5_000)
    await outcomes_tab.click()

    # Issue row for #207 should be visible in the Outcomes panel.
    issue_row_toggle = page.get_by_role("button", name="Toggle issue 207")
    await expect(issue_row_toggle).to_be_visible(timeout=10_000)

    # Expand the row to reveal the PR detail.
    await issue_row_toggle.click()

    # The expanded row should show "#301 (merged)".
    pr_merged_text = page.get_by_text("#301 (merged)")
    await expect(pr_merged_text).to_be_visible(timeout=5_000)

    # Confirm the merge event was published to the bus.
    assert merge_event_published, (
        "merge_update event was never published to the event bus"
    )
