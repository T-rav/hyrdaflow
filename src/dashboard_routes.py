"""Route handlers for the HydraFlow dashboard API."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import sys
import tempfile
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import (
    APIRouter,
    Body,
    HTTPException,
    Query,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import ValidationError

from admin_tasks import TaskResult, run_clean, run_ensure_labels, run_prep, run_scaffold
from app_version import get_app_version
from config import HydraFlowConfig, save_config_file
from events import EventBus, EventType, HydraFlowEvent
from issue_store import IssueStoreStage
from metrics_manager import get_metrics_cache_dir
from models import (
    BackgroundWorkersResponse,
    BackgroundWorkerState,
    BackgroundWorkerStatus,
    BGWorkerHealth,
    ControlStatus,
    ControlStatusConfig,
    ControlStatusResponse,
    HITLEscalationPayload,
    IntentRequest,
    IntentResponse,
    MetricsHistoryResponse,
    MetricsResponse,
    MetricsSnapshot,
    OrchestratorStatusPayload,
    PendingReport,
    PipelineIssue,
    PipelineSnapshot,
    PipelineSnapshotEntry,
    QueueStats,
    ReportIssueRequest,
    ReportIssueResponse,
)
from pr_manager import PRManager
from prompt_telemetry import PromptTelemetry
from state import StateTracker
from timeline import TimelineBuilder
from update_check import load_cached_update_result

if TYPE_CHECKING:
    from orchestrator import HydraFlowOrchestrator
from repo_runtime import RepoRuntimeRegistry
from repo_store import RepoRecord, RepoStore

logger = logging.getLogger("hydraflow.dashboard")

_SUPERVISOR_UNAVAILABLE_PREFIXES: tuple[str, ...] = (
    "hydraflow supervisor is not running.",
    "hf supervisor is not running.",
)
_SUPERVISOR_UNAVAILABLE_MESSAGE = (
    "HydraFlow supervisor is not running. "
    "Start HydraFlow inside the target repository with `make run`."
)

RepoSlugParam = Annotated[
    str | None,
    Query(description="Repo slug to scope the request"),
]

# Internal pipeline labels that must not be treated as epic names in the history panel.
_EPIC_INTERNAL_LABELS: frozenset[str] = frozenset(
    {"hydraflow-epic-child", "hydraflow-epic"}
)

# Backend stage keys → frontend stage names
_STAGE_NAME_MAP: dict[str, str] = {
    IssueStoreStage.FIND: "triage",
    IssueStoreStage.PLAN: "plan",
    IssueStoreStage.READY: "implement",
    IssueStoreStage.REVIEW: "review",
    IssueStoreStage.HITL: "hitl",
}

# Frontend stage key → config label field name (for request-changes)
_FRONTEND_STAGE_TO_LABEL_FIELD = {
    "triage": "find_label",
    "plan": "planner_label",
    "implement": "ready_label",
    "review": "review_label",
}


_INFERENCE_COUNTER_KEYS: tuple[str, ...] = (
    "inference_calls",
    "prompt_est_tokens",
    "total_est_tokens",
    "total_tokens",
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "history_chars_saved",
    "context_chars_saved",
    "pruned_chars_total",
    "cache_hits",
    "cache_misses",
)


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


def _normalize_allowed_dir(raw_path: str | None) -> tuple[Path | None, str | None]:
    """Validate and normalize a directory path constrained to allowed roots."""
    candidate = (raw_path or "").strip()
    if not candidate:
        return None, "path required"
    expanded = os.path.expanduser(candidate)
    if "\x00" in expanded:
        return None, "invalid path"
    candidate_abs = os.path.abspath(expanded)
    for root in _allowed_repo_roots():
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


def _parse_iso_or_none(raw: str | None) -> datetime | None:
    """Parse an ISO 8601 string to datetime, returning None on failure."""
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


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


_HISTORY_STATUSES = {
    "unknown",
    "triaged",
    "planned",
    "implemented",
    "in_review",
    "reviewed",
    "hitl",
    "active",
    "failed",
    "merged",
}


def _coerce_history_status(value: str) -> str:
    """Normalize dashboard history statuses and default to ``unknown``."""
    cleaned = str(value).strip().lower()
    if cleaned in _HISTORY_STATUSES:
        return cleaned
    logger.warning("Unknown history status %r; falling back to 'unknown'", value)
    return "unknown"


def _status_rank(status: str) -> int:
    """Return a numeric rank for a history status used for ordering."""
    ranks = {
        "unknown": 0,
        "triaged": 1,
        "planned": 2,
        "implemented": 3,
        "in_review": 4,
        "reviewed": 5,
        "hitl": 6,
        "active": 7,
        "failed": 8,
        "merged": 9,
    }
    return ranks.get(status, 0)


def _coerce_int(value: object) -> int:
    """Coerce a value to int, returning 0 for unconvertible inputs."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _is_timestamp_in_range(
    raw: str | None, since: datetime | None, until: datetime | None
) -> bool:
    """Return True if the ISO timestamp falls within the [since, until] window."""
    if raw is None:
        return since is None and until is None
    parsed = _parse_iso_or_none(raw)
    if parsed is None:
        return since is None and until is None
    if since is not None and parsed < since:
        return False
    return not (until is not None and parsed > until)


def _status_sort_key(status: str, timestamp: str | None) -> tuple[datetime, int]:
    """Build a sort key from a timestamp and status rank for ordering updates."""
    parsed = _parse_iso_or_none(timestamp)
    if parsed is None:
        parsed = datetime.min.replace(tzinfo=UTC)
    return (parsed, _status_rank(status))


def _is_expected_supervisor_unavailable(exc: Exception) -> bool:
    """Return True for the expected local-dev supervisor-down condition."""
    text = str(exc).strip().lower()
    return any(text.startswith(prefix) for prefix in _SUPERVISOR_UNAVAILABLE_PREFIXES)


def _find_repo_match(slug: str, repos: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Find a repo entry matching *slug* using cascading strategies.

    1. Exact slug match (case-sensitive, then case-insensitive)
    2. Strip owner prefix (``owner/repo`` → try ``repo``)
    3. Path-tail match (last component of repo path equals slug)
    4. Path component match (slug matches a ``/``-delimited segment of the path)
    """
    if not slug:
        return None

    # Normalise: strip whitespace and slashes to prevent "/" matching every path
    slug = slug.strip().strip("/")
    if not slug:
        return None

    slug_lower = slug.lower()
    short = slug.rsplit("/", maxsplit=1)[-1] if "/" in slug else None
    short_lower = short.lower() if short else None

    def _slug_match(target: str) -> dict[str, Any] | None:
        """Match *target* against repo slugs (case-sensitive then insensitive)."""
        lower = target.lower()
        for r in repos:
            if r.get("slug") == target:
                return r
        for r in repos:
            repo_slug = r.get("slug")
            if repo_slug and repo_slug.lower() == lower:
                return r
        return None

    # 1. Exact slug match
    result = _slug_match(slug)
    # 2. Strip owner prefix — e.g. "8thlight/insightmesh" → "insightmesh"
    if not result and short:
        result = _slug_match(short)

    # 3. Path-tail match — last path component matches slug or short slug
    if not result:
        candidates = [slug_lower]
        if short_lower:
            candidates.append(short_lower)
        for candidate in candidates:
            for r in repos:
                path = r.get("path") or ""
                if path and Path(path).name.lower() == candidate:
                    result = r
                    break
            if result:
                break

    # 4. Path component match — slug matches a full /-delimited path segment
    if not result:
        for r in repos:
            path = r.get("path") or ""
            if path and slug_lower in path.lower().split("/"):
                result = r
                break

    return result


def _parse_compat_json_object(raw: str | None) -> dict[str, Any] | None:
    """Best-effort parse of legacy query/body JSON object payloads."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


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


def _extract_field_from_sources(
    field_names: tuple[str, str],
    req: dict[str, Any] | None,
    req_query: str | None,
    query_params: tuple[str | None, str | None],
    *,
    query_params_first: bool = False,
) -> str:
    """Extract a value from query params, body dict, and JSON query.

    Args:
        field_names: Pair of field name keys to look up (primary, alias).
        req: Parsed request body dict.
        req_query: Raw ``req`` query parameter (may be JSON).
        query_params: Dedicated query-parameter values (primary, alias).
        query_params_first: When True, check query params before body;
            otherwise check body before query params.
    """
    candidates: list[str] = []

    def _push(value: str | int | float | bool | None) -> None:
        if isinstance(value, str):
            trimmed = value.strip()
            if trimmed:
                candidates.append(trimmed)

    def _push_from_dict(src: dict[str, Any]) -> None:
        for name in field_names:
            _push(src.get(name))
        nested = src.get("req")
        if isinstance(nested, dict):
            for name in field_names:
                _push(nested.get(name))

    def _push_query_params() -> None:
        for qp in query_params:
            _push(qp)

    def _push_body() -> None:
        if isinstance(req, dict):
            _push_from_dict(req)

    # Ordering: query_params_first controls whether dedicated query
    # params are checked before or after the body dict.
    if query_params_first:
        _push_query_params()
        _push_body()
    else:
        _push_body()

    parsed_query = _parse_compat_json_object(req_query)
    if parsed_query:
        _push_from_dict(parsed_query)
    else:
        _push(req_query)

    if not query_params_first:
        _push_query_params()

    return candidates[0] if candidates else ""


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
    registry: RepoRuntimeRegistry | None = None,
    repo_store: RepoStore | None = None,
    register_repo_cb: Callable[
        [Path, str | None], Awaitable[tuple[RepoRecord, HydraFlowConfig]]
    ]
    | None = None,
    remove_repo_cb: Callable[[str], Awaitable[bool]] | None = None,
    list_repos_cb: Callable[[], list[RepoRecord]] | None = None,
    default_repo_slug: str | None = None,
) -> APIRouter:
    """Create an APIRouter with all dashboard route handlers.

    When *registry* is provided, operational endpoints accept an optional
    ``repo`` query parameter to target a specific repo runtime.  When the
    parameter is omitted, the single-repo defaults (closure-captured
    *config*, *state*, *event_bus*, and *get_orchestrator*) are used for
    backward compatibility.
    """
    router = APIRouter()

    # Build shared dependency container for sub-routers.
    from dashboard_crate_routes import create_crate_router
    from dashboard_history import create_history_router
    from dashboard_hitl_routes import create_hitl_router
    from dashboard_router_deps import RouterDeps

    deps = RouterDeps(
        config=config,
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
    )

    # Compose sub-routers for extracted domains.
    router.include_router(create_crate_router(deps))
    router.include_router(create_hitl_router(deps))
    router.include_router(create_history_router(deps))

    def _resolve_runtime(
        slug: str | None,
    ) -> tuple[
        HydraFlowConfig,
        StateTracker,
        EventBus,
        Callable[[], HydraFlowOrchestrator | None],
    ]:
        """Resolve per-repo dependencies from the registry."""
        return deps.resolve_runtime(slug)

    async def _execute_admin_task(
        task_name: str,
        task_fn: Callable[[HydraFlowConfig], Awaitable[TaskResult]],
        slug: str | None,
    ) -> JSONResponse:
        try:
            runtime_config, _, _, _ = _resolve_runtime(slug)
        except HTTPException:
            return JSONResponse({"error": "Unknown repo"}, status_code=404)
        try:
            result = await task_fn(runtime_config)
        except Exception:  # noqa: BLE001
            logger.exception("%s task failed", task_name)
            return JSONResponse({"error": f"{task_name} failed"}, status_code=500)
        payload = {"status": "ok", "result": result.as_dict()}
        status_code = 200
        if not result.success:
            payload["status"] = "error"
            status_code = 500
        return JSONResponse(payload, status_code=status_code)

    def _pr_manager_for(cfg: HydraFlowConfig, bus: EventBus) -> PRManager:
        """Return the shared PRManager when config matches; otherwise create a new one."""
        return deps.pr_manager_for(cfg, bus)

    def _list_repo_records() -> list[RepoRecord]:
        """Return repo records from the callback or store, with error fallback."""
        if list_repos_cb is not None:
            try:
                return list_repos_cb()
            except Exception:  # noqa: BLE001
                logger.warning("list_repos callback failed", exc_info=True)
        if repo_store is not None:
            try:
                return repo_store.list()
            except Exception:  # noqa: BLE001
                logger.warning("repo_store.list failed", exc_info=True)
        return []

    # Supervisor client/manager removed with hf_cli package (issue #2205).
    # Supervisor endpoints now return graceful "unavailable" responses.
    supervisor_client = None
    supervisor_manager = None

    def _serve_spa_index() -> HTMLResponse:
        """Serve the SPA index.html, falling back to template or placeholder."""
        react_index = ui_dist_dir / "index.html"
        if react_index.exists():
            return HTMLResponse(react_index.read_text())
        template_path = template_dir / "index.html"
        if template_path.exists():
            return HTMLResponse(template_path.read_text())
        return HTMLResponse(
            "<h1>HydraFlow Dashboard</h1><p>Run 'make ui' to build.</p>"
        )

    def _load_local_metrics_cache(
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
            "active_worktrees": len(state.get_active_worktrees()),
            "worker_count": worker_count,
            "worker_errors": worker_errors,
            "dashboard": dashboard_binding,
            "session_started_at": session_started_at,
            "uptime_seconds": uptime_seconds,
            "ready": ready,
            "checks": checks,
        }
        return JSONResponse(payload)

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
            from datetime import datetime

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
        manager = _pr_manager_for(_cfg, _bus)
        all_labels = list(
            {
                *_cfg.ready_label,
                *_cfg.review_label,
                *_cfg.fixed_label,
                *_cfg.hitl_label,
                *_cfg.hitl_active_label,
                *_cfg.planner_label,
                *_cfg.improve_label,
            }
        )
        items = await manager.list_open_prs(all_labels)
        return JSONResponse([item.model_dump() for item in items])

    @router.get("/api/epics")
    async def get_epics(
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Return all tracked epics with enriched sub-issue progress."""
        _cfg, _state, _bus, _get_orch = _resolve_runtime(repo)
        orch = _get_orch()
        if orch is None:
            return JSONResponse([])
        details = await orch._epic_manager.get_all_detail()
        return JSONResponse([d.model_dump() for d in details])

    @router.get("/api/epics/{epic_number}")
    async def get_epic_detail(
        epic_number: int,
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Return full detail for a single epic including child issue info."""
        _cfg, _state, _bus, _get_orch = _resolve_runtime(repo)
        orch = _get_orch()
        if orch is None:
            return JSONResponse({"error": "orchestrator not running"}, status_code=503)
        detail = await orch._epic_manager.get_detail(epic_number)
        if detail is None:
            return JSONResponse({"error": "epic not found"}, status_code=404)
        return JSONResponse(detail.model_dump())

    @router.post("/api/epics/{epic_number}/release")
    async def trigger_epic_release(
        epic_number: int,
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Trigger async merge sequence and release creation for an epic.

        Returns a job_id. Completion is signalled via the EPIC_RELEASED WebSocket
        event — there is no REST polling endpoint for job status.
        """
        _cfg, _state, _bus, _get_orch = _resolve_runtime(repo)
        orch = _get_orch()
        if orch is None:
            return JSONResponse({"error": "orchestrator not running"}, status_code=503)
        result = await orch._epic_manager.trigger_release(epic_number)
        if "error" in result:
            return JSONResponse(result, status_code=400)
        return JSONResponse(result)

    # --- Crate (milestone) routes ---
    @router.get("/api/human-input")
    async def get_human_input_requests(
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Return pending human-input prompts from the orchestrator."""
        _cfg, _state, _bus, _get_orch = _resolve_runtime(repo)
        orch = _get_orch()
        if orch:
            return JSONResponse(orch.human_input_requests)
        return JSONResponse({})

    @router.post("/api/human-input/{issue_number}")
    async def provide_human_input(
        issue_number: int,
        body: dict[str, Any],
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Submit an operator answer to a pending human-input request."""
        _cfg, _state, _bus, _get_orch = _resolve_runtime(repo)
        orch = _get_orch()
        if orch:
            answer = body.get("answer", "")
            orch.provide_human_input(issue_number, answer)
            return JSONResponse({"status": "ok"})
        return JSONResponse({"status": "no orchestrator"}, status_code=400)

    @router.post("/api/control/start")
    async def start_orchestrator() -> JSONResponse:
        """Create and start a new orchestrator instance."""
        orch = get_orchestrator()
        if orch and orch.running:
            return JSONResponse({"error": "already running"}, status_code=409)

        from orchestrator import HydraFlowOrchestrator

        new_orch = HydraFlowOrchestrator(
            config,
            event_bus=event_bus,
            state=state,
        )
        set_orchestrator(new_orch)
        set_run_task(asyncio.create_task(new_orch.run()))
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ORCHESTRATOR_STATUS,
                data=OrchestratorStatusPayload(status="running", reset=True),
            )
        )
        return JSONResponse({"status": "started"})

    @router.post("/api/control/stop")
    async def stop_orchestrator() -> JSONResponse:
        """Request a graceful stop of the running orchestrator."""
        orch = get_orchestrator()
        if not orch or not orch.running:
            return JSONResponse({"error": "not running"}, status_code=400)
        await orch.request_stop()
        return JSONResponse({"status": "stopping"})

    @router.get("/api/control/status")
    async def get_control_status(
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Return orchestrator run status, config summary, and version info."""
        _cfg, _state, _bus, _get_orch = _resolve_runtime(repo)
        orch = _get_orch()
        status = "idle"
        current_session = None
        latest_version = ""
        update_available = False
        if orch:
            status = orch.run_status
            current_session = orch.current_session_id
        update_result = load_cached_update_result(current_version=get_app_version())
        if update_result is not None:
            latest_version = update_result.latest_version or ""
            update_available = update_result.update_available
        credits_until = (
            orch.credits_paused_until.isoformat()
            if orch and orch.credits_paused_until
            else None
        )
        try:
            control_status = ControlStatus(status)
        except ValueError:
            control_status = ControlStatus.IDLE
        response = ControlStatusResponse(
            status=control_status,
            credits_paused_until=credits_until,
            config=ControlStatusConfig(
                app_version=get_app_version(),
                latest_version=latest_version,
                update_available=update_available,
                repo=_cfg.repo,
                ready_label=_cfg.ready_label,
                find_label=_cfg.find_label,
                planner_label=_cfg.planner_label,
                review_label=_cfg.review_label,
                hitl_label=_cfg.hitl_label,
                hitl_active_label=_cfg.hitl_active_label,
                fixed_label=_cfg.fixed_label,
                improve_label=_cfg.improve_label,
                memory_label=_cfg.memory_label,
                transcript_label=_cfg.transcript_label,
                max_triagers=_cfg.max_triagers,
                max_workers=_cfg.max_workers,
                max_planners=_cfg.max_planners,
                max_reviewers=_cfg.max_reviewers,
                max_hitl_workers=_cfg.max_hitl_workers,
                batch_size=_cfg.batch_size,
                model=_cfg.model,
                memory_auto_approve=_cfg.memory_auto_approve,
                pr_unstick_batch_size=_cfg.pr_unstick_batch_size,
                worktree_base=str(_cfg.worktree_base),
            ),
        )
        data = response.model_dump()
        data["current_session_id"] = current_session
        return JSONResponse(data)

    @router.post("/api/admin/prep")
    async def admin_prep(
        repo: str | None = Query(default=None, description="Repo slug to target"),
    ) -> JSONResponse:
        return await _execute_admin_task("prep", run_prep, repo)

    @router.post("/api/admin/scaffold")
    async def admin_scaffold(
        repo: str | None = Query(default=None, description="Repo slug to target"),
    ) -> JSONResponse:
        return await _execute_admin_task("scaffold", run_scaffold, repo)

    @router.post("/api/admin/clean")
    async def admin_clean(
        repo: str | None = Query(default=None, description="Repo slug to target"),
    ) -> JSONResponse:
        return await _execute_admin_task("clean", run_clean, repo)

    @router.post("/api/admin/ensure-labels")
    async def admin_ensure_labels(
        repo: str | None = Query(default=None, description="Repo slug to target"),
    ) -> JSONResponse:
        return await _execute_admin_task("ensure-labels", run_ensure_labels, repo)

    # Mutable fields that can be changed at runtime via PATCH
    _MUTABLE_FIELDS = {
        "max_triagers",
        "max_workers",
        "max_planners",
        "max_reviewers",
        "max_hitl_workers",
        "model",
        "review_model",
        "planner_model",
        "batch_size",
        "max_ci_fix_attempts",
        "max_quality_fix_attempts",
        "max_review_fix_attempts",
        "min_review_findings",
        "max_merge_conflict_fix_attempts",
        "ci_check_timeout",
        "ci_poll_interval",
        "poll_interval",
        "pr_unstick_interval",
        "pr_unstick_batch_size",
        "memory_auto_approve",
        "unstick_auto_merge",
        "unstick_all_causes",
        "worktree_base",
        "auto_crate",
    }

    @router.patch("/api/control/config")
    async def patch_config(
        body: dict[str, Any],
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Update runtime config fields. Pass ``persist: true`` to save to disk.

        When *repo* is provided, updates are scoped to that runtime's config and
        persisted as overrides in the repo store.
        """
        persist = body.pop("persist", False)
        _cfg, _state, _bus, _get_orch = _resolve_runtime(repo)

        updates: dict[str, Any] = {}

        for key, value in body.items():
            if key not in _MUTABLE_FIELDS:
                continue
            if not hasattr(_cfg, key):
                continue
            updates[key] = value

        if not updates:
            return JSONResponse({"status": "ok", "updated": {}})

        # Validate updates through Pydantic field constraints
        test_values = _cfg.model_dump()
        test_values.update(updates)
        try:
            validated = HydraFlowConfig.model_validate(test_values)
        except ValidationError as exc:
            errors = exc.errors()
            msg = "; ".join(
                f"{e['loc'][-1]}: {e['msg']}" for e in errors if e.get("loc")
            )
            return JSONResponse(
                {"status": "error", "message": msg or "Invalid configuration"},
                status_code=422,
            )

        # Apply validated values to the live config
        applied: dict[str, Any] = {}
        for key in updates:
            validated_value = getattr(validated, key)
            object.__setattr__(_cfg, key, validated_value)
            applied[key] = validated_value

        if repo and repo_store is not None and applied:
            repo_store.update_overrides(repo, applied)
        elif persist and applied:
            save_config_file(_cfg.config_file, applied)

        return JSONResponse({"status": "ok", "updated": applied})

    # Import worker definitions from extracted module.
    from dashboard_worker_defs import (
        BG_WORKER_DEFS as _bg_worker_defs,
    )
    from dashboard_worker_defs import (
        INTERVAL_BOUNDS as _INTERVAL_BOUNDS,
    )
    from dashboard_worker_defs import (
        INTERVAL_WORKERS as _INTERVAL_WORKERS,
    )
    from dashboard_worker_defs import (
        PIPELINE_WORKERS as _PIPELINE_WORKERS,
    )
    from dashboard_worker_defs import (
        WORKER_SOURCE_ALIASES as _WORKER_SOURCE_ALIASES,
    )

    def _build_system_worker_inference_stats() -> dict[str, dict[str, int]]:
        """Aggregate prompt-telemetry inference stats keyed by worker name."""
        telemetry = PromptTelemetry(config)
        source_totals = telemetry.get_source_totals()

        worker_totals: dict[str, dict[str, int]] = {}
        for worker_name, _label, _description in _bg_worker_defs:
            sources = (worker_name, *_WORKER_SOURCE_ALIASES.get(worker_name, ()))
            totals = {
                "inference_calls": 0,
                "total_tokens": 0,
                "pruned_chars_total": 0,
            }
            for source_name in sources:
                source_entry = source_totals.get(source_name)
                if not source_entry:
                    continue
                totals["inference_calls"] += source_entry["inference_calls"]
                totals["total_tokens"] += source_entry["total_tokens"]
                totals["pruned_chars_total"] += source_entry["pruned_chars_total"]
            if totals["inference_calls"] > 0:
                saved_tokens_est = round(totals["pruned_chars_total"] / 4)
                worker_totals[worker_name] = {
                    "inference_calls": totals["inference_calls"],
                    "total_tokens": totals["total_tokens"],
                    "pruned_chars_total": totals["pruned_chars_total"],
                    "saved_tokens_est": saved_tokens_est,
                    "unpruned_tokens_est": totals["total_tokens"] + saved_tokens_est,
                }
        return worker_totals

    def _compute_next_run(
        last_run: str | None, interval_seconds: int | None
    ) -> str | None:
        """Compute next run ISO timestamp from last_run + interval."""
        if not last_run or not interval_seconds:
            return None
        from datetime import datetime, timedelta

        try:
            last_dt = datetime.fromisoformat(last_run)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=UTC)
            next_dt = last_dt + timedelta(seconds=interval_seconds)
            return next_dt.isoformat()
        except (ValueError, TypeError):
            return None

    @router.get("/api/system/workers")
    async def get_system_workers(
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Return last known status of each background worker."""
        _cfg, _state, _bus, _get_orch = _resolve_runtime(repo)
        orch = _get_orch()
        bg_states = orch.get_bg_worker_states() if orch else {}
        persisted_states: dict[str, BackgroundWorkerState] = {}
        if not orch:
            try:
                persisted_states = _state.get_bg_worker_states()
            except Exception:  # pragma: no cover - defensive guard
                logger.exception("Failed to load persisted bg worker states")
        inference_by_worker = _build_system_worker_inference_stats()
        workers = []
        for name, label, description in _bg_worker_defs:
            enabled = orch.is_bg_worker_enabled(name) if orch else True

            # Determine interval for this worker
            interval: int | None = None
            if name in _INTERVAL_WORKERS and orch:
                interval = orch.get_bg_worker_interval(name)
            elif name in _INTERVAL_WORKERS:
                if name == "memory_sync":
                    interval = _cfg.memory_sync_interval
                elif name == "metrics":
                    interval = _cfg.metrics_sync_interval
                elif name == "pr_unsticker":
                    interval = _cfg.pr_unstick_interval
                elif name == "pipeline_poller":
                    interval = 5
            elif name in _PIPELINE_WORKERS:
                interval = _cfg.poll_interval

            entry = bg_states.get(name) or persisted_states.get(name)
            if entry:
                last_run = entry.get("last_run")
                raw_details = entry.get("details", {})
                details: dict[str, Any] = (
                    dict(raw_details)
                    if isinstance(raw_details, dict)
                    else {"raw_details": str(raw_details)}
                )
                details.update(inference_by_worker.get(name, {}))
                workers.append(
                    BackgroundWorkerStatus(
                        name=name,
                        label=label,
                        description=description,
                        status=BGWorkerHealth(
                            entry.get("status", BGWorkerHealth.DISABLED)
                        ),
                        enabled=enabled,
                        last_run=last_run,
                        interval_seconds=interval,
                        next_run=_compute_next_run(last_run, interval),
                        details=details,
                    )
                )
            else:
                workers.append(
                    BackgroundWorkerStatus(
                        name=name,
                        label=label,
                        description=description,
                        enabled=enabled,
                        interval_seconds=interval,
                        details=inference_by_worker.get(name, {}),
                    )
                )
        return JSONResponse(BackgroundWorkersResponse(workers=workers).model_dump())

    @router.post("/api/control/bg-worker")
    async def toggle_bg_worker(body: dict[str, Any]) -> JSONResponse:
        """Enable or disable a background worker."""
        name = body.get("name")
        enabled = body.get("enabled")
        if not name or enabled is None:
            return JSONResponse(
                {"error": "name and enabled are required"}, status_code=400
            )
        orch = get_orchestrator()
        if not orch:
            return JSONResponse({"error": "no orchestrator"}, status_code=400)
        orch.set_bg_worker_enabled(name, bool(enabled))
        return JSONResponse({"status": "ok", "name": name, "enabled": bool(enabled)})

    @router.post("/api/control/bg-worker/trigger")
    async def trigger_bg_worker(body: dict[str, Any]) -> JSONResponse:
        """Trigger an immediate execution of a background worker."""
        name = body.get("name")
        if not name:
            return JSONResponse({"error": "name is required"}, status_code=400)
        orch = get_orchestrator()
        if not orch:
            return JSONResponse({"error": "no orchestrator"}, status_code=400)
        triggered = orch.trigger_bg_worker(name)
        if not triggered:
            return JSONResponse({"error": f"unknown worker '{name}'"}, status_code=404)
        return JSONResponse({"status": "ok", "name": name})

    @router.post("/api/control/bg-worker/interval")
    async def set_bg_worker_interval(body: dict[str, Any]) -> JSONResponse:
        """Update the polling interval for a background worker."""
        name = body.get("name")
        interval = body.get("interval_seconds")
        if not name or interval is None:
            return JSONResponse(
                {"error": "name and interval_seconds are required"}, status_code=400
            )
        if name not in _INTERVAL_BOUNDS:
            return JSONResponse(
                {"error": f"interval not editable for worker '{name}'"}, status_code=400
            )
        try:
            interval = int(interval)
        except (TypeError, ValueError):
            return JSONResponse(
                {"error": "interval_seconds must be an integer"}, status_code=400
            )
        lo, hi = _INTERVAL_BOUNDS[name]
        if interval < lo or interval > hi:
            return JSONResponse(
                {"error": f"interval_seconds must be between {lo} and {hi}"},
                status_code=422,
            )
        orch = get_orchestrator()
        if not orch:
            return JSONResponse({"error": "no orchestrator"}, status_code=400)
        orch.set_bg_worker_interval(name, interval)
        return JSONResponse(
            {"status": "ok", "name": name, "interval_seconds": interval}
        )

    @router.get("/api/metrics")
    async def get_metrics(
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Return lifetime stats, derived rates, time-to-merge, and thresholds."""
        _cfg, _state, _bus, _get_orch = _resolve_runtime(repo)
        lifetime = _state.get_lifetime_stats()
        rates: dict[str, float] = {}
        total_reviews = (
            lifetime.total_review_approvals + lifetime.total_review_request_changes
        )
        if lifetime.issues_completed > 0:
            rates["merge_rate"] = lifetime.prs_merged / lifetime.issues_completed
            rates["quality_fix_rate"] = (
                lifetime.total_quality_fix_rounds / lifetime.issues_completed
            )
            rates["hitl_escalation_rate"] = (
                lifetime.total_hitl_escalations / lifetime.issues_completed
            )
            rates["avg_implementation_seconds"] = (
                lifetime.total_implementation_seconds / lifetime.issues_completed
            )
        if total_reviews > 0:
            rates["first_pass_approval_rate"] = (
                lifetime.total_review_approvals / total_reviews
            )
            rates["reviewer_fix_rate"] = lifetime.total_reviewer_fixes / total_reviews
        time_to_merge = _state.get_merge_duration_stats()
        thresholds = _state.check_thresholds(
            _cfg.quality_fix_rate_threshold,
            _cfg.approval_rate_threshold,
            _cfg.hitl_rate_threshold,
        )
        retries = _state.get_retries_summary()
        if retries:
            rates["retries_per_stage"] = sum(retries.values())

        telemetry = PromptTelemetry(_cfg)
        inference_lifetime = telemetry.get_lifetime_totals()
        orch = _get_orch()
        session_id = orch.current_session_id if orch else ""
        inference_session = (
            telemetry.get_session_totals(session_id) if session_id else {}
        )

        return JSONResponse(
            MetricsResponse(
                lifetime=lifetime,
                rates=rates,
                time_to_merge=time_to_merge,
                thresholds=thresholds,
                inference_lifetime=inference_lifetime,
                inference_session=inference_session,
            ).model_dump()
        )

    @router.get("/api/metrics/github")
    async def get_github_metrics(
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Query GitHub for issue/PR counts by label state."""
        _cfg, _state, _bus, _get_orch = _resolve_runtime(repo)
        manager = _pr_manager_for(_cfg, _bus)
        counts = await manager.get_label_counts(_cfg)
        return JSONResponse(counts)

    @router.get("/api/metrics/history")
    async def get_metrics_history(
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Historical snapshots from the metrics issue + current in-memory snapshot.

        Falls back to local disk cache when the orchestrator is not running.
        """
        _cfg, _state, _bus, _get_orch = _resolve_runtime(repo)
        orch = _get_orch()
        if orch is None:
            # Serve from local cache without requiring the orchestrator
            snapshots = _load_local_metrics_cache(_cfg)
            return JSONResponse(
                MetricsHistoryResponse(snapshots=snapshots).model_dump()
            )
        mgr = orch.metrics_manager
        snapshots = await mgr.fetch_history_from_issue()
        current = mgr.latest_snapshot
        return JSONResponse(
            MetricsHistoryResponse(
                snapshots=snapshots,
                current=current,
            ).model_dump()
        )

    @router.get("/api/runs")
    async def list_run_issues() -> JSONResponse:
        """Return issue numbers that have recorded runs."""
        orch = get_orchestrator()
        if not orch:
            return JSONResponse([])
        return JSONResponse(orch.run_recorder.list_issues())

    @router.get("/api/runs/{issue_number}")
    async def get_runs(issue_number: int) -> JSONResponse:
        """Return all recorded runs for an issue."""
        orch = get_orchestrator()
        if not orch:
            return JSONResponse([])
        runs = orch.run_recorder.list_runs(issue_number)
        return JSONResponse([r.model_dump() for r in runs])

    @router.get("/api/runs/{issue_number}/{timestamp}/{filename}")
    async def get_run_artifact(
        issue_number: int, timestamp: str, filename: str
    ) -> Response:
        """Return a specific artifact file from a recorded run."""
        orch = get_orchestrator()
        if not orch:
            return JSONResponse({"error": "no orchestrator"}, status_code=400)
        content = orch.run_recorder.get_run_artifact(issue_number, timestamp, filename)
        if content is None:
            return JSONResponse({"error": "artifact not found"}, status_code=404)
        return Response(content=content, media_type="text/plain")

    @router.get("/api/artifacts/stats")
    async def get_artifact_stats() -> JSONResponse:
        """Return storage statistics for run artifacts."""
        orch = get_orchestrator()
        if not orch:
            return JSONResponse({"error": "no orchestrator"}, status_code=400)
        stats = orch.run_recorder.get_storage_stats()
        stats["retention_days"] = config.artifact_retention_days
        stats["max_size_mb"] = config.artifact_max_size_mb
        return JSONResponse(stats)

    @router.get("/api/harness-insights")
    async def get_harness_insights() -> JSONResponse:
        """Return recent harness failure patterns and improvement suggestions."""
        from harness_insights import (
            HarnessInsightStore,
            generate_suggestions,
        )

        memory_dir = config.data_path("memory")
        store = HarnessInsightStore(memory_dir)
        records = store.load_recent(config.harness_insight_window)
        proposed = store.get_proposed_patterns()
        suggestions = generate_suggestions(
            records, config.harness_pattern_threshold, proposed
        )

        # Build category summary
        cat_counts: Counter[str] = Counter(r.category for r in records)
        sub_counts: Counter[str] = Counter()
        for r in records:
            for sub in r.subcategories:
                sub_counts[sub] += 1

        return JSONResponse(
            {
                "total_failures": len(records),
                "category_counts": dict(cat_counts.most_common()),
                "subcategory_counts": dict(sub_counts.most_common()),
                "suggestions": [s.model_dump() for s in suggestions],
                "proposed_patterns": sorted(proposed),
            }
        )

    @router.get("/api/harness-insights/history")
    async def get_harness_insights_history() -> JSONResponse:
        """Return raw failure records for historical analysis."""
        from harness_insights import HarnessInsightStore

        memory_dir = config.data_path("memory")
        store = HarnessInsightStore(memory_dir)
        records = store.load_recent(config.harness_insight_window)
        return JSONResponse([r.model_dump() for r in records])

    @router.get("/api/review-insights")
    async def get_review_insights() -> JSONResponse:
        """Return aggregated review feedback patterns and category breakdown."""
        from review_insights import ReviewInsightStore, analyze_patterns

        memory_dir = config.data_path("memory")
        store = ReviewInsightStore(memory_dir)
        records = store.load_recent(config.review_insight_window)
        proposed = store.get_proposed_categories()

        verdict_counts: Counter[str] = Counter(r.verdict.value for r in records)
        category_counts: Counter[str] = Counter(
            cat for r in records for cat in r.categories
        )
        fixes_made_count = sum(1 for r in records if r.fixes_made)

        patterns_raw = analyze_patterns(records, config.harness_pattern_threshold)
        patterns = [
            {
                "category": cat,
                "count": cnt,
                "evidence": [
                    {
                        "issue_number": r.issue_number,
                        "pr_number": r.pr_number,
                        "summary": r.summary,
                    }
                    for r in evidence
                ],
            }
            for cat, cnt, evidence in patterns_raw
        ]

        return JSONResponse(
            {
                "total_reviews": len(records),
                "verdict_counts": dict(verdict_counts),
                "category_counts": dict(category_counts),
                "fixes_made_count": fixes_made_count,
                "patterns": patterns,
                "proposed_categories": sorted(proposed),
            }
        )

    @router.get("/api/retrospectives")
    async def get_retrospectives() -> JSONResponse:
        """Return aggregated retrospective stats and recent entries."""
        from retrospective import RetrospectiveEntry

        retro_path = config.data_path("memory", "retrospectives.jsonl")
        entries: list[RetrospectiveEntry] = []
        if retro_path.exists():
            for line in retro_path.read_text().strip().splitlines():
                with contextlib.suppress(Exception):
                    entries.append(RetrospectiveEntry.model_validate_json(line))
        entries = entries[-config.retrospective_window :]

        if not entries:
            return JSONResponse(
                {
                    "total_entries": 0,
                    "avg_plan_accuracy": 0,
                    "avg_quality_fix_rounds": 0,
                    "avg_ci_fix_rounds": 0,
                    "avg_duration_seconds": 0,
                    "reviewer_fix_rate": 0,
                    "verdict_counts": {},
                    "entries": [],
                }
            )

        n = len(entries)
        avg_accuracy = round(sum(e.plan_accuracy_pct for e in entries) / n, 1)
        avg_quality = round(sum(e.quality_fix_rounds for e in entries) / n, 2)
        avg_ci = round(sum(e.ci_fix_rounds for e in entries) / n, 2)
        avg_duration = round(sum(e.duration_seconds for e in entries) / n, 1)
        fix_count = sum(1 for e in entries if e.reviewer_fixes_made)
        verdict_counts: Counter[str] = Counter(
            str(e.review_verdict) for e in entries if e.review_verdict
        )

        return JSONResponse(
            {
                "total_entries": n,
                "avg_plan_accuracy": avg_accuracy,
                "avg_quality_fix_rounds": avg_quality,
                "avg_ci_fix_rounds": avg_ci,
                "avg_duration_seconds": avg_duration,
                "reviewer_fix_rate": round(fix_count / n, 3),
                "verdict_counts": dict(verdict_counts),
                "entries": [e.model_dump() for e in entries],
            }
        )

    @router.get("/api/memories")
    async def get_memories() -> JSONResponse:
        """Return memory items and curated manifest data."""
        from manifest_curator import CuratedManifestStore

        items_dir = config.data_path("memory", "items")
        digest_path = config.data_path("memory", "digest.md")

        items: list[dict[str, object]] = []
        if items_dir.is_dir():
            for path in sorted(items_dir.glob("*.md"), reverse=True):
                try:
                    issue_number = int(path.stem)
                    items.append(
                        {
                            "issue_number": issue_number,
                            "learning": path.read_text().strip(),
                        }
                    )
                except (ValueError, OSError):
                    pass

        digest_chars = 0
        if digest_path.exists():
            with contextlib.suppress(OSError):
                digest_chars = digest_path.stat().st_size

        curated_store = CuratedManifestStore(config)
        curated = curated_store.load()

        return JSONResponse(
            {
                "total_items": len(items),
                "digest_chars": digest_chars,
                "curated": curated,
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

    # --- Repo runtime lifecycle endpoints ---

    @router.get("/api/runtimes")
    async def list_runtimes() -> JSONResponse:
        """List all registered repo runtimes with status."""
        from models import RepoRuntimeInfo

        if registry is None:
            return JSONResponse({"runtimes": []})
        infos = []
        for rt in registry.all:
            infos.append(
                RepoRuntimeInfo(
                    slug=rt.slug,
                    repo=rt.config.repo,
                    running=rt.running,
                    session_id=rt.orchestrator.current_session_id
                    if rt.running
                    else None,
                ).model_dump()
            )
        return JSONResponse({"runtimes": infos})

    @router.get("/api/runtimes/{slug}")
    async def get_runtime_status(slug: str) -> JSONResponse:
        """Get status of a specific repo runtime."""
        from models import RepoRuntimeInfo

        if registry is None:
            return JSONResponse(
                {"error": "No runtime registry configured"}, status_code=501
            )
        rt = registry.get(slug)
        if rt is None:
            return JSONResponse({"error": f"Unknown repo: {slug}"}, status_code=404)
        info = RepoRuntimeInfo(
            slug=rt.slug,
            repo=rt.config.repo,
            running=rt.running,
            session_id=rt.orchestrator.current_session_id if rt.running else None,
        )
        return JSONResponse(info.model_dump())

    @router.post("/api/runtimes/{slug}/start")
    async def start_runtime(slug: str) -> JSONResponse:
        """Start a specific repo runtime."""
        if registry is None:
            return JSONResponse(
                {"error": "No runtime registry configured"}, status_code=501
            )
        rt = registry.get(slug)
        if rt is None:
            return JSONResponse({"error": f"Unknown repo: {slug}"}, status_code=404)
        if rt.running:
            return JSONResponse({"error": "Already running"}, status_code=409)
        await rt.start()
        return JSONResponse({"status": "started", "slug": slug})

    @router.post("/api/runtimes/{slug}/stop")
    async def stop_runtime(slug: str) -> JSONResponse:
        """Stop a specific repo runtime."""
        if registry is None:
            return JSONResponse(
                {"error": "No runtime registry configured"}, status_code=501
            )
        rt = registry.get(slug)
        if rt is None:
            return JSONResponse({"error": f"Unknown repo: {slug}"}, status_code=404)
        if not rt.running:
            return JSONResponse({"error": "Not running"}, status_code=400)
        await rt.stop()
        return JSONResponse({"status": "stopped", "slug": slug})

    @router.delete("/api/runtimes/{slug}")
    async def remove_runtime(slug: str) -> JSONResponse:
        """Stop and unregister a repo runtime."""
        if registry is None:
            return JSONResponse(
                {"error": "No runtime registry configured"}, status_code=501
            )
        rt = registry.get(slug)
        if rt is None:
            return JSONResponse({"error": f"Unknown repo: {slug}"}, status_code=404)
        if remove_repo_cb is not None:
            try:
                await remove_repo_cb(slug)
            except Exception as exc:  # noqa: BLE001
                logger.warning("remove_repo callback failed for %s: %s", slug, exc)
                return JSONResponse({"error": "Failed to remove repo"}, status_code=500)
            return JSONResponse({"status": "removed", "slug": slug})
        if rt.running:
            await rt.stop()
        registry.remove(slug)
        if repo_store is not None:
            try:
                repo_store.remove(slug)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Failed to remove repo %s from store", slug, exc_info=True
                )
        return JSONResponse({"status": "removed", "slug": slug})

    # --- Multi-repo supervisor endpoints ---

    async def _call_supervisor(func: Callable, *args, **kwargs) -> Any:
        """Run a supervisor client function in a thread."""
        if supervisor_client is None:
            raise RuntimeError(
                "HydraFlow supervisor client unavailable in this environment"
            )
        return await asyncio.to_thread(func, *args, **kwargs)

    @router.get("/api/repos")
    async def list_supervised_repos() -> JSONResponse:
        """List repos from the store, callback, or supervisor."""
        if repo_store is not None or list_repos_cb is not None:
            records = _list_repo_records()
            payload: list[dict[str, Any]] = []
            for rec in records:
                runtime = registry.get(rec.slug) if registry else None
                payload.append(
                    {
                        "slug": rec.slug,
                        "repo": rec.repo,
                        "path": rec.path,
                        "running": bool(runtime.running) if runtime else False,
                        "session_id": runtime.orchestrator.current_session_id
                        if runtime and runtime.running
                        else None,
                    }
                )
            return JSONResponse({"repos": payload})
        if supervisor_client is None:
            return JSONResponse({"repos": []})
        try:
            repos = await _call_supervisor(supervisor_client.list_repos)
        except Exception as exc:  # noqa: BLE001
            if not _is_expected_supervisor_unavailable(exc):
                logger.warning("Supervisor list_repos failed: %s", exc)
            return JSONResponse({"error": "Supervisor unavailable"}, status_code=503)
        return JSONResponse({"repos": repos})

    @router.get("/api/fs/roots")
    async def list_browsable_roots() -> JSONResponse:
        """Return filesystem roots that are safe to browse from the UI."""
        roots = [
            {"name": "Home", "path": _allowed_repo_roots()[0]},
            {"name": "Temp", "path": _allowed_repo_roots()[-1]},
        ]
        # De-duplicate when home and temp resolve to same location.
        seen: set[str] = set()
        unique_roots: list[dict[str, str]] = []
        for root in roots:
            path = root["path"]
            if path in seen:
                continue
            seen.add(path)
            unique_roots.append(root)
        return JSONResponse({"roots": unique_roots})

    @router.get("/api/fs/list")
    async def list_browsable_directories(
        path: str | None = Query(default=None),
    ) -> JSONResponse:
        """List child directories for the requested path under allowed roots."""
        allowed_roots = _allowed_repo_roots()
        target_raw = path or allowed_roots[0]
        target_path, error = _normalize_allowed_dir(target_raw)
        if error or target_path is None:
            return JSONResponse({"error": error or "invalid path"}, status_code=400)

        current = str(target_path)
        parent: str | None = None
        parent_candidate = os.path.realpath(str(target_path.parent))
        inside_allowed_parent = any(
            parent_candidate == root or parent_candidate.startswith(f"{root}{os.sep}")
            for root in allowed_roots
        )
        if inside_allowed_parent and parent_candidate != current:
            parent = parent_candidate

        directories: list[dict[str, str]] = []
        try:
            for child in sorted(target_path.iterdir(), key=lambda p: p.name.lower()):
                if not child.is_dir():
                    continue
                # Hide dot-directories in the default browser view.
                if child.name.startswith("."):
                    continue
                child_real = os.path.realpath(str(child))
                inside_allowed_child = any(
                    child_real == root or child_real.startswith(f"{root}{os.sep}")
                    for root in allowed_roots
                )
                if not inside_allowed_child:
                    continue
                directories.append({"name": child.name, "path": child_real})
        except OSError as exc:
            logger.warning("Failed to list directory %s: %s", target_path, exc)
            return JSONResponse({"error": "failed to list directory"}, status_code=500)

        return JSONResponse(
            {
                "current_path": current,
                "parent_path": parent,
                "directories": directories,
            }
        )

    @router.post("/api/repos")
    async def ensure_repo(
        req: dict[str, Any] | None = Body(default=None),
        req_query: str | None = Query(default=None, alias="req"),
        slug: str | None = Query(default=None),
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Ensure a repo is registered with the supervisor by slug."""
        error_payload: tuple[str, int] | None = None
        if supervisor_client is None:
            error_payload = ("supervisor unavailable", 503)
        else:
            target_slug = _extract_repo_slug(req, req_query, slug, repo)
            if not target_slug:
                error_payload = ("slug required", 400)
            else:
                try:
                    repos = await _call_supervisor(supervisor_client.list_repos)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Supervisor list_repos failed: %s", exc)
                    error_payload = ("Supervisor unavailable", 503)
                else:
                    match = _find_repo_match(target_slug, repos)
                    if not match:
                        error_payload = (
                            f"repo '{target_slug}' not found",
                            404,
                        )
                    else:
                        matched_slug = match.get("slug") or target_slug
                        path = match.get("path")
                        if not path:
                            error_payload = (f"repo '{matched_slug}' missing path", 500)
                        else:
                            try:
                                info = await _call_supervisor(
                                    supervisor_client.add_repo,
                                    Path(path),
                                    matched_slug,
                                )
                            except Exception as exc:  # noqa: BLE001
                                logger.warning("Supervisor add_repo failed: %s", exc)
                                error_payload = ("Failed to add repo", 500)
                            else:
                                return JSONResponse(info)

        if error_payload:
            message, status_code = error_payload
            return JSONResponse({"error": message}, status_code=status_code)
        return JSONResponse({"status": "ok"})

    @router.delete("/api/repos/{slug}")
    async def remove_repo(slug: str) -> JSONResponse:
        """Remove a repo via the callback or supervisor."""
        if remove_repo_cb is not None:
            try:
                removed = await remove_repo_cb(slug)
            except Exception as exc:  # noqa: BLE001
                logger.warning("remove_repo callback failed: %s", exc)
                return JSONResponse({"error": "Failed to remove repo"}, status_code=500)
            if not removed:
                return JSONResponse({"error": "Repo not found"}, status_code=404)
            return JSONResponse({"status": "ok"})
        if supervisor_client is None:
            return JSONResponse({"error": "supervisor unavailable"}, status_code=503)
        try:
            await _call_supervisor(supervisor_client.remove_repo, None, slug)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Supervisor remove_repo failed: %s", exc)
            return JSONResponse({"error": "Failed to remove repo"}, status_code=500)
        return JSONResponse({"status": "ok"})

    async def _detect_repo_slug_from_path(repo_path: Path) -> str | None:  # noqa: PLR0911
        """Extract ``owner/repo`` from git remote origin URL at *repo_path*."""
        from urllib.parse import urlparse  # noqa: PLC0415

        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                "-C",
                str(repo_path),
                "remote",
                "get-url",
                "origin",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        except (FileNotFoundError, OSError, TimeoutError):
            return None
        url = (stdout or b"").decode().strip()
        if not url:
            return None
        if url.startswith(("http://", "https://")):
            parsed = urlparse(url)
            host = (parsed.hostname or "").lower()
            if host != "github.com":
                return None
            return parsed.path.lstrip("/").removesuffix(".git") or None
        if url.startswith("git@"):
            if "@" not in url or ":" not in url:
                return None
            user_host, _, remainder = url.partition(":")
            _, _, host = user_host.partition("@")
            if host.lower() != "github.com":
                return None
            slug = remainder.lstrip("/").removesuffix(".git")
            return slug or None
        return None

    @router.post("/api/repos/add")
    async def add_repo_by_path(  # noqa: PLR0911
        req: dict[str, Any] | None = Body(default=None),
        req_query: str | None = Query(default=None, alias="req"),
        path: str | None = Query(default=None),
        repo_path_query: str | None = Query(default=None, alias="repo_path"),
    ) -> JSONResponse:
        """Register a repo by local filesystem path (does NOT start it)."""
        if isinstance(req, dict):
            for key in ("path", "repo_path"):
                value = req.get(key)
                if value is not None and not isinstance(value, str):
                    return JSONResponse(
                        {"error": "path must be a string"}, status_code=400
                    )
            nested = req.get("req")
            if isinstance(nested, dict):
                for key in ("path", "repo_path"):
                    value = nested.get(key)
                    if value is not None and not isinstance(value, str):
                        return JSONResponse(
                            {"error": "path must be a string"}, status_code=400
                        )
        raw_path = _extract_repo_path(req, req_query, path, repo_path_query)
        if not raw_path:
            return JSONResponse({"error": "path required"}, status_code=400)
        repo_path, path_error = _normalize_allowed_dir(raw_path)
        if path_error or repo_path is None:
            return JSONResponse(
                {"error": path_error or "invalid path"}, status_code=400
            )
        # Validate it's a git repo
        is_git = False
        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                "-C",
                str(repo_path),
                "rev-parse",
                "--git-dir",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=10)
            is_git = proc.returncode == 0
        except (FileNotFoundError, OSError, TimeoutError):
            pass
        if not is_git:
            return JSONResponse(
                {"error": f"not a git repository: {raw_path}"},
                status_code=400,
            )
        # Detect slug
        slug = await _detect_repo_slug_from_path(repo_path)
        if register_repo_cb is not None:
            try:
                record, repo_cfg = await register_repo_cb(repo_path, slug)
            except ValueError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)
            except Exception as exc:  # noqa: BLE001
                logger.warning("register_repo callback failed: %s", exc)
                return JSONResponse(
                    {"error": "Failed to register repo"}, status_code=500
                )
            labels_created = False
            if slug:
                try:
                    from prep import ensure_labels  # noqa: PLC0415

                    await ensure_labels(repo_cfg)
                    labels_created = True
                except Exception:  # noqa: BLE001
                    logger.warning("Label creation failed for %s", slug, exc_info=True)
            return JSONResponse(
                {
                    "status": "ok",
                    "slug": record.slug,
                    "path": record.path,
                    "labels_created": labels_created,
                }
            )

        # Register with supervisor fallback
        if supervisor_client is None:
            return JSONResponse(
                {"error": _SUPERVISOR_UNAVAILABLE_MESSAGE},
                status_code=503,
            )
        try:
            await _call_supervisor(
                supervisor_client.register_repo,
                repo_path,
                slug,
            )
        except Exception as exc:  # noqa: BLE001
            if _is_expected_supervisor_unavailable(exc):
                if supervisor_manager is not None:
                    try:
                        await _call_supervisor(supervisor_manager.ensure_running)
                        await _call_supervisor(
                            supervisor_client.register_repo,
                            repo_path,
                            slug,
                        )
                    except Exception as retry_exc:  # noqa: BLE001
                        if _is_expected_supervisor_unavailable(retry_exc):
                            return JSONResponse(
                                {"error": _SUPERVISOR_UNAVAILABLE_MESSAGE},
                                status_code=503,
                            )
                        logger.warning(
                            "Supervisor register_repo failed after auto-start: %s",
                            retry_exc,
                        )
                        return JSONResponse(
                            {"error": "Failed to register repo"},
                            status_code=500,
                        )
                else:
                    return JSONResponse(
                        {"error": _SUPERVISOR_UNAVAILABLE_MESSAGE},
                        status_code=503,
                    )
            else:
                logger.warning("Supervisor register_repo failed: %s", exc)
                return JSONResponse(
                    {"error": "Failed to register repo"},
                    status_code=500,
                )
        # Create labels (best-effort, only after successful registration)
        labels_created = False
        if slug:
            try:
                from prep import ensure_labels  # noqa: PLC0415

                target_cfg = config.model_copy(
                    update={
                        "repo_root": repo_path,
                        "repo": slug,
                    },
                )
                await ensure_labels(target_cfg)
                labels_created = True
            except Exception:  # noqa: BLE001
                logger.warning("Label creation failed for %s", slug, exc_info=True)
        return JSONResponse(
            {
                "status": "ok",
                "slug": slug or repo_path.name,
                "path": str(repo_path),
                "labels_created": labels_created,
            }
        )

    @router.post("/api/repos/pick-folder")
    async def pick_repo_folder() -> JSONResponse:
        """Open a native folder picker and return the selected path."""
        selected = await _pick_folder_with_dialog()
        if not selected:
            return JSONResponse({"error": "No folder selected"}, status_code=400)
        path = Path(os.path.realpath(os.path.expanduser(selected)))
        if not path.is_dir():
            return JSONResponse(
                {"error": "Selected path is not a directory"}, status_code=400
            )
        return JSONResponse({"path": str(path)})

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

    @router.post("/api/report")
    async def submit_report(request: ReportIssueRequest) -> JSONResponse:
        """Queue a bug report for async processing by the report issue worker."""
        report = PendingReport(
            description=request.description,
            screenshot_base64=request.screenshot_base64,
            environment=request.environment,
        )
        state.enqueue_report(report)

        title = f"[Bug Report] {request.description[:100]}"
        response = ReportIssueResponse(
            issue_number=0, title=title, url="", status="queued"
        )
        return JSONResponse(response.model_dump())

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

    return router
