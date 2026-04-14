"""Background worker loop — Sentry issue ingestion.

Polls the Sentry API for unresolved issues across configured projects,
deduplicates against already-filed GitHub issues, and invokes a Claude
agent via ``/hf.issue`` to research the codebase and file a properly
triaged GitHub issue — the same flow as dashboard bug reports.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import httpx

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import Credentials, HydraFlowConfig
from dedup_store import DedupStore
from exception_classify import reraise_on_credit_or_bug

if TYPE_CHECKING:
    from execution import SubprocessRunner
    from issue_store import IssueStore  # noqa: TCH004 — used in __init__ signature
    from pr_manager import PRManager
    from state import StateTracker  # noqa: TCH004 — used in __init__ signature

logger = logging.getLogger("hydraflow.sentry_loop")

_SENTRY_API = "https://sentry.io/api/0"
_ISSUE_URL_RE = re.compile(r"https://github\.com/[^/\s]+/[^/\s]+/issues/(\d+)")


class SentryLoop(BaseBackgroundLoop):
    """Polls Sentry for unresolved issues and files them via Claude agent."""

    def __init__(
        self,
        config: HydraFlowConfig,
        prs: PRManager,
        deps: LoopDeps,
        store: IssueStore | None = None,
        runner: SubprocessRunner | None = None,
        credentials: Credentials | None = None,
        dedup: DedupStore | None = None,
        state: StateTracker | None = None,
    ) -> None:
        super().__init__(
            worker_name="sentry_ingest",
            config=config,
            deps=deps,
            run_on_startup=True,
        )
        self._prs = prs
        self._store = store
        self._runner = runner
        self._credentials = credentials or Credentials()
        self._active_procs: set[asyncio.subprocess.Process] = set()
        self._dedup = dedup
        # In-memory hot cache seeded from persistent DedupStore
        self._filed: set[str] = dedup.get() if dedup else set()
        self._state = state

    def _get_default_interval(self) -> int:
        return self._config.sentry_poll_interval

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._credentials.sentry_auth_token}"}

    def _exists_in_local_cache(self, sentry_id: str) -> bool:
        """Check the local issue store for an existing issue with this Sentry ID."""
        if not self._store:
            return False
        marker = f"sentry:{sentry_id}"
        return any(marker in task.body for task in self._store._issue_cache.values())

    def _mark_filed(self, sentry_id: str) -> None:
        """Record a Sentry issue as filed in both hot cache and persistent store."""
        self._filed.add(sentry_id)
        if self._dedup:
            self._dedup.add(sentry_id)

    async def _do_work(self) -> dict[str, Any] | None:
        if not self._credentials.sentry_auth_token or not self._config.sentry_org:
            return {"skipped": True, "reason": "no credentials"}

        projects = await self._list_projects()
        total_created = 0
        total_skipped = 0

        min_events = self._config.sentry_min_events

        for project in projects:
            issues = await self._fetch_unresolved(project["slug"])
            for issue in issues:
                sentry_id = str(issue["id"])
                if sentry_id in self._filed:
                    total_skipped += 1
                    continue

                # Skip low-event-count noise (single-occurrence transients)
                event_count = int(issue.get("count", "0") or "0")
                if event_count < min_events:
                    total_skipped += 1
                    continue

                # Skip handled exceptions — only unhandled errors are real bugs.
                # Works for any language (Python, JS, Go, etc.)
                if not issue.get("isUnhandled", True):
                    logger.debug(
                        "Skipping handled Sentry issue %s: %s",
                        sentry_id,
                        issue.get("title", "")[:60],
                    )
                    self._mark_filed(sentry_id)
                    total_skipped += 1
                    continue

                if self._exists_in_local_cache(sentry_id):
                    self._mark_filed(sentry_id)
                    total_skipped += 1
                    continue

                if await self._already_filed_on_github(sentry_id):
                    self._mark_filed(sentry_id)
                    total_skipped += 1
                    continue

                # Check attempt budget — park after too many failures
                if self._state:
                    attempts = self._state.get_sentry_creation_attempts(sentry_id)
                    if attempts >= self._config.sentry_max_creation_attempts:
                        logger.warning(
                            "Parking Sentry %s after %d failed creation attempts",
                            sentry_id,
                            attempts,
                        )
                        self._mark_filed(sentry_id)
                        total_skipped += 1
                        continue

                created = await self._create_github_issue(issue, project["slug"])
                if created:
                    await self._resolve_sentry_issue(sentry_id)
                    self._mark_filed(sentry_id)
                    if self._state:
                        self._state.clear_sentry_creation_attempts(sentry_id)
                    total_created += 1
                else:
                    if self._state:
                        self._state.fail_sentry_creation(sentry_id)
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
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(url, headers=self._headers())
                resp.raise_for_status()
                projects: list[dict[str, Any]] = resp.json()
        except httpx.HTTPError:
            logger.warning("Sentry API returned error listing projects", exc_info=True)
            return []

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
        params = {"query": "is:unresolved level:error", "sort": "date", "limit": "25"}
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(url, headers=self._headers(), params=params)
                resp.raise_for_status()
                result: list[dict[str, Any]] = resp.json()
                return result
        except httpx.HTTPError:
            logger.warning(
                "Sentry API returned error fetching issues for %s",
                project_slug,
                exc_info=True,
            )
            return []

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
        except Exception as exc:  # noqa: BLE001
            reraise_on_credit_or_bug(exc)
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
        except Exception as exc:  # noqa: BLE001
            reraise_on_credit_or_bug(exc)
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
        except Exception as exc:  # noqa: BLE001
            reraise_on_credit_or_bug(exc)
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
                stacktrace = exc_val.get("stacktrace") or {}
                for frame in (stacktrace.get("frames") or [])[-10:]:
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

    def _build_issue_description(
        self, sentry_issue: dict[str, Any], project_slug: str, stacktrace: str
    ) -> str:
        """Build the description passed to /hf.issue for agent-driven triage."""
        sentry_id = sentry_issue["id"]
        title = sentry_issue.get("title", "Unknown error")
        culprit = sentry_issue.get("culprit", "")
        count = sentry_issue.get("count", "0")
        first_seen = sentry_issue.get("firstSeen", "")
        last_seen = sentry_issue.get("lastSeen", "")
        level = sentry_issue.get("level", "error")
        permalink = sentry_issue.get("permalink", "")
        short_id = sentry_issue.get("shortId", sentry_id)

        plan_lbl = (
            self._config.planner_label[0]
            if self._config.planner_label
            else "hydraflow-plan"
        )

        parts = [
            f"Sentry error from project {project_slug}: {title}",
            f"Sentry ID: {short_id} | Level: {level} | Events: {count}",
            f"First seen: {first_seen} | Last seen: {last_seen}",
            f"Culprit: {culprit}",
            f"Link: {permalink}",
        ]

        if stacktrace:
            parts.append(f"\nStack trace:\n```\n{stacktrace}\n```")

        parts.append(
            f"\nIMPORTANT: Use the label `{plan_lbl}` instead of "
            f"`hydraflow-find` for this issue."
        )
        parts.append(
            f"\nIMPORTANT: Include this HTML comment in the issue body "
            f"for dedup tracking: <!-- [sentry:{sentry_id}] -->"
        )

        return "\n".join(parts)

    async def _create_github_issue(
        self, sentry_issue: dict[str, Any], project_slug: str
    ) -> bool:
        """Invoke a Claude agent via /hf.issue to research and file the issue."""
        sentry_id = sentry_issue["id"]
        short_id = sentry_issue.get("shortId", sentry_id)
        title = sentry_issue.get("title", "Unknown error")

        # Fetch latest event for full stack trace
        event = await self._fetch_latest_event(sentry_id)
        stacktrace = self._extract_stacktrace(event) if event else ""

        description = self._build_issue_description(
            sentry_issue, project_slug, stacktrace
        )
        prompt = f"/hf.issue {description}"

        from agent_cli import build_agent_command  # noqa: PLC0415
        from models import TranscriptEventData  # noqa: PLC0415
        from runner_utils import StreamConfig, stream_claude_process  # noqa: PLC0415

        cmd = build_agent_command(
            tool=self._config.report_issue_tool,
            model=self._config.sentry_model,
            max_turns=10,
        )

        event_data: TranscriptEventData = {"source": "sentry_ingest"}

        try:
            transcript = await stream_claude_process(
                cmd=cmd,
                prompt=prompt,
                cwd=self._config.repo_root,
                active_procs=self._active_procs,
                event_bus=self._bus,
                event_data=event_data,
                logger=logger,
                config=StreamConfig(
                    runner=self._runner,
                    gh_token=self._credentials.gh_token,
                ),
            )
            match = _ISSUE_URL_RE.search(transcript)
            if match:
                issue_number = int(match.group(1))
                logger.info(
                    "Agent filed Sentry %s as issue #%d: %s",
                    short_id,
                    issue_number,
                    title,
                )
                return True
            logger.warning(
                "Agent ran for Sentry %s but no issue URL found in transcript",
                short_id,
            )
            return False
        except Exception as exc:  # noqa: BLE001
            reraise_on_credit_or_bug(exc)
            logger.exception("Agent failed for Sentry %s", sentry_id)
            return False
