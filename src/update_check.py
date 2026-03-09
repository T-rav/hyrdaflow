"""Lightweight HydraFlow update check helpers."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app_version import get_app_version

_PYPI_JSON_URL = "https://pypi.org/pypi/hydraflow/json"
_CACHE_MAX_AGE_SECONDS = 24 * 60 * 60
_CACHE_DIR = Path.home() / ".hydraflow"
_CACHE_PATH = _CACHE_DIR / "update-check.json"


@dataclass(frozen=True)
class UpdateCheckResult:
    current_version: str
    latest_version: str | None
    update_available: bool
    error: str | None = None


def _version_key(raw: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in raw.strip().split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def _is_newer(latest: str, current: str) -> bool:
    latest_key = _version_key(latest)
    current_key = _version_key(current)
    if not latest_key or not current_key:
        return latest != current
    return latest_key > current_key


def _read_cache(path: Path = _CACHE_PATH) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def load_cached_update_result(
    current_version: str | None = None,
    path: Path = _CACHE_PATH,
) -> UpdateCheckResult | None:
    cached = _read_cache(path)
    if cached is None:
        return None
    cached_current = str(cached.get("current_version", "")).strip()
    effective_current = (current_version or cached_current).strip()
    cached_latest = cached.get("latest_version")
    if not effective_current or not isinstance(cached_latest, str) or not cached_latest:
        return None
    return UpdateCheckResult(
        current_version=effective_current,
        latest_version=cached_latest,
        update_available=_is_newer(cached_latest, effective_current),
    )


def _write_cache(payload: dict[str, Any], path: Path = _CACHE_PATH) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload))
    except OSError:
        return


def _fetch_latest_pypi_version(timeout_seconds: float) -> str:
    response = httpx.get(
        _PYPI_JSON_URL,
        headers={"Accept": "application/json"},
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    info = payload.get("info", {}) if isinstance(payload, dict) else {}
    latest = info.get("version")
    if not isinstance(latest, str) or not latest.strip():
        msg = "invalid PyPI response"
        raise RuntimeError(msg)
    return latest.strip()


def check_for_updates(timeout_seconds: float = 2.0) -> UpdateCheckResult:
    current = get_app_version()
    try:
        latest = _fetch_latest_pypi_version(timeout_seconds)
    except (
        OSError,
        httpx.HTTPError,
        RuntimeError,
        TimeoutError,
        ValueError,
    ) as exc:
        return UpdateCheckResult(
            current_version=current,
            latest_version=None,
            update_available=False,
            error=str(exc),
        )
    return UpdateCheckResult(
        current_version=current,
        latest_version=latest,
        update_available=_is_newer(latest, current),
        error=None,
    )


def check_for_updates_cached(
    timeout_seconds: float = 2.0,
    max_age_seconds: int = _CACHE_MAX_AGE_SECONDS,
    path: Path = _CACHE_PATH,
) -> UpdateCheckResult:
    now = int(time.time())
    current = get_app_version()
    cached = _read_cache(path)
    if cached is not None:
        checked_at = int(cached.get("checked_at", 0))
        cached_current = str(cached.get("current_version", ""))
        cached_latest = cached.get("latest_version")
        if (
            checked_at > 0
            and now - checked_at < max_age_seconds
            and cached_current == current
            and isinstance(cached_latest, str)
            and cached_latest
        ):
            return UpdateCheckResult(
                current_version=current,
                latest_version=cached_latest,
                update_available=_is_newer(cached_latest, current),
            )
    result = check_for_updates(timeout_seconds=timeout_seconds)
    if result.latest_version:
        _write_cache(
            {
                "checked_at": now,
                "current_version": result.current_version,
                "latest_version": result.latest_version,
            },
            path,
        )
    return result


__all__ = [
    "UpdateCheckResult",
    "check_for_updates",
    "check_for_updates_cached",
    "load_cached_update_result",
]
