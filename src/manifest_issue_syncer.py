"""Synchronise manifest snapshots to GitHub issues."""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime

from config import HydraFlowConfig
from pr_manager import PRManager
from state import StateTracker
from subprocess_util import run_subprocess

logger = logging.getLogger("hydraflow.manifest_issue_syncer")


class ManifestIssueSyncer:
    """Push manifest snapshots to GitHub issues tagged with hydraflow-manifest."""

    def __init__(
        self,
        config: HydraFlowConfig,
        state: StateTracker,
        prs: PRManager,
    ) -> None:
        self._config = config
        self._state = state
        self._prs = prs
        self._owner_tag = (
            config.git_user_name
            or os.environ.get("USER")
            or os.environ.get("USERNAME")
            or "hydraflow"
        )

    async def sync(
        self,
        manifest_markdown: str,
        digest_hash: str,
        *,
        source: str = "manifest-refresh",
    ) -> None:
        """Ensure the manifest issue has an up-to-date snapshot comment."""
        if not self._config.manifest_label:
            return
        if not manifest_markdown.strip():
            logger.debug("Skipping manifest sync — empty manifest body")
            return
        if self._state.get_manifest_snapshot_hash() == digest_hash:
            logger.debug("Manifest snapshot already synced (hash=%s)", digest_hash)
            return

        issue_number = await self._ensure_manifest_issue()
        if issue_number == 0:
            logger.warning("Could not ensure hydraflow-manifest issue exists")
            return
        body = self._format_comment(manifest_markdown, digest_hash, source=source)
        await self._prs.post_comment(issue_number, body)
        await self._prs.close_issue(issue_number)
        self._state.set_manifest_snapshot_hash(digest_hash)
        logger.info(
            "Posted manifest snapshot (%s) to issue #%d",
            digest_hash,
            issue_number,
        )

    async def _ensure_manifest_issue(self) -> int:
        """Find or create the manifest persistence issue."""
        cached = self._state.get_manifest_issue_number()
        if cached:
            return cached

        existing = await self._find_existing_manifest_issue()
        if existing is not None:
            self._state.set_manifest_issue_number(existing)
            return existing

        title = f"HydraFlow Manifest — {self._owner_tag}"
        body = (
            "## HydraFlow Manifest Sync\n\n"
            "This issue captures repository manifest snapshots produced by HydraFlow.\n\n"
            f"- **Owner:** {self._owner_tag}\n"
            f"- **Repo:** {self._config.repo or self._config.repo_root.name}\n\n"
            "A new comment will be added whenever the local manifest changes.\n\n"
            "---\n*Managed by HydraFlow Manifest Syncer*"
        )
        issue_number = await self._prs.create_issue(
            title,
            body,
            list(self._config.manifest_label),
        )
        if issue_number:
            self._state.set_manifest_issue_number(issue_number)
        return issue_number

    async def _find_existing_manifest_issue(self) -> int | None:
        """Search for an existing manifest issue (open or closed)."""
        if not self._config.manifest_label:
            return None
        label = self._config.manifest_label[0]
        try:
            raw = await run_subprocess(
                "gh",
                "issue",
                "list",
                "--repo",
                self._config.repo,
                "--label",
                label,
                "--state",
                "all",
                "--json",
                "number,title,state",
                "--limit",
                "100",
                gh_token=self._config.gh_token,
            )
            issues = json.loads(raw)
        except (RuntimeError, json.JSONDecodeError) as exc:
            logger.warning("Could not search manifest issues: %s", exc)
            return None

        owner_lower = self._owner_tag.lower()
        for issue in issues:
            title = str(issue.get("title", "")).lower()
            if owner_lower in title:
                return int(issue["number"])
        return None

    @staticmethod
    def _format_comment(
        manifest_markdown: str,
        digest_hash: str,
        *,
        source: str,
    ) -> str:
        timestamp = datetime.now(UTC).isoformat()
        trimmed = manifest_markdown.strip()
        return "\n".join(
            [
                f"## Manifest Snapshot — {timestamp}",
                f"*Source:* `{source}`  ",
                f"*Hash:* `{digest_hash}`",
                "",
                "<details>",
                "<summary>Manifest Markdown</summary>",
                "",
                "```markdown",
                trimmed,
                "```",
                "",
                "</details>",
                "",
                "---",
                "*Synced automatically by HydraFlow Manifest Manager*",
            ]
        )
