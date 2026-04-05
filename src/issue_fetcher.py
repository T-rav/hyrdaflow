"""GitHub issue fetching for the HydraFlow orchestrator."""

from __future__ import annotations

import asyncio
import json
import logging
import random
from datetime import UTC, datetime, timedelta
from typing import Any

from config import Credentials, HydraFlowConfig
from models import GitHubIssue, PRInfo, Task
from subprocess_util import run_subprocess

logger = logging.getLogger("hydraflow.issue_fetcher")


class IncompleteIssueFetchError(RuntimeError):
    """Raised when a label-scoped issue fetch could not complete reliably."""


class IssueFetcher:
    """Fetches GitHub issues and PRs via the ``gh`` CLI."""

    def __init__(
        self, config: HydraFlowConfig, credentials: Credentials | None = None
    ) -> None:
        self._config = config
        self._credentials = credentials or Credentials()
        self._repo_owner = config.repo.split("/", 1)[0] if "/" in config.repo else ""
        self._rate_limited_until: datetime | None = None
        self._rate_limit_recovery_attempts = 0
        self._rate_limit_lock = asyncio.Lock()
        self._collaborators: set[str] | None = None
        self._collaborators_fetched_at: datetime | None = None
        self._api_cache_ttl = f"{config.data_poll_interval}s"
        # PR cache: {branch_name: {number, url, isDraft}}
        self._pr_cache: dict[str, dict[str, Any]] | None = None
        self._pr_cache_fetched_at: datetime | None = None

    @staticmethod
    def _normalize_labels(raw: list[Any]) -> list[str]:
        """Flatten label dicts (``{"name": "..."}`` from gh CLI) to plain strings."""
        return [lbl["name"] if isinstance(lbl, dict) else str(lbl) for lbl in raw]

    @staticmethod
    def _normalize_comments(raw: list[Any]) -> list[str]:
        """Flatten comment dicts (``{"body": "..."}`` from gh CLI) to plain strings."""
        return [c.get("body", "") if isinstance(c, dict) else str(c) for c in raw]

    @staticmethod
    def _normalize_graphql_issue(node: dict[str, Any]) -> dict[str, Any]:
        """Map a GraphQL issue node to the GitHubIssue-compatible payload."""
        labels_raw = node.get("labels", {})
        labels = (
            labels_raw.get("nodes", []) if isinstance(labels_raw, dict) else labels_raw
        )
        author_raw = node.get("author") or {}
        author = author_raw.get("login", "") if isinstance(author_raw, dict) else ""
        milestone_raw = node.get("milestone")
        milestone_number = (
            milestone_raw.get("number") if isinstance(milestone_raw, dict) else None
        )
        return {
            "number": node.get("number"),
            "title": node.get("title", ""),
            "body": node.get("body", ""),
            "labels": IssueFetcher._normalize_labels(labels),
            "comments": [],
            "url": node.get("url", ""),
            "state": (node.get("state", "OPEN")).lower(),
            "created_at": node.get("createdAt", ""),
            "author": author,
            "milestone_number": milestone_number,
        }

    @staticmethod
    def _normalize_issue_payload(item: dict[str, Any]) -> dict[str, Any]:
        """Map REST/CLI issue shapes to the GitHubIssue-compatible payload."""
        comments_raw = item.get("comments", [])
        comments: list[Any] = comments_raw if isinstance(comments_raw, list) else []
        user = item.get("user")
        author = user.get("login", "") if isinstance(user, dict) else ""
        milestone_raw = item.get("milestone")
        milestone_number = (
            milestone_raw.get("number") if isinstance(milestone_raw, dict) else None
        )
        return {
            "number": item.get("number"),
            "title": item.get("title", ""),
            "body": item.get("body", ""),
            "labels": IssueFetcher._normalize_labels(item.get("labels", [])),
            "comments": IssueFetcher._normalize_comments(comments),
            "url": item.get("html_url", item.get("url", "")),
            "state": item.get("state", "open"),
            "created_at": item.get("createdAt", item.get("created_at", "")),
            "author": author,
            "milestone_number": milestone_number,
        }

    async def _get_collaborators(self) -> set[str] | None:
        """Fetch and cache the repo's collaborator logins.

        Returns ``None`` on API failure (fail-open).  The cache is
        refreshed after ``collaborator_cache_ttl`` seconds.
        """
        now = datetime.now(UTC)
        if (
            self._collaborators is not None
            and self._collaborators_fetched_at is not None
            and (now - self._collaborators_fetched_at).total_seconds()
            < self._config.collaborator_cache_ttl
        ):
            return self._collaborators

        try:
            raw = await run_subprocess(
                "gh",
                "api",
                f"repos/{self._config.repo}/collaborators",
                "--paginate",
                "--jq",
                ".[].login",
                gh_token=self._credentials.gh_token,
            )
            logins = {line.strip() for line in raw.strip().splitlines() if line.strip()}
            self._collaborators = logins
            self._collaborators_fetched_at = now
            return logins
        except (RuntimeError, json.JSONDecodeError, FileNotFoundError) as exc:
            logger.warning("Could not fetch collaborators (fail-open): %s", exc)
            return None

    def _filter_non_collaborators(
        self,
        issues: list[GitHubIssue],
        collaborators: set[str] | None,
    ) -> list[GitHubIssue]:
        """Remove issues authored by non-collaborators.

        Issues with an empty author pass through.  If *collaborators* is
        ``None`` (API failure), all issues pass through (fail-open).
        """
        if collaborators is None:
            return issues
        result: list[GitHubIssue] = []
        for issue in issues:
            if not issue.author or issue.author in collaborators:
                result.append(issue)
            else:
                logger.warning(
                    "Skipping issue #%d from non-collaborator %s",
                    issue.number,
                    issue.author,
                )
        return result

    async def fetch_issues_by_labels(
        self,
        labels: list[str],
        limit: int,
        exclude_labels: list[str] | None = None,
        require_complete: bool = False,
    ) -> list[GitHubIssue]:
        """Fetch open issues matching *any* of *labels*, deduplicated.

        If *labels* is empty but *exclude_labels* is provided, fetch all
        open issues and filter out those carrying any of the exclude labels.
        When *require_complete* is ``True``, rate-limited/incomplete fetches
        raise :class:`IncompleteIssueFetchError` instead of returning partial
        data.
        """
        if self._config.dry_run:
            logger.info(
                "[dry-run] Would fetch issues with labels=%r exclude=%r",
                labels,
                exclude_labels,
            )
            return []

        seen: dict[int, dict] = {}
        incomplete = False

        async def _query_label(label: str | None) -> None:
            nonlocal incomplete
            if self._is_rate_limited_now():
                incomplete = True
                return
            page = 1
            remaining = max(0, limit)
            while remaining > 0:
                per_page = min(100, remaining)
                cmd = [
                    "gh",
                    "api",
                    f"repos/{self._config.repo}/issues",
                    "--method",
                    "GET",
                    "--cache",
                    self._api_cache_ttl,
                    "--field",
                    "state=open",
                    "--field",
                    "sort=created",
                    "--field",
                    "direction=asc",
                    "--field",
                    f"per_page={per_page}",
                    "--field",
                    f"page={page}",
                ]
                if label is not None:
                    cmd += ["--field", f"labels={label}"]
                try:
                    raw = await run_subprocess(
                        *cmd, gh_token=self._credentials.gh_token
                    )
                    self._note_success_after_rate_limit()
                    items = json.loads(raw)
                    if not isinstance(items, list):
                        break
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        if "pull_request" in item:
                            continue
                        normalized = self._normalize_issue_payload(item)
                        number = normalized.get("number")
                        if isinstance(number, int):
                            seen.setdefault(number, normalized)
                    if len(items) < per_page:
                        break
                    page += 1
                    remaining -= per_page
                except (RuntimeError, json.JSONDecodeError, FileNotFoundError) as exc:
                    if isinstance(exc, RuntimeError) and self._is_rate_limit_error(exc):
                        await self._set_rate_limit_backoff(exc)
                    else:
                        logger.error(
                            "gh issue list failed for label=%r: %s", label, exc
                        )
                    incomplete = True
                    return

        if labels:
            await asyncio.gather(*[_query_label(lbl) for lbl in labels])
        elif exclude_labels:
            await _query_label(None)
            # Remove issues that carry any of the exclude labels
            exclude_set = set(exclude_labels)
            to_remove = []
            for num, raw in seen.items():
                raw_labels = set(raw.get("labels", []))
                if raw_labels & exclude_set:
                    to_remove.append(num)
            for num in to_remove:
                del seen[num]
        else:
            return []

        if require_complete and incomplete:
            raise IncompleteIssueFetchError(
                "GitHub issue fetch incomplete due to rate limiting or API errors"
            )

        issues = [GitHubIssue.model_validate(raw) for raw in seen.values()]
        if self._config.collaborator_check_enabled:
            collaborators = await self._get_collaborators()
            issues = self._filter_non_collaborators(issues, collaborators)
        return issues[:limit]

    def _is_rate_limited_now(self) -> bool:
        until = self._rate_limited_until
        if until is None:
            return False
        now = datetime.now(UTC)
        if now >= until:
            self._rate_limited_until = None
            return False
        return True

    def _note_success_after_rate_limit(self) -> None:
        self._rate_limit_recovery_attempts = 0

    @staticmethod
    def _is_rate_limit_error(exc: RuntimeError) -> bool:
        return "rate limit" in str(exc).lower()

    async def _set_rate_limit_backoff(self, exc: RuntimeError) -> None:
        async with self._rate_limit_lock:
            if self._is_rate_limited_now():
                return

            now = datetime.now(UTC)
            reset_until = await self._fetch_rate_limit_reset_time()
            if reset_until is not None and reset_until > now:
                # Hard pause until the GitHub core reset boundary (+small buffer).
                until = reset_until + timedelta(seconds=5)
                self._rate_limit_recovery_attempts = 0
            else:
                # Post-reset recovery: exponentially back off with jitter.
                self._rate_limit_recovery_attempts += 1
                exp = min(self._rate_limit_recovery_attempts, 8)
                base_seconds = 2**exp
                jitter = random.uniform(0.75, 1.25)
                delay_seconds = min(300, max(1, int(base_seconds * jitter)))
                until = now + timedelta(seconds=delay_seconds)

            self._rate_limited_until = until
            seconds = max(1, int((until - datetime.now(UTC)).total_seconds()))
            logger.error(
                "GitHub API rate limit hit; backing off issue fetches for ~%ds (until %s). Cause: %s",
                seconds,
                until.isoformat(),
                exc,
            )

    async def _fetch_rate_limit_reset_time(self) -> datetime | None:
        try:
            raw = await run_subprocess(
                "gh",
                "api",
                "rate_limit",
                "--jq",
                ".resources.core.reset",
                gh_token=self._credentials.gh_token,
            )
            reset_epoch = int(raw.strip())
            return datetime.fromtimestamp(reset_epoch, tz=UTC)
        except (RuntimeError, ValueError, OSError):
            return None

    async def fetch_all_hydraflow_issues(self) -> list[GitHubIssue]:
        """Fetch all open issues with any HydraFlow pipeline label in one batch.

        Uses a single GraphQL request (one alias per label) instead of
        firing a separate REST call per label.  Falls back to REST on
        GraphQL failure.
        """
        all_labels = list(
            {
                *self._config.find_label,
                *self._config.planner_label,
                *self._config.ready_label,
                *self._config.review_label,
                *self._config.hitl_label,
                *self._config.hitl_active_label,
            }
        )
        if not all_labels:
            return []
        if self._config.dry_run:
            logger.info("[dry-run] Would fetch all HydraFlow issues")
            return []
        try:
            return await self._fetch_all_graphql(all_labels)
        except Exception as exc:
            logger.warning(
                "GraphQL batch issue fetch failed, falling back to REST: %s", exc
            )
            return await self.fetch_issues_by_labels(
                all_labels, limit=500, require_complete=True
            )

    async def _fetch_all_graphql(self, all_labels: list[str]) -> list[GitHubIssue]:
        """Single GraphQL request with one alias per label."""
        owner, name = self._config.repo.split("/", 1)

        fragments = []
        for i, label in enumerate(all_labels):
            escaped = label.replace("\\", "\\\\").replace('"', '\\"')
            fragments.append(
                f"  lbl_{i}: issues(first: 100, states: OPEN, "
                f'labels: ["{escaped}"], '
                f"orderBy: {{field: CREATED_AT, direction: ASC}}) {{\n"
                f"    nodes {{\n"
                f"      number title body url state createdAt\n"
                f"      author {{ login }}\n"
                f"      milestone {{ number }}\n"
                f"      labels(first: 20) {{ nodes {{ name }} }}\n"
                f"    }}\n"
                f"  }}"
            )

        query = (
            f'{{ repository(owner: "{owner}", name: "{name}") {{\n'
            + "\n".join(fragments)
            + "\n}}"
        )

        raw = await run_subprocess(
            "gh",
            "api",
            "graphql",
            "-f",
            f"query={query}",
            gh_token=self._credentials.gh_token,
        )
        data = json.loads(raw)

        errors = data.get("errors")
        if errors:
            raise RuntimeError(f"GraphQL errors: {errors}")

        repo_data = data.get("data", {}).get("repository", {})

        seen: dict[int, dict[str, Any]] = {}
        for i in range(len(all_labels)):
            nodes = repo_data.get(f"lbl_{i}", {}).get("nodes", [])
            for node in nodes:
                number = node.get("number")
                if isinstance(number, int) and number not in seen:
                    seen[number] = self._normalize_graphql_issue(node)

        issues = [GitHubIssue.model_validate(v) for v in seen.values()]
        if self._config.collaborator_check_enabled:
            collaborators = await self._get_collaborators()
            issues = self._filter_non_collaborators(issues, collaborators)
        return issues[:500]

    async def fetch_issue_by_number(self, issue_number: int) -> GitHubIssue | None:
        """Fetch a single issue by its number.

        Returns ``None`` if the issue cannot be fetched.
        """
        if self._config.dry_run:
            logger.info("[dry-run] Would fetch issue #%d", issue_number)
            return None
        try:
            raw = await run_subprocess(
                "gh",
                "api",
                f"repos/{self._config.repo}/issues/{issue_number}",
                "--jq",
                '{number, title, body, labels, url: .html_url, state, created_at: .created_at, author: (.user.login // "")}',
                gh_token=self._credentials.gh_token,
            )
            data = json.loads(raw)
            if isinstance(data, dict):
                data["labels"] = self._normalize_labels(data.get("labels", []))
                data["comments"] = await self.fetch_issue_comments(issue_number)
            return GitHubIssue.model_validate(data)
        except (RuntimeError, json.JSONDecodeError) as exc:
            logger.error("Could not fetch issue #%d: %s", issue_number, exc)
            return None

    async def fetch_plan_issues(self) -> list[GitHubIssue]:
        """Fetch issues labeled with the planner label (e.g. ``hydraflow-plan``)."""
        issues = await self.fetch_issues_by_labels(
            self._config.planner_label,
            self._config.batch_size,
        )
        logger.info("Fetched %d issues for planning", len(issues))
        return issues[: self._config.batch_size]

    async def fetch_ready_issues(self, active_issues: set[int]) -> list[GitHubIssue]:
        """Fetch issues labeled ``hydraflow-ready`` for the implement phase.

        Returns up to ``2 * max_workers`` issues so the worker pool
        stays saturated.
        """
        queue_size = 2 * self._config.max_workers

        all_issues = await self.fetch_issues_by_labels(
            self._config.ready_label,
            queue_size,
        )
        # Only skip issues already active in this run (GitHub labels are
        # the source of truth — if it still has hydraflow-ready, it needs work)
        issues = [i for i in all_issues if i.number not in active_issues]
        for skipped in all_issues:
            if skipped.number in active_issues:
                logger.info("Skipping in-progress issue #%d", skipped.number)

        logger.info("Fetched %d issues to implement", len(issues))
        return issues[:queue_size]

    async def _get_open_prs_by_branch(self) -> dict[str, dict[str, Any]]:
        """Fetch all open PRs in one call and return ``{branch: pr_data}``.

        Cached for ``data_poll_interval`` seconds to avoid repeated fetches
        across poll cycles.
        """
        now = datetime.now(UTC)
        if (
            self._pr_cache is not None
            and self._pr_cache_fetched_at is not None
            and (now - self._pr_cache_fetched_at).total_seconds()
            < self._config.data_poll_interval
        ):
            return self._pr_cache

        raw = await run_subprocess(
            "gh",
            "api",
            f"repos/{self._config.repo}/pulls",
            "--paginate",
            "--method",
            "GET",
            "--field",
            "state=open",
            "--field",
            "per_page=100",
            gh_token=self._credentials.gh_token,
        )
        all_prs = json.loads(raw)

        by_branch: dict[str, dict[str, Any]] = {}
        for pr in all_prs:
            if not isinstance(pr, dict):
                continue
            head = pr.get("head", {})
            branch = head.get("ref", "") if isinstance(head, dict) else ""
            if branch:
                by_branch[branch] = {
                    "number": pr.get("number", 0),
                    "url": pr.get("html_url", ""),
                    "isDraft": pr.get("draft", False),
                }

        self._pr_cache = by_branch
        self._pr_cache_fetched_at = now
        return by_branch

    def invalidate_pr_cache(self) -> None:
        """Clear the PR cache so the next lookup fetches fresh data."""
        self._pr_cache = None
        self._pr_cache_fetched_at = None

    async def fetch_reviewable_prs(
        self,
        active_issues: set[int],
        prefetched_issues: list[GitHubIssue] | None = None,
    ) -> tuple[list[PRInfo], list[GitHubIssue]]:
        """Fetch issues labeled ``hydraflow-review`` and resolve their open PRs.

        When *prefetched_issues* is provided, skip the GitHub issue fetch
        and use those issues directly (they come from the ``IssueStore``).
        Returns ``(pr_infos, issues)`` so the reviewer has both.

        Uses a single batch fetch of all open PRs (cached) instead of
        one API call per issue.
        """
        if prefetched_issues is not None:
            issues = [i for i in prefetched_issues if i.number not in active_issues]
        else:
            all_issues = await self.fetch_issues_by_labels(
                self._config.review_label,
                self._config.batch_size,
            )
            # Only skip issues already active in this run
            issues = [i for i in all_issues if i.number not in active_issues]
        if not issues:
            return [], []

        # Single batch fetch instead of per-issue PR lookups
        try:
            pr_by_branch = await self._get_open_prs_by_branch()
        except (RuntimeError, json.JSONDecodeError) as exc:
            logger.warning("Batch PR fetch failed: %s", exc)
            pr_by_branch = {}

        pr_infos: list[PRInfo] = []
        for issue in issues:
            branch = f"agent/issue-{issue.number}"
            pr_data = pr_by_branch.get(branch)
            if pr_data:
                try:
                    pr_infos.append(
                        PRInfo(
                            number=pr_data["number"],
                            issue_number=issue.number,
                            branch=branch,
                            url=pr_data.get("url", ""),
                            draft=pr_data.get("isDraft", False),
                        )
                    )
                except KeyError as exc:
                    logger.warning(
                        "Could not find PR for issue #%d: %s", issue.number, exc
                    )

        non_draft = [p for p in pr_infos if not p.draft and p.number > 0]
        logger.info("Fetched %d reviewable PRs", len(non_draft))
        return non_draft, issues

    async def fetch_issue_comments(self, issue_number: int) -> list[str]:
        """Fetch all comment bodies for *issue_number*.

        Returns a list of comment body strings, oldest-first.
        """
        if self._config.dry_run:
            logger.info("[dry-run] Would fetch comments for issue #%d", issue_number)
            return []
        try:
            raw = await run_subprocess(
                "gh",
                "api",
                f"repos/{self._config.repo}/issues/{issue_number}/comments",
                "--jq",
                "[.[] | .body]",
                gh_token=self._credentials.gh_token,
            )
            data = json.loads(raw)
            if not isinstance(data, list):
                return []
            return [str(c) for c in data]
        except (RuntimeError, json.JSONDecodeError) as exc:
            logger.error(
                "Could not fetch comments for issue #%d: %s", issue_number, exc
            )
            return []


class GitHubTaskFetcher:
    """Wraps :class:`IssueFetcher` to implement the :class:`task_source.TaskFetcher` protocol."""

    def __init__(self, fetcher: IssueFetcher) -> None:
        self._fetcher = fetcher

    async def fetch_all(self) -> list[Task]:
        issues = await self._fetcher.fetch_all_hydraflow_issues()
        return [i.to_task() for i in issues]
