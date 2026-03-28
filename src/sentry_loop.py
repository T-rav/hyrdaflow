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
                    await self._resolve_sentry_issue(sentry_id)
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

    async def _resolve_sentry_issue(self, issue_id: str) -> None:
        """Mark a Sentry issue as resolved so it won't be re-polled.

        If the bug recurs, Sentry auto-reopens it as a new unresolved issue
        and the next poll cycle will pick it up again.
        """
        url = f"{_SENTRY_API}/issues/{issue_id}/"
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.put(
                    url,
                    headers=self._headers(),
                    json={"status": "resolved"},
                )
                resp.raise_for_status()
                logger.debug("Resolved Sentry issue %s", issue_id)
        except Exception:  # noqa: BLE001
            logger.warning("Failed to resolve Sentry issue %s", issue_id, exc_info=True)

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

    async def _fetch_latest_event(self, issue_id: str) -> dict[str, Any] | None:
        """Fetch the latest event for a Sentry issue to get the full stack trace."""
        url = f"{_SENTRY_API}/issues/{issue_id}/events/latest/"
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(url, headers=self._headers())
                resp.raise_for_status()
                result: dict[str, Any] = resp.json()
                return result
        except Exception:  # noqa: BLE001
            logger.debug("Failed to fetch latest event for %s", issue_id, exc_info=True)
            return None

    def _extract_stacktrace(self, event: dict[str, Any]) -> str:
        """Extract a formatted stack trace from a Sentry event."""
        frames: list[str] = []
        for entry in event.get("entries", []):
            if entry.get("type") != "exception":
                continue
            for exc_val in entry.get("data", {}).get("values", []):
                exc_type = exc_val.get("type", "")
                exc_value = exc_val.get("value", "")
                stacktrace = exc_val.get("stacktrace", {})
                for frame in stacktrace.get("frames", [])[-10:]:
                    filename = frame.get("filename", "?")
                    lineno = frame.get("lineNo", "?")
                    func = frame.get("function", "?")
                    context_line = frame.get("context_line", "").strip()
                    line = f"  {filename}:{lineno} in {func}"
                    if context_line:
                        line += f"\n    {context_line}"
                    frames.append(line)
                if exc_type:
                    frames.append(f"\n{exc_type}: {exc_value}")
        return "\n".join(frames) if frames else ""

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

        # Fetch latest event for full stack trace
        event = await self._fetch_latest_event(sentry_id)
        stacktrace = self._extract_stacktrace(event) if event else ""

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
"""

        if stacktrace:
            body += f"""
### Stack trace
```
{stacktrace}
```
"""

        body += f"""
### Instructions
Investigate the root cause of this error. The culprit points to `{culprit}`.
Search the codebase for the failing function, understand the error context,
fix the bug, and add a regression test that reproduces the failure.

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
