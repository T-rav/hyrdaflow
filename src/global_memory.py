"""Global memory store — cross-project knowledge with project-local overrides.

Layout under the global directory (default ``~/.hydraflow/global_memory/``):

    global_memory/
      ├── digest.md           # global knowledge digest
      ├── items/              # individual global memory items
      ├── item_scores.json    # global item scores (same format as project-local)
      └── outcomes.jsonl      # aggregated cross-project outcomes

Project-local overrides live in ``.hydraflow/memory/global_overrides.json``.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("hydraflow.global_memory")

_OVERRIDES_FILENAME = "global_overrides.json"
_PROMOTION_MIN_PROJECTS = 3
_PROMOTION_MIN_SCORE = 0.6
_OVERLAP_THRESHOLD = 0.7
_OVERRIDE_DETECT_MIN_APPEARANCES = 5
_OVERRIDE_DETECT_GLOBAL_MIN = 0.6
_OVERRIDE_DETECT_PROJECT_MAX = 0.3


class GlobalMemoryStore:
    """Manages cross-project knowledge in a shared global memory directory.

    The store is optional — callers should wrap all interactions in
    try/except so that missing or corrupt global memory never interrupts
    the main pipeline.
    """

    def __init__(self, global_dir: Path) -> None:
        self._dir = Path(global_dir)

    # ------------------------------------------------------------------
    # Digest helpers
    # ------------------------------------------------------------------

    def load_global_digest(self) -> str:
        """Load the global digest markdown.

        Returns an empty string when the file is missing or unreadable.
        """
        digest_path = self._dir / "digest.md"
        if not digest_path.is_file():
            return ""
        try:
            content = digest_path.read_text(encoding="utf-8")
        except OSError:
            logger.debug("Could not read global digest at %s", digest_path)
            return ""
        return content.strip()

    def get_combined_digest(self, local_digest: str, max_chars: int) -> str:
        """Combine global and local digests within *max_chars*.

        Strategy:
        - Local digest takes priority when truncation is required.
        - Global digest provides baseline context prepended before local.
        - The combined text is hard-capped at *max_chars*.
        """
        separator = "\n\n---\n\n"
        if max_chars <= len(separator):
            return local_digest[:max_chars]

        global_digest = self.load_global_digest()

        if not global_digest:
            return local_digest[:max_chars]
        if not local_digest:
            return global_digest[:max_chars]

        # Reserve space for local by allocating the remainder after a separator.
        local_budget = max_chars - len(separator)

        # When local fits, prepend as much global as the budget allows.
        if local_budget > 0 and len(local_digest) <= local_budget:
            remaining = local_budget - len(local_digest)
            global_portion = global_digest[:remaining] if remaining > 0 else ""
            combined = (
                (global_portion + separator + local_digest)
                if global_portion
                else local_digest
            )
            result = combined[:max_chars]
            logger.info(
                "Combined digest: global=%d chars + local=%d chars (max=%d)",
                len(global_digest),
                len(local_digest),
                max_chars,
            )
            return result

        # local is larger than budget (or separator leaves no room) — local alone wins.
        logger.info(
            "Combined digest: global=%d chars + local=%d chars (max=%d)",
            len(global_digest),
            len(local_digest),
            max_chars,
        )
        return local_digest[:max_chars]

    # ------------------------------------------------------------------
    # Override management
    # ------------------------------------------------------------------

    def get_overrides(self, project_slug: str) -> set[str]:
        """Return the set of global item IDs overridden by *project_slug*.

        Reads from the project's own ``global_overrides.json``.  The slug is
        used only to locate the correct overrides file via the project data
        directory; callers must pass in the resolved path themselves or use
        ``_overrides_path_for`` with a data root.
        """
        # When called without a data_root we have no project path to read from.
        # Callers that know the data_root should call _load_project_overrides directly.
        return self._load_project_overrides_by_slug(project_slug)

    def record_override(
        self, project_slug: str, global_item_id: str, reason: str
    ) -> None:
        """Record that *project_slug* overrides *global_item_id*.

        The override file is written to the project data directory resolved
        via ``_project_overrides_dir(project_slug)``.  Callers may need to
        pass an explicit path instead; prefer
        ``record_override_at(overrides_path, ...)`` for that.
        """
        overrides_path = self._project_overrides_dir(project_slug) / _OVERRIDES_FILENAME
        logger.info(
            "Recorded override for project %s: global item %s → local (reason: %s)",
            project_slug,
            global_item_id,
            reason[:60],
        )
        self.record_override_at(overrides_path, global_item_id, reason)

    def record_override_at(
        self, overrides_path: Path, global_item_id: str, reason: str
    ) -> None:
        """Write an override record to *overrides_path*.

        Creates the file and parent directories if necessary.
        """
        overrides_path.parent.mkdir(parents=True, exist_ok=True)
        existing = self._read_overrides_file(overrides_path)
        existing["overrides"][global_item_id] = {
            "reason": reason,
            "created_at": datetime.now(UTC).isoformat(),
        }
        overrides_path.write_text(
            json.dumps(existing, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def load_overrides_at(self, overrides_path: Path) -> set[str]:
        """Return the set of overridden global item IDs from *overrides_path*."""
        data = self._read_overrides_file(overrides_path)
        return set(data.get("overrides", {}).keys())

    # ------------------------------------------------------------------
    # Cross-project analysis
    # ------------------------------------------------------------------

    def find_promotion_candidates(
        self, project_stores: dict[str, Path]
    ) -> list[dict[str, Any]]:
        """Find local items that appear in 3+ projects with score >= 0.6.

        *project_stores* maps ``project_slug -> memory_dir`` (the directory
        that contains ``item_scores.json`` and ``items/``).

        Returns a list of candidate dicts with keys:
        - ``representative_text``: the learning text from the first project
        - ``project_slugs``: list of slugs where this item appears
        - ``avg_score``: average score across matching projects
        - ``item_ids``: dict mapping slug -> local item ID
        """
        # Gather all items from each project
        project_items: dict[str, list[tuple[int, str, float]]] = {}
        for slug, memory_dir in project_stores.items():
            items = self._load_project_items(memory_dir)
            if items:
                project_items[slug] = items

        if len(project_items) < _PROMOTION_MIN_PROJECTS:
            return []

        # Find groups of items with >70% keyword overlap across 3+ projects
        candidates: list[dict[str, Any]] = []
        processed_groups: list[set[str]] = []  # track keyword sets already promoted

        # Collect all items with score >= threshold
        qualified: list[tuple[str, int, str, float]] = []
        for slug, items in project_items.items():
            for item_id, text, score in items:
                if score >= _PROMOTION_MIN_SCORE:
                    qualified.append((slug, item_id, text, score))

        # Group by keyword overlap
        seen_indices: set[int] = set()
        for i, (slug_a, id_a, text_a, score_a) in enumerate(qualified):
            if i in seen_indices:
                continue
            keywords_a = _extract_keywords(text_a)
            group_slugs = [slug_a]
            group_ids: dict[str, int] = {slug_a: id_a}
            group_scores = [score_a]
            group_indices: list[int] = []  # indices in qualified that joined this group

            for j, (slug_b, id_b, text_b, score_b) in enumerate(qualified):
                if j <= i or j in seen_indices:
                    continue
                if slug_b in group_slugs:
                    continue  # only one item per project per group
                keywords_b = _extract_keywords(text_b)
                if _keyword_overlap(keywords_a, keywords_b) > _OVERLAP_THRESHOLD:
                    group_slugs.append(slug_b)
                    group_ids[slug_b] = id_b
                    group_scores.append(score_b)
                    group_indices.append(j)

            if len(group_slugs) < _PROMOTION_MIN_PROJECTS:
                continue

            # Avoid re-promoting the same concept
            group_kw = keywords_a
            already_covered = any(
                _keyword_overlap(group_kw, prev) > _OVERLAP_THRESHOLD
                for prev in processed_groups
            )
            if already_covered:
                continue

            avg_score = sum(group_scores) / len(group_scores)
            candidates.append(
                {
                    "representative_text": text_a,
                    "project_slugs": group_slugs,
                    "avg_score": avg_score,
                    "item_ids": group_ids,
                }
            )
            processed_groups.append(group_kw)
            # Only mark the specific indices selected into this group (not all
            # items from member slugs, which would over-suppress future groups).
            seen_indices.add(i)  # the seed item
            seen_indices.update(group_indices)  # the items that joined this group

        logger.info(
            "Found %d promotion candidates across %d projects",
            len(candidates),
            len(project_stores),
        )
        return candidates

    def detect_override_candidates(
        self, project_stores: dict[str, Path]
    ) -> list[dict[str, Any]]:
        """Find global items that score poorly on specific projects but well on others.

        A global item is flagged when:
        - Its global average score > 0.6 (i.e. it's broadly useful), AND
        - At least one project has score < 0.3 with >= 5 appearances.

        Returns a list of dicts with:
        - ``global_item_id``: the item ID in the global store
        - ``global_avg_score``: average score across all projects that have scored it
        - ``outlier_projects``: list of ``{slug, score, appearances}`` dicts
        """
        global_scores = self._load_global_scores()
        if not global_scores:
            return []

        # For each global item, look up scores in each project
        results: list[dict[str, Any]] = []
        for global_id, global_item in global_scores.items():
            global_avg: float = global_item.get("score", 0.0)
            if global_avg <= _OVERRIDE_DETECT_GLOBAL_MIN:
                continue

            outliers: list[dict[str, Any]] = []
            for slug, memory_dir in project_stores.items():
                project_scores = self._load_project_scores(memory_dir)
                # Match by string key (global IDs may be strings like "global-15")
                proj_item = project_scores.get(str(global_id)) or project_scores.get(
                    global_id
                )
                if proj_item is None:
                    continue
                proj_score: float = proj_item.get("score", 0.5)
                appearances: int = proj_item.get("appearances", 0)
                if (
                    proj_score < _OVERRIDE_DETECT_PROJECT_MAX
                    and appearances >= _OVERRIDE_DETECT_MIN_APPEARANCES
                ):
                    outliers.append(
                        {
                            "slug": slug,
                            "score": proj_score,
                            "appearances": appearances,
                        }
                    )

            if outliers:
                results.append(
                    {
                        "global_item_id": global_id,
                        "global_avg_score": global_avg,
                        "outlier_projects": outliers,
                    }
                )

        if results:
            logger.warning(
                "Detected %d override candidates (global items underperforming on specific projects)",
                len(results),
            )
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _project_overrides_dir(self, project_slug: str) -> Path:
        """Return the expected override directory for a project slug.

        This is a heuristic path and may not always be valid.  Callers that
        know the exact data root should use ``record_override_at`` directly.
        """
        return self._dir.parent / project_slug / "memory"

    def _load_project_overrides_by_slug(self, project_slug: str) -> set[str]:
        overrides_path = self._project_overrides_dir(project_slug) / _OVERRIDES_FILENAME
        return self.load_overrides_at(overrides_path)

    @staticmethod
    def _read_overrides_file(path: Path) -> dict[str, Any]:
        if not path.is_file():
            return {"overrides": {}}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if "overrides" not in data:
                data["overrides"] = {}
            return data
        except (OSError, json.JSONDecodeError):
            return {"overrides": {}}

    def _load_global_scores(self) -> dict[str, Any]:
        scores_file = self._dir / "item_scores.json"
        if not scores_file.is_file():
            return {}
        try:
            return json.loads(scores_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _load_project_scores(memory_dir: Path) -> dict[str, Any]:
        scores_file = memory_dir / "item_scores.json"
        if not scores_file.is_file():
            return {}
        try:
            raw: dict[str, Any] = json.loads(scores_file.read_text(encoding="utf-8"))
            return raw
        except (OSError, json.JSONDecodeError):
            return {}

    def _load_project_items(self, memory_dir: Path) -> list[tuple[int, str, float]]:
        """Load (item_id, text, score) tuples from a project memory directory."""
        scores = self._load_project_scores(memory_dir)
        items_dir = memory_dir / "items"
        result: list[tuple[int, str, float]] = []
        for str_id, item_data in scores.items():
            try:
                item_id = int(str_id)
            except ValueError:
                continue
            score: float = item_data.get("score", 0.0)
            # Read text from items/ subdirectory
            item_file = items_dir / f"{item_id}.md"
            if item_file.is_file():
                try:
                    text = item_file.read_text(encoding="utf-8").strip()
                except OSError:
                    text = ""
            else:
                text = ""
            if text:
                result.append((item_id, text, score))
        return result


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _extract_keywords(text: str) -> set[str]:
    """Extract lowercase words of length >= 4 from *text*."""
    return {w.lower() for w in re.findall(r"[a-zA-Z]+", text) if len(w) >= 4}


def _keyword_overlap(a: set[str], b: set[str]) -> float:
    """Return Jaccard-like overlap: |intersection| / max(|a|, |b|)."""
    if not a or not b:
        return 0.0
    return len(a & b) / max(len(a), len(b))
