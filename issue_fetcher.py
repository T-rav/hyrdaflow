"""GitHub issue fetching for the HydraFlow orchestrator."""

from __future__ import annotations

import asyncio
import json
import logging

from config import HydraFlowConfig
from models import GitHubIssue, PRInfo
from subprocess_util import run_subprocess

logger = logging.getLogger("hydraflow.issue_fetcher")


class IssueFetcher:
    """Fetches GitHub issues and PRs via the ``gh`` CLI."""

    def __init__(self, config: HydraFlowConfig) -> None:
        self._config = config

    async def fetch_issues_by_labels(
        self,
        labels: list[str],
        limit: int,
        exclude_labels: list[str] | None = None,
    ) -> list[GitHubIssue]:
        """Fetch open issues matching *any* of *labels*, deduplicated.

        If *labels* is empty but *exclude_labels* is provided, fetch all
        open issues and filter out those carrying any of the exclude labels.
        """
        if self._config.dry_run:
            logger.info(
                "[dry-run] Would fetch issues with labels=%r exclude=%r",
                labels,
                exclude_labels,
            )
            return []

        seen: dict[int, dict] = {}

        async def _query_label(label: str | None) -> None:
            cmd = [
                "gh",
                "issue",
                "list",
                "--repo",
                self._config.repo,
                "--limit",
                str(limit),
                "--json",
                "number,title,body,labels,comments,url,createdAt",
                "--search",
                "sort:created-asc",
            ]
            if label is not None:
                cmd += ["--label", label]
            try:
                raw = await run_subprocess(*cmd, gh_token=self._config.gh_token)
                for item in json.loads(raw):
                    seen.setdefault(item["number"], item)
            except (RuntimeError, json.JSONDecodeError, FileNotFoundError) as exc:
                logger.error("gh issue list failed for label=%r: %s", label, exc)

        if labels:
            await asyncio.gather(*[_query_label(lbl) for lbl in labels])
        elif exclude_labels:
            await _query_label(None)
            # Remove issues that carry any of the exclude labels
            exclude_set = set(exclude_labels)
            to_remove = []
            for num, raw in seen.items():
                raw_labels = {
                    (rl["name"] if isinstance(rl, dict) else str(rl))
                    for rl in raw.get("labels", [])
                }
                if raw_labels & exclude_set:
                    to_remove.append(num)
            for num in to_remove:
                del seen[num]
        else:
            return []

        issues = [GitHubIssue.model_validate(raw) for raw in seen.values()]
        return issues[:limit]

    async def fetch_all_hydraflow_issues(self) -> list[GitHubIssue]:
        """Fetch all open issues with any HydraFlow pipeline label in one batch.

        Collects all configured pipeline labels and calls
        :meth:`fetch_issues_by_labels` once, deduplicating by issue number.
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
        return await self.fetch_issues_by_labels(all_labels, limit=100)

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
                "issue",
                "view",
                str(issue_number),
                "--repo",
                self._config.repo,
                "--json",
                "number,title,body,labels,comments,url,createdAt",
                gh_token=self._config.gh_token,
            )
            data = json.loads(raw)
            return GitHubIssue.model_validate(data)
        except (RuntimeError, json.JSONDecodeError) as exc:
            logger.error("Could not fetch issue #%d: %s", issue_number, exc)
            return None

    async def fetch_plan_issues(self) -> list[GitHubIssue]:
        """Fetch issues labeled with the planner label (e.g. ``hydraflow-plan``)."""
        if not self._config.planner_label:
            # No planner labels configured — fetch all open issues that are
            # not already in a downstream pipeline stage.
            exclude = list(
                {
                    *self._config.ready_label,
                    *self._config.review_label,
                    *self._config.hitl_label,
                    *self._config.fixed_label,
                }
            )
            issues = await self.fetch_issues_by_labels(
                [],
                self._config.batch_size,
                exclude_labels=exclude,
            )
        else:
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

    async def fetch_reviewable_prs(
        self,
        active_issues: set[int],
        prefetched_issues: list[GitHubIssue] | None = None,
    ) -> tuple[list[PRInfo], list[GitHubIssue]]:
        """Fetch issues labeled ``hydraflow-review`` and resolve their open PRs.

        When *prefetched_issues* is provided, skip the GitHub issue fetch
        and use those issues directly (they come from the ``IssueStore``).
        Returns ``(pr_infos, issues)`` so the reviewer has both.
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

        # For each issue, look up the open PR on its branch
        pr_infos: list[PRInfo] = []
        for issue in issues:
            branch = f"agent/issue-{issue.number}"
            try:
                raw = await run_subprocess(
                    "gh",
                    "pr",
                    "list",
                    "--repo",
                    self._config.repo,
                    "--head",
                    branch,
                    "--state",
                    "open",
                    "--json",
                    "number,url,isDraft",
                    "--limit",
                    "1",
                    gh_token=self._config.gh_token,
                )
                prs_json = json.loads(raw)
                if prs_json:
                    pr_data = prs_json[0]
                    pr_infos.append(
                        PRInfo(
                            number=pr_data["number"],
                            issue_number=issue.number,
                            branch=branch,
                            url=pr_data.get("url", ""),
                            draft=pr_data.get("isDraft", False),
                        )
                    )
            except (RuntimeError, json.JSONDecodeError, KeyError) as exc:
                logger.warning("Could not find PR for issue #%d: %s", issue.number, exc)

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
                "issue",
                "view",
                str(issue_number),
                "--repo",
                self._config.repo,
                "--json",
                "comments",
                gh_token=self._config.gh_token,
            )
            data = json.loads(raw)
            comments = data.get("comments", [])
            return [
                c.get("body", "") if isinstance(c, dict) else str(c) for c in comments
            ]
        except (RuntimeError, json.JSONDecodeError) as exc:
            logger.error(
                "Could not fetch comments for issue #%d: %s", issue_number, exc
            )
            return []
