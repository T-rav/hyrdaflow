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
    updated_at: str = "2026-01-01T00:00:00Z"


@dataclass
class FakePR:
    number: int
    issue_number: int
    branch: str
    merged: bool = False
    ci_status: str = "pass"
    draft: bool = False
    url: str = ""
    mergeable: bool = True
    additions: int = 0
    deletions: int = 0
    reviews: list[tuple[str, str]] = field(default_factory=list)
    checks: list[tuple[str, str]] = field(default_factory=list)


class FakeGitHub:
    """Stateful fake for GitHub API (PRManager + IssueFetcher)."""

    def __init__(self) -> None:
        self._issues: dict[int, FakeIssue] = {}
        self._prs: dict[int, FakePR] = {}
        self._pr_counter = 10_000
        self._ci_scripts: dict[int, deque[tuple[bool, str]]] = {}
        self._comments: list[tuple[int, str]] = []
        self._ci_main_status: tuple[str, str] = ("success", "")

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

    def set_ci_main_status(self, conclusion: str, url: str = "") -> None:
        """Script the response for get_latest_ci_status (main branch CI)."""
        self._ci_main_status = (conclusion, url)

    def set_issue_updated_at(self, issue_number: int, updated_at: str) -> None:
        """Set the updated_at timestamp on a seeded issue."""
        if issue_number in self._issues:
            self._issues[issue_number].updated_at = updated_at

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
        self,
        issue_number: int,
        new_stage: str,
        *,
        pr_number: int | None = None,
    ) -> None:
        _ = pr_number
        stage_label_map = {
            "find": "hydraflow-find",
            "triage": "hydraflow-triage",
            "plan": "hydraflow-plan",
            "ready": "hydraflow-ready",
            "review": "hydraflow-review",
            "done": "hydraflow-done",
            "hitl": "hydraflow-hitl",
        }
        new_label = stage_label_map.get(new_stage, new_stage)
        if issue_number in self._issues:
            issue = self._issues[issue_number]
            issue.labels = [
                lbl for lbl in issue.labels if not lbl.startswith("hydraflow-")
            ]
            issue.labels.append(new_label)

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
        self, pr_number: int, verdict_or_body: Any = "", body: str = "", **_kw: Any
    ) -> bool:
        """Accept both (pr, body, event) from phases and (pr, verdict, body) from loops."""
        return True

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

    async def push_branch(
        self,
        *args: Any,
        **_kwargs: Any,
    ) -> bool:
        _ = args
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
        # No open PR for this branch — signal absence with number=0
        return PRInfoFactory.create(
            number=0,
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

    # --- Loop-required PRPort methods ---

    async def list_issues_by_label(self, label: str) -> list[dict[str, Any]]:
        """Return open issues carrying *label* as GitHubIssueSummary-style dicts."""
        return [
            {
                "number": issue.number,
                "title": issue.title,
                "body": issue.body,
                "updated_at": getattr(issue, "updated_at", "2026-01-01T00:00:00Z"),
            }
            for issue in self._issues.values()
            if issue.state == "open" and label in issue.labels
        ]

    async def get_issue_updated_at(self, issue_number: int) -> str:
        """Return updated_at timestamp for an issue."""
        if issue_number in self._issues:
            return getattr(
                self._issues[issue_number], "updated_at", "2026-01-01T00:00:00Z"
            )
        return ""

    async def get_issue_state(self, issue_number: int) -> str:
        """Return issue state as GitHub GraphQL style (OPEN/COMPLETED)."""
        if issue_number in self._issues:
            state = self._issues[issue_number].state
            return "COMPLETED" if state == "closed" else "OPEN"
        return "OPEN"

    async def list_hitl_items(
        self, hitl_labels: list[str], *, concurrency: int = 10
    ) -> list[Any]:
        """Return HITLItem-compatible objects for issues with HITL labels."""
        from models import HITLItem

        items: list[HITLItem] = []
        for issue in self._issues.values():
            if issue.state != "open":
                continue
            if any(lbl in issue.labels for lbl in hitl_labels):
                pr = self.pr_for_issue(issue.number)
                items.append(
                    HITLItem(
                        issue=issue.number,
                        title=issue.title,
                        pr=pr.number if pr else 0,
                        branch=pr.branch if pr else "",
                        cause="ci_failure",
                    )
                )
        return items

    async def get_latest_ci_status(self) -> tuple[str, str]:
        """Return (conclusion, url) for latest CI on main branch."""
        return self._ci_main_status

    async def create_issue(
        self,
        title: str,
        body: str,
        labels: list[str] | None = None,
        **_unused: Any,
    ) -> int:
        """Create a new issue and return its number."""
        num = max(self._issues.keys(), default=9000) + 1
        self.add_issue(num, title, body, labels=labels)
        return num

    async def get_dependabot_alerts(self, **_kw: Any) -> list[dict[str, Any]]:
        """Return Dependabot alerts."""
        return []

    # --- Additional PRPort methods for port conformance (phase 1) ---

    @staticmethod
    def expected_pr_title(issue_number: int, issue_title: str) -> str:
        return f"[#{issue_number}] {issue_title}"

    async def get_pr_mergeable(self, pr_number: int) -> bool | None:
        return True

    async def pull_main(self, **_kw: Any) -> None:
        pass

    async def update_issue_body(self, issue_number: int, body: str) -> None:
        if issue_number in self._issues:
            self._issues[issue_number].body = body

    async def update_pr_title(self, pr_number: int, title: str) -> bool:
        return True

    async def upload_screenshot(self, **_kw: Any) -> str:
        return ""

    # --- Staging / RC promotion PRPort methods ---

    async def create_rc_branch(self, rc_branch: str) -> str:
        return f"sha-{rc_branch}"

    async def create_promotion_pr(
        self, *, rc_branch: str, title: str, body: str, **_kw: Any
    ) -> int:
        _ = (title, body)
        num = self._pr_counter
        self._pr_counter += 1
        self._prs[num] = FakePR(
            number=num,
            issue_number=0,
            branch=rc_branch,
            draft=False,
            url=f"https://github.com/test/repo/pull/{num}",
        )
        return num

    async def find_open_promotion_pr(self) -> Any:
        return None

    async def merge_promotion_pr(self, pr_number: int) -> bool:
        if pr_number in self._prs:
            self._prs[pr_number].merged = True
        return True

    async def list_rc_branches(self) -> list[tuple[str, str]]:
        return []

    async def delete_branch(self, branch: str) -> bool:
        _ = branch
        return True

    async def list_recent_promotion_prs(self, days: int = 7) -> list[dict[str, Any]]:
        _ = days
        return []

    async def ensure_branch_exists(self, branch: str, *, base: str) -> bool:
        _ = (branch, base)
        return False

    async def apply_staging_branch_protection(self, branch: str) -> dict[str, Any]:
        return {"status": "protected", "branch": branch}
