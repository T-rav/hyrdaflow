"""Post-merge retrospective analysis for the HydraFlow orchestrator."""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

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
    timestamp: str
    plan_accuracy_pct: float = 0.0
    planned_files: list[str] = Field(default_factory=list)
    actual_files: list[str] = Field(default_factory=list)
    unplanned_files: list[str] = Field(default_factory=list)
    missed_files: list[str] = Field(default_factory=list)
    quality_fix_rounds: int = 0
    review_verdict: str = ""
    reviewer_fixes_made: bool = False
    ci_fix_rounds: int = 0
    duration_seconds: float = 0.0


class RetrospectiveCollector:
    """Collects post-merge retrospective data and detects patterns."""

    def __init__(
        self,
        config: HydraFlowConfig,
        state: StateTracker,
        prs: PRManager,
    ) -> None:
        self._config = config
        self._state = state
        self._prs = prs
        self._retro_path = (
            config.repo_root / ".hydraflow" / "memory" / "retrospectives.jsonl"
        )
        self._filed_patterns_path = (
            config.repo_root / ".hydraflow" / "memory" / "filed_patterns.json"
        )

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
            recent = self._load_recent(self._config.retrospective_window)
            await self._detect_patterns(recent)
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
            review_verdict=review_result.verdict.value,
            reviewer_fixes_made=review_result.fixes_made,
            ci_fix_rounds=review_result.ci_fix_attempts,
            duration_seconds=impl_duration,
        )

    def _read_plan_file(self, issue_number: int) -> str:
        """Read the plan file for *issue_number*, returning empty string on failure."""
        plan_path = (
            self._config.repo_root / ".hydraflow" / "plans" / f"issue-{issue_number}.md"
        )
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
    def _compute_accuracy(
        planned: list[str], actual: list[str]
    ) -> tuple[float, list[str], list[str]]:
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

        return accuracy, unplanned, missed

    def _append_entry(self, entry: RetrospectiveEntry) -> None:
        """Append a JSON line to the retrospective log."""
        self._retro_path.parent.mkdir(parents=True, exist_ok=True)
        with self._retro_path.open("a") as f:
            f.write(entry.model_dump_json() + "\n")

    def _load_recent(self, n: int) -> list[RetrospectiveEntry]:
        """Load the last *n* entries from the retrospective log."""
        if not self._retro_path.exists():
            return []
        try:
            lines = self._retro_path.read_text().strip().splitlines()
            entries: list[RetrospectiveEntry] = []
            for line in lines[-n:]:
                if line.strip():
                    entries.append(RetrospectiveEntry.model_validate_json(line))
            return entries
        except (OSError, json.JSONDecodeError):
            logger.warning("Could not load retrospective log", exc_info=True)
            return []

    async def _detect_patterns(self, entries: list[RetrospectiveEntry]) -> None:
        """Scan recent entries for patterns and file improvement proposals."""
        if len(entries) < 3:
            return

        filed = self._load_filed_patterns()
        n = len(entries)

        # Quality fix pattern: >50% needed quality fixes
        quality_fix_count = sum(1 for e in entries if e.quality_fix_rounds > 0)
        if quality_fix_count / n > 0.5:
            key = "quality_fix"
            if key not in filed:
                await self._file_improvement_issue(
                    title="Pattern: Frequent quality fix rounds needed",
                    body=(
                        f"**{quality_fix_count} of {n}** recent issues needed "
                        "quality fix rounds during implementation.\n\n"
                        "Consider strengthening the implementation prompt to "
                        "emphasize running `make quality` before finishing.\n\n"
                        "---\n*Auto-detected by HydraFlow Retrospective*"
                    ),
                )
                filed.add(key)
                self._save_filed_patterns(filed)
                return  # Cap at 1 per run

        # Plan accuracy pattern: average < 70%
        avg_accuracy = sum(e.plan_accuracy_pct for e in entries) / n
        if avg_accuracy < 70:
            key = "plan_accuracy"
            if key not in filed:
                await self._file_improvement_issue(
                    title="Pattern: Low plan accuracy across recent issues",
                    body=(
                        f"Average plan accuracy is **{avg_accuracy:.1f}%** "
                        f"across the last {n} issues.\n\n"
                        "The planner is consistently missing files that need "
                        "changes. Consider improving the planner prompt to "
                        "better analyze dependencies.\n\n"
                        "---\n*Auto-detected by HydraFlow Retrospective*"
                    ),
                )
                filed.add(key)
                self._save_filed_patterns(filed)
                return

        # Reviewer fix pattern: >40% needed reviewer fixes
        reviewer_fix_count = sum(1 for e in entries if e.reviewer_fixes_made)
        if reviewer_fix_count / n > 0.4:
            key = "reviewer_fixes"
            if key not in filed:
                await self._file_improvement_issue(
                    title="Pattern: Reviewer frequently fixing implementation",
                    body=(
                        f"**{reviewer_fix_count} of {n}** recent reviews "
                        "required the reviewer to make fixes.\n\n"
                        "The implementation prompt likely needs strengthening "
                        "to produce higher-quality first drafts.\n\n"
                        "---\n*Auto-detected by HydraFlow Retrospective*"
                    ),
                )
                filed.add(key)
                self._save_filed_patterns(filed)
                return

        # Unplanned file pattern: same file appears in >30% of entries
        unplanned_counter: Counter[str] = Counter()
        for e in entries:
            for f in e.unplanned_files:
                unplanned_counter[f] += 1
        threshold = n * 0.3
        for file_path, count in unplanned_counter.most_common():
            if count > threshold:
                key = f"unplanned_file:{file_path}"
                if key not in filed:
                    await self._file_improvement_issue(
                        title=f"Pattern: {file_path} frequently unplanned",
                        body=(
                            f"`{file_path}` appeared as an unplanned file in "
                            f"**{count} of {n}** recent issues.\n\n"
                            "The planner should be made aware that this file "
                            "commonly needs changes.\n\n"
                            "---\n*Auto-detected by HydraFlow Retrospective*"
                        ),
                    )
                    filed.add(key)
                    self._save_filed_patterns(filed)
                    return
                break

    async def _file_improvement_issue(self, title: str, body: str) -> None:
        """File a ``hydraflow-improve`` + ``hydraflow-hitl`` improvement proposal."""
        labels = self._config.improve_label[:1] + self._config.hitl_label[:1]
        issue_num = await self._prs.create_issue(title, body, labels)
        if issue_num:
            self._state.set_hitl_origin(issue_num, self._config.improve_label[0])
            self._state.set_hitl_cause(issue_num, "Retrospective pattern detected")

    def _load_filed_patterns(self) -> set[str]:
        """Load the set of already-filed pattern keys."""
        if not self._filed_patterns_path.exists():
            return set()
        try:
            data = json.loads(self._filed_patterns_path.read_text())
            return set(data) if isinstance(data, list) else set()
        except (OSError, json.JSONDecodeError):
            return set()

    def _save_filed_patterns(self, patterns: set[str]) -> None:
        """Persist the set of filed pattern keys."""
        try:
            self._filed_patterns_path.parent.mkdir(parents=True, exist_ok=True)
            self._filed_patterns_path.write_text(json.dumps(sorted(patterns)))
        except OSError:
            logger.warning(
                "Could not save filed patterns to %s",
                self._filed_patterns_path,
                exc_info=True,
            )
