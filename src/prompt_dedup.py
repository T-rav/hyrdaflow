"""Prompt content deduplication for agent context injection."""

from __future__ import annotations

import hashlib
import re


class PromptDeduplicator:
    """Tracks content already injected into an agent prompt session.

    Provides two dedup strategies:
    1. Hash-based: exact content dedup via SHA-256 fingerprint
    2. Keyword-overlap: fuzzy dedup for memory items with >70% word overlap
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
