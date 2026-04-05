"""Background worker loop — auto-merge bot-authored PRs after CI passes."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from models import ReviewVerdict

if TYPE_CHECKING:
    from github_cache_loop import GitHubDataCache
    from ports import PRPort
    from state import StateTracker

logger = logging.getLogger("hydraflow.bot_pr_loop")


class BotPRLoop(BaseBackgroundLoop):
    """Polls open PRs and auto-merges those authored by known bots."""

    def __init__(
        self,
        config: HydraFlowConfig,
        cache: GitHubDataCache,
        prs: PRPort,
        state: StateTracker,
        deps: LoopDeps,
    ) -> None:
        super().__init__(worker_name="bot_pr", config=config, deps=deps)
        self._cache = cache
        self._prs = prs
        self._state = state

    def _get_default_interval(self) -> int:
        return self._config.bot_pr_interval

    async def _do_work(self) -> dict[str, Any] | None:
        """Check bot PRs and auto-merge if CI passes."""
        settings = self._state.get_bot_pr_settings()
        processed = self._state.get_bot_pr_processed()
        bot_authors = {a.lower() for a in settings.authors}

        open_prs = self._cache.get_open_prs()
        bot_prs = [
            pr
            for pr in open_prs
            if pr.author.lower() in bot_authors and pr.pr not in processed
        ]

        merged = 0
        skipped = 0
        failed = 0

        for pr in bot_prs:
            passed, summary = await self._prs.wait_for_ci(
                pr.pr,
                timeout=60,
                poll_interval=15,
                stop_event=self._stop_event,
            )

            if self._stop_event.is_set():
                break

            if passed:
                # CI green — approve and merge
                await self._prs.submit_review(
                    pr.pr, ReviewVerdict.APPROVE, "CI passed — auto-merging bot PR."
                )
                merge_ok = await self._prs.merge_pr(pr.pr)
                if merge_ok:
                    merged += 1
                    self._state.add_bot_pr_processed(pr.pr)
                    logger.info("Auto-merged bot PR #%d (%s)", pr.pr, pr.title)
                else:
                    failed += 1
                    logger.warning("Failed to merge bot PR #%d", pr.pr)
                continue

            # CI not passed — check if still pending or truly failed
            if "timed out" in summary.lower():
                # CI still pending — skip for now, retry next cycle
                skipped += 1
                logger.debug(
                    "Bot PR #%d CI still pending — will retry next cycle", pr.pr
                )
                continue

            # CI truly failed — apply failure strategy
            strategy = settings.failure_strategy
            if strategy == "skip":
                skipped += 1
                logger.info(
                    "Bot PR #%d CI failed (strategy=skip) — leaving open", pr.pr
                )
            elif strategy == "hitl":
                await self._prs.add_labels(pr.pr, self._config.hitl_label)
                await self._prs.post_comment(
                    pr.pr,
                    f"CI failed on bot PR — escalating to HITL.\n\n{summary}",
                )
                self._state.add_bot_pr_processed(pr.pr)
                failed += 1
                logger.info("Bot PR #%d CI failed — escalated to HITL", pr.pr)
            elif strategy == "close":
                await self._prs.post_comment(
                    pr.pr,
                    f"CI failed on bot PR — closing per configured strategy.\n\n{summary}",
                )
                await self._prs.close_issue(pr.pr)
                self._state.add_bot_pr_processed(pr.pr)
                failed += 1
                logger.info("Bot PR #%d CI failed — closed", pr.pr)

        return {"merged": merged, "skipped": skipped, "failed": failed}
