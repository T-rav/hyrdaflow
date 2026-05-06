"""LLM wrapper for TermProposerLoop draft generation.

Sends a structured request: candidate + context → TermDraft. Validation against
the closed-set vocabularies happens at parse time. Anchor resolution + lint
checks are the LOOP's job, not the LLM wrapper's.

Client shape: the existing wiki_compiler.py uses a subprocess-CLI shape
(`SubprocessRunner.run_simple` with prompt-as-stdin and JSON-extracted from
stdout). That shape is bound to the CLI tool flag layer; for a structured
draft we want a typed dict in/out so unit tests can inject a fake without
spawning subprocesses. The Protocol below is the de-facto contract a
production adapter (subprocess CLI + JSON-mode parsing) will implement on
top of the same `SubprocessRunner` plumbing wiki_compiler uses.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import ValidationError

from ubiquitous_language import (
    BoundedContext,
    Candidate,
    Term,
    TermDraft,
    TermKind,
)


class LLMClient(Protocol):
    """Structured-output LLM client.

    Implementations: production uses a subprocess-CLI adapter wrapping the
    same `SubprocessRunner` path as `wiki_compiler.WikiCompiler._call_model`,
    parsing JSON from stdout into a dict; tests use a stub with a pre-canned
    response.
    """

    async def complete_structured(
        self, *, prompt: str, schema: dict[str, Any]
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class DraftContext:
    """All inputs the LLM needs to draft one Term."""

    candidate: Candidate
    candidate_source: str  # truncated to ≤200 lines
    caller_snippets: dict[str, str]  # anchor -> snippet
    existing_terms: list[Term]


_PROMPT_TEMPLATE = """You are drafting a ubiquitous-language Term for the HydraFlow codebase.

Existing terms (use these canonical names exactly when referring to them):
{existing_term_lines}

Candidate class to draft:
- Name: {name}
- Anchor: {code_anchor}
- Signals: {signals}
- Times imported by covered modules: {imports_seen}
- Importing covered-term anchors: {importing_anchors}

Candidate source:
```python
{candidate_source}
```

Caller snippets (top importers, grounding for the depends_on edges):
{caller_block}

Closed-set vocabularies you MUST use (any other value is invalid):
- kind ∈ {kind_values}
- bounded_context ∈ {context_values}

Bounded-context guidance:
- caretaker — proactive maintenance / hygiene loops (stale issues, CI watch, security patches, code grooming)
- builder — the issue→PR pipeline (planner, agent, review phases, dispatcher)
- ai-dev-team — multi-repo, memory, trust fleet, the broader autonomy layer
- shared-kernel — cross-cutting infra used by every layer (config, event bus, state, ports, base classes)

Output a strict JSON object matching this schema:
{{
  "definition": "<one paragraph, ≥30 chars, drawn from docstring + caller usage; do NOT invent>",
  "kind": "<one of {kind_values}>",
  "bounded_context": "<one of {context_values}>",
  "aliases": ["<lowercase paraphrase>", ...],
  "invariants": ["<bullet drawn from code, 0–3 entries>"],
  "depends_on_anchors": ["<one of: {valid_anchors}>", ...]
}}

depends_on_anchors MUST be a subset of the importing covered-term anchors above.
If unsure, return an empty list — never invent an anchor.
"""


class TermProposerLLM:
    """Drafts a Term from a Candidate via structured LLM call."""

    def __init__(self, client: LLMClient) -> None:
        self._client = client

    async def draft(self, ctx: DraftContext) -> TermDraft:
        prompt = self._build_prompt(ctx)
        raw = await self._client.complete_structured(
            prompt=prompt, schema=TermDraft.model_json_schema()
        )
        try:
            return TermDraft.model_validate(raw)
        except ValidationError as e:
            raise ValueError(f"LLM returned invalid TermDraft: {e}") from e

    def _build_prompt(self, ctx: DraftContext) -> str:
        existing_lines = (
            "\n".join(
                f"- {t.name} ({t.kind.value}, {t.bounded_context.value}) — {t.code_anchor}"
                for t in ctx.existing_terms
            )
            or "(none yet)"
        )

        caller_block = (
            "\n\n".join(
                f"### {anchor}\n```python\n{snippet}\n```"
                for anchor, snippet in ctx.caller_snippets.items()
            )
            or "(no caller snippets available)"
        )

        valid_anchors = (
            ", ".join(repr(a) for a in ctx.candidate.importing_term_anchors)
            or "(none — must return [])"
        )

        return _PROMPT_TEMPLATE.format(
            existing_term_lines=existing_lines,
            name=ctx.candidate.name,
            code_anchor=ctx.candidate.code_anchor,
            signals=", ".join(ctx.candidate.signals),
            imports_seen=ctx.candidate.imports_seen,
            importing_anchors=", ".join(ctx.candidate.importing_term_anchors)
            or "(none)",
            candidate_source=ctx.candidate_source,
            caller_block=caller_block,
            kind_values=", ".join(repr(k.value) for k in TermKind),
            context_values=", ".join(repr(c.value) for c in BoundedContext),
            valid_anchors=valid_anchors,
        )
