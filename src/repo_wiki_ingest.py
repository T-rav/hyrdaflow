"""Repo Wiki ingest helpers — extract knowledge from completed phase cycles.

Called after plan, implement, and review phases complete to compile
learnings into the per-repo wiki.  Each function parses phase-specific
output and produces ``WikiEntry`` objects for the store.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel

from events import EventType, HydraFlowEvent
from knowledge_metrics import metrics as _metrics
from repo_wiki import WikiEntry, classify_topic
from staleness import evaluate as evaluate_staleness

if TYPE_CHECKING:
    from events import EventBus
    from repo_wiki import RepoWikiStore
    from wiki_compiler import WikiCompiler

logger = logging.getLogger("hydraflow.repo_wiki_ingest")


# ---------------------------------------------------------------------------
# Result model for ingest_phase_output
# ---------------------------------------------------------------------------


class IngestWithContradictionsResult(BaseModel):
    entries_added: int = 0
    entries_updated: int = 0
    contradictions_marked: int = 0


def ingest_from_plan(
    store: RepoWikiStore,
    repo: str,
    issue_number: int,
    plan_text: str,
    *,
    git_backed: bool = False,
) -> int:
    """Extract knowledge from a completed plan and ingest into the wiki.

    When ``git_backed`` is True (Phase 3 layout), each entry is written as
    a per-entry markdown file under the appropriate topic directory via
    ``store.write_entry``; a per-issue log record is appended via
    ``store.append_log``; the legacy topic-level ``store.ingest`` path is
    skipped entirely.  Callers staging these writes in a worktree should
    follow up with ``store.commit_pending_entries(...)`` to roll the new
    files into the issue's PR.

    When ``git_backed`` is False, preserves the legacy topic-level ingest.

    Returns the number of entries added/updated.
    """
    if not plan_text or not repo:
        return 0

    # (entry, topic) pairs so each writable entry knows where to land
    # under the per-entry layout.
    pairs: list[tuple[WikiEntry, str]] = []
    sections = _extract_sections(plan_text)

    if "architecture" in sections or "design" in sections:
        content = sections.get("architecture", sections.get("design", ""))
        if content and len(content) > 50:
            pairs.append(
                (
                    WikiEntry(
                        title=f"Architecture notes from #{issue_number}",
                        content=content[:2000],
                        source_type="plan",
                        source_issue=issue_number,
                    ),
                    "architecture",
                )
            )

    if "risks" in sections or "edge cases" in sections:
        content = sections.get("risks", sections.get("edge cases", ""))
        if content and len(content) > 30:
            pairs.append(
                (
                    WikiEntry(
                        title=f"Gotchas identified in #{issue_number}",
                        content=content[:2000],
                        source_type="plan",
                        source_issue=issue_number,
                    ),
                    "gotchas",
                )
            )

    if "testing" in sections or "test strategy" in sections:
        content = sections.get("testing", sections.get("test strategy", ""))
        if content and len(content) > 30:
            pairs.append(
                (
                    WikiEntry(
                        title=f"Test strategy from #{issue_number}",
                        content=content[:2000],
                        source_type="plan",
                        source_issue=issue_number,
                    ),
                    "testing",
                )
            )

    if not pairs:
        return 0

    if git_backed:
        total = _write_pairs_or_rollback(store, repo, issue_number, "plan", pairs)
        logger.info(
            "Wiki ingest from plan #%d: %d entries (git-backed)",
            issue_number,
            total,
        )
        return total

    entries = [e for e, _ in pairs]
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
    *,
    git_backed: bool = False,
) -> int:
    """Extract patterns from review feedback and ingest into the wiki.

    See ``ingest_from_plan`` for the ``git_backed`` contract. Review
    feedback lands under the ``patterns`` topic.

    Returns the number of entries added/updated.
    """
    if not review_feedback or not repo:
        return 0

    pairs: list[tuple[WikiEntry, str]] = []
    if len(review_feedback) > 100:
        pairs.append(
            (
                WikiEntry(
                    title=f"Review patterns from #{issue_number}",
                    content=review_feedback[:2000],
                    source_type="review",
                    source_issue=issue_number,
                ),
                "patterns",
            )
        )

    if not pairs:
        return 0

    if git_backed:
        total = _write_pairs_or_rollback(store, repo, issue_number, "review", pairs)
        logger.info(
            "Wiki ingest from review #%d: %d entries (git-backed)",
            issue_number,
            total,
        )
        return total

    entries = [e for e, _ in pairs]
    result = store.ingest(repo, entries)
    total = result.entries_added + result.entries_updated
    if total:
        logger.info("Wiki ingest from review #%d: %d entries", issue_number, total)
    return total


def _write_pairs_or_rollback(
    store: RepoWikiStore,
    repo: str,
    issue_number: int,
    phase: str,
    pairs: list[tuple[WikiEntry, str]],
) -> int:
    """Write every (entry, topic) pair via ``store.write_entry`` as a
    single unit.  On any exception, delete the files already written so
    no partial set can be picked up by the next ingest's id-scan or
    committed as a half-applied batch.

    Returns the number of entries written on success.  Re-raises the
    underlying exception after rollback when the batch fails, so the
    caller can surface the error and decide whether to retry.
    """
    written: list[Path] = []
    try:
        for entry, topic in pairs:
            written.append(store.write_entry(repo, entry, topic=topic))
        store.append_log(
            repo,
            issue_number,
            {"phase": phase, "action": "ingest", "entries": len(pairs)},
        )
    except Exception:
        for p in written:
            try:
                p.unlink()
            except OSError:
                logger.warning("wiki ingest rollback: failed to unlink %s", p)
        raise
    return len(pairs)


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


# ---------------------------------------------------------------------------
# Async helper: ingest with contradiction detection
# ---------------------------------------------------------------------------


async def ingest_phase_output(
    *,
    store: RepoWikiStore,
    repo: str,
    entries: list[WikiEntry],
    compiler: WikiCompiler,
    event_bus: EventBus | None = None,
) -> IngestWithContradictionsResult:
    """Ingest entries and run contradiction detection on each.

    Contradicted siblings have their ``superseded_by``/``superseded_reason``
    set via :meth:`RepoWikiStore.mark_superseded`. Entries are never deleted.

    When ``event_bus`` is provided, a ``WIKI_SUPERSEDES`` event is published
    for every contradiction marked. Publish failures are swallowed — wiki
    events are non-critical.
    """
    ids = [e.id for e in entries]
    if len(set(ids)) != len(ids):
        duplicates = [i for i in set(ids) if ids.count(i) > 1]
        raise ValueError(
            f"ingest_phase_output entries must have unique ids; duplicate: {duplicates!r}"
        )
    ingest_result = store.ingest(repo, entries)
    _metrics.increment("wiki_entries_ingested", len(entries))
    result = IngestWithContradictionsResult(
        entries_added=ingest_result.entries_added,
        entries_updated=ingest_result.entries_updated,
    )

    now = datetime.now(UTC)
    for new_entry in entries:
        if new_entry.topic is None:
            continue
        topic_path = store.repo_dir(repo) / f"{new_entry.topic}.md"
        if not topic_path.exists():
            continue
        all_entries = store.load_topic_entries(topic_path)
        siblings = [
            e
            for e in all_entries
            if e.id != new_entry.id and evaluate_staleness(e, now=now) == "current"
        ]
        if not siblings:
            continue

        check = await compiler.detect_contradictions(
            new_entry=new_entry,
            siblings=siblings,
            repo=repo,
        )
        for flagged in check.contradicts:
            if store.mark_superseded(
                repo,
                entry_id=flagged.id,
                superseded_by=new_entry.id,
                reason=flagged.reason,
            ):
                result.contradictions_marked += 1
                if event_bus is not None:
                    await _emit_wiki_supersedes(
                        event_bus=event_bus,
                        repo=repo,
                        superseded_id=flagged.id,
                        superseded_by=new_entry.id,
                        reason=flagged.reason,
                    )

    return result


async def _emit_wiki_supersedes(
    *,
    event_bus: EventBus,
    repo: str,
    superseded_id: str,
    superseded_by: str,
    reason: str,
) -> None:
    """Publish a WIKI_SUPERSEDES event. Swallows errors."""
    _metrics.increment("wiki_supersedes")
    event = HydraFlowEvent(
        type=EventType.WIKI_SUPERSEDES,
        data={
            "repo": repo,
            "superseded_id": superseded_id,
            "superseded_by": superseded_by,
            "reason": reason,
        },
    )
    try:
        await event_bus.publish(event)
    except Exception:  # noqa: BLE001
        logger.debug("wiki event publish failed; continuing")


_REFLECTION_BLOCK_RE = re.compile(
    r"^---\s+(?P<phase>[\w-]+)\s*\|\s*[^\n]*---\s*\n",
    flags=re.MULTILINE,
)


def entries_from_reflections_log(
    *,
    log: str,
    repo: str,
    issue_number: int,
) -> list[WikiEntry]:
    """Split a Reflexion log into one WikiEntry per phase block.

    The reflections log is written by ``append_reflection`` in
    ``src/reflections.py`` with the marker format
    ``--- {phase} | YYYY-MM-DD HH:MM UTC ---`` between blocks.

    Empty or whitespace-only blocks are skipped. Each entry gets a
    fresh ULID (default_factory on ``WikiEntry``).
    """
    if not log or not log.strip():
        return []

    matches = list(_REFLECTION_BLOCK_RE.finditer(log))
    if not matches:
        return []

    entries: list[WikiEntry] = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(log)
        body = log[m.end() : end].strip()
        if not body:
            continue
        entry = WikiEntry(
            title=f"Reflection from #{issue_number} ({m.group('phase')})",
            content=body,
            source_type="reflection",
            source_issue=issue_number,
            source_repo=repo,
        )
        entry.topic = classify_topic(entry)
        entries.append(entry)
    return entries
