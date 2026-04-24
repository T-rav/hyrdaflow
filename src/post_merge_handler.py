"""Post-merge handling for the HydraFlow review pipeline."""

from __future__ import annotations

import logging
import re
from collections.abc import Coroutine
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

from acceptance_criteria import AcceptanceCriteriaGenerator
from config import HydraFlowConfig
from epic import EpicCompletionChecker
from events import EventBus, EventType, HydraFlowEvent
from knowledge_metrics import metrics as _metrics

if TYPE_CHECKING:
    from epic import EpicManager
    from ports import IssueStorePort, PRPort

from models import (
    CriterionVerdict,
    GitHubIssue,
    HitlEscalation,
    IssueOutcomeType,
    JudgeResult,
    JudgeVerdict,
    MergeApprovalContext,
    PRInfo,
    ReviewResult,
    StatusCallback,
    SystemAlertPayload,
    Task,
    VerificationCriterion,
    VisualGatePayload,
    VisualValidationDecision,
    VisualValidationPolicy,
)
from prompt_telemetry import PromptTelemetry
from reflections import clear_reflections, read_reflections
from repo_wiki import _load_tracked_active_entries
from repo_wiki_ingest import entries_from_reflections_log, ingest_phase_output
from retrospective import RetrospectiveCollector
from state import StateTracker
from verification_judge import VerificationJudge

if TYPE_CHECKING:
    from repo_wiki import RepoWikiStore
    from wiki_compiler import WikiCompiler

logger = logging.getLogger("hydraflow.post_merge_handler")

_T = TypeVar("_T")


async def _compile_tracked_topics_for_merge(
    *,
    tracked_root: Path,
    repo_slug: str,
    compiler: WikiCompiler | None,
) -> None:
    """Run WikiCompiler.compile_topic_tracked for every tracked topic
    that has ≥2 active entries.

    Runs inline on the post-merge hook chain so the next issue sees a
    deduplicated wiki instead of waiting for the RepoWikiLoop interval
    tick. Side effects are file mutations in ``{tracked_root}/{repo}/
    {topic}/``; those become uncommitted diffs that the existing
    ``RepoWikiLoop._maybe_open_maintenance_pr`` tick rolls up into a
    ``chore(wiki): maintenance`` PR.

    No-op when compiler is None, repo_slug is unset (unresolved config),
    tracked_root is missing, or no topic has enough entries to merit
    a compile pass.
    """
    if compiler is None or not repo_slug:
        return
    repo_dir = tracked_root / repo_slug
    if not repo_dir.is_dir():
        return
    for topic_dir in sorted(p for p in repo_dir.iterdir() if p.is_dir()):
        if len(_load_tracked_active_entries(topic_dir)) < 2:
            continue
        await compiler.compile_topic_tracked(
            tracked_root=tracked_root,
            repo=repo_slug,
            topic=topic_dir.name,
        )


async def _bridge_reflections_to_wiki(
    *,
    config: HydraFlowConfig,
    issue_number: int,
    repo: str,
    store: RepoWikiStore | None,
    compiler: WikiCompiler | None,
    event_bus: EventBus | None = None,
) -> None:
    """On merge: promote the issue's Reflexion log into wiki entries, then clear.

    Silent no-op when store or compiler is None (wiki disabled). Swallows
    wiki failures — we must not block the merge path on wiki trouble.
    """
    if store is None or compiler is None:
        return

    log = read_reflections(config, issue_number)
    if not log or not log.strip():
        return

    try:
        entries = entries_from_reflections_log(
            log=log, repo=repo, issue_number=issue_number
        )
        if entries:
            await ingest_phase_output(
                store=store,
                repo=repo,
                entries=entries,
                compiler=compiler,
                event_bus=event_bus,
            )
        clear_reflections(config, issue_number)
        _metrics.increment("reflections_bridged")
    except Exception:  # noqa: BLE001
        logger.warning(
            "reflection bridge failed for issue #%d; log kept for retry",
            issue_number,
            exc_info=True,
        )


_MANUAL_VERIFY_KEYWORDS = (
    "ui",
    "ux",
    "visual",
    "screen",
    "page",
    "button",
    "browser",
    "click",
    "manual",
    "frontend",
    "form",
)
_NON_MANUAL_WORK_KEYWORDS = (
    "refactor",
    "cleanup",
    "chore",
    "lint",
    "type",
    "typing",
    "test",
    "coverage",
    "docs",
    "documentation",
)
_USER_SURFACE_DIFF_RE = re.compile(
    r"^\+\+\+\s+b/("
    r"src/ui/|ui/|frontend/|web/|"
    r".*\.(?:tsx|jsx|css|scss|html)"
    r")",
    re.IGNORECASE | re.MULTILINE,
)


class PostMergeHandler:
    """Handles post-merge operations: AC generation, retrospective, judge, epic checks."""

    def __init__(
        self,
        config: HydraFlowConfig,
        state: StateTracker,
        prs: PRPort,
        event_bus: EventBus,
        ac_generator: AcceptanceCriteriaGenerator | None,
        retrospective: RetrospectiveCollector | None,
        verification_judge: VerificationJudge | None,
        epic_checker: EpicCompletionChecker | None,
        update_bg_worker_status: StatusCallback | None = None,
        epic_manager: EpicManager | None = None,
        store: IssueStorePort | None = None,
        *,
        wiki_store: RepoWikiStore | None = None,
        wiki_compiler: WikiCompiler | None = None,
    ) -> None:
        self._config = config
        self._state = state
        self._prs = prs
        self._bus = event_bus
        self._event_bus = event_bus  # Named exposure for reflection-bridge hook
        self._ac_generator = ac_generator
        self._retrospective = retrospective
        self._verification_judge = verification_judge
        self._epic_checker = epic_checker
        self._update_bg_worker_status = update_bg_worker_status
        self._prompt_telemetry = PromptTelemetry(config)
        self._epic_manager = epic_manager
        self._store = store
        self._wiki_store = wiki_store
        self._wiki_compiler = wiki_compiler

    def _should_defer_merge(self, issue_number: int) -> bool:
        """Return True if merge should be deferred for bundled epic strategy."""
        if self._epic_manager is None:
            return False
        parent_epics = self._epic_manager.find_parent_epics(issue_number)
        for epic_num in parent_epics:
            epic = self._state.get_epic_state(epic_num)
            if epic is not None and epic.merge_strategy != "independent":
                return True
        return False

    def _persist_completed_timeline(
        self,
        pr: PRInfo,
        issue: GitHubIssue | Task,
        result: ReviewResult,
        merge_seconds: float,
    ) -> None:
        """Build and persist a CompletedTimeline for the merged issue."""
        from models import CompletedTimeline  # noqa: PLC0415

        phase_durations: dict[str, float] = {}
        if result.duration_seconds > 0:
            phase_durations["review"] = round(result.duration_seconds, 1)
        # Pull worker result meta for implementation duration
        meta = self._state.get_worker_result_meta(pr.issue_number)
        dur = meta.get("duration_seconds") if meta else None
        if dur:
            phase_durations["implement"] = round(float(dur), 1)

        timeline = CompletedTimeline(
            issue_number=pr.issue_number,
            title=issue.title,
            completed_at=datetime.now(UTC).isoformat(),
            total_duration_seconds=round(merge_seconds, 1)
            if merge_seconds > 0
            else 0.0,
            phase_durations=phase_durations,
            pr_number=pr.number,
        )
        self._state.record_completed_timeline(timeline)

    async def _notify_epic_approval(self, issue_number: int) -> None:
        """Notify EpicManager that a child issue's PR was approved."""
        if self._epic_manager is None:
            return
        parent_epics = self._epic_manager.find_parent_epics(issue_number)
        for epic_num in parent_epics:
            try:
                await self._epic_manager.on_child_approved(epic_num, issue_number)
            except (RuntimeError, OSError, ValueError):
                logger.warning(
                    "Epic approval notification failed for child #%d of epic #%d",
                    issue_number,
                    epic_num,
                    exc_info=True,
                )

    async def _run_visual_gate(self, ctx: MergeApprovalContext) -> bool:
        """Run the visual validation gate; return True if merge may proceed."""
        if not self._config.visual_gate_enabled:
            return True
        if ctx.visual_gate_fn is None:
            logger.warning(
                "PR #%d: visual_gate_enabled but no visual_gate_fn provided — blocking merge",
                ctx.pr.number,
            )
            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.VISUAL_GATE,
                    data=VisualGatePayload(
                        pr=ctx.pr.number,
                        issue=ctx.issue.id,
                        worker=ctx.worker_id,
                        verdict="blocked",
                        reason="no visual_gate_fn provided to handle_approved",
                    ),
                )
            )
            return False
        return await ctx.visual_gate_fn(ctx.pr, ctx.issue, ctx.result, ctx.worker_id)

    async def _run_ci_gate(self, ctx: MergeApprovalContext) -> bool:
        """Run CI gate if configured; return True to proceed, False to abort."""
        if self._config.max_ci_fix_attempts > 0:
            return await ctx.ci_gate_fn(
                ctx.pr,
                ctx.issue,
                self._config.workspace_path_for_issue(ctx.pr.issue_number),
                ctx.result,
                ctx.worker_id,
                code_scanning_alerts=ctx.code_scanning_alerts,
            )
        return True

    async def handle_approved(
        self,
        ctx: MergeApprovalContext,
    ) -> None:
        """Attempt merge for an approved PR (with optional CI gate).

        For epic children with bundled merge strategies, the PR is approved
        but merge is deferred until all siblings are ready.
        """
        pr = ctx.pr
        # Idempotency guard: don't re-run post-merge side effects if this
        # issue has already been recorded as merged. Protects against retries,
        # race conditions, and duplicate approval events.
        existing = self._state.get_outcome(pr.issue_number)
        if existing is not None and existing.outcome == IssueOutcomeType.MERGED:
            logger.info(
                "PR #%d (issue #%d): skipping handle_approved — "
                "already recorded as MERGED at %s",
                pr.number,
                pr.issue_number,
                existing.closed_at,
            )
            return
        issue = ctx.issue
        result = ctx.result
        diff = ctx.diff
        worker_id = ctx.worker_id
        escalate_fn = ctx.escalate_fn
        publish_fn = ctx.publish_fn
        visual_decision = ctx.visual_decision
        merge_conflict_fix_fn = ctx.merge_conflict_fix_fn

        # Notify EpicManager of approval (for bundled merge coordination)
        if self._epic_manager is not None:
            await self._notify_epic_approval(pr.issue_number)

        # Check if merge should be deferred for bundled epic strategy
        if self._should_defer_merge(pr.issue_number):
            logger.info(
                "PR #%d (issue #%d): deferring merge — "
                "bundled epic strategy requires all siblings to be approved",
                pr.number,
                pr.issue_number,
            )
            return

        if not await self._run_ci_gate(ctx):
            return

        if not await self._run_visual_gate(ctx):
            return

        # Normalize PR title to canonical "Fixes #N: title" before merge
        # so the merge commit and event history show a consistent format.
        try:
            expected_title = self._prs.expected_pr_title(issue.id, issue.title)
            await self._prs.update_pr_title(pr.number, expected_title)
        except Exception:
            logger.debug(
                "Could not normalize PR #%d title before merge",
                pr.number,
                exc_info=True,
            )

        await publish_fn(pr, worker_id, "merging")
        success = await self._prs.merge_pr(pr.number)
        mergeable: bool | None = None
        if not success:
            mergeable = await self._prs.get_pr_mergeable(pr.number)
            if mergeable is False and merge_conflict_fix_fn is not None:
                logger.info(
                    "PR #%d merge failed due to conflict — attempting standard review auto-fix",
                    pr.number,
                )
                await publish_fn(pr, worker_id, "merge_fix")
                recovered = await merge_conflict_fix_fn(pr, issue, worker_id)
                if recovered:
                    await publish_fn(pr, worker_id, "merging")
                    success = await self._prs.merge_pr(pr.number)

        if success:
            result.merged = True
            if self._store is not None:
                self._store.mark_merged(pr.issue_number)
            # Compute merge duration before consolidated state update
            merge_seconds: float = 0.0
            if issue.created_at:
                try:
                    created = datetime.fromisoformat(issue.created_at)
                    merge_seconds = (datetime.now(UTC) - created).total_seconds()
                except (ValueError, TypeError):
                    pass
            self._persist_completed_timeline(pr, issue, result, merge_seconds)
            # Consolidated state mutations + threshold check
            proposals = self._state.record_successful_merge(
                pr.issue_number,
                pr.number,
                ci_fix_attempts=result.ci_fix_attempts,
                merge_duration_seconds=merge_seconds,
                quality_fix_rate_threshold=self._config.quality_fix_rate_threshold,
                approval_rate_threshold=self._config.approval_rate_threshold,
                hitl_rate_threshold=self._config.hitl_rate_threshold,
            )
            for proposal in proposals:
                self._state.mark_threshold_fired(proposal["name"])
                await self._bus.publish(
                    HydraFlowEvent(
                        type=EventType.SYSTEM_ALERT,
                        data=SystemAlertPayload(
                            message=(
                                f"Threshold breached: {proposal['metric']} "
                                f"({proposal['value']:.2f} vs {proposal['threshold']:.2f}). "
                                f"{proposal['action']}"
                            ),
                            source="threshold_check",
                            threshold=proposal,
                        ),
                    )
                )
            await self._prs.swap_pipeline_labels(
                pr.issue_number, self._config.fixed_label[0]
            )
            await self._prs.close_issue(pr.issue_number)
            await self._post_inference_totals_comment(pr, issue)
            await self._run_post_merge_hooks(pr, issue, result, diff, visual_decision)
        else:
            logger.warning("PR #%d merge failed — escalating to HITL", pr.number)
            await publish_fn(pr, worker_id, "escalating")
            if mergeable is None:
                mergeable = await self._prs.get_pr_mergeable(pr.number)
            cause = "PR merge failed on GitHub"
            comment = (
                "**Merge failed** — PR could not be merged. Escalating to human review."
            )
            if mergeable is False:
                cause = "PR merge failed on GitHub: merge conflict"
                comment = (
                    "**Merge failed** — PR has merge conflicts on GitHub. "
                    "Escalating to human review."
                )
            elif mergeable is True:
                cause = "PR merge failed on GitHub: merge blocked (non-conflict)"

            await escalate_fn(
                HitlEscalation(
                    issue_number=pr.issue_number,
                    pr_number=pr.number,
                    cause=cause,
                    origin_label=self._config.review_label[0],
                    comment=comment,
                    event_cause="merge_failed",
                    task=issue,
                )
            )

    async def _post_inference_totals_comment(self, pr: PRInfo, issue: Task) -> None:
        """Post PR inference totals to the issue after a successful merge."""
        totals = self._prompt_telemetry.get_pr_totals(pr.number)
        if not totals:
            return
        token_total = int(totals.get("total_tokens", 0))
        est_total = int(totals.get("total_est_tokens", 0))
        calls = int(totals.get("inference_calls", 0))
        actual_calls = int(totals.get("actual_usage_calls", 0))
        source = "actual usage" if actual_calls > 0 else "estimated usage"

        body = (
            "## Inference Usage\n\n"
            f"- PR: #{pr.number}\n"
            f"- Inference calls: {calls}\n"
            f"- Total tokens: {token_total:,} ({source})\n"
            f"- Estimated fallback tokens: {est_total:,}\n"
        )
        try:
            await self._prs.post_comment(issue.id, body)
        except (RuntimeError, OSError, ValueError):
            logger.warning(
                "Could not post inference usage comment for issue #%d (PR #%d)",
                issue.id,
                pr.number,
                exc_info=True,
            )

    async def _safe_hook(
        self,
        name: str,
        coro: Coroutine[Any, Any, _T],
        issue_number: int,
    ) -> _T | None:
        """Await a post-merge hook, recording failures for visibility."""
        try:
            return await coro
        except (RuntimeError, OSError, ValueError) as exc:
            error_msg = str(exc)[:500]
            logger.warning(
                "%s failed for issue #%d",
                name,
                issue_number,
                exc_info=True,
            )
            try:
                self._state.record_hook_failure(issue_number, name, error_msg)
            except (RuntimeError, OSError, ValueError):
                logger.debug(
                    "Failed to record hook failure for issue #%d",
                    issue_number,
                    exc_info=True,
                )
            try:
                await self._bus.publish(
                    HydraFlowEvent(
                        type=EventType.SYSTEM_ALERT,
                        data=SystemAlertPayload(
                            message=(
                                f"Post-merge hook '{name}' failed for issue "
                                f"#{issue_number}: {error_msg}"
                            ),
                            source="post_merge_hook",
                            hook_name=name,
                            issue=issue_number,
                        ),
                    )
                )
            except (RuntimeError, OSError, ValueError):
                logger.debug(
                    "Failed to publish hook failure event for issue #%d",
                    issue_number,
                    exc_info=True,
                )
            try:
                await self._prs.post_comment(
                    issue_number,
                    f"**Post-merge hook failure:** `{name}` failed.\n\n"
                    f"Error: {error_msg}\n\n"
                    f"---\n*HydraFlow PostMergeHandler*",
                )
            except (RuntimeError, OSError, ValueError):
                logger.warning(
                    "Could not post hook-failure comment for issue #%d",
                    issue_number,
                    exc_info=True,
                )
            return None

    async def _run_post_merge_hooks(
        self,
        pr: PRInfo,
        issue: Task,
        result: ReviewResult,
        diff: str,
        visual_decision: VisualValidationDecision | None = None,
    ) -> None:
        """Run non-blocking post-merge hooks (AC, retrospective, judge, epic)."""
        if self._ac_generator:
            await self._safe_hook(
                "AC generation",
                self._ac_generator.generate(
                    issue_number=pr.issue_number,
                    pr_number=pr.number,
                    issue=GitHubIssue.from_task(issue),
                    diff=diff,
                ),
                pr.issue_number,
            )
        if self._retrospective:
            retro_status = "ok"
            try:
                await self._retrospective.record(
                    issue_number=pr.issue_number,
                    pr_number=pr.number,
                    review_result=result,
                )
            except (RuntimeError, OSError, ValueError):
                retro_status = "error"
                logger.warning(
                    "retrospective failed for issue #%d",
                    pr.issue_number,
                    exc_info=True,
                )
            if self._update_bg_worker_status:
                try:
                    self._update_bg_worker_status(
                        "retrospective",
                        retro_status,
                        {"issue_number": pr.issue_number, "pr_number": pr.number},
                    )
                except (RuntimeError, OSError, ValueError):
                    logger.warning(
                        "retrospective status callback failed for issue #%d",
                        pr.issue_number,
                        exc_info=True,
                    )

        if self._wiki_store is not None and self._wiki_compiler is not None:
            await self._safe_hook(
                "reflection bridge",
                _bridge_reflections_to_wiki(
                    config=self._config,
                    issue_number=pr.issue_number,
                    repo=self._config.repo or "",
                    store=self._wiki_store,
                    compiler=self._wiki_compiler,
                    event_bus=self._event_bus,
                ),
                pr.issue_number,
            )
            # P5: compile the tracked wiki inline so the next issue
            # sees a deduplicated view instead of waiting for the
            # RepoWikiLoop interval. File mutations roll into the
            # existing chore(wiki) maintenance PR flow.
            await self._safe_hook(
                "wiki compile on merge",
                _compile_tracked_topics_for_merge(
                    tracked_root=(self._config.repo_root / self._config.repo_wiki_path),
                    repo_slug=self._config.repo or "",
                    compiler=self._wiki_compiler,
                ),
                pr.issue_number,
            )

        verdict: JudgeVerdict | None = None
        if self._verification_judge:
            verdict = await self._safe_hook(
                "verification judge",
                self._verification_judge.judge(
                    issue_number=pr.issue_number,
                    pr_number=pr.number,
                    diff=diff,
                ),
                pr.issue_number,
            )

        judge_result = self._get_judge_result(issue, pr, verdict)
        if judge_result is not None and self._should_create_verification_issue(
            issue, judge_result, diff, visual_decision
        ):
            # Write verification record to JSONL (no GitHub issue — verify loop removed)
            try:
                import json as _json  # noqa: PLC0415

                rec = {
                    "issue_id": issue.id,
                    "pr_number": pr.number,
                    "title": f"Verify: {issue.title[:80]}",
                    "timestamp": datetime.now(UTC).isoformat(),
                }
                path = self._config.data_path("memory", "verification_records.jsonl")
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a") as f:
                    f.write(_json.dumps(rec) + "\n")
                logger.info(
                    "Verification record written for issue #%d (PR #%d)",
                    issue.id,
                    pr.number,
                )
            except Exception:  # noqa: BLE001
                logger.debug("Failed to write verification record", exc_info=True)

        # Notify EpicManager of child completion (handles auto-close internally)
        if self._epic_manager is not None:
            epic_state = self._state.get_epic_state(pr.issue_number)
            if epic_state is None:
                # Check all tracked epics if this issue is a child
                for es in self._state.get_all_epic_states().values():
                    if pr.issue_number in es.child_issues:
                        await self._safe_hook(
                            "epic child completion",
                            self._epic_manager.on_child_completed(
                                es.epic_number, pr.issue_number
                            ),
                            pr.issue_number,
                        )
                        break
        elif self._epic_checker:
            # Fallback to legacy checker if EpicManager is not wired
            await self._safe_hook(
                "epic completion check",
                self._epic_checker.check_and_close_epics(pr.issue_number),
                pr.issue_number,
            )

    def _get_judge_result(
        self,
        issue: Task,
        pr: PRInfo,
        verdict: JudgeVerdict | None,
    ) -> JudgeResult | None:
        """Convert a JudgeVerdict into a JudgeResult for verification issue creation."""
        if verdict is None:
            return None

        criteria = [
            VerificationCriterion(
                description=cr.criterion,
                passed=cr.verdict == CriterionVerdict.PASS,
                details=cr.reasoning,
            )
            for cr in verdict.criteria_results
        ]

        return JudgeResult(
            issue_number=issue.id,
            pr_number=pr.number,
            criteria=criteria,
            verification_instructions=verdict.verification_instructions,
            summary=verdict.summary,
        )

    def _should_create_verification_issue(
        self,
        issue: Task,
        judge_result: JudgeResult,
        diff: str,
        visual_decision: VisualValidationDecision | None = None,
    ) -> bool:
        """Return True only when the change needs human/manual verification.

        When a ``VisualValidationDecision`` is provided, it takes precedence
        over the legacy heuristic for UI-surface detection:
        - REQUIRED → always create a verification issue (if instructions exist).
        - SKIPPED  → skip the user-surface diff check (still honours manual cues).
        """
        instructions = judge_result.verification_instructions.strip()
        if not instructions:
            logger.info(
                "Skipping verification issue for #%d: no verification instructions",
                issue.id,
            )
            return False

        # Visual validation override: REQUIRED forces creation
        if (
            visual_decision is not None
            and visual_decision.policy == VisualValidationPolicy.REQUIRED
        ):
            logger.info(
                "Creating verification issue for #%d: visual validation required (%s)",
                issue.id,
                visual_decision.reason,
            )
            return True

        issue_text = f"{issue.title}\n{issue.body}".lower()
        instructions_text = instructions.lower()
        has_manual_cues = any(
            kw in instructions_text or kw in issue_text
            for kw in _MANUAL_VERIFY_KEYWORDS
        )

        # When visual validation says SKIPPED, skip the diff-based user-surface check
        if (
            visual_decision is not None
            and visual_decision.policy == VisualValidationPolicy.SKIPPED
        ):
            touches_user_surface = False
        else:
            touches_user_surface = bool(_USER_SURFACE_DIFF_RE.search(diff or ""))

        if has_manual_cues or touches_user_surface:
            return True

        if any(kw in issue_text for kw in _NON_MANUAL_WORK_KEYWORDS):
            logger.info(
                "Skipping verification issue for #%d: non-user-facing change",
                issue.id,
            )
            return False

        logger.info(
            "Skipping verification issue for #%d: no human-verification signal",
            issue.id,
        )
        return False

    # _create_verification_issue removed — verification records now written to JSONL
