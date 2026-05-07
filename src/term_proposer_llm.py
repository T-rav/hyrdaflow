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


_PROMPT_TEMPLATE = """You are evaluating whether a candidate class belongs in HydraFlow's **ubiquitous language** (UL), and — if so — drafting the Term.

## Context: what UL is, why it matters

This codebase follows Eric Evans' Domain-Driven Design. The **ubiquitous language** is the shared vocabulary that engineers, domain experts, and the code itself use to talk about the system. UL terms are *names that carry domain meaning* — they appear in design discussions, ADRs, code, glossaries, and conversations as the same word with the same precise meaning.

UL is not "every class in `src/`." Most classes are scaffolding: they implement, support, or carry data for the things that matter. Only a small fraction of classes name **load-bearing domain concepts** that the system's purpose hinges on. Those are UL terms; everything else is not.

When the system already has UL terms, they form an *ontology* — a graph of named domain concepts with relationships. Your job is to decide whether the candidate enriches that ontology with a new node, or whether it's scaffolding around existing nodes.

## Existing ontology (UL terms already in the glossary)

Use these canonical names exactly when referring to them. The candidate may relate to one or more of these:

{existing_term_lines}

Candidate class:
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

## Step 1 — Inclusion judgment

Decide whether this candidate belongs in the UL. Apply these criteria, in order:

**Linguistic test:** would engineers use this name **as a noun** in design conversations about HydraFlow?
- "We need a new `<Name>`" / "The `<Name>` does X" → likely UL
- "We need to handle `<Name>`" / "`<Name>` happens when X fails" → likely scaffolding (the noun is the thing that throws/contains it, not the thing itself)

INCLUDE (`"include": true`) — **load-bearing domain concepts**:
- Aggregate / Entity / Value Object — modeled state with identity or significant value semantics
- Domain Event — a named thing that *happens* in the domain (e.g., `IssueOpened`, not the carrier struct)
- Service / Port / Adapter — an architectural seam engineers explicitly name
- Loop / Runner — autonomous workers with named identity (`AgentRunner`, `RepoWikiLoop`)
- Policy / Invariant / Bounded Context — rules that gate behavior or shape the system

SKIP (`"include": false`) — **scaffolding**:
- **Exception / Error types** — operational signals raised by services. The service is UL; the exception is its failure mode, not a separate domain concept. Skip unless the exception itself names a *business rule* (e.g., `InsufficientFunds` in an accounting system might be UL; `AuthenticationError` is not).
- **Mixin / abstract composition helpers** — `*Mixin` classes exist to compose behavior into other classes; engineers reach for the composed class, not the mixin.
- **Generic data carriers** — TypedDicts / dataclasses / Pydantic models that exist *only* to type a parameter or return value, with no behavior, no named identity, no engineering conversation. (A Pydantic model that *is* a Domain Event with named meaning is UL; one that's just "the shape of a function arg" is not.)
- **Internal utility / helper classes** — wrappers, builders, formatters used inside one module.
- **Test scaffolding** — fixtures, fakes, mocks.
- **Framework extension points** without HydraFlow-specific identity (e.g., a generic Protocol that any HTTP client could satisfy).

**Hard test:** if a new engineer asked "what is `<Name>`?", is the most useful answer:
- "It's a `<noun-phrase-in-domain>`" → INCLUDE
- "It's how `<other-thing>` represents/handles/carries `<X>`" → SKIP (the *other thing* is the UL term; this candidate is a detail)

**Honest acknowledgment:** when in doubt, prefer SKIP. A glossary cluttered with marginal terms is worse than one missing a few — supersession is cheap when a real concept emerges later.

## Step 2 — When INCLUDE is true, draft the Term

Closed-set vocabularies you MUST use (any other value is invalid):
- kind ∈ {kind_values}
- bounded_context ∈ {context_values}

Bounded-context guidance:
- caretaker — proactive maintenance / hygiene loops (stale issues, CI watch, security patches, code grooming)
- builder — the issue→PR pipeline (planner, agent, review phases, dispatcher)
- ai-dev-team — multi-repo, memory, trust fleet, the broader autonomy layer
- shared-kernel — cross-cutting infra used by every layer (config, event bus, state, ports, base classes)

## Output

Output a strict JSON object. Two valid shapes:

**Shape A — Skip:**
{{
  "include": false,
  "skip_reason": "<short rationale: 'exception type', 'mixin scaffolding', 'thin data carrier', etc.>",
  "definition": "",
  "kind": null,
  "bounded_context": null,
  "aliases": [],
  "invariants": [],
  "depends_on_anchors": []
}}

**Shape B — Include + draft:**
{{
  "include": true,
  "skip_reason": null,
  "definition": "<one paragraph, ≥30 chars, drawn from docstring + caller usage; do NOT invent>",
  "kind": "<one of {kind_values}>",
  "bounded_context": "<one of {context_values}>",
  "aliases": ["<lowercase paraphrase>", ...],
  "invariants": ["<bullet drawn from code, 0–3 entries>"],
  "depends_on_anchors": ["<one of: {valid_anchors}>", ...]
}}

depends_on_anchors MUST be a subset of the importing covered-term anchors above. If unsure, return an empty list — never invent an anchor.
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
