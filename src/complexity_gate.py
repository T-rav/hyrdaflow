from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

logger = logging.getLogger(__name__)


class Complexity(StrEnum):
    TRIVIAL = "trivial"
    LOAD_BEARING = "load-bearing"


class IssueLike(Protocol):
    body: str
    labels: list[str]


LOAD_BEARING_LABELS = frozenset({"hydraflow-load-bearing"})
TRIVIAL_LABELS = frozenset({"hydraflow-typo", "hydraflow-docs-only"})

# Architectural-shape signals. Anything that adds/exposes a new public
# interface, introduces a new top-level component, or sprawls across files
# routes load-bearing — the full adversarial pipeline runs.
LOAD_BEARING_KEYWORDS: tuple[str, ...] = (
    r"\bnew\s+(runner|loop|adr|component|interface|module|api)\b",
    r"\bintroduces?\s+a\s+new\b",
    r"\bpublic\s+interface\b",
    r"\btouches?\s+\d+\+?\s+files\b",
    r"\brefactor(?:s|ing)?\s+to\s+(expose|extract|replace)\b",
)

_KEYWORD_RE = re.compile(
    "|".join(LOAD_BEARING_KEYWORDS),
    flags=re.IGNORECASE,
)

_PROMPT = """\
Classify the following GitHub issue body as TRIVIAL or LOAD-BEARING.

TRIVIAL: typo fix, comment-only change, doc-only edit, single-line bug fix in
non-public code path. The change touches no public interface and creates no
new component.

LOAD-BEARING: anything that introduces or modifies a public interface, adds a
new module/runner/loop, refactors across multiple files, or has architectural
implications.

If uncertain, answer LOAD-BEARING.

Issue body:
---
{body}
---

Respond with one word: TRIVIAL or LOAD-BEARING.
"""


@dataclass
class ComplexityGate:
    """Cheap routing classifier: trivial vs load-bearing.

    Heuristic first (label-based + keyword regex). LLM fallback only if the
    heuristic abstains. Any uncertainty (heuristic abstains and no LLM, or
    LLM raises) defaults to LOAD_BEARING — safer to over-invoke the full
    adversarial pipeline than to under-invoke it.
    """

    llm: Callable[[str], Awaitable[str]] | None

    async def classify(self, issue: IssueLike) -> Complexity:
        body = issue.body or ""
        heuristic = _heuristic_classify(set(issue.labels), body)
        if heuristic is not None:
            return heuristic
        if self.llm is None:
            return Complexity.LOAD_BEARING  # safer default
        return await self._llm_classify(body)

    async def _llm_classify(self, body: str) -> Complexity:
        assert self.llm is not None
        try:
            verdict = await self.llm(_PROMPT.format(body=body))
        except Exception as exc:
            logger.warning("LLM complexity classify failed: %s", exc)
            return Complexity.LOAD_BEARING
        if (verdict or "").strip().lower().startswith("trivial"):
            return Complexity.TRIVIAL
        return Complexity.LOAD_BEARING


def _heuristic_classify(labels: set[str], body: str) -> Complexity | None:
    """Return a verdict if labels or keywords are conclusive, else None."""
    if labels & LOAD_BEARING_LABELS:
        return Complexity.LOAD_BEARING
    if labels & TRIVIAL_LABELS:
        return Complexity.TRIVIAL
    if _KEYWORD_RE.search(body):
        return Complexity.LOAD_BEARING
    return None
