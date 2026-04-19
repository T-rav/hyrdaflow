"""Repo registration workflow: register via UI, verify in list.

Flow:
  1. Boot dashboard with lightweight shim (with_orchestrator=False).
  2. Before navigation, install route handlers:
       - GET /api/repos  → ``{"repos": [], "can_register": true}`` initially,
         then returns the newly-registered repo after POST succeeds.
       - POST /api/repos/add  → records the request body, returns success JSON.
  3. Navigate to the root page and wait for WS ready.
  4. Open the repo-selector dropdown (repo-selector-trigger).
  5. Click "Register repo" button to open RegisterRepoDialog.
  6. Switch to the Manual tab.
  7. Fill the filesystem-path input (data-testid="repo-register-input").
  8. Click Register Repo (data-testid="register-submit").
  9. After submit, the dialog closes and the UI calls GET /api/repos again.
  10. Open the repo-selector dropdown and verify the repo name is visible.
  11. Assert the POST intercept was called with the correct path.

Why route interception:
  MockWorld's start_dashboard() does not wire register_repo_cb or repo_store,
  so POST /api/repos/add returns 503 and GET /api/repos returns can_register:
  false (disabling the button). Route interception provides a clean seam
  without modifying MockWorld internals.
"""

from __future__ import annotations

import json

import pytest
from playwright.async_api import expect

pytestmark = pytest.mark.scenario_browser


async def test_register_repo_appears_in_list(world, page, tmp_path) -> None:
    """Registering a repo via the UI makes it appear in the repo-selector list."""
    repo_path = str(tmp_path / "fake_repo")
    (tmp_path / "fake_repo").mkdir()

    url = await world.start_dashboard(with_orchestrator=False)

    # Mutable state shared across route handlers.
    registered_repos: list[dict] = []
    captured_body: list[str] = []

    async def _handle_repos_get(route, request) -> None:
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"repos": list(registered_repos), "can_register": True}),
        )

    async def _handle_repos_add(route, request) -> None:
        body = request.post_data or ""
        captured_body.append(body)
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, TypeError):
            data = {}
        path = data.get("path", repo_path)
        slug = path.rstrip("/").rsplit("/", 1)[-1]
        registered_repos.append(
            {
                "slug": slug,
                "repo": slug,
                "path": path,
                "running": False,
                "session_id": None,
            }
        )
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"status": "ok", "slug": slug, "path": path}),
        )

    # Install interceptors before navigation.
    await page.route("**/api/repos", _handle_repos_get)
    await page.route("**/api/repos/add", _handle_repos_add)

    await page.goto(url)
    await page.wait_for_selector('body[data-connected="true"]', timeout=10_000)

    # Open the repo-selector dropdown.
    await page.click('[data-testid="repo-selector-trigger"]')
    dropdown = page.locator('[data-testid="repo-selector-dropdown"]')
    await expect(dropdown).to_be_visible(timeout=5_000)

    # Click the "+ Register repo" button inside the dropdown.
    register_btn = dropdown.get_by_text("+ Register repo")
    await expect(register_btn).to_be_enabled(timeout=5_000)
    await register_btn.click()

    # The RegisterRepoDialog should now be open.
    overlay = page.locator('[data-testid="register-repo-overlay"]')
    await expect(overlay).to_be_visible(timeout=5_000)

    # Switch to the Manual tab.
    await page.click('[data-testid="tab-manual"]')

    # Fill the filesystem-path input and submit.
    path_input = page.locator('[data-testid="repo-register-input"]')
    await expect(path_input).to_be_visible(timeout=5_000)
    await path_input.fill(repo_path)

    submit_btn = page.locator('[data-testid="register-submit"]')
    await expect(submit_btn).to_be_enabled(timeout=5_000)
    await submit_btn.click()

    # Dialog should close after successful registration.
    await expect(overlay).not_to_be_visible(timeout=10_000)

    # Re-open the repo-selector dropdown and verify the repo is listed.
    await page.click('[data-testid="repo-selector-trigger"]')
    updated_dropdown = page.locator('[data-testid="repo-selector-dropdown"]')
    await expect(updated_dropdown).to_be_visible(timeout=5_000)
    await expect(
        updated_dropdown.locator("button").filter(has_text="fake_repo").first
    ).to_be_visible(timeout=10_000)

    # Confirm the registration endpoint was hit with the correct path.
    assert captured_body, "Expected POST /api/repos/add to have been intercepted"
    assert any("fake_repo" in b for b in captured_body), (
        f"Expected captured body to reference 'fake_repo'; got: {captured_body!r}"
    )
