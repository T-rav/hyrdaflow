"""Repo Wiki — per-repository LLM knowledge base.

Inspired by Karpathy's "LLM Knowledge Base" pattern: instead of RAG,
maintain a structured markdown wiki that the LLM reads directly.  Each
target repo gets its own wiki directory with an index, topic pages, and
an append-only operation log.

Three operations:
  - **ingest**: after a plan/implement/review cycle completes, compile
    learnings into the wiki (update index, topic pages, cross-refs).
  - **query**: before an agent runs, load relevant wiki pages for the
    target repo and inject them into the prompt.
  - **lint**: periodic health check — flag stale entries, missing
    cross-refs, contradictions.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger("hydraflow.repo_wiki")

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

# Default topic categories seeded on first ingest
DEFAULT_TOPICS: list[str] = [
    "architecture",
    "patterns",
    "gotchas",
    "testing",
    "dependencies",
]


class WikiEntry(BaseModel):
    """A single knowledge entry within a topic page."""

    title: str = Field(description="Short summary of the insight")
    content: str = Field(description="Full explanation")
    source_type: str = Field(
        description="Where the knowledge came from: plan, implement, review, hitl"
    )
    source_issue: int | None = Field(
        default=None, description="GitHub issue number, if applicable"
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
    )
    stale: bool = Field(default=False, description="Flagged as potentially outdated")


class WikiIndex(BaseModel):
    """Master index for a repo wiki — stored as index.json for programmatic access."""

    repo_slug: str = Field(description="owner/repo identifier")
    topics: dict[str, list[str]] = Field(
        default_factory=dict,
        description="topic_name -> list of entry titles",
    )
    total_entries: int = 0
    last_updated: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
    )
    last_lint: str | None = None


class LintResult(BaseModel):
    """Result of a wiki lint pass."""

    stale_entries: int = 0
    orphan_entries: int = 0
    empty_topics: list[str] = Field(default_factory=list)
    total_entries: int = 0


class IngestResult(BaseModel):
    """Result of an ingest operation."""

    pages_updated: int = 0
    entries_added: int = 0
    entries_updated: int = 0


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class RepoWikiStore:
    """File-based per-repo wiki manager.

    Directory layout::

        {wiki_root}/
          {repo_slug}/
            index.json       — structured index (WikiIndex)
            index.md         — human-readable index
            log.jsonl        — append-only operation log
            architecture.md  — topic page
            patterns.md      — topic page
            gotchas.md       — topic page
            testing.md       — topic page
            dependencies.md  — topic page
    """

    def __init__(self, wiki_root: Path) -> None:
        self._wiki_root = wiki_root

    # -- public API --------------------------------------------------------

    def ingest(
        self,
        repo_slug: str,
        entries: list[WikiEntry],
    ) -> IngestResult:
        """Compile new knowledge entries into the wiki.

        Creates the repo wiki directory if it doesn't exist, updates
        topic pages, refreshes the index, and logs the operation.
        """
        repo_dir = self._ensure_repo_dir(repo_slug)
        result = IngestResult()

        for entry in entries:
            topic = self._classify_topic(entry)
            topic_path = repo_dir / f"{topic}.md"

            existing = self._load_topic_entries(topic_path)
            updated = False

            # Check for existing entry with same title — update it
            for i, existing_entry in enumerate(existing):
                if existing_entry.title.lower() == entry.title.lower():
                    existing[i] = entry
                    result.entries_updated += 1
                    updated = True
                    break

            if not updated:
                existing.append(entry)
                result.entries_added += 1

            self._write_topic_page(topic_path, topic, existing)
            result.pages_updated += 1

        self._rebuild_index(repo_slug)
        self._append_log(
            repo_slug,
            "ingest",
            {
                "entries_added": result.entries_added,
                "entries_updated": result.entries_updated,
            },
        )
        return result

    def query(
        self,
        repo_slug: str,
        keywords: list[str] | None = None,
        topics: list[str] | None = None,
        max_chars: int = 15_000,
    ) -> str:
        """Load relevant wiki pages for prompt injection.

        Returns a markdown string containing the index summary and
        matching topic sections, capped at *max_chars*.
        """
        repo_dir = self._repo_dir(repo_slug)
        if not repo_dir.exists():
            return ""

        parts: list[str] = []
        index = self._load_index(repo_slug)
        if index is None:
            return ""

        # Always include a compact index header
        parts.append(f"# Repo Wiki: {repo_slug}\n")
        parts.append(
            f"__{index.total_entries} entries across {len(index.topics)} topics__\n"
        )

        # Determine which topics to include
        target_topics = set(topics or index.topics.keys())

        for topic_name in sorted(target_topics):
            if topic_name not in index.topics:
                continue

            topic_path = repo_dir / f"{topic_name}.md"
            if not topic_path.exists():
                continue

            entries = self._load_topic_entries(topic_path)
            if not entries:
                continue

            # Keyword filtering within topic
            if keywords:
                entries = [
                    e
                    for e in entries
                    if any(
                        kw.lower() in e.title.lower() or kw.lower() in e.content.lower()
                        for kw in keywords
                    )
                ]

            if not entries:
                continue

            section = f"\n## {topic_name.replace('_', ' ').title()}\n\n"
            for entry in entries:
                section += f"### {entry.title}\n{entry.content}\n"
                if entry.source_issue:
                    section += (
                        f"_Source: #{entry.source_issue} ({entry.source_type})_\n"
                    )
                section += "\n"

            parts.append(section)

        result = "\n".join(parts)
        return result[:max_chars]

    def lint(self, repo_slug: str) -> LintResult:
        """Run a health check on the wiki for the given repo.

        Detects: empty topics, entries not in index (orphans), and counts
        total entries. Does NOT modify the wiki — just reports.
        """
        repo_dir = self._repo_dir(repo_slug)
        result = LintResult()

        if not repo_dir.exists():
            return result

        index = self._load_index(repo_slug)
        if index is None:
            return result

        indexed_titles: set[str] = set()
        for titles in index.topics.values():
            indexed_titles.update(titles)

        for topic_name in DEFAULT_TOPICS:
            topic_path = repo_dir / f"{topic_name}.md"
            if not topic_path.exists():
                result.empty_topics.append(topic_name)
                continue

            entries = self._load_topic_entries(topic_path)
            if not entries:
                result.empty_topics.append(topic_name)
                continue

            for entry in entries:
                result.total_entries += 1
                if entry.stale:
                    result.stale_entries += 1
                if entry.title not in indexed_titles:
                    result.orphan_entries += 1

        self._append_log(repo_slug, "lint", result.model_dump())
        return result

    def list_repos(self) -> list[str]:
        """Return slugs for all repos with wikis."""
        if not self._wiki_root.exists():
            return []
        repos: list[str] = []
        for owner_dir in sorted(self._wiki_root.iterdir()):
            if not owner_dir.is_dir():
                continue
            for repo_dir in sorted(owner_dir.iterdir()):
                if repo_dir.is_dir() and (repo_dir / "index.json").exists():
                    repos.append(f"{owner_dir.name}/{repo_dir.name}")
        return repos

    # -- internal ----------------------------------------------------------

    def _repo_dir(self, repo_slug: str) -> Path:
        """Return the wiki directory for a repo slug (owner/repo)."""
        return self._wiki_root / repo_slug

    def _ensure_repo_dir(self, repo_slug: str) -> Path:
        repo_dir = self._repo_dir(repo_slug)
        repo_dir.mkdir(parents=True, exist_ok=True)

        # Seed default topic files if missing
        for topic in DEFAULT_TOPICS:
            topic_path = repo_dir / f"{topic}.md"
            if not topic_path.exists():
                topic_path.write_text(
                    f"# {topic.replace('_', ' ').title()}\n\n_No entries yet._\n"
                )

        # Seed index if missing
        index_path = repo_dir / "index.json"
        if not index_path.exists():
            index = WikiIndex(repo_slug=repo_slug)
            index_path.write_text(index.model_dump_json(indent=2))

        return repo_dir

    def _classify_topic(self, entry: WikiEntry) -> str:
        """Classify an entry into a topic based on keywords in title/content."""
        text = f"{entry.title} {entry.content}".lower()

        topic_keywords: dict[str, list[str]] = {
            "architecture": [
                "architect",
                "structure",
                "module",
                "layer",
                "service",
                "component",
                "design",
                "pattern",
                "directory",
                "layout",
            ],
            "patterns": [
                "pattern",
                "convention",
                "idiom",
                "style",
                "approach",
                "best practice",
                "anti-pattern",
                "refactor",
            ],
            "gotchas": [
                "gotcha",
                "pitfall",
                "bug",
                "issue",
                "error",
                "fail",
                "careful",
                "watch out",
                "caveat",
                "workaround",
                "edge case",
            ],
            "testing": [
                "test",
                "fixture",
                "mock",
                "assert",
                "coverage",
                "pytest",
                "spec",
                "integration test",
                "unit test",
            ],
            "dependencies": [
                "dependency",
                "package",
                "import",
                "library",
                "version",
                "requirement",
                "pip",
                "npm",
                "uv",
                "cargo",
            ],
        }

        best_topic = "patterns"  # default
        best_score = 0

        for topic, keywords in topic_keywords.items():
            score = sum(1 for kw in keywords if kw in text)
            if score > best_score:
                best_score = score
                best_topic = topic

        return best_topic

    def _load_topic_entries(self, topic_path: Path) -> list[WikiEntry]:
        """Parse a topic markdown file back into entries.

        Each entry is stored as a JSON code block under an H3 heading.
        """
        if not topic_path.exists():
            return []

        text = topic_path.read_text()
        entries: list[WikiEntry] = []

        for match in re.finditer(r"```json:entry\n(.+?)\n```", text, re.DOTALL):
            try:
                entries.append(WikiEntry.model_validate_json(match.group(1)))
            except Exception:  # noqa: BLE001
                logger.warning("Skipping malformed entry in %s", topic_path)

        return entries

    def _write_topic_page(
        self,
        topic_path: Path,
        topic_name: str,
        entries: list[WikiEntry],
    ) -> None:
        """Write a topic page with entries stored as JSON code blocks."""
        lines = [f"# {topic_name.replace('_', ' ').title()}\n"]

        if not entries:
            lines.append("_No entries yet._\n")
        else:
            for entry in entries:
                lines.append(f"\n## {entry.title}\n")
                lines.append(f"{entry.content}\n")
                if entry.source_issue:
                    lines.append(
                        f"_Source: #{entry.source_issue} ({entry.source_type})_\n"
                    )
                # Store structured data for round-tripping
                lines.append(f"\n```json:entry\n{entry.model_dump_json()}\n```\n")

        topic_path.write_text("\n".join(lines))

    def _load_index(self, repo_slug: str) -> WikiIndex | None:
        index_path = self._repo_dir(repo_slug) / "index.json"
        if not index_path.exists():
            return None
        try:
            return WikiIndex.model_validate_json(index_path.read_text())
        except Exception:  # noqa: BLE001
            logger.warning("Failed to load wiki index for %s", repo_slug)
            return None

    def _rebuild_index(self, repo_slug: str) -> None:
        """Rebuild the index from the current topic pages."""
        repo_dir = self._repo_dir(repo_slug)
        topics: dict[str, list[str]] = {}
        total = 0

        for topic in DEFAULT_TOPICS:
            topic_path = repo_dir / f"{topic}.md"
            entries = self._load_topic_entries(topic_path)
            if entries:
                topics[topic] = [e.title for e in entries]
                total += len(entries)

        # Also scan for custom topic files
        for md_file in sorted(repo_dir.glob("*.md")):
            topic_name = md_file.stem
            if topic_name in topics or topic_name == "index":
                continue
            entries = self._load_topic_entries(md_file)
            if entries:
                topics[topic_name] = [e.title for e in entries]
                total += len(entries)

        index = WikiIndex(
            repo_slug=repo_slug,
            topics=topics,
            total_entries=total,
            last_updated=datetime.now(UTC).isoformat(),
        )

        # Write JSON index
        index_path = repo_dir / "index.json"
        index_path.write_text(index.model_dump_json(indent=2))

        # Write human-readable index.md
        md_path = repo_dir / "index.md"
        lines = [
            f"# Wiki Index: {repo_slug}\n",
            f"**{total} entries** | Last updated: {index.last_updated}\n",
        ]
        for topic, titles in sorted(topics.items()):
            lines.append(f"\n## {topic.replace('_', ' ').title()} ({len(titles)})\n")
            for title in titles:
                lines.append(f"- {title}")
        md_path.write_text("\n".join(lines) + "\n")

    def _append_log(
        self,
        repo_slug: str,
        operation: str,
        details: dict[str, Any],
    ) -> None:
        """Append an operation record to the repo's log."""
        repo_dir = self._repo_dir(repo_slug)
        log_path = repo_dir / "log.jsonl"
        record = {
            "ts": datetime.now(UTC).isoformat(),
            "op": operation,
            **details,
        }
        with log_path.open("a") as f:
            f.write(json.dumps(record) + "\n")
