"""Pull request lifecycle management via the ``gh`` CLI."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from models import (
    GitHubIssue,
    HITLItem,
    LabelCounts,
    PRInfo,
    PRListItem,
    ReviewVerdict,
)
from prep import HYDRAFLOW_LABELS
from subprocess_util import run_subprocess, run_subprocess_with_retry

logger = logging.getLogger("hydraflow.pr_manager")

# Cache TTL for label-count queries (seconds).
_LABEL_CACHE_TTL: int = 30


def _is_missing_label_404(exc: RuntimeError) -> bool:
    """Return True when gh reports a missing label during label removal."""
    msg = str(exc).lower()
    return "label does not exist" in msg and "http 404" in msg


class SelfReviewError(RuntimeError):
    """Raised when a formal review fails due to the 'own pull request' restriction."""


class CommentFormatter:
    """GitHub comment body formatting — chunking and hard-truncation."""

    GITHUB_COMMENT_LIMIT: int = 65_536  # GitHub maximum comment body size
    TRUNCATION_MARKER: str = "\n\n*...truncated to fit GitHub comment limit*"

    @staticmethod
    def chunk(body: str, limit: int | None = None) -> list[str]:
        """Split *body* into chunks that fit within *limit* characters."""
        if limit is None:
            limit = CommentFormatter.GITHUB_COMMENT_LIMIT
        if len(body) <= limit:
            return [body]
        chunks: list[str] = []
        while body:
            if len(body) <= limit:
                chunks.append(body)
                break
            split_at = body.rfind("\n", 0, limit)
            if split_at <= 0:
                split_at = limit
            chunks.append(body[:split_at])
            body = body[split_at:].lstrip("\n")
        return chunks

    @staticmethod
    def cap(body: str, limit: int | None = None) -> str:
        """Hard-truncate *body* to *limit* characters.

        Acts as a safety net after chunking / header prepending to guarantee
        no single payload exceeds GitHub's comment size limit.
        """
        if limit is None:
            limit = CommentFormatter.GITHUB_COMMENT_LIMIT
        if len(body) <= limit:
            return body
        marker = CommentFormatter.TRUNCATION_MARKER
        return body[: limit - len(marker)] + marker


class PRManager:
    """Pushes branches, creates PRs, merges, and manages labels."""

    _GITHUB_COMMENT_LIMIT = CommentFormatter.GITHUB_COMMENT_LIMIT
    _TRUNCATION_MARKER = CommentFormatter.TRUNCATION_MARKER
    _HEADER_RESERVE = 50  # room for "*Part X/Y*\n\n" prefix

    # Re-export from prep module for backward compatibility
    _HYDRAFLOW_LABELS = HYDRAFLOW_LABELS

    def __init__(self, config: HydraFlowConfig, event_bus: EventBus) -> None:
        self._config = config
        self._bus = event_bus
        self._repo = config.repo
        self._repo_owner = config.repo.split("/", 1)[0] if "/" in config.repo else ""
        self._max_retries = config.gh_max_retries
        self._label_counts_cache: LabelCounts | None = None
        self._label_counts_ts: float = 0.0

    async def _run_gh(self, *cmd: str, cwd: Path | None = None) -> str:
        """Run a gh/git command with retry logic."""
        return await run_subprocess_with_retry(
            *cmd,
            cwd=cwd or self._config.repo_root,
            gh_token=self._config.gh_token,
            max_retries=self._max_retries,
        )

    async def ensure_labels_exist(self) -> None:
        """Create all HydraFlow lifecycle labels in the repo if they don't exist.

        Delegates to :func:`prep.ensure_labels` which handles creation,
        reporting, and dry-run behaviour.
        """
        from prep import ensure_labels  # noqa: PLC0415

        result = await ensure_labels(self._config)
        logger.info(result.summary())

    async def push_branch(self, worktree_path: Path, branch: str) -> bool:
        """Push *branch* to origin from *worktree_path*.

        Returns *True* on success.
        """
        if self._config.dry_run:
            logger.info("[dry-run] Would push branch %s", branch)
            return True

        try:
            await run_subprocess(
                "git",
                "push",
                "--no-verify",
                "-u",
                "origin",
                branch,
                cwd=worktree_path,
                gh_token=self._config.gh_token,
            )
            return True
        except RuntimeError as exc:
            logger.error("Push failed for %s: %s", branch, exc)
            return False

    async def force_push_branch(self, worktree_path: Path, branch: str) -> bool:
        """Force-push *branch* to origin using ``--force-with-lease``.

        Safer than ``--force`` — prevents clobbering concurrent pushes.
        Used after fresh-branch rebuilds where branch history is rewritten.
        Returns *True* on success.
        """
        if self._config.dry_run:
            logger.info("[dry-run] Would force-push branch %s", branch)
            return True

        try:
            await run_subprocess(
                "git",
                "push",
                "--no-verify",
                "--force-with-lease",
                "-u",
                "origin",
                branch,
                cwd=worktree_path,
                gh_token=self._config.gh_token,
            )
            return True
        except RuntimeError as exc:
            logger.error("Force-push failed for %s: %s", branch, exc)
            return False

    async def create_pr(
        self,
        issue: GitHubIssue,
        branch: str,
        *,
        draft: bool = False,
    ) -> PRInfo:
        """Create a PR for *branch* linked to *issue*.

        Returns a :class:`PRInfo` with the PR number and URL.
        """
        title = f"Fixes #{issue.number}: {issue.title}"
        if len(title) > 70:
            title = title[:67] + "..."

        body = (
            f"## Summary\n\n"
            f"Closes #{issue.number}.\n\n"
            f"## Issue\n\n{issue.title}\n\n"
            f"## Test plan\n\n"
            f"- [ ] Unit tests pass (`make test`)\n"
            f"- [ ] Linting passes (`make lint`)\n"
            f"- [ ] Manual review of changes\n\n"
            f"---\n"
            f"Generated by HydraFlow"
        )

        if self._config.dry_run:
            logger.info(
                "[dry-run] Would create %sPR for issue #%d",
                "draft " if draft else "",
                issue.number,
            )
            return PRInfo(
                number=0,
                issue_number=issue.number,
                branch=branch,
                url="",
                draft=draft,
            )

        cmd = [
            "gh",
            "pr",
            "create",
            "--repo",
            self._repo,
            "--head",
            branch,
            "--base",
            self._config.main_branch,
            "--title",
            title,
        ]
        if draft:
            cmd.append("--draft")

        try:
            output = await self._run_with_body_file(
                *cmd, body=body, cwd=self._config.repo_root
            )
            # gh pr create --json would be better, but the URL is in stdout
            pr_url = output.strip()

            # Validate output looks like a PR URL before parsing
            if "/pull/" not in pr_url:
                raise RuntimeError(
                    f"Unexpected gh pr create output (expected PR URL): {pr_url[:200]}"
                )

            # Get PR number from URL (e.g., https://github.com/org/repo/pull/123)
            pr_number = int(pr_url.rstrip("/").split("/")[-1])

            pr_info = PRInfo(
                number=pr_number,
                issue_number=issue.number,
                branch=branch,
                url=pr_url,
                draft=draft,
            )

            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.PR_CREATED,
                    data={
                        "pr": pr_number,
                        "issue": issue.number,
                        "branch": branch,
                        "draft": draft,
                        "url": pr_url,
                    },
                )
            )

            return pr_info

        except (RuntimeError, ValueError) as exc:
            logger.error("PR creation failed for issue #%d: %s", issue.number, exc)
            existing = await self.find_open_pr_for_branch(
                branch, issue_number=issue.number
            )
            if existing is not None:
                logger.info(
                    "Using existing PR #%d for issue #%d on branch %s after create failure",
                    existing.number,
                    issue.number,
                    branch,
                )
                return existing
            return PRInfo(
                number=0,
                issue_number=issue.number,
                branch=branch,
                draft=draft,
            )

    async def find_open_pr_for_branch(
        self, branch: str, *, issue_number: int = 0
    ) -> PRInfo | None:
        """Return the open PR for *branch*, or ``None`` when absent/unreadable."""
        if self._config.dry_run:
            return None
        head_filter = f"{self._repo_owner}:{branch}" if self._repo_owner else branch
        try:
            raw = await self._run_gh(
                "gh",
                "api",
                f"repos/{self._repo}/pulls",
                "--method",
                "GET",
                "--field",
                "state=open",
                "--field",
                f"head={head_filter}",
                "--field",
                "per_page=1",
                "--jq",
                "[.[] | {number, url: .html_url, isDraft: .draft}]",
            )
            prs = json.loads(raw)
            if not prs:
                return None
            pr_data = prs[0]
            return PRInfo(
                number=int(pr_data["number"]),
                issue_number=issue_number,
                branch=branch,
                url=str(pr_data.get("url", "")),
                draft=bool(pr_data.get("isDraft", False)),
            )
        except (RuntimeError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            logger.debug(
                "Could not resolve open PR for branch %s", branch, exc_info=True
            )
            return None

    async def branch_has_diff_from_main(self, branch: str) -> bool:
        """Return whether *branch* has commits ahead of configured main branch."""
        if self._config.dry_run:
            return True
        try:
            raw = await self._run_gh(
                "gh",
                "api",
                f"repos/{self._repo}/compare/{self._config.main_branch}...{branch}",
                "--jq",
                "{ahead_by}",
            )
            data = json.loads(raw)
            if isinstance(data, dict):
                ahead_by = int(data.get("ahead_by", 0) or 0)
                return ahead_by > 0
        except (RuntimeError, ValueError, TypeError, json.JSONDecodeError):
            logger.warning(
                "Could not determine branch diff for %s; assuming diff exists",
                branch,
                exc_info=True,
            )
        return True

    async def merge_pr(self, pr_number: int) -> bool:
        """Merge PR immediately via squash merge with branch deletion.

        Returns *True* on success.
        """
        if self._config.dry_run:
            logger.info("[dry-run] Would merge PR #%d", pr_number)
            return True

        try:
            await run_subprocess(
                "gh",
                "pr",
                "merge",
                str(pr_number),
                "--repo",
                self._repo,
                "--squash",
                "--delete-branch",
                cwd=self._config.repo_root,
                gh_token=self._config.gh_token,
            )

            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.MERGE_UPDATE,
                    data={"pr": pr_number, "status": "merged"},
                )
            )
            return True
        except RuntimeError as exc:
            logger.error("Merge failed for PR #%d: %s", pr_number, exc)
            return False

    async def _comment(
        self, target: Literal["issue", "pr"], number: int, body: str
    ) -> None:
        """Post a comment on a GitHub issue or PR."""
        if self._config.dry_run:
            logger.info("[dry-run] Would post comment on %s #%d", target, number)
            return
        chunk_limit = CommentFormatter.GITHUB_COMMENT_LIMIT - self._HEADER_RESERVE
        chunks = CommentFormatter.chunk(body, chunk_limit)
        for idx, chunk in enumerate(chunks):
            part = chunk
            if len(chunks) > 1:
                part = f"*Part {idx + 1}/{len(chunks)}*\n\n{chunk}"
            part = CommentFormatter.cap(part, CommentFormatter.GITHUB_COMMENT_LIMIT)
            try:
                await self._run_with_body_file(
                    "gh",
                    target,
                    "comment",
                    str(number),
                    "--repo",
                    self._repo,
                    body=part,
                    cwd=self._config.repo_root,
                )
            except RuntimeError as exc:
                logger.warning(
                    "Could not post comment on %s #%d: %s",
                    target,
                    number,
                    exc,
                )

    async def post_comment(self, task_id: int, body: str) -> None:
        """Post a comment on a GitHub issue."""
        await self._comment("issue", task_id, body)

    async def post_pr_comment(self, pr_number: int, body: str) -> None:
        """Post a comment on a GitHub pull request."""
        await self._comment("pr", pr_number, body)

    async def submit_review(
        self, pr_number: int, verdict: ReviewVerdict, body: str
    ) -> bool:
        """Submit a formal GitHub PR review.

        *verdict* is a :class:`ReviewVerdict` enum member.
        Returns *True* on success.
        """
        flag_map = {
            ReviewVerdict.APPROVE: "--approve",
            ReviewVerdict.REQUEST_CHANGES: "--request-changes",
            ReviewVerdict.COMMENT: "--comment",
        }
        flag = flag_map[verdict]

        if self._config.dry_run:
            logger.info(
                "[dry-run] Would submit %s review on PR #%d",
                verdict.value,
                pr_number,
            )
            return True

        body = CommentFormatter.cap(body, CommentFormatter.GITHUB_COMMENT_LIMIT)
        try:
            await self._run_with_body_file(
                "gh",
                "pr",
                "review",
                str(pr_number),
                "--repo",
                self._repo,
                flag,
                body=body,
                cwd=self._config.repo_root,
            )
            return True
        except RuntimeError as exc:
            err_msg = str(exc)
            err_lower = err_msg.lower()
            if (
                "can not request changes on your own pull request" in err_lower
                or "cannot approve your own pull request" in err_lower
            ):
                logger.info(
                    "Cannot submit %s review on own PR #%d — falling back to comment",
                    verdict.value,
                    pr_number,
                )
                raise SelfReviewError(err_msg) from exc
            logger.error(
                "Could not submit %s review on PR #%d: %s",
                verdict.value,
                pr_number,
                exc,
            )
            return False

    async def _add_labels(
        self, target: Literal["issue", "pr"], number: int, labels: list[str]
    ) -> None:
        """Add *labels* to a GitHub issue or PR."""
        if self._config.dry_run or not labels:
            return
        for label in labels:
            try:
                await self._run_gh(
                    "gh",
                    "api",
                    f"repos/{self._repo}/issues/{number}/labels",
                    "-X",
                    "POST",
                    "--raw-field",
                    f"labels[]={label}",
                )
            except RuntimeError as exc:
                logger.warning(
                    "Could not add label %r to %s #%d: %s",
                    label,
                    target,
                    number,
                    exc,
                )

    async def add_labels(self, issue_number: int, labels: list[str]) -> None:
        """Add *labels* to a GitHub issue."""
        await self._add_labels("issue", issue_number, labels)

    async def _remove_label(
        self, target: Literal["issue", "pr"], number: int, label: str
    ) -> None:
        """Remove *label* from a GitHub issue or PR."""
        if self._config.dry_run:
            return
        try:
            encoded_label = quote(label, safe="")
            await self._run_gh(
                "gh",
                "api",
                f"repos/{self._repo}/issues/{number}/labels/{encoded_label}",
                "-X",
                "DELETE",
            )
        except RuntimeError as exc:
            if _is_missing_label_404(exc):
                logger.debug(
                    "Label %r not present on %s #%d; skipping remove",
                    label,
                    target,
                    number,
                )
                return
            logger.warning(
                "Could not remove label %r from %s #%d: %s",
                label,
                target,
                number,
                exc,
            )

    async def remove_label(self, issue_number: int, label: str) -> None:
        """Remove *label* from a GitHub issue."""
        await self._remove_label("issue", issue_number, label)

    async def close_issue(self, issue_number: int) -> None:
        """Close a GitHub issue."""
        if self._config.dry_run:
            return
        try:
            await self._run_gh(
                "gh",
                "issue",
                "close",
                str(issue_number),
                "--repo",
                self._repo,
            )
        except RuntimeError as exc:
            logger.warning(
                "Could not close issue #%d: %s",
                issue_number,
                exc,
            )

    async def update_issue_body(self, issue_number: int, body: str) -> None:
        """Update the body of a GitHub issue using ``--body-file``."""
        if self._config.dry_run:
            return
        fd, tmp_path = tempfile.mkstemp(suffix=".md", prefix="hydraflow-body-")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(body)
            await self._run_gh(
                "gh",
                "issue",
                "edit",
                str(issue_number),
                "--repo",
                self._repo,
                "--body-file",
                tmp_path,
            )
        except RuntimeError as exc:
            logger.warning(
                "Could not update body for issue #%d: %s",
                issue_number,
                exc,
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    async def remove_pr_label(self, pr_number: int, label: str) -> None:
        """Remove *label* from a GitHub pull request."""
        await self._remove_label("pr", pr_number, label)

    async def add_pr_labels(self, pr_number: int, labels: list[str]) -> None:
        """Add *labels* to a GitHub pull request."""
        await self._add_labels("pr", pr_number, labels)

    async def swap_pipeline_labels(
        self,
        issue_number: int,
        new_label: str,
        *,
        pr_number: int | None = None,
    ) -> None:
        """Atomically swap to *new_label*, removing all other pipeline labels.

        This prevents the dual-label bug where a crash between remove and add
        leaves an issue with conflicting pipeline labels (e.g. hydraflow-ready +
        hydraflow-hitl simultaneously).
        """
        all_labels = self._config.all_pipeline_labels
        for lbl in all_labels:
            if lbl != new_label:
                await self._remove_label("issue", issue_number, lbl)
                if pr_number is not None:
                    await self._remove_label("pr", pr_number, lbl)
        await self._add_labels("issue", issue_number, [new_label])
        if pr_number is not None:
            await self._add_labels("pr", pr_number, [new_label])

    async def create_issue(
        self,
        title: str,
        body: str,
        labels: list[str] | None = None,
    ) -> int:
        """Create a new GitHub issue. Returns the issue number (0 on failure)."""
        if self._config.dry_run:
            logger.info("[dry-run] Would create issue: %s", title)
            return 0

        cmd = [
            "gh",
            "issue",
            "create",
            "--repo",
            self._repo,
            "--title",
            title,
        ]
        for label in labels or []:
            cmd.extend(["--label", label])

        try:
            output = await self._run_with_body_file(
                *cmd, body=body, cwd=self._config.repo_root
            )
            # gh issue create prints the issue URL — validate before parsing
            url = output.strip()
            if "/issues/" not in url:
                raise RuntimeError(
                    f"Unexpected gh issue create output (expected issue URL): {url[:200]}"
                )
            issue_number = int(url.rstrip("/").split("/")[-1])

            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.ISSUE_CREATED,
                    data={
                        "number": issue_number,
                        "title": title,
                        "labels": labels or [],
                    },
                )
            )
            return issue_number
        except (RuntimeError, ValueError) as exc:
            logger.error("Issue creation failed for %r: %s", title, exc)
            return 0

    async def upload_screenshot_gist(self, png_base64: str) -> str:
        """Upload a base64-encoded PNG as a GitHub gist and return the raw URL.

        Returns an empty string on failure or in dry-run mode.
        """
        if self._config.dry_run:
            logger.info("[dry-run] Would upload screenshot gist")
            return ""

        import base64

        # Strip optional data URI prefix
        if png_base64.startswith("data:"):
            _, _, png_base64 = png_base64.partition(",")

        fd, tmp_path = tempfile.mkstemp(suffix=".png", prefix="hydraflow-screenshot-")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(base64.b64decode(png_base64))

            output = await self._run_gh(
                "gh",
                "gist",
                "create",
                "--public",
                "--filename",
                "screenshot.png",
                tmp_path,
            )
            # gh gist create prints the gist URL, e.g.
            # https://gist.github.com/user/abc123
            gist_url = output.strip()
            if "gist.github.com" not in gist_url:
                logger.warning("Unexpected gist create output: %s", gist_url[:200])
                return ""

            # Convert to raw URL:
            # https://gist.githubusercontent.com/user/abc123/raw/screenshot.png
            raw_url = (
                gist_url.replace("gist.github.com", "gist.githubusercontent.com")
                + "/raw/screenshot.png"
            )
            return raw_url
        except Exception:
            logger.exception("Screenshot gist upload failed")
            return ""
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    async def get_pr_diff(self, pr_number: int) -> str:
        """Fetch the diff for *pr_number*."""
        try:
            return await self._run_gh(
                "gh",
                "pr",
                "diff",
                str(pr_number),
                "--repo",
                self._repo,
            )
        except RuntimeError as exc:
            logger.error("Could not get diff for PR #%d: %s", pr_number, exc)
            return ""

    async def get_pr_diff_names(self, pr_number: int) -> list[str]:
        """Fetch the list of files changed in *pr_number*."""
        try:
            output = await self._run_gh(
                "gh",
                "pr",
                "diff",
                str(pr_number),
                "--repo",
                self._repo,
                "--name-only",
            )
            return [f.strip() for f in output.strip().splitlines() if f.strip()]
        except RuntimeError as exc:
            logger.error("Could not get diff file names for PR #%d: %s", pr_number, exc)
            return []

    async def pull_main(self) -> bool:
        """Pull latest main into the local repo."""
        if self._config.dry_run:
            logger.info("[dry-run] Would pull main")
            return True
        try:
            await self._run_gh(
                "git",
                "pull",
                "origin",
                self._config.main_branch,
            )
            return True
        except RuntimeError as exc:
            logger.error("Pull main failed: %s", exc)
            return False

    # --- CI check methods ---

    async def get_pr_checks(self, pr_number: int) -> list[dict[str, str]]:
        """Fetch CI check results for *pr_number*.

        Returns a list of dicts with ``name`` and ``state`` keys.
        Returns an empty list on failure or in dry-run mode.
        """
        if self._config.dry_run:
            logger.info("[dry-run] Would fetch CI checks for PR #%d", pr_number)
            return []

        try:
            raw = await self._run_gh(
                "gh",
                "pr",
                "checks",
                str(pr_number),
                "--repo",
                self._repo,
                "--json",
                "name,state",
            )
            return json.loads(raw)  # type: ignore[no-any-return]
        except (RuntimeError, json.JSONDecodeError) as exc:
            logger.warning("Could not fetch CI checks for PR #%d: %s", pr_number, exc)
            return []

    _RUN_ID_PATTERN = re.compile(r"/actions/runs/(\d+)")

    async def _get_failed_check_runs(self, pr_number: int) -> list[tuple[str, str]]:
        """Return [(name, run_id), ...] for failed CI checks on this PR."""
        raw = await self._run_gh(
            "gh",
            "pr",
            "checks",
            str(pr_number),
            "--repo",
            self._repo,
            "--json",
            "name,state,detailsUrl",
        )
        checks = json.loads(raw)

        seen_run_ids: set[str] = set()
        failed_names: list[tuple[str, str]] = []
        for check in checks:
            state = check.get("state", "").upper()
            if state in self._PASSING_STATES or state in self._PENDING_STATES:
                continue
            details_url = check.get("detailsUrl", "")
            if not details_url:
                continue
            match = self._RUN_ID_PATTERN.search(details_url)
            if not match:
                continue
            run_id = match.group(1)
            if run_id not in seen_run_ids:
                seen_run_ids.add(run_id)
                failed_names.append((check.get("name", "unknown"), run_id))
        return failed_names

    async def _fetch_run_log(self, name: str, run_id: str) -> str:
        """Fetch the --log-failed output for one run, or '' on error."""
        try:
            log_output = await self._run_gh(
                "gh",
                "run",
                "view",
                run_id,
                "--repo",
                self._repo,
                "--log-failed",
            )
            if log_output.strip():
                return f"### {name} (run {run_id})\n\n{log_output}"
        except RuntimeError as exc:
            logger.debug("Could not fetch log for run %s: %s", run_id, exc)
        return ""

    async def fetch_ci_failure_logs(self, pr_number: int) -> str:
        """Fetch full CI failure logs for *pr_number*.

        Queries check runs, extracts run IDs from failed checks, and
        fetches their ``--log-failed`` output.  Returns the concatenated
        log text (one section per failed check) or an empty string on
        error or in dry-run mode.
        """
        if self._config.dry_run:
            return ""

        try:
            failed_runs = await self._get_failed_check_runs(pr_number)
        except (RuntimeError, json.JSONDecodeError) as exc:
            logger.warning("Could not fetch CI checks for PR #%d: %s", pr_number, exc)
            return ""

        if not failed_runs:
            return ""

        sections = [
            log
            for name, run_id in failed_runs
            if (log := await self._fetch_run_log(name, run_id))
        ]
        return "\n\n".join(sections)

    _PASSING_STATES = frozenset({"SUCCESS", "NEUTRAL", "SKIPPED"})
    _PENDING_STATES = frozenset(
        {"PENDING", "QUEUED", "IN_PROGRESS", "REQUESTED", "WAITING"}
    )

    def _evaluate_ci_checks(
        self, checks: list[dict[str, Any]], pr_number: int
    ) -> tuple[bool, str] | None:
        """Evaluate completed CI checks.

        Returns ``(passed, message)`` if all checks have finished,
        or ``None`` if any check is still pending.
        """
        pending = [
            c for c in checks if c.get("state", "").upper() in self._PENDING_STATES
        ]
        if pending:
            return None

        failed = [
            c["name"]
            for c in checks
            if c.get("state", "").upper() not in self._PASSING_STATES
        ]
        if failed:
            return False, f"Failed checks: {', '.join(str(n) for n in failed)}"
        return True, f"All {len(checks)} checks passed"

    async def wait_for_ci(
        self,
        pr_number: int,
        timeout: int,
        poll_interval: int,
        stop_event: asyncio.Event,
    ) -> tuple[bool, str]:
        """Poll CI checks until all complete or *timeout* seconds elapse.

        Returns ``(passed, summary_message)``.
        """
        if self._config.dry_run:
            logger.info("[dry-run] Would wait for CI on PR #%d", pr_number)
            return True, "Dry-run: CI skipped"

        elapsed = 0
        while elapsed < timeout:
            if stop_event.is_set():
                return False, "Stopped"

            checks = await self.get_pr_checks(pr_number)

            if not checks:
                return True, "No CI checks found"

            verdict = self._evaluate_ci_checks(checks, pr_number)
            if verdict is None:
                # Still pending — publish event and wait
                pending_count = sum(
                    1
                    for c in checks
                    if c.get("state", "").upper() in self._PENDING_STATES
                )
                await self._bus.publish(
                    HydraFlowEvent(
                        type=EventType.CI_CHECK,
                        data={
                            "pr": pr_number,
                            "status": "pending",
                            "pending": pending_count,
                            "total": len(checks),
                        },
                    )
                )
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=poll_interval)
                    return False, "Stopped"
                except TimeoutError:
                    elapsed += poll_interval
                    continue

            passed, msg = verdict
            data: dict[str, object] = {
                "pr": pr_number,
                "status": "passed" if passed else "failed",
            }
            if not passed:
                # Extract failed names from the message for the event
                data["failed"] = [
                    c["name"]
                    for c in checks
                    if c.get("state", "").upper() not in self._PASSING_STATES
                ]
            else:
                data["total"] = len(checks)
            await self._bus.publish(HydraFlowEvent(type=EventType.CI_CHECK, data=data))
            return passed, msg

        return False, f"Timeout after {timeout}s"

    # --- PR activity query helpers ---

    async def get_pr_head_sha(self, pr_number: int) -> str:
        """Fetch the HEAD commit SHA for *pr_number*.

        Returns the SHA string, or empty string on failure or in dry-run mode.
        """
        if self._config.dry_run:
            logger.info("[dry-run] Would fetch HEAD SHA for PR #%d", pr_number)
            return ""

        try:
            raw = await self._run_gh(
                "gh",
                "pr",
                "view",
                str(pr_number),
                "--repo",
                self._repo,
                "--json",
                "headRefOid",
            )
            data = json.loads(raw)
            return data.get("headRefOid", "")
        except (RuntimeError, json.JSONDecodeError) as exc:
            logger.warning("Could not fetch HEAD SHA for PR #%d: %s", pr_number, exc)
            return ""

    async def get_pr_reviews(self, pr_number: int) -> list[dict[str, str]]:
        """Fetch reviews for *pr_number* with author info.

        Returns a list of dicts with ``author``, ``state``, ``submitted_at``,
        and ``commit_id`` keys.  Returns ``[]`` on failure or in dry-run mode.
        """
        if self._config.dry_run:
            logger.info("[dry-run] Would fetch reviews for PR #%d", pr_number)
            return []

        try:
            raw = await self._run_gh(
                "gh",
                "api",
                f"repos/{self._repo}/pulls/{pr_number}/reviews",
                "--jq",
                "[.[] | {author: .user.login, state: .state, submitted_at: .submitted_at, commit_id: .commit_id}]",
            )
            return json.loads(raw)  # type: ignore[no-any-return]
        except (RuntimeError, json.JSONDecodeError) as exc:
            logger.warning("Could not fetch reviews for PR #%d: %s", pr_number, exc)
            return []

    async def get_pr_comments(self, pr_number: int) -> list[dict[str, str]]:
        """Fetch issue-level comments for *pr_number* with author info.

        Returns a list of dicts with ``author`` and ``created_at`` keys.
        Returns ``[]`` on failure or in dry-run mode.
        """
        if self._config.dry_run:
            logger.info("[dry-run] Would fetch comments for PR #%d", pr_number)
            return []

        try:
            raw = await self._run_gh(
                "gh",
                "api",
                f"repos/{self._repo}/issues/{pr_number}/comments",
                "--jq",
                "[.[] | {author: .user.login, created_at: .created_at}]",
            )
            return json.loads(raw)  # type: ignore[no-any-return]
        except (RuntimeError, json.JSONDecodeError) as exc:
            logger.warning("Could not fetch comments for PR #%d: %s", pr_number, exc)
            return []

    # --- dashboard query helpers ---

    async def list_open_prs(self, labels: list[str]) -> list[PRListItem]:
        """Fetch open PRs for the given *labels*, deduplicated by PR number.

        Returns ``[]`` in dry-run mode or when any individual label query
        fails (the failure is silently skipped so other labels still succeed).
        """
        if self._config.dry_run:
            return []

        seen: set[int] = set()
        prs: list[PRListItem] = []

        for label in labels:
            try:
                raw = await self._run_gh(
                    "gh",
                    "api",
                    f"repos/{self._repo}/issues",
                    "--method",
                    "GET",
                    "--field",
                    "state=open",
                    "--field",
                    f"labels={label}",
                    "--field",
                    "per_page=50",
                    "--jq",
                    "[.[] | select(.pull_request) | {number, url: .html_url, title}]",
                )
                for p in json.loads(raw):
                    pr_num = p.get("number")
                    if pr_num is None:
                        logger.debug(
                            "Skipping PR in list_open_prs: missing 'number' key"
                        )
                        continue
                    if pr_num in seen:
                        continue
                    seen.add(pr_num)
                    try:
                        branch, draft = await self._get_pr_branch_and_draft(pr_num)
                        issue_num = self._issue_number_from_branch(branch)
                        prs.append(
                            PRListItem(
                                pr=pr_num,
                                issue=issue_num,
                                branch=branch,
                                url=p.get("url", ""),
                                draft=draft,
                                title=p.get("title", ""),
                            )
                        )
                    except (RuntimeError, json.JSONDecodeError, KeyError, TypeError):
                        logger.debug("Skipping PR in list_open_prs", exc_info=True)
                        continue
            except (RuntimeError, json.JSONDecodeError, KeyError, TypeError):
                logger.debug("Skipping PR in list_open_prs", exc_info=True)
                continue

        return prs

    async def _fetch_hitl_raw_issues(
        self, hitl_labels: list[str]
    ) -> list[dict[str, Any]]:
        """Fetch and deduplicate open issues matching any of the given HITL labels."""
        seen_issues: set[int] = set()
        raw_issues: list[dict[str, Any]] = []
        for label in hitl_labels:
            try:
                raw = await self._run_gh(
                    "gh",
                    "api",
                    f"repos/{self._repo}/issues",
                    "--method",
                    "GET",
                    "--field",
                    "state=open",
                    "--field",
                    f"labels={label}",
                    "--field",
                    "per_page=50",
                    "--jq",
                    "[.[] | select(.pull_request | not) | {number, title, url: .html_url}]",
                )
                for issue in json.loads(raw):
                    if issue["number"] not in seen_issues:
                        seen_issues.add(issue["number"])
                        raw_issues.append(issue)
            except (RuntimeError, json.JSONDecodeError, KeyError, TypeError):
                logger.warning(
                    "Failed to fetch HITL issues for label",
                    exc_info=True,
                )
        return raw_issues

    async def _build_hitl_item(self, raw_issue: dict[str, Any]) -> HITLItem:
        """Look up the associated PR for one raw issue and assemble a HITLItem."""
        branch = self._config.branch_for_issue(raw_issue["number"])
        pr_number = 0
        pr_url = ""
        try:
            head_filter = f"{self._repo_owner}:{branch}" if self._repo_owner else branch
            pr_raw = await self._run_gh(
                "gh",
                "api",
                f"repos/{self._repo}/pulls",
                "--method",
                "GET",
                "--field",
                "state=open",
                "--field",
                f"head={head_filter}",
                "--field",
                "per_page=1",
                "--jq",
                "[.[] | {number, url: .html_url}]",
            )
            pr_data = json.loads(pr_raw)
            if pr_data:
                pr_number = pr_data[0]["number"]
                pr_url = pr_data[0].get("url", "")
        except (RuntimeError, json.JSONDecodeError, KeyError, TypeError):
            logger.debug(
                "PR lookup failed for branch %s",
                branch,
                exc_info=True,
            )
        return HITLItem(
            issue=raw_issue["number"],
            title=raw_issue.get("title", ""),
            issueUrl=raw_issue.get("url", ""),
            pr=pr_number,
            prUrl=pr_url,
            branch=branch,
        )

    @staticmethod
    def _issue_number_from_branch(branch: str) -> int:
        issue_num = 0
        if branch.startswith("agent/issue-"):
            with contextlib.suppress(ValueError):
                issue_num = int(branch.rsplit("-", maxsplit=1)[-1])
        return issue_num

    async def _get_pr_branch_and_draft(self, pr_number: int) -> tuple[str, bool]:
        """Resolve branch + draft status for a PR via REST API."""
        raw = await self._run_gh(
            "gh",
            "api",
            f"repos/{self._repo}/pulls/{pr_number}",
            "--jq",
            "{headRefName: .head.ref, isDraft: .draft}",
        )
        data = json.loads(raw)
        if isinstance(data, list):
            data = data[0] if data else {}
        if not isinstance(data, dict):
            return "", False
        return str(data.get("headRefName", "")), bool(data.get("isDraft", False))

    async def list_hitl_items(self, hitl_labels: list[str]) -> list[HITLItem]:
        """Fetch HITL issues and look up their associated PRs.

        For each HITL label, fetches open issues, deduplicates by issue
        number, then looks up the associated PR via the ``agent/issue-N``
        branch convention.  Returns ``[]`` in dry-run mode or on failure.
        """
        if self._config.dry_run:
            return []

        try:
            raw_issues = await self._fetch_hitl_raw_issues(hitl_labels)
            return [await self._build_hitl_item(issue) for issue in raw_issues]
        except (RuntimeError, json.JSONDecodeError, KeyError, TypeError):
            logger.warning("Failed to fetch HITL items", exc_info=True)
            return []

    # --- GitHub metrics helpers ---

    async def _search_github_count(self, query: str) -> int:
        """Run a GitHub search query and return the total_count.

        Issues a ``gh api search/issues`` request with the given *query*
        string and returns the ``total_count`` integer.  Returns 0 on
        any error so callers can safely sum results.
        """
        raw = await self._run_gh(
            "gh",
            "api",
            "search/issues",
            "-f",
            f"q={query}",
            "--jq",
            ".total_count",
        )
        return int(raw.strip() or "0")

    async def _count_open_issues_by_label(
        self, label_map: dict[str, list[str]]
    ) -> dict[str, int]:
        """Count open issues for each display key in *label_map*.

        Uses the GitHub Search API (``search/issues``) which returns
        ``total_count`` directly — no pagination, scales to 10k+ issues.
        """
        open_by_label: dict[str, int] = {}
        for display_key, label_names in label_map.items():
            count = 0
            for label in label_names:
                try:
                    count += await self._search_github_count(
                        f'repo:{self._repo} is:issue is:open label:"{label}"'
                    )
                except (RuntimeError, ValueError):
                    logger.debug(
                        "Could not count open issues for label %r",
                        label,
                        exc_info=True,
                    )
            open_by_label[display_key] = count
        return open_by_label

    async def _count_closed_issues(self, labels: list[str]) -> int:
        """Count closed issues with any of the given *labels*.

        Uses the GitHub Search API (``search/issues``) which returns
        ``total_count`` directly — no pagination, scales to 10k+ issues.
        """
        total = 0
        for label in labels:
            try:
                total += await self._search_github_count(
                    f'repo:{self._repo} is:issue is:closed label:"{label}"'
                )
            except (RuntimeError, ValueError):
                logger.debug(
                    "Could not count closed issues for label %r",
                    label,
                    exc_info=True,
                )
        return total

    async def _count_merged_prs(self, label: str) -> int:
        """Count merged PRs with the given *label*.

        Uses the GitHub Search API (``search/issues``) which returns
        ``total_count`` directly — no pagination, scales to 10k+ issues.
        """
        try:
            return await self._search_github_count(
                f'repo:{self._repo} is:pr is:merged label:"{label}"'
            )
        except (RuntimeError, ValueError):
            logger.debug(
                "Could not count merged PRs for label %r",
                label,
                exc_info=True,
            )
            return 0

    async def get_label_counts(self, config: HydraFlowConfig) -> LabelCounts:
        """Query GitHub for issue/PR counts by HydraFlow label.

        Returns a dict with ``open_by_label``, ``total_closed``, and
        ``total_merged`` keys.  Results are cached for 30 seconds.
        """
        import time

        now = time.monotonic()
        if (
            self._label_counts_cache is not None
            and now - self._label_counts_ts < _LABEL_CACHE_TTL
        ):
            return self._label_counts_cache

        label_map = {
            "hydraflow-plan": config.planner_label,
            "hydraflow-ready": config.ready_label,
            "hydraflow-review": config.review_label,
            "hydraflow-hitl": config.hitl_label,
            "hydraflow-fixed": config.fixed_label,
        }

        open_by_label = await self._count_open_issues_by_label(label_map)
        total_closed = await self._count_closed_issues(config.fixed_label)
        fixed_label = config.fixed_label[0] if config.fixed_label else "hydraflow-fixed"
        total_merged = await self._count_merged_prs(fixed_label)

        result: LabelCounts = {
            "open_by_label": open_by_label,
            "total_closed": total_closed,
            "total_merged": total_merged,
        }
        self._label_counts_cache = result
        self._label_counts_ts = now
        return result

    # --- body-file helpers ---

    # Backward-compatible aliases — delegates to CommentFormatter
    @staticmethod
    def _chunk_body(body: str, limit: int | None = None) -> list[str]:
        """Split *body* into chunks that fit within GitHub's comment limit."""
        return CommentFormatter.chunk(body, limit)

    @classmethod
    def _cap_body(cls, body: str, limit: int | None = None) -> str:
        """Hard-truncate *body* to *limit* characters."""
        return CommentFormatter.cap(body, limit)

    async def _run_with_body_file(self, *cmd: str, body: str, cwd: Path) -> str:
        """Run a ``gh`` command using ``--body-file`` instead of ``--body``.

        Writes *body* to a temporary ``.md`` file, passes ``--body-file``
        to the command, and cleans up the file afterwards.
        """
        fd, tmp_path = tempfile.mkstemp(suffix=".md", prefix="hydraflow-body-")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(body)
            return await run_subprocess_with_retry(
                *cmd,
                "--body-file",
                tmp_path,
                cwd=cwd,
                gh_token=self._config.gh_token,
                max_retries=self._max_retries,
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # TaskTransitioner protocol implementation
    # (transition, post_comment, close_task, create_task)
    # ------------------------------------------------------------------

    async def transition(
        self, task_id: int, new_stage: str, *, pr_number: int | None = None
    ) -> None:
        """Implement :class:`task_source.TaskTransitioner` — swap pipeline labels."""
        _STAGE_LABEL = {
            "find": (self._config.find_label or ["hydraflow-find"])[0],
            "plan": (self._config.planner_label or ["hydraflow-plan"])[0],
            "ready": (self._config.ready_label or ["hydraflow-ready"])[0],
            "review": (self._config.review_label or ["hydraflow-review"])[0],
            "hitl": (self._config.hitl_label or ["hydraflow-hitl"])[0],
        }
        label = _STAGE_LABEL.get(new_stage, new_stage)
        await self.swap_pipeline_labels(task_id, label, pr_number=pr_number)

    async def close_task(self, task_id: int) -> None:
        """Implement :class:`task_source.TaskTransitioner` — close the issue."""
        await self.close_issue(task_id)

    async def create_task(
        self, title: str, body: str, labels: list[str] | None = None
    ) -> int:
        """Implement :class:`task_source.TaskTransitioner` — create a new issue."""
        return await self.create_issue(title, body, labels)
