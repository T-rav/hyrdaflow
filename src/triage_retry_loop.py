"""TriageRetryLoop — autonomous re-entry for parked issues (ADR-0063 W2).

Triage parks an issue with ``parked_label`` when the body lacks enough
detail to plan the work. Without this loop the issue sits indefinitely,
waiting for a human comment. Slice #4 of the documentation-audit roadmap
(see ``docs/arch/factory_phase_drift_2026-05-12.md``) identified triage as
the *only* factory phase with no autonomous re-entry path.

This loop closes that gap. Every ``triage_retry_interval`` seconds it:

1. Lists open issues carrying ``parked_label``.
2. For each, honours the 24h-since-last-retry floor (independent of the
   tick interval so a 6h cadence loop still respects the daily floor).
3. If the per-issue counter is below ``triage_retry_max_attempts``, bumps
   the counter, posts a comment that surfaces the *original parking
   reason* as context for the next triage pass, and swaps the parked
   label back to ``find_label`` so ``TriagePhase`` picks the issue up on
   the next pipeline poll.
4. Otherwise files a ``hitl-escalation`` issue with the
   ``triage_retry_exhausted_label`` sub-label, leaving the original
   issue parked + linked from the escalation body.

A reconciliation step at the top of every tick clears retry counters
for issues that have since closed (human-intervention path, dedup, or
the eventual successful triage on the next pass).

Pattern reference: ``src/memory_backlog_loop.py`` for the
counter-bump + 3-strikes-escalation shape; ``src/stale_issue_loop.py``
for the issue-scan + per-issue gate shape. ADR-0049 in-body kill-switch
gate + static config gate ensure operators can disable the loop without
a redeploy.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps  # noqa: TCH001
from exception_classify import reraise_on_credit_or_bug

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from pr_manager import PRManager
    from state import StateTracker

logger = logging.getLogger("hydraflow.triage_retry_loop")

# Marker the loop writes when it re-dispatches an issue. The next triage
# pass treats body text below this anchor as the prior parking reason and
# folds it into the next clarity evaluation. The anchor is also used by
# the loop itself to harvest the most recent parking reason — see
# ``_extract_parking_reason``.
_RETRY_MARKER = "<!-- triage-retry-loop:context -->"

# Regex that extracts the "Missing:" bullet list out of the
# ``park_issue`` comment template (see ``src/phase_utils.py::park_issue``).
# The captured group is the bullet block; the loop joins it back together
# when composing the retry comment.
_PARKING_REASON_RE = re.compile(
    r"\*\*Missing:\*\*\s*\n((?:^- .+\n?)+)",
    re.MULTILINE,
)


class TriageRetryLoop(BaseBackgroundLoop):
    """Re-runs parked-issue triage every ``triage_retry_interval`` seconds.

    Per-issue retry counter persisted in ``StateTracker``. After
    ``triage_retry_max_attempts`` autonomous retries the loop escalates
    to HITL via the ``triage_retry_exhausted_label`` sub-label. ADR-0063
    W2 — the factory-phase-drift-mitigation workstream that closes the
    only HITL gap in the eight-phase pipeline.
    """

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        state: StateTracker,
        pr_manager: PRManager,
        deps: LoopDeps,
    ) -> None:
        super().__init__(
            worker_name="triage_retry",
            config=config,
            deps=deps,
            run_on_startup=False,
        )
        self._state = state
        self._pr = pr_manager

    def _get_default_interval(self) -> int:
        return self._config.triage_retry_interval

    async def _do_work(self) -> dict[str, Any] | None:
        """Re-dispatch each parked issue that has waited long enough."""
        # ADR-0049 in-body kill-switch gate. Operators can flip the loop
        # off from the UI without a redeploy.
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        # Static config gate (deploy-time disable). Defense-in-depth.
        if not self._config.triage_retry_loop_enabled:
            return {"status": "config_disabled"}

        stats: dict[str, int] = {
            "scanned": 0,
            "retried": 0,
            "escalated": 0,
            "skipped_recent": 0,
            "skipped_disabled": 0,
            "reconciled": 0,
        }

        # 1. Reconcile counters for issues that closed since the last
        # tick — without this the retry counter sticks at N for issues
        # the human resolved manually, and the next park-then-retry of
        # the same issue would skip straight to escalation.
        try:
            reconciled = await self._reconcile_closed_parked()
            stats["reconciled"] = reconciled
        except Exception as exc:  # noqa: BLE001
            reraise_on_credit_or_bug(exc)
            logger.warning(
                "triage_retry: reconcile_closed_parked failed", exc_info=True
            )

        parked_label = self._config.parked_label[0]
        try:
            issues = await self._pr.list_issues_by_label(parked_label)
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning(
                "triage_retry: list_issues_by_label(%s) failed",
                parked_label,
                exc_info=True,
            )
            return stats

        now = datetime.now(UTC)
        floor = timedelta(seconds=self._config.triage_retry_interval)

        for issue in issues:
            number = int(issue.get("number") or 0)
            if number <= 0:
                continue
            stats["scanned"] += 1

            # Respect the 24h-between-retries floor independently of the
            # tick interval. Operators can lower the interval to debug
            # without accidentally hammering a flaky author.
            last_attempt_iso = self._state.get_triage_retry_last_attempt(number)
            if last_attempt_iso:
                try:
                    last_attempt = datetime.fromisoformat(last_attempt_iso)
                    if last_attempt.tzinfo is None:
                        last_attempt = last_attempt.replace(tzinfo=UTC)
                    if now - last_attempt < floor:
                        stats["skipped_recent"] += 1
                        continue
                except ValueError:
                    logger.debug(
                        "triage_retry: corrupt last-attempt timestamp on #%d: %r",
                        number,
                        last_attempt_iso,
                    )

            attempts = self._state.get_triage_retry_attempts(number)
            try:
                if attempts >= self._config.triage_retry_max_attempts:
                    await self._escalate_to_hitl(number, issue, attempts)
                    stats["escalated"] += 1
                else:
                    await self._retry_triage(number, issue, attempts)
                    stats["retried"] += 1
                self._state.set_triage_retry_last_attempt(number, now.isoformat())
            except Exception as exc:  # noqa: BLE001
                reraise_on_credit_or_bug(exc)
                logger.warning(
                    "triage_retry: retry/escalation failed for #%d",
                    number,
                    exc_info=True,
                )
                continue

        return {"status": "ok", **stats}

    async def _retry_triage(
        self, issue_number: int, issue: dict[str, Any], prior_attempts: int
    ) -> None:
        """Bump the counter, comment with context, and route back to find."""
        attempts = self._state.inc_triage_retry_attempts(issue_number)
        parking_reason = self._extract_parking_reason(issue.get("body") or "")
        comment = self._compose_retry_comment(
            attempts=attempts,
            max_attempts=self._config.triage_retry_max_attempts,
            parking_reason=parking_reason,
        )
        await self._pr.post_comment(issue_number, comment)
        # Swap parked → find so TriagePhase picks the issue up on the
        # next pipeline poll. The find label is the canonical re-entry
        # point — TriagePhase polls find-labeled issues every tick.
        find_label = self._config.find_label[0]
        await self._pr.swap_pipeline_labels(issue_number, find_label)
        # ``swap_pipeline_labels`` only removes labels in
        # ``all_pipeline_labels`` — ``parked_label`` is intentionally
        # outside that set so dedup helpers don't fight pipeline state.
        # Remove it explicitly here.
        parked_label = self._config.parked_label[0]
        try:
            await self._pr.remove_label(issue_number, parked_label)
        except Exception as exc:  # noqa: BLE001
            reraise_on_credit_or_bug(exc)
            logger.debug(
                "triage_retry: failed to drop %s from #%d (label may already be gone)",
                parked_label,
                issue_number,
                exc_info=True,
            )
        logger.info(
            "triage_retry: re-dispatched #%d to find (attempt %d/%d)",
            issue_number,
            attempts,
            self._config.triage_retry_max_attempts,
        )

    async def _escalate_to_hitl(
        self, issue_number: int, issue: dict[str, Any], attempts: int
    ) -> None:
        """File a hitl-escalation companion issue when the retry budget is gone."""
        title_text = issue.get("title") or f"#{issue_number}"
        parking_reason = self._extract_parking_reason(issue.get("body") or "")
        body = self._compose_escalation_body(
            issue_number=issue_number,
            title=title_text,
            attempts=attempts,
            parking_reason=parking_reason,
        )
        escalation_title = (
            f"HITL: triage retry exhausted for #{issue_number} ({title_text[:60]})"
        )
        labels = [
            self._config.hitl_escalation_label[0],
            self._config.triage_retry_exhausted_label[0],
        ]
        await self._pr.create_issue(escalation_title, body, labels)
        # Leave the parked label on the original issue — the human now
        # owns the clarification path. Bump the attempt counter one more
        # time so a repeat tick (before the escalation issue closes) is
        # treated as already-escalated and skipped by the floor gate.
        self._state.inc_triage_retry_attempts(issue_number)
        logger.warning(
            "triage_retry: escalated #%d to HITL after %d retries",
            issue_number,
            attempts,
        )

    def _compose_retry_comment(
        self, *, attempts: int, max_attempts: int, parking_reason: str
    ) -> str:
        """Build the comment posted when re-dispatching an issue back to triage."""
        reason_block = parking_reason.strip() or "(no original parking reason captured)"
        return (
            "## Auto-Retry: Triage\n\n"
            f"HydraFlow's TriageRetryLoop is re-evaluating this parked issue "
            f"(attempt {attempts}/{max_attempts}, ADR-0063 W2).\n\n"
            "**Original parking reason:**\n"
            f"{reason_block}\n\n"
            f"{_RETRY_MARKER}\n\n"
            "If you've added the requested detail, the next triage pass will "
            "pick it up automatically. If not, the issue will be re-evaluated "
            "again in ~24h. After the retry budget is exhausted, it escalates "
            "to a human via `hitl-escalation`.\n\n"
            "---\n"
            "*Generated by HydraFlow TriageRetryLoop — see "
            "[ADR-0063](docs/adr/0063-factory-phase-drift-mitigation.md) W2.*"
        )

    def _compose_escalation_body(
        self,
        *,
        issue_number: int,
        title: str,
        attempts: int,
        parking_reason: str,
    ) -> str:
        """Build the HITL escalation issue body when the retry budget is gone."""
        reason_block = parking_reason.strip() or "(no original parking reason captured)"
        return (
            f"`TriageRetryLoop` has re-dispatched issue #{issue_number} "
            f"({title}) to triage {attempts} times without resolution. The "
            "autonomous retry budget is exhausted; a human now owns the "
            "clarification path.\n\n"
            "**Original parking reason (from the most recent retry):**\n"
            f"{reason_block}\n\n"
            "**Closing this issue clears the retry counter** so the parked "
            "issue can re-enter the autonomous retry chain if/when it is "
            "re-opened with new context.\n\n"
            "Per [ADR-0063](docs/adr/0063-factory-phase-drift-mitigation.md) "
            "W2 (factory-phase drift mitigation — triage is the only phase "
            "with no autonomous re-entry path)."
        )

    def _extract_parking_reason(self, body: str) -> str:
        """Pull the bullet list of missing info out of the parked issue body.

        ``park_issue`` writes a comment with a ``**Missing:**`` block; on
        re-trigger the parked-comment ends up in the issue body's comment
        thread but the *most recent* TriageRetryLoop comment also includes
        the same block. We scan with a regex that tolerates either source,
        falling back to an empty string when neither is present.
        """
        if not body:
            return ""
        # Newest match wins — the regex is non-greedy by construction and
        # ``findall`` walks in document order. The last comment in the
        # body is the most recent.
        matches = _PARKING_REASON_RE.findall(body)
        if not matches:
            return ""
        return matches[-1].strip()

    async def _reconcile_closed_parked(self) -> int:
        """Clear retry counters for parked issues that have since closed.

        Without this, a closed-then-reopened-then-reparked issue would
        leapfrog the autonomous retry chain and escalate immediately. The
        cleanup is best-effort — failures log and the next tick retries.
        """
        attempts_dict = dict(self._state._data.triage_retry_attempts)  # type: ignore[attr-defined]
        if not attempts_dict:
            return 0
        cleared = 0
        for key in list(attempts_dict.keys()):
            try:
                issue_number = int(key)
            except (TypeError, ValueError):
                continue
            try:
                state = await self._pr.get_issue_state(issue_number)
            except Exception as exc:  # noqa: BLE001
                reraise_on_credit_or_bug(exc)
                logger.debug(
                    "triage_retry: get_issue_state(#%d) failed — leaving counter intact",
                    issue_number,
                    exc_info=True,
                )
                continue
            if state and state.upper() != "OPEN":
                self._state.clear_triage_retry_attempts(issue_number)
                cleared += 1
        return cleared
