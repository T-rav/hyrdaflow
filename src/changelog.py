"""Changelog generation from epic sub-issue PRs."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

from models import ChangeCategory, ChangelogEntry
from pr_manager import PRManager

logger = logging.getLogger("hydraflow.changelog")

# Conventional commit prefix → category mapping
_PREFIX_MAP: list[tuple[re.Pattern[str], ChangeCategory]] = [
    (re.compile(r"^feat(\(.+?\))?[!:]", re.IGNORECASE), ChangeCategory.FEATURES),
    (re.compile(r"^fix(\(.+?\))?[!:]", re.IGNORECASE), ChangeCategory.BUG_FIXES),
    (
        re.compile(r"^refactor(\(.+?\))?[!:]", re.IGNORECASE),
        ChangeCategory.IMPROVEMENTS,
    ),
    (
        re.compile(r"^perf(\(.+?\))?[!:]", re.IGNORECASE),
        ChangeCategory.IMPROVEMENTS,
    ),
    (re.compile(r"^docs?(\(.+?\))?[!:]", re.IGNORECASE), ChangeCategory.DOCUMENTATION),
]

# Matches a "## Summary" section in a PR body
_SUMMARY_RE = re.compile(
    r"##\s+Summary\s*\n(.*?)(?=\n##\s|\Z)",
    re.DOTALL | re.IGNORECASE,
)


def categorize_change(title: str) -> ChangeCategory:
    """Classify a PR title into a changelog category using conventional commit prefixes."""
    stripped = title.strip()
    for pattern, category in _PREFIX_MAP:
        if pattern.search(stripped):
            return category
    return ChangeCategory.MISCELLANEOUS


def extract_summary(body: str) -> str:
    """Extract the ``## Summary`` section from a PR body.

    Returns the summary text stripped of leading/trailing whitespace,
    or an empty string if no summary section is found.
    """
    if not body:
        return ""
    match = _SUMMARY_RE.search(body)
    if match:
        return match.group(1).strip()
    return ""


# Matches only the conventional commit types used in _PREFIX_MAP — avoids
# stripping arbitrary WORD: prefixes (e.g. "HTTP:", "WIP:") from titles.
_CLEAN_PREFIX_RE = re.compile(
    r"^(?:feat|fix|refactor|perf|docs?)(\(.+?\))?!?:\s*",
    re.IGNORECASE,
)


def _clean_title(title: str) -> str:
    """Remove conventional commit prefix from a title for display."""
    # Strip "feat: ", "fix(scope): ", "feat!: ", etc. — only known types.
    stripped = title.strip()
    cleaned = _CLEAN_PREFIX_RE.sub("", stripped)
    return cleaned.strip() or stripped


def format_changelog(
    version: str,
    entries: list[ChangelogEntry],
    date: str | None = None,
) -> str:
    """Format changelog entries into Keep a Changelog style markdown.

    Args:
        version: Version string (e.g. "1.2.0").
        entries: List of changelog entries to format.
        date: Optional date string. Defaults to today's date.

    Returns:
        Formatted markdown changelog string.
    """
    if date is None:
        date = datetime.now(UTC).strftime("%Y-%m-%d")

    if not entries:
        return f"## [{version}] - {date}\n\nNo changes recorded.\n"

    # Group entries by category, preserving display order
    category_order = list(ChangeCategory)
    grouped: dict[ChangeCategory, list[ChangelogEntry]] = {}
    for entry in entries:
        grouped.setdefault(entry.category, []).append(entry)

    lines: list[str] = [f"## [{version}] - {date}"]

    for cat in category_order:
        cat_entries = grouped.get(cat)
        if not cat_entries:
            continue
        lines.append("")
        lines.append(f"### {cat.value}")
        for entry in cat_entries:
            display_title = _clean_title(entry.title)
            refs: list[str] = []
            if entry.issue_number:
                refs.append(f"#{entry.issue_number}")
            if entry.pr_number:
                refs.append(f"PR #{entry.pr_number}")
            ref_str = f" ({', '.join(refs)})" if refs else ""
            lines.append(f"- {display_title}{ref_str}")
            if entry.summary:
                for summary_line in entry.summary.splitlines():
                    stripped = summary_line.strip()
                    if stripped:
                        lines.append(f"  {stripped}")

    lines.append("")
    return "\n".join(lines)


async def generate_changelog(
    pr_manager: PRManager,
    sub_issues: list[int],
    version: str,
    date: str | None = None,
) -> str:
    """Generate a markdown changelog from sub-issue PRs.

    For each sub-issue, looks up the associated PR, extracts its title
    and summary section, categorizes the change, and formats everything
    into a Keep a Changelog style markdown document.

    Args:
        pr_manager: PRManager instance for GitHub API calls.
        sub_issues: List of sub-issue numbers from the epic.
        version: Version string for the changelog header.
        date: Optional date string. Defaults to today's date.

    Returns:
        Formatted markdown changelog string.
    """
    entries: list[ChangelogEntry] = []

    for issue_num in sub_issues:
        try:
            pr_number = await pr_manager.get_pr_for_issue(issue_num)
        except Exception:  # noqa: BLE001
            logger.debug(
                "Failed to look up PR for sub-issue #%d — skipping",
                issue_num,
                exc_info=True,
            )
            continue
        if not pr_number:
            logger.debug("No PR found for sub-issue #%d — skipping", issue_num)
            continue

        try:
            title, body = await pr_manager.get_pr_title_and_body(pr_number)
        except Exception:  # noqa: BLE001
            logger.debug(
                "Failed to fetch PR #%d for sub-issue #%d — skipping",
                pr_number,
                issue_num,
                exc_info=True,
            )
            continue
        if not title:
            logger.debug(
                "Empty title for PR #%d (issue #%d) — skipping",
                pr_number,
                issue_num,
            )
            continue

        category = categorize_change(title)
        summary = extract_summary(body)

        entries.append(
            ChangelogEntry(
                category=category,
                title=title,
                summary=summary,
                issue_number=issue_num,
                pr_number=pr_number,
            )
        )

    return format_changelog(version, entries, date=date)
