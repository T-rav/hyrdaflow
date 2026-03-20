"""Centralized GitHub data cache — single poller, all consumers read from cache.

Replaces the pattern where every dashboard endpoint and background worker
makes its own ``gh api`` calls.  A single :class:`GitHubCacheLoop` polls
GitHub on a fixed interval and stores results in :class:`GitHubDataCache`.
Dashboard endpoints and background workers read from the cache instantly.

Write operations (create PR, merge, comment, label swap) still call ``gh``
directly — they're low-frequency and need immediate confirmation.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from issue_fetcher import IssueFetcher
    from models import HITLItem, LabelCounts, PRListItem
    from pr_manager import PRManager

logger = logging.getLogger("hydraflow.github_cache")


@dataclass
class CacheSnapshot:
    """Timestamped cache entry for a single dataset."""

    data: Any = None
    fetched_at: datetime | None = None

    @property
    def age_seconds(self) -> float:
        """Seconds since the data was fetched, or inf if never fetched."""
        if self.fetched_at is None:
            return float("inf")
        return (datetime.now(UTC) - self.fetched_at).total_seconds()


class GitHubDataCache:
    """In-memory + disk-persisted cache for GitHub API read data.

    Each dataset is fetched by :meth:`poll` and stored both in memory
    and on disk (JSON).  Dashboard endpoints and background workers
    read from memory via the ``get_*`` methods — never hitting the API.

    The cache is repo-scoped: each :class:`RepoRuntime` gets its own
    instance with its own disk file.
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        pr_manager: PRManager,
        fetcher: IssueFetcher,
        cache_dir: Path | None = None,
    ) -> None:
        self._config = config
        self._prs = pr_manager
        self._fetcher = fetcher
        self._cache_dir = cache_dir or config.repo_data_root
        self._cache_file = self._cache_dir / "github_cache.json"
        self._poll_lock = asyncio.Lock()

        # In-memory snapshots
        self._open_prs = CacheSnapshot()
        self._hitl_items = CacheSnapshot()
        self._label_counts = CacheSnapshot()
        self._collaborators = CacheSnapshot()

        # Load persisted cache on construction
        self._load_from_disk()

    # --- Read methods (instant, never hit the network) ---

    def get_open_prs(self) -> list[PRListItem]:
        """Return cached open PRs, or empty list if not yet fetched."""
        return self._open_prs.data or []

    def get_hitl_items(self) -> list[HITLItem]:
        """Return cached HITL items, or empty list if not yet fetched."""
        return self._hitl_items.data or []

    def get_label_counts(self) -> LabelCounts | None:
        """Return cached label counts, or None if not yet fetched."""
        return self._label_counts.data

    def get_collaborators(self) -> set[str] | None:
        """Return cached collaborator set, or None if not yet fetched."""
        return self._collaborators.data

    def get_cache_age(self, dataset: str) -> float:
        """Return seconds since the given dataset was last fetched."""
        snap = getattr(self, f"_{dataset}", None)
        if isinstance(snap, CacheSnapshot):
            return snap.age_seconds
        return float("inf")

    # --- Poll (called by GitHubCacheLoop) ---

    async def poll(self) -> dict[str, Any]:
        """Fetch all datasets from GitHub and update the cache.

        Returns a stats dict for background worker status reporting.
        """
        async with self._poll_lock:
            stats: dict[str, Any] = {}
            now = datetime.now(UTC)

            # Open PRs
            try:
                all_labels = list(
                    dict.fromkeys(
                        [
                            *self._config.ready_label,
                            *self._config.review_label,
                            *self._config.hitl_label,
                        ]
                    )
                )
                prs = await self._prs.list_open_prs(all_labels)
                self._open_prs = CacheSnapshot(data=prs, fetched_at=now)
                stats["open_prs"] = len(prs)
            except Exception:
                logger.warning("Cache poll failed for open_prs", exc_info=True)

            # HITL items
            try:
                hitl_labels = list(
                    dict.fromkeys(
                        [*self._config.hitl_label, *self._config.hitl_active_label]
                    )
                )
                items = await self._prs.list_hitl_items(hitl_labels)
                self._hitl_items = CacheSnapshot(data=items, fetched_at=now)
                stats["hitl_items"] = len(items)
            except Exception:
                logger.warning("Cache poll failed for hitl_items", exc_info=True)

            # Label counts
            try:
                counts = await self._prs.get_label_counts(self._config)
                self._label_counts = CacheSnapshot(data=counts, fetched_at=now)
                stats["label_counts"] = True
            except Exception:
                logger.warning("Cache poll failed for label_counts", exc_info=True)

            # Collaborators
            try:
                collabs = await self._fetcher._get_collaborators()
                self._collaborators = CacheSnapshot(data=collabs, fetched_at=now)
                stats["collaborators"] = len(collabs) if collabs else 0
            except Exception:
                logger.warning("Cache poll failed for collaborators", exc_info=True)

            self._save_to_disk()
            return stats

    def invalidate(self, dataset: str | None = None) -> None:
        """Clear cache timestamps, forcing refetch on next poll.

        If *dataset* is None, invalidate all datasets.
        """
        targets = (
            [f"_{dataset}"]
            if dataset
            else ["_open_prs", "_hitl_items", "_label_counts", "_collaborators"]
        )
        for attr in targets:
            snap = getattr(self, attr, None)
            if isinstance(snap, CacheSnapshot):
                setattr(self, attr, CacheSnapshot())

    # --- Disk persistence ---

    def _save_to_disk(self) -> None:
        """Persist cache to JSON for restart recovery."""
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            data: dict[str, Any] = {}
            if self._open_prs.data is not None:
                data["open_prs"] = [
                    p.model_dump() if hasattr(p, "model_dump") else p
                    for p in self._open_prs.data
                ]
            if self._hitl_items.data is not None:
                data["hitl_items"] = [
                    i.model_dump() if hasattr(i, "model_dump") else i
                    for i in self._hitl_items.data
                ]
            if self._label_counts.data is not None:
                lc = self._label_counts.data
                data["label_counts"] = (
                    lc.model_dump() if hasattr(lc, "model_dump") else lc
                )
            if self._collaborators.data is not None:
                data["collaborators"] = sorted(self._collaborators.data)
            data["fetched_at"] = datetime.now(UTC).isoformat()
            self._cache_file.write_text(json.dumps(data, indent=2))
        except Exception:
            logger.debug("Failed to persist github cache", exc_info=True)

    def _load_from_disk(self) -> None:
        """Load persisted cache from disk if available."""
        if not self._cache_file.is_file():
            return
        try:
            raw = json.loads(self._cache_file.read_text())
            fetched_str = raw.get("fetched_at")
            fetched_at = datetime.fromisoformat(fetched_str) if fetched_str else None

            # Load as raw dicts — they'll be replaced by proper models on
            # the first poll().  Good enough for dashboard display.
            if "open_prs" in raw:
                self._open_prs = CacheSnapshot(
                    data=raw["open_prs"], fetched_at=fetched_at
                )
            if "hitl_items" in raw:
                self._hitl_items = CacheSnapshot(
                    data=raw["hitl_items"], fetched_at=fetched_at
                )
            if "label_counts" in raw:
                self._label_counts = CacheSnapshot(
                    data=raw["label_counts"], fetched_at=fetched_at
                )
            if "collaborators" in raw:
                self._collaborators = CacheSnapshot(
                    data=set(raw["collaborators"]), fetched_at=fetched_at
                )
            logger.info("Loaded github cache from disk (%s)", self._cache_file)
        except Exception:
            logger.debug("Failed to load github cache from disk", exc_info=True)


class GitHubCacheLoop(BaseBackgroundLoop):
    """Background loop that polls GitHub and updates the data cache."""

    def __init__(
        self,
        config: HydraFlowConfig,
        cache: GitHubDataCache,
        *,
        deps: LoopDeps,
    ) -> None:
        super().__init__(
            worker_name="github_cache",
            config=config,
            deps=deps,
            run_on_startup=True,
        )
        self._cache = cache

    async def _do_work(self) -> bool:
        stats = await self._cache.poll()
        logger.info(
            "GitHub cache refreshed: %s",
            ", ".join(f"{k}={v}" for k, v in stats.items()),
        )
        return bool(stats)

    def _get_default_interval(self) -> int:
        return self._config.data_poll_interval
