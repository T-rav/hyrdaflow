"""Promotion loop — cuts rc/* snapshots from staging and promotes them to main.

Runs on a tight poll interval (``staging_promotion_interval``, default 300s)
but actually cuts a new RC branch only every ``rc_cadence_hours`` (default 4h).
Between cuts it monitors the existing promotion PR: on green it merges with a
merge commit (ADR-0042 forbids squash here), on red it files a ``hydraflow-find``
issue and closes the PR so the next cadence tick can try again.

Gated by ``staging_enabled``; no-op when false.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig

if TYPE_CHECKING:
    from ports import PRPort
    from state import StateTracker

logger = logging.getLogger("hydraflow.staging_promotion_loop")


class StagingPromotionLoop(BaseBackgroundLoop):
    """Periodic staging→main release-candidate promoter. See ADR-0042."""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        prs: PRPort,
        deps: LoopDeps,
        state: StateTracker | None = None,
    ) -> None:
        super().__init__(worker_name="staging_promotion", config=config, deps=deps)
        self._prs = prs
        self._state = state

    def _get_default_interval(self) -> int:
        return self._config.staging_promotion_interval

    async def _do_work(self) -> dict[str, Any] | None:
        if not self._config.staging_enabled:
            return {"status": "staging_disabled"}

        swept = await self._sweep_if_due()

        existing = await self._prs.find_open_promotion_pr()
        if existing is not None:
            result = await self._handle_open_promotion(existing.number)
        elif not self._cadence_elapsed():
            result = {"status": "cadence_not_elapsed"}
        else:
            result = await self._cut_new_rc()

        if swept:
            result = {**result, "swept": swept}
        return result

    async def _handle_open_promotion(self, pr_number: int) -> dict[str, Any]:
        passed, summary = await self._prs.wait_for_ci(
            pr_number,
            timeout=60,
            poll_interval=15,
            stop_event=self._stop_event,
        )
        if passed:
            merged = await self._prs.merge_promotion_pr(pr_number)
            if merged:
                logger.info("Promoted RC PR #%d to main", pr_number)
                if self._state is not None:
                    try:
                        head_sha = await self._prs.get_pr_head_sha(pr_number)
                    except Exception:  # noqa: BLE001
                        logger.debug(
                            "Could not read head SHA for promoted PR #%d",
                            pr_number,
                            exc_info=True,
                        )
                        head_sha = ""
                    if head_sha:
                        self._state.set_last_green_rc_sha(head_sha)
                        self._state.reset_auto_reverts_in_cycle()
                return {"status": "promoted", "pr": pr_number}
            logger.warning("Promotion merge failed for PR #%d", pr_number)
            return {"status": "merge_failed", "pr": pr_number}

        if "timed out" in summary.lower():
            return {"status": "ci_pending", "pr": pr_number}

        issue_number = await self._file_failure_issue(pr_number, summary)
        await self._prs.post_comment(
            pr_number,
            f"Promotion CI failed — closing, next cadence cycle will retry.\n\n"
            f"Filed follow-up: #{issue_number}.\n\n{summary}",
        )
        await self._prs.close_issue(pr_number)
        logger.warning(
            "Promotion PR #%d closed after CI failure; filed #%d",
            pr_number,
            issue_number,
        )
        return {
            "status": "ci_failed",
            "pr": pr_number,
            "find_issue": issue_number,
        }

    async def _file_failure_issue(self, pr_number: int, summary: str) -> int:
        labels = self._config.find_label or ["hydraflow-find"]
        title = f"RC promotion #{pr_number} failed CI"
        body = (
            f"Automated promotion PR #{pr_number} failed CI and was closed.\n\n"
            f"The StagingPromotionLoop will retry on the next cadence tick.\n\n"
            "Investigate whether the failure is:\n"
            "- a real regression → fix before the next cadence\n"
            "- a flake → re-open the PR or wait for the next cycle\n"
            "- an environmental issue → fix CI config\n\n"
            f"```\n{summary}\n```"
        )
        try:
            return await self._prs.create_issue(title, body, labels)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to file hydraflow-find issue for PR %d", pr_number)
            return 0

    async def _cut_new_rc(self) -> dict[str, Any]:
        now = datetime.now(UTC)
        rc_branch = f"{self._config.rc_branch_prefix}{now.strftime('%Y-%m-%d-%H%M')}"
        try:
            await self._prs.create_rc_branch(rc_branch)
        except RuntimeError:
            logger.exception("Failed to create RC branch %s", rc_branch)
            return {"status": "rc_branch_failed"}

        title = f"Promote {rc_branch} → {self._config.main_branch}"
        body = (
            f"Automated release-candidate promotion PR.\n\n"
            f"Source: `{rc_branch}` (snapshot of `{self._config.staging_branch}` "
            f"cut at {now.isoformat(timespec='seconds')}).\n\n"
            "See ADR-0042 for context."
        )
        try:
            pr_number = await self._prs.create_promotion_pr(
                rc_branch=rc_branch,
                title=title,
                body=body,
            )
        except RuntimeError:
            logger.exception("Failed to open promotion PR for %s", rc_branch)
            return {"status": "promotion_pr_failed", "rc_branch": rc_branch}

        self._record_last_rc(now)
        logger.info("Opened promotion PR #%d for %s", pr_number, rc_branch)
        return {"status": "opened", "pr": pr_number, "rc_branch": rc_branch}

    def _cadence_path(self) -> Path:
        return self._config.data_root / "memory" / ".staging_promotion_last_rc"

    def _cadence_elapsed(self) -> bool:
        path = self._cadence_path()
        if not path.exists():
            return True
        try:
            last = datetime.fromisoformat(path.read_text().strip())
        except ValueError:
            return True
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        elapsed_hours = (datetime.now(UTC) - last).total_seconds() / 3600
        return elapsed_hours >= self._config.rc_cadence_hours

    def _record_last_rc(self, when: datetime) -> None:
        path = self._cadence_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(when.isoformat())

    def _sweep_path(self) -> Path:
        return self._config.data_root / "memory" / ".staging_promotion_last_sweep"

    def _sweep_due(self) -> bool:
        path = self._sweep_path()
        if not path.exists():
            return True
        try:
            last = datetime.fromisoformat(path.read_text().strip())
        except ValueError:
            return True
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        return (datetime.now(UTC) - last).total_seconds() >= 86400

    async def _sweep_if_due(self) -> int | None:
        if not self._sweep_due():
            return None
        deleted = await self._sweep_stale_rc_branches()
        path = self._sweep_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(datetime.now(UTC).isoformat())
        return deleted

    async def _sweep_stale_rc_branches(self) -> int:
        branches = await self._prs.list_rc_branches()
        if not branches:
            return 0

        retention_seconds = self._config.staging_rc_retention_days * 86400
        now = datetime.now(UTC)

        dated: list[tuple[str, datetime]] = []
        for branch, iso in branches:
            try:
                when = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            except ValueError:
                logger.debug("Un-parseable committer date %r on %s", iso, branch)
                continue
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
            dated.append((branch, when))
        if not dated:
            return 0

        # Newest RC is always preserved even if older than the retention window,
        # so we never leave zero RC snapshots on the repo.
        dated.sort(key=lambda b: b[1], reverse=True)
        newest = dated[0][0]
        open_pr = await self._prs.find_open_promotion_pr()
        keep_branch = open_pr.branch if open_pr is not None else None

        deleted = 0
        for branch, when in dated[1:]:
            if branch == keep_branch:
                continue
            if (now - when).total_seconds() < retention_seconds:
                continue
            if await self._prs.delete_branch(branch):
                deleted += 1
                logger.info("Swept stale RC branch %s", branch)
        if deleted:
            logger.info(
                "Retention sweep: deleted %d rc/* branches (kept newest=%s)",
                deleted,
                newest,
            )
        return deleted
