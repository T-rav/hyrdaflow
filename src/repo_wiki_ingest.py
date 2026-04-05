"""Repo Wiki ingest helpers — extract knowledge from completed phase cycles.

Called after plan, implement, and review phases complete to compile
learnings into the per-repo wiki.  Each function parses phase-specific
output and produces ``WikiEntry`` objects for the store.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from repo_wiki import WikiEntry

if TYPE_CHECKING:
    from repo_wiki import RepoWikiStore

logger = logging.getLogger("hydraflow.repo_wiki_ingest")


def ingest_from_plan(
    store: RepoWikiStore,
    repo: str,
    issue_number: int,
    plan_text: str,
) -> int:
    """Extract knowledge from a completed plan and ingest into the wiki.

    Returns the number of entries added/updated.
    """
    if not plan_text or not repo:
        return 0

    entries: list[WikiEntry] = []

    # Extract architecture insights from plan sections
    sections = _extract_sections(plan_text)

    if "architecture" in sections or "design" in sections:
        content = sections.get("architecture", sections.get("design", ""))
        if content and len(content) > 50:
            entries.append(
                WikiEntry(
                    title=f"Architecture notes from #{issue_number}",
                    content=content[:2000],
                    source_type="plan",
                    source_issue=issue_number,
                )
            )

    if "risks" in sections or "edge cases" in sections:
        content = sections.get("risks", sections.get("edge cases", ""))
        if content and len(content) > 30:
            entries.append(
                WikiEntry(
                    title=f"Gotchas identified in #{issue_number}",
                    content=content[:2000],
                    source_type="plan",
                    source_issue=issue_number,
                )
            )

    if "testing" in sections or "test strategy" in sections:
        content = sections.get("testing", sections.get("test strategy", ""))
        if content and len(content) > 30:
            entries.append(
                WikiEntry(
                    title=f"Test strategy from #{issue_number}",
                    content=content[:2000],
                    source_type="plan",
                    source_issue=issue_number,
                )
            )

    if not entries:
        return 0

    result = store.ingest(repo, entries)
    total = result.entries_added + result.entries_updated
    if total:
        logger.info("Wiki ingest from plan #%d: %d entries", issue_number, total)
    return total


def ingest_from_review(
    store: RepoWikiStore,
    repo: str,
    issue_number: int,
    review_feedback: str,
) -> int:
    """Extract patterns from review feedback and ingest into the wiki.

    Returns the number of entries added/updated.
    """
    if not review_feedback or not repo:
        return 0

    entries: list[WikiEntry] = []

    # Look for recurring patterns in review feedback
    if len(review_feedback) > 100:
        entries.append(
            WikiEntry(
                title=f"Review patterns from #{issue_number}",
                content=review_feedback[:2000],
                source_type="review",
                source_issue=issue_number,
            )
        )

    if not entries:
        return 0

    result = store.ingest(repo, entries)
    total = result.entries_added + result.entries_updated
    if total:
        logger.info("Wiki ingest from review #%d: %d entries", issue_number, total)
    return total


def _extract_sections(text: str) -> dict[str, str]:
    """Parse markdown sections (## headings) into a dict."""
    sections: dict[str, str] = {}
    current_heading = ""
    current_lines: list[str] = []

    for line in text.split("\n"):
        if line.startswith("## "):
            if current_heading and current_lines:
                sections[current_heading] = "\n".join(current_lines).strip()
            current_heading = line[3:].strip().lower()
            current_lines = []
        elif current_heading:
            current_lines.append(line)

    if current_heading and current_lines:
        sections[current_heading] = "\n".join(current_lines).strip()

    return sections
