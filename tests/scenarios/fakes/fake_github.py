"""Stateful GitHub fake for scenario testing.

Tracks issues (labels, state, comments) and PRs (merged, CI status)
as in-memory state. Implements the async PRManager interface methods
that phases call via PipelineHarness.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from tests.conftest import PRInfoFactory


@dataclass
class FakeIssue:
    number: int
    title: str
    body: str
    labels: list[str] = field(default_factory=list)
    state: str = "open"
    comments: list[str] = field(default_factory=list)


@dataclass
class FakePR:
    number: int
    issue_number: int
    branch: str
    merged: bool = False
    ci_status: str = "pass"
    draft: bool = False
    url: str = ""


class FakeGitHub:
    """Stateful fake for GitHub API (PRManager + IssueFetcher)."""

    def __init__(self) -> None:
        self._issues: dict[int, FakeIssue] = {}
        self._prs: dict[int, FakePR] = {}
        self._pr_counter = 10_000
        self._ci_scripts: dict[int, deque[tuple[bool, str]]] = {}
        self._comments: list[tuple[int, str]] = []

    # --- Seed API ---

    def add_issue(
        self,
        number: int,
        title: str,
        body: str,
        labels: list[str] | None = None,
    ) -> None:
        self._issues[number] = FakeIssue(
            number=number,
            title=title,
            body=body,
            labels=labels or [],
        )

    def script_ci(self, pr_number: int, results: list[tuple[bool, str]]) -> None:
        self._ci_scripts[pr_number] = deque(results)

    # --- Query API ---

    def issue(self, number: int) -> FakeIssue:
        if number not in self._issues:
            msg = f"FakeGitHub: no issue {number}"
            raise KeyError(msg)
        return self._issues[number]

    def pr(self, number: int) -> FakePR:
        if number not in self._prs:
            msg = f"FakeGitHub: no PR {number}"
            raise KeyError(msg)
        return self._prs[number]

    def pr_for_issue(self, issue_number: int) -> FakePR | None:
        for p in self._prs.values():
            if p.issue_number == issue_number:
                return p
        return None

    # --- PRManager interface (async methods called by phases) ---

    async def transition(
        self, issue_number: int, from_label: str, to_label: str
    ) -> None:
        if issue_number in self._issues:
            issue = self._issues[issue_number]
            if from_label in issue.labels:
                issue.labels.remove(from_label)
            if to_label not in issue.labels:
                issue.labels.append(to_label)

    async def swap_pipeline_labels(self, issue_number: int, new_label: str) -> None:
        if issue_number in self._issues:
            issue = self._issues[issue_number]
            issue.labels = [
                lbl for lbl in issue.labels if not lbl.startswith("hydraflow-")
            ]
            issue.labels.append(new_label)

    async def add_labels(self, issue_number: int, labels: list[str]) -> None:
        if issue_number in self._issues:
            for label in labels:
                if label not in self._issues[issue_number].labels:
                    self._issues[issue_number].labels.append(label)

    async def remove_label(self, issue_number: int, label: str) -> None:
        if issue_number in self._issues:
            issue = self._issues[issue_number]
            issue.labels = [lbl for lbl in issue.labels if lbl != label]

    async def post_comment(self, issue_number: int, body: str) -> None:
        self._comments.append((issue_number, body))
        if issue_number in self._issues:
            self._issues[issue_number].comments.append(body)

    async def post_pr_comment(self, pr_number: int, body: str) -> None:
        self._comments.append((pr_number, body))

    async def submit_review(
        self, pr_number: int, body: str, event: str = "COMMENT"
    ) -> None:
        pass

    async def create_task(
        self, title: str, body: str, labels: list[str] | None = None
    ) -> int:
        num = max(self._issues.keys(), default=9000) + 1
        self.add_issue(num, title, body, labels=labels)
        return num

    async def close_task(self, issue_number: int) -> None:
        await self.close_issue(issue_number)

    async def close_issue(self, issue_number: int) -> None:
        if issue_number in self._issues:
            self._issues[issue_number].state = "closed"

    async def find_existing_issue(self, title: str) -> int:
        for issue in self._issues.values():
            if issue.title == title and issue.state == "open":
                return issue.number
        return 0

    async def push_branch(self, branch: str, worktree_path: Any = None) -> bool:
        return True

    async def create_pr(
        self,
        issue: Any,
        branch: str,
        *,
        draft: bool = False,
        **_unused: Any,
    ) -> Any:
        number = self._pr_counter
        self._pr_counter += 1
        issue_number = getattr(issue, "id", getattr(issue, "number", 0))
        self._prs[number] = FakePR(
            number=number,
            issue_number=issue_number,
            branch=branch,
            draft=draft,
            url=f"https://github.com/test/repo/pull/{number}",
        )
        return PRInfoFactory.create(
            number=number,
            issue_number=issue_number,
            branch=branch,
            draft=draft,
        )

    async def find_open_pr_for_branch(
        self,
        branch: str,
        *,
        issue_number: int | None = None,
        **_unused: Any,
    ) -> Any:
        for p in self._prs.values():
            if p.branch == branch and not p.merged:
                return PRInfoFactory.create(
                    number=p.number,
                    issue_number=p.issue_number,
                    branch=p.branch,
                )
        number = self._pr_counter
        self._pr_counter += 1
        return PRInfoFactory.create(
            number=number,
            issue_number=issue_number or 0,
            branch=branch,
        )

    async def branch_has_diff_from_main(self, branch: str) -> bool:
        return True

    async def add_pr_labels(self, pr_number: int, labels: list[str]) -> None:
        pass

    async def get_pr_diff(self, pr_number: int) -> str:
        return "diff --git a/x b/x"

    async def get_pr_head_sha(self, pr_number: int) -> str:
        return "abc123"

    async def get_pr_diff_names(self, pr_number: int) -> list[str]:
        return ["src/app.py"]

    async def get_pr_approvers(self, pr_number: int) -> list[str]:
        return ["octocat"]

    async def fetch_code_scanning_alerts(self, pr_number: int = 0, **_kw: Any) -> list:
        return []

    async def wait_for_ci(self, pr_number: int, **_kw: Any) -> tuple[bool, str]:
        q = self._ci_scripts.get(pr_number)
        if q:
            return q.popleft()
        return (True, "CI passed")

    async def fetch_ci_failure_logs(self, pr_number: int, **_kw: Any) -> str:
        return ""

    async def merge_pr(self, pr_number: int, **_kw: Any) -> bool:
        if pr_number in self._prs:
            self._prs[pr_number].merged = True
        return True
