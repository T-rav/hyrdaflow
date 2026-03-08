"""Post-merge retrospective analysis for the HydraFlow orchestrator."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from events import EventBus, EventType, HydraFlowEvent
from models import IsoTimestamp, PlanAccuracyResult, ReviewVerdict

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from models import ReviewResult
    from pr_manager import PRManager
    from state import StateTracker

logger = logging.getLogger("hydraflow.retrospective")


class RetrospectiveEntry(BaseModel):
    """A single retrospective record appended to the JSONL log."""

    issue_number: int
    pr_number: int
    timestamp: IsoTimestamp
    plan_accuracy_pct: float = 0.0
    planned_files: list[str] = Field(default_factory=list)
    actual_files: list[str] = Field(default_factory=list)
    unplanned_files: list[str] = Field(default_factory=list)
    missed_files: list[str] = Field(default_factory=list)
    quality_fix_rounds: int = 0
    review_verdict: ReviewVerdict | Literal[""] = ""
    reviewer_fixes_made: bool = False
    ci_fix_rounds: int = 0
    duration_seconds: float = 0.0


def get_retro_feedback_section(
    entries: list[RetrospectiveEntry],
) -> str:
    """Build a ``## Retrospective Insights`` section for agent prompts.

    Analyzes recent retrospective entries and returns a markdown section
    with actionable guidance based on detected patterns. Returns an empty
    string if no meaningful patterns are found.
    """
    if len(entries) < 3:
        return ""

    lines: list[str] = [
        "\n## Retrospective Insights",
        f"Analysis of {len(entries)} recent completed issues:",
    ]
    has_content = False

    # Pattern: high quality-fix rate
    quality_fix_count = sum(1 for e in entries if (e.quality_fix_rounds or 0) > 0)
    if quality_fix_count > len(entries) * 0.3:
        pct = round(quality_fix_count / len(entries) * 100)
        lines.append(
            f"- **{pct}% of issues needed quality fixes.** "
            "Run `make quality-lite` before committing. "
            "Check lint, type hints, and test coverage proactively."
        )
        has_content = True

    # Pattern: low plan accuracy
    accuracies = [e.plan_accuracy_pct for e in entries if e.plan_accuracy_pct is not None]
    if accuracies:
        avg_accuracy = sum(accuracies) / len(accuracies)
        if avg_accuracy < 70:
            lines.append(
                f"- **Average plan accuracy is {avg_accuracy:.0f}%.** "
                "Plans frequently miss files or include unplanned changes. "
                "Carefully review the plan and identify all affected files before coding."
            )
            has_content = True

    # Pattern: high CI fix rounds
    ci_rounds = [e.ci_fix_rounds for e in entries if e.ci_fix_rounds > 0]
    if len(ci_rounds) > len(entries) * 0.3:
        avg_rounds = sum(ci_rounds) / len(ci_rounds)
        lines.append(
            f"- **{len(ci_rounds)}/{len(entries)} issues needed CI fixes** "
            f"(avg {avg_rounds:.1f} rounds). "
            "Run tests locally before pushing. Check for missing imports and type errors."
        )
        has_content = True

    # Pattern: reviewer frequently makes fixes
    reviewer_fix_count = sum(1 for e in entries if e.reviewer_fixes_made)
    if reviewer_fix_count > len(entries) * 0.3:
        pct = round(reviewer_fix_count / len(entries) * 100)
        lines.append(
            f"- **Reviewer had to fix code in {pct}% of issues.** "
            "Self-review your changes before submitting. "
            "Check for edge cases, error handling, and test coverage."
        )
        has_content = True

    # Pattern: missed files in plan
    missed_counts = [len(e.missed_files) for e in entries if e.missed_files]
    if len(missed_counts) > len(entries) * 0.3:
        lines.append(
            f"- **{len(missed_counts)}/{len(entries)} issues had files the plan missed.** "
            "Trace all call sites and dependencies when identifying files to change."
        )
        has_content = True

    if not has_content:
        return ""

    return "\n".join(lines)


def load_retro_feedback_section(state: Any) -> str:
    """Load recent retrospectives from *state* and build a feedback section.

    Shared helper used by AgentRunner and PlannerRunner to avoid
    duplicating the load → validate → format pipeline.
    Returns an empty string on any error or missing data.
    """
    try:
        if not state or not hasattr(state, "load_recent_retrospectives"):
            return ""
        rows = state.load_recent_retrospectives(20)
        entries = []
        for row in rows:
            try:
                entries.append(RetrospectiveEntry.model_validate(row))
            except Exception:  # noqa: BLE001
                continue
        return get_retro_feedback_section(entries)
    except Exception:  # noqa: BLE001
        return ""


class RetrospectiveCollector:
    """Collects post-merge retrospective data and detects patterns."""

    def __init__(
        self,
        config: HydraFlowConfig,
        state: StateTracker,
        prs: PRManager,
        bus: EventBus | None = None,
    ) -> None:
        self._config = config
        self._state = state
        self._prs = prs
        self._bus = bus or EventBus()

    async def record(
        self,
        issue_number: int,
        pr_number: int,
        review_result: ReviewResult,
    ) -> None:
        """Run the full retrospective: collect, store, detect patterns.

        This method is designed to be non-blocking — exceptions are
        caught and logged so they never interrupt the merge flow.
        """
        try:
            entry = await self._collect(issue_number, pr_number, review_result)
            self._append_entry(entry)

            await self._bus.publish(HydraFlowEvent(
                type=EventType.RETROSPECTIVE_RECORDED,
                data=entry.model_dump(),
            ))
            try:
                self._state.db.commit(f"retro: issue #{issue_number}")
            except Exception:
                logger.debug("Dolt commit failed", exc_info=True)
        except Exception:
            logger.warning(
                "Retrospective failed for issue #%d — continuing",
                issue_number,
                exc_info=True,
            )

    async def _collect(
        self,
        issue_number: int,
        pr_number: int,
        review_result: ReviewResult,
    ) -> RetrospectiveEntry:
        """Gather all data and build a RetrospectiveEntry."""
        plan_text = self._read_plan_file(issue_number)
        planned_files = self._parse_planned_files(plan_text)
        actual_files = await self._get_actual_files(pr_number)
        accuracy, unplanned, missed = self._compute_accuracy(
            planned_files, actual_files
        )

        meta = self._state.get_worker_result_meta(issue_number)
        quality_fix_rounds = meta.get("quality_fix_attempts", 0)
        impl_duration = meta.get("duration_seconds", 0.0)

        return RetrospectiveEntry(
            issue_number=issue_number,
            pr_number=pr_number,
            timestamp=datetime.now(UTC).isoformat(),
            plan_accuracy_pct=accuracy,
            planned_files=planned_files,
            actual_files=actual_files,
            unplanned_files=unplanned,
            missed_files=missed,
            quality_fix_rounds=quality_fix_rounds,
            review_verdict=review_result.verdict,
            reviewer_fixes_made=review_result.fixes_made,
            ci_fix_rounds=review_result.ci_fix_attempts,
            duration_seconds=impl_duration,
        )

    def _read_plan_file(self, issue_number: int) -> str:
        """Read the plan file for *issue_number*, returning empty string on failure."""
        plan_path = self._config.data_path("plans", f"issue-{issue_number}.md")
        try:
            return plan_path.read_text()
        except OSError:
            logger.debug("Plan file not found for issue #%d", issue_number)
            return ""

    def _parse_planned_files(self, plan_text: str) -> list[str]:
        """Extract file paths from plan text.

        Prefers the structured ``## File Delta`` section if present,
        falling back to heuristic extraction from ``## Files to Modify``
        and ``## New Files``.
        """
        if not plan_text:
            return []

        # Try structured delta first
        from delta_verifier import parse_file_delta

        delta_files = parse_file_delta(plan_text)
        if delta_files:
            return delta_files

        # Fallback: heuristic extraction from prose sections
        files: list[str] = []
        in_section = False

        for line in plan_text.splitlines():
            stripped = line.strip()

            # Detect start of relevant sections
            if re.match(r"^##\s+(Files to Modify|New Files)", stripped):
                in_section = True
                continue

            # End section on next heading
            if in_section and re.match(r"^##\s+", stripped):
                in_section = False
                continue

            if not in_section:
                continue

            # Extract file paths from list items:
            #   - `src/foo.py`
            #   - **src/foo.py**
            #   - src/foo.py
            #   ### 1. `src/foo.py` (NEW)
            # Match backtick-delimited paths
            backtick_matches = re.findall(r"`([^`]+\.\w+)`", stripped)
            if backtick_matches:
                files.extend(backtick_matches)
                continue

            # Match bold paths: **path/to/file.py**
            bold_matches = re.findall(r"\*\*([^*]+\.\w+)\*\*", stripped)
            if bold_matches:
                files.extend(bold_matches)
                continue

            # Match bare paths on list items: - path/to/file.py
            bare_match = re.match(r"^[-*]\s+(\S+\.\w+)", stripped)
            if bare_match:
                files.append(bare_match.group(1))

        return sorted(set(files))

    async def _get_actual_files(self, pr_number: int) -> list[str]:
        """Get the list of files actually changed in the PR."""
        return await self._prs.get_pr_diff_names(pr_number)

    @staticmethod
    def _compute_accuracy(planned: list[str], actual: list[str]) -> PlanAccuracyResult:
        """Compute plan accuracy percentage, unplanned files, and missed files."""
        planned_set = set(planned)
        actual_set = set(actual)
        unplanned = sorted(actual_set - planned_set)
        missed = sorted(planned_set - actual_set)
        intersection = planned_set & actual_set

        if not planned_set:
            accuracy = 0.0
        else:
            accuracy = round(len(intersection) / len(planned_set) * 100, 1)

        return PlanAccuracyResult(accuracy=accuracy, unplanned=unplanned, missed=missed)

    def _append_entry(self, entry: RetrospectiveEntry) -> None:
        """Append a retrospective entry to Dolt."""
        if hasattr(self._state, "append_retrospective"):
            try:
                self._state.append_retrospective(entry.model_dump())
            except Exception:  # noqa: BLE001
                logger.warning("Dolt retrospective write failed", exc_info=True)

    def _load_recent(self, n: int) -> list[RetrospectiveEntry]:
        """Load the last *n* entries from Dolt."""
        if hasattr(self._state, "load_recent_retrospectives"):
            try:
                rows = self._state.load_recent_retrospectives(n)
                entries: list[RetrospectiveEntry] = []
                for row in rows:
                    try:
                        entries.append(RetrospectiveEntry.model_validate(row))
                    except Exception:  # noqa: BLE001
                        continue
                return entries
            except Exception:  # noqa: BLE001
                logger.warning("Could not load retrospectives from Dolt", exc_info=True)
        return []

