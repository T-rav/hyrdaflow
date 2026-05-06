"""Verify ReviewPhase.review_prs filters out term-proposer PRs (ADR-0054).

The Term-Proposer Loop opens its own bot PRs labelled
``hydraflow-ul-proposed`` and relies on ``DependabotMergeLoop`` to auto-merge
them on CI green. The agent pipeline (plan/implement/review) must NOT touch
those PRs, otherwise the LLM call inside the loop would recurse into the
review pipeline.

Constructing a real ``ReviewPhase`` requires ~16 collaborators, so this test
asserts the routing exception in two ways:

1. The single source of truth for the label lives in
   ``term_proposer_loop.TERM_PROPOSER_PR_LABEL`` (no string duplication).
2. The production code path in ``ReviewPhase.review_prs`` actually consults
   that constant — verified via ``inspect.getsource`` so refactors that drop
   the filter (or re-introduce a hardcoded literal) fail this test.
"""

from __future__ import annotations

import inspect

from review_phase import ReviewPhase
from term_proposer_loop import TERM_PROPOSER_PR_LABEL


def test_constant_is_the_label_string() -> None:
    """The constant must equal the literal label DependabotMergeLoop watches for."""
    assert TERM_PROPOSER_PR_LABEL == "hydraflow-ul-proposed"


def test_review_prs_filters_via_constant_not_literal() -> None:
    """``ReviewPhase.review_prs`` must reference the constant, not a hardcoded string."""
    source = inspect.getsource(ReviewPhase.review_prs)
    assert "TERM_PROPOSER_PR_LABEL" in source, (
        "ReviewPhase.review_prs must filter via the imported constant"
    )
    # And the literal must NOT be re-duplicated inside review_prs.
    assert '"hydraflow-ul-proposed"' not in source, (
        "ReviewPhase.review_prs reintroduced a hardcoded label literal — "
        "use TERM_PROPOSER_PR_LABEL instead"
    )
