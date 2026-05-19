"""Module-level helpers, constants, and dataclasses for the review_phase package.

Split out of the original ``src/review_phase.py`` (T36) so the main
``ReviewPhase`` class file is smaller. Everything here is re-exported from
``review_phase/__init__.py`` for back-compat — external callers continue
to do ``from review_phase import X``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from opentelemetry import metrics

from models import (
    CodeScanningAlert,
    ReviewResult,
    ReviewVerdict,
    Task,
    VisualValidationDecision,
)
from repo_wiki import RepoWikiStore

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
