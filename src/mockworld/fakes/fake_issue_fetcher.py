"""FakeIssueFetcher — IssueFetcherPort impl backed by FakeGitHub state.

Extracted from `tests/scenarios/fakes/mock_world.py:_wire_targets`,
which previously monkeypatched the real IssueFetcher with FakeGitHub
methods. Now FakeIssueFetcher is a standalone class that satisfies
IssueFetcherPort and can be passed via build_services() override.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mockworld.seed import MockWorldSeed

    from mockworld.fakes.fake_github import FakeGitHub


@dataclass
class FakeIssueSummary:
    """Minimal IssueFetcher-shaped payload."""

    number: int
    title: str
    body: str
    labels: list[str]
    state: str = "OPEN"


class FakeIssueFetcher:
    """IssueFetcherPort implementation reading from FakeGitHub state."""

    _is_fake_adapter = True

    def __init__(self, github: FakeGitHub) -> None:
        self._github = github

    @classmethod
    def from_seed(cls, seed: MockWorldSeed) -> FakeIssueFetcher:
        """Build a FakeIssueFetcher from a serialized seed.

        Constructs an internal FakeGitHub from the seed's issue list
        and wraps it. Same semantics as constructing FakeGitHub.from_seed
        and passing it in. (FakeGitHub.from_seed lands in Task 1.6.)
        """
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
        return cls(github=github)

    async def fetch_open_issues_by_label(self, label: str) -> list[FakeIssueSummary]:
        out = []
        for issue in self._github._issues.values():
            if issue.state != "open":
                continue
            if label not in issue.labels:
                continue
            out.append(
                FakeIssueSummary(
                    number=issue.number,
                    title=issue.title,
                    body=issue.body,
                    labels=list(issue.labels),
                )
            )
        return out
