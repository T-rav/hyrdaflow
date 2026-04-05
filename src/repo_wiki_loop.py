"""Background worker loop — repo wiki lint and maintenance."""

from __future__ import annotations

import logging
from typing import Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from repo_wiki import RepoWikiStore

logger = logging.getLogger("hydraflow.repo_wiki_loop")


class RepoWikiLoop(BaseBackgroundLoop):
    """Periodically lints all per-repo wikis for staleness and consistency."""

    def __init__(
        self,
        config: HydraFlowConfig,
        wiki_store: RepoWikiStore,
        deps: LoopDeps,
    ) -> None:
        super().__init__(worker_name="repo_wiki", config=config, deps=deps)
        self._wiki_store = wiki_store

    def _get_default_interval(self) -> int:
        return self._config.repo_wiki_interval

    async def _do_work(self) -> dict[str, Any] | None:
        repos = self._wiki_store.list_repos()
        if not repos:
            return {"repos": 0, "total_entries": 0}

        total_stale = 0
        total_orphans = 0
        total_entries = 0
        empty_topics: list[str] = []

        for slug in repos:
            result = self._wiki_store.lint(slug)
            total_stale += result.stale_entries
            total_orphans += result.orphan_entries
            total_entries += result.total_entries
            empty_topics.extend(f"{slug}:{t}" for t in result.empty_topics)

        stats = {
            "repos": len(repos),
            "total_entries": total_entries,
            "stale_entries": total_stale,
            "orphan_entries": total_orphans,
            "empty_topics": len(empty_topics),
        }

        if total_stale or total_orphans:
            logger.info(
                "Wiki lint: %d stale, %d orphans across %d repos",
                total_stale,
                total_orphans,
                len(repos),
            )

        return stats
