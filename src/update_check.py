"""Lightweight HydraFlow update check helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


__all__ = [
    "UpdateCheckResult",
    "load_cached_update_result",
]
