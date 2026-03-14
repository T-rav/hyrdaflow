"""RouterContext — shared dependencies and helpers for dashboard route handlers."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import ValidationError

from admin_tasks import TaskResult
from config import HydraFlowConfig
from events import EventBus
from issue_fetcher import IssueFetcher
from metrics_manager import get_metrics_cache_dir
from models import (
    IssueOutcomeType,
    MetricsSnapshot,
)
from pr_manager import PRManager
from state import StateTracker
from transcript_summarizer import TranscriptSummarizer

if TYPE_CHECKING:
    from orchestrator import HydraFlowOrchestrator

from repo_runtime import RepoRuntime, RepoRuntimeRegistry
from repo_store import RepoRecord, RepoStore

logger = logging.getLogger("hydraflow.dashboard")


class RouterContext:
    """Holds shared dependencies and helpers for all dashboard route handlers.

    Replaces the closure-captured variables from the former ``create_router()``
    monolithic function, making each route handler testable and navigable.
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        state: StateTracker,
        pr_manager: PRManager,
        get_orchestrator: Callable[[], HydraFlowOrchestrator | None],
        set_orchestrator: Callable[[HydraFlowOrchestrator], None],
        set_run_task: Callable[[asyncio.Task[None]], None],
        ui_dist_dir: Path,
        template_dir: Path,
        *,
        registry: RepoRuntimeRegistry | None = None,
        repo_store: RepoStore | None = None,
        register_repo_cb: Callable[
            [Path, str | None], Awaitable[tuple[RepoRecord, HydraFlowConfig]]
        ]
        | None = None,
        remove_repo_cb: Callable[[str], Awaitable[bool]] | None = None,
        list_repos_cb: Callable[[], list[RepoRecord]] | None = None,
        default_repo_slug: str | None = None,
        allowed_repo_roots_fn: Callable[[], tuple[str, ...]] | None = None,
    ) -> None:
        # Core dependencies
        self.config = config
        self.event_bus = event_bus
        self.state = state
        self.pr_manager = pr_manager
        self.get_orchestrator = get_orchestrator
        self.set_orchestrator = set_orchestrator
        self.set_run_task = set_run_task
        self.ui_dist_dir = ui_dist_dir
        self.template_dir = template_dir

        # Multi-repo support
        self.registry = registry
        self.repo_store = repo_store
        self.register_repo_cb = register_repo_cb
        self.remove_repo_cb = remove_repo_cb
        self.list_repos_cb = list_repos_cb
        self.default_repo_slug = default_repo_slug

        # Filesystem roots override
        from dashboard_routes._helpers import _allowed_repo_roots

        self.repo_roots_fn = (
            allowed_repo_roots_fn
            if allowed_repo_roots_fn is not None
            else _allowed_repo_roots
        )

        # Derived objects
        self.supervisor_client = None
        self.supervisor_manager = None
        self.issue_fetcher = IssueFetcher(config)
        self.hitl_summarizer = TranscriptSummarizer(
            config, pr_manager, event_bus, state
        )
        self.hitl_summary_inflight: set[int] = set()
        self.hitl_summary_slots = asyncio.Semaphore(3)
        self.hitl_summary_cooldown_seconds = 300

        # Issue history cache
        self.history_cache_file = config.data_path("metrics", "history_cache.json")
        self.HISTORY_CACHE_TTL = 30  # seconds
        self.history_cache: dict[str, Any] = {
            "event_count": -1,
            "telemetry_mtime": 0.0,
            "issue_rows": None,
            "pr_to_issue": None,
            "enriched_issues": set(),
        }
        self.history_cache_ts: list[float] = [0.0]

        # Warm the in-memory cache from disk on startup.
        try:
            self.load_history_cache()
        except Exception:
            logger.warning("History cache warm-up failed", exc_info=True)

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def resolve_runtime(
        self, slug: str | None
    ) -> tuple[
        HydraFlowConfig,
        StateTracker,
        EventBus,
        Callable[[], HydraFlowOrchestrator | None],
    ]:
        """Resolve per-repo dependencies from the registry.

        When *slug* is ``None`` or no registry is configured, returns the
        single-repo closure defaults for backward compatibility.
        """
        if self.registry is not None and slug is not None:
            rt: RepoRuntime | None = self.registry.get(slug)
            if rt is None:
                raise HTTPException(status_code=404, detail=f"Unknown repo: {slug}")
            return rt.config, rt.state, rt.event_bus, lambda: rt.orchestrator
        return self.config, self.state, self.event_bus, self.get_orchestrator

    async def execute_admin_task(
        self,
        task_name: str,
        task_fn: Callable[[HydraFlowConfig], Awaitable[TaskResult]],
        slug: str | None,
    ) -> JSONResponse:
        try:
            runtime_config, _, _, _ = self.resolve_runtime(slug)
        except HTTPException:
            return JSONResponse({"error": "Unknown repo"}, status_code=404)
        try:
            result = await task_fn(runtime_config)
        except Exception:  # noqa: BLE001
            logger.exception("%s task failed", task_name)
            return JSONResponse({"error": f"{task_name} failed"}, status_code=500)
        payload: dict[str, Any] = {"status": "ok", "result": result.as_dict()}
        status_code = 200
        if not result.success:
            payload["status"] = "error"
            status_code = 500
        return JSONResponse(payload, status_code=status_code)

    def pr_manager_for(self, cfg: HydraFlowConfig, bus: EventBus) -> PRManager:
        """Return the shared PRManager when config matches; otherwise create a new one."""
        if cfg is self.config and bus is self.event_bus:
            return self.pr_manager
        return PRManager(cfg, bus)

    def list_repo_records(self) -> list[RepoRecord]:
        """Return repo records from the callback or store, with error fallback."""
        if self.list_repos_cb is not None:
            try:
                return self.list_repos_cb()
            except Exception:  # noqa: BLE001
                logger.warning("list_repos callback failed", exc_info=True)
        if self.repo_store is not None:
            try:
                return self.repo_store.list()
            except Exception:  # noqa: BLE001
                logger.warning("repo_store.list failed", exc_info=True)
        return []

    def serve_spa_index(self) -> HTMLResponse:
        """Serve the SPA index.html, falling back to template or placeholder."""
        react_index = self.ui_dist_dir / "index.html"
        if react_index.exists():
            return HTMLResponse(react_index.read_text())
        template_path = self.template_dir / "index.html"
        if template_path.exists():
            return HTMLResponse(template_path.read_text())
        return HTMLResponse(
            "<h1>HydraFlow Dashboard</h1><p>Run 'make ui' to build.</p>"
        )

    def load_local_metrics_cache(
        self,
        target_config: HydraFlowConfig,
        limit: int = 100,
    ) -> list[MetricsSnapshot]:
        """Load metrics snapshots from local disk cache without requiring the orchestrator."""
        cache_file = get_metrics_cache_dir(target_config) / "snapshots.jsonl"
        if not cache_file.exists():
            return []
        snapshots: list[MetricsSnapshot] = []
        try:
            with open(cache_file) as f:
                for raw_line in f:
                    stripped = raw_line.strip()
                    if not stripped:
                        continue
                    try:
                        snapshots.append(MetricsSnapshot.model_validate_json(stripped))
                    except ValidationError:
                        logger.debug(
                            "Skipping corrupt metrics snapshot line",
                            exc_info=True,
                        )
                        continue
        except OSError:
            logger.warning(
                "Could not read metrics cache %s",
                cache_file,
                exc_info=True,
            )
            return []
        return snapshots[-limit:]

    # ------------------------------------------------------------------
    # HITL summary helpers
    # ------------------------------------------------------------------

    def build_hitl_context(self, issue: Any, *, cause: str, origin: str | None) -> str:
        """Build a text context block for HITL summary generation."""
        body = (issue.body or "").strip()
        comments = issue.comments
        recent_comments = [str(c).strip() for c in comments[-5:] if str(c).strip()]
        comments_block = "\n".join(f"- {c[:400]}" for c in recent_comments)
        origin_text = origin or "unknown"
        return (
            f"Issue #{issue.number}: {issue.title}\n"
            f"Escalation cause: {cause or 'not recorded'}\n"
            f"Escalation origin: {origin_text}\n\n"
            f"Issue body:\n{body[:6000]}\n\n"
            f"Recent comments:\n{comments_block[:3000]}"
        )

    @staticmethod
    def normalise_summary_lines(raw: str) -> str:
        """Strip bullet prefixes and cap a summary to 8 lines."""
        lines = [line.strip(" -\t") for line in raw.splitlines() if line.strip()]
        return "\n".join(lines[:8]).strip()

    def hitl_summary_retry_due(self, issue_number: int) -> bool:
        """Return True if enough time has passed to retry a failed HITL summary."""
        from dashboard_routes._helpers import _parse_iso_or_none

        failed_at, _ = self.state.get_hitl_summary_failure(issue_number)
        failed_dt = _parse_iso_or_none(failed_at)
        if failed_dt is None:
            return True
        age = (datetime.now(UTC) - failed_dt).total_seconds()
        return age >= self.hitl_summary_cooldown_seconds

    async def compute_hitl_summary(
        self, issue_number: int, *, cause: str, origin: str | None
    ) -> str | None:
        """Fetch issue, generate and normalise a HITL summary, then persist to state."""
        if (
            not self.config.transcript_summarization_enabled
            or self.config.dry_run
            or not self.config.gh_token
        ):
            return None
        issue = await self.issue_fetcher.fetch_issue_by_number(issue_number)
        if issue is None:
            self.state.set_hitl_summary_failure(issue_number, "Issue fetch failed")
            return None
        context = self.build_hitl_context(issue, cause=cause, origin=origin)
        generated = await self.hitl_summarizer.summarize_hitl_context(context)
        if not generated:
            self.state.set_hitl_summary_failure(
                issue_number, "Summary model returned empty"
            )
            return None
        summary = self.normalise_summary_lines(generated)
        if not summary:
            self.state.set_hitl_summary_failure(
                issue_number, "Summary normalization produced empty output"
            )
            return None
        self.state.set_hitl_summary(issue_number, summary)
        self.state.clear_hitl_summary_failure(issue_number)
        return summary

    async def warm_hitl_summary(
        self, issue_number: int, *, cause: str, origin: str | None
    ) -> None:
        """Schedule background HITL summary generation, guarded by inflight tracking."""
        if issue_number in self.hitl_summary_inflight:
            return
        self.hitl_summary_inflight.add(issue_number)
        try:
            async with self.hitl_summary_slots:
                await self.compute_hitl_summary(
                    issue_number, cause=cause, origin=origin
                )
        except Exception as exc:
            self.state.set_hitl_summary_failure(
                issue_number,
                f"{type(exc).__name__}: {exc}",
            )
            logger.exception(
                "Failed to warm HITL summary for issue #%d",
                issue_number,
            )
        finally:
            self.hitl_summary_inflight.discard(issue_number)

    # ------------------------------------------------------------------
    # HITL state helpers
    # ------------------------------------------------------------------

    def clear_hitl_state(
        self,
        orch: HydraFlowOrchestrator | None,
        issue_number: int,
    ) -> None:
        """Clear all HITL tracking state for an issue."""
        if orch:
            orch.skip_hitl_issue(issue_number)
        self.state.remove_hitl_origin(issue_number)
        self.state.remove_hitl_cause(issue_number)
        self.state.remove_hitl_summary(issue_number)

    async def resolve_hitl_item(
        self,
        issue_number: int,
        orch: Any,
        *,
        action: str,
        comment_heading: str,
        comment_body: str,
        outcome_type: IssueOutcomeType,
        reason: str,
    ) -> JSONResponse:
        """Clear HITL state, record outcome, post comment, and publish event."""
        from events import EventType, HydraFlowEvent
        from models import HITLUpdatePayload

        self.clear_hitl_state(orch, issue_number)
        self.state.record_outcome(
            issue_number,
            outcome_type,
            reason=reason,
            phase="hitl",
        )

        try:
            await self.pr_manager.post_comment(
                issue_number,
                f"**{comment_heading}** — {comment_body}\n\n---\n*HydraFlow Dashboard*",
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "Failed to post %s comment for issue #%d",
                action,
                issue_number,
                exc_info=True,
            )

        await self.event_bus.publish(
            HydraFlowEvent(
                type=EventType.HITL_UPDATE,
                data=HITLUpdatePayload(
                    issue=issue_number,
                    status="resolved",
                    action=action,
                    reason=reason,
                ),
            )
        )
        return JSONResponse({"status": "ok"})

    # ------------------------------------------------------------------
    # Issue history cache
    # ------------------------------------------------------------------

    def save_history_cache(self) -> None:
        """Persist in-memory history cache to disk."""
        rows = self.history_cache.get("issue_rows")
        if rows is None:
            return
        serialisable_rows: dict[str, Any] = {}
        for k, v in rows.items():
            entry = dict(v)
            entry["session_ids"] = sorted(entry.get("session_ids") or [])
            serialisable_rows[str(k)] = entry
        payload = {
            "event_count": self.history_cache.get("event_count", -1),
            "telemetry_mtime": self.history_cache.get("telemetry_mtime", 0.0),
            "issue_rows": serialisable_rows,
            "pr_to_issue": {
                str(k): v
                for k, v in (self.history_cache.get("pr_to_issue") or {}).items()
            },
            "enriched_issues": sorted(self.history_cache.get("enriched_issues") or []),
        }
        try:
            self.history_cache_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.history_cache_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload))
            tmp.replace(self.history_cache_file)
        except OSError:
            logger.debug("Could not persist history cache", exc_info=True)

    def load_history_cache(self) -> None:
        """Load persisted history cache from disk into memory."""
        if not self.history_cache_file.is_file():
            return
        try:
            raw = json.loads(self.history_cache_file.read_text())
        except (OSError, json.JSONDecodeError, ValueError):
            logger.debug("Corrupt history cache, ignoring", exc_info=True)
            return
        if not isinstance(raw, dict) or "issue_rows" not in raw:
            return
        rows: dict[int, dict[str, Any]] = {}
        for k, v in raw.get("issue_rows", {}).items():
            if not isinstance(v, dict):
                continue
            entry = dict(v)
            entry["session_ids"] = set(entry.get("session_ids") or [])
            if isinstance(entry.get("prs"), dict):
                entry["prs"] = {int(pk): pv for pk, pv in entry["prs"].items()}
            if isinstance(entry.get("linked_issues"), dict):
                entry["linked_issues"] = {
                    int(lk): lv for lk, lv in entry["linked_issues"].items()
                }
            rows[int(k)] = entry
        self.history_cache["issue_rows"] = rows
        self.history_cache["pr_to_issue"] = {
            int(k): int(v) for k, v in raw.get("pr_to_issue", {}).items()
        }
        self.history_cache["event_count"] = raw.get("event_count", -1)
        self.history_cache["telemetry_mtime"] = raw.get("telemetry_mtime", 0.0)
        self.history_cache["enriched_issues"] = set(raw.get("enriched_issues") or [])
        self.history_cache_ts[0] = time.monotonic()

    # ------------------------------------------------------------------
    # Issue history aggregation helpers
    # ------------------------------------------------------------------

    def new_issue_history_entry(self, issue_number: int) -> dict[str, Any]:
        """Create a blank history aggregation row for an issue."""
        from dashboard_routes._helpers import _INFERENCE_COUNTER_KEYS

        repo_slug = (self.config.repo or "").strip()
        if repo_slug.startswith("https://github.com/"):
            repo_slug = repo_slug[len("https://github.com/") :]
        elif repo_slug.startswith("http://github.com/"):
            repo_slug = repo_slug[len("http://github.com/") :]
        repo_slug = repo_slug.strip("/")
        issue_url = (
            f"https://github.com/{repo_slug}/issues/{issue_number}" if repo_slug else ""
        )
        return {
            "issue_number": issue_number,
            "title": f"Issue #{issue_number}",
            "issue_url": issue_url,
            "status": "unknown",
            "epic": "",
            "crate_number": None,
            "crate_title": "",
            "linked_issues": {},
            "prs": {},
            "session_ids": set(),
            "source_calls": {},
            "model_calls": {},
            "inference": dict.fromkeys(_INFERENCE_COUNTER_KEYS, 0),
            "first_seen": None,
            "last_seen": None,
            "status_updated_at": None,
        }
