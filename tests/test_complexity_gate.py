import pytest
from src.complexity_gate import Complexity, ComplexityGate


class _Issue:
    def __init__(self, body: str, labels: list[str]):
        self.body = body
        self.labels = labels


@pytest.mark.asyncio
async def test_explicit_load_bearing_label_routes_load_bearing():
    issue = _Issue(body="anything", labels=["hydraflow-load-bearing"])
    gate = ComplexityGate(llm=None)
    assert await gate.classify(issue) == Complexity.LOAD_BEARING


@pytest.mark.asyncio
async def test_typo_or_docs_only_label_routes_trivial():
    typo_issue = _Issue(body="fix typo in docstring", labels=["hydraflow-typo"])
    docs_issue = _Issue(body="reword README intro", labels=["hydraflow-docs-only"])
    gate = ComplexityGate(llm=None)
    assert await gate.classify(typo_issue) == Complexity.TRIVIAL
    assert await gate.classify(docs_issue) == Complexity.TRIVIAL


@pytest.mark.asyncio
async def test_architectural_keywords_route_load_bearing():
    bodies = [
        "Add a new runner for X",
        "Introduces a new loop that polls...",
        "We need a new ADR to cover this",
        "Refactor to expose a public interface for...",
        "This refactors to extract the gateway",
        "Touches 3+ files: a.py, b.py, c.py",
        "This change touches 5 files across the package",
        "Defines a public interface for sinks",
    ]
    gate = ComplexityGate(llm=None)
    for body in bodies:
        issue = _Issue(body=body, labels=[])
        assert await gate.classify(issue) == Complexity.LOAD_BEARING, body


@pytest.mark.asyncio
async def test_llm_fallback_invoked_when_heuristic_abstains():
    issue = _Issue(body="Make the button blue.", labels=[])
    calls = {"n": 0}

    async def fake_llm(prompt: str) -> str:
        calls["n"] += 1
        return "trivial"

    gate = ComplexityGate(llm=fake_llm)
    result = await gate.classify(issue)
    assert calls["n"] == 1
    assert result == Complexity.TRIVIAL


@pytest.mark.asyncio
async def test_classifier_failure_defaults_to_load_bearing():
    async def fake_llm(prompt: str) -> str:
        raise RuntimeError("LLM down")

    gate = ComplexityGate(llm=fake_llm)
    issue = _Issue(body="ambiguous body", labels=[])
    assert await gate.classify(issue) == Complexity.LOAD_BEARING
