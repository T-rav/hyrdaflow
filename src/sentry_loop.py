"""Background worker loop — Sentry issue ingestion.

Polls the Sentry API for unresolved issues across configured projects,
deduplicates against already-filed GitHub issues, and creates new GitHub
issues labeled for the HydraFlow pipeline.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import httpx

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig

if TYPE_CHECKING:
    from pr_manager import PRManager

logger = logging.getLogger("hydraflow.sentry_loop")

_SENTRY_API = "https://sentry.io/api/0"


class SentryLoop(BaseBackgroundLoop):
    """Polls Sentry for unresolved issues and files them as GitHub issues."""

    def __init__(
        self,
        config: HydraFlowConfig,
        prs: PRManager,
        deps: LoopDeps,
    ) -> None:
        super().__init__(
            worker_name="sentry_ingest",
            config=config,
            deps=deps,
            run_on_startup=True,
        )
        self._prs = prs
        self._filed: set[str] = set()  # Sentry issue IDs already filed

    def _get_default_interval(self) -> int:
        return self._config.sentry_poll_interval

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._config.sentry_auth_token}"}

    async def _do_work(self) -> dict[str, Any] | None:
        if not self._config.sentry_auth_token or not self._config.sentry_org:
            return {"skipped": True, "reason": "no credentials"}

        projects = await self._list_projects()
        total_created = 0
        total_skipped = 0

        for project in projects:
            issues = await self._fetch_unresolved(project["slug"])
            for issue in issues:
                sentry_id = str(issue["id"])
                if sentry_id in self._filed:
                    total_skipped += 1
                    continue

                if await self._already_filed_on_github(sentry_id):
                    self._filed.add(sentry_id)
                    total_skipped += 1
                    continue

                created = await self._create_github_issue(issue, project["slug"])
                if created:
                    self._filed.add(sentry_id)
                    total_created += 1
                else:
                    total_skipped += 1

        return {
            "projects_polled": len(projects),
            "issues_created": total_created,
            "issues_skipped": total_skipped,
        }

    async def _list_projects(self) -> list[dict[str, Any]]:
        """List Sentry projects, optionally filtered by config."""
        org = quote(self._config.sentry_org)
        url = f"{_SENTRY_API}/organizations/{org}/projects/"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=self._headers())
            resp.raise_for_status()
            projects: list[dict[str, Any]] = resp.json()

        if self._config.sentry_project_filter:
            allowed = {
                s.strip()
                for s in self._config.sentry_project_filter.split(",")
                if s.strip()
            }
            projects = [p for p in projects if p["slug"] in allowed]
        return projects

    async def _fetch_unresolved(self, project_slug: str) -> list[dict[str, Any]]:
        """Fetch unresolved issues for a project, newest first."""
        org = quote(self._config.sentry_org)
        url = f"{_SENTRY_API}/projects/{org}/{quote(project_slug)}/issues/"
        params = {"query": "is:unresolved", "sort": "date", "limit": "25"}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=self._headers(), params=params)
            resp.raise_for_status()
            result: list[dict[str, Any]] = resp.json()
            return result

    async def _already_filed_on_github(self, sentry_id: str) -> bool:
        """Check if a GitHub issue already references this Sentry issue ID."""
        marker = f"sentry:{sentry_id}"
        try:
            repo = self._config.repo
            if not repo:
                return False
            raw = await self._prs._run_gh(
                "gh",
                "api",
                "search/issues",
                "-f",
                f"q={marker} repo:{repo} is:issue",
                "--jq",
                ".total_count",
            )
            return int(raw.strip() or "0") > 0
        except Exception:  # noqa: BLE001
            logger.debug("GitHub search failed for sentry:%s", sentry_id, exc_info=True)
            return False

    async def _create_github_issue(
        self, sentry_issue: dict[str, Any], project_slug: str
    ) -> bool:
        """Create a GitHub issue from a Sentry issue."""
        sentry_id = sentry_issue["id"]
        title = sentry_issue.get("title", "Unknown error")
        culprit = sentry_issue.get("culprit", "")
        count = sentry_issue.get("count", "0")
        first_seen = sentry_issue.get("firstSeen", "")
        last_seen = sentry_issue.get("lastSeen", "")
        level = sentry_issue.get("level", "error")
        permalink = sentry_issue.get("permalink", "")
        short_id = sentry_issue.get("shortId", sentry_id)

        body = f"""## Sentry Error: {title}

| Field | Value |
|-------|-------|
| **Sentry ID** | {short_id} |
| **Project** | {project_slug} |
| **Level** | {level} |
| **Events** | {count} |
| **First seen** | {first_seen} |
| **Last seen** | {last_seen} |
| **Culprit** | `{culprit}` |
| **Link** | {permalink} |

### Stack trace location
`{culprit}`

### Notes
Auto-filed from Sentry. Investigate the root cause, fix the error, and add a regression test.

<!-- [sentry:{sentry_id}] -->
"""
        gh_title = f"[Sentry] {title}"
        if len(gh_title) > 200:
            gh_title = gh_title[:197] + "..."

        try:
            labels = self._config.planner_label or ["hydraflow-plan"]
            await self._prs.create_issue(gh_title, body, labels=labels[:1])
            logger.info("Created GitHub issue for Sentry %s: %s", short_id, title)
            return True
        except Exception:  # noqa: BLE001
            logger.exception("Failed to create GitHub issue for Sentry %s", sentry_id)
            return False
