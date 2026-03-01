"""Persistent supervisor state management."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import SUPERVISOR_STATE_FILE


def _normalize_path(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve())


def _load_state() -> dict[str, Any]:
    if SUPERVISOR_STATE_FILE.is_file():
        try:
            return json.loads(SUPERVISOR_STATE_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {"repos": []}


def _save_state(state: dict[str, Any]) -> None:
    SUPERVISOR_STATE_FILE.write_text(json.dumps(state, indent=2))


def list_repos() -> list[dict[str, Any]]:
    return list(_load_state().get("repos", []))


def get_repo(
    *, path: str | Path | None = None, slug: str | None = None
) -> dict[str, Any] | None:
    """Return the stored repo entry for *path* or *slug* (if present)."""
    state = _load_state()
    target_path = _normalize_path(path) if path else None
    repos = state.setdefault("repos", [])
    for repo in repos:
        if target_path and repo.get("path") == target_path:
            return repo
        if slug and repo.get("slug") == slug:
            return repo
    return None


def upsert_repo(path: str | Path, slug: str, port: int, log_file: str) -> None:
    state = _load_state()
    repos = state.setdefault("repos", [])
    dashboard_url = f"http://localhost:{port}"
    normalized_path = _normalize_path(path)
    for repo in repos:
        if repo.get("path") == normalized_path:
            repo.update(
                {
                    "slug": slug,
                    "port": port,
                    "dashboard_url": dashboard_url,
                    "log_file": log_file,
                }
            )
            _save_state(state)
            return
    repos.append(
        {
            "path": normalized_path,
            "slug": slug,
            "port": port,
            "dashboard_url": dashboard_url,
            "log_file": log_file,
        }
    )
    _save_state(state)


def remove_repo(*, path: str | Path | None = None, slug: str | None = None) -> bool:
    """Remove a repo by absolute path or slug. Returns True if deleted."""
    state = _load_state()
    repos = state.setdefault("repos", [])
    normalized_path = _normalize_path(path) if path else None
    for idx, repo in enumerate(repos):
        if normalized_path and repo.get("path") == normalized_path:
            repos.pop(idx)
            _save_state(state)
            return True
        if slug and repo.get("slug") == slug:
            repos.pop(idx)
            _save_state(state)
            return True
    return False
