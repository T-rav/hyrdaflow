"""System-tab config edit workflow: editing rc_cadence_hours sends PATCH /api/control/config.

Architecture note:
  Editable config knobs in HydraFlow live in the System tab → Workers subtab.
  Each background-worker card may carry an embedded settings panel.  The
  ``staging_promotion`` card renders ``StagingPromotionSettingsPanel``, which
  exposes several inputs that auto-save on blur via ``PATCH /api/control/config``.

  The field chosen here is ``rc_cadence_hours`` — a numeric input that:
    1. Reads its current value from ``config?.rc_cadence_hours`` (populated via
       the ``data.config`` field of ``GET /api/control/status``).
    2. On blur, if the value changed, fires:
         PATCH /api/control/config
         body: { rc_cadence_hours: <new_value>, persist: true }
    3. On 200 OK the local state is kept; on non-200 it rolls back.

Why route interception:
  ``GET /api/control/status`` must return ``status: "running"`` plus a ``config``
  block so the React context sets ``orchestratorStatus`` and populates
  ``config.rc_cadence_hours``.  Without interception the test dashboard would
  return a non-running status and the staging-promotion panel would not render
  the cadence input.  ``GET /api/staging-promotion/status`` is also intercepted
  to prevent a 404 from crashing ``StagingPromotionStatusRow``.

Flow:
  1. Boot dashboard (lightweight shim, no real orchestrator).
  2. Install route interceptors *before* navigation.
  3. Navigate and wait for WS-ready signal.
  4. Click the System tab.
  5. The Workers subtab is active by default.
  6. Locate the staging_promotion worker card (Operations group, not collapsed).
  7. Fill the ``rc-cadence-hours-input`` with a new value.
  8. Press Tab to blur — triggers the PATCH save.
  9. Assert: intercepted PATCH body contains the new value, method is PATCH.
"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.scenario_browser

# Minimal control-status payload — mirrors the pattern in test_pr_approve.py.
# We include rc_cadence_hours so the staging-promotion panel renders with a
# known current value (4 hours).
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
        "rc_cadence_hours": 4,
        "staging_enabled": False,
        "main_branch": "main",
        "staging_branch": "staging",
    },
}

# Minimal staging-promotion status to silence StagingPromotionStatusRow errors.
_STAGING_PROMOTION_STATUS = {
    "cadence_hours": 4,
    "cadence_progress_hours": 0,
    "open_promotion_pr": None,
    "recent_promoted": 0,
    "recent_failed": 0,
    "recent_failure_rate": 0.0,
}


async def test_config_edit_rc_cadence_sends_patch(world, page) -> None:
    """Changing rc_cadence_hours in the System tab fires PATCH /api/control/config.

    Edits the RC cadence field from 4 → 6 hours, blurs to trigger autosave,
    then asserts the intercepted PATCH body contains the new value.
    """
    url = await world.start_dashboard(with_orchestrator=False)

    captured: dict[str, str] = {}

    async def _handle_control_status(route, request) -> None:
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(_RUNNING_CONTROL_STATUS),
        )

    async def _handle_staging_promotion_status(route, request) -> None:
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(_STAGING_PROMOTION_STATUS),
        )

    async def _handle_config_patch(route, request) -> None:
        captured["method"] = request.method
        captured["body"] = request.post_data or ""
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"status": "ok", "updated": {"rc_cadence_hours": 6}}),
        )

    # Install interceptors before navigation so the first fetch is captured.
    await page.route("**/api/control/status", _handle_control_status)
    await page.route(
        "**/api/staging-promotion/status", _handle_staging_promotion_status
    )
    await page.route("**/api/control/config", _handle_config_patch)

    await page.goto(url)
    await page.wait_for_selector('body[data-connected="true"]', timeout=10_000)

    # Navigate to the System tab.
    system_tab = page.locator('[data-testid="main-tabs"] [role="tab"]').filter(
        has_text="System"
    )
    await system_tab.click()

    # Workers subtab is active by default — the staging_promotion card lives in
    # the Operations group which is not collapsed by default (useState(false)).
    # The card renders StagingPromotionSettingsPanel as extraContent.
    staging_card = page.locator('[data-testid="worker-card-staging_promotion"]')
    await staging_card.wait_for(state="visible", timeout=10_000)

    # The RC cadence input is inside the card — fill with new value then blur.
    cadence_input = staging_card.locator('[data-testid="rc-cadence-hours-input"]')
    await cadence_input.wait_for(state="visible", timeout=5_000)

    # Fill overwrites the current value without needing a triple-click.
    await cadence_input.fill("6")
    # Tab away to trigger the onBlur handler that fires the PATCH.
    await cadence_input.press("Tab")

    # Give the autosave request a moment to complete.
    await page.wait_for_timeout(800)

    # Assert: PATCH was fired with the correct payload.
    assert captured.get("method") == "PATCH", (
        f"Expected PATCH, got {captured.get('method')!r}"
    )
    body_str = captured.get("body", "")
    try:
        body = json.loads(body_str)
    except json.JSONDecodeError:
        body = {}
    assert body.get("rc_cadence_hours") == 6, (
        f"Expected rc_cadence_hours=6 in PATCH body, got: {body_str!r}"
    )
    assert body.get("persist") is True, (
        f"Expected persist=True in PATCH body, got: {body_str!r}"
    )
