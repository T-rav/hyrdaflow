"""Review insight aggregation — tracks recurring reviewer feedback patterns."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import BaseModel

from models import IsoTimestamp, ReviewVerdict

logger = logging.getLogger("hydraflow.review_insights")

# ---------------------------------------------------------------------------
# Category keyword mapping
# ---------------------------------------------------------------------------

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "missing_tests": ["test", "coverage", "untested", "no tests"],
    "type_annotations": ["type", "annotation", "typing", "hint"],
    "security": ["security", "injection", "secret", "vulnerability"],
    "naming": ["naming", "name", "rename", "convention"],
    "edge_cases": ["edge case", "boundary", "empty", "null", "none"],
    "error_handling": ["error handling", "exception", "try/except"],
    "code_quality": ["complexity", "refactor", "SRP", "duplication"],
    "lint_format": ["lint", "format", "ruff", "style"],
}

CATEGORY_ESCALATIONS: dict[str, dict[str, str | list[str]]] = {
    "missing_tests": {
        "mandatory_block": (
            "## Mandatory Requirements: Test Coverage\n\n"
            "Recurring review feedback has flagged **missing or insufficient test coverage**. "
            "The following rules are **mandatory** — do not skip them:\n\n"
            "- Every new public function MUST have at least one unit test.\n"
            "- Every bug fix MUST include a regression test that reproduces the bug.\n"
            "- Tests must cover the issue's requirements, not just helper functions.\n"
            "- Failure paths need explicit tests (invalid input, error conditions).\n"
            "- Coverage for changed files must not decrease.\n"
        ),
        "checklist_items": [
            "- [ ] Every new/modified public function has a dedicated test",
            "- [ ] Branch coverage for changed files >= 80%",
            "- [ ] Edge cases (None, empty, boundary) are tested",
            "- [ ] Failure paths have explicit tests (invalid input, errors)",
            "- [ ] Tests cover issue requirements, not just helpers",
        ],
        "pre_quality_guidance": (
            "Recurring feedback: missing test coverage. "
            "Verify every new public function has a unit test. "
            "Check that failure paths are tested. "
            "Ensure tests cover the issue's actual requirements, not just utilities."
        ),
    },
    "error_handling": {
        "mandatory_block": (
            "## Mandatory Requirements: Error Handling\n\n"
            "Recurring review feedback has flagged **inadequate error handling**. "
            "The following rules are **mandatory**:\n\n"
            "- Every external call (API, file I/O, subprocess) MUST have error handling.\n"
            "- Exceptions MUST include context (what failed, what was expected).\n"
            "- Never silently swallow exceptions without logging.\n"
        ),
        "checklist_items": [
            "- [ ] Every external call has appropriate error handling",
            "- [ ] Exceptions include context about what failed",
            "- [ ] No bare except clauses without logging",
        ],
        "pre_quality_guidance": (
            "Recurring feedback: inadequate error handling. "
            "Verify all external calls have error handling. "
            "Check that exceptions include useful context messages."
        ),
    },
    "security": {
        "mandatory_block": (
            "## Mandatory Requirements: Security\n\n"
            "Recurring review feedback has flagged **security vulnerabilities**. "
            "The following rules are **mandatory**:\n\n"
            "- Never interpolate user input directly into commands or queries.\n"
            "- Validate and sanitize all external inputs.\n"
            "- Never log secrets, tokens, or credentials.\n"
        ),
        "checklist_items": [
            "- [ ] No user input interpolated into commands or queries",
            "- [ ] External inputs are validated and sanitized",
            "- [ ] No secrets or tokens in logs or error messages",
        ],
        "pre_quality_guidance": (
            "Recurring feedback: security vulnerabilities. "
            "Verify no user input is interpolated into commands. "
            "Check that external inputs are validated."
        ),
    },
    "type_annotations": {
        "mandatory_block": (
            "## Mandatory Requirements: Type Annotations\n\n"
            "Recurring review feedback has flagged **missing type annotations**. "
            "The following rules are **mandatory**:\n\n"
            "- Every new public function MUST have full type annotations.\n"
            "- Avoid `Any` where a concrete type exists.\n"
            "- Return types must be explicit, not inferred.\n"
        ),
        "checklist_items": [
            "- [ ] Every new/modified public function has type annotations",
            "- [ ] No unnecessary `Any` types — use concrete types",
            "- [ ] Return types are explicit on all public functions",
        ],
        "pre_quality_guidance": (
            "Recurring feedback: missing type annotations. "
            "Verify all new public functions have full type hints. "
            "Check that return types are explicit."
        ),
    },
}

CATEGORY_DESCRIPTIONS: dict[str, str] = {
    "missing_tests": "Missing or insufficient test coverage",
    "type_annotations": "Missing type annotations on public functions",
    "security": "Security vulnerabilities or unsafe patterns",
    "naming": "Poor naming conventions or unclear identifiers",
    "edge_cases": "Missing edge case handling (empty inputs, None, boundaries)",
    "error_handling": "Inadequate error handling or exception management",
    "code_quality": "Code complexity, duplication, or SRP violations",
    "lint_format": "Linting or formatting issues",
}

# Actionable remediation hints injected when a category appears in feedback.
# Each hint gives the implementation agent specific guidance on what to fix.
CATEGORY_REMEDIATION: dict[str, str] = {
    "missing_tests": (
        "Ensure tests cover: (a) the specific issue requirements, not just helpers; "
        "(b) failure/error paths, not only happy paths; "
        "(c) that new functions are actually called in production code (no dead code)"
    ),
    "edge_cases": (
        "Add tests for empty inputs, None values, zero-length collections, "
        "and boundary conditions for every new code path"
    ),
    "error_handling": (
        "Add explicit error-path tests: verify exceptions are raised with "
        "correct messages and that callers handle failures gracefully"
    ),
}

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


class ReviewRecord(BaseModel):
    """A structured record of a single review outcome."""

    pr_number: int
    issue_number: int
    timestamp: IsoTimestamp
    verdict: ReviewVerdict
    summary: str
    fixes_made: bool
    categories: list[str]


# ---------------------------------------------------------------------------
# Category extraction
# ---------------------------------------------------------------------------


def extract_categories(summary: str) -> list[str]:
    """Extract feedback categories from a review summary using keyword matching.

    Scans *summary* (case-insensitive) against :data:`CATEGORY_KEYWORDS`
    and returns all matching category keys.
    """
    lower = summary.lower()
    return [
        cat
        for cat, keywords in CATEGORY_KEYWORDS.items()
        if any(kw.lower() in lower for kw in keywords)
    ]


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


class ReviewInsightStore:
    """File-backed store for review records and proposed-category tracking."""

    def __init__(self, memory_dir: Path) -> None:
        self._memory_dir = memory_dir
        self._reviews_path = memory_dir / "reviews.jsonl"
        self._proposed_path = memory_dir / "proposed_categories.json"

    def append_review(self, record: ReviewRecord) -> None:
        """Append *record* as a JSON line to ``reviews.jsonl``."""
        try:
            from file_util import append_jsonl  # noqa: PLC0415

            append_jsonl(self._reviews_path, record.model_dump_json())
        except OSError:
            logger.warning(
                "Could not append review to %s",
                self._reviews_path,
                exc_info=True,
            )

    def load_recent(self, n: int = 10) -> list[ReviewRecord]:
        """Load the last *n* review records from disk."""
        if not self._reviews_path.exists():
            return []
        lines = self._reviews_path.read_text().strip().splitlines()
        tail = lines[-n:] if len(lines) > n else lines
        records: list[ReviewRecord] = []
        for line in tail:
            try:
                records.append(ReviewRecord.model_validate_json(line))
            except Exception:  # noqa: BLE001
                logger.warning("Skipping malformed review record: %s", line[:80])
        return records

    def get_proposed_categories(self) -> set[str]:
        """Return the set of categories that already have filed proposals."""
        if not self._proposed_path.exists():
            return set()
        try:
            data = json.loads(self._proposed_path.read_text())
            return set(data)
        except (json.JSONDecodeError, TypeError):
            return set()

    def mark_category_proposed(self, category: str) -> None:
        """Record that an improvement proposal has been filed for *category*."""
        proposed = self.get_proposed_categories()
        proposed.add(category)
        self._memory_dir.mkdir(parents=True, exist_ok=True)
        self._proposed_path.write_text(json.dumps(sorted(proposed)))


# ---------------------------------------------------------------------------
# Pattern analysis
# ---------------------------------------------------------------------------


def analyze_patterns(
    records: list[ReviewRecord],
    threshold: int = 3,
) -> list[tuple[str, int, list[ReviewRecord]]]:
    """Identify recurring feedback categories above *threshold*.

    Only non-APPROVE reviews are considered. Returns a list of
    ``(category, count, matching_records)`` tuples sorted by frequency
    (descending).
    """
    non_approve = [r for r in records if r.verdict != ReviewVerdict.APPROVE]
    if not non_approve:
        return []

    from collections import Counter

    cat_counts: Counter[str] = Counter()
    cat_records: dict[str, list[ReviewRecord]] = {}
    for record in non_approve:
        for cat in record.categories:
            cat_counts[cat] += 1
            cat_records.setdefault(cat, []).append(record)

    return [
        (cat, count, cat_records[cat])
        for cat, count in cat_counts.most_common()
        if count >= threshold
    ]


# ---------------------------------------------------------------------------
# Issue body builder
# ---------------------------------------------------------------------------


def build_insight_issue_body(
    category: str,
    count: int,
    total: int,
    evidence: list[ReviewRecord],
) -> str:
    """Build the markdown body for a review improvement proposal issue."""
    desc = CATEGORY_DESCRIPTIONS.get(category, category)
    lines = [
        f"## Review Insight: {desc}",
        "",
        f"The category **{category}** appeared in **{count} of the last "
        f"{total}** non-APPROVE reviews.",
        "",
        "### Evidence",
        "",
    ]
    for rec in evidence:
        lines.append(
            f"- PR #{rec.pr_number} (issue #{rec.issue_number}): {rec.summary}"
        )

    lines.extend(
        [
            "",
            "### Suggested Prompt Improvement",
            "",
            f"Add to the implementation prompt: Pay special attention to "
            f"**{desc.lower()}**. "
            f"This has been flagged in {count} recent reviews.",
            "",
            "---",
            "*Auto-generated by HydraFlow review insight aggregation.*",
        ]
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Prompt injection
# ---------------------------------------------------------------------------


def get_common_feedback_section(
    records: list[ReviewRecord],
    top_n: int = 3,
) -> str:
    """Build a ``## Common Review Feedback`` section for the implementation prompt.

    Analyzes recent non-APPROVE reviews and returns a markdown section
    listing the most frequent feedback categories. Returns an empty string
    if no patterns are found.
    """
    non_approve = [r for r in records if r.verdict != ReviewVerdict.APPROVE]
    if not non_approve:
        return ""

    from collections import Counter

    cat_counts: Counter[str] = Counter()
    for record in non_approve:
        for cat in record.categories:
            cat_counts[cat] += 1

    if not cat_counts:
        return ""

    total = len(non_approve)
    top = cat_counts.most_common(top_n)

    lines = [
        "\n## Common Review Feedback",
        "Recent reviews have frequently flagged these issues. "
        "Pay special attention to:",
    ]
    for cat, count in top:
        desc = CATEGORY_DESCRIPTIONS.get(cat, cat)
        hint = CATEGORY_REMEDIATION.get(cat, "")
        line = f"- {desc} (flagged in {count} of last {total} reviews)"
        if hint:
            line += f"\n  Action: {hint}"
        lines.append(line)

    return "\n".join(lines)


def get_escalation_data(
    records: list[ReviewRecord],
    top_n: int = 3,
    threshold: int = 3,
) -> list[dict[str, str | int | list[str]]]:
    """Return structured escalation data for recurring feedback categories.

    Analyzes recent non-APPROVE reviews and returns escalation fragments
    for categories that appear at least *threshold* times and have an entry
    in :data:`CATEGORY_ESCALATIONS`. Each dict contains:
    ``category``, ``count``, ``mandatory_block``, ``checklist_items``,
    and ``pre_quality_guidance``.
    """
    non_approve = [r for r in records if r.verdict != ReviewVerdict.APPROVE]
    if not non_approve:
        return []

    from collections import Counter

    cat_counts: Counter[str] = Counter()
    for record in non_approve:
        for cat in record.categories:
            cat_counts[cat] += 1

    if not cat_counts:
        return []

    results: list[dict[str, str | int | list[str]]] = []
    for cat, count in cat_counts.most_common(top_n):
        if count < threshold:
            break
        if cat not in CATEGORY_ESCALATIONS:
            continue
        esc = CATEGORY_ESCALATIONS[cat]
        results.append(
            {
                "category": cat,
                "count": count,
                "mandatory_block": esc["mandatory_block"],
                "checklist_items": esc["checklist_items"],
                "pre_quality_guidance": esc["pre_quality_guidance"],
            }
        )

    return results
