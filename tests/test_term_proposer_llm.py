"""Tests for the term-proposer LLM wrapper."""

from __future__ import annotations

import pytest

from term_proposer_llm import (
    DraftContext,
    TermDraft,
    TermProposerLLM,
)
from ubiquitous_language import (
    BoundedContext,
    Candidate,
    Term,
    TermKind,
)


class FakeLLMClient:
    """Stub that returns a pre-canned structured response."""

    def __init__(self, response: dict) -> None:
        self.response = response
        self.calls: list[dict] = []

    async def complete_structured(self, *, prompt: str, schema: dict) -> dict:
        self.calls.append({"prompt": prompt, "schema": schema})
        return self.response


@pytest.fixture
def candidate() -> Candidate:
    return Candidate(
        name="HelperService",
        code_anchor="src/helper.py:HelperService",
        signals=("S2",),
        imports_seen=2,
        importing_term_anchors=("src/agent.py:AgentRunner",),
    )


@pytest.fixture
def existing_terms() -> list[Term]:
    return [
        Term(
            id="01H_AGENT",
            name="AgentRunner",
            kind=TermKind.RUNNER,
            bounded_context=BoundedContext.BUILDER,
            definition="The implement-phase runner that turns a plan into commits and a PR.",
            code_anchor="src/agent.py:AgentRunner",
        ),
    ]


class TestTermProposerLLM:
    @pytest.mark.asyncio
    async def test_returns_validated_draft(
        self, candidate: Candidate, existing_terms: list[Term]
    ) -> None:
        fake = FakeLLMClient(
            response={
                "definition": "Helper service that supports AgentRunner with shared utilities for plan execution.",
                "kind": "service",
                "bounded_context": "builder",
                "aliases": ["helper service", "agent helper"],
                "invariants": ["Stateless — instances are interchangeable."],
                "depends_on_anchors": ["src/agent.py:AgentRunner"],
            }
        )
        llm = TermProposerLLM(client=fake)
        ctx = DraftContext(
            candidate=candidate,
            candidate_source='class HelperService:\n    """Helper."""\n    pass\n',
            caller_snippets={"src/agent.py:AgentRunner": "class AgentRunner: ..."},
            existing_terms=existing_terms,
        )
        draft = await llm.draft(ctx)
        assert isinstance(draft, TermDraft)
        assert draft.kind == TermKind.SERVICE
        assert draft.bounded_context == BoundedContext.BUILDER
        assert "AgentRunner" in str(draft.depends_on_anchors)
        assert len(draft.definition) >= 30
        assert len(fake.calls) == 1

    @pytest.mark.asyncio
    async def test_rejects_garbage_response(
        self, candidate: Candidate, existing_terms: list[Term]
    ) -> None:
        fake = FakeLLMClient(response={"definition": "x", "kind": "not_a_real_kind"})
        llm = TermProposerLLM(client=fake)
        ctx = DraftContext(
            candidate=candidate,
            candidate_source="class HelperService: pass\n",
            caller_snippets={},
            existing_terms=existing_terms,
        )
        with pytest.raises(ValueError, match="invalid|kind"):
            await llm.draft(ctx)

    @pytest.mark.asyncio
    async def test_prompt_includes_existing_term_names(
        self, candidate: Candidate, existing_terms: list[Term]
    ) -> None:
        fake = FakeLLMClient(
            response={
                "definition": "A test definition that is at least thirty characters long for validation.",
                "kind": "service",
                "bounded_context": "builder",
                "aliases": [],
                "invariants": [],
                "depends_on_anchors": [],
            }
        )
        llm = TermProposerLLM(client=fake)
        ctx = DraftContext(
            candidate=candidate,
            candidate_source="class HelperService: pass\n",
            caller_snippets={},
            existing_terms=existing_terms,
        )
        await llm.draft(ctx)
        prompt = fake.calls[0]["prompt"]
        # Prompt MUST include the existing-term canonical names so the LLM uses them
        assert "AgentRunner" in prompt
