"""Stateful GitHub fake for scenario testing.

Tracks issues (labels, state, comments) and PRs (merged, CI status)
as in-memory state. Implements the async PRManager interface methods
that phases call via PipelineHarness.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from mockworld.fakes._factories import PRInfoFactory

if TYPE_CHECKING:
    from mockworld.seed import MockWorldSeed


class RateLimitError(Exception):
    """Raised by FakeGitHub when rate-limit mode is exhausted.

    `secondary=True` represents GitHub's abuse-detection variant, which
    production code handles differently from primary rate limits.
    """

    def __init__(self, reset_in: int = 60, *, secondary: bool = False) -> None:
        self.reset_in = reset_in
        self.secondary = secondary
        suffix = " (secondary)" if secondary else ""
        super().__init__(f"FakeGitHub rate limit{suffix}; reset in {reset_in}s")


@dataclass
class FakeIssue:
    number: int
    title: str
    body: str
    labels: list[str] = field(default_factory=list)
    state: str = "open"
    # Stored as raw bodies; list_issue_comments wraps each into a
    # `gh issue view --json comments`-shaped dict. Tests that need richer
    # comment metadata (author, timestamp) can post-process this list.
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
    labels: list[str] = field(default_factory=list)


class FakeGitHub:
    """Stateful fake for GitHub API (PRManager + IssueFetcher)."""

    _is_fake_adapter = True  # read by dashboard for MOCKWORLD banner

    def __init__(self) -> None:
        self._issues: dict[int, FakeIssue] = {}
        self._prs: dict[int, FakePR] = {}
        self._pr_counter = 10_000
        self._ci_scripts: dict[int, deque[tuple[bool, str]]] = {}
        self._comments: list[tuple[int, str]] = []
        self._ci_main_status: tuple[str, str] = ("success", "")
        self._rate_limit_remaining: int | None = None  # None = disabled
        self._rate_limit_reset_in: int = 60
        self._rate_limit_secondary: bool = False
        self._alerts: dict[str, list[Any]] = {}

    @classmethod
    def from_seed(cls, seed: MockWorldSeed) -> FakeGitHub:
        """Construct a FakeGitHub populated from a MockWorldSeed."""
        gh = cls()
        for issue_dict in seed.issues:
            gh.add_issue(
                number=issue_dict["number"],
                title=issue_dict["title"],
                body=issue_dict["body"],
                labels=list(issue_dict.get("labels", [])),
            )
        for pr_dict in seed.prs:
            gh.add_pr(
                number=pr_dict["number"],
                issue_number=pr_dict["issue_number"],
                branch=pr_dict["branch"],
                ci_status=pr_dict.get("ci_status", "pass"),
                merged=pr_dict.get("merged", False),
            )
            for label in pr_dict.get("labels", []):
                gh.add_pr_label(pr_dict["number"], label)
        return gh

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

    def add_pr(
        self,
        *,
        number: int,
        issue_number: int,
        branch: str,
        ci_status: str = "pass",
        merged: bool = False,
    ) -> None:
        """Directly insert a PR record (sync helper for test seeding).

        The async ``create_pr`` handles the production path; this helper
        exists so scenario seeds can set up a fully-populated world
        synchronously.
        """
        self._prs[number] = FakePR(
            number=number,
            issue_number=issue_number,
            branch=branch,
            merged=merged,
            ci_status=ci_status,
        )

    def add_pr_label(self, pr_number: int, label: str) -> None:
        """Seed-API helper: attach a label to a fake PR."""
        if pr_number not in self._prs:
            raise KeyError(f"FakeGitHub: no PR {pr_number}")
        pr = self._prs[pr_number]
        if label not in pr.labels:
            pr.labels.append(label)

    def add_alerts(self, *, branch: str, alerts: list[Any]) -> None:
        """Script code-scanning alerts returned by fetch_code_scanning_alerts."""
        self._alerts[branch] = list(alerts)

    def script_ci(self, pr_number: int, results: list[tuple[bool, str]]) -> None:
        self._ci_scripts[pr_number] = deque(results)

    def set_ci_main_status(self, conclusion: str, url: str = "") -> None:
        """Script the response for get_latest_ci_status (main branch CI)."""
        self._ci_main_status = (conclusion, url)

    def set_issue_updated_at(self, issue_number: int, updated_at: str) -> None:
        """Set the updated_at timestamp on a seeded issue."""
        if issue_number in self._issues:
            self._issues[issue_number].updated_at = updated_at

    def set_rate_limit_mode(
        self,
        *,
        remaining: int = 0,
        reset_in: int = 60,
        secondary: bool = False,
    ) -> None:
        """Enable rate-limit gating; next *remaining* calls succeed, then raise."""
        self._rate_limit_remaining = remaining
        self._rate_limit_reset_in = reset_in
        self._rate_limit_secondary = secondary

    def clear_rate_limit(self) -> None:
        self._rate_limit_remaining = None
        self._rate_limit_secondary = False

    def _maybe_rate_limit(self) -> None:
        if self._rate_limit_remaining is None:
            return
        if self._rate_limit_remaining <= 0:
            raise RateLimitError(
                reset_in=self._rate_limit_reset_in,
                secondary=self._rate_limit_secondary,
            )
        self._rate_limit_remaining -= 1

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
        self._maybe_rate_limit()
        _ = pr_number
        stage_label_map = {
            "find": "hydraflow-find",
            "triage": "hydraflow-triage",
            "discover": "hydraflow-discover",
            "shape": "hydraflow-shape",
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

    async def swap_pipeline_labels(
        self,
        issue_number: int,
        new_label: str,
        *,
        pr_number: int | None = None,
    ) -> None:
        self._maybe_rate_limit()
        _ = pr_number
        if issue_number in self._issues:
            issue = self._issues[issue_number]
            issue.labels = [
                lbl for lbl in issue.labels if not lbl.startswith("hydraflow-")
            ]
            issue.labels.append(new_label)

    async def add_labels(self, issue_number: int, labels: list[str]) -> None:
        self._maybe_rate_limit()
        if issue_number in self._issues:
            for label in labels:
                if label not in self._issues[issue_number].labels:
                    self._issues[issue_number].labels.append(label)

    async def remove_label(self, issue_number: int, label: str) -> None:
        self._maybe_rate_limit()
        if issue_number in self._issues:
            issue = self._issues[issue_number]
            issue.labels = [lbl for lbl in issue.labels if lbl != label]

    async def post_comment(self, issue_number: int, body: str) -> None:
        self._maybe_rate_limit()
        self._comments.append((issue_number, body))
        if issue_number in self._issues:
            self._issues[issue_number].comments.append(body)

    async def post_pr_comment(self, pr_number: int, body: str) -> None:
        self._maybe_rate_limit()
        self._comments.append((pr_number, body))

    async def submit_review(
        self, pr_number: int, verdict: Any, body: str, **_kw: Any
    ) -> bool:
        """Submit a formal PR review (no-op stub — always returns True)."""
        self._maybe_rate_limit()
        return True

    async def create_task(
        self, title: str, body: str, labels: list[str] | None = None
    ) -> int:
        self._maybe_rate_limit()
        num = max(self._issues.keys(), default=9000) + 1
        self.add_issue(num, title, body, labels=labels)
        return num

    async def close_task(self, issue_number: int) -> None:
        self._maybe_rate_limit()
        if issue_number in self._issues:
            self._issues[issue_number].state = "closed"

    async def close_issue(self, issue_number: int) -> None:
        self._maybe_rate_limit()
        if issue_number in self._issues:
            self._issues[issue_number].state = "closed"

    async def find_existing_issue(self, title: str) -> int:
        self._maybe_rate_limit()
        for issue in self._issues.values():
            if issue.title == title and issue.state == "open":
                return issue.number
        return 0

    async def push_branch(
        self,
        *args: Any,
        **_kwargs: Any,
    ) -> bool:
        self._maybe_rate_limit()
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
        self._maybe_rate_limit()
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
        self._maybe_rate_limit()
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
        self._maybe_rate_limit()
        return True

    async def add_pr_labels(self, pr_number: int, labels: list[str]) -> None:
        self._maybe_rate_limit()

    async def get_pr_diff(self, pr_number: int) -> str:
        self._maybe_rate_limit()
        return "diff --git a/x b/x"

    async def get_pr_head_sha(self, pr_number: int) -> str:
        self._maybe_rate_limit()
        return "abc123"

    async def get_pr_diff_names(self, pr_number: int) -> list[str]:
        self._maybe_rate_limit()
        return ["src/app.py"]

    async def get_pr_approvers(self, pr_number: int) -> list[str]:
        self._maybe_rate_limit()
        return ["octocat"]

    async def fetch_code_scanning_alerts(self, branch: str, **_kw: Any) -> list:
        self._maybe_rate_limit()
        return list(self._alerts.get(branch, []))

    async def wait_for_ci(
        self, pr_number: int, *_args: Any, **_kw: Any
    ) -> tuple[bool, str]:
        self._maybe_rate_limit()
        q = self._ci_scripts.get(pr_number)
        if q:
            return q.popleft()
        return (True, "CI passed")

    async def fetch_ci_failure_logs(self, pr_number: int, **_kw: Any) -> str:
        self._maybe_rate_limit()
        return ""

    async def merge_pr(self, pr_number: int, **_kw: Any) -> bool:
        self._maybe_rate_limit()
        if pr_number in self._prs:
            self._prs[pr_number].merged = True
        return True

    # --- Loop-required PRPort methods ---

    async def list_issues_by_label(self, label: str) -> list[dict[str, Any]]:
        """Return open issues carrying *label* as GitHubIssueSummary-style dicts."""
        self._maybe_rate_limit()
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

    async def list_closed_issues_by_label(
        self,
        label: str,
        *,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Return closed issues carrying *label* (most recent up to *limit*)."""
        self._maybe_rate_limit()
        rows = [
            {
                "number": issue.number,
                "title": issue.title,
                "body": issue.body,
                "updated_at": getattr(issue, "updated_at", "2026-01-01T00:00:00Z"),
            }
            for issue in self._issues.values()
            if issue.state != "open" and label in issue.labels
        ]
        return rows[:limit]

    async def list_prs_by_label(self, label: str) -> list[Any]:
        """Return open (non-merged) PRs carrying *label*.

        Mirrors ``PRManager.list_prs_by_label`` (which delegates to
        ``gh pr list --label <label> --state open``). Used by
        SandboxFailureFixerLoop to poll auto-fix candidates.
        """
        self._maybe_rate_limit()
        out: list[Any] = []
        for pr in self._prs.values():
            if pr.merged:
                continue
            if label not in pr.labels:
                continue
            out.append(
                PRInfoFactory.create(
                    number=pr.number,
                    issue_number=pr.issue_number,
                    branch=pr.branch,
                    draft=pr.draft,
                )
            )
        return out

    async def list_issue_comments(self, issue_number: int) -> list[dict[str, Any]]:
        """Return comments seeded on the issue (oldest first).

        FakeIssue.comments stores raw body strings; this method wraps each
        into a `gh issue view --json comments`-shaped dict so callers (notably
        gather_context, which does `c.get("user", {}).get("login", ...)`)
        operate on dicts as the real PRPort contract requires.
        """
        self._maybe_rate_limit()
        issue = self._issues.get(issue_number)
        if issue is None:
            return []
        return [
            {
                "user": {"login": "fake-author"},
                "body": body,
                "created_at": "2026-01-01T00:00:00Z",
            }
            for body in (getattr(issue, "comments", []) or [])
        ]

    async def get_issue_updated_at(self, issue_number: int) -> str:
        """Return updated_at timestamp for an issue."""
        self._maybe_rate_limit()
        if issue_number in self._issues:
            return getattr(
                self._issues[issue_number], "updated_at", "2026-01-01T00:00:00Z"
            )
        return ""

    async def get_issue_state(self, issue_number: int) -> str:
        """Return issue state as GitHub GraphQL style (OPEN/COMPLETED)."""
        self._maybe_rate_limit()
        if issue_number in self._issues:
            state = self._issues[issue_number].state
            return "COMPLETED" if state == "closed" else "OPEN"
        return "OPEN"

    async def list_hitl_items(
        self, hitl_labels: list[str], *, concurrency: int = 10
    ) -> list[Any]:
        """Return HITLItem-compatible objects for issues with HITL labels."""
        self._maybe_rate_limit()
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
        self._maybe_rate_limit()
        return self._ci_main_status

    async def create_issue(
        self,
        title: str,
        body: str,
        labels: list[str] | None = None,
        **_unused: Any,
    ) -> int:
        """Create a new issue and return its number."""
        self._maybe_rate_limit()
        num = max(self._issues.keys(), default=9000) + 1
        self.add_issue(num, title, body, labels=labels)
        return num

    async def get_dependabot_alerts(self, **_kw: Any) -> list[dict[str, Any]]:
        """Return Dependabot alerts."""
        self._maybe_rate_limit()
        return []

    # --- Additional PRPort methods for port conformance (phase 1) ---

    @staticmethod
    def expected_pr_title(issue_number: int, issue_title: str) -> str:
        return f"[#{issue_number}] {issue_title}"

    async def get_pr_mergeable(self, pr_number: int) -> bool | None:
        self._maybe_rate_limit()
        return True

    async def pull_main(self, **_kw: Any) -> None:
        self._maybe_rate_limit()

    async def update_issue_body(self, issue_number: int, body: str) -> None:
        self._maybe_rate_limit()
        if issue_number in self._issues:
            self._issues[issue_number].body = body

    async def update_pr_title(self, pr_number: int, title: str) -> bool:
        self._maybe_rate_limit()
        return True

    async def upload_screenshot(self, **_kw: Any) -> str:
        self._maybe_rate_limit()
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
