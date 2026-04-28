"""FakeIssueFetcher — IssueFetcherPort impl backed by FakeGitHub state.

Standalone class created for the sandbox entrypoint (Task 1.10), which
constructs Fakes via build_services() overrides — monkeypatching only
works in-process and can't reach the docker container.

Task 2.5b widening: now satisfies both ``IssueFetcherPort``
(``fetch_issue_by_number``, ``fetch_issues_by_labels``) and the
concrete-only methods that orchestrator-side machinery dispatches
without going through the Port:

- ``fetch_all_hydraflow_issues`` — used by ``GitHubTaskFetcher`` and
  ``IssueStore.refresh()``. Returns all open issues carrying any
  ``hydraflow-*`` lifecycle label.
- ``fetch_issue_comments`` — used by ``IssueStore.enrich_with_comments``
  to fetch comment bodies for an issue.
- ``fetch_open_issues_by_label`` — PR A's narrower surface, kept for
  the Fake unit tests that predate the widening.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from models import GitHubIssue

if TYPE_CHECKING:
    from mockworld.fakes.fake_github import FakeGitHub
    from mockworld.seed import MockWorldSeed


# Lifecycle labels recognized by HydraFlow's IssueStore. Mirrors the
# config defaults — the Fake doesn't read HydraFlowConfig, so it
# hardcodes the canonical set. Any production-side label-rename would
# need to be reflected here too.
HYDRAFLOW_LABELS = (
    "hydraflow-find",
    "hydraflow-discover",
    "hydraflow-shape",
    "hydraflow-plan",
    "hydraflow-ready",
    "hydraflow-review",
    "hydraflow-hitl",
)


@dataclass
class FakeIssueSummary:
    """Minimal IssueFetcher-shaped payload (PR A's narrower surface)."""

    number: int
    title: str
    body: str
    labels: list[str]
    state: str = "OPEN"


class FakeIssueFetcher:
    """In-memory IssueFetcherPort impl backed by a FakeGitHub world."""

    _is_fake_adapter = True

    def __init__(self, github: FakeGitHub) -> None:
        self._github = github

    @classmethod
    def from_seed(cls, seed: MockWorldSeed) -> FakeIssueFetcher:
        from mockworld.fakes.fake_github import FakeGitHub

        github = FakeGitHub.from_seed(seed)
        return cls(github=github)

    def _to_github_issue(self, issue: object) -> GitHubIssue:
        return GitHubIssue(
            number=issue.number,  # type: ignore[attr-defined]
            title=issue.title,  # type: ignore[attr-defined]
            body=issue.body,  # type: ignore[attr-defined]
            labels=list(issue.labels),  # type: ignore[attr-defined]
            comments=list(getattr(issue, "comments", [])),
            url="",
            author="fake-author",
            state=("open" if issue.state == "open" else "closed"),  # type: ignore[attr-defined]
            created_at="",
        )

    # ------------------------------------------------------------------
    # IssueFetcherPort (the canonical surface)
    # ------------------------------------------------------------------

    async def fetch_issue_by_number(self, issue_number: int) -> GitHubIssue | None:
        issue = self._github._issues.get(issue_number)
        if issue is None:
            return None
        return self._to_github_issue(issue)

    async def fetch_issues_by_labels(
        self,
        labels: list[str],
        limit: int,
        exclude_labels: list[str] | None = None,
        require_complete: bool = False,
    ) -> list[GitHubIssue]:
        """Return open issues matching any *labels*, deduplicated.

        ``require_complete`` is honored as a no-op (the Fake never returns
        partial results because there's no rate-limit / pagination edge).
        """
        _ = require_complete  # Fake never partially fetches
        excluded = set(exclude_labels or [])
        wanted = set(labels)

        out: list[GitHubIssue] = []
        for issue in self._github._issues.values():
            if issue.state != "open":
                continue
            issue_labels = set(issue.labels)
            # Empty labels with exclude_labels means "all open issues
            # except those carrying excluded labels" — mirrors the real
            # IssueFetcher's documented contract.
            if wanted and not (wanted & issue_labels):
                continue
            if excluded and (excluded & issue_labels):
                continue
            out.append(self._to_github_issue(issue))
            if len(out) >= limit:
                break
        return out

    # ------------------------------------------------------------------
    # Concrete-only IssueFetcher methods (called via duck-typing,
    # not via the Port)
    # ------------------------------------------------------------------

    async def fetch_all_hydraflow_issues(self) -> list[GitHubIssue]:
        """Return open issues carrying any HydraFlow lifecycle label.

        Used by ``GitHubTaskFetcher`` (which wraps an IssueFetcher and
        feeds the IssueStore poller). The Fake hardcodes the lifecycle
        label set; see module-level ``HYDRAFLOW_LABELS``.
        """
        return await self.fetch_issues_by_labels(list(HYDRAFLOW_LABELS), limit=500)

    async def fetch_issue_comments(self, issue_number: int) -> list[str]:
        """Return raw comment bodies seeded on *issue_number*."""
        issue = self._github._issues.get(issue_number)
        if issue is None:
            return []
        return list(getattr(issue, "comments", []))

    async def fetch_reviewable_prs(
        self,
        active_issues: set[int],
        prefetched_issues: list[GitHubIssue] | None = None,
    ) -> tuple[list[object], list[GitHubIssue]]:
        """Resolve ``hydraflow-review``-labeled issues into (PRInfo, issue) pairs.

        Mirrors ``IssueFetcher.fetch_reviewable_prs``: returns the open
        non-draft PRs whose branch matches ``agent/issue-{N}``. The Fake
        derives the (issue, PR) pairs from FakeGitHub's ``_prs`` map.
        """
        from mockworld.fakes._factories import PRInfoFactory

        if prefetched_issues is not None:
            issues = [i for i in prefetched_issues if i.number not in active_issues]
        else:
            issues = await self.fetch_issues_by_labels(["hydraflow-review"], limit=200)
            issues = [i for i in issues if i.number not in active_issues]

        if not issues:
            return [], []

        pr_infos: list[object] = []
        for issue in issues:
            for pr in self._github._prs.values():
                if pr.merged or pr.draft:
                    continue
                if pr.issue_number == issue.number:
                    pr_infos.append(
                        PRInfoFactory.create(
                            number=pr.number,
                            issue_number=pr.issue_number,
                            branch=pr.branch,
                            draft=pr.draft,
                        )
                    )
                    break
        return pr_infos, issues

    async def _get_collaborators(self) -> set[str] | None:
        """Return None (fail-open) — sandbox has no collaborator concept.

        Production fetches ``repos/{repo}/collaborators`` and caches the
        login set so the issue fetcher can drop non-collaborator triage
        spam. The Fake doesn't model collaborators; returning ``None``
        signals "check disabled" in the production code path.
        """
        return None

    # ------------------------------------------------------------------
    # PR A's narrower surface (kept for back-compat with Fake unit tests)
    # ------------------------------------------------------------------

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
