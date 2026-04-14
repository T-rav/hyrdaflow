"""PRBuilder — chainable, immutable test-data builder for GitHub PRs."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tests.scenarios.fakes.mock_world import MockWorld


@dataclass(frozen=True)
class _Check:
    name: str
    status: str  # "success" | "failure" | "pending"


@dataclass(frozen=True)
class _Review:
    reviewer: str
    verdict: str  # "APPROVED" | "REQUEST_CHANGES" | "COMMENT"


@dataclass(frozen=True)
class PRBuilder:
    _issue_number: int | None = None
    _branch: str = "hydraflow/test-branch"
    _files: tuple[str, ...] = ()
    _additions: int = 1
    _deletions: int = 0
    _ci_status: str = "success"
    _reviews: tuple[_Review, ...] = field(default_factory=tuple)
    _checks: tuple[_Check, ...] = field(default_factory=tuple)
    _mergeable: bool = True

    def for_issue(self, issue_number: int) -> PRBuilder:
        return replace(self, _issue_number=issue_number)

    def on_branch(self, branch: str) -> PRBuilder:
        return replace(self, _branch=branch)

    def with_diff(
        self, *, files: list[str], additions: int = 1, deletions: int = 0
    ) -> PRBuilder:
        return replace(
            self, _files=tuple(files), _additions=additions, _deletions=deletions
        )

    def with_ci_status(self, status: str) -> PRBuilder:
        return replace(self, _ci_status=status)

    def with_review(self, reviewer: str, verdict: str) -> PRBuilder:
        return replace(self, _reviews=(*self._reviews, _Review(reviewer, verdict)))

    def with_check(self, name: str, status: str) -> PRBuilder:
        return replace(self, _checks=(*self._checks, _Check(name, status)))

    def mergeable(self, value: bool = True) -> PRBuilder:
        return replace(self, _mergeable=value)

    async def at(self, world: MockWorld) -> Any:
        """Seed the world's GitHub fake and return the FakePR record."""
        if self._issue_number is None:
            msg = "PRBuilder requires .for_issue(N) before .at(world)"
            raise ValueError(msg)

        # Look up the seeded issue; FakeGitHub.create_pr expects an issue-like
        # object with .id / .number.
        fake_issue = world.github.issue(self._issue_number)
        await world.github.create_pr(issue=fake_issue, branch=self._branch)

        # Retrieve the FakePR record; apply optional state attributes.
        pr = world.github.pr_for_issue(self._issue_number)
        if pr is None:
            msg = f"create_pr did not seed a PR for issue {self._issue_number}"
            raise AssertionError(msg)

        for attr, value in (
            ("additions", self._additions),
            ("deletions", self._deletions),
            ("ci_status", self._ci_status),
            ("mergeable", self._mergeable),
        ):
            if hasattr(pr, attr):
                setattr(pr, attr, value)  # noqa: B010
        if hasattr(pr, "reviews"):
            setattr(  # noqa: B010
                pr,
                "reviews",
                [(r.reviewer, r.verdict) for r in self._reviews],
            )
        if hasattr(pr, "checks"):
            setattr(  # noqa: B010
                pr,
                "checks",
                [(c.name, c.status) for c in self._checks],
            )
        return pr
