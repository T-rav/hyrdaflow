"""Prompt audit script — see docs/superpowers/specs/2026-04-20-prompt-audit-design.md."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


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


# ---------------------------------------------------------------------------
# Rubric #5 — output contract explicit
# ---------------------------------------------------------------------------

_OUTPUT_CONTRACT_CUES = (
    r"respond with",
    r"do not",
    r"no prose",
    r"no markdown",
    r"no apolog",
    r"output format",
    r"return only",
    r"the output must",
)


def score_output_contract(rendered: str) -> str:
    return "Pass" if _any_hit(_OUTPUT_CONTRACT_CUES, rendered) else "Fail"


# ---------------------------------------------------------------------------
# Rubric #6 — placement of long context
# ---------------------------------------------------------------------------

LONG_CONTEXT_THRESHOLD = 10_000


def _largest_tagged_block_end(rendered: str) -> int:
    best_end = -1
    best_len = -1
    for match in _TAG_PAIR.finditer(rendered):
        if match.group(1).lower() in _EXCLUDED_TAGS:
            continue
        length = match.end() - match.start()
        if length > best_len:
            best_len = length
            best_end = match.end()
    return best_end


def _last_imperative_offset(rendered: str) -> int:
    verbs = "|".join(sorted(IMPERATIVE_VERBS))
    last = -1
    for match in re.finditer(rf"\b({verbs})\b", rendered, re.IGNORECASE):
        last = match.start()
    return last


def score_long_context_placement(rendered: str) -> str:
    if len(rendered) < LONG_CONTEXT_THRESHOLD:
        return "N/A"
    block_end = _largest_tagged_block_end(rendered)
    last_imp = _last_imperative_offset(rendered)
    if block_end == -1 or last_imp == -1:
        return "Fail"
    return "Pass" if block_end < last_imp else "Fail"


# ---------------------------------------------------------------------------
# Rubric #7 — chain-of-thought scaffolded where decisions are made
# ---------------------------------------------------------------------------

_DECISION_VERBS = frozenset(
    {
        "classify",
        "decide",
        "verdict",
        "approve",
        "reject",
        "score",
        "rank",
        "choose",
        "determine",
        "evaluate",
    }
)
_COT_CUES = (r"<thinking>", r"<scratchpad>", r"think step by step", r"reason first")


def score_cot(rendered: str) -> str:
    words = set(re.findall(r"[A-Za-z]+", rendered.lower()))
    applicable = bool(words & _DECISION_VERBS)
    if not applicable:
        return "N/A"
    return "Pass" if _any_hit(_COT_CUES, rendered) else "Fail"


# ---------------------------------------------------------------------------
# Rubric #8 — edge cases named
# ---------------------------------------------------------------------------

_EDGE_CASE_CUES = (
    r"if (empty|missing|truncated|unclear|no \w+)",
    r"when the \w+ (is not|cannot|fails)",
    r"\botherwise,",
    r"in case of",
    r"\bfallback\b",
    r"do not assume",
)


def score_edge_cases(rendered: str) -> str:
    return "Pass" if _any_hit(_EDGE_CASE_CUES, rendered) else "Fail"


# ---------------------------------------------------------------------------
# Severity classifier
# ---------------------------------------------------------------------------


@dataclass
class Scorecard:
    scores: dict[int, str] = field(default_factory=dict)


def severity_for(card: Scorecard) -> str:
    fails = [k for k, v in card.scores.items() if v == "Fail"]
    partials = [k for k, v in card.scores.items() if v == "Partial"]
    if len(fails) >= 2 or 1 in fails or 6 in fails:
        return "High"
    if len(fails) == 1 or len(partials) >= 3:
        return "Medium"
    return "Low"


# ---------------------------------------------------------------------------
# Combined score() — applies all eight rubric rules
# ---------------------------------------------------------------------------


def score(rendered: str) -> Scorecard:
    return Scorecard(
        scores={
            1: score_leads_with_request(rendered),
            2: score_specific(rendered),
            3: score_xml_tags(rendered),
            4: score_examples(rendered),
            5: score_output_contract(rendered),
            6: score_long_context_placement(rendered),
            7: score_cot(rendered),
            8: score_edge_cases(rendered),
        }
    )


def main() -> None:
    raise NotImplementedError("wired up in later tasks")


if __name__ == "__main__":
    main()
