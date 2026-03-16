"""Human-in-the-loop control for the orchestrator."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hitl_phase import HITLPhase
    from issue_fetcher import IssueFetcher

logger = logging.getLogger("hydraflow.hitl_controller")


class HITLController:
    """Manages HITL interactions: human input requests/responses and corrections."""

    def __init__(
        self,
        hitl_phase: HITLPhase,
        fetcher: IssueFetcher,
        hitl_label: list[str],
    ) -> None:
        self._hitl_phase = hitl_phase
        self._fetcher = fetcher
        self._hitl_label = hitl_label
        self._human_input_requests: dict[int, str] = {}
        self._human_input_responses: dict[int, str] = {}

    @property
    def human_input_requests(self) -> dict[int, str]:
        """Pending questions for the human operator."""
        return self._human_input_requests

    @property
    def human_input_responses(self) -> dict[int, str]:
        """Fulfilled human-input responses."""
        return self._human_input_responses

    @property
    def active_hitl_issues(self) -> set[int]:
        """Proxy to hitl_phase active issues."""
        return self._hitl_phase.active_hitl_issues

    @property
    def hitl_corrections(self) -> dict[int, str]:
        """Proxy to hitl_phase corrections dict."""
        return self._hitl_phase.hitl_corrections

    def provide_human_input(self, issue_number: int, answer: str) -> None:
        """Provide an answer to a paused agent's question."""
        self._human_input_responses[issue_number] = answer
        self._human_input_requests.pop(issue_number, None)

    def submit_correction(self, issue_number: int, correction: str) -> None:
        """Store a correction for a HITL issue to guide retry."""
        self._hitl_phase.submit_correction(issue_number, correction)

    def get_status(self, issue_number: int) -> str:
        """Return the HITL status for an issue."""
        return self._hitl_phase.get_status(issue_number)

    def skip_issue(self, issue_number: int) -> None:
        """Remove an issue from HITL tracking."""
        self._hitl_phase.skip_issue(issue_number)

    async def do_work(self) -> None:
        """Fetch HITL issues, attempt auto-fixes, then process human corrections."""
        hitl_issues = await self._fetcher.fetch_issues_by_labels(
            list(self._hitl_label),
            limit=50,
        )
        if hitl_issues:
            await self._hitl_phase.attempt_auto_fixes(hitl_issues)
        await self._hitl_phase.process_corrections()
