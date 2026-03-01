"""Harness insight aggregation — tracks failure patterns across all pipeline stages.

Categorizes failures from planner, quality gates, review rejections, CI, and HITL
escalations, detects recurring patterns, and generates improvement suggestions.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from models import IsoTimestamp, PipelineStage

if TYPE_CHECKING:
    from pr_manager import PRManager
    from state import StateTracker

logger = logging.getLogger("hydraflow.harness_insights")

# ---------------------------------------------------------------------------
# Failure categories
# ---------------------------------------------------------------------------


class FailureCategory(StrEnum):
    """Pipeline stage failure categories."""

    PLAN_VALIDATION = "plan_validation"
    QUALITY_GATE = "quality_gate"
    REVIEW_REJECTION = "review_rejection"
    CI_FAILURE = "ci_failure"
    HITL_ESCALATION = "hitl_escalation"
    IMPLEMENTATION_ERROR = "implementation_error"
    VISUAL_FAIL = "visual_fail"
    VISUAL_WARN = "visual_warn"


CATEGORY_DESCRIPTIONS: dict[str, str] = {
    FailureCategory.PLAN_VALIDATION: "Plan validation failed after retry",
    FailureCategory.QUALITY_GATE: "Quality gate failure during implementation",
    FailureCategory.REVIEW_REJECTION: "PR rejected by reviewer",
    FailureCategory.CI_FAILURE: "CI pipeline failure after fix attempts",
    FailureCategory.HITL_ESCALATION: "Escalated to human-in-the-loop",
    FailureCategory.IMPLEMENTATION_ERROR: "Implementation agent error or exception",
    FailureCategory.VISUAL_FAIL: "Visual validation failed — screenshot diff exceeded threshold",
    FailureCategory.VISUAL_WARN: "Visual validation warning — minor screenshot differences detected",
}

# Keyword mapping for subcategory extraction from failure details
SUBCATEGORY_KEYWORDS: dict[str, list[str]] = {
    "lint_error": ["ruff", "lint", "format", "style"],
    "type_error": ["pyright", "type", "mypy", "annotation"],
    "test_failure": ["test", "pytest", "assert", "coverage"],
    "import_error": ["import", "module not found", "no module"],
    "syntax_error": ["syntax", "parse error", "unexpected token"],
    "merge_conflict": ["merge conflict", "conflict", "CONFLICT"],
    "timeout": ["timeout", "timed out", "exceeded"],
    "missing_tests": ["missing test", "no test", "untested"],
    "naming": ["naming", "convention", "rename"],
    "error_handling": ["error handling", "exception", "try/except"],
    "visual_diff": ["screenshot", "visual diff", "pixel diff", "diff image"],
    "visual_regression": [
        "visual regression",
        "baseline mismatch",
        "screenshot mismatch",
    ],
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


class FailureRecord(BaseModel):
    """A structured record of a single pipeline failure."""

    issue_number: int
    pr_number: int = 0
    timestamp: IsoTimestamp = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
    )
    category: FailureCategory
    subcategories: list[str] = Field(default_factory=list)
    details: str = ""
    stage: PipelineStage | Literal[""] = ""


class ImprovementSuggestion(BaseModel):
    """An auto-generated improvement suggestion based on recurring patterns."""

    category: str = Field(
        description="Primary failure category this suggestion addresses"
    )
    subcategory: str = Field(
        default="", description="Specific sub-pattern (e.g. lint_error)"
    )
    occurrence_count: int = Field(
        description="Number of times this pattern was detected"
    )
    window_size: int = Field(description="Total records in the analysis window")
    description: str = Field(description="Human-readable description of the pattern")
    suggestion: str = Field(description="Suggested improvement action")
    evidence: list[FailureRecord] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Subcategory extraction
# ---------------------------------------------------------------------------


def extract_subcategories(details: str) -> list[str]:
    """Extract subcategories from failure details using keyword matching."""
    if not details:
        return []
    lower = details.lower()
    return [
        sub
        for sub, keywords in SUBCATEGORY_KEYWORDS.items()
        if any(kw.lower() in lower for kw in keywords)
    ]


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


class HarnessInsightStore:
    """File-backed store for pipeline failure records and proposed-pattern tracking."""

    def __init__(self, memory_dir: Path) -> None:
        self._memory_dir = memory_dir
        self._failures_path = memory_dir / "harness_failures.jsonl"
        self._proposed_path = memory_dir / "harness_proposed.json"

    def append_failure(self, record: FailureRecord) -> None:
        """Append *record* as a JSON line to ``harness_failures.jsonl``."""
        try:
            self._memory_dir.mkdir(parents=True, exist_ok=True)
            with self._failures_path.open("a") as f:
                f.write(record.model_dump_json() + "\n")
        except OSError:
            logger.warning(
                "Could not append failure to %s",
                self._failures_path,
                exc_info=True,
            )

    def load_recent(self, n: int = 20) -> list[FailureRecord]:
        """Load the last *n* failure records from disk."""
        if not self._failures_path.exists():
            return []
        try:
            lines = self._failures_path.read_text().strip().splitlines()
        except OSError:
            return []
        tail = lines[-n:] if len(lines) > n else lines
        records: list[FailureRecord] = []
        for line in tail:
            try:
                records.append(FailureRecord.model_validate_json(line))
            except Exception:  # noqa: BLE001
                logger.warning("Skipping malformed harness record: %s", line[:80])
        return records

    def get_proposed_patterns(self) -> set[str]:
        """Return the set of pattern keys that already have filed proposals."""
        if not self._proposed_path.exists():
            return set()
        try:
            data = json.loads(self._proposed_path.read_text())
            return set(data) if isinstance(data, list) else set()
        except (json.JSONDecodeError, TypeError, OSError):
            return set()

    def mark_pattern_proposed(self, key: str) -> None:
        """Record that an improvement proposal has been filed for *key*."""
        proposed = self.get_proposed_patterns()
        proposed.add(key)
        self._memory_dir.mkdir(parents=True, exist_ok=True)
        self._proposed_path.write_text(json.dumps(sorted(proposed)))


# ---------------------------------------------------------------------------
# Pattern analysis
# ---------------------------------------------------------------------------


def analyze_category_patterns(
    records: list[FailureRecord],
    threshold: int = 3,
) -> list[tuple[str, int, list[FailureRecord]]]:
    """Identify recurring failure categories above *threshold*.

    Returns a list of ``(category, count, matching_records)`` tuples
    sorted by frequency (descending).
    """
    if not records:
        return []

    cat_counts: Counter[str] = Counter()
    cat_records: dict[str, list[FailureRecord]] = {}
    for record in records:
        cat_counts[record.category] += 1
        cat_records.setdefault(record.category, []).append(record)

    return [
        (cat, count, cat_records[cat])
        for cat, count in cat_counts.most_common()
        if count >= threshold
    ]


def analyze_subcategory_patterns(
    records: list[FailureRecord],
    threshold: int = 3,
) -> list[tuple[str, int, list[FailureRecord]]]:
    """Identify recurring subcategories above *threshold*.

    Returns a list of ``(subcategory, count, matching_records)`` tuples
    sorted by frequency (descending).
    """
    if not records:
        return []

    sub_counts: Counter[str] = Counter()
    sub_records: dict[str, list[FailureRecord]] = {}
    for record in records:
        for sub in record.subcategories:
            sub_counts[sub] += 1
            sub_records.setdefault(sub, []).append(record)

    return [
        (sub, count, sub_records[sub])
        for sub, count in sub_counts.most_common()
        if count >= threshold
    ]


# ---------------------------------------------------------------------------
# Issue body builder
# ---------------------------------------------------------------------------


def build_harness_issue_body(
    category: str,
    count: int,
    total: int,
    evidence: list[FailureRecord],
    *,
    subcategory: str = "",
) -> str:
    """Build the markdown body for a harness improvement proposal issue."""
    desc = CATEGORY_DESCRIPTIONS.get(category, category)
    label = f"{desc} — subcategory: {subcategory}" if subcategory else desc

    lines = [
        f"## Harness Insight: {label}",
        "",
        f"The failure pattern **{category}**"
        + (f" (subcategory: **{subcategory}**)" if subcategory else "")
        + f" occurred **{count} times** in the last {total} pipeline failures.",
        "",
        "### Evidence",
        "",
    ]
    for rec in evidence[:10]:  # Cap evidence to 10 entries
        issue_ref = f"issue #{rec.issue_number}"
        pr_ref = f", PR #{rec.pr_number}" if rec.pr_number else ""
        detail_preview = rec.details[:120] if rec.details else "no details"
        lines.append(f"- {issue_ref}{pr_ref}: {detail_preview}")

    suggestion = _generate_suggestion(category, subcategory, count)
    lines.extend(
        [
            "",
            "### Suggested Improvement",
            "",
            suggestion,
            "",
            "---",
            "*Auto-generated by HydraFlow harness insight analysis.*",
        ]
    )
    return "\n".join(lines)


def _generate_suggestion(category: str, subcategory: str, count: int) -> str:
    """Generate a context-aware improvement suggestion."""
    suggestions: dict[str, str] = {
        FailureCategory.PLAN_VALIDATION: (
            "Strengthen the planner prompt to produce more structured plans. "
            "Consider adding explicit section requirements or examples."
        ),
        FailureCategory.QUALITY_GATE: (
            "Add pre-implementation quality checks to the agent prompt. "
            "Emphasize running `make quality` before finishing."
        ),
        FailureCategory.REVIEW_REJECTION: (
            "Improve the implementation prompt to address common reviewer "
            "feedback patterns. Consider injecting recent rejection reasons."
        ),
        FailureCategory.CI_FAILURE: (
            "Add CI awareness to the implementation prompt. "
            "Consider running CI checks locally before pushing."
        ),
        FailureCategory.HITL_ESCALATION: (
            "Review the escalation triggers and consider adding more "
            "automated recovery paths before human intervention."
        ),
        FailureCategory.IMPLEMENTATION_ERROR: (
            "Review agent error patterns and consider adding guardrails "
            "or retry logic for the most common failure modes."
        ),
        FailureCategory.VISUAL_FAIL: (
            "Add visual regression baseline management to the pipeline. "
            "Review screenshot diff thresholds and update baselines after intentional UI changes."
        ),
        FailureCategory.VISUAL_WARN: (
            "Minor visual differences detected repeatedly — consider tightening diff thresholds "
            "or updating baselines to prevent warning escalation."
        ),
    }
    base = suggestions.get(category, f"Review recurring {category} failures.")

    sub_hints: dict[str, str] = {
        "lint_error": " Add a lint pre-check step or add the lint rule to CLAUDE.md.",
        "type_error": " Add type-checking guidance to the implementation prompt.",
        "test_failure": " Strengthen TDD requirements in the implementation prompt.",
        "import_error": " Improve dependency resolution guidance in the planner.",
        "merge_conflict": " Consider more frequent main-branch merges during implementation.",
        "visual_diff": " Update visual baselines after intentional UI changes to reduce false positives.",
        "visual_regression": " Add visual regression gates earlier in the review pipeline.",
    }
    hint = sub_hints.get(subcategory, "")

    return f"{base}{hint} (Detected {count} occurrences.)"


# ---------------------------------------------------------------------------
# Improvement suggestion generation
# ---------------------------------------------------------------------------


def generate_suggestions(
    records: list[FailureRecord],
    threshold: int = 3,
    proposed: set[str] | None = None,
) -> list[ImprovementSuggestion]:
    """Analyze records and generate improvement suggestions for unproposed patterns.

    Returns a list of :class:`ImprovementSuggestion` for patterns that
    meet the threshold and have not been previously proposed.
    """
    if proposed is None:
        proposed = set()

    suggestions: list[ImprovementSuggestion] = []
    total = len(records)

    # Check category-level patterns
    for cat, count, evidence in analyze_category_patterns(records, threshold):
        key = f"category:{cat}"
        if key in proposed:
            continue
        desc = CATEGORY_DESCRIPTIONS.get(cat, cat)
        suggestion_text = _generate_suggestion(cat, "", count)
        suggestions.append(
            ImprovementSuggestion(
                category=cat,
                occurrence_count=count,
                window_size=total,
                description=desc,
                suggestion=suggestion_text,
                evidence=evidence,
            )
        )

    # Check subcategory-level patterns
    for sub, count, evidence in analyze_subcategory_patterns(records, threshold):
        # Use the most common category for this subcategory
        cat_counter: Counter[str] = Counter(r.category for r in evidence)
        primary_cat = cat_counter.most_common(1)[0][0]
        key = f"subcategory:{sub}"
        if key in proposed:
            continue
        suggestion_text = _generate_suggestion(primary_cat, sub, count)
        suggestions.append(
            ImprovementSuggestion(
                category=primary_cat,
                subcategory=sub,
                occurrence_count=count,
                window_size=total,
                description=f"Recurring {sub} failures",
                suggestion=suggestion_text,
                evidence=evidence,
            )
        )

    # Sort by occurrence count (highest first)
    suggestions.sort(key=lambda s: s.occurrence_count, reverse=True)
    return suggestions


# ---------------------------------------------------------------------------
# Issue filing
# ---------------------------------------------------------------------------


async def file_harness_suggestions(
    suggestions: list[ImprovementSuggestion],
    store: HarnessInsightStore,
    prs: PRManager,
    state: StateTracker,
    improve_label: list[str],
    hitl_label: list[str],
    memory_label: list[str] | None = None,
    *,
    max_per_cycle: int = 1,
) -> int:
    """File improvement issues for suggestions, returning the number filed.

    Caps filing at *max_per_cycle* issues per invocation to avoid spam.
    Marks each filed suggestion as proposed in the store.
    """
    filed = 0
    for suggestion in suggestions:
        if filed >= max_per_cycle:
            break

        key = (
            f"subcategory:{suggestion.subcategory}"
            if suggestion.subcategory
            else f"category:{suggestion.category}"
        )

        desc = suggestion.description
        title = f"[Harness Insight] Recurring pattern: {desc}"
        body = build_harness_issue_body(
            suggestion.category,
            suggestion.occurrence_count,
            suggestion.window_size,
            suggestion.evidence,
            subcategory=suggestion.subcategory,
        )
        use_memory_flow = bool(memory_label)
        labels = (
            improve_label[:1] + memory_label[:1]
            if use_memory_flow
            else improve_label[:1] + hitl_label[:1]
        )
        issue_title = f"[Memory] {title}" if use_memory_flow else title
        issue_num = await prs.create_issue(issue_title, body, labels)
        if issue_num:
            if improve_label and not use_memory_flow:
                state.set_hitl_origin(issue_num, improve_label[0])
            if not use_memory_flow:
                state.set_hitl_cause(issue_num, f"Harness pattern detected: {desc}")
            store.mark_pattern_proposed(key)
            filed += 1

    return filed
