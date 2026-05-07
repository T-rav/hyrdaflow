"""Evals for the TermProposerLLM prompt's INCLUDE/SKIP judgment.

Uses the REAL `claude` CLI to evaluate the prompt's classification quality
against a corpus of happy/sad/edge cases. Skipped on CI by default — these
cost LLM tokens and are an evals harness, not a regression suite.

Run locally:
    pytest tests/test_term_proposer_evals.py -v -m evals

Each case is:
- HAPPY: a class that should be included as a UL Term
- SAD: a class that should be skipped (scaffolding, not vocabulary)
- EDGE: a borderline case where the expected judgment is documented and
  the test asserts the LLM lands on the documented side

When evals fail, examine the LLM's `skip_reason` (when False) or the drafted
definition (when True) to understand whether the prompt or the corpus needs
revision.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from term_proposer_llm import DraftContext, TermProposerLLM
from term_proposer_runtime import ClaudeCLIClient
from ubiquitous_language import (
    BoundedContext,
    Candidate,
    Term,
    TermKind,
)

pytestmark = [
    pytest.mark.skip(reason="Evals — real LLM calls; run locally with -m evals"),
    pytest.mark.evals,
]


@dataclass(frozen=True)
class EvalCase:
    """One classification eval. `expected_include` documents the judgment we
    want; `kind` ('happy' / 'sad' / 'edge') labels the test class."""

    candidate_name: str
    candidate_anchor: str
    candidate_source: str
    expected_include: bool
    kind: str
    notes: str = ""


def _stub_existing_terms() -> list[Term]:
    """Minimal existing-ontology fixture (chunk-1 seed terms)."""
    return [
        Term(
            id="01H_AGENT",
            name="AgentRunner",
            kind=TermKind.RUNNER,
            bounded_context=BoundedContext.BUILDER,
            definition="Implement-phase runner that turns a plan into commits and a PR.",
            code_anchor="src/agent.py:AgentRunner",
        ),
        Term(
            id="01H_BBL",
            name="BaseBackgroundLoop",
            kind=TermKind.LOOP,
            bounded_context=BoundedContext.SHARED_KERNEL,
            definition="Abstract base for all caretaker / pipeline loops.",
            code_anchor="src/base_background_loop.py:BaseBackgroundLoop",
        ),
        Term(
            id="01H_EVT",
            name="EventBus",
            kind=TermKind.SERVICE,
            bounded_context=BoundedContext.SHARED_KERNEL,
            definition="In-process pub/sub bus carrying HydraFlowEvent values across loops and runners.",
            code_anchor="src/events.py:EventBus",
        ),
    ]


HAPPY_CASES = [
    EvalCase(
        candidate_name="StaleIssueGCLoop",
        candidate_anchor="src/stale_issue_gc_loop.py:StaleIssueGCLoop",
        candidate_source=(
            "class StaleIssueGCLoop(BaseBackgroundLoop):\n"
            '    """Caretaker loop that auto-closes hydraflow-hitl issues with no\n'
            "    activity beyond the configured threshold. Files a closing\n"
            "    comment and applies hydraflow-stale before closing.\n"
            '    """\n'
            "    async def _do_work(self) -> dict:\n"
            "        ...\n"
        ),
        expected_include=True,
        kind="happy",
        notes="Caretaker loop with named identity — clear UL membership.",
    ),
    EvalCase(
        candidate_name="ReviewRunner",
        candidate_anchor="src/review_runner.py:ReviewRunner",
        candidate_source=(
            "class ReviewRunner:\n"
            '    """Review-phase runner. Examines a PR, runs the agent for\n'
            "    targeted improvements, and either approves or requests\n"
            "    changes via a Verdict.\n"
            '    """\n'
            "    async def review_pr(self, pr): ...\n"
        ),
        expected_include=True,
        kind="happy",
        notes="Phase runner with named architectural role.",
    ),
    EvalCase(
        candidate_name="WorkspaceManager",
        candidate_anchor="src/workspace.py:WorkspaceManager",
        candidate_source=(
            "class WorkspaceManager:\n"
            '    """Manages git worktrees for issue isolation per ADR-0003.\n'
            "    Provides create/destroy/merge/conflict-detect operations behind\n"
            "    the WorkspacePort interface.\n"
            '    """\n'
            "    def create(self, issue): ...\n"
            "    def destroy(self, ws): ...\n"
        ),
        expected_include=True,
        kind="happy",
        notes="Service named in ADR with concrete behavior.",
    ),
]


SAD_CASES = [
    EvalCase(
        candidate_name="AuthenticationError",
        candidate_anchor="src/credentials.py:AuthenticationError",
        candidate_source=(
            "class AuthenticationError(Exception):\n"
            '    """Raised when the configured GitHub token is missing or\n'
            "    rejected. Operational failure mode — caller should re-auth.\n"
            '    """\n'
        ),
        expected_include=False,
        kind="sad",
        notes="Exception type — operational signal, not domain concept.",
    ),
    EvalCase(
        candidate_name="AutoAgentStateMixin",
        candidate_anchor="src/state.py:AutoAgentStateMixin",
        candidate_source=(
            "class AutoAgentStateMixin:\n"
            '    """Mixin providing auto-agent retry-counter accessors. Composed\n'
            "    into StateData by the four-mixin facade pattern.\n"
            '    """\n'
            "    def increment_retry(self, issue): ...\n"
            "    def reset_retry(self, issue): ...\n"
        ),
        expected_include=False,
        kind="sad",
        notes="Mixin scaffolding — engineers reach for StateData, not this.",
    ),
    EvalCase(
        candidate_name="_ParsedTerm",
        candidate_anchor="src/repo_wiki.py:_ParsedTerm",
        candidate_source=(
            "class _ParsedTerm(BaseModel):\n"
            '    """Internal dataclass used by load_term_file to thread parsed\n'
            "    frontmatter into Term.model_validate. Not used outside this\n"
            "    module.\n"
            '    """\n'
            "    fields: dict\n"
            "    body: str\n"
        ),
        expected_include=False,
        kind="sad",
        notes="Internal helper — engineers don't reach for it.",
    ),
]


EDGE_CASES = [
    EvalCase(
        candidate_name="IssueOpened",
        candidate_anchor="src/events.py:IssueOpened",
        candidate_source=(
            "class IssueOpened(BaseModel):\n"
            '    """Domain event published on the EventBus when a new issue\n'
            "    is detected by the dispatcher.\n"
            '    """\n'
            "    issue_id: int\n"
            "    title: str\n"
            "    labels: list[str]\n"
        ),
        expected_include=True,
        kind="edge",
        notes="Pydantic model that IS a Domain Event — UL despite being a 'data class'.",
    ),
    EvalCase(
        candidate_name="BackgroundWorkerStatusPayload",
        candidate_anchor="src/events.py:BackgroundWorkerStatusPayload",
        candidate_source=(
            "class BackgroundWorkerStatusPayload(TypedDict):\n"
            '    """Wire format for the BACKGROUND_WORKER_STATUS event published\n'
            "    by every BaseBackgroundLoop tick. Consumed by dashboard.\n"
            '    """\n'
            "    worker_name: str\n"
            "    last_run_ts: float\n"
            "    error: str | None\n"
        ),
        expected_include=False,
        kind="edge",
        notes=(
            "Borderline. Documented expectation: SKIP — it's the wire format of "
            "an event published by named workers; the event + worker are UL, this "
            "TypedDict is the carrier shape. If the LLM disagrees and the team "
            "prefers INCLUDE, update this case + the prompt."
        ),
    ),
    EvalCase(
        candidate_name="HitlPort",
        candidate_anchor="src/ports.py:HitlPort",
        candidate_source=(
            "class HitlPort(Protocol):\n"
            '    """Hexagonal port for human-in-the-loop interactions. Production\n'
            "    impl posts to GitHub; tests use a fake.\n"
            '    """\n'
            "    async def request_human_review(self, issue) -> str: ...\n"
        ),
        expected_include=True,
        kind="edge",
        notes="Empty Protocol but a named architectural seam — UL.",
    ),
]


ALL_CASES = HAPPY_CASES + SAD_CASES + EDGE_CASES


@pytest.fixture(scope="module")
def llm() -> TermProposerLLM:
    from execution import get_default_runner

    runner = get_default_runner()
    return TermProposerLLM(client=ClaudeCLIClient(runner=runner))


@pytest.fixture(scope="module")
def existing_terms() -> list[Term]:
    return _stub_existing_terms()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", HAPPY_CASES, ids=lambda c: f"happy-{c.candidate_name}")
async def test_happy_path_includes(
    llm: TermProposerLLM, existing_terms: list[Term], case: EvalCase
) -> None:
    """Domain concepts (loops, runners, services) must be classified INCLUDE."""
    candidate = Candidate(
        name=case.candidate_name,
        code_anchor=case.candidate_anchor,
        signals=("S1",),
        imports_seen=2,
        importing_term_anchors=("src/agent.py:AgentRunner",),
    )
    ctx = DraftContext(
        candidate=candidate,
        candidate_source=case.candidate_source,
        caller_snippets={},
        existing_terms=existing_terms,
    )
    draft = await llm.draft(ctx)
    assert draft.include is True, (
        f"{case.candidate_name}: expected INCLUDE; got SKIP "
        f"(reason: {draft.skip_reason!r}). {case.notes}"
    )
    assert draft.kind is not None
    assert draft.bounded_context is not None
    assert len(draft.definition) >= 30


@pytest.mark.asyncio
@pytest.mark.parametrize("case", SAD_CASES, ids=lambda c: f"sad-{c.candidate_name}")
async def test_sad_path_skips(
    llm: TermProposerLLM, existing_terms: list[Term], case: EvalCase
) -> None:
    """Scaffolding (exceptions, mixins, internal helpers) must be SKIP."""
    candidate = Candidate(
        name=case.candidate_name,
        code_anchor=case.candidate_anchor,
        signals=("S2",),
        imports_seen=2,
        importing_term_anchors=("src/agent.py:AgentRunner",),
    )
    ctx = DraftContext(
        candidate=candidate,
        candidate_source=case.candidate_source,
        caller_snippets={},
        existing_terms=existing_terms,
    )
    draft = await llm.draft(ctx)
    assert draft.include is False, (
        f"{case.candidate_name}: expected SKIP; got INCLUDE "
        f"(definition: {draft.definition!r}). {case.notes}"
    )
    assert draft.skip_reason, "include=False must carry a skip_reason"


@pytest.mark.asyncio
@pytest.mark.parametrize("case", EDGE_CASES, ids=lambda c: f"edge-{c.candidate_name}")
async def test_edge_cases_match_documented_expectation(
    llm: TermProposerLLM, existing_terms: list[Term], case: EvalCase
) -> None:
    """Borderline cases — assert against the documented expected judgment.
    When these fail, the team should decide whether to update the case's
    expectation OR the prompt criteria."""
    candidate = Candidate(
        name=case.candidate_name,
        code_anchor=case.candidate_anchor,
        signals=("S2",),
        imports_seen=2,
        importing_term_anchors=("src/agent.py:AgentRunner",),
    )
    ctx = DraftContext(
        candidate=candidate,
        candidate_source=case.candidate_source,
        caller_snippets={},
        existing_terms=existing_terms,
    )
    draft = await llm.draft(ctx)
    assert draft.include is case.expected_include, (
        f"{case.candidate_name}: expected include={case.expected_include}; "
        f"got include={draft.include} "
        f"(skip_reason={draft.skip_reason!r}, definition={draft.definition[:80]!r}). "
        f"{case.notes}"
    )
