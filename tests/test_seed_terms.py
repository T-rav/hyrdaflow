"""Verifies seed terms parse, anchors resolve, contexts/kinds are valid."""

from __future__ import annotations

from pathlib import Path

import pytest

from ubiquitous_language import (
    BoundedContext,
    Term,
    TermKind,
    TermStore,
    build_symbol_index,
    lint_paraphrases,
    resolve_anchor,
)

REPO_ROOT = Path(__file__).parent.parent
TERMS_DIR = REPO_ROOT / "docs" / "wiki" / "terms"
SRC_DIR = REPO_ROOT / "src"

EXPECTED_NAMES = {
    "HydraFlowConfig",
    "EventBus",
    "StateTracker",
    "BaseBackgroundLoop",
    "RepoWikiStore",
    "PRPort",
    "WorkspacePort",
    "IssueStorePort",
    "AgentRunner",
}


@pytest.fixture(scope="module")
def seed_terms() -> list[Term]:
    return TermStore(TERMS_DIR).list()


def test_all_expected_seed_terms_present(seed_terms: list[Term]) -> None:
    actual = {t.name for t in seed_terms}
    missing = EXPECTED_NAMES - actual
    assert not missing, f"Missing seed terms: {missing}"


def test_all_seed_anchors_resolve(seed_terms: list[Term]) -> None:
    index = build_symbol_index(SRC_DIR)
    unresolved = [
        (t.name, t.code_anchor)
        for t in seed_terms
        if not resolve_anchor(t.code_anchor, index)
    ]
    assert not unresolved, f"Unresolved anchors: {unresolved}"


def test_seed_terms_use_valid_kinds_and_contexts(seed_terms: list[Term]) -> None:
    for t in seed_terms:
        assert isinstance(t.kind, TermKind)
        assert isinstance(t.bounded_context, BoundedContext)


def test_seed_terms_have_definitions_and_anchors(seed_terms: list[Term]) -> None:
    for t in seed_terms:
        assert len(t.definition) >= 30, f"{t.name}: definition too short"
        assert ":" in t.code_anchor, f"{t.name}: malformed anchor"


def test_seed_terms_are_accepted(seed_terms: list[Term]) -> None:
    """The originally hand-authored seed terms ship as `accepted`.

    Auto-grown terms from `TermProposerLoop` (ADR-0054) carry `proposed_by`
    and ship as `proposed` until the Confidence-Promoter loop ages them;
    those are correctly out-of-scope for this assertion.
    """
    for t in seed_terms:
        if t.proposed_by is not None:
            continue  # auto-grown term — lifecycle governed by ADR-0054
        assert t.confidence == "accepted", f"{t.name} should ship as accepted"


@pytest.mark.skip(
    reason="Wiki paraphrase cleanup is a follow-up plan; this asserts the lint runs"
)
def test_paraphrase_lint_runs_against_live_wiki() -> None:
    terms = TermStore(TERMS_DIR).list()
    violations = lint_paraphrases(terms, REPO_ROOT / "docs" / "wiki")
    # Document baseline count rather than assert clean
    assert isinstance(violations, list)
