"""Tests for epic auto-close functionality."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from epic import EpicCompletionChecker, check_all_checkboxes, parse_epic_sub_issues
from models import EpicState, GitHubIssue
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
        assert "All sub-issues resolved" in comment

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


# ---------------------------------------------------------------------------
# Epic edge cases — closed-without-merge, HITL, nested epics, audit trail
# ---------------------------------------------------------------------------


def _make_checker_with_state(
    *,
    epics: list[GitHubIssue] | None = None,
    sub_issues: dict[int, GitHubIssue] | None = None,
    epic_state: EpicState | None = None,
) -> tuple[EpicCompletionChecker, AsyncMock, AsyncMock, MagicMock]:
    """Like _make_checker but with a mock StateTracker."""
    config = ConfigFactory.create(
        epic_label=["hydraflow-epic"],
        hitl_label=["hydraflow-hitl"],
    )
    prs = AsyncMock()
    fetcher = AsyncMock()
    fetcher.fetch_issues_by_labels = AsyncMock(return_value=epics or [])
    sub_map = sub_issues or {}
    fetcher.fetch_issue_by_number = AsyncMock(side_effect=sub_map.get)
    state = MagicMock()
    state.get_epic_state.return_value = epic_state
    checker = EpicCompletionChecker(config, prs, fetcher, state=state)
    return checker, prs, fetcher, state


class TestEpicClosedWithoutMerge:
    """Epic closes when sub-issues are closed as wontfix/duplicate."""

    @pytest.mark.asyncio
    async def test_closes_epic_when_sub_issue_closed_as_wontfix(self) -> None:
        epic = _make_epic(100, [1, 2])
        sub_issues = {
            1: IssueFactory.create(
                number=1, labels=["hydraflow-fixed"], title="Issue #1"
            ),
            2: GitHubIssue(
                number=2,
                title="Issue #2",
                labels=["wontfix"],
                state="closed",
            ),
        }
        checker, prs, _, _ = _make_checker_with_state(
            epics=[epic],
            sub_issues=sub_issues,
            epic_state=EpicState(epic_number=100, child_issues=[1, 2]),
        )

        await checker.check_and_close_epics(1)

        prs.close_issue.assert_called_once_with(100)
        comment = prs.post_comment.call_args[0][1]
        assert "Excluded (closed without merge)" in comment
        assert "#2" in comment

    @pytest.mark.asyncio
    async def test_closes_epic_when_sub_issue_closed_as_duplicate(self) -> None:
        epic = _make_epic(100, [1, 2])
        sub_issues = {
            1: IssueFactory.create(
                number=1, labels=["hydraflow-fixed"], title="Issue #1"
            ),
            2: GitHubIssue(
                number=2,
                title="Issue #2",
                labels=["duplicate"],
                state="closed",
            ),
        }
        checker, prs, _, _ = _make_checker_with_state(
            epics=[epic],
            sub_issues=sub_issues,
            epic_state=EpicState(epic_number=100, child_issues=[1, 2]),
        )

        await checker.check_and_close_epics(1)

        prs.close_issue.assert_called_once_with(100)

    @pytest.mark.asyncio
    async def test_closes_epic_all_sub_issues_closed_without_fixed(self) -> None:
        """All sub-issues closed (no fixed label) — still closes epic."""
        epic = _make_epic(100, [1, 2])
        sub_issues = {
            1: GitHubIssue(
                number=1, title="Issue #1", labels=["wontfix"], state="closed"
            ),
            2: GitHubIssue(
                number=2, title="Issue #2", labels=["invalid"], state="closed"
            ),
        }
        checker, prs, _, _ = _make_checker_with_state(
            epics=[epic],
            sub_issues=sub_issues,
            epic_state=EpicState(epic_number=100, child_issues=[1, 2]),
        )

        await checker.check_and_close_epics(1)

        prs.close_issue.assert_called_once_with(100)

    @pytest.mark.asyncio
    async def test_does_not_close_when_sub_issue_open_without_labels(self) -> None:
        """Open sub-issue without fixed or HITL labels — blocks epic."""
        epic = _make_epic(100, [1, 2])
        sub_issues = {
            1: IssueFactory.create(
                number=1, labels=["hydraflow-fixed"], title="Issue #1"
            ),
            2: GitHubIssue(
                number=2,
                title="Issue #2",
                labels=[],
                state="open",
            ),
        }
        checker, prs, _, _ = _make_checker_with_state(
            epics=[epic],
            sub_issues=sub_issues,
            epic_state=EpicState(epic_number=100, child_issues=[1, 2]),
        )

        await checker.check_and_close_epics(1)

        prs.close_issue.assert_not_called()


class TestEpicHITLHandling:
    """HITL-escalated sub-issues post warnings but don't close epic."""

    @pytest.mark.asyncio
    async def test_hitl_sub_issue_posts_warning_and_blocks(self) -> None:
        epic = _make_epic(100, [1, 2])
        sub_issues = {
            1: IssueFactory.create(
                number=1, labels=["hydraflow-fixed"], title="Issue #1"
            ),
            2: GitHubIssue(
                number=2,
                title="Issue #2",
                labels=["hydraflow-hitl"],
                state="open",
            ),
        }
        checker, prs, _, _ = _make_checker_with_state(
            epics=[epic],
            sub_issues=sub_issues,
            epic_state=EpicState(epic_number=100, child_issues=[1, 2]),
        )

        await checker.check_and_close_epics(1)

        # Should NOT close the epic
        prs.close_issue.assert_not_called()
        # Should post a warning comment
        prs.post_comment.assert_called_once()
        comment = prs.post_comment.call_args[0][1]
        assert "Epic completion blocked" in comment
        assert "#2" in comment
        assert "HITL" in comment

    @pytest.mark.asyncio
    async def test_hitl_warning_not_repeated(self) -> None:
        """If we already warned about a HITL sub-issue, don't warn again."""
        epic = _make_epic(100, [1, 2])
        sub_issues = {
            1: IssueFactory.create(
                number=1, labels=["hydraflow-fixed"], title="Issue #1"
            ),
            2: GitHubIssue(
                number=2,
                title="Issue #2",
                labels=["hydraflow-hitl"],
                state="open",
            ),
        }
        checker, prs, _, _ = _make_checker_with_state(
            epics=[epic],
            sub_issues=sub_issues,
            epic_state=EpicState(
                epic_number=100,
                child_issues=[1, 2],
                hitl_warned_children=[2],  # Already warned
            ),
        )

        await checker.check_and_close_epics(1)

        prs.close_issue.assert_not_called()
        prs.post_comment.assert_not_called()

    @pytest.mark.asyncio
    async def test_hitl_sub_issue_closed_allows_epic_close(self) -> None:
        """If a HITL sub-issue is closed, treat it as resolved."""
        epic = _make_epic(100, [1, 2])
        sub_issues = {
            1: IssueFactory.create(
                number=1, labels=["hydraflow-fixed"], title="Issue #1"
            ),
            2: GitHubIssue(
                number=2,
                title="Issue #2",
                labels=["hydraflow-hitl"],
                state="closed",
            ),
        }
        checker, prs, _, _ = _make_checker_with_state(
            epics=[epic],
            sub_issues=sub_issues,
            epic_state=EpicState(epic_number=100, child_issues=[1, 2]),
        )

        await checker.check_and_close_epics(1)

        prs.close_issue.assert_called_once_with(100)

    @pytest.mark.asyncio
    async def test_multiple_hitl_sub_issues_in_warning(self) -> None:
        """Warning mentions all HITL sub-issues."""
        epic = _make_epic(100, [1, 2, 3])
        sub_issues = {
            1: IssueFactory.create(
                number=1, labels=["hydraflow-fixed"], title="Issue #1"
            ),
            2: GitHubIssue(
                number=2,
                title="Issue #2",
                labels=["hydraflow-hitl"],
                state="open",
            ),
            3: GitHubIssue(
                number=3,
                title="Issue #3",
                labels=["hydraflow-hitl"],
                state="open",
            ),
        }
        checker, prs, _, _ = _make_checker_with_state(
            epics=[epic],
            sub_issues=sub_issues,
            epic_state=EpicState(epic_number=100, child_issues=[1, 2, 3]),
        )

        await checker.check_and_close_epics(1)

        prs.close_issue.assert_not_called()
        comment = prs.post_comment.call_args[0][1]
        assert "#2" in comment
        assert "#3" in comment
        assert "are" in comment  # Plural


class TestNestedEpics:
    """Nested epic detection and recursive handling."""

    @pytest.mark.asyncio
    async def test_closed_nested_epic_counts_as_resolved(self) -> None:
        """A closed nested epic (sub-issue with epic label) is resolved."""
        epic = _make_epic(100, [1, 2])
        sub_issues = {
            1: IssueFactory.create(
                number=1, labels=["hydraflow-fixed"], title="Issue #1"
            ),
            2: GitHubIssue(
                number=2,
                title="[Epic] Child epic",
                labels=["hydraflow-epic"],
                state="closed",
            ),
        }
        checker, prs, _, _ = _make_checker_with_state(
            epics=[epic],
            sub_issues=sub_issues,
            epic_state=EpicState(epic_number=100, child_issues=[1, 2]),
        )

        await checker.check_and_close_epics(1)

        prs.close_issue.assert_called_once_with(100)

    @pytest.mark.asyncio
    async def test_open_nested_epic_blocks_parent(self) -> None:
        """An open nested epic blocks the parent from closing."""
        epic = _make_epic(100, [1, 2])
        sub_issues = {
            1: IssueFactory.create(
                number=1, labels=["hydraflow-fixed"], title="Issue #1"
            ),
            2: GitHubIssue(
                number=2,
                title="[Epic] Child epic",
                labels=["hydraflow-epic"],
                state="open",
            ),
        }
        checker, prs, _, _ = _make_checker_with_state(
            epics=[epic],
            sub_issues=sub_issues,
            epic_state=EpicState(epic_number=100, child_issues=[1, 2]),
        )

        await checker.check_and_close_epics(1)

        prs.close_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_nested_epic_with_fixed_label_also_resolved(self) -> None:
        """A nested epic with fixed_label is resolved (takes priority path)."""
        epic = _make_epic(100, [1, 2])
        sub_issues = {
            1: IssueFactory.create(
                number=1, labels=["hydraflow-fixed"], title="Issue #1"
            ),
            2: GitHubIssue(
                number=2,
                title="[Epic] Child epic",
                labels=["hydraflow-epic", "hydraflow-fixed"],
                state="closed",
            ),
        }
        checker, prs, _, _ = _make_checker_with_state(
            epics=[epic],
            sub_issues=sub_issues,
            epic_state=EpicState(epic_number=100, child_issues=[1, 2]),
        )

        await checker.check_and_close_epics(1)

        prs.close_issue.assert_called_once_with(100)


class TestDynamicSubIssueAudit:
    """Audit trail for sub-issue list changes between checks."""

    @pytest.mark.asyncio
    async def test_new_sub_issues_detected_and_state_updated(self) -> None:
        """When epic body has new sub-issues, state is updated."""
        # Epic body references issues [1, 2, 3] but state only knows [1, 2]
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
        epic_state = EpicState(epic_number=100, child_issues=[1, 2])
        checker, prs, _, state = _make_checker_with_state(
            epics=[epic],
            sub_issues=sub_issues,
            epic_state=epic_state,
        )

        await checker.check_and_close_epics(1)

        # State should be updated with the new child issue list
        state.upsert_epic_state.assert_called()
        # Epic should still close since all sub-issues are fixed
        prs.close_issue.assert_called_once_with(100)

    @pytest.mark.asyncio
    async def test_sub_issues_added_mid_process_included(self) -> None:
        """Sub-issues added mid-process are included in completion check."""
        # Epic body references [1, 2, 3], but issue 3 is not completed
        epic = _make_epic(100, [1, 2, 3])
        sub_issues = {
            1: IssueFactory.create(
                number=1, labels=["hydraflow-fixed"], title="Issue #1"
            ),
            2: IssueFactory.create(
                number=2, labels=["hydraflow-fixed"], title="Issue #2"
            ),
            3: GitHubIssue(
                number=3,
                title="Issue #3 (new, incomplete)",
                labels=[],
                state="open",
            ),
        }
        checker, prs, _, _ = _make_checker_with_state(
            epics=[epic],
            sub_issues=sub_issues,
            epic_state=EpicState(epic_number=100, child_issues=[1, 2]),
        )

        await checker.check_and_close_epics(1)

        # Should NOT close because issue 3 is not resolved
        prs.close_issue.assert_not_called()


class TestEpicExcludedStateTracking:
    """Excluded children are persisted in state."""

    @pytest.mark.asyncio
    async def test_excluded_children_persisted_in_state(self) -> None:
        epic = _make_epic(100, [1, 2])
        sub_issues = {
            1: IssueFactory.create(
                number=1, labels=["hydraflow-fixed"], title="Issue #1"
            ),
            2: GitHubIssue(
                number=2,
                title="Issue #2",
                labels=["wontfix"],
                state="closed",
            ),
        }
        epic_state = EpicState(epic_number=100, child_issues=[1, 2])
        checker, prs, _, state = _make_checker_with_state(
            epics=[epic],
            sub_issues=sub_issues,
            epic_state=epic_state,
        )

        await checker.check_and_close_epics(1)

        prs.close_issue.assert_called_once_with(100)
        # State should have been updated with excluded children
        state.upsert_epic_state.assert_called()

    @pytest.mark.asyncio
    async def test_no_state_tracker_still_closes_epic(self) -> None:
        """Without a state tracker, epic still closes on completion."""
        epic = _make_epic(100, [1, 2])
        sub_issues = {
            1: IssueFactory.create(
                number=1, labels=["hydraflow-fixed"], title="Issue #1"
            ),
            2: GitHubIssue(
                number=2,
                title="Issue #2",
                labels=["duplicate"],
                state="closed",
            ),
        }
        # Use the original _make_checker (no state tracker)
        checker, prs, _ = _make_checker(epics=[epic], sub_issues=sub_issues)

        await checker.check_and_close_epics(1)

        prs.close_issue.assert_called_once_with(100)
