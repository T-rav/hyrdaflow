"""Tests for FakeGitHub stateful fake."""

from __future__ import annotations

import pytest

from mockworld.fakes.fake_github import FakeGitHub, RateLimitError
from tests.conftest import TaskFactory

pytestmark = pytest.mark.scenario


class TestFakeGitHubIssues:
    def test_add_and_query_issue(self):
        gh = FakeGitHub()
        gh.add_issue(1, "Fix bug", "body", labels=["hydraflow-ready"])
        issue = gh.issue(1)
        assert issue.labels == ["hydraflow-ready"]
        assert issue.title == "Fix bug"

    def test_issue_not_found_raises(self):
        gh = FakeGitHub()
        with pytest.raises(KeyError, match="999"):
            gh.issue(999)


class TestFakeGitHubPRs:
    async def test_create_pr_tracks_state(self):
        gh = FakeGitHub()
        issue = TaskFactory.create(id=1)
        pr = await gh.create_pr(issue, "agent/issue-1")
        assert pr.number >= 1
        assert gh.pr(pr.number).merged is False

    async def test_merge_pr_sets_merged(self):
        gh = FakeGitHub()
        issue = TaskFactory.create(id=1)
        pr = await gh.create_pr(issue, "agent/issue-1")
        result = await gh.merge_pr(pr.number)
        assert result is True
        assert gh.pr(pr.number).merged is True

    async def test_pr_for_issue(self):
        gh = FakeGitHub()
        issue = TaskFactory.create(id=1)
        pr = await gh.create_pr(issue, "agent/issue-1")
        found = gh.pr_for_issue(1)
        assert found is not None
        assert found.number == pr.number

    async def test_wait_for_ci_default_pass(self):
        gh = FakeGitHub()
        passed, _ = await gh.wait_for_ci(100)
        assert passed is True

    async def test_wait_for_ci_scripted_failure(self):
        gh = FakeGitHub()
        gh.script_ci(100, [(False, "CI failed"), (True, "CI passed")])
        r1 = await gh.wait_for_ci(100)
        r2 = await gh.wait_for_ci(100)
        assert r1[0] is False
        assert r2[0] is True


class TestFakeGitHubMutations:
    async def test_transition_updates_labels(self):
        gh = FakeGitHub()
        gh.add_issue(1, "t", "b", labels=["hydraflow-find"])
        await gh.transition(1, "plan")
        assert gh.issue(1).labels == ["hydraflow-plan"]

    async def test_swap_pipeline_labels_removes_existing(self):
        gh = FakeGitHub()
        gh.add_issue(1, "t", "b", labels=["hydraflow-find", "bug"])
        await gh.swap_pipeline_labels(1, "hydraflow-plan")
        assert "hydraflow-plan" in gh.issue(1).labels
        assert "hydraflow-find" not in gh.issue(1).labels
        assert "bug" in gh.issue(1).labels  # non-pipeline labels preserved

    async def test_close_issue_sets_state(self):
        gh = FakeGitHub()
        gh.add_issue(1, "t", "b")
        await gh.close_issue(1)
        assert gh.issue(1).state == "closed"

    async def test_post_comment_appends_to_issue(self):
        gh = FakeGitHub()
        gh.add_issue(1, "t", "b")
        await gh.post_comment(1, "a comment")
        assert "a comment" in gh.issue(1).comments


class TestFakeGitHubRateLimit:
    async def test_rate_limit_zero_remaining_raises(self) -> None:
        gh = FakeGitHub()
        gh.add_issue(1, "t", "b", labels=[])
        gh.set_rate_limit_mode(remaining=0, reset_in=60)
        with pytest.raises(RateLimitError) as exc_info:
            await gh.add_labels(1, ["x"])
        assert exc_info.value.reset_in == 60
        assert exc_info.value.secondary is False

    async def test_rate_limit_nonzero_remaining_decrements(self) -> None:
        gh = FakeGitHub()
        gh.add_issue(1, "t", "b", labels=[])
        gh.set_rate_limit_mode(remaining=2, reset_in=60)
        await gh.add_labels(1, ["a"])  # remaining=1
        await gh.add_labels(1, ["b"])  # remaining=0
        with pytest.raises(RateLimitError):
            await gh.add_labels(1, ["c"])

    async def test_secondary_rate_limit_sets_flag(self) -> None:
        gh = FakeGitHub()
        gh.add_issue(1, "t", "b", labels=[])
        gh.set_rate_limit_mode(remaining=0, secondary=True)
        with pytest.raises(RateLimitError) as exc_info:
            await gh.add_labels(1, ["x"])
        assert exc_info.value.secondary is True

    async def test_rate_limit_heals_via_clear(self) -> None:
        gh = FakeGitHub()
        gh.add_issue(1, "t", "b", labels=[])
        gh.set_rate_limit_mode(remaining=0)
        gh.clear_rate_limit()
        await gh.add_labels(1, ["x"])  # no raise
        assert "x" in gh.issue(1).labels


class TestFakeGitHubCodeScanningAlerts:
    async def test_fetch_code_scanning_alerts_returns_scripted_list(self) -> None:
        from models import CodeScanningAlert

        gh = FakeGitHub()
        alerts = [
            CodeScanningAlert(
                number=1,
                severity="error",
                security_severity="high",
                path="src/x.py",
                start_line=42,
                rule="py/sql-injection",
                message="potential injection",
            ),
        ]
        gh.add_alerts(branch="refs/heads/x", alerts=alerts)
        out = await gh.fetch_code_scanning_alerts(branch="refs/heads/x")
        assert out == alerts

    async def test_fetch_code_scanning_alerts_defaults_empty(self) -> None:
        gh = FakeGitHub()
        assert await gh.fetch_code_scanning_alerts(branch="refs/heads/missing") == []

    async def test_fetch_code_scanning_alerts_keyed_by_branch(self) -> None:
        """Alerts are keyed by branch string, matching PRPort.fetch_code_scanning_alerts."""
        from models import CodeScanningAlert

        gh = FakeGitHub()
        a1 = CodeScanningAlert(
            number=1,
            severity="error",
            security_severity="high",
            path="a.py",
            start_line=1,
            rule="r1",
            message="m1",
        )
        a2 = CodeScanningAlert(
            number=2,
            severity="warning",
            security_severity="medium",
            path="b.py",
            start_line=2,
            rule="r2",
            message="m2",
        )
        gh.add_alerts(branch="agent/issue-1", alerts=[a1])
        gh.add_alerts(branch="agent/issue-2", alerts=[a2])

        out1 = await gh.fetch_code_scanning_alerts(branch="agent/issue-1")
        out2 = await gh.fetch_code_scanning_alerts(branch="agent/issue-2")
        assert out1 == [a1]
        assert out2 == [a2]
