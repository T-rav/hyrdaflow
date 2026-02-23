"""Tests for epic auto-close functionality."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from epic import EpicCompletionChecker, check_all_checkboxes, parse_epic_sub_issues
from models import GitHubIssue
from tests.conftest import IssueFactory
from tests.helpers import ConfigFactory

# ---------------------------------------------------------------------------
# parse_epic_sub_issues
# ---------------------------------------------------------------------------


class TestParseEpicSubIssues:
    def test_parses_unchecked_checkboxes(self) -> None:
        body = "- [ ] #123 — Add feature\n- [ ] #456 — Fix bug"
        assert parse_epic_sub_issues(body) == [123, 456]

    def test_parses_checked_checkboxes(self) -> None:
        body = "- [x] #789 — Done task"
        assert parse_epic_sub_issues(body) == [789]

    def test_parses_mixed_checkboxes(self) -> None:
        body = "- [ ] #10 — Pending\n- [x] #20 — Done\n- [ ] #30 — WIP"
        assert parse_epic_sub_issues(body) == [10, 20, 30]

    def test_returns_empty_for_no_checkboxes(self) -> None:
        body = "This is a regular issue body with no checkboxes."
        assert parse_epic_sub_issues(body) == []

    def test_returns_empty_for_empty_body(self) -> None:
        assert parse_epic_sub_issues("") == []

    def test_ignores_non_issue_checkboxes(self) -> None:
        body = "- [ ] Some task without an issue reference\n- [ ] Another task"
        assert parse_epic_sub_issues(body) == []

    def test_handles_multiple_sub_issues(self) -> None:
        lines = [f"- [ ] #{i} — Task {i}" for i in range(1, 8)]
        body = "\n".join(lines)
        assert parse_epic_sub_issues(body) == list(range(1, 8))

    def test_ignores_non_checkbox_issue_references(self) -> None:
        body = "See #100 for details.\n- [ ] #200 — Linked sub-issue"
        assert parse_epic_sub_issues(body) == [200]


# ---------------------------------------------------------------------------
# check_all_checkboxes
# ---------------------------------------------------------------------------


class TestCheckAllCheckboxes:
    def test_checks_all_unchecked(self) -> None:
        body = "- [ ] #123 — Task A\n- [ ] #456 — Task B"
        result = check_all_checkboxes(body)
        assert result == "- [x] #123 — Task A\n- [x] #456 — Task B"

    def test_preserves_already_checked(self) -> None:
        body = "- [x] #789 — Done"
        assert check_all_checkboxes(body) == "- [x] #789 — Done"

    def test_handles_mixed_state(self) -> None:
        body = "- [ ] #10 — Pending\n- [x] #20 — Done\n- [ ] #30 — WIP"
        result = check_all_checkboxes(body)
        assert result == "- [x] #10 — Pending\n- [x] #20 — Done\n- [x] #30 — WIP"

    def test_preserves_non_checkbox_content(self) -> None:
        body = "## Epic Title\n\nDescription here.\n\n- [ ] #1 — Task\n\nFooter text."
        result = check_all_checkboxes(body)
        assert "## Epic Title" in result
        assert "Description here." in result
        assert "- [x] #1 — Task" in result
        assert "Footer text." in result


# ---------------------------------------------------------------------------
# EpicCompletionChecker
# ---------------------------------------------------------------------------


def _make_epic(number: int, sub_issues: list[int]) -> GitHubIssue:
    lines = [f"- [ ] #{n} — Sub-issue {n}" for n in sub_issues]
    body = "## Epic\n\n" + "\n".join(lines)
    return GitHubIssue(
        number=number, title="[Epic] Test", body=body, labels=["hydraflow-epic"]
    )


def _make_checker(
    *,
    epics: list[GitHubIssue] | None = None,
    sub_issues: dict[int, GitHubIssue] | None = None,
    dry_run: bool = False,
) -> tuple[EpicCompletionChecker, AsyncMock, AsyncMock]:
    config = ConfigFactory.create(
        epic_label=["hydraflow-epic"],
        dry_run=dry_run,
    )
    prs = AsyncMock()
    fetcher = AsyncMock()
    fetcher.fetch_issues_by_labels = AsyncMock(return_value=epics or [])
    sub_map = sub_issues or {}
    fetcher.fetch_issue_by_number = AsyncMock(side_effect=sub_map.get)
    checker = EpicCompletionChecker(config, prs, fetcher)
    return checker, prs, fetcher


class TestEpicCompletionChecker:
    @pytest.mark.asyncio
    async def test_closes_epic_when_all_sub_issues_completed(self) -> None:
        epic = _make_epic(100, [1, 2, 3])
        sub_issues = {
            1: IssueFactory.create(
                number=1, labels=["hydraflow-fixed"], title="Issue #1"
            ),
            2: IssueFactory.create(
                number=2, labels=["hydraflow-fixed"], title="Issue #2"
            ),
            3: IssueFactory.create(
                number=3, labels=["hydraflow-fixed"], title="Issue #3"
            ),
        }
        checker, prs, _ = _make_checker(epics=[epic], sub_issues=sub_issues)

        await checker.check_and_close_epics(1)

        prs.close_issue.assert_called_once_with(100)
        prs.add_labels.assert_called_once_with(100, ["hydraflow-fixed"])
        prs.post_comment.assert_called_once()
        prs.update_issue_body.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_epic_when_some_sub_issues_incomplete(self) -> None:
        epic = _make_epic(100, [1, 2, 3])
        sub_issues = {
            1: IssueFactory.create(
                number=1, labels=["hydraflow-fixed"], title="Issue #1"
            ),
            2: IssueFactory.create(
                number=2, labels=[], title="Issue #2"
            ),  # Not completed
            3: IssueFactory.create(
                number=3, labels=["hydraflow-fixed"], title="Issue #3"
            ),
        }
        checker, prs, _ = _make_checker(epics=[epic], sub_issues=sub_issues)

        await checker.check_and_close_epics(1)

        prs.close_issue.assert_not_called()
        prs.update_issue_body.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_epic_not_referencing_completed_issue(self) -> None:
        epic = _make_epic(100, [10, 20, 30])
        checker, prs, fetcher = _make_checker(epics=[epic])

        await checker.check_and_close_epics(999)

        # Should not fetch sub-issues since the completed issue isn't in the epic
        fetcher.fetch_issue_by_number.assert_not_called()
        prs.close_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_no_open_epics(self) -> None:
        checker, prs, _ = _make_checker(epics=[])

        await checker.check_and_close_epics(1)

        prs.close_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_epic_with_no_checkboxes(self) -> None:
        epic = GitHubIssue(
            number=100,
            title="[Epic] No checkboxes",
            body="This epic has no checkbox sub-issues.",
            labels=["hydraflow-epic"],
        )
        checker, prs, _ = _make_checker(epics=[epic])

        await checker.check_and_close_epics(1)

        prs.close_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_fetch_failure_gracefully(self) -> None:
        config = ConfigFactory.create(epic_label=["hydraflow-epic"])
        prs = AsyncMock()
        fetcher = AsyncMock()
        fetcher.fetch_issues_by_labels = AsyncMock(
            side_effect=RuntimeError("API error")
        )
        checker = EpicCompletionChecker(config, prs, fetcher)

        # Should not raise
        await checker.check_and_close_epics(1)

        prs.close_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_updates_epic_body_checkboxes(self) -> None:
        epic = _make_epic(100, [1, 2])
        sub_issues = {
            1: IssueFactory.create(
                number=1, labels=["hydraflow-fixed"], title="Issue #1"
            ),
            2: IssueFactory.create(
                number=2, labels=["hydraflow-fixed"], title="Issue #2"
            ),
        }
        checker, prs, _ = _make_checker(epics=[epic], sub_issues=sub_issues)

        await checker.check_and_close_epics(1)

        updated_body = prs.update_issue_body.call_args[0][1]
        assert "- [x] #1" in updated_body
        assert "- [x] #2" in updated_body
        assert "- [ ]" not in updated_body

    @pytest.mark.asyncio
    async def test_posts_closing_comment(self) -> None:
        epic = _make_epic(100, [1])
        sub_issues = {
            1: IssueFactory.create(
                number=1, labels=["hydraflow-fixed"], title="Issue #1"
            )
        }
        checker, prs, _ = _make_checker(epics=[epic], sub_issues=sub_issues)

        await checker.check_and_close_epics(1)

        comment = prs.post_comment.call_args[0][1]
        assert "All sub-issues completed" in comment

    @pytest.mark.asyncio
    async def test_skips_when_sub_issue_not_found(self) -> None:
        epic = _make_epic(100, [1, 2])
        sub_issues = {
            1: IssueFactory.create(
                number=1, labels=["hydraflow-fixed"], title="Issue #1"
            ),
            # Issue 2 not found (returns None)
        }
        checker, prs, _ = _make_checker(epics=[epic], sub_issues=sub_issues)

        await checker.check_and_close_epics(1)

        prs.close_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_epic_label_not_configured(self) -> None:
        config = ConfigFactory.create(epic_label=[])
        prs = AsyncMock()
        fetcher = AsyncMock()
        checker = EpicCompletionChecker(config, prs, fetcher)

        await checker.check_and_close_epics(1)

        fetcher.fetch_issues_by_labels.assert_not_called()

    @pytest.mark.asyncio
    async def test_does_not_close_when_fixed_label_not_configured(self) -> None:
        """With fixed_label=[], no sub-issue can be confirmed complete — epic stays open."""
        epic = _make_epic(100, [1])
        sub_issues = {
            1: IssueFactory.create(
                number=1, labels=["hydraflow-fixed"], title="Issue #1"
            )
        }
        config = ConfigFactory.create(epic_label=["hydraflow-epic"], fixed_label=[])
        prs = AsyncMock()
        fetcher = AsyncMock()
        fetcher.fetch_issues_by_labels = AsyncMock(return_value=[epic])
        fetcher.fetch_issue_by_number = AsyncMock(side_effect=sub_issues.get)
        checker = EpicCompletionChecker(config, prs, fetcher)

        await checker.check_and_close_epics(1)

        prs.close_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_multiple_epics(self) -> None:
        epic_a = _make_epic(100, [1, 2])
        epic_b = _make_epic(200, [1, 3])
        sub_issues = {
            1: IssueFactory.create(
                number=1, labels=["hydraflow-fixed"], title="Issue #1"
            ),
            2: IssueFactory.create(
                number=2, labels=["hydraflow-fixed"], title="Issue #2"
            ),
            3: IssueFactory.create(number=3, labels=[], title="Issue #3"),  # Not done
        }
        checker, prs, _ = _make_checker(epics=[epic_a, epic_b], sub_issues=sub_issues)

        await checker.check_and_close_epics(1)

        # Only epic_a should be closed (all sub-issues done)
        prs.close_issue.assert_called_once_with(100)
