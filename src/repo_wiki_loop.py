"""Background worker loop — repo wiki lint, compilation, and maintenance."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from repo_wiki import DEFAULT_TOPICS, RepoWikiStore

if TYPE_CHECKING:
    from state import StateTracker
    from wiki_compiler import WikiCompiler

logger = logging.getLogger("hydraflow.repo_wiki_loop")

# Terminal outcome types — issues with these outcomes are considered closed.
_TERMINAL_OUTCOMES = frozenset({"merged", "hitl_closed", "failed", "manual_close"})


class RepoWikiLoop(BaseBackgroundLoop):
    """Periodically lints and compiles all per-repo wikis.

    Each cycle:
    1. **Active lint** — marks stale entries for closed issues, prunes
       old stale entries, rebuilds index.
    2. **Compile** — if a WikiCompiler is available, runs LLM synthesis
       on any topic with 5+ entries to deduplicate and cross-reference.
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        wiki_store: RepoWikiStore,
        deps: LoopDeps,
        wiki_compiler: WikiCompiler | None = None,
        state: StateTracker | None = None,
    ) -> None:
        super().__init__(worker_name="repo_wiki", config=config, deps=deps)
        self._wiki_store = wiki_store
        self._wiki_compiler = wiki_compiler
        self._state = state

    def _get_default_interval(self) -> int:
        return self._config.repo_wiki_interval

    def _get_closed_issues(self) -> set[int]:
        """Derive closed issue numbers from StateTracker outcomes."""
        if self._state is None:
            return set()
        outcomes = self._state.get_all_outcomes()
        return {int(k) for k, v in outcomes.items() if v.outcome in _TERMINAL_OUTCOMES}

    async def _do_work(self) -> dict[str, Any] | None:
        repos = self._wiki_store.list_repos()
        if not repos:
            return {"repos": 0, "total_entries": 0}

        closed_issues = self._get_closed_issues()

        total_stale = 0
        total_orphans = 0
        total_entries = 0
        total_marked_stale = 0
        total_pruned = 0
        total_compiled = 0
        empty_topics: list[str] = []

        for slug in repos:
            # Phase 1: Active lint — self-healing pass
            result = self._wiki_store.active_lint(slug, closed_issues=closed_issues)
            total_stale += result.stale_entries
            total_orphans += result.orphan_entries
            total_entries += result.total_entries
            total_marked_stale += result.entries_marked_stale
            total_pruned += result.orphans_pruned
            empty_topics.extend(f"{slug}:{t}" for t in result.empty_topics)

            # Phase 2: LLM compilation — synthesize topics with many entries
            if self._wiki_compiler is not None:
                for topic in DEFAULT_TOPICS:
                    topic_path = self._wiki_store._repo_dir(slug) / f"{topic}.md"
                    entries = self._wiki_store._load_topic_entries(topic_path)
                    # Compile at 5+ entries (not 2) to avoid burning LLM
                    # calls on small topics where synthesis adds little value.
                    if len(entries) >= 5:
                        try:
                            after = await self._wiki_compiler.compile_topic(
                                self._wiki_store, slug, topic
                            )
                            if after < len(entries):
                                total_compiled += len(entries) - after
                        except Exception:  # noqa: BLE001
                            logger.warning(
                                "Wiki compile failed for %s/%s",
                                slug,
                                topic,
                                exc_info=True,
                            )

        stats = {
            "repos": len(repos),
            "total_entries": total_entries,
            "stale_entries": total_stale,
            "orphan_entries": total_orphans,
            "entries_marked_stale": total_marked_stale,
            "entries_pruned": total_pruned,
            "entries_compiled": total_compiled,
            "empty_topics": len(empty_topics),
        }

        if total_marked_stale or total_pruned or total_compiled:
            logger.info(
                "Wiki maintenance: %d marked stale, %d pruned, %d compiled across %d repos",
                total_marked_stale,
                total_pruned,
                total_compiled,
                len(repos),
            )

        return stats
