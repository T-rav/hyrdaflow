"""Repo management, runtime lifecycle, filesystem browsing, and GitHub operations route handlers."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Body, Query
from fastapi.responses import JSONResponse

from dashboard_routes._context import RepoSlugParam
from dashboard_routes._helpers import (
    _SAFE_SLUG_COMPONENT,
    _SUPERVISOR_UNAVAILABLE_MESSAGE,
    _extract_repo_path,
    _extract_repo_slug,
    _find_repo_match,
    _is_expected_supervisor_unavailable,
    _normalize_allowed_dir,
    _pick_folder_with_dialog,
)

if TYPE_CHECKING:
    from dashboard_routes._context import RouterContext

logger = logging.getLogger("hydraflow.dashboard")


# ------------------------------------------------------------------
# Module-level async helpers
# ------------------------------------------------------------------


async def _call_supervisor(
    ctx: RouterContext, func: Any, *args: Any, **kwargs: Any
) -> Any:
    """Call a supervisor function in a background thread."""
    if ctx.supervisor_client is None:
        raise RuntimeError(
            "HydraFlow supervisor client unavailable in this environment"
        )
    return await asyncio.to_thread(func, *args, **kwargs)


async def _detect_repo_slug_from_path(repo_path: Path) -> str | None:  # noqa: PLR0911
    """Detect the GitHub owner/repo slug from a local git repo's remote URL."""
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


# ------------------------------------------------------------------
# Route registration
# ------------------------------------------------------------------


def register_repo_routes(router: APIRouter, ctx: RouterContext) -> None:
    """Register repo management, runtime, filesystem, and GitHub routes."""

    # ---- Runtime lifecycle -------------------------------------------------

    @router.get("/api/runtimes")
    async def list_runtimes() -> JSONResponse:
        from models import RepoRuntimeInfo  # noqa: PLC0415

        if ctx.registry is None:
            return JSONResponse({"runtimes": []})
        infos = []
        for rt in ctx.registry.all:
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
        from models import RepoRuntimeInfo  # noqa: PLC0415

        if ctx.registry is None:
            return JSONResponse(
                {"error": "No runtime registry configured"}, status_code=501
            )
        rt = ctx.registry.get(slug)
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
        if ctx.registry is None:
            return JSONResponse(
                {"error": "No runtime registry configured"}, status_code=501
            )
        rt = ctx.registry.get(slug)
        if rt is None:
            return JSONResponse({"error": f"Unknown repo: {slug}"}, status_code=404)
        if rt.running:
            return JSONResponse({"error": "Already running"}, status_code=409)
        await rt.start()
        return JSONResponse({"status": "started", "slug": slug})

    @router.post("/api/runtimes/{slug}/stop")
    async def stop_runtime(slug: str) -> JSONResponse:
        if ctx.registry is None:
            return JSONResponse(
                {"error": "No runtime registry configured"}, status_code=501
            )
        rt = ctx.registry.get(slug)
        if rt is None:
            return JSONResponse({"error": f"Unknown repo: {slug}"}, status_code=404)
        if not rt.running:
            return JSONResponse({"error": "Not running"}, status_code=400)
        await rt.stop()
        return JSONResponse({"status": "stopped", "slug": slug})

    @router.delete("/api/runtimes/{slug}")
    async def remove_runtime(slug: str) -> JSONResponse:
        if ctx.registry is None:
            return JSONResponse(
                {"error": "No runtime registry configured"}, status_code=501
            )
        rt = ctx.registry.get(slug)
        if rt is None:
            return JSONResponse({"error": f"Unknown repo: {slug}"}, status_code=404)
        if ctx.remove_repo_cb is not None:
            try:
                await ctx.remove_repo_cb(slug)
            except Exception as exc:
                logger.warning("remove_repo callback failed for %s: %s", slug, exc)
                return JSONResponse({"error": "Failed to remove repo"}, status_code=500)
            return JSONResponse({"status": "removed", "slug": slug})
        if rt.running:
            await rt.stop()
        ctx.registry.remove(slug)
        if ctx.repo_store is not None:
            try:
                ctx.repo_store.remove(slug)
            except Exception:
                logger.warning(
                    "Failed to remove repo %s from store", slug, exc_info=True
                )
        return JSONResponse({"status": "removed", "slug": slug})

    # ---- Repos -------------------------------------------------------------

    @router.get("/api/repos")
    async def list_supervised_repos() -> JSONResponse:
        """List repos from the store, callback, or supervisor."""
        if ctx.repo_store is not None or ctx.list_repos_cb is not None:
            records = ctx.list_repo_records()
            payload = []
            for rec in records:
                runtime = ctx.registry.get(rec.slug) if ctx.registry else None
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
            return JSONResponse({"repos": payload, "can_register": True})
        if ctx.supervisor_client is None:
            return JSONResponse({"repos": [], "can_register": False})
        try:
            repos = await _call_supervisor(ctx, ctx.supervisor_client.list_repos)
        except Exception as exc:
            if not _is_expected_supervisor_unavailable(exc):
                logger.warning("Supervisor list_repos failed: %s", exc)
            return JSONResponse(
                {"error": "Supervisor unavailable", "can_register": False},
                status_code=503,
            )
        return JSONResponse({"repos": repos, "can_register": True})

    # ---- Filesystem browsing -----------------------------------------------

    _root_names: dict[int, str] = {0: "Home", 1: "Temp"}

    @router.get("/api/fs/roots")
    async def list_browsable_roots() -> JSONResponse:
        """Return filesystem roots that are safe to browse from the UI."""
        all_roots = ctx.repo_roots_fn()
        roots = [
            {"name": _root_names.get(i, f"Root {i + 1}"), "path": root}
            for i, root in enumerate(all_roots)
        ]
        return JSONResponse({"roots": roots})

    @router.get("/api/fs/list")
    async def list_browsable_directories(
        path: str | None = Query(default=None),
    ) -> JSONResponse:
        allowed_roots = ctx.repo_roots_fn()
        if not allowed_roots:
            return JSONResponse(
                {"error": "no allowed roots configured"}, status_code=500
            )
        target_raw = path or allowed_roots[0]
        target_path, error = _normalize_allowed_dir(
            target_raw, allowed_roots=allowed_roots
        )
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
        directories = []
        try:
            for child in sorted(target_path.iterdir(), key=lambda p: p.name.lower()):
                if not child.is_dir():
                    continue
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

    # ---- Repo CRUD (ensure / remove / add-by-path / pick / clone) ----------

    @router.post("/api/repos")
    async def ensure_repo(
        req: dict[str, Any] | None = Body(default=None),
        req_query: str | None = Query(default=None, alias="req"),
        slug: str | None = Query(default=None),
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Ensure a repo is registered with the supervisor by slug."""
        error_payload = None
        if ctx.supervisor_client is None:
            error_payload = ("supervisor unavailable", 503)
        else:
            target_slug = _extract_repo_slug(req, req_query, slug, repo)
            if not target_slug:
                error_payload = ("slug required", 400)
            else:
                try:
                    repos = await _call_supervisor(
                        ctx, ctx.supervisor_client.list_repos
                    )
                except Exception as exc:
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
                            error_payload = (
                                f"repo '{matched_slug}' missing path",
                                500,
                            )
                        else:
                            try:
                                info = await _call_supervisor(
                                    ctx,
                                    ctx.supervisor_client.add_repo,
                                    Path(path),
                                    matched_slug,
                                )
                            except Exception as exc:
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
        if ctx.remove_repo_cb is not None:
            try:
                removed = await ctx.remove_repo_cb(slug)
            except Exception as exc:
                logger.warning("remove_repo callback failed: %s", exc)
                return JSONResponse({"error": "Failed to remove repo"}, status_code=500)
            if not removed:
                return JSONResponse({"error": "Repo not found"}, status_code=404)
            return JSONResponse({"status": "ok"})
        if ctx.supervisor_client is None:
            return JSONResponse({"error": "supervisor unavailable"}, status_code=503)
        try:
            await _call_supervisor(ctx, ctx.supervisor_client.remove_repo, None, slug)
        except Exception as exc:
            logger.warning("Supervisor remove_repo failed: %s", exc)
            return JSONResponse({"error": "Failed to remove repo"}, status_code=500)
        return JSONResponse({"status": "ok"})

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
        repo_path, path_error = _normalize_allowed_dir(
            raw_path, allowed_roots=ctx.repo_roots_fn()
        )
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
        if ctx.register_repo_cb is not None:
            try:
                record, repo_cfg = await ctx.register_repo_cb(repo_path, slug)
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
        if ctx.supervisor_client is None:
            return JSONResponse(
                {"error": _SUPERVISOR_UNAVAILABLE_MESSAGE},
                status_code=503,
            )
        try:
            await _call_supervisor(
                ctx,
                ctx.supervisor_client.register_repo,
                repo_path,
                slug,
            )
        except Exception as exc:  # noqa: BLE001
            if _is_expected_supervisor_unavailable(exc):
                if ctx.supervisor_manager is not None:
                    try:
                        await _call_supervisor(
                            ctx, ctx.supervisor_manager.ensure_running
                        )
                        await _call_supervisor(
                            ctx,
                            ctx.supervisor_client.register_repo,
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

                target_cfg = ctx.config.model_copy(
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
        folder_path = Path(os.path.realpath(os.path.expanduser(selected)))
        if not folder_path.is_dir():
            return JSONResponse(
                {"error": "Selected path is not a directory"}, status_code=400
            )
        return JSONResponse({"path": str(folder_path)})

    # ---- GitHub operations -------------------------------------------------

    @router.get("/api/github/repos")
    async def list_github_repos(
        query: str | None = Query(default=None),
    ) -> JSONResponse:
        """List GitHub repos for the authenticated user via ``gh repo list``."""
        cmd = [
            "gh",
            "repo",
            "list",
            "--json",
            "name,owner,url,description",
            "--limit",
            "100",
        ]
        proc: asyncio.subprocess.Process | None = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        except FileNotFoundError:
            return JSONResponse(
                {
                    "error": "gh CLI not found — install GitHub CLI and run 'gh auth login'"
                },
                status_code=503,
            )
        except TimeoutError:
            if proc is not None:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
            return JSONResponse(
                {"error": "gh CLI timed out"},
                status_code=504,
            )
        if proc.returncode != 0:
            msg = (stderr or b"").decode().strip()
            if "auth" in msg.lower() or "login" in msg.lower():
                return JSONResponse(
                    {"error": "Not authenticated — run 'gh auth login' first"},
                    status_code=401,
                )
            return JSONResponse(
                {"error": f"gh repo list failed: {msg}"},
                status_code=502,
            )
        try:
            repos = json.loads(stdout or b"[]")
        except json.JSONDecodeError:
            return JSONResponse(
                {"error": "Failed to parse gh output"},
                status_code=502,
            )
        # Filter by query if provided
        if query:
            q = query.lower()
            repos = [
                r
                for r in repos
                if q in (r.get("name") or "").lower()
                or q in ((r.get("owner") or {}).get("login") or "").lower()
                or q
                in f"{(r.get('owner') or {}).get('login', '')}/{r.get('name', '')}".lower()
            ]
        return JSONResponse({"repos": repos})

    @router.post("/api/github/clone")
    async def clone_github_repo(  # noqa: PLR0911
        req: dict[str, Any] | None = Body(default=None),
    ) -> JSONResponse:
        """Clone a GitHub repo into the workspace directory and register it."""
        if not isinstance(req, dict):
            return JSONResponse({"error": "request body required"}, status_code=400)
        slug = (req.get("slug") or "").strip()
        if not slug or "/" not in slug:
            return JSONResponse(
                {"error": "slug required in owner/repo format"},
                status_code=400,
            )
        raw_owner, raw_repo = slug.split("/", 1)
        if not raw_owner or not raw_repo:
            return JSONResponse(
                {"error": "slug required in owner/repo format"},
                status_code=400,
            )
        # Validate path components to prevent directory traversal
        if (
            not _SAFE_SLUG_COMPONENT.match(raw_owner)
            or not _SAFE_SLUG_COMPONENT.match(raw_repo)
            or set(raw_owner) <= {"."}
            or set(raw_repo) <= {"."}
        ):
            return JSONResponse(
                {"error": "slug contains invalid characters"},
                status_code=400,
            )
        # Sanitise: extract only the final path component to break any
        # traversal sequences.  PurePosixPath.name is recognised by
        # CodeQL as a path-injection sanitiser.
        owner = PurePosixPath(raw_owner).name
        repo_name = PurePosixPath(raw_repo).name
        if not owner or not repo_name:
            return JSONResponse(
                {"error": "slug contains invalid characters"},
                status_code=400,
            )
        workspace_dir = Path(
            os.path.expanduser(str(ctx.config.repos_workspace_dir))
        ).resolve()
        clone_target = (workspace_dir / owner / repo_name).resolve()
        if not clone_target.is_relative_to(workspace_dir):
            return JSONResponse(
                {"error": "slug contains invalid characters"},
                status_code=400,
            )
        # Reconstruct slug from sanitised components
        slug = f"{owner}/{repo_name}"
        already_cloned = clone_target.is_dir() and (clone_target / ".git").is_dir()
        if not already_cloned:
            workspace_dir.mkdir(parents=True, exist_ok=True)
            owner_dir = clone_target.parent
            owner_dir.mkdir(parents=True, exist_ok=True)
            cmd = ["gh", "repo", "clone", slug, str(clone_target)]
            clone_proc: asyncio.subprocess.Process | None = None
            try:
                clone_proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await asyncio.wait_for(
                    clone_proc.communicate(), timeout=300
                )
            except FileNotFoundError:
                return JSONResponse(
                    {"error": "gh CLI not found"},
                    status_code=503,
                )
            except TimeoutError:
                if clone_proc is not None:
                    with contextlib.suppress(ProcessLookupError):
                        clone_proc.kill()
                return JSONResponse(
                    {"error": "Clone timed out"},
                    status_code=504,
                )
            if clone_proc.returncode != 0:
                msg = (stderr or b"").decode().strip()
                return JSONResponse(
                    {"error": f"Clone failed: {msg}"},
                    status_code=502,
                )
        # Register with the callback or supervisor
        if ctx.register_repo_cb is not None:
            try:
                record, repo_cfg = await ctx.register_repo_cb(clone_target, slug)
            except ValueError as exc:
                logger.warning("register_repo validation error: %s", exc)
                return JSONResponse(
                    {"error": "Invalid repository configuration"},
                    status_code=400,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("register_repo callback failed: %s", exc)
                return JSONResponse(
                    {"error": "Failed to register repo"}, status_code=500
                )
            labels_created = False
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
                    "already_cloned": already_cloned,
                    "labels_created": labels_created,
                }
            )
        # Fallback: register via add_repo_by_path logic
        return JSONResponse(
            {
                "status": "ok",
                "slug": slug.replace("/", "-"),
                "path": str(clone_target),
                "already_cloned": already_cloned,
                "labels_created": False,
            }
        )
