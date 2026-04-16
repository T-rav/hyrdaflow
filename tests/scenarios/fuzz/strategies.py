"""Hypothesis strategies that produce builder instances.

Strategies compose over the existing builders (IssueBuilder, PRBuilder,
RepoStateBuilder) so fuzz tests reuse phase-1 seed plumbing. Each strategy
draws structural fields only — values stay inside legal domains (e.g. label
names from the state-machine set).
"""

from __future__ import annotations

from hypothesis import strategies as st

from tests.scenarios.builders.issue import IssueBuilder
from tests.scenarios.builders.pr import PRBuilder
from tests.scenarios.builders.repo import RepoStateBuilder

# Valid labels from the hydraflow state machine (subset — extend as needed).
_VALID_LABELS = [
    "hydraflow-find",
    "hydraflow-ready",
    "hydraflow-planning",
    "hydraflow-implementing",
    "hydraflow-reviewing",
    "hydraflow-done",
    "hydraflow-hitl",
    "hydraflow-ci-failure",
]

_CI_STATUSES = ["success", "failure", "pending"]


def issue_numbers() -> st.SearchStrategy[int]:
    return st.integers(min_value=1, max_value=9_999)


def labels() -> st.SearchStrategy[list[str]]:
    return st.lists(st.sampled_from(_VALID_LABELS), min_size=1, max_size=3, unique=True)


def issue_titles() -> st.SearchStrategy[str]:
    return st.text(
        alphabet=st.characters(
            min_codepoint=0x20, max_codepoint=0x7E, blacklist_characters=["`", '"']
        ),
        min_size=1,
        max_size=80,
    )


@st.composite
def issue_builders(draw: st.DrawFn) -> IssueBuilder:
    """Strategy that draws a seeded IssueBuilder (not yet .at()-ed)."""
    builder = (
        IssueBuilder()
        .numbered(draw(issue_numbers()))
        .titled(draw(issue_titles()))
        .bodied(draw(st.text(max_size=200)))
        .labeled(*draw(labels()))
    )
    return builder


@st.composite
def pr_builders(draw: st.DrawFn) -> PRBuilder:
    """Strategy that draws a PRBuilder for a given issue number."""
    return (
        PRBuilder()
        .for_issue(draw(issue_numbers()))
        .on_branch(f"hydraflow/{draw(issue_numbers())}-test")
        .with_ci_status(draw(st.sampled_from(_CI_STATUSES)))
    )


@st.composite
def repo_states(draw: st.DrawFn) -> RepoStateBuilder:
    """Composite: a RepoStateBuilder with 1-5 issues and 0-3 PRs.

    Deduplicates issue numbers within the batch so .at() doesn't hit the
    FakeGitHub add_issue duplicate-number path.
    """
    issues = draw(st.lists(issue_builders(), min_size=1, max_size=5))
    # Dedupe by number — strategy-level fix for the FakeGitHub constraint.
    seen: set[int] = set()
    deduped: list[IssueBuilder] = []
    for ib in issues:
        n = ib._number
        if n is None or n in seen:
            continue
        seen.add(n)
        deduped.append(ib)
    if not deduped:
        deduped = [draw(issue_builders())]

    issue_numbers_in_state = [ib._number for ib in deduped if ib._number is not None]
    prs = draw(
        st.lists(
            st.builds(
                lambda n, status: (
                    PRBuilder()
                    .for_issue(n)
                    .on_branch(f"hydraflow/{n}-test")
                    .with_ci_status(status)
                ),
                st.sampled_from(issue_numbers_in_state or [1]),
                st.sampled_from(_CI_STATUSES),
            ),
            min_size=0,
            max_size=3,
        )
    )
    return RepoStateBuilder().with_issues(deduped).with_prs(prs)
