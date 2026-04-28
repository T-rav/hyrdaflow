"""FakeGitHub.list_prs_by_label — filters in-memory PRs by label."""

from __future__ import annotations

import pytest

from mockworld.fakes import FakeGitHub


@pytest.mark.asyncio
async def test_list_prs_by_label_returns_matching_prs() -> None:
    gh = FakeGitHub()
    gh.add_issue(1, "first", "body", labels=["hydraflow-ready"])
    gh.add_issue(2, "second", "body", labels=["hydraflow-ready"])
    gh.add_pr(number=100, issue_number=1, branch="hf/issue-1")
    gh.add_pr(number=101, issue_number=2, branch="hf/issue-2")
    gh.add_pr_label(100, "sandbox-fail-auto-fix")
    gh.add_pr_label(101, "wip")

    prs = await gh.list_prs_by_label("sandbox-fail-auto-fix")

    assert len(prs) == 1
    assert prs[0].number == 100


@pytest.mark.asyncio
async def test_list_prs_by_label_empty_when_no_match() -> None:
    gh = FakeGitHub()
    gh.add_issue(1, "first", "body")
    gh.add_pr(number=100, issue_number=1, branch="hf/issue-1")

    prs = await gh.list_prs_by_label("does-not-exist")

    assert prs == []


@pytest.mark.asyncio
async def test_list_prs_by_label_excludes_merged_prs() -> None:
    gh = FakeGitHub()
    gh.add_issue(1, "first", "body")
    gh.add_pr(number=100, issue_number=1, branch="hf/issue-1", merged=True)
    gh.add_pr_label(100, "sandbox-fail-auto-fix")

    prs = await gh.list_prs_by_label("sandbox-fail-auto-fix")

    assert prs == [], "merged PRs should not appear in by-label query"


@pytest.mark.asyncio
async def test_add_pr_label_raises_descriptive_keyerror_for_missing_pr() -> None:
    gh = FakeGitHub()
    with pytest.raises(KeyError, match="FakeGitHub: no PR 999"):
        gh.add_pr_label(999, "any-label")
