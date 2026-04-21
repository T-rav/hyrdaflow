"""Prompt audit script — see docs/superpowers/specs/2026-04-20-prompt-audit-design.md."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class AuditTarget:
    name: str
    builder_qualname: str
    fixture_path: str
    category: str
    call_site: str


PROMPT_REGISTRY: list[AuditTarget] = []

# ---------------------------------------------------------------------------
# Rubric #1 — leads with the request
# ---------------------------------------------------------------------------

IMPERATIVE_VERBS = frozenset(
    {
        "produce",
        "return",
        "generate",
        "classify",
        "review",
        "decide",
        "output",
        "propose",
        "write",
        "summarize",
    }
)


def _split_sentences(text: str) -> list[str]:
    """Split on `.`, `?`, `!`, `:` — any of which can end a directive sentence."""
    return [s.strip() for s in re.split(r"(?<=[.!?:])\s+", text) if s.strip()]


def score_leads_with_request(rendered: str) -> str:
    stripped = re.sub(r"<\w+>.*?</\w+>", "", rendered, flags=re.DOTALL).strip()
    sentences = _split_sentences(stripped)
    for idx, sentence in enumerate(sentences):
        words = set(re.findall(r"[A-Za-z]+", sentence.lower()))
        if words & IMPERATIVE_VERBS:
            if idx == 0:
                return "Pass"
            if idx <= 2:
                return "Partial"
            return "Fail"
    return "Fail"


# ---------------------------------------------------------------------------
# Rubric #2 — specific
# ---------------------------------------------------------------------------

OUTPUT_ARTIFACT_NOUNS = (
    r"\bJSON\b",
    r"\bobject\b",
    r"\blist\b",
    r"\bclassification\b",
    r"\blabel\b",
    r"\bplan\b",
    r"\breview\b",
    r"\bpatch\b",
    r"\bdiff\b",
    r"\bsummary\b",
)
SCHEMA_CUES = (r"fields:", r"keys:", r"schema", r"`[a-z_][a-z0-9_]*`")
SUCCESS_CRITERIA_CUES = (
    r"\bmust\b",
    r"\bshould\b",
    r"requirements",
    r"the output must",
)


def _any_hit(patterns: tuple[str, ...], text: str) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def score_specific(rendered: str) -> str:
    hits = sum(
        [
            _any_hit(OUTPUT_ARTIFACT_NOUNS, rendered),
            _any_hit(SCHEMA_CUES, rendered),
            _any_hit(SUCCESS_CRITERIA_CUES, rendered),
        ]
    )
    if hits == 3:
        return "Pass"
    if hits == 2:
        return "Partial"
    return "Fail"


# ---------------------------------------------------------------------------
# Rubric #3 — XML tag structure
# ---------------------------------------------------------------------------

_TAG_PAIR = re.compile(r"<(\w+)>.*?</\1>", re.DOTALL)
_EXCLUDED_TAGS = frozenset({"thinking", "scratchpad"})


def score_xml_tags(rendered: str) -> str:
    tags = {m.group(1).lower() for m in _TAG_PAIR.finditer(rendered)}
    content_tags = tags - _EXCLUDED_TAGS
    if len(content_tags) >= 3:
        return "Pass"
    if len(content_tags) >= 1:
        return "Partial"
    return "Fail"


# ---------------------------------------------------------------------------
# Rubric #4 — examples where applicable
# ---------------------------------------------------------------------------

_STRUCTURED_CUES = (
    r"\bJSON\b",
    r"\bschema\b",
    r"format:",
    r"fields:",
    r"`[a-z_][a-z0-9_]*`",
)
_EXAMPLE_PRESENT = (r"<example>", r"\bExample:", r"<example ")


def score_examples(rendered: str) -> str:
    applicable = _any_hit(_STRUCTURED_CUES, rendered)
    if not applicable:
        return "N/A"
    return "Pass" if _any_hit(_EXAMPLE_PRESENT, rendered) else "Fail"


def main() -> None:
    raise NotImplementedError("wired up in later tasks")


if __name__ == "__main__":
    main()
