"""Route handlers for the HydraFlow dashboard API."""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import json
import logging
import os
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Body, Query, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, ValidationError

from app_version import get_app_version
from config import HydraFlowConfig, save_config_file
from events import EventBus, EventType, HydraFlowEvent
from hf_cli.update_check import load_cached_update_result
from issue_fetcher import IssueFetcher
from issue_store import IssueStoreStage
from metrics_manager import get_metrics_cache_dir
from models import (
    BackgroundWorkersResponse,
    BackgroundWorkerState,
    BackgroundWorkerStatus,
    BGWorkerHealth,
    ControlStatusConfig,
    ControlStatusResponse,
    CrateCreateRequest,
    CrateItemsRequest,
    CrateUpdateRequest,
    HITLCloseRequest,
    HITLSkipRequest,
    IntentRequest,
    IntentResponse,
    IssueHistoryEntry,
    IssueHistoryLink,
    IssueHistoryPR,
    IssueHistoryResponse,
    IssueOutcomeType,
    MetricsHistoryResponse,
    MetricsResponse,
    MetricsSnapshot,
    PendingReport,
    PipelineIssue,
    PipelineSnapshot,
    PipelineSnapshotEntry,
    QueueStats,
    ReportIssueRequest,
    ReportIssueResponse,
    parse_task_links,
)
from pr_manager import PRManager
from prompt_telemetry import PromptTelemetry
from state import StateTracker
from timeline import TimelineBuilder
from transcript_summarizer import TranscriptSummarizer

if TYPE_CHECKING:
    from orchestrator import HydraFlowOrchestrator
    from repo_runtime import RepoRuntime, RepoRuntimeRegistry

logger = logging.getLogger("hydraflow.dashboard")

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
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _event_issue_number(data: dict[str, Any]) -> int | None:
    value = data.get("issue")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _normalise_event_status(event_type: EventType, data: dict[str, Any]) -> str | None:
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


def _status_rank(status: str) -> int:
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
    if raw is None:
        return since is None and until is None
    parsed = _parse_iso_or_none(raw)
    if parsed is None:
        return since is None and until is None
    if since is not None and parsed < since:
        return False
    return not (until is not None and parsed > until)


def _status_sort_key(status: str, timestamp: str | None) -> tuple[datetime, int]:
    parsed = _parse_iso_or_none(timestamp)
    if parsed is None:
        parsed = datetime.min.replace(tzinfo=UTC)
    return (parsed, _status_rank(status))


def _is_expected_supervisor_unavailable(exc: Exception) -> bool:
    """Return True for the expected local-dev supervisor-down condition."""
    text = str(exc).strip().lower()
    return text.startswith("hf supervisor is not running.")


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
) -> APIRouter:
    """Create an APIRouter with all dashboard route handlers.

    When *registry* is provided, operational endpoints accept an optional
    ``repo`` query parameter to target a specific repo runtime.  When the
    parameter is omitted, the single-repo defaults (closure-captured
    *config*, *state*, *event_bus*, and *get_orchestrator*) are used for
    backward compatibility.
    """
    router = APIRouter()
    hitl_summary_cooldown_seconds = 300

    class RepoAddRequest(BaseModel):
        slug: str | None = None

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
        req: RepoAddRequest | dict[str, Any] | None,
        req_query: str | None,
        slug_query: str | None,
        repo_query: str | None,
    ) -> str:
        """Extract repo slug from supported request shapes."""
        candidates: list[str] = []

        def _push(value: Any) -> None:
            if isinstance(value, str):
                trimmed = value.strip()
                if trimmed:
                    candidates.append(trimmed)

        _push(slug_query)
        _push(repo_query)

        if isinstance(req, RepoAddRequest):
            _push(req.slug)
        elif isinstance(req, dict):
            _push(req.get("slug"))
            _push(req.get("repo"))
            nested = req.get("req")
            if isinstance(nested, dict):
                _push(nested.get("slug"))
                _push(nested.get("repo"))

        parsed_query = _parse_compat_json_object(req_query)
        if parsed_query:
            _push(parsed_query.get("slug"))
            _push(parsed_query.get("repo"))
            nested = parsed_query.get("req")
            if isinstance(nested, dict):
                _push(nested.get("slug"))
                _push(nested.get("repo"))
        else:
            _push(req_query)

        return candidates[0] if candidates else ""

    def _extract_repo_path(
        req: dict[str, Any] | None,
        req_query: str | None,
        path_query: str | None,
        repo_path_query: str | None,
    ) -> str:
        """Extract repo path from supported body/query payload shapes."""
        candidates: list[str] = []

        def _push(value: Any) -> None:
            if isinstance(value, str):
                trimmed = value.strip()
                if trimmed:
                    candidates.append(trimmed)

        if isinstance(req, dict):
            _push(req.get("path"))
            _push(req.get("repo_path"))
            nested = req.get("req")
            if isinstance(nested, dict):
                _push(nested.get("path"))
                _push(nested.get("repo_path"))

        parsed_query = _parse_compat_json_object(req_query)
        if parsed_query:
            _push(parsed_query.get("path"))
            _push(parsed_query.get("repo_path"))
            nested = parsed_query.get("req")
            if isinstance(nested, dict):
                _push(nested.get("path"))
                _push(nested.get("repo_path"))
        else:
            _push(req_query)

        _push(path_query)
        _push(repo_path_query)

        return candidates[0] if candidates else ""

    def _resolve_runtime(
        slug: str | None,
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
        if slug and registry is not None:
            rt: RepoRuntime | None = registry.get(slug)
            if rt is None:
                msg = f"Unknown repo: {slug}"
                raise ValueError(msg)
            return rt.config, rt.state, rt.event_bus, lambda: rt.orchestrator
        return config, state, event_bus, get_orchestrator

    try:
        supervisor_client = importlib.import_module("hf_cli.supervisor_client")
    except ImportError:  # pragma: no cover - env missing CLI
        supervisor_client = None  # type: ignore[assignment]
    try:
        supervisor_manager = importlib.import_module("hf_cli.supervisor_manager")
    except ImportError:  # pragma: no cover - env missing CLI
        supervisor_manager = None  # type: ignore[assignment]
    issue_fetcher = IssueFetcher(config)
    hitl_summarizer = TranscriptSummarizer(config, pr_manager, event_bus, state)
    hitl_summary_inflight: set[int] = set()
    hitl_summary_slots = asyncio.Semaphore(3)

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
        limit: int = 100,
    ) -> list[MetricsSnapshot]:
        """Load metrics snapshots from local disk cache without requiring the orchestrator."""
        cache_file = get_metrics_cache_dir(config) / "snapshots.jsonl"
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
        return {
            "issue_number": issue_number,
            "title": f"Issue #{issue_number}",
            "issue_url": "",
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
        if not timestamp:
            return
        current_first = row.get("first_seen")
        current_last = row.get("last_seen")
        if not isinstance(current_first, str) or timestamp < current_first:
            row["first_seen"] = timestamp
        if not isinstance(current_last, str) or timestamp > current_last:
            row["last_seen"] = timestamp

    async def _enrich_issue_history_with_github(
        entries: dict[int, dict[str, Any]], limit: int = 150
    ) -> None:
        if not entries:
            return

        fetcher = IssueFetcher(config)
        issue_numbers = sorted(entries.keys(), reverse=True)[:limit]
        sem = asyncio.Semaphore(6)

        async def _fetch_and_apply(issue_number: int) -> None:
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
                epic = next((lbl for lbl in labels if "epic" in lbl.lower()), "")
                row["epic"] = epic
            ms_num = _coerce_int(getattr(issue, "milestone_number", None))
            if ms_num > 0 and not row.get("crate_number"):
                row["crate_number"] = ms_num
            for link in parse_task_links(issue.body or ""):
                tid = int(link.target_id)
                row["linked_issues"][tid] = {
                    "target_id": tid,
                    "kind": str(link.kind),
                    "target_url": link.target_url or None,
                }

        await asyncio.gather(*(_fetch_and_apply(num) for num in issue_numbers))

    def _build_hitl_context(issue: Any, *, cause: str, origin: str | None) -> str:
        body = str(getattr(issue, "body", "") or "").strip()
        comments = list(getattr(issue, "comments", []) or [])
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
        lines = [line.strip(" -\t") for line in raw.splitlines() if line.strip()]
        return "\n".join(lines[:8]).strip()

    def _hitl_summary_retry_due(issue_number: int) -> bool:
        failed_at, _ = state.get_hitl_summary_failure(issue_number)
        failed_dt = _parse_iso_or_none(failed_at)
        if failed_dt is None:
            return True
        age = (datetime.now(UTC) - failed_dt).total_seconds()
        return age >= hitl_summary_cooldown_seconds

    async def _compute_hitl_summary(
        issue_number: int, *, cause: str, origin: str | None
    ) -> str | None:
        if (
            not config.transcript_summarization_enabled
            or config.dry_run
            or not config.gh_token
        ):
            return None
        issue = await issue_fetcher.fetch_issue_by_number(issue_number)
        if issue is None:
            state.set_hitl_summary_failure(issue_number, "Issue fetch failed")
            return None
        context = _build_hitl_context(issue, cause=cause, origin=origin)
        generated = await hitl_summarizer.summarize_hitl_context(context)
        if not generated:
            state.set_hitl_summary_failure(issue_number, "Summary model returned empty")
            return None
        summary = _normalise_summary_lines(generated)
        if not summary:
            state.set_hitl_summary_failure(
                issue_number, "Summary normalization produced empty output"
            )
            return None
        state.set_hitl_summary(issue_number, summary)
        state.clear_hitl_summary_failure(issue_number)
        return summary

    async def _warm_hitl_summary(
        issue_number: int, *, cause: str, origin: str | None
    ) -> None:
        if issue_number in hitl_summary_inflight:
            return
        hitl_summary_inflight.add(issue_number)
        try:
            async with hitl_summary_slots:
                await _compute_hitl_summary(issue_number, cause=cause, origin=origin)
        except Exception:
            state.set_hitl_summary_failure(
                issue_number, "Unexpected summary warm error"
            )
            logger.exception(
                "Failed to warm HITL summary for issue #%d",
                issue_number,
            )
        finally:
            hitl_summary_inflight.discard(issue_number)

    @router.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        return _serve_spa_index()

    @router.get("/api/state")
    async def get_state(
        repo: str | None = Query(
            default=None, description="Repo slug to scope the request"
        ),
    ) -> JSONResponse:
        _cfg, _state, _bus, _get_orch = _resolve_runtime(repo)
        return JSONResponse(_state.to_dict())

    @router.get("/api/stats")
    async def get_stats(
        repo: str | None = Query(
            default=None, description="Repo slug to scope the request"
        ),
    ) -> JSONResponse:
        _cfg, _state, _bus, _get_orch = _resolve_runtime(repo)
        data: dict[str, Any] = _state.get_lifetime_stats().model_dump()
        orch = _get_orch()
        if orch:
            data["queue"] = orch.issue_store.get_queue_stats().model_dump()
        return JSONResponse(data)

    @router.get("/api/queue")
    async def get_queue(
        repo: str | None = Query(
            default=None, description="Repo slug to scope the request"
        ),
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
                {"status": "error", "detail": "issue_number and feedback are required"},
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
                data={
                    "issue": issue_number,
                    "cause": feedback,
                    "origin": origin_label,
                },
            )
        )

        return JSONResponse({"status": "ok"})

    @router.get("/api/pipeline")
    async def get_pipeline(
        repo: str | None = Query(
            default=None, description="Repo slug to scope the request"
        ),
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
        repo: str | None = Query(
            default=None, description="Repo slug to scope the request"
        ),
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
    async def get_prs() -> JSONResponse:
        """Fetch all open HydraFlow PRs from GitHub."""
        all_labels = list(
            {
                *config.ready_label,
                *config.review_label,
                *config.fixed_label,
                *config.hitl_label,
                *config.hitl_active_label,
                *config.planner_label,
                *config.improve_label,
            }
        )
        items = await pr_manager.list_open_prs(all_labels)
        return JSONResponse([item.model_dump() for item in items])

    @router.get("/api/epics")
    async def get_epics() -> JSONResponse:
        """Return all tracked epics with enriched sub-issue progress."""
        orch = get_orchestrator()
        if orch is None:
            return JSONResponse([])
        details = await orch._epic_manager.get_all_detail()
        return JSONResponse([d.model_dump() for d in details])

    @router.get("/api/epics/{epic_number}")
    async def get_epic_detail(epic_number: int) -> JSONResponse:
        """Return full detail for a single epic including child issue info."""
        orch = get_orchestrator()
        if orch is None:
            return JSONResponse({"error": "orchestrator not running"}, status_code=503)
        detail = await orch._epic_manager.get_detail(epic_number)
        if detail is None:
            return JSONResponse({"error": "epic not found"}, status_code=404)
        return JSONResponse(detail.model_dump())

    @router.post("/api/epics/{epic_number}/release")
    async def trigger_epic_release(epic_number: int) -> JSONResponse:
        """Trigger async merge sequence and release creation for an epic.

        Returns a job_id. Completion is signalled via the EPIC_RELEASED WebSocket
        event — there is no REST polling endpoint for job status.
        """
        orch = get_orchestrator()
        if orch is None:
            return JSONResponse({"error": "orchestrator not running"}, status_code=503)
        result = await orch._epic_manager.trigger_release(epic_number)
        if "error" in result:
            return JSONResponse(result, status_code=400)
        return JSONResponse(result)

    # --- Crate (milestone) routes ---

    @router.get("/api/crates")
    async def get_crates() -> JSONResponse:
        """List all milestones as crates with enriched progress data."""
        try:
            crates = await pr_manager.list_milestones()
            result = []
            for crate in crates:
                data = crate.model_dump()
                data["total_issues"] = crate.open_issues + crate.closed_issues
                data["progress"] = (
                    round(
                        crate.closed_issues
                        / (crate.open_issues + crate.closed_issues)
                        * 100
                    )
                    if (crate.open_issues + crate.closed_issues) > 0
                    else 0
                )
                result.append(data)
            return JSONResponse(result)
        except RuntimeError as exc:
            logger.error("Failed to fetch crates: %s", exc)
            return JSONResponse({"error": "Failed to fetch crates"}, status_code=500)

    @router.post("/api/crates")
    async def create_crate(body: CrateCreateRequest) -> JSONResponse:
        """Create a new milestone (crate)."""
        if not body.title.strip():
            return JSONResponse({"error": "title is required"}, status_code=400)
        try:
            crate = await pr_manager.create_milestone(
                title=body.title.strip(),
                description=body.description,
                due_on=body.due_on,
            )
            return JSONResponse(crate.model_dump())
        except RuntimeError as exc:
            logger.error("Failed to create crate: %s", exc)
            return JSONResponse({"error": "Failed to create crate"}, status_code=500)

    @router.patch("/api/crates/{crate_number}")
    async def update_crate(crate_number: int, body: CrateUpdateRequest) -> JSONResponse:
        """Update a milestone (crate).

        Only fields present in the request JSON are forwarded.  Sending
        ``"due_on": null`` clears the milestone due date.
        """
        fields = {k: body.model_dump()[k] for k in body.model_fields_set}
        if not fields:
            return JSONResponse({"error": "no fields to update"}, status_code=400)
        try:
            crate = await pr_manager.update_milestone(crate_number, **fields)
            return JSONResponse(crate.model_dump())
        except RuntimeError as exc:
            logger.error("Failed to update crate #%d: %s", crate_number, exc)
            return JSONResponse({"error": "Failed to update crate"}, status_code=500)

    @router.delete("/api/crates/{crate_number}")
    async def delete_crate(crate_number: int) -> JSONResponse:
        """Delete a milestone (crate)."""
        try:
            await pr_manager.delete_milestone(crate_number)
            return JSONResponse({"ok": True})
        except RuntimeError as exc:
            logger.error("Failed to delete crate #%d: %s", crate_number, exc)
            return JSONResponse({"error": "Failed to delete crate"}, status_code=500)

    @router.post("/api/crates/{crate_number}/items")
    async def add_crate_items(
        crate_number: int, body: CrateItemsRequest
    ) -> JSONResponse:
        """Assign issues to a milestone (crate)."""
        try:
            for issue_num in body.issue_numbers:
                await pr_manager.set_issue_milestone(issue_num, crate_number)
            return JSONResponse({"ok": True, "added": len(body.issue_numbers)})
        except RuntimeError as exc:
            logger.error("Failed to add items to crate #%d: %s", crate_number, exc)
            return JSONResponse(
                {"error": "Failed to add items to crate"}, status_code=500
            )

    @router.delete("/api/crates/{crate_number}/items")
    async def remove_crate_items(
        crate_number: int, body: CrateItemsRequest
    ) -> JSONResponse:
        """Remove issues from a milestone (crate) by clearing their milestone.

        Only clears the milestone if the issue is currently assigned to the
        specified crate (milestone), avoiding unintended removal from a
        different milestone.
        """
        try:
            current_issues = await pr_manager.list_milestone_issues(crate_number)
            current_nums = {i.get("number") for i in current_issues}
            removed = 0
            for issue_num in body.issue_numbers:
                if issue_num in current_nums:
                    await pr_manager.set_issue_milestone(issue_num, None)
                    removed += 1
            return JSONResponse({"ok": True, "removed": removed})
        except RuntimeError as exc:
            logger.error("Failed to remove items from crate #%d: %s", crate_number, exc)
            return JSONResponse(
                {"error": "Failed to remove items from crate"}, status_code=500
            )

    @router.get("/api/crates/active")
    async def get_active_crate() -> JSONResponse:
        """Return the active crate number, title, progress, and auto_crate flag."""
        orch = get_orchestrator()
        active_number = state.get_active_crate_number()
        result: dict[str, Any] = {
            "crate_number": active_number,
            "title": None,
            "progress": 0,
            "open_issues": 0,
            "closed_issues": 0,
            "total_issues": 0,
            "auto_crate": config.auto_crate,
        }
        if active_number is not None and orch is not None:
            try:
                crates = await pr_manager.list_milestones(state="all")
                active = next((c for c in crates if c.number == active_number), None)
                if active:
                    total = active.open_issues + active.closed_issues
                    result["title"] = active.title
                    result["open_issues"] = active.open_issues
                    result["closed_issues"] = active.closed_issues
                    result["total_issues"] = total
                    result["progress"] = (
                        round(active.closed_issues / total * 100) if total > 0 else 0
                    )
            except Exception:
                logger.warning("Failed to enrich active crate details", exc_info=True)
        return JSONResponse(result)

    @router.post("/api/crates/active")
    async def set_active_crate(body: dict[str, Any]) -> JSONResponse:
        """Set the active crate. Body: ``{"crate_number": N}`` or ``{"crate_number": null}``."""
        crate_number = body.get("crate_number")
        if crate_number is not None and not isinstance(crate_number, int):
            return JSONResponse(
                {
                    "status": "error",
                    "detail": "crate_number must be an integer or null",
                },
                status_code=400,
            )
        orch = get_orchestrator()
        if orch is None:
            # Fallback: update state directly when orchestrator isn't running
            state.set_active_crate_number(crate_number)
            return JSONResponse({"status": "ok", "crate_number": crate_number})
        if crate_number is not None:
            await orch.crate_manager.activate_crate(crate_number)
        else:
            state.set_active_crate_number(None)
        return JSONResponse({"status": "ok", "crate_number": crate_number})

    @router.post("/api/crates/advance")
    async def advance_crate() -> JSONResponse:
        """Advance past the current active crate to the next open one.

        Calls ``check_and_advance()`` which completes the active crate
        and activates the next milestone with open issues.  If the
        current crate still has open issues, it is force-cleared first
        so the pipeline moves forward regardless.
        """
        orch = get_orchestrator()
        cm = orch.crate_manager if orch is not None else None
        if cm is None:
            state.set_active_crate_number(None)
            return JSONResponse({"status": "ok", "previous": None, "next": None})
        previous = cm.active_crate_number
        # Force-clear first so check_and_advance will see no active
        # crate (if it still has open issues, check_and_advance would
        # be a no-op otherwise).
        state.set_active_crate_number(None)
        # Now find the next open crate
        try:
            crates = await pr_manager.list_milestones(state="open")
            candidates = sorted(
                (c for c in crates if c.open_issues > 0 and c.number != previous),
                key=lambda c: c.number,
            )
            if candidates:
                await cm.activate_crate(candidates[0].number)
                return JSONResponse(
                    {
                        "status": "ok",
                        "previous": previous,
                        "next": candidates[0].number,
                    }
                )
        except Exception:
            logger.warning("Failed to find next crate during advance", exc_info=True)
        return JSONResponse({"status": "ok", "previous": previous, "next": None})

    @router.get("/api/hitl")
    async def get_hitl(
        repo: str | None = Query(
            default=None, description="Repo slug to scope the request"
        ),
    ) -> JSONResponse:
        """Fetch issues/PRs labeled for human-in-the-loop (stuck on CI)."""
        _cfg, _state, _bus, _get_orch = _resolve_runtime(repo)
        hitl_labels = list(dict.fromkeys([*_cfg.hitl_label, *_cfg.hitl_active_label]))
        items = await pr_manager.list_hitl_items(hitl_labels)
        orch = _get_orch()
        enriched = []
        for item in items:
            data = item.model_dump()
            if orch:
                data["status"] = orch.get_hitl_status(item.issue)
            cause = state.get_hitl_cause(item.issue)
            origin = state.get_hitl_origin(item.issue)
            if not cause and origin:
                if origin in config.improve_label:
                    cause = "Self-improvement proposal"
                elif origin in config.review_label:
                    cause = "Review escalation"
                elif origin in config.find_label:
                    cause = "Triage escalation"
                else:
                    cause = "Escalation (reason not recorded)"
            if cause:
                data["cause"] = cause
            if origin and origin in config.improve_label:
                data["isMemorySuggestion"] = True
            # Flag items held for issue type review
            if cause and (
                "epic detected" in cause.lower()
                or "bug report detected" in cause.lower()
            ):
                data["issueTypeReview"] = True
            cached_summary = state.get_hitl_summary(item.issue)
            data["llmSummary"] = cached_summary or ""
            data["llmSummaryUpdatedAt"] = state.get_hitl_summary_updated_at(item.issue)
            visual_ev = state.get_hitl_visual_evidence(item.issue)
            if visual_ev:
                data["visualEvidence"] = visual_ev.model_dump()
            if (
                not cached_summary
                and config.transcript_summarization_enabled
                and not config.dry_run
                and bool(config.gh_token)
                and _hitl_summary_retry_due(item.issue)
            ):
                asyncio.create_task(
                    _warm_hitl_summary(item.issue, cause=cause or "", origin=origin)
                )
            enriched.append(data)

        # When memory auto-approve is on, filter out memory suggestions that
        # were queued before the setting was enabled.
        if config.memory_auto_approve:
            enriched = [d for d in enriched if not d.get("isMemorySuggestion")]

        return JSONResponse(enriched)

    @router.get("/api/hitl/{issue_number}/summary")
    async def get_hitl_summary(issue_number: int) -> JSONResponse:
        """Return cached HITL summary, generating one if missing."""
        cached = state.get_hitl_summary(issue_number)
        if cached:
            return JSONResponse(
                {
                    "issue": issue_number,
                    "summary": cached,
                    "updated_at": state.get_hitl_summary_updated_at(issue_number),
                    "cached": True,
                }
            )

        cause = state.get_hitl_cause(issue_number) or ""
        origin = state.get_hitl_origin(issue_number)
        summary = await _compute_hitl_summary(issue_number, cause=cause, origin=origin)
        if summary:
            return JSONResponse(
                {
                    "issue": issue_number,
                    "summary": summary,
                    "updated_at": state.get_hitl_summary_updated_at(issue_number),
                    "cached": False,
                }
            )
        return JSONResponse(
            {"issue": issue_number, "summary": "", "updated_at": None, "cached": False}
        )

    @router.post("/api/hitl/{issue_number}/correct")
    async def hitl_correct(issue_number: int, body: dict[str, Any]) -> JSONResponse:
        """Submit a correction for a HITL issue to guide retry."""
        orch = get_orchestrator()
        if not orch:
            return JSONResponse({"status": "no orchestrator"}, status_code=400)
        correction = body.get("correction") or ""
        if not correction.strip():
            return JSONResponse(
                {"status": "error", "detail": "Correction text must not be empty"},
                status_code=400,
            )
        orch.submit_hitl_correction(issue_number, correction)

        # Swap labels for immediate dashboard feedback
        await pr_manager.swap_pipeline_labels(issue_number, config.hitl_active_label[0])

        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.HITL_UPDATE,
                data={
                    "issue": issue_number,
                    "status": "processing",
                    "action": "correct",
                },
            )
        )
        return JSONResponse({"status": "ok"})

    @router.post("/api/hitl/{issue_number}/skip")
    async def hitl_skip(issue_number: int, body: HITLSkipRequest) -> JSONResponse:
        """Remove a HITL issue from the queue without action (reason required)."""
        orch = get_orchestrator()
        if not orch:
            return JSONResponse({"status": "no orchestrator"}, status_code=400)

        # Read origin before clearing state
        origin = state.get_hitl_origin(issue_number)

        orch.skip_hitl_issue(issue_number)
        state.remove_hitl_origin(issue_number)
        state.remove_hitl_cause(issue_number)
        state.remove_hitl_summary(issue_number)
        state.record_outcome(
            issue_number,
            IssueOutcomeType.HITL_SKIPPED,
            reason=body.reason,
            phase="hitl",
        )

        # If this was an improve issue, transition to triage for implementation
        if origin and origin in config.improve_label and config.find_label:
            await pr_manager.swap_pipeline_labels(issue_number, config.find_label[0])
        else:
            # Just remove all pipeline labels
            for lbl in config.all_pipeline_labels:
                await pr_manager.remove_label(issue_number, lbl)

        # Post reason as comment (best-effort, after skip succeeds)
        try:
            await pr_manager.post_comment(
                issue_number,
                f"**HITL Skip** — Operator skipped this issue.\n\n"
                f"**Reason:** {body.reason}\n\n"
                f"---\n*HydraFlow Dashboard*",
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "Failed to post skip comment for issue #%d",
                issue_number,
                exc_info=True,
            )

        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.HITL_UPDATE,
                data={
                    "issue": issue_number,
                    "status": "resolved",
                    "action": "skip",
                    "reason": body.reason,
                },
            )
        )
        return JSONResponse({"status": "ok"})

    @router.post("/api/hitl/{issue_number}/close")
    async def hitl_close(issue_number: int, body: HITLCloseRequest) -> JSONResponse:
        """Close a HITL issue on GitHub (reason required)."""
        orch = get_orchestrator()
        if not orch:
            return JSONResponse({"status": "no orchestrator"}, status_code=400)

        orch.skip_hitl_issue(issue_number)
        state.remove_hitl_origin(issue_number)
        state.remove_hitl_cause(issue_number)
        state.remove_hitl_summary(issue_number)
        state.record_outcome(
            issue_number,
            IssueOutcomeType.HITL_CLOSED,
            reason=body.reason,
            phase="hitl",
        )
        await pr_manager.close_issue(issue_number)

        # Post reason as comment (best-effort, after close succeeds)
        try:
            await pr_manager.post_comment(
                issue_number,
                f"**HITL Close** — Operator closed this issue.\n\n"
                f"**Reason:** {body.reason}\n\n"
                f"---\n*HydraFlow Dashboard*",
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "Failed to post close comment for issue #%d",
                issue_number,
                exc_info=True,
            )

        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.HITL_UPDATE,
                data={
                    "issue": issue_number,
                    "status": "resolved",
                    "action": "close",
                    "reason": body.reason,
                },
            )
        )
        return JSONResponse({"status": "ok"})

    @router.post("/api/hitl/{issue_number}/approve-memory")
    async def hitl_approve_memory(issue_number: int) -> JSONResponse:
        """Approve a HITL item as a memory suggestion, relabeling for sync."""
        # Remove all pipeline labels and add memory label
        for lbl in config.all_pipeline_labels:
            await pr_manager.remove_label(issue_number, lbl)
        await pr_manager.add_labels(issue_number, config.memory_label)
        orch = get_orchestrator()
        if orch:
            orch.skip_hitl_issue(issue_number)
        state.remove_hitl_origin(issue_number)
        state.remove_hitl_cause(issue_number)
        state.remove_hitl_summary(issue_number)
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.HITL_UPDATE,
                data={
                    "issue": issue_number,
                    "status": "resolved",
                    "action": "approved_as_memory",
                },
            )
        )
        return JSONResponse({"status": "ok"})

    @router.post("/api/hitl/{issue_number}/approve-process")
    async def hitl_approve_process(issue_number: int) -> JSONResponse:
        """Approve a HITL item held for issue type review — send to planning."""
        orch = get_orchestrator()
        if not orch:
            return JSONResponse({"status": "no orchestrator"}, status_code=400)

        # Issue was already triaged as ready — send directly to planning
        await pr_manager.swap_pipeline_labels(issue_number, config.planner_label[0])

        # Clear HITL state after label swap succeeds
        orch.skip_hitl_issue(issue_number)
        state.remove_hitl_origin(issue_number)
        state.remove_hitl_cause(issue_number)
        state.remove_hitl_summary(issue_number)
        state.record_outcome(
            issue_number,
            IssueOutcomeType.HITL_APPROVED,
            reason="Operator approved issue type for processing",
            phase="hitl",
        )

        try:
            await pr_manager.post_comment(
                issue_number,
                "**Approved for processing** — Operator approved this issue.\n\n"
                "---\n*HydraFlow Dashboard*",
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "Failed to post approval comment for #%d",
                issue_number,
                exc_info=True,
            )

        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.HITL_UPDATE,
                data={
                    "issue": issue_number,
                    "status": "resolved",
                    "action": "approved_for_processing",
                },
            )
        )
        return JSONResponse({"status": "ok"})

    @router.get("/api/human-input")
    async def get_human_input_requests() -> JSONResponse:
        orch = get_orchestrator()
        if orch:
            return JSONResponse(orch.human_input_requests)
        return JSONResponse({})

    @router.post("/api/human-input/{issue_number}")
    async def provide_human_input(
        issue_number: int, body: dict[str, Any]
    ) -> JSONResponse:
        orch = get_orchestrator()
        if orch:
            answer = body.get("answer", "")
            orch.provide_human_input(issue_number, answer)
            return JSONResponse({"status": "ok"})
        return JSONResponse({"status": "no orchestrator"}, status_code=400)

    @router.post("/api/control/start")
    async def start_orchestrator() -> JSONResponse:
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
                data={"status": "running", "reset": True},
            )
        )
        return JSONResponse({"status": "started"})

    @router.post("/api/control/stop")
    async def stop_orchestrator() -> JSONResponse:
        orch = get_orchestrator()
        if not orch or not orch.running:
            return JSONResponse({"error": "not running"}, status_code=400)
        await orch.request_stop()
        return JSONResponse({"status": "stopping"})

    @router.get("/api/control/status")
    async def get_control_status(
        repo: str | None = Query(
            default=None, description="Repo slug to scope the request"
        ),
    ) -> JSONResponse:
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
        response = ControlStatusResponse(
            status=status,
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
        "auto_process_epics",
        "auto_process_bug_reports",
        "worktree_base",
        "auto_crate",
    }

    @router.patch("/api/control/config")
    async def patch_config(body: dict[str, Any]) -> JSONResponse:
        """Update runtime config fields. Pass ``persist: true`` to save to disk."""
        persist = body.pop("persist", False)
        updates: dict[str, Any] = {}

        for key, value in body.items():
            if key not in _MUTABLE_FIELDS:
                continue
            if not hasattr(config, key):
                continue
            updates[key] = value

        if not updates:
            return JSONResponse({"status": "ok", "updated": {}})

        # Validate updates through Pydantic field constraints
        test_values = config.model_dump()
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
            object.__setattr__(config, key, validated_value)
            applied[key] = validated_value

        if persist and applied:
            save_config_file(config.config_file, applied)

        return JSONResponse({"status": "ok", "updated": applied})

    # Known workers with human-friendly labels (pipeline loops + background)
    _bg_worker_defs = [
        (
            "triage",
            "Triage",
            "Classifies freshly discovered issues and routes them into the pipeline.",
        ),
        (
            "plan",
            "Plan",
            "Builds implementation plans for triaged issues that are ready to execute.",
        ),
        (
            "implement",
            "Implement",
            "Runs coding agents to implement planned issues and open pull requests.",
        ),
        (
            "review",
            "Review",
            "Reviews PRs, applies fixes, and merges approved work when checks pass.",
        ),
        (
            "memory_sync",
            "Memory Manager",
            "Ingests memory and transcript issues into durable learnings and proposals.",
        ),
        (
            "retrospective",
            "Retrospective",
            "Captures post-merge outcomes and identifies recurring delivery patterns.",
        ),
        (
            "metrics",
            "Metrics",
            "Refreshes operational metrics and dashboards from state and GitHub data.",
        ),
        (
            "review_insights",
            "Review Insights",
            "Aggregates recurring review feedback into improvement opportunities.",
        ),
        (
            "pipeline_poller",
            "Pipeline Poller",
            "Refreshes live pipeline snapshots for dashboard queue/status rendering.",
        ),
        (
            "pr_unsticker",
            "PR Unsticker",
            "Requeues stalled HITL PRs by validating requirements and reopening flow.",
        ),
        (
            "report_issue",
            "Report Issue",
            "Processes queued bug reports into GitHub issues via the configured agent.",
        ),
        (
            "adr_reviewer",
            "ADR Reviewer",
            "Reviews proposed ADRs via a 3-judge council and routes to accept, reject, or escalate.",
        ),
    ]

    # Workers that have independent configurable intervals
    _INTERVAL_WORKERS = {
        "memory_sync",
        "metrics",
        "pr_unsticker",
        "pipeline_poller",
        "report_issue",
    }
    # Pipeline loops share poll_interval (read-only display)
    _PIPELINE_WORKERS = {"triage", "plan", "implement", "review"}
    _WORKER_SOURCE_ALIASES: dict[str, tuple[str, ...]] = {
        "plan": ("planner",),
        "implement": ("agent",),
        "review": ("reviewer", "merge_conflict", "fresh_rebuild"),
    }

    def _build_system_worker_inference_stats() -> dict[str, dict[str, int]]:
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
    async def get_system_workers() -> JSONResponse:
        """Return last known status of each background worker."""
        orch = get_orchestrator()
        bg_states = orch.get_bg_worker_states() if orch else {}
        persisted_states: dict[str, BackgroundWorkerState] = {}
        if not orch:
            try:
                persisted_states = state.get_bg_worker_states()
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
                    interval = config.memory_sync_interval
                elif name == "metrics":
                    interval = config.metrics_sync_interval
                elif name == "pr_unsticker":
                    interval = config.pr_unstick_interval
                elif name == "pipeline_poller":
                    interval = 5
            elif name in _PIPELINE_WORKERS:
                interval = config.poll_interval

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

    # Interval bounds per editable worker.
    # memory_sync, metrics, pr_unsticker bounds must match config.py Field constraints.
    # pipeline_poller has no config Field; 5s minimum matches the hardcoded default.
    _INTERVAL_BOUNDS = {
        "memory_sync": (10, 14400),
        "metrics": (30, 14400),
        "pr_unsticker": (60, 86400),
        "pipeline_poller": (5, 14400),
        "adr_reviewer": (3600, 604800),
    }

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

    @router.get("/api/issues/outcomes")
    async def get_issue_outcomes() -> JSONResponse:
        """Return all recorded issue outcomes."""
        outcomes = state.get_all_outcomes()
        return JSONResponse({k: v.model_dump() for k, v in outcomes.items()})

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
        import json

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
        import json

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
        logger.debug("History cache warm-up failed", exc_info=True)

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
            import copy

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
                timestamp = record.get("timestamp")
                _touch_issue_timestamps(
                    row, timestamp if isinstance(timestamp, str) else None
                )
                session_id = str(record.get("session_id", "")).strip()
                if session_id:
                    row["session_ids"].add(session_id)
                source = str(record.get("source", "")).strip()
                if source:
                    row["source_calls"][source] = row["source_calls"].get(source, 0) + 1
                model = str(record.get("model", "")).strip()
                if model:
                    row["model_calls"][model] = row["model_calls"].get(model, 0) + 1
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
                _touch_issue_timestamps(
                    row, timestamp if isinstance(timestamp, str) else None
                )

                session_id = str(record.get("session_id", "")).strip()
                if session_id:
                    row["session_ids"].add(session_id)

                source = str(record.get("source", "")).strip()
                if source:
                    row["source_calls"][source] = row["source_calls"].get(source, 0) + 1

                model = str(record.get("model", "")).strip()
                if model:
                    row["model_calls"][model] = row["model_calls"].get(model, 0) + 1

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

        if not cache_hit:
            for event in all_events:
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
                            if s and "epic" in s.lower():
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

            # Store in cache if this was an unfiltered aggregation.
            if use_unfiltered:
                import copy

                _history_cache["issue_rows"] = copy.deepcopy(issue_rows)
                _history_cache["pr_to_issue"] = dict(pr_to_issue)
                _history_cache["event_count"] = event_count
                _history_cache["telemetry_mtime"] = telem_mtime
                _history_cache_ts[0] = now
                _save_history_cache()

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
                    )
                    for pr_data in prs_map.values()
                    if isinstance(pr_data, dict)
                    and _coerce_int(pr_data.get("number")) > 0
                ),
                key=lambda p: p.number,
                reverse=True,
            )

            items.append(
                IssueHistoryEntry(
                    issue_number=issue_number,
                    title=title,
                    issue_url=str(row.get("issue_url", "")),
                    status=row_status,
                    epic=str(row.get("epic", "")),
                    crate_number=row.get("crate_number"),
                    crate_title=str(row.get("crate_title", "")),
                    linked_issues=linked_issues,
                    prs=pr_rows,
                    session_ids=sorted(
                        str(s) for s in row.get("session_ids", set()) if str(s)
                    ),
                    source_calls=dict(sorted(row.get("source_calls", {}).items())),
                    model_calls=dict(sorted(row.get("model_calls", {}).items())),
                    inference={
                        k: _coerce_int(v) for k, v in row.get("inference", {}).items()
                    },
                    first_seen=row.get("first_seen"),
                    last_seen=row.get("last_seen"),
                    outcome=state.get_outcome(issue_number),
                )
            )

        # Keep API fast by enriching only visible rows and only when needed.
        # Skip issues already enriched in a previous request.
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
            # Update cached issue_rows with enrichment data so future cache
            # hits include titles/epics/linked_issues from GitHub.
            if use_unfiltered and _history_cache["issue_rows"] is not None:
                import copy

                _history_cache["issue_rows"] = copy.deepcopy(issue_rows)
                _save_history_cache()
            items = []
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
                        )
                        for pr_data in prs_map.values()
                        if isinstance(pr_data, dict)
                        and _coerce_int(pr_data.get("number")) > 0
                    ),
                    key=lambda p: p.number,
                    reverse=True,
                )
                items.append(
                    IssueHistoryEntry(
                        issue_number=issue_number,
                        title=title,
                        issue_url=str(row.get("issue_url", "")),
                        status=row_status,
                        epic=str(row.get("epic", "")),
                        crate_number=row.get("crate_number"),
                        crate_title=str(row.get("crate_title", "")),
                        linked_issues=linked_issues,
                        prs=pr_rows,
                        session_ids=sorted(
                            str(s) for s in row.get("session_ids", set()) if str(s)
                        ),
                        source_calls=dict(sorted(row.get("source_calls", {}).items())),
                        model_calls=dict(sorted(row.get("model_calls", {}).items())),
                        inference={
                            k: _coerce_int(v)
                            for k, v in row.get("inference", {}).items()
                        },
                        first_seen=row.get("first_seen"),
                        last_seen=row.get("last_seen"),
                        outcome=state.get_outcome(issue_number),
                    )
                )

        items.sort(
            key=lambda item: (
                item.last_seen or "",
                item.inference.get("total_tokens", 0),
                item.issue_number,
            ),
            reverse=True,
        )
        items = items[:clamped_limit]

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
                    import copy

                    _history_cache["issue_rows"] = copy.deepcopy(issue_rows)
                    _save_history_cache()
            except Exception:
                logger.debug("Failed to fetch milestones for crate titles")

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

    @router.get("/api/metrics")
    async def get_metrics() -> JSONResponse:
        """Return lifetime stats, derived rates, time-to-merge, and thresholds."""
        lifetime = state.get_lifetime_stats()
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
        time_to_merge = state.get_merge_duration_stats()
        thresholds = state.check_thresholds(
            config.quality_fix_rate_threshold,
            config.approval_rate_threshold,
            config.hitl_rate_threshold,
        )
        retries = state.get_retries_summary()
        if retries:
            rates["retries_per_stage"] = sum(retries.values())

        telemetry = PromptTelemetry(config)
        inference_lifetime = telemetry.get_lifetime_totals()
        orch = get_orchestrator()
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
    async def get_github_metrics() -> JSONResponse:
        """Query GitHub for issue/PR counts by label state."""
        counts = await pr_manager.get_label_counts(config)
        return JSONResponse(counts)

    @router.get("/api/metrics/history")
    async def get_metrics_history() -> JSONResponse:
        """Historical snapshots from the metrics issue + current in-memory snapshot.

        Falls back to local disk cache when the orchestrator is not running.
        """
        orch = get_orchestrator()
        if orch is None:
            # Serve from local cache without requiring the orchestrator
            snapshots = _load_local_metrics_cache()
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
        builder = TimelineBuilder(event_bus)
        timelines = builder.build_all()
        return JSONResponse([t.model_dump() for t in timelines])

    @router.get("/api/timeline/issue/{issue_num}")
    async def get_timeline_issue(issue_num: int) -> JSONResponse:
        builder = TimelineBuilder(event_bus)
        timeline = builder.build_for_issue(issue_num)
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
        if rt.running:
            await rt.stop()
        registry.remove(slug)
        return JSONResponse({"status": "removed", "slug": slug})

    # --- Multi-repo supervisor endpoints ---

    async def _call_supervisor(func: Callable, *args, **kwargs) -> Any:
        if supervisor_client is None:
            raise RuntimeError("hf supervisor client unavailable in this environment")
        return await asyncio.to_thread(func, *args, **kwargs)

    @router.get("/api/repos")
    async def list_supervised_repos() -> JSONResponse:
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
        req: RepoAddRequest | dict[str, Any] | None = Body(default=None),
        req_query: str | None = Query(default=None, alias="req"),
        slug: str | None = Query(default=None),
        repo: str | None = Query(default=None),
    ) -> JSONResponse:
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
        # Register with supervisor
        if supervisor_client is None:
            return JSONResponse(
                {
                    "error": (
                        "hf supervisor is not running. "
                        "Run `hf run` inside a repo to start it."
                    )
                },
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
                                {
                                    "error": (
                                        "hf supervisor is not running. "
                                        "Run `hf run` inside a repo to start it."
                                    )
                                },
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
                        {
                            "error": (
                                "hf supervisor is not running. "
                                "Run `hf run` inside a repo to start it."
                            )
                        },
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
    async def get_sessions(repo: str | None = None) -> JSONResponse:
        """Return session logs, optionally filtered by repo."""
        sessions = state.load_sessions(repo=repo)
        return JSONResponse([s.model_dump() for s in sessions])

    @router.get("/api/sessions/{session_id}")
    async def get_session_detail(session_id: str) -> JSONResponse:
        """Return a single session by ID with associated events."""
        session = state.get_session(session_id)
        if session is None:
            return JSONResponse({"error": "Session not found"}, status_code=404)
        # Include events tagged with this session_id
        all_events = event_bus.get_history()
        session_events = [
            e.model_dump() for e in all_events if e.session_id == session_id
        ]
        data = session.model_dump()
        data["events"] = session_events
        return JSONResponse(data)

    @router.delete("/api/sessions/{session_id}")
    async def delete_session(session_id: str) -> JSONResponse:
        """Delete a session by ID. Returns 400 if active, 404 if not found."""
        try:
            deleted = state.delete_session(session_id)
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
        await ws.accept()

        # Snapshot history BEFORE subscribing to avoid duplicates.
        # Events published between snapshot and subscribe are picked
        # up by the live queue, never sent twice.
        history = event_bus.get_history()

        async with event_bus.subscription() as queue:
            # Send history on connect
            for event in history:
                try:
                    await ws.send_text(event.model_dump_json())
                except Exception as exc:
                    logger.warning(
                        "WebSocket error during history replay: %s",
                        exc.__class__.__name__,
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
                logger.warning(
                    "WebSocket error during live streaming: %s",
                    exc.__class__.__name__,
                )

    # SPA catch-all: serve index.html for any path not matched above.
    # This must be registered LAST so it doesn't shadow API/WS routes.
    @router.get("/{path:path}", response_model=None)
    async def spa_catchall(path: str) -> Response:
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
