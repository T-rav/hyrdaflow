"""/api/wiki/* endpoints — read + admin-enqueue routes for the git-backed repo wiki.

Phase 5 of ``docs/git-backed-wiki-design.md``.  Read endpoints traverse
the tracked ``repo_wiki/`` directory under ``config.repo_root`` (the
per-entry layout landed by Phase 2); admin endpoints enqueue
``MaintenanceTask`` entries that ``RepoWikiLoop`` drains on its next
tick.  Nothing here mutates the wiki directly — every write goes
through the single-track commit path that emits the
``chore(wiki): maintenance`` PR.

Follows the ``_memory_routes.py`` pattern: ``register(router, ctx)``
attaches ``@router.<method>`` handlers that close over ``ctx`` for
shared state (config, wiki queue, wiki loop).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException
from pydantic import BaseModel, Field

from wiki_maint_queue import MaintenanceTask

if TYPE_CHECKING:
    from fastapi import APIRouter

    from dashboard_routes._routes import RouteContext

logger = logging.getLogger("hydraflow.dashboard.wiki")

_TOPICS: tuple[str, ...] = (
    "architecture",
    "patterns",
    "gotchas",
    "testing",
    "dependencies",
)

# Filename pattern: ``{id:04d}-issue-{N|unknown}-{slug}.md``.  Parses both
# the id and the issue tag so the API can filter by either.
_ENTRY_FILENAME_RE = re.compile(r"^(\d+)-issue-(\S+?)-(.+)\.md$")


class ForceCompilePayload(BaseModel):
    owner: str = Field(min_length=1)
    repo: str = Field(min_length=1)
    topic: str = Field(min_length=1)


class MarkStalePayload(BaseModel):
    owner: str = Field(min_length=1)
    repo: str = Field(min_length=1)
    entry_id: str = Field(min_length=1)
    reason: str = Field(default="")


class RebuildIndexPayload(BaseModel):
    owner: str = Field(min_length=1)
    repo: str = Field(min_length=1)


def _wiki_loop(ctx: RouteContext):
    """Return the ``RepoWikiLoop`` from the running orchestrator, or None.

    Services live inside ``ServiceRegistry`` on the orchestrator, which
    is constructed after the dashboard.  Looking them up lazily keeps
    the route module decoupled from ``service_registry`` import order.
    """
    orch = ctx.get_orchestrator()
    if orch is None:
        return None
    svc = getattr(orch, "_svc", None)
    if svc is None:
        return None
    return getattr(svc, "repo_wiki_loop", None)


def _maintenance_queue(ctx: RouteContext):
    """Return the loop's ``MaintenanceQueue``, or None if loop is down."""
    loop = _wiki_loop(ctx)
    if loop is None:
        return None
    return getattr(loop, "_queue", None)


def _wiki_root(ctx: RouteContext) -> Path:
    """Absolute path to the tracked ``repo_wiki/`` directory.

    Reads from ``config.repo_root / config.repo_wiki_path`` so the API
    sees what the migration script and phase runners wrote, not the
    legacy ``.hydraflow/repo_wiki/`` layout.
    """
    return (ctx.config.repo_root / ctx.config.repo_wiki_path).resolve()


def _repo_dir(ctx: RouteContext, owner: str, repo: str) -> Path | None:
    """Return the tracked dir for ``{owner}/{repo}`` or None when absent.

    Prevents path traversal via ``..`` or absolute paths in owner/repo.
    """
    if "/" in owner or "/" in repo or ".." in owner or ".." in repo:
        return None
    candidate = _wiki_root(ctx) / owner / repo
    try:
        candidate_resolved = candidate.resolve()
    except OSError:
        return None
    root = _wiki_root(ctx)
    if not str(candidate_resolved).startswith(str(root)):
        return None
    if not candidate_resolved.is_dir():
        return None
    return candidate_resolved


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split a markdown file into (frontmatter-dict, body-str).

    Tolerates missing frontmatter: returns ``({}, text)`` so downstream
    callers still get the full text rendered as body.
    """
    if not text.startswith("---\n"):
        return {}, text
    try:
        end = text.index("\n---\n", 4)
    except ValueError:
        return {}, text
    block = text[4:end]
    body = text[end + len("\n---\n") :]
    frontmatter: dict[str, str] = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        frontmatter[key.strip()] = value.strip()
    return frontmatter, body


def _entry_summary_from_path(
    *, topic: str, path: Path, owner: str, repo: str
) -> dict[str, Any] | None:
    """Cheap-to-compute summary (frontmatter only, no body) for list views."""
    match = _ENTRY_FILENAME_RE.match(path.name)
    if match is None:
        return None
    entry_id = match.group(1)
    issue_tag = match.group(2)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    frontmatter, _ = _parse_frontmatter(text)
    return {
        "id": entry_id,
        "issue": issue_tag,
        "topic": topic,
        "owner": owner,
        "repo": repo,
        "filename": path.name,
        "status": frontmatter.get("status", "active"),
        "source_phase": frontmatter.get("source_phase", ""),
        "source_issue": frontmatter.get("source_issue", issue_tag),
        "created_at": frontmatter.get("created_at", ""),
    }


def _match_filters(
    summary: dict[str, Any],
    *,
    status: str | None,
    q: str | None,
    body_fetcher,
) -> bool:
    """Apply status + substring filters.  ``body_fetcher`` is a 0-arg
    callable that returns the markdown body (lazily — free-text ``q``
    search loads body text only when status filter is satisfied)."""
    if status and summary["status"] != status:
        return False
    if q:
        needle = q.lower()
        if needle in summary["filename"].lower():
            return True
        if needle in summary.get("source_phase", "").lower():
            return True
        try:
            return needle in body_fetcher().lower()
        except OSError:
            return False
    return True


def register(router: APIRouter, ctx: RouteContext) -> None:
    """Attach /api/wiki/* handlers to ``router``.

    All reads go through the tracked ``repo_wiki/`` layout under
    ``config.repo_root``.  All writes happen via ``MaintenanceQueue``
    drains inside ``RepoWikiLoop`` — the admin endpoints here never
    mutate the wiki directly.
    """

    @router.get("/api/wiki/repos")
    def list_wiki_repos() -> list[dict[str, str]]:
        root = _wiki_root(ctx)
        if not root.is_dir():
            return []
        out: list[dict[str, str]] = []
        for owner_dir in sorted(root.iterdir()):
            if not owner_dir.is_dir():
                continue
            for repo_dir in sorted(owner_dir.iterdir()):
                if not repo_dir.is_dir():
                    continue
                if (repo_dir / "index.md").exists() or (
                    repo_dir / "index.json"
                ).exists():
                    out.append({"owner": owner_dir.name, "repo": repo_dir.name})
        return out

    @router.get("/api/wiki/repos/{owner}/{repo}/entries")
    def list_wiki_entries(
        owner: str,
        repo: str,
        topic: str | None = None,
        status: str | None = None,
        q: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        repo_dir = _repo_dir(ctx, owner, repo)
        if repo_dir is None:
            return []
        topics: tuple[str, ...] = (topic,) if topic else _TOPICS
        out: list[dict[str, Any]] = []
        for t in topics:
            topic_dir = repo_dir / t
            if not topic_dir.is_dir():
                continue
            for entry_path in sorted(topic_dir.glob("*.md")):
                summary = _entry_summary_from_path(
                    topic=t, path=entry_path, owner=owner, repo=repo
                )
                if summary is None:
                    continue
                if not _match_filters(
                    summary,
                    status=status,
                    q=q,
                    body_fetcher=lambda p=entry_path: p.read_text(encoding="utf-8"),
                ):
                    continue
                out.append(summary)
        offset = max(offset, 0)
        limit = max(limit, 0)
        return out[offset : offset + limit]

    @router.get("/api/wiki/repos/{owner}/{repo}/entries/{entry_id}")
    def get_wiki_entry(owner: str, repo: str, entry_id: str) -> dict[str, Any]:
        repo_dir = _repo_dir(ctx, owner, repo)
        if repo_dir is None:
            raise HTTPException(status_code=404, detail="repo not found")
        if not re.fullmatch(r"\d{1,6}", entry_id):
            raise HTTPException(status_code=400, detail="invalid entry id")
        prefix = f"{int(entry_id):04d}-"
        for topic in _TOPICS:
            topic_dir = repo_dir / topic
            if not topic_dir.is_dir():
                continue
            for match in topic_dir.glob(f"{prefix}*.md"):
                text = match.read_text(encoding="utf-8")
                frontmatter, body = _parse_frontmatter(text)
                return {
                    "id": entry_id,
                    "topic": topic,
                    "owner": owner,
                    "repo": repo,
                    "filename": match.name,
                    "frontmatter": frontmatter,
                    "body": body,
                }
        raise HTTPException(status_code=404, detail="entry not found")

    @router.get("/api/wiki/repos/{owner}/{repo}/log")
    def get_wiki_log(
        owner: str,
        repo: str,
        issue: int | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        repo_dir = _repo_dir(ctx, owner, repo)
        if repo_dir is None:
            return []
        log_dir = repo_dir / "log"
        if not log_dir.is_dir():
            return []
        if issue is not None:
            candidates = [log_dir / f"{issue}.jsonl"]
        else:
            candidates = sorted(log_dir.glob("*.jsonl"))
        records: list[dict[str, Any]] = []
        for path in candidates:
            if not path.is_file():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    import json  # noqa: PLC0415

                    records.append(json.loads(stripped))
                except ValueError:
                    continue
        limit = max(limit, 0)
        return records[-limit:] if limit else []

    @router.get("/api/wiki/maintenance/status")
    def get_maintenance_status() -> dict[str, Any]:
        loop = _wiki_loop(ctx)
        queue = _maintenance_queue(ctx)
        queue_path = (
            queue._path  # noqa: SLF001 — read-only diagnostics
            if queue is not None
            else None
        )
        return {
            "open_pr_url": getattr(loop, "_open_pr_url", None) if loop else None,
            "open_pr_branch": getattr(loop, "_open_pr_branch", None) if loop else None,
            "queue_depth": len(queue.peek()) if queue is not None else 0,
            "queue_path": str(queue_path) if queue_path else None,
            "interval_seconds": ctx.config.repo_wiki_interval,
            "auto_merge": ctx.config.repo_wiki_maintenance_auto_merge,
            "coalesce": ctx.config.repo_wiki_maintenance_pr_coalesce,
        }

    @router.post("/api/wiki/admin/force-compile")
    def admin_force_compile(payload: ForceCompilePayload) -> dict[str, str]:
        queue = _maintenance_queue(ctx)
        if queue is None:
            raise HTTPException(status_code=503, detail="wiki queue unavailable")
        queue.enqueue(
            MaintenanceTask(
                kind="force-compile",
                repo_slug=f"{payload.owner}/{payload.repo}",
                params={"topic": payload.topic},
            )
        )
        return {"status": "queued"}

    @router.post("/api/wiki/admin/mark-stale")
    def admin_mark_stale(payload: MarkStalePayload) -> dict[str, str]:
        queue = _maintenance_queue(ctx)
        if queue is None:
            raise HTTPException(status_code=503, detail="wiki queue unavailable")
        queue.enqueue(
            MaintenanceTask(
                kind="mark-stale",
                repo_slug=f"{payload.owner}/{payload.repo}",
                params={
                    "entry_id": payload.entry_id,
                    "reason": payload.reason,
                },
            )
        )
        return {"status": "queued"}

    @router.post("/api/wiki/admin/rebuild-index")
    def admin_rebuild_index(payload: RebuildIndexPayload) -> dict[str, str]:
        queue = _maintenance_queue(ctx)
        if queue is None:
            raise HTTPException(status_code=503, detail="wiki queue unavailable")
        queue.enqueue(
            MaintenanceTask(
                kind="rebuild-index",
                repo_slug=f"{payload.owner}/{payload.repo}",
                params={},
            )
        )
        return {"status": "queued"}

    @router.post("/api/wiki/admin/run-now")
    def admin_run_now() -> dict[str, str]:
        """Request that ``RepoWikiLoop`` runs on the next event-loop iteration.

        The loop itself decides timing — this endpoint only flips a flag
        the loop observes; it does not bypass the interval directly.
        Phase 5 delivers the queued-for-soon semantics; Phase 6 may add
        an interrupt path.
        """
        loop = _wiki_loop(ctx)
        if loop is None:
            raise HTTPException(status_code=503, detail="wiki loop unavailable")
        # BaseBackgroundLoop exposes ``trigger_now`` / ``force_tick`` on
        # some loops; fall through to a log-only response if not.
        trigger = getattr(loop, "trigger_now", None) or getattr(
            loop, "force_tick", None
        )
        if callable(trigger):
            trigger()
            return {"status": "triggered"}
        logger.info("Wiki admin run-now received; loop has no trigger hook")
        return {"status": "acknowledged"}
