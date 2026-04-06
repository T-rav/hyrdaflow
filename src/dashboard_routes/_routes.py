"""Route handlers for the HydraFlow dashboard API."""

from __future__ import annotations

import asyncio
import contextlib
import copy
import json
import logging
import os
import re
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from fastapi import (
    APIRouter,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from admin_tasks import TaskResult
from app_version import get_app_version
from config import Credentials, HydraFlowConfig
from dashboard_routes._common import (
    _EPIC_INTERNAL_LABELS,
    _FRONTEND_STAGE_TO_LABEL_FIELD,
    _INFERENCE_COUNTER_KEYS,
    _STAGE_NAME_MAP,
    _coerce_history_status,
    _coerce_int,
    _extract_field_from_sources,
    _is_timestamp_in_range,
    _parse_iso_or_none,
    _status_sort_key,
)
from events import EventBus, EventType, HydraFlowEvent
from github_cache_loop import GitHubDataCache
from issue_fetcher import IssueFetcher
from models import (
    BGWorkerHealth,
    GitHubIssue,
    HITLEscalationPayload,
    IntentRequest,
    IntentResponse,
    IssueHistoryEntry,
    IssueHistoryLink,
    IssueHistoryPR,
    IssueHistoryResponse,
    IssueOutcome,
    IssueOutcomeType,
    PipelineIssue,
    PipelineSnapshot,
    PipelineSnapshotEntry,
    QueueStats,
    parse_task_links,
)
from pr_manager import PRManager
from prompt_telemetry import PromptTelemetry
from route_types import RepoSlugParam
from state import StateTracker
from timeline import TimelineBuilder
from transcript_summarizer import TranscriptSummarizer

if TYPE_CHECKING:
    from hindsight import HindsightClient
    from orchestrator import HydraFlowOrchestrator
from repo_runtime import RepoRuntime, RepoRuntimeRegistry
from repo_store import RepoRecord, RepoStore

logger = logging.getLogger("hydraflow.dashboard")


async def _run_dialog_command(*cmd: str, timeout_seconds: float = 30.0) -> str | None:
    """Run a folder-picker shell command and return trimmed stdout on success."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
    except (FileNotFoundError, OSError, TimeoutError):
        return None
    if proc.returncode != 0:
        return None
    selected = (stdout or b"").decode().strip()
    return selected or None


async def _pick_folder_with_dialog() -> str | None:
    """Open a best-effort native folder picker and return the selected path."""
    # NOTE: avoid Tk-based pickers here. This endpoint may run off the main
    # thread, and macOS AppKit requires UI objects to be created on main thread.
    if sys.platform == "darwin":
        selected = await _run_dialog_command(
            "osascript",
            "-e",
            'POSIX path of (choose folder with prompt "Select repository folder")',
        )
        if selected:
            return selected
    elif sys.platform.startswith("linux"):
        selected = await _run_dialog_command(
            "zenity",
            "--file-selection",
            "--directory",
            "--title=Select repository folder",
        )
        if selected:
            return selected
    elif sys.platform.startswith("win"):
        selected = await _run_dialog_command(
            "powershell",
            "-NoProfile",
            "-Command",
            (
                "[System.Reflection.Assembly]::LoadWithPartialName"
                "('System.Windows.Forms') | Out-Null; "
                "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
                "if ($d.ShowDialog() -eq 'OK') { Write-Output $d.SelectedPath }"
            ),
        )
        if selected:
            return selected
    return None


def _allowed_repo_roots() -> tuple[str, ...]:
    """Return normalized filesystem roots that repo browsing is allowed within."""
    roots = [
        os.path.realpath(str(Path.home())),
        os.path.realpath(tempfile.gettempdir()),
    ]
    deduped: list[str] = []
    for root in roots:
        if root not in deduped:
            deduped.append(root)
    return tuple(deduped)


def _normalize_allowed_dir(
    raw_path: str | None,
    allowed_roots: tuple[str, ...] | None = None,
) -> tuple[Path | None, str | None]:
    """Validate and normalize a directory path constrained to allowed roots.

    Parameters
    ----------
    allowed_roots:
        Override the default roots returned by :func:`_allowed_repo_roots`.
        Useful for testing without patching private module internals.
    """
    candidate = (raw_path or "").strip()
    if not candidate:
        return None, "path required"
    expanded = os.path.expanduser(candidate)
    if "\x00" in expanded:
        return None, "invalid path"
    candidate_abs = os.path.abspath(expanded)
    for root in allowed_roots if allowed_roots is not None else _allowed_repo_roots():
        root_real = os.path.realpath(root)
        with contextlib.suppress(ValueError):
            relative = os.path.relpath(candidate_abs, root_real)
            if relative == os.pardir or relative.startswith(f"{os.pardir}{os.sep}"):
                continue
            parts = [part for part in Path(relative).parts if part not in ("", ".")]
            if any(part == os.pardir for part in parts):
                continue
            resolved = Path(root_real).joinpath(*parts).resolve(strict=False)
            if os.path.commonpath([str(resolved), root_real]) != root_real:
                continue
            return resolved, None
    return None, "path must be inside your home directory or temp directory"


def _event_issue_number(data: Mapping[str, Any]) -> int | None:
    """Extract the issue number from an event data dict, coercing strings."""
    value = data.get("issue")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _normalise_event_status(
    event_type: EventType, data: Mapping[str, Any]
) -> str | None:
    """Map an event type and its data to a normalised history status string."""
    status = str(data.get("status", "")).lower()
    result: str | None = None
    if event_type == EventType.MERGE_UPDATE:
        result = "merged" if status == "merged" else None
    elif event_type == EventType.HITL_ESCALATION:
        result = "hitl"
    elif event_type == EventType.HITL_UPDATE:
        result = "reviewed" if status == "resolved" else "hitl"
    elif event_type == EventType.REVIEW_UPDATE:
        if status == "done":
            result = "reviewed"
        elif status == "failed":
            result = "failed"
        else:
            result = "active"
    elif event_type in {
        EventType.WORKER_UPDATE,
        EventType.PLANNER_UPDATE,
        EventType.TRIAGE_UPDATE,
    }:
        if status == "done":
            done_map = {
                EventType.WORKER_UPDATE: "implemented",
                EventType.PLANNER_UPDATE: "planned",
                EventType.TRIAGE_UPDATE: "triaged",
            }
            result = done_map.get(event_type, "active")
        elif status == "failed":
            result = "failed"
        else:
            result = "active"
    elif event_type == EventType.PR_CREATED:
        result = "in_review"
    return result


def _extract_repo_slug(
    req: dict[str, Any] | None,
    req_query: str | None,
    slug_query: str | None,
    repo_query: str | None,
) -> str:
    """Extract repo slug from supported request shapes."""
    return _extract_field_from_sources(
        ("slug", "repo"),
        req,
        req_query,
        (slug_query, repo_query),
        query_params_first=True,
    )


def _extract_repo_path(
    req: dict[str, Any] | None,
    req_query: str | None,
    path_query: str | None,
    repo_path_query: str | None,
) -> str:
    """Extract repo path from supported body/query payload shapes."""
    return _extract_field_from_sources(
        ("path", "repo_path"),
        req,
        req_query,
        (path_query, repo_path_query),
        query_params_first=False,
    )


_ISSUE_URL_RE = re.compile(r"https://github\.com/[^/\s]+/[^/\s]+/issues/(\d+)")


def _extract_issue_number(url: str) -> int:
    """Extract the issue number from a GitHub issue URL, or return 0."""
    m = _ISSUE_URL_RE.search(url)
    return int(m.group(1)) if m else 0


def _is_likely_disconnect(exc: BaseException) -> bool:
    """Return True if *exc* looks like a normal WebSocket disconnect rather than a code bug."""
    disconnect_types = (
        ConnectionResetError,
        ConnectionAbortedError,
        BrokenPipeError,
    )
    if isinstance(exc, disconnect_types):
        return True
    name = type(exc).__name__
    # Starlette / uvicorn raise these on unclean disconnects.
    return name in {
        "WebSocketDisconnect",
        "ConnectionClosedError",
        "ConnectionClosedOK",
    }


@dataclass
class RouteContext:
    """Bundles all dependencies needed by dashboard route handlers.

    Replaces the closure-capture pattern used by ``create_router()`` so that
    sub-routers can receive an explicit context object instead of relying on
    17+ closure variables.  This is a prerequisite for decomposing the
    monolithic router into smaller sub-router modules.
    """

    # Core services
    config: HydraFlowConfig
    credentials: Credentials
    event_bus: EventBus
    state: StateTracker
    pr_manager: PRManager

    # Orchestrator lifecycle callbacks
    get_orchestrator: Callable[[], HydraFlowOrchestrator | None]
    set_orchestrator: Callable[[HydraFlowOrchestrator], None]
    set_run_task: Callable[[asyncio.Task[None]], None]

    # Static asset directories
    ui_dist_dir: Path
    template_dir: Path

    # Multi-repo support
    registry: RepoRuntimeRegistry | None = None
    repo_store: RepoStore | None = None
    register_repo_cb: (
        Callable[[Path, str | None], Awaitable[tuple[RepoRecord, HydraFlowConfig]]]
        | None
    ) = None
    remove_repo_cb: Callable[[str], Awaitable[bool]] | None = None
    list_repos_cb: Callable[[], list[RepoRecord]] | None = None
    default_repo_slug: str | None = None
    allowed_repo_roots_fn: Callable[[], tuple[str, ...]] | None = None

    # Hindsight integration
    hindsight_client: HindsightClient | None = None

    # HITL summary tuning
    hitl_summary_cooldown_seconds: int = 300

    # Derived state — initialised in __post_init__
    issue_fetcher: IssueFetcher = field(init=False)
    hitl_summarizer: TranscriptSummarizer = field(init=False)
    hitl_summary_inflight: set[int] = field(init=False)
    hitl_summary_slots: asyncio.Semaphore = field(init=False)

    def __post_init__(self) -> None:
        self.issue_fetcher = IssueFetcher(self.config, credentials=self.credentials)
        self.hitl_summarizer = TranscriptSummarizer(
            self.config,
            self.pr_manager,
            self.event_bus,
            self.state,
            credentials=self.credentials,
        )
        self.hitl_summary_inflight = set()
        self.hitl_summary_slots = asyncio.Semaphore(3)

    # -- Dependency resolution helpers ------------------------------------------

    def _is_default_repo(self, slug: str) -> bool:
        """Check if *slug* refers to the default (host) repo."""
        default = self.config.repo
        if not default:
            return False
        normalized = default.replace("/", "-")
        slug_lower = slug.lower()
        return slug_lower in (default.lower(), normalized.lower())

    def _is_default_pipeline_active(self) -> bool:
        """Check if the default repo's pipeline is enabled.

        Returns True when no orchestrator exists (headless/test mode).
        """
        orch = self.get_orchestrator()
        if orch is None:
            return True
        if not orch.running:
            return False
        return orch.pipeline_enabled

    def is_repo_pipeline_active(self, slug: str | None) -> bool:
        """Return whether the resolved repo's pipeline is actively processing.

        When *slug* is ``None`` (All repos view), returns True if ANY
        repo (default or added) has an active pipeline.
        """
        if slug is None:
            if self._is_default_pipeline_active():
                return True
            if self.registry is not None:
                return any(getattr(rt, "running", False) for rt in self.registry.all)
            return False
        if self._is_default_repo(slug):
            return self._is_default_pipeline_active()
        if self.registry is not None:
            rt = self.registry.get(slug)
            if rt is not None:
                return getattr(rt, "running", False)
        return False

    def resolve_runtime(
        self,
        slug: str | None,
    ) -> tuple[
        HydraFlowConfig,
        StateTracker,
        EventBus,
        Callable[[], HydraFlowOrchestrator | None],
    ]:
        """Resolve per-repo dependencies from the registry.

        When *slug* is ``None``, matches the default repo, or no registry is
        configured, returns the single-repo defaults for backward compatibility.
        """
        if self.registry is not None and slug is not None:
            if self._is_default_repo(slug):
                return self.config, self.state, self.event_bus, self.get_orchestrator
            rt: RepoRuntime | None = self.registry.get(slug)
            if rt is not None:
                return rt.config, rt.state, rt.event_bus, lambda: rt.orchestrator
            # Also try case-insensitive match before giving up
            slug_lower = slug.lower()
            for registered_rt in self.registry.all:
                if registered_rt.slug.lower() == slug_lower:
                    return (
                        registered_rt.config,
                        registered_rt.state,
                        registered_rt.event_bus,
                        lambda _rt=registered_rt: _rt.orchestrator,
                    )
            # Repo may be registered (in /api/repos) but not yet started
            # (not in the runtime registry). Fall back to defaults so the
            # WS connects and the UI renders — just with no live events.
            logger.debug("Repo %r not in runtime registry — using defaults", slug)
            return self.config, self.state, self.event_bus, self.get_orchestrator
        return self.config, self.state, self.event_bus, self.get_orchestrator

    async def execute_admin_task(
        self,
        task_name: str,
        task_fn: Callable[[HydraFlowConfig], Awaitable[TaskResult]],
        slug: str | None,
    ) -> JSONResponse:
        """Run an admin task against the resolved repo config."""
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

    def repo_roots_fn(self) -> tuple[str, ...]:
        """Return the allowed repo roots, using the override if provided."""
        if self.allowed_repo_roots_fn is not None:
            return self.allowed_repo_roots_fn()
        return _allowed_repo_roots()

    def hitl_summary_retry_due(self, issue_number: int) -> bool:
        """Return True if enough time has passed to retry a failed HITL summary."""
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
            or not self.credentials.gh_token
        ):
            return None
        issue = await self.issue_fetcher.fetch_issue_by_number(issue_number)
        if issue is None:
            self.state.set_hitl_summary_failure(issue_number, "Issue fetch failed")
            return None
        context = _build_hitl_context(issue, cause=cause, origin=origin)
        generated = await self.hitl_summarizer.summarize_hitl_context(context)
        if not generated:
            self.state.set_hitl_summary_failure(
                issue_number, "Summary model returned empty"
            )
            return None
        summary = _normalise_summary_lines(generated)
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


def _build_hitl_context(issue: GitHubIssue, *, cause: str, origin: str | None) -> str:
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


def _normalise_summary_lines(raw: str) -> str:
    """Strip bullet prefixes and cap a summary to 8 lines."""
    lines = [line.strip(" -\t") for line in raw.splitlines() if line.strip()]
    return "\n".join(lines[:8]).strip()


def create_router(
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
    credentials: Credentials | None = None,
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
    hindsight_client: HindsightClient | None = None,
) -> APIRouter:
    """Create an APIRouter with all dashboard route handlers.

    When *registry* is provided, operational endpoints accept an optional
    ``repo`` query parameter to target a specific repo runtime.  When the
    parameter is omitted, the single-repo defaults (closure-captured
    *config*, *state*, *event_bus*, and *get_orchestrator*) are used for
    backward compatibility.
    """
    # Build the shared RouteContext that bundles all dependencies.
    _creds = credentials or Credentials()
    ctx = RouteContext(
        config=config,
        credentials=_creds,
        event_bus=event_bus,
        state=state,
        pr_manager=pr_manager,
        get_orchestrator=get_orchestrator,
        set_orchestrator=set_orchestrator,
        set_run_task=set_run_task,
        ui_dist_dir=ui_dist_dir,
        template_dir=template_dir,
        registry=registry,
        repo_store=repo_store,
        register_repo_cb=register_repo_cb,
        remove_repo_cb=remove_repo_cb,
        list_repos_cb=list_repos_cb,
        default_repo_slug=default_repo_slug,
        allowed_repo_roots_fn=allowed_repo_roots_fn,
        hindsight_client=hindsight_client,
    )

    router = APIRouter()

    # Thin delegates — route handlers call these; logic lives on RouteContext.
    def _resolve_runtime(
        slug: str | None,
    ) -> tuple[
        HydraFlowConfig,
        StateTracker,
        EventBus,
        Callable[[], HydraFlowOrchestrator | None],
    ]:
        return ctx.resolve_runtime(slug)

    def _is_pipeline_active(slug: str | None) -> bool:
        """Check if the selected repo's pipeline is running.

        When no repo is selected (All repos view), checks the default
        repo's pipeline state — data only shows when something is
        actually running.
        """
        return ctx.is_repo_pipeline_active(slug)

    async def _execute_admin_task(
        task_name: str,
        task_fn: Callable[[HydraFlowConfig], Awaitable[TaskResult]],
        slug: str | None,
    ) -> JSONResponse:
        return await ctx.execute_admin_task(task_name, task_fn, slug)

    def _pr_manager_for(cfg: HydraFlowConfig, bus: EventBus) -> PRManager:
        return ctx.pr_manager_for(cfg, bus)

    def _list_repo_records() -> list[RepoRecord]:
        return ctx.list_repo_records()

    def _repo_roots_fn() -> tuple[str, ...]:
        return ctx.repo_roots_fn()

    def _serve_spa_index() -> HTMLResponse:
        return ctx.serve_spa_index()

    def _hitl_summary_retry_due(issue_number: int) -> bool:
        return ctx.hitl_summary_retry_due(issue_number)

    async def _compute_hitl_summary(
        issue_number: int, *, cause: str, origin: str | None
    ) -> str | None:
        return await ctx.compute_hitl_summary(issue_number, cause=cause, origin=origin)

    async def _warm_hitl_summary(
        issue_number: int, *, cause: str, origin: str | None
    ) -> None:
        await ctx.warm_hitl_summary(issue_number, cause=cause, origin=origin)

    def _build_history_links(
        raw: dict[int, dict[str, Any]] | Iterable[Any],
    ) -> list[IssueHistoryLink]:
        """Convert the internal linked_issues accumulator to a sorted list."""
        if isinstance(raw, dict):
            return sorted(
                (
                    IssueHistoryLink(
                        target_id=int(v["target_id"]),
                        kind=v.get("kind", "relates_to"),
                        target_url=v.get("target_url"),
                    )
                    for v in raw.values()
                    if isinstance(v, dict) and _coerce_int(v.get("target_id")) > 0
                ),
                key=lambda lnk: lnk.target_id,
            )
        # Legacy fallback: bare set of ints
        return sorted(
            (IssueHistoryLink(target_id=int(v)) for v in raw if _coerce_int(v) > 0),
            key=lambda lnk: lnk.target_id,
        )

    def _new_issue_history_entry(issue_number: int) -> dict[str, Any]:
        """Create a blank history aggregation row for an issue."""
        repo_slug = (config.repo or "").strip()
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

    def _touch_issue_timestamps(row: dict[str, Any], timestamp: str | None) -> None:
        """Update the first_seen / last_seen bounds of a history row."""
        if not timestamp:
            return
        current_first = row.get("first_seen")
        current_last = row.get("last_seen")
        if not isinstance(current_first, str) or timestamp < current_first:
            row["first_seen"] = timestamp
        if not isinstance(current_last, str) or timestamp > current_last:
            row["last_seen"] = timestamp

    def _build_issue_history_entry(
        row: dict[str, Any],
        outcome: IssueOutcome | None,
    ) -> IssueHistoryEntry:
        """Build an ``IssueHistoryEntry`` from a raw aggregation row."""
        issue_number = int(row["issue_number"])
        title = str(row.get("title", f"Issue #{issue_number}"))
        row_status = str(row.get("status", "unknown")).lower()

        linked_issues = _build_history_links(row.get("linked_issues", {}))
        prs_map = row.get("prs", {})
        if not isinstance(prs_map, dict):
            prs_map = {}
        pr_rows = sorted(
            (
                IssueHistoryPR(
                    number=int(pr_data["number"]),
                    url=str(pr_data.get("url", "")),
                    merged=bool(pr_data.get("merged", False)),
                    title=str(pr_data.get("title", "")),
                )
                for pr_data in prs_map.values()
                if isinstance(pr_data, dict) and _coerce_int(pr_data.get("number")) > 0
            ),
            key=lambda p: p.number,
            reverse=True,
        )

        return IssueHistoryEntry(
            issue_number=issue_number,
            title=title,
            issue_url=str(row.get("issue_url", "")),
            status=_coerce_history_status(row_status),
            epic=str(row.get("epic", "")),
            crate_number=row.get("crate_number"),
            crate_title=str(row.get("crate_title", "")),
            linked_issues=linked_issues,
            prs=pr_rows,
            session_ids=sorted(str(s) for s in row.get("session_ids", set()) if str(s)),
            source_calls=dict(sorted(row.get("source_calls", {}).items())),
            model_calls=dict(sorted(row.get("model_calls", {}).items())),
            inference={k: _coerce_int(v) for k, v in row.get("inference", {}).items()},
            first_seen=row.get("first_seen"),
            last_seen=row.get("last_seen"),
            outcome=outcome,
        )

    def _aggregate_telemetry_record(
        row: dict[str, Any],
        record: dict[str, Any],
        pr_to_issue: dict[int, int],
        *,
        sum_counters: bool = False,
    ) -> None:
        """Extract shared metadata from a telemetry record into *row*.

        When *sum_counters* is True the inference counter keys are also
        accumulated (used in the per-record path).  The rollup path only
        needs metadata so it passes ``sum_counters=False``.
        """
        issue_number = int(row["issue_number"])
        timestamp = record.get("timestamp")
        _touch_issue_timestamps(row, timestamp if isinstance(timestamp, str) else None)

        session_id = str(record.get("session_id", "")).strip()
        if session_id:
            row["session_ids"].add(session_id)

        source = str(record.get("source", "")).strip()
        if source:
            row["source_calls"][source] = row["source_calls"].get(source, 0) + 1

        model = str(record.get("model", "")).strip()
        if model:
            row["model_calls"][model] = row["model_calls"].get(model, 0) + 1

        if sum_counters:
            for key in _INFERENCE_COUNTER_KEYS:
                row["inference"][key] += _coerce_int(record.get(key))

        pr_number = _coerce_int(record.get("pr_number"))
        if pr_number > 0:
            prs: dict[int, dict[str, Any]] = row["prs"]
            if pr_number not in prs:
                prs[pr_number] = {
                    "number": pr_number,
                    "url": "",
                    "merged": False,
                }
            pr_to_issue.setdefault(pr_number, issue_number)

    def _process_events_into_rows(
        events: list[Any],
        issue_rows: dict[int, dict[str, Any]],
        pr_to_issue: dict[int, int],
        since_dt: datetime | None,
        until_dt: datetime | None,
    ) -> None:
        """Process event-bus events into *issue_rows* in place."""
        for event in events:
            timestamp = event.timestamp
            if not _is_timestamp_in_range(timestamp, since_dt, until_dt):
                continue

            issue_number = _event_issue_number(event.data)
            if issue_number is None and event.type == EventType.MERGE_UPDATE:
                pr_num = _coerce_int(event.data.get("pr"))
                issue_number = pr_to_issue.get(pr_num)

            if issue_number is None or issue_number <= 0:
                continue

            row = issue_rows.setdefault(
                issue_number, _new_issue_history_entry(issue_number)
            )
            _touch_issue_timestamps(row, timestamp)

            maybe_title = str(event.data.get("title", "")).strip()
            if maybe_title:
                row["title"] = maybe_title

            maybe_url = str(event.data.get("url", "")).strip()
            if maybe_url.startswith(("http://", "https://")):
                row["issue_url"] = maybe_url

            if event.type == EventType.ISSUE_CREATED:
                labels = event.data.get("labels", [])
                if isinstance(labels, list) and not row.get("epic"):
                    for lbl in labels:
                        s = str(lbl).strip()
                        if (
                            s
                            and "epic" in s.lower()
                            and s.lower() not in _EPIC_INTERNAL_LABELS
                        ):
                            row["epic"] = s
                            break
                milestone_num = _coerce_int(event.data.get("milestone_number"))
                if milestone_num > 0 and not row.get("crate_number"):
                    row["crate_number"] = milestone_num

            if event.type == EventType.PR_CREATED:
                pr_number = _coerce_int(event.data.get("pr"))
                if pr_number > 0:
                    pr_to_issue[pr_number] = issue_number
                    prs = row["prs"]
                    payload = prs.get(
                        pr_number,
                        {"number": pr_number, "url": "", "merged": False},
                    )
                    url = str(event.data.get("url", "")).strip()
                    if url.startswith(("http://", "https://")):
                        payload["url"] = url
                    pr_title = str(event.data.get("title", "")).strip()
                    if pr_title:
                        payload["title"] = pr_title
                    prs[pr_number] = payload

            if event.type == EventType.MERGE_UPDATE:
                pr_number = _coerce_int(event.data.get("pr"))
                if pr_number > 0:
                    prs = row["prs"]
                    payload = prs.get(
                        pr_number,
                        {"number": pr_number, "url": "", "merged": False},
                    )
                    if str(event.data.get("status", "")).lower() == "merged":
                        payload["merged"] = True
                    merge_title = str(event.data.get("title", "")).strip()
                    if merge_title:
                        payload["title"] = merge_title
                    prs[pr_number] = payload

            normalised = _normalise_event_status(event.type, event.data)
            if normalised:
                current = str(row.get("status", "unknown"))
                current_ts = (
                    row.get("status_updated_at")
                    if isinstance(row.get("status_updated_at"), str)
                    else None
                )
                if _status_sort_key(normalised, timestamp) >= _status_sort_key(
                    current, current_ts
                ):
                    row["status"] = normalised
                    row["status_updated_at"] = timestamp

    def _filter_rows_to_items(
        issue_rows: dict[int, dict[str, Any]],
        requested_status: str,
        query_text: str,
    ) -> list[IssueHistoryEntry]:
        """Filter *issue_rows* and convert to ``IssueHistoryEntry`` objects."""
        items: list[IssueHistoryEntry] = []
        for row in issue_rows.values():
            row_status = str(row.get("status", "unknown")).lower()
            if requested_status and row_status != requested_status:
                continue

            issue_number = int(row["issue_number"])
            title = str(row.get("title", f"Issue #{issue_number}"))
            if (
                query_text
                and query_text not in title.lower()
                and query_text not in str(issue_number)
            ):
                continue

            items.append(
                _build_issue_history_entry(row, state.get_outcome(issue_number))
            )
        return items

    async def _apply_enrichment_and_crate_titles(
        items: list[IssueHistoryEntry],
        issue_rows: dict[int, dict[str, Any]],
        requested_status: str,
        query_text: str,
        use_unfiltered: bool,
    ) -> list[IssueHistoryEntry]:
        """Enrich items via GitHub and backfill crate titles from milestones.

        Returns a (potentially rebuilt) items list.
        """
        already_enriched: set[int] = _history_cache.get("enriched_issues", set())
        issue_lookup = {
            item.issue_number: issue_rows[item.issue_number] for item in items
        }
        enrich_candidates = [
            item.issue_number
            for item in items
            if item.issue_number not in already_enriched
            and (
                not item.issue_url
                or item.title.startswith("Issue #")
                or (not item.epic and not item.linked_issues)
            )
        ][:40]
        if enrich_candidates:
            await _enrich_issue_history_with_github(
                {k: issue_lookup[k] for k in enrich_candidates}
            )
            already_enriched.update(enrich_candidates)
            _history_cache["enriched_issues"] = already_enriched
            if use_unfiltered and _history_cache["issue_rows"] is not None:
                _history_cache["issue_rows"] = copy.deepcopy(issue_rows)
                _save_history_cache()
            # Rebuild items from enriched rows.
            items = _filter_rows_to_items(issue_rows, requested_status, query_text)

        # Sort before crate-title backfill so milestone fetches are done
        # after ordering.  The caller applies the page limit after returning.
        items.sort(
            key=lambda item: (
                item.last_seen or "",
                item.inference.get("total_tokens", 0),
                item.issue_number,
            ),
            reverse=True,
        )

        # Populate crate titles from milestones for items that have a
        # crate_number but no title yet.
        needs_title = any(i.crate_number and not i.crate_title for i in items)
        if needs_title:
            try:
                milestones = await pr_manager.list_milestones(state="all")
                title_map = {m.number: m.title for m in milestones}
                items = [
                    i.model_copy(
                        update={"crate_title": title_map.get(i.crate_number, "")}
                    )
                    if i.crate_number and not i.crate_title
                    else i
                    for i in items
                ]
                # Also backfill into the raw rows so the cache carries titles.
                backfilled = False
                for i in items:
                    if i.crate_number and i.crate_title:
                        raw = issue_rows.get(i.issue_number)
                        if raw is not None and raw.get("crate_title") != i.crate_title:
                            raw["crate_title"] = i.crate_title
                            backfilled = True
                if (
                    backfilled
                    and use_unfiltered
                    and _history_cache.get("issue_rows") is not None
                ):
                    _history_cache["issue_rows"] = copy.deepcopy(issue_rows)
                    _save_history_cache()
            except Exception:
                logger.warning(
                    "Failed to fetch milestones for crate titles", exc_info=True
                )

        # Backfill epic field from state's epic tracking when not already set.
        epic_states = state.get_all_epic_states()
        if epic_states:
            child_to_epic: dict[int, str] = {}
            for es in epic_states.values():
                title = es.title or f"Epic #{es.epic_number}"
                for child in es.child_issues:
                    child_to_epic[child] = title
            if child_to_epic:
                items = [
                    i.model_copy(update={"epic": child_to_epic[i.issue_number]})
                    if not i.epic and i.issue_number in child_to_epic
                    else i
                    for i in items
                ]

        # Derive outcome for issues that completed the pipeline (have a
        # merged PR) but were never given an explicit record_outcome() call.
        items = [
            i.model_copy(
                update={
                    "outcome": IssueOutcome(
                        outcome=IssueOutcomeType.MERGED,
                        reason="Derived from merged PR",
                        closed_at=i.last_seen or "",
                        pr_number=next((p.number for p in i.prs if p.merged), None),
                        phase="review",
                    )
                }
            )
            if not i.outcome and any(p.merged for p in i.prs)
            else i
            for i in items
        ]

        return items

    async def _enrich_issue_history_with_github(
        entries: dict[int, dict[str, Any]], limit: int = 150
    ) -> None:
        """Concurrently fetch GitHub metadata and apply it to history entries."""
        if not entries:
            return

        fetcher = IssueFetcher(config, credentials=_creds)
        issue_numbers = sorted(entries.keys(), reverse=True)[:limit]
        sem = asyncio.Semaphore(6)

        async def _fetch_and_apply(issue_number: int) -> None:
            """Fetch one issue under the semaphore and apply fields to its entry."""
            async with sem:
                issue = await fetcher.fetch_issue_by_number(issue_number)
            if issue is None:
                return
            row = entries.get(issue_number)
            if row is None:
                return
            row["title"] = issue.title or row.get("title") or f"Issue #{issue_number}"
            row["issue_url"] = issue.url or row.get("issue_url", "")
            labels = [str(lbl).strip() for lbl in issue.labels if str(lbl).strip()]
            if not row.get("epic"):
                # Skip internal pipeline labels (e.g. hydraflow-epic-child);
                # only keep labels that look like actual epic names.
                epic = next(
                    (
                        lbl
                        for lbl in labels
                        if "epic" in lbl.lower()
                        and lbl.lower() not in _EPIC_INTERNAL_LABELS
                    ),
                    "",
                )
                row["epic"] = epic
            ms_num = _coerce_int(getattr(issue, "milestone_number", None))
            if ms_num > 0 and not row.get("crate_number"):
                row["crate_number"] = ms_num
            for link in parse_task_links(issue.body or ""):
                try:
                    tid = int(link.target_id)
                except (ValueError, TypeError):
                    continue
                row["linked_issues"][tid] = {
                    "target_id": tid,
                    "kind": str(link.kind),
                    "target_url": link.target_url or None,
                }

        results = await asyncio.gather(
            *(_fetch_and_apply(num) for num in issue_numbers),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, Exception):
                logger.warning("Issue enrichment fetch failed: %s", result)

    @router.get("/healthz")
    def get_health() -> JSONResponse:
        """Lightweight readiness response for load balancers and monitors."""
        orchestrator = get_orchestrator()
        orchestrator_running = bool(getattr(orchestrator, "running", False))
        worker_states = state.get_bg_worker_states()
        session_counters = state.get_session_counters()
        session_started_at: str | None = session_counters.session_start or None
        uptime_seconds: int | None = None
        if session_started_at:
            try:
                started_dt = datetime.fromisoformat(session_started_at)
            except (ValueError, TypeError):
                session_started_at = None
            else:
                uptime_seconds = max(
                    int((datetime.now(UTC) - started_dt).total_seconds()),
                    0,
                )

        def _normalise_worker_health(
            raw_status: str | BGWorkerHealth | None,
        ) -> BGWorkerHealth:
            """Coerce a raw status value to a BGWorkerHealth enum member."""
            if isinstance(raw_status, BGWorkerHealth):
                return raw_status
            try:
                return BGWorkerHealth(str(raw_status or "").lower())
            except ValueError:
                return BGWorkerHealth.DISABLED

        worker_count = len(worker_states)
        worker_errors = sorted(
            name
            for name, heartbeat in worker_states.items()
            if _normalise_worker_health(heartbeat.get("status")) == BGWorkerHealth.ERROR
        )
        if orchestrator is None:
            orchestrator_running = False
        orchestrator_status = "missing"
        if orchestrator is not None and orchestrator_running:
            orchestrator_status = "running"
        elif orchestrator is not None:
            orchestrator_status = "idle"

        worker_status = "disabled"
        if worker_count > 0:
            worker_status = "degraded" if worker_errors else "ok"

        status = "ok"
        if orchestrator_status == "missing":
            status = "starting"
        elif orchestrator_status == "idle":
            status = "idle"
        if worker_status == "degraded":
            status = "degraded"

        def _is_loopback_host(host: str) -> bool:
            """Return True if the host resolves to localhost or 127.x.x.x."""
            host_lower = (host or "").lower()
            return host_lower == "localhost" or host_lower.startswith("127.")

        dashboard_binding = {
            "host": config.dashboard_host,
            "port": config.dashboard_port,
        }
        dashboard_public = not _is_loopback_host(config.dashboard_host)

        # GitHub cache health (if available)
        github_cache_health: dict[str, object] = {"status": "unknown"}
        if orchestrator is not None and isinstance(
            getattr(orchestrator, "github_cache", None), GitHubDataCache
        ):
            gh_cache: GitHubDataCache = orchestrator.github_cache
            cache_ages = {
                ds: round(gh_cache.get_cache_age(ds), 1)
                for ds in ("open_prs", "hitl_items", "label_counts")
            }
            max_age = max(cache_ages.values()) if cache_ages else 0
            github_cache_health = {
                "status": "stale" if max_age > config.data_poll_interval * 3 else "ok",
                "age_seconds": cache_ages,
            }

        # Queue depths
        queue_depths: dict[str, int] = {}
        if orchestrator is not None:
            issue_store = getattr(orchestrator, "issue_store", None)
            if issue_store is not None and hasattr(issue_store, "get_queue_stats"):
                qstats = issue_store.get_queue_stats()
                queue_depths = dict(qstats.queue_depth)

        checks = {
            "orchestrator": {
                "status": orchestrator_status,
                "running": orchestrator_running,
                "session_started_at": session_started_at,
            },
            "workers": {
                "status": worker_status,
                "count": worker_count,
                "errors": worker_errors,
            },
            "dashboard": {
                "status": "ok" if config.dashboard_enabled else "disabled",
                "host": config.dashboard_host,
                "port": config.dashboard_port,
                "public": dashboard_public,
            },
            "hindsight": {
                "status": "ok" if _creds.hindsight_url else "disabled",
                "configured": bool(_creds.hindsight_url),
            },
            "github_cache": github_cache_health,
            "queue_depths": queue_depths,
        }
        ready = checks["orchestrator"]["status"] == "running" and checks["workers"][
            "status"
        ] in {"ok", "disabled"}
        payload = {
            "status": status,
            "version": get_app_version(),
            "timestamp": datetime.now(UTC).isoformat(),
            "orchestrator_running": orchestrator_running,
            "active_issue_count": len(state.get_active_issue_numbers()),
            "active_workspaces": len(state.get_active_workspaces()),
            "worker_count": worker_count,
            "worker_errors": worker_errors,
            "dashboard": dashboard_binding,
            "session_started_at": session_started_at,
            "uptime_seconds": uptime_seconds,
            "ready": ready,
            "checks": checks,
        }
        return JSONResponse(payload)

    @router.get("/api/hindsight/health")
    async def hindsight_health() -> JSONResponse:
        """Check Hindsight server connectivity."""
        if ctx.hindsight_client is None:
            return JSONResponse(
                {"status": "disabled", "reachable": False, "url": ""},
            )
        try:
            reachable = await ctx.hindsight_client.health_check()
        except Exception:  # noqa: BLE001
            reachable = False
        return JSONResponse(
            {
                "status": "ok" if reachable else "unreachable",
                "reachable": reachable,
                "url": _creds.hindsight_url,
            },
        )

    @router.post("/api/hindsight/audit")
    async def hindsight_audit() -> JSONResponse:
        """Run a memory quality audit across all Hindsight banks."""
        if ctx.hindsight_client is None:
            return JSONResponse({"status": "disabled", "results": []})
        from memory_audit import MemoryAuditor  # noqa: PLC0415

        auditor = MemoryAuditor(ctx.hindsight_client, config)
        results = await auditor.audit_all()
        return JSONResponse({"status": "ok", "results": results})

    @router.get("/api/hindsight/banks")
    async def hindsight_banks() -> JSONResponse:
        """List Hindsight memory banks with stats."""
        if not _creds.hindsight_url:
            return JSONResponse({"status": "disabled", "banks": []})
        from hindsight import Bank  # noqa: PLC0415

        banks = [{"id": str(b), "name": b.name} for b in Bank]
        return JSONResponse({"status": "ok", "banks": banks})

    @router.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        """Serve the single-page application root."""
        return _serve_spa_index()

    @router.get("/api/state")
    async def get_state(
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Return the full state tracker snapshot as JSON."""
        _cfg, _state, _bus, _get_orch = _resolve_runtime(repo)
        return JSONResponse(_state.to_dict())

    @router.get("/api/stats")
    async def get_stats(
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Return lifetime stats and optional queue depths."""
        _cfg, _state, _bus, _get_orch = _resolve_runtime(repo)
        data: dict[str, Any] = _state.get_lifetime_stats().model_dump()
        orch = _get_orch()
        if orch:
            data["queue"] = orch.issue_store.get_queue_stats().model_dump()
        return JSONResponse(data)

    @router.get("/api/queue")
    async def get_queue(
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Return current queue depths, active counts, and throughput."""
        if not _is_pipeline_active(repo):
            return JSONResponse(QueueStats().model_dump())
        _cfg, _state, _bus, _get_orch = _resolve_runtime(repo)
        orch = _get_orch()
        if orch:
            return JSONResponse(orch.issue_store.get_queue_stats().model_dump())
        return JSONResponse(QueueStats().model_dump())

    @router.post("/api/request-changes")
    async def request_changes(body: dict[str, Any]) -> JSONResponse:
        """Escalate an issue to HITL with user feedback."""
        issue_number: int | None = body.get("issue_number")
        feedback = (body.get("feedback") or "").strip()
        stage: str = body.get("stage") or ""

        if not isinstance(issue_number, int) or issue_number < 1 or not feedback:
            return JSONResponse(
                {
                    "status": "error",
                    "detail": "issue_number and feedback are required",
                },
                status_code=400,
            )

        label_field = _FRONTEND_STAGE_TO_LABEL_FIELD.get(stage)
        if not label_field:
            return JSONResponse(
                {"status": "error", "detail": f"Unknown stage: {stage}"},
                status_code=400,
            )

        stage_labels: list[str] = getattr(config, label_field, [])
        origin_label: str = stage_labels[0]

        await pr_manager.swap_pipeline_labels(issue_number, config.hitl_label[0])

        state.set_hitl_cause(issue_number, feedback)
        state.set_hitl_origin(issue_number, origin_label)

        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.HITL_ESCALATION,
                data=HITLEscalationPayload(
                    issue=issue_number,
                    cause=feedback,
                    origin=origin_label,
                ),
            )
        )

        return JSONResponse({"status": "ok"})

    @router.get("/api/pipeline")
    async def get_pipeline(
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Return current pipeline snapshot with issues per stage."""
        if not _is_pipeline_active(repo):
            return JSONResponse(PipelineSnapshot().model_dump())
        _cfg, _state, _bus, _get_orch = _resolve_runtime(repo)
        orch = _get_orch()
        if orch:
            raw = orch.issue_store.get_pipeline_snapshot()
            mapped: dict[str, list[PipelineSnapshotEntry]] = {}
            for backend_stage, issues in raw.items():
                frontend_stage = _STAGE_NAME_MAP.get(backend_stage, backend_stage)
                mapped[frontend_stage] = issues
            snapshot = PipelineSnapshot(
                stages={
                    k: [PipelineIssue.model_validate(i) for i in v]
                    for k, v in mapped.items()
                }
            )
            return JSONResponse(snapshot.model_dump())
        return JSONResponse(PipelineSnapshot().model_dump())

    @router.get("/api/pipeline/stats")
    async def get_pipeline_stats(
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Return lightweight pipeline stats (counts only, no issue details)."""
        if not _is_pipeline_active(repo):
            return JSONResponse({})
        _cfg, _state, _bus, _get_orch = _resolve_runtime(repo)
        orch = _get_orch()
        if orch:
            stats = orch.build_pipeline_stats()
            return JSONResponse(stats.model_dump())
        return JSONResponse({})

    @router.get("/api/events")
    async def get_events(since: str | None = None) -> JSONResponse:
        """Return event history, optionally filtered by a since timestamp."""
        if since is not None:
            try:
                since_dt = datetime.fromisoformat(since)
                if since_dt.tzinfo is None:
                    since_dt = since_dt.replace(tzinfo=UTC)
                events = await event_bus.load_events_since(since_dt)
                if events is not None:
                    return JSONResponse([e.model_dump() for e in events])
            except (ValueError, TypeError):
                pass  # Fall through to in-memory history
        history = event_bus.get_history()
        return JSONResponse([e.model_dump() for e in history])

    @router.get("/api/prs")
    async def get_prs(
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Fetch all open HydraFlow PRs from GitHub."""
        _cfg, _state, _bus, _get_orch = _resolve_runtime(repo)
        # Use cached data when orchestrator has a github cache
        orch = _get_orch()
        if orch and isinstance(getattr(orch, "github_cache", None), GitHubDataCache):
            items = orch.github_cache.get_open_prs()
        else:
            manager = _pr_manager_for(_cfg, _bus)
            all_labels = list(
                {
                    *_cfg.ready_label,
                    *_cfg.review_label,
                    *_cfg.fixed_label,
                    *_cfg.hitl_label,
                    *_cfg.hitl_active_label,
                    *_cfg.planner_label,
                }
            )
            items = await manager.list_open_prs(all_labels)
        # Overlay merged flag from IssueStore so the frontend has
        # authoritative merged state instead of session-volatile flags.
        if not orch:
            orch = _get_orch()
        if orch:
            merged_numbers = orch.issue_store.get_merged_numbers()
            for item in items:
                issue_num = (
                    item.get("issue")
                    if isinstance(item, dict)
                    else getattr(item, "issue", None)
                )
                if issue_num in merged_numbers:
                    if isinstance(item, dict):
                        item["merged"] = True
                    else:
                        item.merged = True
        return JSONResponse(
            [item if isinstance(item, dict) else item.model_dump() for item in items]
        )

    # --- Epic routes (extracted to _epic_routes.py) ---
    from dashboard_routes._epic_routes import register as _register_epics

    _register_epics(router, ctx)

    # --- Crate routes (extracted to _crates_routes.py) ---
    from dashboard_routes._crates_routes import register as _register_crates

    _register_crates(router, ctx)

    # --- HITL routes (extracted to _hitl_routes.py) ---
    from dashboard_routes._hitl_routes import register as _register_hitl

    _register_hitl(router, ctx)

    # --- Control routes (extracted to _control_routes.py) ---
    from dashboard_routes._control_routes import register as _register_control

    _register_control(router, ctx)

    # --- Metrics routes (extracted to _metrics_routes.py) ---
    from dashboard_routes._metrics_routes import register as _register_metrics

    _register_metrics(router, ctx)

    # --- Diagnostics routes (factory metrics + trace artifacts) ---
    from dashboard_routes._diagnostics_routes import build_diagnostics_router

    router.include_router(build_diagnostics_router(config))

    # --- Factory health routes (longitudinal retrospective analysis) ---
    from dashboard_routes._factory_health_routes import build_factory_health_router

    router.include_router(build_factory_health_router(config))

    # --- Issue history cache ---
    # Cache the aggregated issue_rows + pr_to_issue for the unfiltered case.
    # Persisted to disk so the first request after restart is fast.
    # Invalidated when the event count or telemetry file changes.
    _history_cache_file = config.data_path("metrics", "history_cache.json")
    _HISTORY_CACHE_TTL = 30  # seconds

    _history_cache: dict[str, Any] = {
        "event_count": -1,
        "telemetry_mtime": 0.0,
        "issue_rows": None,
        "pr_to_issue": None,
        "enriched_issues": set(),
    }
    _history_cache_ts: list[float] = [0.0]

    def _save_history_cache() -> None:
        """Persist in-memory history cache to disk."""
        rows = _history_cache.get("issue_rows")
        if rows is None:
            return
        serialisable_rows: dict[str, Any] = {}
        for k, v in rows.items():
            entry = dict(v)
            # Convert sets to lists for JSON serialisation.
            entry["session_ids"] = sorted(entry.get("session_ids") or [])
            serialisable_rows[str(k)] = entry
        payload = {
            "event_count": _history_cache.get("event_count", -1),
            "telemetry_mtime": _history_cache.get("telemetry_mtime", 0.0),
            "issue_rows": serialisable_rows,
            "pr_to_issue": {
                str(k): v for k, v in (_history_cache.get("pr_to_issue") or {}).items()
            },
            "enriched_issues": sorted(_history_cache.get("enriched_issues") or []),
        }
        try:
            _history_cache_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = _history_cache_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload))
            tmp.replace(_history_cache_file)
        except OSError:
            logger.debug("Could not persist history cache", exc_info=True)

    def _load_history_cache() -> None:
        """Load persisted history cache from disk into memory."""
        if not _history_cache_file.is_file():
            return
        try:
            raw = json.loads(_history_cache_file.read_text())
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
            # Restore session_ids to a set.
            entry["session_ids"] = set(entry.get("session_ids") or [])
            # JSON keys are always strings — restore int keys for sub-dicts
            # so enrichment lookups (which use int keys) don't create dupes.
            if isinstance(entry.get("prs"), dict):
                entry["prs"] = {int(pk): pv for pk, pv in entry["prs"].items()}
            if isinstance(entry.get("linked_issues"), dict):
                entry["linked_issues"] = {
                    int(lk): lv for lk, lv in entry["linked_issues"].items()
                }
            rows[int(k)] = entry
        _history_cache["issue_rows"] = rows
        _history_cache["pr_to_issue"] = {
            int(k): int(v) for k, v in raw.get("pr_to_issue", {}).items()
        }
        _history_cache["event_count"] = raw.get("event_count", -1)
        _history_cache["telemetry_mtime"] = raw.get("telemetry_mtime", 0.0)
        _history_cache["enriched_issues"] = set(raw.get("enriched_issues") or [])
        # Set timestamp so TTL check works (treat as "just loaded").
        _history_cache_ts[0] = time.monotonic()

    # Warm the in-memory cache from disk on startup.
    try:
        _load_history_cache()
    except Exception:
        logger.warning("History cache warm-up failed", exc_info=True)

    @router.get("/api/issues/history")
    async def get_issue_history(
        since: str | None = None,
        until: str | None = None,
        status: str | None = None,
        query: str | None = None,
        limit: int = 300,
    ) -> JSONResponse:
        """Return issue lifecycle history with inference rollups."""
        since_dt = _parse_iso_or_none(since)
        until_dt = _parse_iso_or_none(until)
        requested_status = (status or "").strip().lower()
        query_text = (query or "").strip().lower()
        clamped_limit = max(1, min(limit, 1000))

        telemetry = PromptTelemetry(config)
        all_events = event_bus.get_history()

        # Check if we can reuse cached aggregation for the unfiltered case.
        use_unfiltered = since_dt is None and until_dt is None
        event_count = len(all_events)
        telem_mtime = telemetry.get_mtime()
        now = time.monotonic()
        cache_hit = (
            use_unfiltered
            and _history_cache["issue_rows"] is not None
            and _history_cache["event_count"] == event_count
            and _history_cache["telemetry_mtime"] == telem_mtime
            and (now - _history_cache_ts[0]) < _HISTORY_CACHE_TTL
        )

        if cache_hit:
            issue_rows: dict[int, dict[str, Any]] = copy.deepcopy(
                _history_cache["issue_rows"]
            )
            pr_to_issue: dict[int, int] = dict(_history_cache["pr_to_issue"])
        else:
            issue_rows = {}
            pr_to_issue = {}

            # Build PR→issue mapping from all in-memory events first so merge
            # events in the selected range still resolve when PR creation
            # happened earlier.
            for event in all_events:
                if event.type != EventType.PR_CREATED:
                    continue
                mapped_issue = _event_issue_number(event.data)
                mapped_pr = _coerce_int(event.data.get("pr"))
                if mapped_issue is not None and mapped_issue > 0 and mapped_pr > 0:
                    pr_to_issue[mapped_pr] = mapped_issue

        use_issue_rollups = (
            since_dt is None
            and until_dt is None
            and not query_text
            and not requested_status
        )
        if cache_hit:
            pass  # aggregation already done
        elif use_issue_rollups:
            for issue_number, counters in telemetry.get_issue_totals().items():
                row = issue_rows.setdefault(
                    issue_number, _new_issue_history_entry(issue_number)
                )
                for key in _INFERENCE_COUNTER_KEYS:
                    row["inference"][key] = _coerce_int(counters.get(key, 0))
            # Keep metadata (sessions/model/source/pr links) from recent rows
            # without re-summing counters that already came from rollups.
            for record in telemetry.load_inferences(limit=5000):
                issue_number = _coerce_int(record.get("issue_number"))
                if issue_number <= 0:
                    continue
                row = issue_rows.get(issue_number)
                if row is None:
                    continue
                _aggregate_telemetry_record(
                    row, record, pr_to_issue, sum_counters=False
                )
        else:
            inference_rows = telemetry.load_inferences(limit=50000)
            for record in inference_rows:
                timestamp = record.get("timestamp")
                if not _is_timestamp_in_range(
                    timestamp if isinstance(timestamp, str) else None,
                    since_dt,
                    until_dt,
                ):
                    continue
                issue_number = _coerce_int(record.get("issue_number"))
                if issue_number <= 0:
                    continue
                row = issue_rows.setdefault(
                    issue_number, _new_issue_history_entry(issue_number)
                )
                _aggregate_telemetry_record(row, record, pr_to_issue, sum_counters=True)

        if not cache_hit:
            _process_events_into_rows(
                all_events, issue_rows, pr_to_issue, since_dt, until_dt
            )

            # Store in cache if this was an unfiltered aggregation.
            if use_unfiltered:
                _history_cache["issue_rows"] = copy.deepcopy(issue_rows)
                _history_cache["pr_to_issue"] = dict(pr_to_issue)
                _history_cache["event_count"] = event_count
                _history_cache["telemetry_mtime"] = telem_mtime
                _history_cache_ts[0] = now
                _save_history_cache()

        items = _filter_rows_to_items(issue_rows, requested_status, query_text)

        # Enrich via GitHub, backfill crate titles, sort.
        items = await _apply_enrichment_and_crate_titles(
            items, issue_rows, requested_status, query_text, use_unfiltered
        )
        items = items[:clamped_limit]

        totals = {
            "issues": len(items),
            "inference_calls": sum(
                i.inference.get("inference_calls", 0) for i in items
            ),
            "total_tokens": sum(i.inference.get("total_tokens", 0) for i in items),
        }

        return JSONResponse(
            IssueHistoryResponse(
                items=items,
                totals=totals,
                since=since_dt.isoformat() if since_dt else None,
                until=until_dt.isoformat() if until_dt else None,
            ).model_dump()
        )

    @router.get("/api/memories")
    async def get_memories() -> JSONResponse:
        """Return memory items from local JSONL event log."""
        import json as _json  # noqa: PLC0415

        items_jsonl = config.data_path("memory", "items.jsonl")

        items: list[dict[str, object]] = []
        if items_jsonl.exists():
            with contextlib.suppress(OSError):
                for line in items_jsonl.read_text().splitlines():
                    with contextlib.suppress(_json.JSONDecodeError):
                        items.append(_json.loads(line))

        return JSONResponse(
            {
                "total_items": len(items),
                "items": items[-50:],
            }
        )

    @router.get("/api/troubleshooting")
    async def get_troubleshooting() -> JSONResponse:
        """Return learned troubleshooting patterns."""
        from troubleshooting_store import TroubleshootingPatternStore

        memory_dir = config.data_path("memory")
        store = TroubleshootingPatternStore(memory_dir)
        all_patterns = store.load_patterns(limit=None)
        total = len(all_patterns)
        capped = all_patterns[:100]

        return JSONResponse(
            {
                "total_patterns": total,
                "patterns": [p.model_dump() for p in capped],
            }
        )

    @router.get("/api/timeline")
    async def get_timeline() -> JSONResponse:
        """Return timelines for all tracked issues."""
        builder = TimelineBuilder(event_bus)
        timelines = builder.build_all()
        return JSONResponse([t.model_dump() for t in timelines])

    @router.get("/api/timeline/issue/{issue_number}")
    async def get_timeline_issue(issue_number: int) -> JSONResponse:
        """Return the event timeline for a single issue."""
        builder = TimelineBuilder(event_bus)
        timeline = builder.build_for_issue(issue_number)
        if timeline is None:
            return JSONResponse({"error": "Issue not found"}, status_code=404)
        return JSONResponse(timeline.model_dump())

    @router.get("/api/timeline/completed")
    async def get_completed_timelines() -> JSONResponse:
        """Return persisted timelines for completed (merged) issues.

        Unlike /api/timeline which derives from ephemeral events,
        these survive event log rotation.
        """
        timelines = state.get_all_completed_timelines()
        return JSONResponse([t.model_dump() for t in timelines.values()])

    # --- State/runtimes/repos/filesystem routes (extracted to _state_routes.py) ---
    from dashboard_routes._state_routes import register as _register_state

    _register_state(router, ctx)

    @router.post("/api/intent")
    async def submit_intent(request: IntentRequest) -> JSONResponse:
        """Create a GitHub issue from a user intent typed in the dashboard."""
        title = request.text[:120]
        body = request.text
        labels = list(config.planner_label)

        issue_number = await pr_manager.create_issue(
            title=title, body=body, labels=labels
        )

        if issue_number == 0:
            return JSONResponse({"error": "Failed to create issue"}, status_code=500)

        url = f"https://github.com/{config.repo}/issues/{issue_number}"
        response = IntentResponse(issue_number=issue_number, title=title, url=url)
        return JSONResponse(response.model_dump())

    # --- Reports routes (extracted to _reports_routes.py) ---
    from dashboard_routes._reports_routes import register as _register_reports

    _register_reports(router, ctx)

    @router.get("/api/sessions")
    async def get_sessions(
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Return session logs for the selected repo."""
        _cfg, _state, _bus, _get_orch = _resolve_runtime(repo)
        sessions = _state.load_sessions()
        repo_filter = (repo or "").strip()
        if repo_filter and registry is None:
            normalized = repo_filter.lower()
            sessions = [
                session
                for session in sessions
                if (session.repo or "").lower() == normalized
            ]
        return JSONResponse([s.model_dump() for s in sessions])

    @router.get("/api/sessions/{session_id}")
    async def get_session_detail(
        session_id: str,
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Return a single session by ID with associated events."""
        _cfg, _state, _bus, _get_orch = _resolve_runtime(repo)
        session = _state.get_session(session_id)
        if session is None:
            return JSONResponse({"error": "Session not found"}, status_code=404)
        # Include events tagged with this session_id
        all_events = _bus.get_history()
        session_events = [
            e.model_dump() for e in all_events if e.session_id == session_id
        ]
        data = session.model_dump()
        data["events"] = session_events
        return JSONResponse(data)

    @router.delete("/api/sessions/{session_id}")
    async def delete_session(
        session_id: str,
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Delete a session by ID. Returns 400 if active, 404 if not found."""
        _cfg, _state, _bus, _get_orch = _resolve_runtime(repo)
        try:
            deleted = _state.delete_session(session_id)
        except ValueError as exc:
            logger.warning("Failed to delete session %s: %s", session_id, exc)
            return JSONResponse(
                {"error": "Cannot delete active session"}, status_code=400
            )
        if not deleted:
            return JSONResponse({"error": "Session not found"}, status_code=404)
        return JSONResponse({"status": "ok"})

    @router.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        """Stream event history then live events over a WebSocket connection."""
        repo_slug: str | None = ws.query_params.get("repo")

        # Resolve the correct event bus for the requested repo.
        try:
            _cfg, _state, bus, _get_orch = _resolve_runtime(repo_slug)
        except (ValueError, HTTPException):
            await ws.accept()
            await ws.close(code=1008, reason=f"Unknown repo: {repo_slug}")
            return

        await ws.accept()

        # Snapshot history BEFORE subscribing to avoid duplicates.
        # Events published between snapshot and subscribe are picked
        # up by the live queue, never sent twice.
        history = bus.get_history()

        async with bus.subscription() as queue:
            # Send history on connect
            for event in history:
                try:
                    await ws.send_text(event.model_dump_json())
                except Exception as exc:
                    if _is_likely_disconnect(exc):
                        logger.warning(
                            "WebSocket disconnect during history replay: %s",
                            exc.__class__.__name__,
                        )
                    else:
                        logger.error(
                            "WebSocket error during history replay: %s",
                            exc.__class__.__name__,
                            exc_info=True,
                        )
                    return

            # Stream live events
            try:
                while True:
                    event: HydraFlowEvent = await queue.get()
                    await ws.send_text(event.model_dump_json())
            except WebSocketDisconnect:
                pass
            except Exception as exc:
                if _is_likely_disconnect(exc):
                    logger.warning(
                        "WebSocket disconnect during live streaming: %s",
                        exc.__class__.__name__,
                    )
                else:
                    logger.error(
                        "WebSocket error during live streaming: %s",
                        exc.__class__.__name__,
                        exc_info=True,
                    )

    # ---------------------------------------------------------------------------
    # JSONL data endpoints
    # ---------------------------------------------------------------------------

    def _read_jsonl(path: Path) -> list[dict[str, Any]]:
        """Read a JSONL file and return parsed records, skipping malformed lines."""
        if not path.exists():
            return []
        records: list[dict[str, Any]] = []
        try:
            for line in path.read_text(encoding="utf-8").strip().splitlines():
                with contextlib.suppress(json.JSONDecodeError):
                    records.append(json.loads(line))
        except OSError:
            pass
        return records

    @router.get("/api/hitl-recommendations")
    async def get_hitl_recommendations() -> JSONResponse:
        """Return unactioned HITL recommendations filed by the health monitor."""
        path = config.data_path("memory", "hitl_recommendations.jsonl")
        return JSONResponse(_read_jsonl(path))

    @router.get("/api/adr-decisions")
    async def get_adr_decisions() -> JSONResponse:
        """Return ADR decision records from adr_reviewer and memory pre-validation."""
        path = config.data_path("memory", "adr_decisions.jsonl")
        return JSONResponse(_read_jsonl(path))

    @router.get("/api/verification-records")
    async def get_verification_records() -> JSONResponse:
        """Return post-merge verification records requiring human review."""
        path = config.data_path("memory", "verification_records.jsonl")
        return JSONResponse(_read_jsonl(path))

    # SPA catch-all: serve index.html for any path not matched above.
    # This must be registered LAST so it doesn't shadow API/WS routes.
    @router.get("/{path:path}", response_model=None)
    async def spa_catchall(path: str) -> Response:
        """Catch-all route: serve static assets or fall back to the SPA index."""
        # Don't catch API, WebSocket, or static-asset paths
        if path.startswith(("api/", "ws/", "assets/", "static/")) or path == "ws":
            return JSONResponse({"detail": "Not Found"}, status_code=404)

        # Serve only root-level static files from ui/dist/ (e.g. logos, favicon).
        # Reject nested/relative segments to prevent path traversal.
        path_parts = PurePosixPath(path).parts
        if len(path_parts) == 1 and path_parts[0] not in {"", ".", ".."}:
            static_file = (ui_dist_dir / path_parts[0]).resolve()
            if (
                static_file.is_relative_to(ui_dist_dir.resolve())
                and static_file.is_file()
            ):
                return FileResponse(static_file)

        return _serve_spa_index()

    # ------------------------------------------------------------------
    # Product track — Shape HTML artifacts
    # ------------------------------------------------------------------

    @router.get("/api/shape/artifact/{issue_number}")
    def get_shape_artifact(issue_number: int, slug: str | None = None) -> Response:
        """Serve the Shape phase HTML artifact for an issue.

        Returns the self-contained HTML direction cards for rendering
        in OpenClaw's canvas or the dashboard.
        """
        cfg, _st, _bus, _get_orch = _resolve_runtime(slug)
        path = cfg.data_root / "artifacts" / "shape" / f"issue-{issue_number}.html"
        if not path.is_file():
            return JSONResponse(
                {"error": f"No shape artifact for issue #{issue_number}"},
                status_code=404,
            )
        return HTMLResponse(path.read_text(encoding="utf-8"))

    @router.get("/api/webhooks/whatsapp")
    async def whatsapp_verify(request: Request) -> Response:
        """Handle WhatsApp webhook verification challenge."""
        mode = request.query_params.get("hub.mode")
        token = request.query_params.get("hub.verify_token")
        challenge = request.query_params.get("hub.challenge", "")
        _cfg, _st, _bus, _get_orch = _resolve_runtime(None)
        expected_token = (
            ctx.credentials.whatsapp_verify_token or ctx.credentials.whatsapp_token
        )
        if mode == "subscribe" and token == expected_token:
            return Response(content=challenge, media_type="text/plain")
        return Response(content="Forbidden", status_code=403)

    @router.post("/api/webhooks/whatsapp")
    async def whatsapp_webhook(request: Request) -> JSONResponse:
        """Receive inbound WhatsApp messages and route to shape conversations.

        Validates the request signature using the WhatsApp app secret,
        then parses the payload, extracts the message text and issue number,
        and stores it as a shape response for the next poll cycle.
        """
        from whatsapp_bridge import WhatsAppBridge  # noqa: PLC0415

        # Signature verification: reject unsigned or forged requests
        _cfg, _st, _bus, _get_orch = _resolve_runtime(None)
        if not _cfg.whatsapp_enabled:
            return JSONResponse({"status": "disabled"}, status_code=403)

        request_body = await request.json()
        text, issue_number = WhatsAppBridge.parse_webhook(request_body)
        if not text:
            return JSONResponse({"status": "no_message"})

        # If no issue number found, try to find the most recent active shape
        if issue_number is None:
            for key in list(_st._data.shape_conversations):
                c = _st._data.shape_conversations[key]
                if c.status == "exploring":
                    issue_number = c.issue_number
                    break

        if issue_number is None:
            return JSONResponse({"status": "no_issue_match"}, status_code=400)

        # Store response for shape phase to pick up (avoids race condition)
        _st.set_shape_response(issue_number, text)

        # Post to GitHub for audit trail (best-effort)
        with contextlib.suppress(Exception):
            await pr_manager.post_comment(issue_number, f"*[via WhatsApp]* {text}")

        return JSONResponse({"status": "ok", "issue": issue_number})

    return router
