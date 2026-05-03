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
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field, model_validator
from ulid import ULID

from staleness import evaluate as evaluate_staleness

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


_TOPIC_KEYWORDS: dict[str, list[str]] = {
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


def classify_topic(entry: WikiEntry) -> str:
    """Classify a ``WikiEntry`` into a topic based on title/content keywords.

    Public module-level helper so phase runners can classify compiler-
    produced entries without poking at private store methods.  Defaults
    to ``"patterns"`` when no topic-specific keywords match.
    """
    text = f"{entry.title} {entry.content}".lower()
    best_topic = "patterns"
    best_score = 0
    for topic, keywords in _TOPIC_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text)
        if score > best_score:
            best_score = score
            best_topic = topic
    return best_topic


_SOURCE_FOOTER_RE = re.compile(r"^_Source:[^\n]*_\s*$", re.MULTILINE)


def _strip_prose_chrome(body: str) -> str:
    """Strip the optional ``_Source: ..._`` footer and surrounding blank
    lines from a parsed entry body, leaving the prose content.

    Used by ``_load_topic_entries`` to reconstruct ``WikiEntry.content``
    from the prose section above each ``json:entry`` metadata block.
    """
    cleaned = _SOURCE_FOOTER_RE.sub("", body)
    return cleaned.strip()


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


_TRACKED_TOPICS: tuple[str, ...] = (
    "architecture",
    "patterns",
    "gotchas",
    "testing",
    "dependencies",
)
_STALE_PRUNE_DAYS = 90


def _split_tracked_entry(text: str) -> tuple[dict[str, str], str, str]:
    """Split a tracked per-entry markdown file into frontmatter + body.

    Returns ``(fields, raw_frontmatter_block, body)`` where ``fields`` is
    a forgiving ``key: value`` parse of the frontmatter.  Files without
    a frontmatter block return ``({}, "", text)``.
    """
    if not text.startswith("---\n"):
        return {}, "", text
    try:
        end = text.index("\n---\n", 4)
    except ValueError:
        return {}, "", text
    block = text[4:end]
    body = text[end + len("\n---\n") :]
    fields: dict[str, str] = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields, block, body


def _update_tracked_entry_status(
    text: str, *, status: str, stale_reason: str | None = None
) -> str | None:
    """Rewrite the ``status:`` frontmatter line; add ``stale_reason`` when
    provided.  Returns the new file text, or ``None`` if the file has no
    frontmatter block (caller should skip).
    """
    fields, _block, body = _split_tracked_entry(text)
    if not fields:
        return None

    fields["status"] = status
    if stale_reason is not None:
        fields["stale_reason"] = stale_reason
    # Drop keys with empty values that pydantic would reject; keep order
    # stable enough for readable diffs.
    rebuilt_lines = [f"{k}: {v}" for k, v in fields.items()]
    return "---\n" + "\n".join(rebuilt_lines) + "\n---\n" + body


def _tracked_entry_age_days(fields: dict[str, str], now: datetime) -> int:
    created = fields.get("created_at") or ""
    try:
        ts = datetime.fromisoformat(created)
    except (ValueError, TypeError):
        return 0
    return max(0, (now - ts).days)


def _load_tracked_active_entries(topic_dir: Path) -> list[dict[str, Any]]:
    """Return ``[{id, title, body, source_issue, source_phase, created_at,
    path}]`` for every ``status: active`` entry in ``topic_dir``.

    Used by ``WikiCompiler.compile_topic_tracked`` to build the LLM
    prompt and to remember which files to mark superseded after the
    synthesis output lands.
    """
    if not topic_dir.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(topic_dir.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        fields, _block, body = _split_tracked_entry(text)
        if not fields or fields.get("status", "active") != "active":
            continue
        title = body.lstrip().split("\n", 1)[0].lstrip("# ").strip() or path.stem
        out.append(
            {
                "id": fields.get("id", ""),
                "title": title,
                "body": body.strip(),
                "source_issue": fields.get("source_issue", ""),
                "source_phase": fields.get("source_phase", ""),
                "created_at": fields.get("created_at", ""),
                "corroborations": fields.get("corroborations", "1"),
                "path": str(path),
            }
        )
    return out


def _write_tracked_synthesis_entry(
    topic_dir: Path,
    *,
    entry: WikiEntry,
    topic: str,
    supersedes: list[str],
) -> Path:
    """Write a compiler-synthesized per-entry file with
    ``source_phase: synthesis`` and a ``supersedes`` list in frontmatter.

    The filename embeds ``issue-synthesis`` (not ``issue-{N}``) so
    synthesis outputs are distinguishable from ingest entries at a
    glance.  Returns the written path.
    """
    topic_dir.mkdir(parents=True, exist_ok=True)
    next_id = _next_entry_id(topic_dir)
    slug = _slugify(entry.title)
    if slug == "untitled":
        slug = "synthesis"
    filename = f"{next_id:04d}-issue-synthesis-{slug}.md"
    path = topic_dir / filename

    now = datetime.now(UTC).isoformat()
    safe_content = _sanitize_body_for_frontmatter(entry.content)
    lines = [
        "---",
        f"id: {next_id:04d}",
        f"topic: {topic}",
        "source_issue: synthesis",
        "source_phase: synthesis",
        f"created_at: {now}",
        "status: active",
        f"corroborations: {entry.corroborations}",
    ]
    if supersedes:
        lines.append("supersedes: " + ",".join(supersedes))
    lines.append("---")
    lines.append("")
    lines.append(f"# {entry.title}")
    lines.append("")
    lines.append(safe_content)
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _mark_tracked_entry_superseded(entry_path: Path, *, superseded_by: str) -> None:
    """Flip ``status`` → ``superseded`` and add ``superseded_by`` in the
    frontmatter.  No-op when the file has no frontmatter block.

    Uses ``file_util.atomic_write`` so an interrupted rewrite can't
    leave the file as a half-frontmatter block that ``_split_tracked_entry``
    would then silently drop (which would cost us both the
    ``superseded_by`` pointer and the entry body).
    """
    from file_util import atomic_write  # noqa: PLC0415

    try:
        text = entry_path.read_text(encoding="utf-8")
    except OSError:
        return
    fields, _block, body = _split_tracked_entry(text)
    if not fields:
        return
    fields["status"] = "superseded"
    fields["superseded_by"] = superseded_by
    rebuilt = (
        "---\n" + "\n".join(f"{k}: {v}" for k, v in fields.items()) + "\n---\n" + body
    )
    try:
        atomic_write(entry_path, rebuilt)
    except OSError:
        logger.warning(
            "mark_tracked_entry_superseded: failed to rewrite %s", entry_path
        )


def increment_corroboration(entry_path: Path, *, by: int = 1) -> None:
    """Atomically bump the ``corroborations`` counter in a tracked-layout
    entry file. No-op when the file is missing or has no frontmatter
    block. A missing ``corroborations`` field is treated as 1 and then
    incremented.
    """
    from file_util import atomic_write  # noqa: PLC0415

    if by < 1:
        return
    try:
        text = entry_path.read_text(encoding="utf-8")
    except OSError:
        return
    fields, _block, body = _split_tracked_entry(text)
    if not fields:
        return
    current_raw = fields.get("corroborations", "1")
    try:
        current = max(1, int(str(current_raw).strip()))
    except (TypeError, ValueError):
        current = 1
    fields["corroborations"] = str(current + by)
    rebuilt = (
        "---\n" + "\n".join(f"{k}: {v}" for k, v in fields.items()) + "\n---\n" + body
    )
    try:
        atomic_write(entry_path, rebuilt)
    except OSError:
        logger.warning("increment_corroboration: failed to rewrite %s", entry_path)


def active_lint_tracked(
    tracked_root: Path,
    repo_slug: str,
    closed_issues: set[int] | None = None,
) -> LintResult:
    """Tracked-layout counterpart of ``RepoWikiStore.active_lint``.

    Scans per-entry files under ``{tracked_root}/{repo_slug}/{topic}/*.md``
    and mutates them in place.  Matches the legacy ``active_lint`` semantics:
    the 90-day prune window is measured from ``created_at``, not from
    stale-flag-timestamp — so an old active entry whose issue just closed
    can be flipped stale and pruned in the same pass.  This is intentional:
    ``created_at`` is a proxy for "still relevant," and a 120-day-old entry
    whose source issue has closed is typically already superseded by a
    ``WikiCompiler`` synthesis entry.

    Actions:

    - Entries whose frontmatter ``source_issue`` is an int in
      *closed_issues* and current ``status == "active"`` are rewritten
      with ``status: stale`` and a ``stale_reason`` pointing at the
      closed issue.
    - Stale entries older than 90 days are deleted outright — their
      source information is recoverable from git history.

    Writes happen in the tracked dir so the subsequent
    ``RepoWikiLoop._maybe_open_maintenance_pr`` tick will pick them up as
    uncommitted diffs and open a ``chore(wiki): maintenance`` PR.

    Returns a ``LintResult`` with the counts the loop already reports.
    """
    result = LintResult()
    repo_dir = tracked_root / repo_slug
    if not repo_dir.is_dir():
        return result

    closed = closed_issues or set()
    now = datetime.now(UTC)

    for topic_name in _TRACKED_TOPICS:
        topic_dir = repo_dir / topic_name
        if not topic_dir.is_dir():
            result.empty_topics.append(topic_name)
            continue

        files = sorted(topic_dir.glob("*.md"))
        if not files:
            result.empty_topics.append(topic_name)
            continue

        for entry_path in files:
            try:
                text = entry_path.read_text(encoding="utf-8")
            except OSError:
                continue

            fields, _block, _body = _split_tracked_entry(text)
            if not fields:
                continue

            result.total_entries += 1
            status = fields.get("status", "active")
            try:
                source_issue: int | None = int(fields["source_issue"])
            except (KeyError, ValueError):
                source_issue = None

            if (
                status == "active"
                and source_issue is not None
                and source_issue in closed
            ):
                updated = _update_tracked_entry_status(
                    text,
                    status="stale",
                    stale_reason=f"source issue #{source_issue} closed",
                )
                if updated is not None:
                    # Atomic rewrite: an interrupted write would leave a
                    # half-frontmatter block that _split_tracked_entry
                    # silently drops, losing the entry entirely.
                    from file_util import atomic_write  # noqa: PLC0415

                    atomic_write(entry_path, updated)
                    result.entries_marked_stale += 1
                    status = "stale"

            if status == "stale":
                result.stale_entries += 1
                if _tracked_entry_age_days(fields, now) > _STALE_PRUNE_DAYS:
                    try:
                        entry_path.unlink()
                        result.orphans_pruned += 1
                    except OSError:
                        logger.warning(
                            "active_lint_tracked: failed to prune %s",
                            entry_path,
                        )

    return result


class WikiEntry(BaseModel):
    """A single knowledge entry within a topic page."""

    id: str = Field(
        default_factory=lambda: str(ULID()),
        description="Stable ULID used for supersedes references",
    )
    title: str = Field(description="Short summary of the insight")
    content: str = Field(description="Full explanation")
    topic: str | None = Field(
        default=None,
        description="Which topic page this entry lives under (architecture/patterns/gotchas/testing/dependencies/harness)",
    )
    source_type: str = Field(
        description="Where the knowledge came from: plan, implement, review, hitl, reflection, librarian, manual"
    )
    source_issue: int | None = Field(
        default=None, description="GitHub issue number, if applicable"
    )
    source_repo: str | None = Field(
        default=None,
        description="owner/repo slug, or 'global' for tribal entries",
    )
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    valid_from: str | None = Field(
        default=None,
        description="ISO8601; defaults to created_at if unset",
    )
    valid_to: str | None = Field(
        default=None,
        description="ISO8601 absolute date OR null=indefinite. Durations resolved at ingest.",
    )
    superseded_by: str | None = Field(
        default=None, description="id of newer entry that replaces this one"
    )
    superseded_reason: str | None = Field(
        default=None,
        description="Freeform reason paired with superseded_by",
    )
    confidence: Literal["high", "medium", "low"] = Field(default="medium")
    stale: bool = Field(
        default=False,
        description="Legacy marker; see superseded_by for canonical staleness",
    )
    corroborations: int = Field(
        default=1,
        ge=1,
        description=(
            "How many independent sources have re-asserted this principle. "
            "Entries loaded without this field default to 1. Incremented by "
            "the ingest-path dedup/corroboration logic in wiki_compiler."
        ),
    )

    @model_validator(mode="after")
    def _default_valid_from(self) -> WikiEntry:
        if self.valid_from is None:
            self.valid_from = self.created_at
        return self


def annotate_entries_with_temporal_tags(
    entries: list[WikiEntry],
    *,
    now: datetime,
) -> list[tuple[WikiEntry, str]]:
    """Tag each entry with a short human-readable stability string.

    Tags:
    - ``"recently added"`` — age < 30 days
    - ``"stable for N months"`` — 30 days ≤ age < 365 days
    - ``"stable for N year(s)"`` — age ≥ 365 days
    - ``"age unknown"`` — ``created_at`` unparseable

    When ``corroborations`` > 1, a ``(+N)`` suffix is appended so the
    planner/reviewer can see how independently-re-discovered the claim
    is at a glance. Pure function — no I/O, no LLM calls, safe to run
    on every wiki read.
    """
    annotated: list[tuple[WikiEntry, str]] = []
    for entry in entries:
        try:
            created = datetime.fromisoformat(entry.created_at)
        except (TypeError, ValueError):
            annotated.append((entry, "age unknown"))
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        age_days = (now - created).days
        if age_days < 30:
            base = "recently added"
        elif age_days < 365:
            months = max(1, age_days // 30)
            base = f"stable for {months} months"
        else:
            years = age_days // 365
            suffix = "year" if years == 1 else "years"
            base = f"stable for {years} {suffix}"
        if entry.corroborations > 1:
            base = f"{base} (+{entry.corroborations})"
        annotated.append((entry, base))
    return annotated


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
    review_candidates_flagged: int = 0  # stale + age > 90d (no longer pruned)
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

    Directory layout for the **self-repo** (``self_slug`` matches an
    ingested slug)::

        {wiki_root}/
          index.json       — structured index (WikiIndex)
          index.md         — human-readable index
          log.jsonl        — append-only operation log
          architecture.md  — topic page
          patterns.md      — topic page
          gotchas.md       — topic page
          testing.md       — topic page
          dependencies.md  — topic page

    For **other managed repos** the slug is nested under wiki_root::

        {wiki_root}/{owner}/{repo}/<topics>...

    The self-repo flattening lets the wiki live at ``docs/wiki/`` and be
    git-tracked alongside the code it documents; managed-repo wikis stay
    in ``.hydraflow/repo_wiki/`` (runtime cache) until each managed repo
    sets its own ``docs/wiki/``.
    """

    def __init__(
        self,
        wiki_root: Path,
        tracked_root: Path | None = None,
        self_slug: str | None = None,
    ) -> None:
        """Initialise a repo-wiki store.

        ``wiki_root`` is the topic-page location. ``tracked_root``, when
        provided, is the Phase 3 per-entry tracked location. When both
        are set and the tracked layout has entries for a repo/topic,
        reads prefer the tracked layout; legacy is the fallback.

        ``self_slug`` (e.g. ``"T-rav/hydraflow"``) marks which slug is
        the running repo's own wiki. The self-repo's pages live directly
        under ``wiki_root`` (no owner/repo nesting); every other slug
        nests under ``wiki_root/owner/repo``.
        """
        self._wiki_root = wiki_root
        self._tracked_root = tracked_root
        self._self_slug = self_slug
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

        Read-path priority: tracked layout (Phase 3, per-entry files
        under ``{tracked_root}/{owner}/{repo}/{topic}/*.md``) wins when
        it has entries.  Legacy topic-page layout
        (``{wiki_root}/{owner}/{repo}/{topic}.md``) is the fallback.
        """
        repo_dir = self._repo_dir(repo_slug)
        index = self._load_index(repo_slug) if repo_dir.exists() else None

        # Determine the universe of topics to scan. Tracked layout may
        # have topics the legacy index never knew about, so we union.
        tracked_topics = self._list_tracked_topics(repo_slug)
        legacy_topics = set(index.topics.keys()) if index is not None else set()
        all_topics = tracked_topics | legacy_topics
        if not all_topics:
            return ""

        parts: list[str] = [f"# Repo Wiki: {repo_slug}\n"]
        if index is not None:
            parts.append(
                f"__{index.total_entries} entries across {len(index.topics)} topics__\n"
            )

        target_topics = set(topics) if topics else all_topics

        for topic_name in sorted(target_topics):
            if topic_name not in all_topics:
                continue

            # Prefer tracked layout when present.
            tracked_dir = self._tracked_topic_dir(repo_slug, topic_name)
            if tracked_dir is not None:
                entries = self._load_tracked_topic_entries(tracked_dir)
            else:
                topic_path = repo_dir / f"{topic_name}.md"
                if not topic_path.exists():
                    continue
                entries = self._load_topic_entries(topic_path)

            if not entries:
                continue

            # Staleness filtering — only inject current entries into prompts
            now = datetime.now(UTC)
            entries = [
                e for e in entries if evaluate_staleness(e, now=now) == "current"
            ]

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

    def query_with_tags(
        self,
        repo_slug: str,
        keywords: list[str] | None = None,
        topics: list[str] | None = None,
        max_chars: int = 15_000,
    ) -> tuple[str, dict[str, str]]:
        """Like ``query`` but also returns a ``{title: temporal_tag}``
        map for the tracked-layout entries.

        Callers that want tagged output inline can weave the tags in at
        render time (see ``BaseRunner._inject_repo_wiki``). Returns an
        empty tag map when the store has no tracked_root or the repo
        has no tracked entries.
        """
        markdown = self.query(
            repo_slug, keywords=keywords, topics=topics, max_chars=max_chars
        )
        tags: dict[str, str] = {}
        if self._tracked_root is None:
            return markdown, tags
        now = datetime.now(UTC)
        for topic in self._list_tracked_topics(repo_slug):
            topic_dir = self._tracked_topic_dir(repo_slug, topic)
            if topic_dir is None or not topic_dir.is_dir():
                continue
            entries = self._load_tracked_topic_entries(topic_dir)
            for entry, tag in annotate_entries_with_temporal_tags(entries, now=now):
                tags[entry.title] = tag
        return markdown, tags

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
                    try:
                        created = datetime.fromisoformat(current.created_at)
                        age_days = (now - created).days
                    except (ValueError, TypeError):
                        age_days = 0
                    if age_days > _STALE_PRUNE_DAYS:
                        # Phase 1 change: flag as review candidate; do NOT prune.
                        # Staleness is now content-based (superseded_by), not time-based.
                        result.review_candidates_flagged += 1

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

    def mark_superseded(
        self,
        repo_slug: str,
        entry_id: str,
        *,
        superseded_by: str,
        reason: str,
    ) -> bool:
        """Set superseded_by/superseded_reason on an existing entry.

        Searches all topic pages for the entry by id. Returns True if the
        entry was found and updated; False otherwise. Does not delete or
        move the entry. Callers emit events.
        """
        repo_dir = self._repo_dir(repo_slug)
        if not repo_dir.exists():
            return False

        now = datetime.now(UTC).isoformat()
        for topic_name in DEFAULT_TOPICS:
            topic_path = repo_dir / f"{topic_name}.md"
            if not topic_path.exists():
                continue
            entries = self._load_topic_entries(topic_path)
            for i, e in enumerate(entries):
                if e.id == entry_id:
                    entries[i] = e.model_copy(
                        update={
                            "superseded_by": superseded_by,
                            "superseded_reason": reason,
                            "updated_at": now,
                        }
                    )
                    self._write_topic_page(topic_path, topic_name, entries)
                    self._append_log(
                        repo_slug,
                        "mark_superseded",
                        {"entry_id": entry_id, "superseded_by": superseded_by},
                    )
                    return True
        return False

    def list_repos(self) -> list[str]:
        """Return slugs for all repos with wikis.

        Accepts either the legacy ``index.json`` (topic-level layout) or the
        new ``index.md`` (per-entry layout, see docs/git-backed-wiki-design.md
        Phase 2). During the migration window both coexist; after migration
        only ``index.md`` remains.

        **WARNING (Phase 2 transition):** Other methods on ``RepoWikiStore``
        (``ingest``, ``query``, ``lint``, ``active_lint``, ``_ensure_repo_dir``,
        ``_rebuild_index``, ``_load_topic_entries``) target the topic-level
        layout (``{topic}.md`` files + ``index.json``). PR #8465 slimmed the
        on-disk format — each entry is now a ``## Title`` section with
        prose followed by a slim ``json:entry`` metadata block — but the
        layout shape (one ``.md`` per topic, central ``index.json``) is
        unchanged. Pointing a live ``RepoWikiStore`` at a new-layout
        per-entry-file directory will still corrupt it: ``_ensure_repo_dir``
        seeds topic ``.md`` files on top of the new per-entry subdirectories.
        Phase 3 refactors those methods. Until then, the production runtime
        keeps pointing at the legacy ``.hydraflow/repo_wiki/`` path; the
        tracked ``repo_wiki/`` is populated by the migration script but not
        yet read at runtime.
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
                f"corroborations: {entry.corroborations}",
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
        # Timeouts on every subprocess.run guard against thread-pool
        # exhaustion when this runs under ``asyncio.to_thread`` from
        # plan_phase / review_phase — same deadlock class as PR #8454.
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
            timeout=30,
        ).stdout.strip()
        if not status:
            return

        subprocess.run(
            ["git", "-C", str(worktree_path), "add", path_prefix],
            check=True,
            timeout=30,
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
            timeout=60,
        )

    # -- public API --------------------------------------------------------

    def repo_dir(self, repo_slug: str) -> Path:
        """Public: return the on-disk directory for a repo's wiki."""
        return self._repo_dir(repo_slug)

    def load_topic_entries(self, topic_path: Path) -> list[WikiEntry]:
        """Public: parse entries from a topic page on disk."""
        return self._load_topic_entries(topic_path)

    # -- internal ----------------------------------------------------------

    def _repo_dir(self, repo_slug: str) -> Path:
        """Return the wiki directory for a repo slug (owner/repo).

        Self-repo (``repo_slug == self._self_slug``) lives flat under
        ``wiki_root`` so it can sit at ``docs/wiki/`` alongside the
        code. Other slugs nest under ``wiki_root/owner/repo``.
        """
        if self._self_slug and repo_slug == self._self_slug:
            return self._wiki_root
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
        """Backward-compat: classify via the module-level `classify_topic`."""
        return classify_topic(entry)

    def _list_tracked_topics(self, repo_slug: str) -> set[str]:
        """Return topic names that have tracked-layout entries for a repo."""
        if self._tracked_root is None:
            return set()
        repo_dir = self._tracked_root / repo_slug
        if not repo_dir.is_dir():
            return set()
        return {
            child.name
            for child in repo_dir.iterdir()
            if child.is_dir() and any(child.glob("*.md"))
        }

    def _tracked_topic_dir(self, repo_slug: str, topic: str) -> Path | None:
        """Return the tracked per-entry topic directory if configured + populated.

        Phase 3 layout: ``{tracked_root}/{owner}/{repo}/{topic}/*.md``.
        Returns ``None`` when no tracked_root was provided or the dir is
        empty/missing — callers then fall back to the legacy topic-page path.
        """
        if self._tracked_root is None:
            return None
        topic_dir = self._tracked_root / repo_slug / topic
        if not topic_dir.is_dir():
            return None
        if not any(topic_dir.glob("*.md")):
            return None
        return topic_dir

    def _load_tracked_topic_entries(self, topic_dir: Path) -> list[WikiEntry]:
        """Parse per-entry tracked-format markdown files into WikiEntry objects.

        Each file has YAML frontmatter + markdown body.  Only ``active`` entries
        are returned; ``stale`` / ``superseded`` entries are filtered out since
        callers use this for prompt injection.
        """
        return [
            entry for entry, _ in self._load_tracked_topic_entries_with_paths(topic_dir)
        ]

    def _load_tracked_topic_entries_with_paths(
        self, topic_dir: Path
    ) -> list[tuple[WikiEntry, Path]]:
        """Like ``_load_tracked_topic_entries`` but preserves each entry's
        source file path. Used by the ingest-time corroboration hook:
        ``CorroborationDecision.canonical_path`` is populated from these
        tuples so the caller can atomically bump the counter without a
        second directory walk.
        """
        pairs: list[tuple[WikiEntry, Path]] = []
        for raw in _load_tracked_active_entries(topic_dir):
            try:
                corroborations_raw = raw.get("corroborations", "1")
                try:
                    corroborations = max(1, int(str(corroborations_raw).strip()))
                except (TypeError, ValueError):
                    corroborations = 1
                entry = WikiEntry(
                    id=raw.get("id") or "",
                    title=raw.get("title") or "(untitled)",
                    content=raw.get("body") or "",
                    topic=topic_dir.name,
                    source_type=raw.get("source_phase") or "unknown",
                    source_issue=(
                        int(raw["source_issue"]) if raw.get("source_issue") else None
                    ),
                    created_at=raw.get("created_at") or datetime.now(UTC).isoformat(),
                    corroborations=corroborations,
                )
                path_raw = raw.get("path")
                path = Path(path_raw) if path_raw else topic_dir / "unknown.md"
                pairs.append((entry, path))
            except (ValueError, TypeError):
                logger.warning("Skipping malformed tracked entry under %s", topic_dir)
        return pairs

    def _load_topic_entries(self, topic_path: Path) -> list[WikiEntry]:
        """Parse a topic markdown file back into entries.

        Schema-slim layout: each entry is rendered as a `## Title`
        section followed by prose, an optional `_Source: #N (kind)_`
        footer, and a `json:entry` code block carrying metadata WITHOUT
        the `content` field. The reader reconstructs ``WikiEntry.content``
        from the prose section above the metadata block.

        Legacy entries that still embed ``content`` in the JSON continue
        to load — the prose section overrides if present, otherwise the
        JSON-embedded copy is used.

        Parsing strategy: split the file at line-start ``## `` boundaries
        into entry sections, then within each section locate the LAST
        ``json:entry`` code block as the metadata block. This is robust
        against (a) prose containing embedded ```` ```json:entry ```` fences
        (e.g., wiki entries about the wiki schema itself), and (b) free-form
        ``## Heading`` sections without a metadata block (silently skipped
        rather than eating the next entry).
        """
        if not topic_path.exists():
            return []

        text = topic_path.read_text()
        # Split at line-start "## " — first chunk is the file preamble.
        sections = re.split(r"(?:^|\n)## ", text)
        entries: list[WikiEntry] = []

        for section in sections[1:]:
            title, _, body = section.partition("\n")
            title = title.strip()
            if not title:
                continue
            meta_matches = list(
                re.finditer(r"```json:entry\n(.+?)\n```", body, re.DOTALL),
            )
            if not meta_matches:
                continue  # free-form section without metadata — skip silently
            meta_match = meta_matches[-1]  # always the LAST block
            try:
                metadata = json.loads(meta_match.group(1))
                prose = _strip_prose_chrome(body[: meta_match.start()])
                if prose:
                    metadata["content"] = prose
                elif "content" not in metadata:
                    metadata["content"] = ""
                if not metadata.get("title"):
                    metadata["title"] = title
                entries.append(WikiEntry.model_validate(metadata))
            except Exception:  # noqa: BLE001
                logger.warning("Skipping malformed entry in %s", topic_path)

        return entries

    def _write_topic_page(
        self,
        topic_path: Path,
        topic_name: str,
        entries: list[WikiEntry],
    ) -> None:
        """Write a topic page with slim per-entry metadata blocks.

        The `content` field is stored only in the prose section (not
        duplicated inside the json:entry block) — see _load_topic_entries
        for the read-side contract.
        """
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
                slim = entry.model_dump_json(exclude={"content", "valid_from"})
                lines.append(f"\n```json:entry\n{slim}\n```\n")

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

        prior = self._load_index(repo_slug)
        index = WikiIndex(
            repo_slug=repo_slug,
            topics=topics,
            total_entries=total,
            last_updated=datetime.now(UTC).isoformat(),
            last_lint=prior.last_lint if prior is not None else None,
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
