"""Review processing for the HydraFlow orchestrator."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from issue_cache import IssueCache
    from ports import IssueStorePort, PRPort, ReviewInsightStorePort, WorkspacePort
    from precondition_gate import PreconditionGate
    from retrospective_queue import RetrospectiveQueue
    from review_advisor import (  # noqa: TCH004 — used in __init__ + sig
        PostVerifyResult,
        ReviewPlan,
    )
    from visual_validator import VisualValidator
    from wiki_compiler import (  # noqa: TCH004 — used in __init__ signature
        CorroborationDecision,
        WikiCompiler,
    )


from opentelemetry import metrics

from adr_utils import (
    adr_validation_reasons,
    check_adr_duplicate,
    extract_adr_section,
    is_adr_issue_title,
)
from baseline_policy import BaselinePolicy
from comment_formatter import SelfReviewError
from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from harness_insights import FailureCategory, HarnessInsightStore
from merge_conflict_resolver import MergeConflictResolver
from models import (
    BaselineApprovalResult,
    CodeScanningAlert,
    ConflictResolutionResult,
    HitlEscalation,
    JudgeResult,
    MergeApprovalContext,
    PipelineStage,
    PRInfo,
    ReviewResult,
    ReviewVerdict,
    StatusCallback,
    Task,
    VisualEvidence,
    VisualGatePayload,
    VisualScreenResult,
    VisualValidationDecision,
    VisualValidationReport,
)
from phase_utils import (
    MemorySuggester,
    _sentry_transaction,
    log_exception_with_bug_classification,
    publish_review_status,
    record_harness_failure,
    release_batch_in_flight,
    run_concurrent_batch,
    run_with_fatal_guard,
    store_lifecycle,
)
from post_merge_handler import PostMergeHandler
from repo_wiki import (
    RepoWikiStore,
    WikiEntry,
    classify_topic,
    increment_corroboration,
)
from review_insights import (
    _PROPOSAL_STALE_DAYS,
    CATEGORY_DESCRIPTIONS,
    ReviewRecord,
    analyze_patterns,
    build_insight_issue_body,
    extract_categories,
    verify_proposals,
)
from reviewer import ReviewRunner
from state import StateTracker
from task_source import TaskTransitioner
from transcript_summarizer import TranscriptSummarizer

logger = logging.getLogger("hydraflow.review_phase")

# ``_AdvisorRole`` pins the runner-protocol role contract — used by
# ``_PostVerifyRunner.run`` (T24.5 closed I1+I2: explicit role beats
# substring detection on the prompt). Module-scope so the inner
# ``_PostVerifyRunner`` class body can reference it via closure when
# ``_build_post_verify_runner`` is invoked.
_AdvisorRole = Literal["pre_flight", "mid_flight", "post_verify"]

# OTel metric instruments for the post-verify advisor's veto-retry loop.
# Module-level so the proxy meter delegates to the registered MeterProvider
# at call time. No-op when no provider is set (production today). Tests
# install an InMemoryMetricReader to read counter values.
# Per ADR-0055, OTel is the project's telemetry layer.
_advisor_meter = metrics.get_meter("hydraflow.review_phase.advisor")
_veto_retries_total = _advisor_meter.create_counter(
    "review_advisor_veto_retries_total",
    description=(
        "Count of advisor-driven veto retry triggers, labeled by surface "
        "and the attempt number that just kicked off (1, 2, ..., or "
        "'exhausted' when the retry budget runs out)."
    ),
)
_veto_recovered_total = _advisor_meter.create_counter(
    "review_advisor_veto_recovered_total",
    description=(
        "Count of post-retry advisor APPROVE verdicts (advisor recovered "
        "from a prior VETO without HITL), labeled by surface."
    ),
)
_veto_exhausted_total = _advisor_meter.create_counter(
    "review_advisor_veto_exhausted_total",
    description=(
        "Count of advisor veto-retry exhaustions that escalated to HITL, "
        "labeled by surface."
    ),
)


def _emit_advisor_loop_metric(counter: Any, attrs: dict[str, Any]) -> None:
    """Best-effort counter increment. Telemetry must never alter business
    control flow (ADR-0055)."""
    try:
        counter.add(1, attrs)
    except Exception:
        logger.debug("advisor loop metric emit failed", exc_info=True)


# T37 — tighten wiki-ingest self-modification detection.
#
# The old detector substring-matched ``src/review_advisor.py`` / ``src/review_phase.py``
# anywhere in the candidate ingest content; a purely descriptive review summary
# that named those paths in passing (e.g., "review found a type-hint gap in
# src/review_advisor.py") would synthesize the pseudo diff header and force
# veto authority on what was a benign wiki entry. Fail-closed but noisy.
#
# These patterns gate synthesis on modification *context*, not bare mentions:
#   1. Already-formed unified-diff headers (real diff content embedded).
#   2. Path inside a fenced ```diff / ```patch block.
#   3. Editorial verbs ("modified", "changed", "edited", "updated", "patched")
#      immediately preceding the path.
# Anything else — prose mention, type-hint reference, file-path-in-error-log —
# is treated as a non-modification mention and does NOT synthesize the header.
# T29's self-mod guard still fires when a real modification context is seen.
_SELF_MOD_SYNTHESIS_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Already-formed diff headers (real diff content embedded in transcript).
    re.compile(r"diff --git a/(src/(?:review_advisor|review_phase)\.py)"),
    re.compile(r"\+\+\+ b/(src/(?:review_advisor|review_phase)\.py)"),
    re.compile(r"--- a/(src/(?:review_advisor|review_phase)\.py)"),
    # Fenced patch / diff block containing the path.
    re.compile(
        r"```(?:diff|patch)\b[^`]*?(src/(?:review_advisor|review_phase)\.py)",
        re.DOTALL,
    ),
    # Editorial verbs immediately before the path:
    # "modified src/...", "edited src/...", "updated src/...", "patched src/..."
    re.compile(
        r"\b(?:modif(?:y|ied|ies|ying)|chang(?:e|ed|es|ing)|"
        r"edit(?:ed|s|ing)?|update(?:d|s|ing)?|"
        r"patch(?:ed|es|ing)?|refactor(?:ed|s|ing)?)\s+"
        r"[`'\"]*(src/(?:review_advisor|review_phase)\.py)",
        re.IGNORECASE,
    ),
)


def _detect_self_modification_context(transcript: str) -> list[str]:
    """Return the sorted set of advisor source paths that appear in a
    *modification context* within ``transcript`` (not a benign mention).

    Empty list means no pseudo diff header should be synthesized — the
    candidate content does not look like it's describing real changes to
    advisor's own implementation files.
    """
    detected: set[str] = set()
    for pattern in _SELF_MOD_SYNTHESIS_PATTERNS:
        for match in pattern.finditer(transcript):
            detected.add(match.group(1))
    return sorted(detected)


def _run_fallback_ingest_review(
    *,
    tracked_store: RepoWikiStore,
    worktree_path: Path,
    repo: str,
    issue_number: int,
    summary: str,
    path_prefix: str,
) -> None:
    """Sync wrapper for the fallback review-ingest path.

    Module-level so it can be dispatched via ``asyncio.to_thread`` — the
    sync ``git commit`` in ``commit_pending_entries`` would otherwise
    stall the event loop (ADR-0001).
    """
    from repo_wiki_ingest import ingest_from_review  # noqa: PLC0415

    count = ingest_from_review(
        tracked_store, repo, issue_number, summary, git_backed=True
    )
    if count:
        tracked_store.commit_pending_entries(
            worktree_path=worktree_path,
            phase="review",
            issue_number=issue_number,
            path_prefix=path_prefix,
        )


@dataclass(slots=True)
class ReviewGuardContext:
    """Successful result from _run_initial_guards."""

    task: Task
    workspace_path: Path


@dataclass(slots=True)
class PreReviewContext:
    """Artifacts captured before running the reviewer."""

    diff: str
    visual_decision: VisualValidationDecision | None
    code_scanning_alerts: list[CodeScanningAlert] | None


# Marker substrings indicating a ReviewResult that did NOT reach a real
# verdict and therefore must NOT be cached. Caching these as
# has_blocking=False would silently let a non-reviewed PR satisfy the
# downstream gate.
_NON_VERDICT_SUMMARY_MARKERS: tuple[str, ...] = (
    "stopped",
    "Issue not found",
    "Merge conflicts with main",
    "Review failed due to unexpected error",
)


def _is_meaningful_verdict(result: ReviewResult) -> bool:
    """Return True if *result* represents a real review decision worth caching.

    Skips:
      - COMMENT verdicts (advisory only, no decision)
      - results whose summary contains a non-verdict marker substring
        (stopped, infrastructure error, missing issue, merge conflict)

    Keeps:
      - APPROVE / REQUEST_CHANGES with a normal summary

    Used by ReviewPhase.review_prs to gate the review_stored cache
    write so a no-real-review result cannot poison the downstream
    READY-stage precondition gate.
    """
    if result.verdict == ReviewVerdict.COMMENT:
        return False
    summary = result.summary or ""
    return not any(marker in summary for marker in _NON_VERDICT_SUMMARY_MARKERS)


class ReviewPhase:
    """Runs reviewer agents on PRs, merging approved ones inline."""

    def __init__(
        self,
        config: HydraFlowConfig,
        state: StateTracker,
        workspaces: WorkspacePort,
        reviewers: ReviewRunner,
        prs: PRPort,
        stop_event: asyncio.Event,
        store: IssueStorePort,
        conflict_resolver: MergeConflictResolver,
        post_merge: PostMergeHandler,
        event_bus: EventBus | None = None,
        harness_insights: HarnessInsightStore | None = None,
        review_insights: ReviewInsightStorePort | None = None,
        update_bg_worker_status: StatusCallback | None = None,
        baseline_policy: BaselinePolicy | None = None,
        active_issues_cb: Callable[[], None] | None = None,
        transcript_summarizer: TranscriptSummarizer | None = None,
        wiki_store: RepoWikiStore | None = None,
        wiki_compiler: WikiCompiler | None = None,
        retrospective_queue: RetrospectiveQueue | None = None,
        precondition_gate: PreconditionGate | None = None,
        issue_cache: IssueCache | None = None,
    ) -> None:
        self._config = config
        self._state = state
        self._workspaces = workspaces
        self._reviewers = reviewers
        self._prs = prs
        self._transitioner: TaskTransitioner = prs
        self._stop_event = stop_event
        self._store = store
        self._bus = event_bus or EventBus()
        self._suggest_memory = MemorySuggester(config)
        self._summarizer = transcript_summarizer
        self._wiki_store = wiki_store
        self._wiki_compiler = wiki_compiler
        self._update_bg_worker_status = update_bg_worker_status
        self._harness_insights = harness_insights
        if review_insights is not None:
            self._insights = review_insights
        else:
            from review_insights import ReviewInsightStore  # noqa: PLC0415

            self._insights = ReviewInsightStore(config.memory_dir)
        self._active_issues_cb = active_issues_cb
        self._active_issues: set[int] = set()
        self._active_issues_lock = asyncio.Lock()
        self._conflict_resolver = conflict_resolver
        self._post_merge = post_merge
        self._baseline_policy = baseline_policy
        self._retrospective_queue = retrospective_queue
        self._precondition_gate = precondition_gate
        self._issue_cache = issue_cache
        self._visual_validator: VisualValidator | None = None
        if config.visual_validation_enabled:
            from visual_validator import VisualValidator  # noqa: PLC0415

            self._visual_validator = VisualValidator(config)

        # Per-PR advisor retry counter — incremented on VETO. Bounded by
        # surface_cfg.max_veto_retries.
        self._advisor_attempt: dict[int, int] = {}
        # Per-PR list of advisor PostVerifyResults collected this run. The
        # transcript hand-back to the executor (on VETO) is rendered from
        # this list. T12 will replace this with persistent advisor_session.jsonl.
        self._advisor_results: dict[int, list[Any]] = {}
        # Per-PR pre-flight ReviewPlan, captured by ``_run_pre_flight_advisor``
        # before the executor runs and threaded into both the executor's
        # review prompt and the post-verify advisor's input. Reset on every
        # ``_review_one_inner`` entry so plans don't leak across reviews.
        self._advisor_pre_flight_plan: dict[int, ReviewPlan] = {}
        self._post_verify_runner = self._build_post_verify_runner()

    def _build_post_verify_runner(self) -> Any:
        """Build the runner adapter the PostVerifyAdvisor dispatches into.

        Production path: routes through ``self._reviewers._execute`` (the
        existing review-runner harness — same plumbing used by
        ``_run_pre_merge_spec_check``).

        MockWorld path: ``self._reviewers`` is the FakeReviewRunner whose
        ``.parent`` is the FakeLLM. We extract the issue number from the
        prompt (emitted by ``PostVerifyAdvisor._build_prompt`` when
        ``PostVerifyInput.issue_number`` is set) and pop the scripted advisor
        result keyed by ``(issue_number, "post_verify")``.

        Dispatch is duck-typed on ``hasattr(self._reviewers, "_execute")``:
        production ``ReviewRunner`` provides it via ``BaseRunner``; the
        MockWorld fake does not. T9 keeps this routing simple — T10 will
        revisit if/when bounded retry needs richer wiring.
        """
        parent = self

        class _PostVerifyRunner:
            async def run(
                self,
                *,
                model: str,
                subagent_type: str,
                prompt: str,
                role: _AdvisorRole,
            ) -> str:
                # noqa is intentional — `subagent_type` is part of the
                # _AdvisorSubagentRunner protocol; production path does not
                # forward it (TranscriptEventData has no slot for it), but
                # MockWorld path keys advisor scripts by role only.
                _ = subagent_type
                reviewers = parent._reviewers

                # MockWorld dispatch: scenarios attach a FakeLLM via a
                # sentinel attribute (_mockworld_fake_llm) to route advisor
                # calls past the production ReviewRunner._execute (which
                # would hit a real Claude subprocess). Production reviewers
                # never carry this sentinel.
                #
                # Use ``vars()`` (not ``getattr``) for the presence check —
                # ``unittest.mock.AsyncMock`` auto-vivifies any attribute
                # access into a child mock, which would route every test
                # using an AsyncMock-based reviewer into the MockWorld
                # branch and return a coroutine-as-payload. Real MockWorld
                # scenarios set the sentinel as an instance attribute
                # (see tests/scenarios/fakes/mock_world.py), so checking
                # ``__dict__`` cleanly distinguishes them.
                instance_dict = getattr(reviewers, "__dict__", None) or {}
                fake_llm = instance_dict.get("_mockworld_fake_llm")
                if fake_llm is not None and getattr(
                    fake_llm, "_is_fake_adapter", False
                ):
                    import re  # noqa: PLC0415

                    if not hasattr(fake_llm, "pop_advisor_result"):
                        return ""
                    match = re.search(r"^Issue:\s*(\d+)\s*$", prompt, re.MULTILINE)
                    issue_number = int(match.group(1)) if match else 0
                    # Role resolution: prefer the explicit ``role`` parameter
                    # passed by the advisor (T24.5 closed I1+I2). Mid-flight
                    # calls dispatch from inside the executor's session via
                    # the Task tool, which doesn't thread through this
                    # protocol — those prompts carry the
                    # ``MidFlightAdvisor.SENTINEL`` HTML-comment marker as
                    # their first line, so we detect that explicitly. This
                    # is a forward-only marker that won't naturally appear
                    # in PR bodies, specs, or user content (unlike the
                    # pre-T24.5 ``## Mid-flight consult`` header substring
                    # which false-positived on advisor-pattern PRs whose
                    # bodies documented the format).
                    from review_advisor import (  # noqa: PLC0415
                        MidFlightAdvisor,
                    )

                    if MidFlightAdvisor.SENTINEL in prompt:
                        resolved_role: _AdvisorRole = "mid_flight"
                    else:
                        resolved_role = role
                    result = fake_llm.pop_advisor_result(issue_number, resolved_role)
                    if isinstance(result, str):
                        return result
                    return result or ""

                # Production path: thread through the same review-runner
                # harness used by _run_pre_merge_spec_check.
                from agent_cli import build_agent_command  # noqa: PLC0415

                cmd = build_agent_command(
                    tool=parent._config.review_tool,
                    model=model,
                    disallowed_tools="Write,Edit,NotebookEdit",
                )
                return await reviewers._execute(
                    cmd,
                    prompt,
                    parent._config.repo_root,
                    {"source": "advisor"},
                )

        return _PostVerifyRunner()

    _WIKI_INGEST_MAX_CHARS = 40_000

    async def _wiki_ingest_review(
        self, issue_number: int, *, transcript: str, summary: str
    ) -> None:
        """Ingest review knowledge into the per-repo wiki.

        When the LLM compiler is available, passes the full *transcript*
        for richer synthesis.  Falls back to *summary* for mechanical
        extraction.  Skips if this issue+review was already ingested.
        Never raises.

        When ``config.repo_wiki_git_backed`` is True and the issue
        worktree exists, per-entry markdown files are written under the
        worktree's ``repo_wiki/`` directory and committed so the wiki
        updates ride the issue's PR.  Dedup state still lives on the
        main host's legacy wiki path.

        T28: PostVerifyAdvisor (surface=``wiki_ingest``) is consulted
        in advisory mode (``post_verify_authority="advisory"``,
        ``max_veto_retries=0``) before content is written. In advisory
        mode the advisor's VETO is downgraded to APPROVE inside
        :class:`PostVerifyAdvisor.run` — disagreements are still logged
        for telemetry/calibration but ingestion proceeds. EXCEPTION:
        T29's self-modification guard upgrades authority to ``veto``
        when the candidate content discusses changes to advisor's own
        implementation files (``src/review_advisor.py``,
        ``src/review_phase.py``); in that path a real VETO blocks
        ingestion.
        """
        if self._wiki_store is None or not self._config.repo:
            return
        repo = self._config.repo
        if self._wiki_store.is_ingested(repo, issue_number, "review"):
            return

        # T28: post-verify advisor in advisory mode. VETO is downgraded
        # to APPROVE unless self-mod guard forces veto authority — then a
        # real VETO short-circuits the ingest entirely.
        if await self._run_wiki_ingest_advisor(
            issue_number=issue_number, transcript=transcript, summary=summary
        ):
            return

        tracked_store, worktree_path = self._wiki_tracked_store(issue_number)
        try:
            # Prefer LLM synthesis from transcript when compiler is available
            if self._wiki_compiler is not None and transcript:
                entries = await self._wiki_compiler.synthesize_ingest(
                    repo,
                    issue_number,
                    "review",
                    transcript[: self._WIKI_INGEST_MAX_CHARS],
                )
                if entries:
                    if tracked_store is not None and worktree_path is not None:
                        decisions = await self._precompute_corroboration(
                            tracked_store=tracked_store,
                            repo=repo,
                            entries=entries,
                        )
                        # Offload sync file + git-subprocess work off the
                        # event loop — ADR-0001 — so other concurrent
                        # phase loops don't stall on ``git commit``.
                        await asyncio.to_thread(
                            self._wiki_commit_compiler_entries,
                            tracked_store=tracked_store,
                            worktree_path=worktree_path,
                            repo=repo,
                            issue_number=issue_number,
                            phase="review",
                            entries=entries,
                            decisions=decisions,
                        )
                    else:
                        self._wiki_store.ingest(repo, entries)
                    self._wiki_store.mark_ingested(repo, issue_number, "review")
                    return

            # Fallback: mechanical extraction from structured summary
            from repo_wiki_ingest import ingest_from_review  # noqa: PLC0415

            if tracked_store is not None and worktree_path is not None:
                await asyncio.to_thread(
                    _run_fallback_ingest_review,
                    tracked_store=tracked_store,
                    worktree_path=worktree_path,
                    repo=repo,
                    issue_number=issue_number,
                    summary=summary,
                    path_prefix=self._config.repo_wiki_path,
                )
            else:
                ingest_from_review(self._wiki_store, repo, issue_number, summary)
            self._wiki_store.mark_ingested(repo, issue_number, "review")
        except Exception:  # noqa: BLE001
            logger.warning(
                "Wiki ingest failed for review #%d", issue_number, exc_info=True
            )

    async def _run_wiki_ingest_advisor(
        self,
        *,
        issue_number: int,
        transcript: str,
        summary: str,
    ) -> bool:
        """Run :class:`PostVerifyAdvisor` for the ``wiki_ingest`` surface (T28).

        Returns ``True`` when ingestion should be blocked (only ever happens
        when T29's self-modification guard upgrades authority to ``veto`` and
        the advisor returns VETO). Returns ``False`` when ingestion may
        proceed — covering the normal advisory-mode path (VETO is downgraded
        to APPROVE inside :class:`PostVerifyAdvisor.run`), APPROVE verdicts,
        the kill-switch off path, and degraded advisor failures.

        Per spec tiering, ``wiki_ingest`` has ``post_verify_authority="advisory"``
        and ``max_veto_retries=0`` — so the advisor is consulted purely for
        calibration: disagreements feed
        ``review_advisor_disagreement_total`` (T16.5) and the
        ``review_advisor_disagreement_validated_total`` KPI (T22), and every
        call appends to ``advisor_session.jsonl`` (T12). The advisor's
        opinion does *not* normally block ingestion.

        ``reraise_on_credit_or_bug`` discipline is preserved per
        ``docs/wiki/dark-factory.md`` §2.2 inside
        :meth:`_run_post_verify_for_surface`.
        """
        diff_descriptor = self._build_wiki_ingest_diff_descriptor(
            issue_number=issue_number, transcript=transcript, summary=summary
        )

        pv_result = await self._run_post_verify_for_surface(
            surface="wiki_ingest",
            diff=diff_descriptor,
            spec=summary or None,
            executor_verdict_summary="wiki_ingest_candidate",
            issue_number=issue_number,
        )
        if pv_result is None:
            return False

        # Advisory mode: VETO is downgraded to APPROVE inside advisor.run.
        # A residual VETO here means the self-mod guard upgraded authority
        # to "veto" — block ingestion.
        if pv_result.verdict == "VETO":
            logger.warning(
                "wiki_ingest VETO from advisor for review #%d "
                "(self-modification guard active): %s",
                issue_number,
                pv_result.reasoning,
            )
            return True
        return False

    def _build_wiki_ingest_diff_descriptor(
        self,
        *,
        issue_number: int,
        transcript: str,
        summary: str,
    ) -> str:
        """Render a textual descriptor of the candidate wiki ingest content.

        Wiki ingest has no unified text diff — the advisor's input is a
        synthesized view of what would be written: the review summary and
        a bounded slice of the transcript. The descriptor must be
        non-empty so the advisor has *something* to evaluate, and must
        carry through any discussion of advisor implementation files so
        ``resolve_post_verify_authority``'s self-modification guard can
        detect those references and force veto authority.

        ``resolve_post_verify_authority`` matches *unified-diff header*
        substrings (``diff --git a/<path>`` etc.). Wiki ingest never
        produces those headers naturally, so when the candidate content
        mentions a self-modifying path we synthesize a pseudo-header
        block in the descriptor — that gives the existing self-mod
        detector a unified surface to match against without forking its
        path-matching logic.

        Path list source-of-truth (T30.5 I3): we import
        ``review_advisor.SELF_MODIFYING_PATHS`` to keep the recognized-path
        set aligned with the advisor module; different matchers (unified-
        diff headers vs. content context) consume the same paths.

        T37: detection is context-sensitive. A bare substring mention of an
        advisor source path (e.g., "review found a type-hint gap in
        src/review_advisor.py") no longer synthesizes the pseudo header —
        only modification context (already-formed diff headers, fenced
        diff/patch blocks, or editorial verbs like "modified <path>") does.
        See ``_detect_self_modification_context``.
        """
        from review_advisor import SELF_MODIFYING_PATHS  # noqa: PLC0415

        # Mirror the synthesize_ingest cap so the descriptor reflects
        # exactly the content that would feed the wiki compiler.
        bounded_transcript = (transcript or "")[: self._WIKI_INGEST_MAX_CHARS]
        combined = f"{summary}\n{bounded_transcript}"
        lines = [
            f"Wiki ingest candidate — issue #{issue_number}",
            f"Repo: {self._config.repo or '(unset)'}",
        ]
        # Synthesize unified-diff headers only for self-mod paths that
        # appear in a *modification context* — bare substring mentions
        # (benign prose) do NOT trigger synthesis. Intersect with
        # SELF_MODIFYING_PATHS so the regex remains the gate but the
        # canonical path list still governs which paths are eligible.
        detected = _detect_self_modification_context(combined)
        for path in detected:
            if path in SELF_MODIFYING_PATHS:
                lines.append(f"diff --git a/{path} b/{path}")
        lines.extend(
            [
                "",
                "## Summary",
                summary or "(none)",
            ]
        )
        if bounded_transcript:
            lines.extend(["", "## Transcript (bounded)", bounded_transcript])
        return "\n".join(lines)

    def _wiki_tracked_store(
        self, issue_number: int
    ) -> tuple[RepoWikiStore | None, Path | None]:
        """Build a ``RepoWikiStore`` pointed at the issue worktree's
        tracked ``repo_wiki/`` directory, or ``(None, None)`` when
        git-backed writes are disabled / the worktree is missing.
        """
        if not self._config.repo_wiki_git_backed:
            return None, None
        worktree_path = self._config.workspace_path_for_issue(issue_number)
        if not worktree_path.is_dir():
            logger.debug(
                "Wiki git-backed write skipped for #%d: worktree %s missing",
                issue_number,
                worktree_path,
            )
            return None, None
        tracked_root = worktree_path / self._config.repo_wiki_path
        return (
            RepoWikiStore(wiki_root=tracked_root, tracked_root=tracked_root),
            worktree_path,
        )

    async def _precompute_corroboration(
        self,
        *,
        tracked_store: RepoWikiStore,
        repo: str,
        entries: list[WikiEntry],
    ) -> list[CorroborationDecision]:
        """Run ``dedup_or_corroborate`` per entry against existing active
        entries in the same topic. Returns one decision per entry in the
        same order. Bounded per-entry by a candidate cap so a large
        topic doesn't fire one LLM call per existing entry.
        """
        from wiki_compiler import CorroborationDecision  # noqa: PLC0415

        if self._wiki_compiler is None:
            return [CorroborationDecision() for _ in entries]
        max_candidates = 5
        decisions: list[CorroborationDecision] = []
        for entry in entries:
            topic = classify_topic(entry)
            topic_dir = tracked_store._tracked_topic_dir(repo, topic)
            existing_pairs: list[tuple[WikiEntry, Path]] = []
            if topic_dir is not None:
                existing_pairs = (
                    tracked_store._load_tracked_topic_entries_with_paths(topic_dir)
                )[:max_candidates]
            try:
                decision = await self._wiki_compiler.dedup_or_corroborate(
                    repo_slug=repo,
                    entry=entry,
                    existing_entries=existing_pairs,
                    topic=topic,
                )
            except Exception:  # noqa: BLE001
                logger.warning(
                    "corroboration precompute failed for %s/%s",
                    repo,
                    entry.title,
                    exc_info=True,
                )
                decision = CorroborationDecision()
            decisions.append(decision)
        return decisions

    def _wiki_commit_compiler_entries(
        self,
        *,
        tracked_store: RepoWikiStore,
        worktree_path: Path,
        repo: str,
        issue_number: int,
        phase: str,
        entries: list[WikiEntry],
        decisions: list[CorroborationDecision] | None = None,
    ) -> None:
        """Route compiler-synthesized entries through ``write_entry`` then
        commit.  Rolls back any files written before a mid-batch failure.

        When ``decisions`` is provided (same length as ``entries``),
        entries whose decision says ``should_corroborate`` skip the
        write and instead bump the canonical's counter via
        ``increment_corroboration`` — the ingest side of the
        depth-signal system (ADR-0032).
        """
        from wiki_compiler import CorroborationDecision  # noqa: PLC0415

        written: list[Path] = []
        if decisions is None or len(decisions) != len(entries):
            decisions = [CorroborationDecision() for _ in entries]
        try:
            for entry, decision in zip(entries, decisions, strict=True):
                if decision.should_corroborate and decision.canonical_path is not None:
                    increment_corroboration(decision.canonical_path)
                    continue
                topic = classify_topic(entry)
                written.append(tracked_store.write_entry(repo, entry, topic=topic))
            tracked_store.append_log(
                repo,
                issue_number,
                {"phase": phase, "action": "ingest", "entries": len(written)},
            )
            tracked_store.commit_pending_entries(
                worktree_path=worktree_path,
                phase=phase,
                issue_number=issue_number,
                path_prefix=self._config.repo_wiki_path,
            )
        except Exception:
            for p in written:
                try:
                    p.unlink()
                except OSError:
                    logger.warning("wiki ingest rollback: failed to unlink %s", p)
            raise

    @property
    def active_issues(self) -> set[int]:
        return self._active_issues

    async def post_review_transcript_hooks(
        self, review_results: list[ReviewResult]
    ) -> None:
        """File memory suggestions and post transcript summaries for review results."""
        for result in review_results:
            if not result.transcript:
                continue
            if result.merged:
                review_status = "success"
            elif result.ci_passed is False:
                review_status = "failed"
            else:
                review_status = "completed"
            await self._post_review_transcript(result, status=review_status)

    async def _post_review_transcript(
        self, result: ReviewResult, *, status: str
    ) -> None:
        """File memory suggestion and post transcript summary for a single review."""
        if result.transcript:
            await self._suggest_memory(
                result.transcript, "reviewer", f"PR #{result.pr_number}"
            )
        if self._summarizer and result.transcript and result.issue_number > 0:
            try:
                await self._summarizer.summarize_and_comment(
                    transcript=result.transcript,
                    issue_number=result.issue_number,
                    phase="review",
                    status=status,
                    duration_seconds=result.duration_seconds,
                    log_file=self._review_log_reference(result.pr_number),
                )
            except Exception as exc:
                log_exception_with_bug_classification(
                    logger,
                    exc,
                    f"Failed to post transcript summary for issue #{result.issue_number}",
                )

    def _review_log_reference(self, pr_number: int) -> str:
        """Return a display-friendly log path for reviewer transcripts."""
        log_path = self._config.log_dir / f"review-pr-{pr_number}.txt"
        return self._config.format_path_for_display(log_path)

    async def review_prs(
        self,
        prs: list[PRInfo],
        issues: list[Task],
    ) -> list[ReviewResult]:
        """Run reviewer agents on non-draft PRs, merging approved ones inline."""
        if not prs:
            return []

        # Apply the precondition gate (#6423) before reviewing. Issues
        # whose plan/review records are missing get routed back to the
        # ready stage; only PRs whose underlying issues pass the gate
        # are reviewed in this cycle.
        if self._precondition_gate is not None:
            from stage_preconditions import Stage  # noqa: PLC0415

            gated = await self._precondition_gate.filter_and_route(issues, Stage.REVIEW)
            gated_ids = {i.id for i in gated}
            issues = gated
            prs = [pr for pr in prs if pr.issue_number in gated_ids]
            if not prs:
                return []

        # Skip term-proposer / term-pruner / edge-proposer PRs (handled by
        # DependabotMergeLoop, ADR-0054 / ADR-0057 / ADR-0058). All three loops
        # open auto-merging bot PRs whose content is purely generated; the agent
        # pipeline must not route them.
        from edge_proposer_loop import EDGE_PROPOSER_PR_LABEL  # noqa: PLC0415
        from term_proposer_loop import TERM_PROPOSER_PR_LABEL  # noqa: PLC0415
        from term_pruner_loop import TERM_PRUNER_PR_LABEL  # noqa: PLC0415

        _ul_bot_labels = {
            TERM_PROPOSER_PR_LABEL,
            TERM_PRUNER_PR_LABEL,
            EDGE_PROPOSER_PR_LABEL,
        }
        prs = [pr for pr in prs if not (set(pr.labels or []) & _ul_bot_labels)]
        if not prs:
            logger.debug(
                "review_phase: all PRs filtered out (term-proposer/pruner/edge-proposer candidates)"
            )
            return []

        issue_map = {i.id: i for i in issues}
        semaphore = asyncio.Semaphore(self._config.max_reviewers)

        async def _review_one(idx: int, pr: PRInfo) -> ReviewResult:
            """Review a single PR under the concurrency semaphore."""
            if self._stop_event.is_set():
                return ReviewResult(
                    pr_number=pr.number,
                    issue_number=pr.issue_number,
                    summary="stopped",
                )
            async with semaphore:
                if self._stop_event.is_set():
                    return ReviewResult(
                        pr_number=pr.number,
                        issue_number=pr.issue_number,
                        summary="stopped",
                    )
                async with self._active_issues_lock:
                    self._active_issues.add(pr.issue_number)
                    if self._active_issues_cb:
                        self._active_issues_cb()
                with _sentry_transaction("pipeline.review", f"review:PR#{pr.number}"):
                    async with store_lifecycle(self._store, pr.issue_number, "review"):
                        try:
                            return await run_with_fatal_guard(
                                self._review_one_inner(idx, pr, issue_map),
                                on_failure=lambda exc_name: ReviewResult(
                                    pr_number=pr.number,
                                    issue_number=pr.issue_number,
                                    summary=f"Review failed due to unexpected error ({exc_name})",
                                ),
                                context=f"Review failed for PR #{pr.number} (issue #{pr.issue_number})",
                                log=logger,
                            )
                        finally:
                            await self._publish_review_status(pr, idx, "done")
                            async with self._active_issues_lock:
                                self._active_issues.discard(pr.issue_number)
                                if self._active_issues_cb:
                                    self._active_issues_cb()

        try:
            results = await run_concurrent_batch(prs, _review_one, self._stop_event)
        finally:
            release_batch_in_flight(self._store, {pr.issue_number for pr in prs})

        # Mirror review verdicts into the issue cache as review_stored
        # records (#6422 + #6421). The READY-stage precondition gate
        # for downstream PR-driven re-review reads has_blocking from
        # these records. Only meaningful verdicts produce a cache
        # record:
        #   APPROVE          → has_blocking=False (good to go)
        #   REQUEST_CHANGES  → has_blocking=True  (must re-review)
        # No-verdict / stopped / errored results are SKIPPED entirely
        # so they cannot poison a downstream gate by silently caching
        # has_blocking=False for a review that never actually ran.
        # See _is_meaningful_verdict for the skip rules.
        if self._issue_cache is not None:
            for result in results:
                if result.issue_number <= 0:
                    continue
                if not _is_meaningful_verdict(result):
                    continue
                try:
                    self._issue_cache.record_review_stored(
                        result.issue_number,
                        review_text=result.summary,
                        has_blocking=(result.verdict == ReviewVerdict.REQUEST_CHANGES),
                    )
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "Failed to write review_stored cache record for issue #%d",
                        result.issue_number,
                        exc_info=True,
                    )

        return results

    async def review_adrs(self, issues: list[Task]) -> list[ReviewResult]:
        """Review ADR issues that intentionally have no PR."""
        adr_issues = [issue for issue in issues if is_adr_issue_title(issue.title)]
        if not adr_issues:
            return []

        results: list[ReviewResult] = []
        for issue in adr_issues:
            if self._stop_event.is_set():
                break
            async with store_lifecycle(self._store, issue.id, "review"):
                adr_result = await self._review_single_adr(issue)
                if adr_result.merged:
                    self._store.mark_merged(issue.id)
                results.append(adr_result)
        return results

    async def _review_single_adr(self, issue: Task) -> ReviewResult:
        """Validate ADR quality and either finalize or escalate to HITL.

        T26: PreFlightAdvisor (AlwaysTrigger) runs after the duplicate guard
        and before the structural validator; PostVerifyAdvisor runs after
        the structural validator approves and gates the finalize path. Both
        use surface ``"adr_review"`` (no mid-flight — ADRs have no fix loop).
        On VETO the advisor's reasoning is folded into the existing
        requeue-to-plan path so the author can revise the ADR draft.
        """
        topic_key = check_adr_duplicate(issue.title, self._config.repo_root)
        if topic_key:
            await self._transitioner.post_comment(
                issue.id,
                f"## Closing as Duplicate\n\n"
                f"An ADR already exists for this topic in `docs/adr/`. "
                f"Normalized topic: *{topic_key}*",
            )
            await self._transitioner.close_task(issue.id)
            self._state.mark_issue(issue.id, "completed")
            logger.info(
                "ADR issue #%d closed as duplicate — topic %r exists in docs/adr/",
                issue.id,
                topic_key,
            )
            return ReviewResult(
                pr_number=0,
                issue_number=issue.id,
                verdict=ReviewVerdict.APPROVE,
                summary="Closed as duplicate ADR",
                merged=True,
            )

        # T26 pre-flight (AlwaysTrigger). The ADR body is the "diff" for the
        # advisor — there is no PR or unified diff. Plan is keyed by
        # ``issue.id`` (no PR number) and consumed by the post-verify call
        # below for plan-aware second-opinion.
        adr_content = issue.body or ""
        self._advisor_pre_flight_plan.pop(issue.id, None)
        await self._run_pre_flight_advisor_for_adr(issue=issue, diff=adr_content)

        reasons = adr_validation_reasons(issue.body)
        decision_detail = extract_adr_section(issue.body, "decision")
        if len(decision_detail.strip()) < 60:
            reasons.append(
                "Decision section lacks actionable detail (minimum 60 chars)"
            )

        if reasons:
            # Re-queue for planning instead of HITL — ADR needs author fixes
            await self._prs.post_comment(
                issue.id,
                "## ADR Review — Changes Needed\n\n"
                "The ADR draft needs fixes before finalization.\n\n"
                "**Required fixes:**\n"
                + "\n".join(f"- {reason}" for reason in reasons)
                + "\n\nUpdate the ADR and re-label to re-enter the pipeline.",
            )
            if issue is not None:
                self._store.enqueue_transition(issue, "plan")
            await self._transitioner.transition(issue.id, "plan")
            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.SYSTEM_REROUTE,
                    data={
                        "issue": issue.id,
                        "action": "requeued_to_plan",
                        "reasons": reasons,
                    },
                )
            )
            return ReviewResult(
                pr_number=0,
                issue_number=issue.id,
                verdict=ReviewVerdict.REQUEST_CHANGES,
                summary=f"ADR re-queued for fixes: {'; '.join(reasons)}",
            )

        # T26 post-verify (veto). The structural validator returned APPROVE
        # ("no reasons") — give the advisor a chance to second-opinion the
        # ADR's content before finalize. On VETO, requeue to plan with the
        # advisor's reasoning so the author can revise. ADR has no fix loop
        # (mid_flight=False), so this is a one-shot binary gate, mirroring
        # the pre_merge_spec_check pattern.
        veto_result = await self._run_post_verify_advisor_for_adr(
            issue=issue,
            diff=adr_content,
            executor_verdict_summary="ADR structural validation passed",
        )
        if veto_result is not None:
            return veto_result

        await self._transitioner.post_comment(
            issue.id,
            "## ADR Review Approved\n\n"
            "ADR draft validated and finalized by the review phase.\n\n"
            "Closing issue as complete.",
        )
        await self._prs.swap_pipeline_labels(issue.id, self._config.fixed_label[0])
        await self._transitioner.close_task(issue.id)
        self._state.mark_issue(issue.id, "completed")
        self._state.record_issue_completed()
        self._state.increment_session_counter("reviewed")
        return ReviewResult(
            pr_number=0,
            issue_number=issue.id,
            verdict=ReviewVerdict.APPROVE,
            summary="ADR review approved",
            merged=True,
        )

    async def _prepare_review_worktree(
        self, pr: PRInfo, task: Task, idx: int
    ) -> Path | None:
        """Ensure worktree exists and main is merged. Returns path or None on conflict."""
        wt_path = self._config.workspace_path_for_issue(pr.issue_number)
        if not wt_path.exists():
            wt_path = await self._workspaces.create(pr.issue_number, pr.branch)
        merged = await self._merge_with_main(pr, task, wt_path, idx)
        if not merged:
            return None
        return wt_path

    async def _fetch_code_scanning_alerts(
        self, pr: PRInfo
    ) -> list[CodeScanningAlert] | None:
        """Fetch code scanning alerts for the PR branch.

        Returns the alert list or ``None`` on error.
        """
        try:
            alerts = await self._prs.fetch_code_scanning_alerts(pr.branch)
            if alerts:
                logger.info(
                    "PR #%d: fetched %d code scanning alert(s)",
                    pr.number,
                    len(alerts),
                )
            return alerts or None
        except (RuntimeError, OSError):
            logger.debug(
                "Could not fetch code scanning alerts for PR #%d",
                pr.number,
                exc_info=True,
            )
            return None

    async def _check_baseline_policy(
        self, pr: PRInfo, task: Task
    ) -> BaselineApprovalResult | None:
        """Run baseline policy check if a policy is configured.

        Returns the approval result or ``None`` when no policy is active.
        """
        if self._baseline_policy is None:
            return None
        try:
            changed_files = await self._prs.get_pr_diff_names(pr.number)
            if not changed_files:
                return None
            pr_approvers = await self._prs.get_pr_approvers(pr.number)
            commit_sha = await self._prs.get_pr_head_sha(pr.number)
            return await self._baseline_policy.check_approval(
                pr_number=pr.number,
                issue_number=pr.issue_number,
                changed_files=changed_files,
                pr_approvers=pr_approvers,
                commit_sha=commit_sha,
            )
        except (RuntimeError, OSError):
            logger.warning(
                "Baseline policy check failed for PR #%d — failing closed to protect baseline integrity",
                pr.number,
                exc_info=True,
            )
            return BaselineApprovalResult(
                approved=False,
                requires_approval=True,
                reason="Baseline policy check failed — manual review required",
            )

    async def _review_one_inner(
        self,
        idx: int,
        pr: PRInfo,
        issue_map: dict[int, Task],
        surface: str = "pr_review",
    ) -> ReviewResult:
        """Core review logic for a single PR — called inside the semaphore.

        ``surface`` defaults to ``"pr_review"`` for back-compat (T24.7 prep
        for Phase 4). Phase 4 outer helpers may invoke this with other
        surface names; the surface is threaded through the advisor and
        executor prompt-building call sites.
        """
        from trace_rollup import write_phase_rollup  # noqa: PLC0415
        from tracing_context import (  # noqa: PLC0415
            TracingContext,
            source_to_phase,
        )

        trace_phase = source_to_phase("reviewer")
        run_id = self._state.begin_trace_run(pr.issue_number, trace_phase)
        self._reviewers.set_tracing_context(
            TracingContext(
                issue_number=pr.issue_number,
                phase=trace_phase,
                source="reviewer",
                run_id=run_id,
            )
        )

        try:
            await self._publish_review_status(pr, idx, "start")

            # Reset per-PR pre-flight plan on every review entry. Like
            # ``_advisor_attempt`` (cleared inside ``_run_post_verify_advisor``),
            # the plan is scoped to a single review cycle and must not leak
            # across reviews of the same PR — reusing a stale plan from the
            # prior cycle would feed an out-of-date rubric to both the
            # executor's prompt and the post-verify advisor.
            self._advisor_pre_flight_plan.pop(pr.number, None)

            guards = await self._run_initial_guards(idx, pr, issue_map)
            if isinstance(guards, ReviewResult):
                return guards

            pre_review = await self._run_pre_review_checks(pr, guards.task)
            if isinstance(pre_review, ReviewResult):
                return pre_review

            await self._run_pre_flight_advisor(
                pr, guards.task, pre_review.diff, surface=surface
            )

            result = await self._run_and_post_review(
                pr,
                guards.task,
                guards.workspace_path,
                pre_review.diff,
                idx,
                code_scanning_alerts=pre_review.code_scanning_alerts,
                pre_flight_plan=self._advisor_pre_flight_plan.get(pr.number),
                surface=surface,
            )

            return await self._run_post_review_actions(
                pr,
                guards.task,
                guards.workspace_path,
                result,
                pre_review,
                idx,
                surface=surface,
            )
        finally:
            self._reviewers.clear_tracing_context()
            try:
                write_phase_rollup(
                    config=self._config,
                    issue_number=pr.issue_number,
                    phase=trace_phase,
                    run_id=run_id,
                )
            except Exception:
                logger.warning(
                    "Phase rollup failed for PR #%d",
                    pr.number,
                    exc_info=True,
                )
            self._state.end_trace_run(pr.issue_number, trace_phase)

    async def _run_initial_guards(
        self,
        idx: int,
        pr: PRInfo,
        issue_map: dict[int, Task],
    ) -> ReviewResult | ReviewGuardContext:
        """Handle prerequisite guards before running a review."""
        task = issue_map.get(pr.issue_number)
        if task is None:
            return ReviewResult(
                pr_number=pr.number,
                issue_number=pr.issue_number,
                summary="Issue not found",
            )

        wt_path = await self._prepare_review_worktree(pr, task, idx)
        if wt_path is None:
            return ReviewResult(
                pr_number=pr.number,
                issue_number=pr.issue_number,
                summary="Merge conflicts with main — escalated to HITL",
            )

        return ReviewGuardContext(task=task, workspace_path=wt_path)

    async def _run_pre_review_checks(
        self,
        pr: PRInfo,
        task: Task,
    ) -> ReviewResult | PreReviewContext:
        """Run baseline, visual, and delta checks before invoking reviewer."""
        diff = await self._prs.get_pr_diff(pr.number)

        baseline_result = await self._check_baseline_policy(pr, task)
        if (
            baseline_result
            and baseline_result.requires_approval
            and not baseline_result.approved
        ):
            await self._escalate_to_hitl(
                HitlEscalation(
                    issue_number=pr.issue_number,
                    pr_number=pr.number,
                    cause="Baseline changes require approval",
                    origin_label=self._config.review_label[0],
                    comment=(
                        "## Baseline Policy Violation\n\n"
                        "This PR modifies visual baseline files that require "
                        "explicit approval from a designated owner before merging.\n\n"
                        "**Changed baseline files:**\n"
                        + "\n".join(f"- `{f}`" for f in baseline_result.changed_files)
                        + "\n\nPlease request a review from an authorized baseline approver."
                    ),
                    event_cause="baseline_approval_required",
                    task=task,
                )
            )
            return ReviewResult(
                pr_number=pr.number,
                issue_number=pr.issue_number,
                summary="Baseline changes require approval — escalated to HITL",
            )

        visual_decision = self._compute_visual_validation(diff, task)
        if visual_decision is not None and pr.number > 0:
            from visual_validation import (  # noqa: PLC0415
                format_visual_validation_comment,
            )

            await self._prs.post_pr_comment(
                pr.number,
                format_visual_validation_comment(visual_decision),
            )

        code_scanning_alerts = await self._fetch_code_scanning_alerts(pr)
        await self._run_delta_verification(pr, diff)

        return PreReviewContext(
            diff=diff,
            visual_decision=visual_decision,
            code_scanning_alerts=code_scanning_alerts,
        )

    async def _run_post_review_actions(
        self,
        pr: PRInfo,
        task: Task,
        wt_path: Path,
        result: ReviewResult,
        pre_review: PreReviewContext,
        worker_id: int,
        surface: str = "pr_review",
    ) -> ReviewResult:
        """Handle re-review, visual validation, verdict flow, and cleanup.

        ``surface`` is forwarded to ``_run_post_verify_advisor`` so the
        post-verify advisor uses the correct surface config (T24.7).
        Defaults to ``"pr_review"`` for back-compat.
        """
        diff = pre_review.diff
        code_scanning_alerts = pre_review.code_scanning_alerts

        if result.verdict in (
            ReviewVerdict.REQUEST_CHANGES,
            ReviewVerdict.COMMENT,
        ):
            if result.fixes_made:
                result, diff = await self._handle_self_fix_re_review(
                    pr,
                    task,
                    wt_path,
                    result,
                    diff,
                    worker_id,
                    code_scanning_alerts=code_scanning_alerts,
                )
            else:
                result, diff = await self._attempt_review_fix(
                    pr,
                    task,
                    wt_path,
                    result,
                    diff,
                    worker_id,
                    code_scanning_alerts=code_scanning_alerts,
                )

        visual_report = await self._run_visual_validation(pr, wt_path, worker_id)
        if visual_report and visual_report.has_failures:
            result = await self._handle_visual_failure(
                pr,
                task,
                result,
                visual_report,
                worker_id,
            )

        await self._record_review_outcome(pr, result)

        # Pre-merge spec check for product-track issues
        if (
            result.verdict == ReviewVerdict.APPROVE
            and pr.number > 0
            and self._is_product_track_pr(task)
        ):
            spec_ok = await self._run_pre_merge_spec_check(
                task, diff, pr_number=pr.number
            )
            if not spec_ok:
                result = result.model_copy(
                    update={
                        "verdict": ReviewVerdict.REQUEST_CHANGES,
                        "summary": (result.summary or "")
                        + "\n\nSpec-match check failed: implementation does not fully "
                        "match the product direction from Shape. See spec-match "
                        "comment on the issue.",
                    }
                )

        # PostVerifyAdvisor — second-opinion gate on APPROVE verdicts.
        # On VETO, the advisor hands the disagreement back to the executor
        # for up to ``surface_cfg.max_veto_retries`` retries. After the
        # retry budget is exhausted, the disagreement is escalated to HITL.
        if result.verdict == ReviewVerdict.APPROVE and pr.number > 0:
            result, diff = await self._run_post_verify_advisor(
                pr=pr,
                task=task,
                wt_path=wt_path,
                result=result,
                diff=diff,
                worker_id=worker_id,
                code_scanning_alerts=code_scanning_alerts,
                surface=surface,
            )

        skip_worktree_cleanup = False
        if result.verdict == ReviewVerdict.APPROVE and pr.number > 0:
            await self._handle_approved_merge(
                pr,
                task,
                result,
                diff,
                worker_id,
                code_scanning_alerts=code_scanning_alerts,
                visual_decision=pre_review.visual_decision,
            )
        elif result.verdict in (
            ReviewVerdict.REQUEST_CHANGES,
            ReviewVerdict.COMMENT,
        ):
            skip_worktree_cleanup = await self._handle_rejected_review(
                pr,
                task,
                result,
                worker_id,
            )

        await self._cleanup_worktree(pr, result, skip_worktree_cleanup)
        return result

    async def _run_pre_flight_advisor(
        self,
        pr: PRInfo,
        task: Task,
        diff: str,
        surface: str = "pr_review",
    ) -> None:
        """Run :class:`PreFlightAdvisor` when the composite trigger fires.

        Stashes the resulting :class:`ReviewPlan` under
        ``self._advisor_pre_flight_plan[pr.number]`` so downstream call sites
        (the executor's review prompt + the post-verify advisor's input) can
        consume it without a second invocation. Best-effort writes a JSON
        scratchpad to ``review_logs/<pr>/preflight.json`` for operator
        debugging — failures there must not break the pipeline.

        No-ops when:
          * The selected ``surface`` or pre_flight role is kill-switched off.
          * The composite trigger returns False (trivial/docs-only diffs
            without prior fix attempts and no critical-path touches).
          * The advisor returns ``None`` (degraded path — runner or parse
            error). The executor proceeds without a plan; the contract is
            "advisor is advisory" per the spec.

        ``surface`` defaults to ``"pr_review"`` for back-compat (T24.7 prep
        for Phase 4 multi-surface wiring); other surfaces (``adr_review``,
        ``visual_gate``, etc.) pass the surface name explicitly.

        Function-local imports keep the dependency on ``review_advisor``
        contained to where it's used and avoid the auto-lint hook stripping
        an "unused" top-level import.
        """
        from review_advisor import (  # noqa: PLC0415
            PreFlightAdvisor,
            PreFlightInput,
            build_surface_config,
            diff_stats_from_text,
            is_advisor_enabled,
        )

        surface_cfg = build_surface_config(surface)
        if (
            not surface_cfg.pre_flight_enabled
            or surface_cfg.pre_flight_trigger is None
            or not is_advisor_enabled(surface, "pre_flight")
        ):
            return

        diff_stats = diff_stats_from_text(diff)
        from review_advisor import PRContext  # noqa: PLC0415

        pr_ctx = PRContext(prior_fix_attempts=self._advisor_attempt.get(pr.number, 0))
        if not surface_cfg.pre_flight_trigger.should_run(diff_stats, pr_ctx):
            return

        log_path = (
            self._config.repo_root
            / "review_logs"
            / str(pr.number)
            / "advisor_session.jsonl"
        )
        advisor = PreFlightAdvisor(
            runner=self._post_verify_runner,
            surface_config=surface_cfg,
            log_path=log_path,
            pr_number=pr.number,
        )
        try:
            plan = await advisor.run(
                PreFlightInput(
                    surface=surface,
                    diff=diff,
                    spec=task.body or None,
                    related_paths=diff_stats.changed_paths,
                    prior_attempts=self._advisor_attempt.get(pr.number, 0),
                    issue_number=task.id,
                )
            )
        except Exception as exc:
            # Auth / credit errors are re-raised inside PreFlightAdvisor.run,
            # but per docs/wiki/dark-factory.md §2.2 the wrapper's broad
            # except must also reraise credit-exhausted / likely-bug errors
            # so the orchestrator sees infrastructure failures.
            from exception_classify import (  # noqa: PLC0415
                reraise_on_credit_or_bug,
            )

            reraise_on_credit_or_bug(exc)
            logger.warning(
                "pre_flight advisor errored for PR #%d — proceeding without plan",
                pr.number,
                exc_info=True,
            )
            return

        if plan is None:
            return
        self._advisor_pre_flight_plan[pr.number] = plan
        scratchpad = (
            self._config.repo_root / "review_logs" / str(pr.number) / "preflight.json"
        )
        try:
            scratchpad.parent.mkdir(parents=True, exist_ok=True)
            scratchpad.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        except Exception:
            logger.debug("preflight scratchpad write failed", exc_info=True)

    async def _run_post_verify_for_surface(
        self,
        *,
        surface: str,
        diff: str,
        spec: str | None,
        executor_verdict_summary: str,
        executor_fix_diff: str | None = None,
        pre_flight_plan: ReviewPlan | None = None,
        attempt_number: int = 0,
        issue_number: int,
        log_pr_number: int | None = None,
    ) -> PostVerifyResult | None:
        """Run a single post-verify advisor invocation for ``surface``.

        Returns the :class:`PostVerifyResult`, or ``None`` when the advisor
        was skipped (surface/role kill-switch off) or degraded (runner crash
        / parse error surfaced past ``reraise_on_credit_or_bug``). Callers
        layer their own disposition logic on top: binary-gate (block on
        VETO), advisory (downgrade VETO to APPROVE inside the advisor's
        ``run``), requeue (ADR), retry-loop (pr_review).

        Shared skeleton extracted from the five per-surface helpers (T35).
        Each helper now owns only the disposition logic specific to its
        surface; the surface-config lookup, kill-switch check, authority
        resolution (T29 self-modification guard), log path construction,
        :class:`PostVerifyAdvisor` instantiation, and
        ``reraise_on_credit_or_bug`` discipline (``docs/wiki/dark-factory.md``
        §2.2) all live here.

        Authority is resolved on every call, so the pr_review retry loop
        — which wraps this helper in a while-loop — re-checks
        :func:`resolve_post_verify_authority` per iteration. A fix that
        introduces or removes a self-modifying path is picked up on the
        next pass.

        ``log_pr_number`` defaults to ``None``; when supplied, the log
        path is keyed by the PR number, and ``PostVerifyAdvisor.pr_number``
        receives the PR number. When unset, both fall back to
        ``issue_number`` — the convention for surfaces with no PR (ADR
        review, wiki ingest).
        """
        from review_advisor import (  # noqa: PLC0415
            PostVerifyAdvisor,
            PostVerifyInput,
            build_surface_config,
            is_advisor_enabled,
            resolve_post_verify_authority,
        )

        surface_cfg = build_surface_config(surface)
        if not surface_cfg.post_verify_enabled or not is_advisor_enabled(
            surface, "post_verify"
        ):
            return None

        # T29 self-modification guard — diffs touching advisor's own
        # implementation files force veto authority regardless of surface
        # config. Resolved on every call so a fix that introduces or
        # removes a self-modifying path is picked up on the next pass.
        authority = resolve_post_verify_authority(
            surface_config=surface_cfg,
            diff=diff,
        )

        log_key = log_pr_number if log_pr_number is not None else issue_number
        log_path = (
            self._config.repo_root
            / "review_logs"
            / str(log_key)
            / "advisor_session.jsonl"
        )
        advisor = PostVerifyAdvisor(
            runner=self._post_verify_runner,
            surface_config=surface_cfg,
            log_path=log_path,
            pr_number=log_key,
            authority_override=authority,
        )
        try:
            return await advisor.run(
                PostVerifyInput(
                    surface=surface,
                    diff=diff,
                    spec=spec,
                    executor_verdict_summary=executor_verdict_summary,
                    executor_fix_diff=executor_fix_diff,
                    pre_flight_plan=pre_flight_plan,
                    attempt_number=attempt_number,
                    issue_number=issue_number,
                )
            )
        except Exception as exc:
            # Per docs/wiki/dark-factory.md §2.2: the broad-except must
            # reraise credit-exhausted / likely-bug errors so the
            # orchestrator's higher layers see infrastructure failures
            # rather than burn the attempt budget against an exhausted
            # billing signal.
            from exception_classify import (  # noqa: PLC0415
                reraise_on_credit_or_bug,
            )

            reraise_on_credit_or_bug(exc)
            logger.warning(
                "post_verify advisor degraded surface=%s log_key=%s — %r",
                surface,
                log_key,
                exc,
            )
            return None

    async def _run_post_verify_advisor(
        self,
        *,
        pr: PRInfo,
        task: Task,
        wt_path: Path,
        result: ReviewResult,
        diff: str,
        worker_id: int,
        code_scanning_alerts: list[CodeScanningAlert] | None = None,
        surface: str = "pr_review",
    ) -> tuple[ReviewResult, str]:
        """Run PostVerifyAdvisor with bounded VETO retries.

        On APPROVE (or when the surface/role kill-switches are off) returns
        ``(result, diff)`` unchanged.

        On VETO, hands the full advisor transcript back to ``_attempt_review_fix``
        so the executor can address the disagreement, then re-runs the advisor.
        Repeats up to ``surface_cfg.max_veto_retries`` retries. Once the
        retry budget is exhausted, escalates to HITL with the full
        disagreement transcript and returns ``(result, diff)`` flipped to
        REQUEST_CHANGES so the caller skips the merge branch.

        ``surface`` defaults to ``"pr_review"`` for back-compat (T24.7 prep
        for Phase 4 multi-surface wiring); other surfaces (``adr_review``,
        ``visual_gate``, etc.) pass the surface name explicitly. The same
        surface drives the surface-config lookup, the kill-switch check,
        the ``PostVerifyInput.surface`` field, and the metric labels.

        Function-local imports keep the dependency on ``review_advisor``
        contained to where it's used and avoid the auto-lint hook stripping
        an "unused" top-level import.
        """
        from review_advisor import (  # noqa: PLC0415
            build_surface_config,
            is_advisor_enabled,
        )

        surface_cfg = build_surface_config(surface)
        if not surface_cfg.post_verify_enabled or not is_advisor_enabled(
            surface, "post_verify"
        ):
            return result, diff

        # Reset per-PR advisor state on every entry to this function. Each
        # call to _run_post_verify_advisor represents a fresh review cycle
        # with its own retry budget — re-using the previous review's
        # exhausted counter would cause review #2 to skip straight to
        # "exhausted" without giving the executor a fresh chance. The
        # _advisor_results queue is the input to the disagreement transcript
        # rendered for HITL escalation, so it must be cleared too.
        self._advisor_attempt[pr.number] = 0
        self._advisor_results[pr.number] = []
        attempt_number = 0

        while True:
            # Each call re-resolves the T29 self-modification authority
            # override against the current diff (skeleton handles this),
            # so a fix that introduces or removes a self-modifying path
            # is picked up on the next pass.
            pv_result = await self._run_post_verify_for_surface(
                surface=surface,
                diff=diff,
                spec=task.body or None,
                executor_verdict_summary=(result.summary or result.verdict.value),
                pre_flight_plan=self._advisor_pre_flight_plan.get(pr.number),
                attempt_number=attempt_number,
                issue_number=task.id,
                log_pr_number=pr.number,
            )
            if pv_result is None:
                # Degraded path: log and fall through to the executor's
                # verdict (fail-open; a future task may revisit per
                # HYDRAFLOW_REVIEW_POSTVERIFY_FAIL_AS_VETO). The skeleton
                # already re-raised credit/bug errors per
                # docs/wiki/dark-factory.md §2.2; anything reaching here
                # is a true degraded path or a freshly-disabled kill-switch
                # mid-loop. Either way, defer to the executor's verdict.
                return result, diff

            self._advisor_results[pr.number].append(pv_result)

            if pv_result.verdict == "APPROVE":
                # If a prior VETO drove a retry that this APPROVE recovered
                # from, record the recovery in metrics before returning.
                if attempt_number > 0:
                    _emit_advisor_loop_metric(
                        _veto_recovered_total, {"surface": surface}
                    )
                return result, diff

            # VETO — either retry or escalate.
            if attempt_number >= surface_cfg.max_veto_retries:
                _emit_advisor_loop_metric(_veto_exhausted_total, {"surface": surface})
                _emit_advisor_loop_metric(
                    _veto_retries_total,
                    {"surface": surface, "attempt": "exhausted"},
                )
                transcript = self._render_advisor_transcript(pr.number)
                await self._escalate_to_hitl(
                    HitlEscalation(
                        issue_number=task.id,
                        pr_number=pr.number,
                        cause=(
                            f"PostVerifyAdvisor vetoed merge after "
                            f"{attempt_number + 1} attempts"
                        ),
                        origin_label=self._config.review_label[0],
                        comment=(
                            "## Advisor Veto (retry budget exhausted)\n\n"
                            f"{pv_result.reasoning}\n\n"
                            "### Disagreement transcript\n\n"
                            f"{transcript}\n\n"
                            "Escalating to human review."
                        ),
                        event_cause="advisor_post_verify_veto",
                        task=task,
                    )
                )
                return (
                    result.model_copy(
                        update={
                            "verdict": ReviewVerdict.REQUEST_CHANGES,
                            "summary": (result.summary or "")
                            + "\n\nPostVerifyAdvisor vetoed merge after "
                            + f"{attempt_number + 1} attempts: "
                            + pv_result.reasoning,
                        }
                    ),
                    diff,
                )

            # Hand back to the executor with the full advisor transcript so
            # the next executor attempt can directly address the disagreement.
            # Record the retry trigger before mutating attempt_number so the
            # metric attribute reflects the retry number that's about to run
            # (1-indexed: first retry is attempt=1).
            _emit_advisor_loop_metric(
                _veto_retries_total,
                {"surface": surface, "attempt": str(attempt_number + 1)},
            )
            self._advisor_attempt[pr.number] = attempt_number + 1
            attempt_number += 1
            transcript = self._render_advisor_transcript(pr.number)
            result, diff = await self._attempt_review_fix(
                pr,
                task,
                wt_path,
                result,
                diff,
                worker_id,
                code_scanning_alerts=code_scanning_alerts,
                advisor_transcript=transcript,
                suggested_fix_direction=pv_result.suggested_fix_direction,
                surface=surface,
            )

            # If the executor could not produce an APPROVE verdict, abort the
            # advisor loop — the caller's normal rejection path takes over.
            if result.verdict != ReviewVerdict.APPROVE:
                return result, diff

    def _render_advisor_transcript(self, pr_number: int) -> str:
        """Render the in-memory advisor disagreement transcript for ``pr_number``.

        Phase 2 builds the transcript from ``self._advisor_results``;
        T12 will replace this with a persistent ``advisor_session.jsonl``.
        """
        results = self._advisor_results.get(pr_number, [])
        parts: list[str] = []
        for i, r in enumerate(results, 1):
            parts.append(f"### Attempt {i}")
            parts.append(f"Verdict: {r.verdict}")
            parts.append(f"Reasoning: {r.reasoning}")
            for d in r.disagreements:
                parts.append(
                    f"  - [{d.severity}] executor said: {d.executor_claim}\n"
                    f"    advisor said: {d.advisor_assessment}"
                )
            if r.suggested_fix_direction:
                parts.append(f"Suggested direction: {r.suggested_fix_direction}")
            parts.append("")
        return "\n".join(parts)

    @staticmethod
    def _is_product_track_pr(task: Task) -> bool:
        """Check if the task came through the product discovery/shape track."""
        return any(
            "Selected Product Direction" in c or "DECOMPOSITION REQUIRED" in c
            for c in (task.comments or [])
        )

    async def _run_pre_merge_spec_check(
        self, task: Task, diff: str, pr_number: int | None = None
    ) -> bool:
        """Run a lightweight spec-match check before merge.

        Returns True if the implementation matches the spec (proceed with merge).
        Returns False if significant gaps are found (block merge).

        ``pr_number`` (T25) is used to look up the pre-flight ReviewPlan from
        ``self._advisor_pre_flight_plan`` so the post-verify advisor for the
        ``pre_merge_spec_check`` surface can piggyback on ``pr_review``'s
        plan. Defaults to ``None`` for back-compat with regression tests that
        invoke the function directly.
        """
        from spec_match import (  # noqa: PLC0415
            build_self_review_prompt,
            extract_spec_match,
        )

        diff_summary = diff[:5000] if len(diff) > 5000 else diff
        prompt = build_self_review_prompt(task, diff_summary)

        try:
            from agent_cli import build_agent_command  # noqa: PLC0415

            cmd = build_agent_command(
                tool=self._config.review_tool,
                model=self._config.review_model,
                disallowed_tools="Write,Edit,NotebookEdit",
            )
            transcript = await self._reviewers._execute(
                cmd,
                prompt,
                self._config.repo_root,
                {"issue": task.id, "source": "spec-check"},
            )
            result = extract_spec_match(transcript)
            verdict = str(result.get("verdict", "UNKNOWN"))

            if result.get("content"):
                await self._prs.post_comment(
                    task.id,
                    f"## Pre-Merge Spec Check\n\n{result['content']}",
                )

            executor_match = verdict != "MISMATCH"

            # T25: pre_merge_spec_check post-verify advisor — second-opinion
            # gate on the executor's verdict. The advisor sees the spec, the
            # diff, and the executor's verdict summary, and can VETO the merge
            # even when the executor's verdict was MATCH. Piggybacks on
            # ``pr_review``'s pre-flight plan when present (per spec tiering
            # matrix; pre_merge_spec_check has pre_flight_enabled=False).
            #
            # No bounded retry loop here: pre_merge_spec_check is a one-shot
            # binary gate, not a fix-and-iterate cycle. If post-verify VETOes,
            # we return False to block the merge directly; the caller (in
            # _run_post_review_actions) flips the ReviewResult to
            # REQUEST_CHANGES. Future work: fold in retry semantics if the
            # spec-check ever grows a fix loop.
            advisor_blocked = await self._run_pre_merge_spec_check_advisor(
                task=task,
                diff=diff,
                executor_verdict_summary=verdict,
                pr_number=pr_number,
            )
            if advisor_blocked:
                return False

            if verdict == "MISMATCH":
                logger.warning(
                    "Issue #%d spec-match MISMATCH — blocking merge", task.id
                )
                return False
            return executor_match
        except Exception as exc:
            # Fatal infrastructure errors (auth, credit, likely-bug) must
            # propagate so the pipeline's auth-retry / credit-pause / crash
            # handling layers can react. Soft failures block the merge
            # instead of silently approving — the merge gate must be
            # fail-closed, not fail-open (issue #6357).
            from subprocess_util import (  # noqa: PLC0415
                AuthenticationError,
                CreditExhaustedError,
            )

            if isinstance(exc, AuthenticationError | CreditExhaustedError):
                raise
            if isinstance(
                exc,
                TypeError
                | KeyError
                | AttributeError
                | ValueError
                | IndexError
                | NotImplementedError,
            ):
                raise
            # Credit/auth-looking string matches coming through non-SDK paths
            # (e.g. wrapped by review runner). Keep these as raising too —
            # the message is the only signal.
            msg = str(exc)
            if "CreditExhaustedError" in msg or "AuthenticationError" in msg:
                raise
            logger.warning(
                "Spec-match check failed for #%d — blocking merge to avoid fail-open",
                task.id,
                exc_info=True,
            )
            return False

    async def _run_pre_merge_spec_check_advisor(
        self,
        *,
        task: Task,
        diff: str,
        executor_verdict_summary: str,
        pr_number: int | None,
    ) -> bool:
        """Run PostVerifyAdvisor for the ``pre_merge_spec_check`` surface.

        Returns ``True`` when the advisor VETOes (caller must block the merge);
        ``False`` when the advisor APPROVEs, the surface/role kill-switches
        are off, or the advisor degrades on a non-fatal error.

        The pre_merge_spec_check surface is a binary gate — there is no
        fix-and-iterate retry loop here. If VETO occurs, the merge is blocked
        directly; the executor's existing fail-closed behaviour on MISMATCH
        is preserved. ``reraise_on_credit_or_bug`` discipline is preserved
        inside :meth:`_run_post_verify_for_surface` per
        ``docs/wiki/dark-factory.md`` §2.2.
        """
        # Piggyback on pr_review's pre-flight plan when present (per spec
        # tiering matrix). pre_merge_spec_check has pre_flight_enabled=False
        # so it never produces its own plan.
        pre_flight_plan = (
            self._advisor_pre_flight_plan.get(pr_number)
            if pr_number is not None
            else None
        )

        pv_result = await self._run_post_verify_for_surface(
            surface="pre_merge_spec_check",
            diff=diff,
            spec=task.body or None,
            executor_verdict_summary=executor_verdict_summary,
            pre_flight_plan=pre_flight_plan,
            issue_number=task.id,
            log_pr_number=pr_number,
        )
        if pv_result is None:
            # Degraded path or kill-switch off: let the executor's verdict
            # stand. The executor's existing fail-closed semantics on
            # MISMATCH still block bad merges; the advisor is a strict
            # tightening on MATCH-shaped verdicts only.
            return False

        if pv_result.verdict == "VETO":
            logger.warning(
                "Issue #%d pre_merge_spec_check VETO from advisor — blocking merge",
                task.id,
            )
            return True
        return False

    async def _run_pre_flight_advisor_for_adr(
        self,
        *,
        issue: Task,
        diff: str,
    ) -> None:
        """Run :class:`PreFlightAdvisor` for the ``adr_review`` surface (T26).

        ADR review has no PR; this thin wrapper mirrors
        ``_run_pre_flight_advisor`` but keys ``self._advisor_pre_flight_plan``
        and the log path by ``issue.id`` instead of ``pr.number``. Same
        advisor logic, same kill-switch behaviour, same scratchpad
        convention. The trigger is :class:`AlwaysTrigger` per spec, so the
        advisor runs whenever the surface kill-switch allows.

        Function-local imports keep the dependency on ``review_advisor``
        contained to where it's used and avoid the auto-lint hook stripping
        an "unused" top-level import.
        """
        from review_advisor import (  # noqa: PLC0415
            PreFlightAdvisor,
            PreFlightInput,
            build_surface_config,
            diff_stats_from_text,
            is_advisor_enabled,
        )

        surface = "adr_review"
        surface_cfg = build_surface_config(surface)
        if (
            not surface_cfg.pre_flight_enabled
            or surface_cfg.pre_flight_trigger is None
            or not is_advisor_enabled(surface, "pre_flight")
        ):
            return

        diff_stats = diff_stats_from_text(diff)
        from review_advisor import PRContext  # noqa: PLC0415

        pr_ctx = PRContext(prior_fix_attempts=0)
        if not surface_cfg.pre_flight_trigger.should_run(diff_stats, pr_ctx):
            return

        log_path = (
            self._config.repo_root
            / "review_logs"
            / str(issue.id)
            / "advisor_session.jsonl"
        )
        advisor = PreFlightAdvisor(
            runner=self._post_verify_runner,
            surface_config=surface_cfg,
            log_path=log_path,
            pr_number=issue.id,
        )
        try:
            plan = await advisor.run(
                PreFlightInput(
                    surface=surface,
                    diff=diff,
                    spec=issue.body or None,
                    related_paths=diff_stats.changed_paths,
                    prior_attempts=0,
                    issue_number=issue.id,
                )
            )
        except Exception as exc:
            from exception_classify import (  # noqa: PLC0415
                reraise_on_credit_or_bug,
            )

            reraise_on_credit_or_bug(exc)
            logger.warning(
                "pre_flight advisor errored for ADR issue #%d — "
                "proceeding without plan",
                issue.id,
                exc_info=True,
            )
            return

        if plan is None:
            return
        self._advisor_pre_flight_plan[issue.id] = plan
        scratchpad = (
            self._config.repo_root / "review_logs" / str(issue.id) / "preflight.json"
        )
        try:
            scratchpad.parent.mkdir(parents=True, exist_ok=True)
            scratchpad.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        except Exception:
            logger.debug("preflight scratchpad write failed", exc_info=True)

    async def _run_post_verify_advisor_for_adr(
        self,
        *,
        issue: Task,
        diff: str,
        executor_verdict_summary: str,
    ) -> ReviewResult | None:
        """Run :class:`PostVerifyAdvisor` for the ``adr_review`` surface (T26).

        Returns a :class:`ReviewResult` (REQUEST_CHANGES) when the advisor
        VETOes — the caller skips the finalize/approve path. Returns
        ``None`` when the advisor APPROVEs, the kill-switches are off, or
        the advisor degrades on a non-fatal error (proceed with finalize).

        ADR review has no fix loop (``mid_flight_enabled=False``), so this
        is a one-shot binary gate — there's no executor fix step that a
        retry could give different input to. On VETO we requeue the issue
        to ``plan`` with the advisor's reasoning, mirroring the existing
        structural-validation requeue path. ``reraise_on_credit_or_bug``
        discipline is preserved inside :meth:`_run_post_verify_for_surface`
        per ``docs/wiki/dark-factory.md`` §2.2.

        T29 self-modification guard: when the ADR content touches advisor's
        own implementation files, ``resolve_post_verify_authority`` forces
        veto authority regardless of surface config.
        """
        pv_result = await self._run_post_verify_for_surface(
            surface="adr_review",
            diff=diff,
            spec=issue.body or None,
            executor_verdict_summary=executor_verdict_summary,
            pre_flight_plan=self._advisor_pre_flight_plan.get(issue.id),
            issue_number=issue.id,
        )
        if pv_result is None or pv_result.verdict != "VETO":
            return None

        # VETO — requeue to plan with the advisor's reasoning surfaced.
        logger.warning(
            "ADR issue #%d post_verify VETO from advisor — requeueing to plan",
            issue.id,
        )
        veto_reason = pv_result.reasoning or "advisor vetoed without reasoning"
        suggested = pv_result.suggested_fix_direction
        comment_lines = [
            "## ADR Review — Advisor Veto",
            "",
            "The ADR draft passed structural validation but the post-verify "
            "advisor flagged blocking concerns:",
            "",
            f"**Reasoning:** {veto_reason}",
        ]
        if pv_result.disagreements:
            comment_lines.append("")
            comment_lines.append("**Disagreements:**")
            for d in pv_result.disagreements:
                comment_lines.append(f"- [{d.severity}] {d.advisor_assessment}")
        if suggested:
            comment_lines.append("")
            comment_lines.append(f"**Suggested direction:** {suggested}")
        comment_lines.append("")
        comment_lines.append("Update the ADR and re-label to re-enter the pipeline.")
        await self._prs.post_comment(issue.id, "\n".join(comment_lines))

        if issue is not None:
            self._store.enqueue_transition(issue, "plan")
        await self._transitioner.transition(issue.id, "plan")
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.SYSTEM_REROUTE,
                data={
                    "issue": issue.id,
                    "action": "requeued_to_plan",
                    "reasons": [f"advisor veto: {veto_reason}"],
                },
            )
        )
        return ReviewResult(
            pr_number=0,
            issue_number=issue.id,
            verdict=ReviewVerdict.REQUEST_CHANGES,
            summary=f"ADR re-queued — advisor veto: {veto_reason}",
        )

    def _compute_visual_validation(
        self, diff: str, task: Task
    ) -> VisualValidationDecision | None:
        """Compute the visual validation decision for a PR diff."""
        if not self._config.visual_validation_enabled:
            return None
        from visual_validation import compute_visual_validation  # noqa: PLC0415

        return compute_visual_validation(
            self._config,
            diff,
            issue_labels=task.tags,
            issue_comments=task.comments,
        )

    async def _check_sha_skip_guard(self, pr: PRInfo) -> ReviewResult | None:
        """Return a skip result if no new commits since last review, else None."""
        current_sha = await self._prs.get_pr_head_sha(pr.number)
        if isinstance(current_sha, str) and current_sha:
            stored_sha = self._state.get_last_reviewed_sha(pr.issue_number)
            if stored_sha and stored_sha == current_sha:
                logger.info(
                    "PR #%d (issue #%d): skipping review — no new commits since "
                    "last review (SHA %s)",
                    pr.number,
                    pr.issue_number,
                    current_sha[:12],
                )
                return ReviewResult(
                    pr_number=pr.number,
                    issue_number=pr.issue_number,
                    summary="Skipped — no new commits since last review",
                )
        return None

    async def _run_visual_validation(
        self, pr: PRInfo, wt_path: Path, worker_id: int
    ) -> VisualValidationReport | None:
        """Run visual validation if enabled. Returns None when disabled or on error."""
        if self._visual_validator is None:
            return None
        try:
            await self._publish_review_status(pr, worker_id, "visual_check")
            # The check_fn is a placeholder — real implementations would inject
            # an actual screenshot capture + diffing callable.  For now the
            # validator infrastructure is wired up but produces an empty report
            # unless a check function is supplied externally.
            report = await self._visual_validator.validate_screens(
                [], self._noop_visual_check
            )
            if report.screens:
                logger.info(
                    "PR #%d: visual validation %s (%d screens, %d retries)",
                    pr.number,
                    report.overall_verdict.value,
                    len(report.screens),
                    report.total_retries,
                )
            return report
        except (RuntimeError, OSError):
            logger.warning(
                "Visual validation failed for PR #%d — skipping",
                pr.number,
                exc_info=True,
            )
            return None

    @staticmethod
    async def _noop_visual_check(screen_name: str) -> VisualScreenResult:
        """Default no-op visual check (placeholder for real implementation)."""
        return VisualScreenResult(screen_name=screen_name, diff_ratio=0.0)

    async def _handle_visual_failure(
        self,
        pr: PRInfo,
        task: Task,
        result: ReviewResult,
        report: VisualValidationReport,
        worker_id: int,
    ) -> ReviewResult:
        """Handle a visual validation failure — escalate to HITL with report details."""
        summary_text = report.format_summary()

        if report.infra_failures > 0 and report.visual_diffs == 0:
            cause = "Visual validation infrastructure failure (not a visual diff)"
        else:
            cause = "Visual validation detected failures"

        await self._publish_review_status(pr, worker_id, "escalating")
        await self._escalate_to_hitl(
            HitlEscalation(
                issue_number=task.id,
                pr_number=pr.number,
                cause=cause,
                origin_label=self._config.review_label[0],
                comment=(
                    f"**Visual validation failed** — escalating to human review.\n\n"
                    f"{summary_text}"
                ),
                event_cause="visual_validation_failed",
                extra_event_data={
                    "visual_verdict": report.overall_verdict.value,
                    "visual_retries": report.total_retries,
                    "infra_failures": report.infra_failures,
                    "visual_diffs": report.visual_diffs,
                },
                task=task,
            )
        )
        result.verdict = ReviewVerdict.REQUEST_CHANGES
        result.summary = f"Visual validation failed: {cause}"
        return result

    async def _record_review_outcome(self, pr: PRInfo, result: ReviewResult) -> None:
        """Record all post-review state: verdicts, SHA, duration, insights.

        Also records a harness failure for any non-APPROVE verdict.
        """
        self._state.mark_pr(pr.number, result.verdict.value)
        self._state.mark_issue(pr.issue_number, "reviewed")
        self._state.record_review_verdict(result.verdict.value, result.fixes_made)
        if result.verdict == ReviewVerdict.APPROVE:
            self._state.increment_session_counter("reviewed")

        post_review_sha = await self._prs.get_pr_head_sha(pr.number)
        if isinstance(post_review_sha, str) and post_review_sha:
            self._state.set_last_reviewed_sha(pr.issue_number, post_review_sha)

        if result.duration_seconds > 0:
            self._state.record_review_duration(result.duration_seconds)
        await self._record_review_insight(result)
        if result.verdict != ReviewVerdict.APPROVE:
            record_harness_failure(
                self._harness_insights,
                pr.issue_number,
                FailureCategory.REVIEW_REJECTION,
                f"Review verdict: {result.verdict.value}. {result.summary[:200]}",
                stage=PipelineStage.REVIEW,
                pr_number=pr.number,
            )

    async def _cleanup_worktree(
        self, pr: PRInfo, result: ReviewResult, skip: bool
    ) -> None:
        """Destroy the worktree unless it should be preserved."""
        # Preserve worktrees for interrupted reviews so work can be resumed.
        # If the PR was already merged, the worktree is no longer needed.
        if self._stop_event.is_set() and not result.merged:
            skip = True

        if not skip:
            try:
                await self._workspaces.post_work_cleanup(
                    pr.issue_number, phase="review"
                )
                self._state.remove_workspace(pr.issue_number)
            except RuntimeError as exc:
                logger.warning(
                    "Could not clean up worktree for issue #%d: %s",
                    pr.issue_number,
                    exc,
                )

    async def _merge_with_main(
        self,
        pr: PRInfo,
        issue: Task,
        wt_path: Path,
        worker_id: int,
    ) -> bool:
        """Merge main into the PR branch, resolving conflicts if needed.

        Returns True on success, False on failure (escalates to HITL).
        """
        return await self._conflict_resolver.merge_with_main(
            pr,
            issue,
            wt_path,
            worker_id,
            escalate_fn=self._escalate_to_hitl,
            publish_fn=self._publish_review_status,
        )

    def _build_bead_review_context(self, issue: Task) -> list[dict[str, object]] | None:
        """Build bead task context for the reviewer."""
        mapping = self._state.get_bead_mapping(issue.id)
        if not mapping:
            return None

        from task_graph import extract_phases  # noqa: PLC0415

        # Try to extract phases from plan comment for file/test info
        phase_info: dict[str, dict[str, object]] = {}
        for comment in issue.comments:
            phases = extract_phases(comment)
            for phase in phases:
                phase_info[phase.id] = {
                    "files": ", ".join(phase.files) or "N/A",
                    "tests": ", ".join(phase.tests) or "N/A",
                }

        bead_tasks: list[dict[str, object]] = []
        for phase_id, bead_id in sorted(mapping.items()):
            info = phase_info.get(phase_id, {})
            bead_tasks.append(
                {
                    "id": bead_id,
                    "phase": phase_id,
                    "status": "closed",  # assume closed after implementation
                    "files": info.get("files", "N/A"),
                    "tests": info.get("tests", "N/A"),
                }
            )

        return bead_tasks if bead_tasks else None

    async def _run_and_post_review(
        self,
        pr: PRInfo,
        issue: Task,
        wt_path: Path,
        diff: str,
        worker_id: int,
        code_scanning_alerts: list[CodeScanningAlert] | None = None,
        pre_flight_plan: ReviewPlan | None = None,
        surface: str = "pr_review",
    ) -> ReviewResult:
        """Run the reviewer, push fixes, post summary, submit formal review.

        ``pre_flight_plan`` is the optional :class:`ReviewPlan` produced by
        ``PreFlightAdvisor``. When set, it is rendered into the executor's
        review prompt as a focus rubric.

        ``surface`` selects which advisor surface config drives the
        executor's mid-flight prompt assembly. Defaults to ``"pr_review"``
        for back-compat (T24.7).
        """
        # Build bead context for per-bead review when beads are enabled
        bead_tasks = self._build_bead_review_context(issue)

        result = await self._reviewers.review(
            pr,
            issue,
            wt_path,
            diff,
            worker_id=worker_id,
            code_scanning_alerts=code_scanning_alerts,
            bead_tasks=bead_tasks,
            pre_flight_plan=pre_flight_plan,
            surface=surface,
        )

        if result.fixes_made:
            await self._prs.push_branch(wt_path, pr.branch)

        if result.summary and pr.number > 0:
            await self._prs.post_pr_comment(pr.number, result.summary)
            # Ingest review feedback into the per-repo wiki
            await self._wiki_ingest_review(
                pr.issue_number,
                transcript=result.transcript,
                summary=result.summary,
            )

        if pr.number > 0 and result.verdict != ReviewVerdict.APPROVE:
            try:
                await self._prs.submit_review(pr.number, result.verdict, result.summary)
            except SelfReviewError:
                logger.info(
                    "Skipping formal %s review on own PR #%d"
                    " — already posted as comment",
                    result.verdict.value,
                    pr.number,
                )

        if result.verdict == ReviewVerdict.APPROVE:
            result = await self._check_adversarial_threshold(
                pr,
                issue,
                wt_path,
                diff,
                result,
                worker_id,
                code_scanning_alerts=code_scanning_alerts,
            )

        return result

    async def _handle_self_fix_re_review(
        self,
        pr: PRInfo,
        issue: Task,
        wt_path: Path,
        result: ReviewResult,
        diff: str,
        worker_id: int,
        code_scanning_alerts: list[CodeScanningAlert] | None = None,
        surface: str = "pr_review",
    ) -> tuple[ReviewResult, str]:
        """Re-review a PR after the reviewer self-fixed findings.

        Returns ``(updated_result, updated_diff)``.  If the re-review
        approves, the upgraded result and refreshed diff are returned.
        On failure or continued rejection the original result is preserved.

        ``surface`` selects which advisor surface config drives the
        executor's mid-flight prompt assembly on the re-review. Defaults to
        ``"pr_review"`` for back-compat (T30.5 I2: thread surface through
        retry-path re-reviews so future multi-surface retry loops route to
        the correct surface config rather than silently defaulting).
        """
        logger.info(
            "PR #%d: reviewer self-fixed with %s verdict — re-reviewing updated code",
            pr.number,
            result.verdict.value,
        )

        async def _re_review() -> tuple[ReviewResult, str]:
            await self._publish_review_status(pr, worker_id, "re_reviewing")
            updated_diff = await self._prs.get_pr_diff(pr.number)
            # Thread the pre-flight plan into retries so the executor keeps
            # the same focus rubric across the loop (T24.5 closed I3).
            re_result = await self._reviewers.review(
                pr,
                issue,
                wt_path,
                updated_diff,
                worker_id=worker_id,
                code_scanning_alerts=code_scanning_alerts,
                pre_flight_plan=self._advisor_pre_flight_plan.get(pr.number),
                surface=surface,
            )
            if re_result.fixes_made:
                await self._prs.push_branch(wt_path, pr.branch)
            if re_result.verdict == ReviewVerdict.APPROVE:
                logger.info(
                    "PR #%d: self-fix re-review passed — upgrading verdict to APPROVE",
                    pr.number,
                )
                return re_result, updated_diff
            logger.info(
                "PR #%d: self-fix re-review still returned %s — proceeding with rejection",
                pr.number,
                re_result.verdict.value,
            )
            return result, updated_diff

        return await run_with_fatal_guard(
            _re_review(),
            on_failure=lambda _: (result, diff),
            context=f"PR #{pr.number}: self-fix re-review failed — falling back to original rejection",
            log=logger,
        )

    async def _run_single_review_fix(
        self,
        pr: PRInfo,
        task: Task,
        wt_path: Path,
        result: ReviewResult,
        attempt: int,
        worker_id: int,
        code_scanning_alerts: list[CodeScanningAlert] | None = None,
        advisor_transcript: str | None = None,
        suggested_fix_direction: str | None = None,
        surface: str = "pr_review",
    ) -> tuple[ReviewResult, str] | None:
        """Run one fix-then-re-review cycle.

        Returns ``(re_result, updated_diff)`` on success, or ``None`` if
        the fix agent made no changes.

        ``advisor_transcript`` and ``suggested_fix_direction`` are
        propagated into the fix-agent prompt when the call originates from
        the post-verify advisor's VETO retry loop.

        ``surface`` selects which advisor surface config drives the
        re-review's mid-flight prompt assembly. Defaults to ``"pr_review"``
        for back-compat (T30.5 I2).
        """
        await self._publish_review_status(pr, worker_id, "fixing_review")

        fix_result = await self._reviewers.fix_review_findings(
            pr,
            task,
            wt_path,
            result.summary,
            worker_id=worker_id,
            advisor_transcript=advisor_transcript,
            suggested_fix_direction=suggested_fix_direction,
        )

        if not fix_result.fixes_made:
            logger.info(
                "PR #%d: fix agent made no changes on attempt %d — giving up",
                pr.number,
                attempt,
            )
            return None

        # Push the fixes
        await self._prs.push_branch(wt_path, pr.branch)

        # Re-review
        await self._publish_review_status(pr, worker_id, "re_reviewing")
        updated_diff = await self._prs.get_pr_diff(pr.number)
        # Thread the pre-flight plan into retries so the executor keeps
        # the same focus rubric across the loop (T24.5 closed I3).
        re_result = await self._reviewers.review(
            pr,
            task,
            wt_path,
            updated_diff,
            worker_id=worker_id,
            code_scanning_alerts=code_scanning_alerts,
            pre_flight_plan=self._advisor_pre_flight_plan.get(pr.number),
            surface=surface,
        )

        if re_result.fixes_made:
            await self._prs.push_branch(wt_path, pr.branch)

        return re_result, updated_diff

    async def _attempt_review_fix(
        self,
        pr: PRInfo,
        task: Task,
        wt_path: Path,
        result: ReviewResult,
        diff: str,
        worker_id: int,
        code_scanning_alerts: list[CodeScanningAlert] | None = None,
        advisor_transcript: str | None = None,
        suggested_fix_direction: str | None = None,
        surface: str = "pr_review",
    ) -> tuple[ReviewResult, str]:
        """Spin up a sub-agent to fix review findings, then re-review.

        Tries up to 2 fix-then-review cycles. If the fix agent makes
        changes and the re-review approves, returns the upgraded result.
        Otherwise falls through to the normal rejection path.

        When called from the post-verify advisor's VETO retry loop,
        ``advisor_transcript`` and ``suggested_fix_direction`` thread the
        full advisor disagreement record into the executor's prompt so the
        next attempt can directly address the disagreement.

        ``surface`` selects which advisor surface config drives the
        re-review's mid-flight prompt assembly. Defaults to ``"pr_review"``
        for back-compat (T30.5 I2).
        """
        max_fix_attempts = 2

        for attempt in range(1, max_fix_attempts + 1):
            logger.info(
                "PR #%d: attempting review fix %d/%d",
                pr.number,
                attempt,
                max_fix_attempts,
            )

            attempt_outcome = await run_with_fatal_guard(
                self._run_single_review_fix(
                    pr,
                    task,
                    wt_path,
                    result,
                    attempt,
                    worker_id,
                    code_scanning_alerts=code_scanning_alerts,
                    advisor_transcript=advisor_transcript,
                    suggested_fix_direction=suggested_fix_direction,
                    surface=surface,
                ),
                on_failure=lambda _: None,
                context=f"PR #{pr.number}: review fix attempt {attempt} failed — falling back to rejection",
                log=logger,
            )

            if attempt_outcome is None:
                break

            re_result, updated_diff = attempt_outcome

            if re_result.verdict == ReviewVerdict.APPROVE:
                logger.info(
                    "PR #%d: review fix attempt %d succeeded — upgrading to APPROVE",
                    pr.number,
                    attempt,
                )
                return re_result, updated_diff

            # Still rejected — use the new feedback for the next attempt
            logger.info(
                "PR #%d: review fix attempt %d still %s — %s",
                pr.number,
                attempt,
                re_result.verdict.value,
                "retrying" if attempt < max_fix_attempts else "falling through",
            )
            result = re_result
            diff = updated_diff

        return result, diff

    async def _run_delta_verification(self, pr: PRInfo, diff: str) -> str:
        """Run delta verification comparing plan's File Delta section to actual diff.

        Returns a summary string (empty if no plan or no delta section).
        """
        from delta_verifier import parse_file_delta, verify_delta

        plan_path = self._config.plans_dir / f"issue-{pr.issue_number}.md"
        if not plan_path.exists():
            return ""

        try:
            plan_text = plan_path.read_text()
        except OSError:
            return ""

        planned_files = parse_file_delta(plan_text)
        if not planned_files:
            return ""

        # Extract actual changed files from the diff
        actual_files = await self._prs.get_pr_diff_names(pr.number)
        report = verify_delta(planned_files, actual_files)

        if report.has_drift:
            summary = report.format_summary()
            logger.warning(
                "Delta drift for PR #%d (issue #%d): %d missing, %d unexpected",
                pr.number,
                pr.issue_number,
                len(report.missing),
                len(report.unexpected),
            )
            return summary
        return ""

    async def _handle_approved_merge(
        self,
        pr: PRInfo,
        issue: Task,
        result: ReviewResult,
        diff: str,
        worker_id: int,
        code_scanning_alerts: list[CodeScanningAlert] | None = None,
        visual_decision: VisualValidationDecision | None = None,
    ) -> None:
        """Attempt merge for an approved PR (with optional CI gate)."""
        ctx = MergeApprovalContext(
            pr=pr,
            issue=issue,
            result=result,
            diff=diff,
            worker_id=worker_id,
            ci_gate_fn=self.wait_and_fix_ci,
            escalate_fn=self._escalate_to_hitl,
            publish_fn=self._publish_review_status,
            code_scanning_alerts=code_scanning_alerts,
            visual_gate_fn=self.check_visual_gate,
            visual_decision=visual_decision,
            merge_conflict_fix_fn=self._attempt_post_merge_conflict_fix,
        )
        await self._post_merge.handle_approved(ctx)

    async def _attempt_post_merge_conflict_fix(
        self,
        pr: PRInfo,
        issue: Task,
        worker_id: int,
    ) -> bool:
        """Attempt conflict resolution after a failed GitHub merge.

        This keeps the standard review path aligned with unsticker behavior:
        resolve merge conflicts on the branch, push updates, then retry merge.
        """
        wt_path = self._config.workspace_path_for_issue(pr.issue_number)
        if not wt_path.exists():
            wt_path = await self._workspaces.create(pr.issue_number, pr.branch)

        resolution = await self._conflict_resolver.resolve_merge_conflicts(
            pr,
            issue,
            wt_path,
            worker_id=worker_id,
            source="post_merge",
        )
        if not resolution.success:
            return False

        if resolution.used_rebuild:
            await self._prs.push_branch(
                self._config.workspace_path_for_issue(pr.issue_number),
                pr.branch,
                force=True,
            )
        else:
            await self._prs.push_branch(wt_path, pr.branch)
        return True

    async def check_visual_gate(
        self,
        pr: PRInfo,
        issue: Task,
        result: ReviewResult,
        worker_id: int,
    ) -> bool:
        """Run visual validation gate before merge finalization.

        Returns True if merge may proceed, False to block.
        When the gate is bypassed an audit event is emitted.

        T27: PostVerifyAdvisor (surface=``visual_gate``) wraps the visual
        pipeline's PASS verdict. The visual_gate surface is post-verify
        only (no pre-flight, no mid-flight, ``max_veto_retries=1``) so this
        is a one-shot binary gate — VETO blocks the merge and routes
        through the existing failure/escalation path with the advisor's
        reasoning attached. APPROVE / disabled / degraded all fall through
        to the existing PASS sign-off behaviour.
        """
        start = time.monotonic()

        if not self._config.visual_gate_enabled:
            return True

        # Emergency bypass — allow merge but log an audit event
        if self._config.visual_gate_bypass:
            logger.warning(
                "PR #%d: visual gate BYPASSED (emergency kill-switch)",
                pr.number,
            )
            if self._bus:
                await self._bus.publish(
                    HydraFlowEvent(
                        type=EventType.VISUAL_GATE,
                        data=VisualGatePayload(
                            pr=pr.number,
                            issue=issue.id,
                            worker=worker_id,
                            verdict="bypass",
                            reason="emergency kill-switch active",
                            runtime_seconds=round(time.monotonic() - start, 3),
                        ),
                    )
                )
            result.visual_passed = True
            return True

        verdict, artifacts, reason = await self._invoke_visual_pipeline(
            pr, issue, worker_id
        )

        runtime = round(time.monotonic() - start, 3)

        # Emit gate telemetry
        await self._emit_visual_gate_telemetry(
            pr, issue, worker_id, verdict, reason, runtime, artifacts
        )

        if verdict == "pass":
            # T27: post-verify advisor second-opinions the visual pipeline's
            # PASS verdict. VETO blocks the merge and routes through the
            # existing failure path; APPROVE / kill-switch off / degraded
            # falls through to the sign-off path unchanged.
            advisor_block_reason = await self._run_visual_gate_advisor(
                pr=pr,
                issue=issue,
                executor_verdict_summary=verdict,
                pipeline_reason=reason,
                artifacts=artifacts,
            )
            if advisor_block_reason is not None:
                await self._handle_visual_gate_failure(
                    pr,
                    issue,
                    result,
                    verdict="advisor_veto",
                    reason=advisor_block_reason,
                )
                return False
            await self._handle_visual_gate_pass(pr, result, verdict, runtime, artifacts)
            return True

        await self._handle_visual_gate_failure(pr, issue, result, verdict, reason)
        return False

    async def _run_visual_gate_advisor(
        self,
        *,
        pr: PRInfo,
        issue: Task,
        executor_verdict_summary: str,
        pipeline_reason: str,
        artifacts: dict[str, str],
    ) -> str | None:
        """Run :class:`PostVerifyAdvisor` for the ``visual_gate`` surface (T27).

        Returns the advisor's VETO reasoning string (caller must block the
        merge) when the advisor VETOes; ``None`` when the advisor APPROVEs,
        the surface/role kill-switches are off, or the advisor degrades on
        a non-fatal error (proceed with the visual pipeline's PASS verdict).

        The "diff" passed to the advisor is a textual descriptor of the
        visual diff (verdict, pipeline reason, artifact links/count) — not
        a unified text diff. Visual gate has ``mid_flight_enabled=False``
        and ``pre_flight_enabled=False``, so this is a one-shot binary gate
        with a tighter retry budget (``max_veto_retries=1`` per spec) — no
        plan threading, no fix-and-iterate loop. ``reraise_on_credit_or_bug``
        discipline is preserved inside :meth:`_run_post_verify_for_surface`
        per ``docs/wiki/dark-factory.md`` §2.2.

        T29 self-modification guard: visual_gate has no diff to inspect for
        self-modifying paths, so the descriptor is passed for completeness
        but will not normally trigger the guard. The descriptor is non-empty
        — the advisor needs *something* to evaluate.
        """
        diff_descriptor = self._build_visual_diff_descriptor(
            pr=pr,
            issue=issue,
            executor_verdict_summary=executor_verdict_summary,
            pipeline_reason=pipeline_reason,
            artifacts=artifacts,
        )

        pv_result = await self._run_post_verify_for_surface(
            surface="visual_gate",
            diff=diff_descriptor,
            spec=issue.body or None,
            executor_verdict_summary=executor_verdict_summary,
            issue_number=issue.id,
            log_pr_number=pr.number,
        )
        if pv_result is None or pv_result.verdict != "VETO":
            return None

        logger.warning(
            "PR #%d visual_gate VETO from advisor — blocking merge",
            pr.number,
        )
        veto_reason = pv_result.reasoning or "advisor vetoed without reasoning"
        return f"advisor veto: {veto_reason}"

    def _build_visual_diff_descriptor(
        self,
        *,
        pr: PRInfo,
        issue: Task,
        executor_verdict_summary: str,
        pipeline_reason: str,
        artifacts: dict[str, str],
    ) -> str:
        """Render a textual descriptor of the visual gate's evidence.

        The visual gate has no unified text diff — the advisor's input
        is a synthesized summary of the visual pipeline's verdict, the
        pipeline's reason string, and links/keys for any artifacts the
        pipeline produced (baseline, diff image, report URL). Always
        non-empty so the advisor has *something* to evaluate.
        """
        lines = [
            f"PR #{pr.number} — visual gate evidence",
            f"Issue: {issue.id}",
            f"Pipeline verdict: {executor_verdict_summary}",
            f"Pipeline reason: {pipeline_reason or '(none)'}",
        ]
        if artifacts:
            lines.append(f"Artifact count: {len(artifacts)}")
            for name, link in sorted(artifacts.items()):
                lines.append(f"- {name}: {link}")
        else:
            lines.append("Artifacts: (none)")
        return "\n".join(lines)

    async def _emit_visual_gate_telemetry(
        self,
        pr: PRInfo,
        issue: Task,
        worker_id: int,
        verdict: str,
        reason: str,
        runtime: float,
        artifacts: dict[str, str],
    ) -> None:
        """Emit a VISUAL_GATE event with pipeline results."""
        if self._bus:
            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.VISUAL_GATE,
                    data=VisualGatePayload(
                        pr=pr.number,
                        issue=issue.id,
                        worker=worker_id,
                        verdict=verdict,
                        reason=reason,
                        runtime_seconds=runtime,
                        retries=0,
                        artifact_count=len(artifacts),
                        artifacts=artifacts,
                    ),
                )
            )

    async def _handle_visual_gate_pass(
        self,
        pr: PRInfo,
        result: ReviewResult,
        verdict: str,
        runtime: float,
        artifacts: dict[str, str],
    ) -> None:
        """Post sign-off comment and mark visual gate as passed."""
        result.visual_passed = True
        sign_off = (
            f"**Visual Gate: PASSED**\n\n"
            f"Visual validation completed successfully.\n"
            f"Verdict: `{verdict}` | Runtime: {runtime}s"
        )
        if artifacts:
            sign_off += "\n\n**Artifacts:**\n"
            for name, link in artifacts.items():
                sign_off += f"- [{name}]({link})\n"
        try:
            await self._prs.post_pr_comment(pr.number, sign_off)
        except (RuntimeError, OSError):
            logger.warning(
                "PR #%d: could not post visual gate sign-off comment",
                pr.number,
                exc_info=True,
            )

    async def _handle_visual_gate_failure(
        self,
        pr: PRInfo,
        issue: Task,
        result: ReviewResult,
        verdict: str,
        reason: str,
    ) -> None:
        """Post block comment, escalate to HITL, and mark visual gate as failed."""
        result.visual_passed = False
        logger.warning(
            "PR #%d: visual gate BLOCKED (verdict=%s) — blocking merge",
            pr.number,
            verdict,
        )
        try:
            await self._prs.post_pr_comment(
                pr.number,
                f"**Visual Gate: BLOCKED**\n\n"
                f"Verdict: `{verdict}` — {reason}\n"
                f"Escalating to human review.",
            )
        except (RuntimeError, OSError):
            logger.warning(
                "PR #%d: could not post visual gate block comment",
                pr.number,
                exc_info=True,
            )
        await self._escalate_to_hitl(
            HitlEscalation(
                issue_number=pr.issue_number,
                pr_number=pr.number,
                cause=f"Visual gate {verdict}",
                origin_label=self._config.review_label[0],
                comment=f"Visual gate verdict: {verdict} — {reason}",
                event_cause="visual_gate_failed",
                task=issue,
            )
        )

    async def _invoke_visual_pipeline(
        self,
        pr: PRInfo,
        issue: Task,  # noqa: ARG002
        worker_id: int,  # noqa: ARG002
    ) -> tuple[str, dict[str, str], str]:
        """Invoke the external visual validation service.

        Returns (verdict, artifacts, reason).
        Override or mock this method in tests to exercise fail paths.
        In production this will call an external visual validation service.

        WARNING: This is a placeholder stub. With visual_gate_enabled=True the
        gate will always pass until this method is connected to a real service.
        """
        logger.warning(
            "PR #%d: _invoke_visual_pipeline is a stub — visual gate is not connected "
            "to a real validation service; verdict will always be 'pass'",
            pr.number,
        )
        return "pass", {}, "visual validation passed"

    async def _run_ci_wait_attempt(
        self, pr: PRInfo, attempt: int, worker_id: int
    ) -> tuple[bool, str]:
        """Poll CI once. Return (passed, message)."""
        await self._publish_review_status(pr, worker_id, "ci_wait")
        return await self._prs.wait_for_ci(
            pr.number,
            self._config.ci_check_timeout,
            self._config.ci_poll_interval,
            self._stop_event,
        )

    async def _run_ci_fix_attempt(
        self,
        pr: PRInfo,
        issue: Task,
        wt_path: Path,
        summary: str,
        worker_id: int,
        attempt: int,
        *,
        ci_logs: str = "",
        code_scanning_alerts: list[CodeScanningAlert] | None = None,
    ) -> bool:
        """Run the CI fix agent. Return True if changes were made and pushed."""
        await self._publish_review_status(pr, worker_id, "ci_fix")
        fix_result = await self._reviewers.fix_ci(
            pr,
            issue,
            wt_path,
            summary,
            attempt=attempt,
            worker_id=worker_id,
            ci_logs=ci_logs,
            code_scanning_alerts=code_scanning_alerts,
        )
        if not fix_result.fixes_made:
            logger.info(
                "CI fix agent made no changes for PR #%d — stopping retries",
                pr.number,
            )
            return False
        await self._prs.push_branch(wt_path, pr.branch)
        return True

    async def _escalate_ci_failure(
        self,
        pr: PRInfo,
        issue: Task,
        logs: str,
        ci_fix_attempts: int,
    ) -> None:
        """Record state, record harness failure, escalate to HITL."""
        self._state.record_ci_fix_rounds(ci_fix_attempts)
        record_harness_failure(
            self._harness_insights,
            issue.id,
            FailureCategory.CI_FAILURE,
            f"CI failed after {ci_fix_attempts} fix attempt(s): {logs[:200]}",
            pr_number=pr.number,
            stage=PipelineStage.REVIEW,
        )
        cause = f"CI failed after {ci_fix_attempts} fix attempt(s): {logs[:200]}"
        # Pre-store richer context with full CI logs before routing to diagnostic loop
        from models import EscalationContext  # noqa: PLC0415

        context = EscalationContext(
            cause=cause,
            origin_phase="review",
            ci_logs=logs,
            pr_number=pr.number,
        )
        self._state.set_escalation_context(issue.id, context)
        await self._escalate_to_hitl(
            HitlEscalation(
                issue_number=issue.id,
                pr_number=pr.number,
                cause=cause,
                origin_label=self._config.review_label[0],
                comment=(
                    f"**CI failed** after {ci_fix_attempts} fix attempt(s).\n\n"
                    f"Last failure: {logs}\n\n"
                    f"PR not merged — escalating to human review."
                ),
                event_cause="ci_failed",
                extra_event_data={"ci_fix_attempts": ci_fix_attempts},
                task=issue,
            )
        )

    async def wait_and_fix_ci(
        self,
        pr: PRInfo,
        issue: Task,
        wt_path: Path,
        result: ReviewResult,
        worker_id: int,
        code_scanning_alerts: list[CodeScanningAlert] | None = None,
    ) -> bool:
        """Wait for CI and attempt fixes if it fails.

        Returns *True* if CI passed and the PR should be merged.
        Mutates *result* to set ``ci_passed`` and ``ci_fix_attempts``.
        """
        max_attempts = self._config.max_ci_fix_attempts
        summary = ""

        for attempt in range(max_attempts + 1):
            passed, summary = await self._run_ci_wait_attempt(pr, attempt, worker_id)
            if passed:
                result.ci_passed = True
                return True

            if attempt >= max_attempts:
                break

            # Fetch full CI logs for observability injection
            ci_logs = ""
            try:
                raw = await self._prs.fetch_ci_failure_logs(pr.number)
                if raw:
                    from log_context import truncate_log  # noqa: PLC0415

                    ci_logs = truncate_log(raw, self._config.max_ci_log_chars)
            except (RuntimeError, OSError):
                logger.debug(
                    "Could not fetch CI failure logs for PR #%d",
                    pr.number,
                    exc_info=True,
                )

            made_changes = await self._run_ci_fix_attempt(
                pr,
                issue,
                wt_path,
                summary,
                worker_id,
                attempt + 1,
                ci_logs=ci_logs,
                code_scanning_alerts=code_scanning_alerts,
            )
            result.ci_fix_attempts += 1
            if not made_changes:
                break

        await self._handle_ci_exhaustion(pr, issue, result, summary, worker_id)
        return False

    async def _handle_ci_exhaustion(
        self,
        pr: PRInfo,
        issue: Task,
        result: ReviewResult,
        summary: str,
        worker_id: int,
    ) -> None:
        """Handle the case where all CI fix attempts are exhausted."""
        result.ci_passed = False
        if result.transcript:
            await self._suggest_memory(
                result.transcript, "ci_fix_failure", f"PR #{pr.number}"
            )
        await self._publish_review_status(pr, worker_id, "escalating")
        await self._escalate_ci_failure(pr, issue, summary, result.ci_fix_attempts)

    async def _record_review_insight(self, result: ReviewResult) -> None:
        """Record a review result and file improvement proposals if patterns emerge.

        Wrapped in try/except so insight failures never interrupt the review flow.
        """
        status = "ok"
        details: dict[str, object] = {
            "issue_number": result.issue_number,
            "pr_number": result.pr_number,
        }
        try:
            record = ReviewRecord(
                pr_number=result.pr_number,
                issue_number=result.issue_number,
                timestamp=datetime.now(UTC).isoformat(),
                verdict=result.verdict,
                summary=result.summary,
                fixes_made=result.fixes_made,
                categories=extract_categories(result.summary),
                raw_feedback=result.transcript,
            )
            self._insights.append_review(record)

            # Dual-write to Hindsight removed in Phase 3 cutover.

            # Enqueue pattern analysis for the retrospective loop
            if self._retrospective_queue is not None:
                from retrospective_queue import QueueItem, QueueKind  # noqa: PLC0415

                self._retrospective_queue.append(
                    QueueItem(
                        kind=QueueKind.REVIEW_PATTERNS,
                        pr_number=result.pr_number,
                        issue_number=result.issue_number,
                    )
                )
            else:
                # Fallback: inline analysis when queue not wired
                recent = self._insights.load_recent(self._config.review_insight_window)
                patterns = analyze_patterns(
                    recent, self._config.review_pattern_threshold
                )
                proposed = self._insights.get_proposed_categories()

                for category, count, evidence in patterns:
                    if category in proposed:
                        continue
                    body = build_insight_issue_body(
                        category, count, len(recent), evidence
                    )
                    desc = CATEGORY_DESCRIPTIONS.get(category, category)
                    title = f"[Review Insight] Recurring feedback: {desc}"
                    labels = self._config.find_label[:1]
                    await self._transitioner.create_task(title, body, labels)
                    self._insights.mark_category_proposed(category)
                    self._insights.record_proposal(category, pre_count=count)

                stale = verify_proposals(self._insights, recent)
                for category in stale:
                    desc = CATEGORY_DESCRIPTIONS.get(category, category)
                    title = f"[HITL] Stale review insight: {desc}"
                    body = (
                        f"## Stale Improvement Proposal\n\n"
                        f"The improvement proposal for **{category}** ({desc}) "
                        f"was filed over {_PROPOSAL_STALE_DAYS} days ago but the "
                        f"pattern frequency has not decreased. Human intervention is "
                        f"required to resolve this recurring feedback loop.\n\n"
                        f"---\n*Auto-escalated by HydraFlow review insight verification.*"
                    )
                    hitl_labels = list(self._config.hitl_label)
                    await self._transitioner.create_task(title, body, hitl_labels)
        except (RuntimeError, OSError):
            status = "error"
            details["error"] = "review insight recording failed"
            logger.warning(
                "Review insight recording failed for PR #%d",
                result.pr_number,
                exc_info=True,
            )
        finally:
            if self._update_bg_worker_status:
                try:
                    self._update_bg_worker_status("retrospective", status, details)
                except (RuntimeError, OSError):
                    logger.warning(
                        "retrospective status callback failed for PR #%d",
                        result.pr_number,
                        exc_info=True,
                    )

    async def _publish_review_status(
        self, pr: PRInfo, worker_id: int, status: str
    ) -> None:
        """Emit a REVIEW_UPDATE event with the given status."""
        await publish_review_status(self._bus, pr, worker_id, status)

    async def _escalate_to_hitl(self, esc: HitlEscalation) -> None:
        """Route escalation through diagnostic loop instead of direct HITL."""
        from models import EscalationContext  # noqa: PLC0415

        # Build escalation context if not already stored by the call site
        existing = self._state.get_escalation_context(esc.issue_number)
        if existing is None:
            context = EscalationContext(
                cause=esc.cause,
                origin_phase="review",
                pr_number=esc.pr_number,
            )
            self._state.set_escalation_context(esc.issue_number, context)

        self._state.set_hitl_origin(esc.issue_number, esc.origin_label)
        self._state.set_hitl_cause(esc.issue_number, esc.cause)
        self._state.record_hitl_escalation()
        if esc.visual_evidence is not None:
            self._state.set_hitl_visual_evidence(esc.issue_number, esc.visual_evidence)

        if esc.task is not None:
            self._store.enqueue_transition(esc.task, "diagnose")
        await self._transitioner.transition(
            esc.issue_number, "diagnose", pr_number=esc.pr_number
        )

        if esc.post_on_pr and esc.pr_number and esc.pr_number > 0:
            await self._prs.post_pr_comment(esc.pr_number, esc.comment)
        else:
            await self._prs.post_comment(esc.issue_number, esc.comment)

        event_data: dict[str, object] = {
            "issue": esc.issue_number,
            "status": "diagnostic",
            "role": "reviewer",
            "cause": esc.event_cause or esc.cause,
        }
        if esc.pr_number and esc.pr_number > 0:
            event_data["pr"] = esc.pr_number
        if esc.visual_evidence is not None:
            event_data["visual_evidence"] = esc.visual_evidence.model_dump()
        if esc.extra_event_data:
            event_data.update(esc.extra_event_data)
        await self._bus.publish(
            HydraFlowEvent(type=EventType.HITL_ESCALATION, data=event_data)
        )

    async def escalate_visual_failure(
        self,
        issue_number: int,
        pr_number: int | None,
        evidence: VisualEvidence,
        *,
        task: Task | None = None,
    ) -> None:
        """Escalate a visual validation failure to HITL with evidence.

        Convenience wrapper around ``_escalate_to_hitl`` that records the
        visual evidence, picks the appropriate failure category, and
        builds a descriptive comment.
        """
        fail_items = [i for i in evidence.items if i.status == "fail"]
        warn_items = [i for i in evidence.items if i.status == "warn"]

        category = (
            FailureCategory.VISUAL_FAIL if fail_items else FailureCategory.VISUAL_WARN
        )
        record_harness_failure(
            self._harness_insights,
            issue_number,
            category,
            evidence.summary or f"{len(fail_items)} fail(s), {len(warn_items)} warn(s)",
            pr_number=pr_number or 0,
            stage=PipelineStage.REVIEW,
        )

        screen_lines = []
        for item in evidence.items:
            if item.status in ("fail", "warn"):
                label = "FAIL" if item.status == "fail" else "WARN"
                screen_lines.append(
                    f"- **{item.screen_name}** — {item.diff_percent:.1f}% diff [{label}]"
                )

        comment = (
            "## Visual Validation Failed\n\n"
            + (evidence.summary + "\n\n" if evidence.summary else "")
            + (
                "**Affected screens:**\n" + "\n".join(screen_lines) + "\n\n"
                if screen_lines
                else ""
            )
            + (f"[View run]({evidence.run_url})\n\n" if evidence.run_url else "")
            + "Escalating to human review."
        )

        cause = (
            f"Visual validation failed: {evidence.summary}"
            if evidence.summary
            else "Visual validation failed"
        )

        await self._escalate_to_hitl(
            HitlEscalation(
                issue_number=issue_number,
                pr_number=pr_number,
                cause=cause,
                origin_label=self._config.review_label[0],
                comment=comment,
                event_cause="visual_validation_failed",
                task=task,
                visual_evidence=evidence,
            )
        )

    @staticmethod
    def _count_review_findings(summary: str) -> int:
        """Count the number of findings in a review summary.

        Counts bullet points (``-`` or ``*``) and numbered items (``1.``)
        as individual findings.
        """
        lines = summary.strip().splitlines()
        count = 0
        for line in lines:
            stripped = line.strip()
            # Bullet points ("- text", "* text") or numbered items ("1. text")
            if re.match(r"^[-*]\s+\S", stripped) or re.match(r"^\d+\.\s+\S", stripped):
                count += 1
        return count

    async def _check_adversarial_threshold(
        self,
        pr: PRInfo,
        issue: Task,
        wt_path: Path,
        diff: str,
        result: ReviewResult,
        worker_id: int,
        code_scanning_alerts: list[CodeScanningAlert] | None = None,
    ) -> ReviewResult:
        """Re-review if APPROVE has too few findings and no justification.

        Returns the (possibly updated) review result.
        """
        min_findings = self._config.min_review_findings
        if min_findings <= 0:
            return result

        findings_count = self._count_review_findings(result.summary)
        has_justification = "THOROUGH_REVIEW_COMPLETE" in result.transcript

        if findings_count >= min_findings or has_justification:
            return result

        # Under threshold with no justification — re-review once
        logger.info(
            "PR #%d: APPROVE with only %d findings (min %d) and no "
            "THOROUGH_REVIEW_COMPLETE — re-reviewing",
            pr.number,
            findings_count,
            min_findings,
        )
        await self._publish_review_status(pr, worker_id, "re_reviewing")

        # Thread the pre-flight plan into retries so the executor keeps
        # the same focus rubric across the loop (T24.5 closed I3).
        re_result = await self._reviewers.review(
            pr,
            issue,
            wt_path,
            diff,
            worker_id=worker_id,
            code_scanning_alerts=code_scanning_alerts,
            pre_flight_plan=self._advisor_pre_flight_plan.get(pr.number),
        )

        # If re-review still under threshold without justification, accept
        # but log a warning (don't loop forever)
        re_count = self._count_review_findings(re_result.summary)
        re_justified = "THOROUGH_REVIEW_COMPLETE" in re_result.transcript
        if re_count < min_findings and not re_justified:
            logger.warning(
                "PR #%d: re-review still under threshold (%d/%d) "
                "with no justification — accepting anyway",
                pr.number,
                re_count,
                min_findings,
            )

        # If reviewer made fixes during re-review, push them
        if re_result.fixes_made:
            await self._prs.push_branch(wt_path, pr.branch)

        return re_result

    async def _handle_rejected_review(
        self,
        pr: PRInfo,
        task: Task,
        result: ReviewResult,
        worker_id: int,
    ) -> bool:
        """Handle REQUEST_CHANGES or COMMENT verdict with retry logic.

        Returns *True* if the worktree should be preserved (retry case),
        *False* if the worktree should be destroyed (HITL escalation).
        """
        max_attempts = self._config.max_review_fix_attempts
        attempts = self._state.get_review_attempts(pr.issue_number)

        if attempts < max_attempts:
            # Under cap: re-queue for implementation with feedback
            new_count = self._state.increment_review_attempts(pr.issue_number)
            self._state.set_review_feedback(pr.issue_number, result.summary)

            # Swap labels: review → ready (issue and PR)
            # Activate eager-transition protection before the label swap
            self._store.enqueue_transition(task, "ready")
            await self._transitioner.transition(
                pr.issue_number, "ready", pr_number=pr.number
            )

            await self._transitioner.post_comment(
                pr.issue_number,
                f"**Review requested changes** (attempt {new_count}/{max_attempts}). "
                f"Re-queuing for implementation with feedback.",
            )

            logger.info(
                "PR #%d: %s verdict — retry %d/%d, re-queuing issue #%d",
                pr.number,
                result.verdict.value,
                new_count,
                max_attempts,
                pr.issue_number,
            )
            return True  # Preserve worktree
        else:
            # Cap exceeded: escalate to HITL
            logger.warning(
                "PR #%d: review fix cap (%d) exceeded — escalating issue #%d to HITL",
                pr.number,
                max_attempts,
                pr.issue_number,
            )
            record_harness_failure(
                self._harness_insights,
                pr.issue_number,
                FailureCategory.HITL_ESCALATION,
                f"Review fix cap exceeded after {max_attempts} attempt(s)",
                stage=PipelineStage.REVIEW,
                pr_number=pr.number,
            )
            await self._publish_review_status(pr, worker_id, "escalating")
            # Pre-store richer context with agent transcript before routing to diagnostic loop
            from models import EscalationContext  # noqa: PLC0415

            cap_cause = f"Review fix cap exceeded after {max_attempts} attempt(s)"
            cap_context = EscalationContext(
                cause=cap_cause,
                origin_phase="review",
                pr_number=pr.number,
                agent_transcript=result.transcript if result.transcript else None,
            )
            self._state.set_escalation_context(pr.issue_number, cap_context)
            await self._escalate_to_hitl(
                HitlEscalation(
                    issue_number=pr.issue_number,
                    pr_number=pr.number,
                    cause=cap_cause,
                    origin_label=self._config.review_label[0],
                    comment=(
                        f"**Review fix cap exceeded** — {max_attempts} review fix "
                        f"attempt(s) exhausted. Escalating to human review."
                    ),
                    post_on_pr=False,
                    event_cause="review_fix_cap_exceeded",
                    task=task,
                )
            )
            if result.transcript:
                await self._suggest_memory(
                    result.transcript,
                    "review_fix_cap_exceeded",
                    f"PR #{pr.number}",
                )
            return False  # Destroy worktree

    # Delegate properties for backward compatibility in tests
    @property
    def _resolve_merge_conflicts(
        self,
    ) -> Callable[..., Coroutine[Any, Any, ConflictResolutionResult]]:
        """Backward-compatible access to conflict resolver."""
        return self._conflict_resolver.resolve_merge_conflicts

    @property
    def _get_judge_result(self) -> Callable[..., JudgeResult | None]:
        """Backward-compatible access to judge result helper."""
        return self._post_merge._get_judge_result

    @property
    def _run_post_merge_hooks(self) -> Callable[..., Coroutine[Any, Any, None]]:
        """Backward-compatible access to post-merge hooks."""
        return self._post_merge._run_post_merge_hooks

    @property
    def _save_conflict_transcript(self) -> Callable[..., None]:
        """Backward-compatible access to conflict transcript saving."""
        return self._conflict_resolver.save_conflict_transcript

    @property
    def _maybe_summarize_conflict(self) -> Callable[..., Coroutine[Any, Any, None]]:
        """Backward-compatible access to conflict summary."""
        return self._conflict_resolver._maybe_summarize_conflict
