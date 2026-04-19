"""HITL tab — human-in-the-loop items awaiting corrections."""

from __future__ import annotations

from .base import BasePage


class HitlPage(BasePage):
    async def open(self) -> None:
        """Navigate to the dashboard root and switch to the HITL tab.

        The React app does not read the ``tab`` URL parameter — the active tab
        is controlled by internal state only.  We navigate to ``/`` (so the
        full app boots and the WS connection is established) and then click the
        HITL tab button to switch the view.

        The tab button is always rendered regardless of orchestrator status;
        only the tab content differs (table vs. idle message).
        """
        await self.goto("/")
        # The HITL tab is a div[role="tab"] inside [data-testid="main-tabs"].
        # Playwright's text locator finds it even when the badge span is present.
        await (
            self.page.locator('[data-testid="main-tabs"] [role="tab"]')
            .filter(has_text="HITL")
            .click()
        )

    def item(self, issue_number: int):
        """Row element for a HITL item (click to expand detail panel)."""
        return self.page.locator(f'[data-testid="hitl-row-{issue_number}"]')

    def detail(self, issue_number: int):
        """Expanded detail panel for a HITL item."""
        return self.page.locator(f'[data-testid="hitl-detail-{issue_number}"]')

    def correction_input(self, issue_number: int):
        """Correction textarea inside the expanded detail panel."""
        return self.page.locator(f'[data-testid="hitl-textarea-{issue_number}"]')

    def submit_button(self, issue_number: int):
        """'Retry with guidance' button — submits correction to /api/hitl/{N}/correct."""
        return self.page.locator(f'[data-testid="hitl-retry-{issue_number}"]')

    def skip_button(self, issue_number: int):
        """Skip button — posts **HITL Skip** comment and removes item from queue."""
        return self.page.locator(f'[data-testid="hitl-skip-{issue_number}"]')

    def close_button(self, issue_number: int):
        """Close button — posts **HITL Close** comment and closes the issue."""
        return self.page.locator(f'[data-testid="hitl-close-{issue_number}"]')
