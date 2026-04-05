"""Prompt content deduplication for agent context injection."""

from __future__ import annotations

import hashlib
import re

# Minimum paragraph length (chars) to consider for dedup.
# Short paragraphs (headings, labels) are kept unconditionally.
_MIN_PARAGRAPH_CHARS = 80


class PromptDeduplicator:
    """Tracks content already injected into an agent prompt session.

    Provides three dedup strategies:
    1. Hash-based: exact content dedup via SHA-256 fingerprint
    2. Keyword-overlap: fuzzy dedup for memory items with >70% word overlap
    3. Section-level: paragraph-level dedup across named prompt sections
    """

    def __init__(self) -> None:
        self._seen_hashes: set[str] = set()

    def is_duplicate(self, content: str) -> bool:
        """Return True if this exact content was already seen."""
        h = hashlib.sha256(content.encode()).hexdigest()[:16]
        if h in self._seen_hashes:
            return True
        self._seen_hashes.add(h)
        return False

    def dedup_memories(self, memories: list[str]) -> list[str]:
        """Remove duplicate memory items by keyword overlap (>70%)."""
        seen_keywords: list[set[str]] = []
        unique: list[str] = []
        for mem in memories:
            words = {w.lower() for w in re.findall(r"[a-zA-Z]+", mem) if len(w) >= 4}
            if not words:
                unique.append(mem)
                continue
            is_dup = any(
                len(words & existing) / max(len(words), 1) > 0.7
                for existing in seen_keywords
            )
            if not is_dup:
                unique.append(mem)
                seen_keywords.append(words)
        return unique

    def dedup_sections(
        self, *sections: tuple[str, str]
    ) -> tuple[list[tuple[str, str]], int]:
        """Deduplicate across named prompt sections at paragraph level.

        Each input is ``(name, content)``.  Sections are processed in order;
        paragraphs in later sections that duplicate paragraphs from earlier
        sections are replaced with a back-reference note.

        Returns ``(deduped_sections, chars_saved)`` where each entry in
        *deduped_sections* keeps its original *name* and has the deduplicated
        *content*.
        """
        seen_hashes: set[str] = set()
        # Map hash -> originating section name for back-references.
        hash_origin: dict[str, str] = {}
        result: list[tuple[str, str]] = []
        chars_saved = 0

        for name, content in sections:
            if not content or not content.strip():
                result.append((name, content))
                continue

            paragraphs = _split_paragraphs(content)
            kept: list[str] = []
            for para in paragraphs:
                stripped = para.strip()
                if len(stripped) < _MIN_PARAGRAPH_CHARS:
                    # Too short to dedup — keep unconditionally.
                    kept.append(para)
                    continue

                h = hashlib.sha256(stripped.encode()).hexdigest()[:16]
                if h in seen_hashes:
                    origin = hash_origin.get(h, "an earlier section")
                    chars_saved += len(para)
                    kept.append(f"[Content already provided in {origin} — see above]")
                else:
                    seen_hashes.add(h)
                    hash_origin[h] = name
                    kept.append(para)

            result.append((name, "\n\n".join(kept)))
        return result, chars_saved


def _split_paragraphs(text: str) -> list[str]:
    """Split *text* into paragraphs on blank-line boundaries."""
    return [p for p in re.split(r"\n{2,}", text) if p.strip()]
