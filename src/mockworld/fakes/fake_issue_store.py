"""FakeIssueStore — IssueStorePort impl backed by FakeGitHub state.

Extracted from `tests/scenarios/fakes/mock_world.py:_wire_targets`,
which previously monkeypatched the real IssueStore. Now standalone
so build_services() can accept it as an override.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mockworld.seed import MockWorldSeed

    from events import EventBus
    from mockworld.fakes.fake_github import FakeGitHub


@dataclass
class FakeIssueRecord:
    """Minimal IssueStore-shaped payload."""

    number: int
    title: str
    body: str
    labels: list[str]
    state: str = "OPEN"


class FakeIssueStore:
    """IssueStorePort impl. Reads from FakeGitHub; writes back to it."""

    _is_fake_adapter = True

    def __init__(self, github: FakeGitHub, event_bus: EventBus) -> None:
        self._github = github
        self._bus = event_bus

    @classmethod
    def from_seed(cls, seed: MockWorldSeed, event_bus: EventBus) -> FakeIssueStore:
        from mockworld.fakes.fake_github import FakeGitHub

        # Until FakeGitHub.from_seed lands in Task 1.6, build inline.
        github = FakeGitHub()
        for issue_dict in seed.issues:
            github.add_issue(
                number=issue_dict["number"],
                title=issue_dict["title"],
                body=issue_dict["body"],
                labels=list(issue_dict.get("labels", [])),
            )
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
