"""Review insight aggregation — tracks recurring reviewer feedback patterns."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel

from dedup_store import DedupStore
from models import IsoTimestamp, ReviewVerdict

if TYPE_CHECKING:
    from dolt_backend import DoltBackend
    from hindsight import HindsightClient
    from hindsight_wal import HindsightWAL
    from ports import ReviewInsightStorePort  # noqa: TCH004

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
    raw_feedback: str = ""


class ProposalMetadata(BaseModel):
    """Metadata recorded when a [Review Insight] improvement proposal is filed."""

    pre_count: int
    """Pattern frequency at the time of filing."""
    proposed_at: IsoTimestamp
    """ISO 8601 UTC timestamp when the proposal was filed."""
    verified: bool = False
    """True if the pattern frequency decreased by >50% after the proposal."""


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

    def __init__(
        self,
        memory_dir: Path,
        *,
        hindsight: HindsightClient | None = None,
        dolt: DoltBackend | None = None,
        wal: HindsightWAL | None = None,
    ) -> None:
        self._memory_dir = memory_dir
        self._reviews_path = memory_dir / "reviews.jsonl"
        self._proposed = DedupStore(
            "proposed_categories",
            memory_dir / "proposed_categories.json",
            dolt=dolt,
        )
        self._hindsight = hindsight
        self._dolt = dolt
        self._wal = wal

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

        if self._hindsight is not None:
            from hindsight import Bank, schedule_retain  # noqa: PLC0415

            schedule_retain(
                self._hindsight,
                Bank.REVIEW_INSIGHTS,
                record.summary,
                context=f"PR #{record.pr_number} issue #{record.issue_number} verdict={record.verdict}",
                metadata={
                    "pr_number": record.pr_number,
                    "issue_number": record.issue_number,
                    "verdict": str(record.verdict),
                    "categories": record.categories,
                },
                wal=self._wal,
            )

        try:
            import sentry_sdk as _sentry

            _sentry.add_breadcrumb(
                category="review_insights.recorded",
                message=f"Review insight recorded for PR #{record.pr_number}",
                level="info",
                data={"pr_number": record.pr_number, "verdict": str(record.verdict)},
            )
        except ImportError:
            pass

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
        return self._proposed.get()

    def mark_category_proposed(self, category: str) -> None:
        """Record that an improvement proposal has been filed for *category*."""
        self._proposed.add(category)

    # --- Proposal metadata (pre_count + timestamps for verification) ---

    def _proposal_meta_path(self) -> Path:
        return self._memory_dir / "proposal_metadata.json"

    def load_proposal_metadata(self) -> dict[str, ProposalMetadata]:
        """Load per-category proposal metadata from ``proposal_metadata.json``.

        Returns an empty dict if the file does not exist or is unreadable.
        """
        path = self._proposal_meta_path()
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text())
            result: dict[str, ProposalMetadata] = {}
            for cat, entry in raw.items():
                try:
                    result[cat] = ProposalMetadata.model_validate(entry)
                except Exception:  # noqa: BLE001
                    logger.warning("Skipping malformed proposal metadata for %s", cat)
            return result
        except (json.JSONDecodeError, OSError):
            logger.warning(
                "Could not read proposal metadata from %s", path, exc_info=True
            )
            return {}

    def save_proposal_metadata(self, metadata: dict[str, ProposalMetadata]) -> None:
        """Persist proposal metadata to ``proposal_metadata.json``."""
        path = self._proposal_meta_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            raw = {cat: entry.model_dump() for cat, entry in metadata.items()}
            path.write_text(json.dumps(raw, indent=2))
        except OSError:
            logger.warning(
                "Could not write proposal metadata to %s", path, exc_info=True
            )

    def record_proposal(self, category: str, pre_count: int) -> None:
        """Record a new improvement proposal with its baseline pattern count.

        Stores ``pre_count`` and the current UTC timestamp in
        ``proposal_metadata.json``.
        """
        from datetime import UTC, datetime  # noqa: PLC0415

        meta = self.load_proposal_metadata()
        meta[category] = ProposalMetadata(
            pre_count=pre_count,
            proposed_at=datetime.now(UTC).isoformat(),
        )
        self.save_proposal_metadata(meta)

    def update_proposal_verified(self, category: str, *, verified: bool) -> None:
        """Mark a proposal as verified (or stale) in proposal_metadata.json."""
        meta = self.load_proposal_metadata()
        if category in meta:
            meta[category].verified = verified
            self.save_proposal_metadata(meta)


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

    results = [
        (cat, count, cat_records[cat])
        for cat, count in cat_counts.most_common()
        if count >= threshold
    ]

    for cat, count, _recs in results:
        try:
            import sentry_sdk as _sentry

            _sentry.add_breadcrumb(
                category="review_insights.pattern_detected",
                message=f"Review pattern detected: {cat} ({count} occurrences)",
                level="warning",
                data={"category": cat, "count": count},
            )
        except ImportError:
            pass

    return results


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


# ---------------------------------------------------------------------------
# Proposal verification
# ---------------------------------------------------------------------------

_PROPOSAL_STALE_DAYS = 30
_PROPOSAL_IMPROVEMENT_THRESHOLD = 0.5  # >50% reduction marks as verified


def verify_proposals(
    store: ReviewInsightStore | ReviewInsightStorePort,
    records: list[ReviewRecord],
) -> list[str]:
    """Check filed improvement proposals and classify outcomes.

    For each category that has metadata stored in ``proposal_metadata.json``:

    - If the current pattern count decreased by >50% vs ``pre_count``,
      mark the proposal as ``verified: true``.
    - If the pattern count is unchanged (same or higher) and the proposal
      is older than 30 days, return the category in the stale list so the
      caller can re-file a HITL issue for human escalation.

    Returns a list of category names that are stale and need HITL escalation.
    Never raises — all errors are logged and swallowed.
    """
    from datetime import UTC, datetime, timedelta  # noqa: PLC0415

    stale_categories: list[str] = []
    try:
        meta = store.load_proposal_metadata()
        if not meta:
            return []

        # Count current pattern frequencies across all records
        from collections import Counter  # noqa: PLC0415

        non_approve = [r for r in records if r.verdict != ReviewVerdict.APPROVE]
        cat_counts: Counter[str] = Counter()
        for record in non_approve:
            for cat in record.categories:
                cat_counts[cat] += 1

        now = datetime.now(UTC)

        for category, proposal in meta.items():
            if proposal.verified:
                continue  # Already resolved

            try:
                proposed_at = datetime.fromisoformat(proposal.proposed_at)
                # Ensure timezone-aware comparison
                if proposed_at.tzinfo is None:
                    proposed_at = proposed_at.replace(tzinfo=UTC)
            except ValueError:
                logger.warning(
                    "Could not parse proposed_at for category %s: %s",
                    category,
                    proposal.proposed_at,
                )
                continue

            current_count = cat_counts.get(category, 0)

            # Check improvement: >50% reduction in frequency
            if (
                proposal.pre_count > 0
                and current_count < proposal.pre_count * _PROPOSAL_IMPROVEMENT_THRESHOLD
            ):
                store.update_proposal_verified(category, verified=True)
                logger.info(
                    "Proposal for category '%s' verified: count dropped from %d to %d",
                    category,
                    proposal.pre_count,
                    current_count,
                )
                continue

            # Check staleness: unchanged after 30 days
            age = now - proposed_at
            if (
                age >= timedelta(days=_PROPOSAL_STALE_DAYS)
                and current_count >= proposal.pre_count
            ):
                stale_categories.append(category)
                logger.warning(
                    "Proposal for category '%s' is stale after %d days (count: %d -> %d)",
                    category,
                    age.days,
                    proposal.pre_count,
                    current_count,
                )

    except Exception:
        logger.exception("Error during proposal verification")

    return stale_categories
