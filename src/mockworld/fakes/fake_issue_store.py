"""FakeIssueStore — IssueStorePort impl backed by FakeGitHub state.

Standalone class created for the sandbox entrypoint (Task 1.10), which
constructs Fakes via build_services() overrides — monkeypatching only
works in-process and can't reach the docker container.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from events import EventBus
    from mockworld.fakes.fake_github import FakeGitHub
    from mockworld.seed import MockWorldSeed


@dataclass
class FakeIssueRecord:
    """Minimal IssueStore-shaped payload."""

    number: int
    title: str
    body: str
    labels: list[str]
    state: str = "OPEN"


class FakeIssueStore:
    """Minimal sandbox stand-in — does NOT satisfy IssueStorePort.

    Provides only `get`, `transition`, `list_by_label` — the surface the
    sandbox entrypoint needs (Task 1.10). The real IssueStorePort has
    11+ methods (`get_triageable`, `get_plannable`, `mark_active`,
    `enrich_with_comments`, etc.). Extend here when sandbox scenarios
    need more methods. Do NOT pass this where an IssueStorePort is
    required without checking the call site.
    """

    _is_fake_adapter = True

    def __init__(self, github: FakeGitHub, event_bus: EventBus) -> None:
        self._github = github
        self._bus = event_bus

    @classmethod
    def from_seed(cls, seed: MockWorldSeed, event_bus: EventBus) -> FakeIssueStore:
        from mockworld.fakes.fake_github import FakeGitHub

        github = FakeGitHub.from_seed(seed)
        return cls(github=github, event_bus=event_bus)

    async def get(self, issue_number: int) -> FakeIssueRecord:
        issue = self._github._issues[issue_number]
        return FakeIssueRecord(
            number=issue.number,
            title=issue.title,
            body=issue.body,
            labels=list(issue.labels),
        )

    async def transition(
        self, issue_number: int, from_label: str, to_label: str
    ) -> None:
        issue = self._github._issues[issue_number]
        if from_label in issue.labels:
            issue.labels.remove(from_label)
        if to_label not in issue.labels:
            issue.labels.append(to_label)

    async def list_by_label(self, label: str) -> list[FakeIssueRecord]:
        out = []
        for issue in self._github._issues.values():
            if label in issue.labels and issue.state == "open":
                out.append(
                    FakeIssueRecord(
                        number=issue.number,
                        title=issue.title,
                        body=issue.body,
                        labels=list(issue.labels),
                    )
                )
        return out
