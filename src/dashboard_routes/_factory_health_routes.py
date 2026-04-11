"""Factory health dashboard routes.

Exposes a single endpoint that returns longitudinal analysis of
retrospective metrics: rolling averages, memory-impact cohorts,
and regression detection.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter

from factory_health import compute_summary

if TYPE_CHECKING:
    from config import HydraFlowConfig

logger = logging.getLogger("hydraflow.dashboard.factory_health")


def _load_jsonl(path: Any) -> list[dict[str, Any]]:
    """Load entries from a JSONL file, skipping malformed lines."""
    try:
        if not path.exists():
            return []
    except OSError:
        return []
    entries: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    entries.append(obj)
    except OSError as exc:
        logger.warning("Failed to read %s: %s", path, exc)
    return entries


def build_factory_health_router(config: HydraFlowConfig) -> APIRouter:
    """Build the ``/api/factory-health`` router."""

    router = APIRouter(prefix="/api/factory-health", tags=["factory-health"])

    @router.get("/summary")
    def get_factory_health(repo: str = "") -> dict[str, Any]:
        retro_path = config.data_path("memory", "retrospectives.jsonl")
        telemetry_path = config.data_path("metrics", "prompt", "inferences.jsonl")
        retro_entries = _load_jsonl(retro_path)
        telemetry_entries = _load_jsonl(telemetry_path)
        if repo:
            retro_entries = [e for e in retro_entries if e.get("repo") == repo]
            telemetry_entries = [e for e in telemetry_entries if e.get("repo") == repo]
        return compute_summary(retro_entries, telemetry_entries)

    return router
