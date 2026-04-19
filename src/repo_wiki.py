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
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from dedup_store import DedupStore

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


# Phase 3: map legacy on-disk ``source_type`` values to the Phase 3 YAML
# frontmatter ``source_phase`` vocabulary. Anything unrecognised becomes
# ``legacy-migrated`` so frontmatter stays introspectable without the
# full legacy value bleeding through.
_SOURCE_TYPE_TO_PHASE: dict[str, str] = {
    "plan": "plan",
    "review": "review",
    "implement": "implement",
    "synthesis": "synthesis",
    "compiled": "synthesis",
}

_SLUG_STRIP_RE = re.compile(r"[^a-z0-9]+")
# Any filename whose first hyphen-separated segment is all digits counts as
# a numbered entry.  Matching a broader shape than "{id}-issue-..." prevents
# duplicate IDs when a synthesis entry (no issue tag) or hand-edited file
# lands in the same directory.
_ENTRY_ID_RE = re.compile(r"^(\d+)-")


def _slugify(title: str, *, max_len: int = 50) -> str:
    """Filesystem-safe slug for an entry title."""
    slug = _SLUG_STRIP_RE.sub("-", title.lower()).strip("-")
    return slug[:max_len] or "untitled"


def _next_entry_id(topic_dir: Path) -> int:
    """Next monotonic id within a topic directory.

    Scans any filename starting with ``{digits}-`` and returns ``max + 1``,
    starting at 1 when empty.  IDs are scoped per topic so
    ``patterns/0001`` and ``gotchas/0001`` coexist.  The broader regex
    (vs strictly ``{id}-issue-``) guarantees that synthesis entries or
    manually-created numbered files don't cause ID collisions.
    """
    if not topic_dir.is_dir():
        return 1
    ids: list[int] = []
    for p in topic_dir.glob("*.md"):
        m = _ENTRY_ID_RE.match(p.name)
        if m:
            ids.append(int(m.group(1)))
    return max(ids) + 1 if ids else 1


def _sanitize_body_for_frontmatter(content: str) -> str:
    """Prevent a leading ``---`` in body content from being parsed as a
    second YAML document.

    If content begins with a line that is exactly ``---`` (or whitespace
    then ``---``), prepend a zero-width safeguard so downstream YAML
    parsers stop at the frontmatter block.  Horizontal rules in the
    middle of content are unaffected.
    """
    if content.lstrip().startswith("---"):
        return "<!-- -->\n" + content
    return content


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
    entries_marked_stale: int = 0
    orphans_pruned: int = 0
    index_rebuilt: bool = False


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
        self._dedup_stores: dict[str, object] = {}

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

    def active_lint(
        self,
        repo_slug: str,
        closed_issues: set[int] | None = None,
    ) -> LintResult:
        """Run an active lint pass that fixes problems.

        Unlike ``lint()``, this method modifies the wiki:
        - Marks entries as stale if their source issue is in *closed_issues*
        - Prunes entries older than 90 days that are already marked stale
        - Removes orphan entries (not in index) by rebuilding from source
        - Rebuilds the index after any modifications

        Returns the same ``LintResult`` with counts of actions taken.
        """
        repo_dir = self._repo_dir(repo_slug)
        result = LintResult()

        if not repo_dir.exists():
            return result

        closed = closed_issues or set()
        any_modified = False
        now = datetime.now(UTC)
        _STALE_PRUNE_DAYS = 90

        for topic_name in DEFAULT_TOPICS:
            topic_path = repo_dir / f"{topic_name}.md"
            entries = self._load_topic_entries(topic_path)
            if not entries:
                result.empty_topics.append(topic_name)
                continue

            original_count = len(entries)
            topic_modified = False
            new_entries: list[WikiEntry] = []

            for entry in entries:
                result.total_entries += 1

                # Mark stale if source issue is closed
                should_mark_stale = (
                    not entry.stale
                    and entry.source_issue is not None
                    and entry.source_issue in closed
                )
                if should_mark_stale:
                    current = entry.model_copy(
                        update={"stale": True, "updated_at": now.isoformat()}
                    )
                    result.entries_marked_stale += 1
                    topic_modified = True
                else:
                    current = entry

                if current.stale:
                    result.stale_entries += 1
                    # Prune stale entries older than threshold
                    try:
                        created = datetime.fromisoformat(current.created_at)
                        age_days = (now - created).days
                    except (ValueError, TypeError):
                        age_days = 0
                    if age_days > _STALE_PRUNE_DAYS:
                        result.orphans_pruned += 1
                        topic_modified = True
                        continue  # skip — don't keep this entry

                new_entries.append(current)

            if len(new_entries) != original_count:
                topic_modified = True

            if topic_modified:
                self._write_topic_page(topic_path, topic_name, new_entries)
                any_modified = True

        if any_modified:
            self._rebuild_index(repo_slug)
            result.index_rebuilt = True

        # Update last_lint timestamp in index
        index = self._load_index(repo_slug)
        if index is not None:
            index.last_lint = now.isoformat()
            index_path = repo_dir / "index.json"
            index_path.write_text(index.model_dump_json(indent=2))

        self._append_log(repo_slug, "active_lint", result.model_dump())
        return result

    def list_repos(self) -> list[str]:
        """Return slugs for all repos with wikis.

        Accepts either the legacy ``index.json`` (topic-level layout) or the
        new ``index.md`` (per-entry layout, see docs/git-backed-wiki-design.md
        Phase 2). During the migration window both coexist; after migration
        only ``index.md`` remains.

        **WARNING (Phase 2 transition):** Other methods on ``RepoWikiStore``
        (``ingest``, ``query``, ``lint``, ``active_lint``, ``_ensure_repo_dir``,
        ``_rebuild_index``, ``_load_topic_entries``) still hardcode the
        legacy topic-level layout (``{topic}.md`` files + ``index.json``).
        Pointing a live ``RepoWikiStore`` at a new-layout directory will
        corrupt it: ``_ensure_repo_dir`` seeds topic ``.md`` files on top of
        the new per-entry subdirectories.  Phase 3 refactors those methods.
        Until then, the production runtime keeps pointing at the legacy
        ``.hydraflow/repo_wiki/`` path; the tracked ``repo_wiki/`` is
        populated by the migration script but not yet read at runtime.
        """
        if not self._wiki_root.exists():
            return []
        repos: list[str] = []
        for owner_dir in sorted(self._wiki_root.iterdir()):
            if not owner_dir.is_dir():
                continue
            for repo_dir in sorted(owner_dir.iterdir()):
                if not repo_dir.is_dir():
                    continue
                has_legacy = (repo_dir / "index.json").exists()
                has_new = (repo_dir / "index.md").exists()
                if has_legacy or has_new:
                    repos.append(f"{owner_dir.name}/{repo_dir.name}")
        return repos

    # -- dedup tracking ----------------------------------------------------

    def _get_dedup(self, repo_slug: str) -> DedupStore:
        """Return the ingest dedup store for a repo, creating lazily."""
        from dedup_store import DedupStore  # noqa: PLC0415

        if repo_slug not in self._dedup_stores:
            repo_dir = self._repo_dir(repo_slug)
            self._dedup_stores[repo_slug] = DedupStore(
                f"wiki_ingest:{repo_slug}",
                repo_dir / "ingest_dedup.json",
            )
        return self._dedup_stores[repo_slug]  # type: ignore[return-value]

    def is_ingested(self, repo_slug: str, issue_number: int, source_type: str) -> bool:
        """Check if this (issue, source_type) has already been ingested."""
        key = f"{issue_number}:{source_type}"
        return key in self._get_dedup(repo_slug).get()

    def mark_ingested(
        self, repo_slug: str, issue_number: int, source_type: str
    ) -> None:
        """Record that this (issue, source_type) has been ingested."""
        key = f"{issue_number}:{source_type}"
        self._get_dedup(repo_slug).add(key)

    # -- Phase 3: per-entry write API --------------------------------------

    def write_entry(
        self,
        repo_slug: str,
        entry: WikiEntry,
        *,
        topic: str,
    ) -> Path:
        """Write one per-entry markdown file with YAML frontmatter.

        Implements the Phase 3 write path (see
        docs/git-backed-wiki-design.md). The file lands at
        ``{wiki_root}/{repo_slug}/{topic}/{id:04d}-issue-{N}-{slug}.md``
        with an id scoped per (repo, topic) — scanning existing files in
        the topic directory for the next integer.

        ``source_type`` on the entry maps to ``source_phase`` in the
        frontmatter: ``plan``/``review`` pass through, ``compiled``
        becomes ``synthesis``, anything else becomes ``legacy-migrated``.

        Callers must provide ``topic`` explicitly — classification is
        the caller's responsibility, not the store's.

        Raises:
            FileExistsError: If the computed path collides with an
                existing file (same id + slug + issue).  The exclusive
                open prevents silent overwrite of prior entries.
        """
        repo_dir = self._repo_dir(repo_slug)
        topic_dir = repo_dir / topic
        topic_dir.mkdir(parents=True, exist_ok=True)

        next_id = _next_entry_id(topic_dir)
        issue_tag = (
            str(entry.source_issue) if entry.source_issue is not None else "unknown"
        )
        slug = _slugify(entry.title)
        filename = f"{next_id:04d}-issue-{issue_tag}-{slug}.md"
        path = topic_dir / filename

        source_phase = _SOURCE_TYPE_TO_PHASE.get(entry.source_type, "legacy-migrated")
        status = "stale" if entry.stale else "active"
        safe_content = _sanitize_body_for_frontmatter(entry.content)

        body = "\n".join(
            [
                "---",
                f"id: {next_id:04d}",
                f"topic: {topic}",
                f"source_issue: {issue_tag}",
                f"source_phase: {source_phase}",
                f"created_at: {entry.created_at}",
                f"status: {status}",
                "---",
                "",
                f"# {entry.title}",
                "",
                safe_content,
                "",
            ]
        )
        # Exclusive open (`x`) prevents silent overwrite if the same id +
        # slug + issue collide; surfaces the collision loudly so callers
        # can handle it (e.g. by rolling back prior writes in a batch).
        with path.open("x", encoding="utf-8") as f:
            f.write(body)
        return path

    def append_log(
        self,
        repo_slug: str,
        issue_number: int,
        record: dict[str, Any],
    ) -> Path:
        """Append a JSON line to the per-issue audit log.

        Records are partitioned per-issue so concurrent issue PRs never
        append to the same file on merge. The record is stamped with
        ``issue_number`` so downstream consumers (console, migrations)
        always have it.

        Uses ``file_util.append_jsonl`` under a ``file_lock`` so
        concurrent in-process writers (e.g. overlapping plan / review
        ingests for the same issue) get atomic appends + fsync
        durability — matching the rest of the codebase's crash-safe
        JSONL pattern.
        """
        from file_util import append_jsonl, file_lock  # noqa: PLC0415

        log_dir = self._repo_dir(repo_slug) / "log"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"{issue_number}.jsonl"

        payload = dict(record)
        payload.setdefault("issue_number", issue_number)
        with file_lock(log_file):
            append_jsonl(log_file, json.dumps(payload))
        return log_file

    def commit_pending_entries(
        self,
        *,
        worktree_path: Path,
        phase: str,
        issue_number: int,
        path_prefix: str = "repo_wiki",
    ) -> None:
        """Stage and commit new per-entry files under ``{path_prefix}/`` in
        the given worktree.

        Uses targeted ``git add {path_prefix}/`` — never ``git add -A`` —
        so unrelated changes in the worktree are not swept into the wiki
        commit. When there is nothing to commit (no changes under
        ``{path_prefix}/``), the method is a no-op and does not produce
        an empty commit.

        ``path_prefix`` defaults to ``"repo_wiki"`` but callers that
        respect ``HydraFlowConfig.repo_wiki_path`` (e.g. phase runners)
        should pass that value so operators who override the config take
        effect.

        The commit message is ``wiki: ingest {phase} for #{issue_number}``.
        """
        import subprocess  # noqa: PLC0415 — isolated here, not a module-level dep

        # Targeted status check: only look at the configured prefix.
        status = subprocess.run(
            [
                "git",
                "-C",
                str(worktree_path),
                "status",
                "--porcelain",
                path_prefix,
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        if not status:
            return

        subprocess.run(
            ["git", "-C", str(worktree_path), "add", path_prefix],
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(worktree_path),
                "-c",
                "user.email=hydraflow@noreply",
                "-c",
                "user.name=HydraFlow",
                "commit",
                "-m",
                f"wiki: ingest {phase} for #{issue_number}",
            ],
            check=True,
        )

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
