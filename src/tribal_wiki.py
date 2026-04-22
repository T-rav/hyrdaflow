"""Tribal wiki — global cross-repo knowledge store.

Layout mirrors per-repo wiki (index.json + topic.md pages) but is not
namespaced by repo. All entries carry ``source_repo="global"``.

Entries are written only by the generalization pass (src/wiki_compiler.py)
when the same principle is observed in ≥2 per-repo wikis. Directly
modifying the tribal store from agent code is not a supported use case.

Loaded at every plan/implement/review phase alongside the target repo's
wiki — tribal rules apply regardless of which repo is being worked on.
"""

from __future__ import annotations

import logging
from pathlib import Path

from repo_wiki import IngestResult, LintResult, RepoWikiStore, WikiEntry

logger = logging.getLogger("hydraflow.tribal_wiki")

_TRIBAL_SLUG = "global"


class TribalWikiStore:
    """Thin wrapper over ``RepoWikiStore`` pinned to a single ``'global'`` slug.

    All ingests stamp ``source_repo='global'``. Reads and writes route through
    the underlying ``RepoWikiStore`` so staleness filtering, contradiction
    marking, and on-disk format stay consistent with per-repo wikis.
    """

    def __init__(self, tribal_root: Path) -> None:
        # Final on-disk layout: {tribal_root}/global/{topic}.md
        self._store = RepoWikiStore(tribal_root)

    def ingest(self, entries: list[WikiEntry]) -> IngestResult:
        stamped = [e.model_copy(update={"source_repo": _TRIBAL_SLUG}) for e in entries]
        return self._store.ingest(_TRIBAL_SLUG, stamped)

    def query(
        self,
        keywords: list[str] | None = None,
        topics: list[str] | None = None,
        max_chars: int = 15_000,
    ) -> str:
        return self._store.query(
            _TRIBAL_SLUG,
            keywords=keywords,
            topics=topics,
            max_chars=max_chars,
        )

    def repo_dir(self) -> Path:
        return self._store.repo_dir(_TRIBAL_SLUG)

    def load_topic_entries(self, topic_path: Path) -> list[WikiEntry]:
        return self._store.load_topic_entries(topic_path)

    def lint(self) -> LintResult:
        return self._store.lint(_TRIBAL_SLUG)

    def active_lint(self, closed_issues: set[int] | None = None) -> LintResult:
        return self._store.active_lint(_TRIBAL_SLUG, closed_issues=closed_issues)

    def mark_superseded(
        self,
        entry_id: str,
        *,
        superseded_by: str,
        reason: str,
    ) -> bool:
        return self._store.mark_superseded(
            _TRIBAL_SLUG,
            entry_id,
            superseded_by=superseded_by,
            reason=reason,
        )
