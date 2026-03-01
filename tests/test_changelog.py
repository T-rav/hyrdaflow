"""Tests for changelog generation from epic sub-issue PRs."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from changelog import (
    categorize_change,
    extract_summary,
    format_changelog,
    generate_changelog,
)
from epic import EpicCompletionChecker
from models import ChangeCategory, ChangelogEntry, GitHubIssue
from tests.conftest import IssueFactory
from tests.helpers import ConfigFactory

# ---------------------------------------------------------------------------
# categorize_change
# ---------------------------------------------------------------------------


class TestCategorizeChange:
    def test_feat_prefix(self) -> None:
        assert categorize_change("feat: add new feature") == ChangeCategory.FEATURES

    def test_feat_with_scope(self) -> None:
        assert categorize_change("feat(ui): add button") == ChangeCategory.FEATURES

    def test_fix_prefix(self) -> None:
        assert categorize_change("fix: resolve crash") == ChangeCategory.BUG_FIXES

    def test_fix_with_scope(self) -> None:
        assert categorize_change("fix(api): handle null") == ChangeCategory.BUG_FIXES

    def test_refactor_prefix(self) -> None:
        assert (
            categorize_change("refactor: clean up code") == ChangeCategory.IMPROVEMENTS
        )

    def test_perf_prefix(self) -> None:
        assert (
            categorize_change("perf: speed up queries") == ChangeCategory.IMPROVEMENTS
        )

    def test_docs_prefix(self) -> None:
        assert categorize_change("docs: update readme") == ChangeCategory.DOCUMENTATION

    def test_doc_singular_prefix(self) -> None:
        assert categorize_change("doc: fix typo") == ChangeCategory.DOCUMENTATION

    def test_unknown_prefix(self) -> None:
        assert categorize_change("chore: update deps") == ChangeCategory.MISCELLANEOUS

    def test_no_prefix(self) -> None:
        assert categorize_change("Add new feature") == ChangeCategory.MISCELLANEOUS

    def test_case_insensitive(self) -> None:
        assert categorize_change("FEAT: uppercase") == ChangeCategory.FEATURES
        assert categorize_change("Fix: mixed case") == ChangeCategory.BUG_FIXES

    def test_breaking_change_bang(self) -> None:
        assert categorize_change("feat!: breaking change") == ChangeCategory.FEATURES

    def test_empty_title(self) -> None:
        assert categorize_change("") == ChangeCategory.MISCELLANEOUS

    def test_whitespace_title(self) -> None:
        assert categorize_change("   ") == ChangeCategory.MISCELLANEOUS


# ---------------------------------------------------------------------------
# extract_summary
# ---------------------------------------------------------------------------


class TestExtractSummary:
    def test_extracts_summary_section(self) -> None:
        body = "## Summary\n- Added new feature\n- Fixed bug\n\n## Details\nMore info"
        result = extract_summary(body)
        assert "Added new feature" in result
        assert "Fixed bug" in result
        assert "More info" not in result

    def test_extracts_summary_at_end(self) -> None:
        body = "## Summary\n- Single change item"
        result = extract_summary(body)
        assert "Single change item" in result

    def test_returns_empty_for_no_summary(self) -> None:
        body = "## Details\nSome details here"
        assert extract_summary(body) == ""

    def test_returns_empty_for_empty_body(self) -> None:
        assert extract_summary("") == ""

    def test_returns_empty_for_none_like_body(self) -> None:
        assert extract_summary("") == ""

    def test_case_insensitive_heading(self) -> None:
        body = "## SUMMARY\n- Changed something"
        result = extract_summary(body)
        assert "Changed something" in result

    def test_strips_whitespace(self) -> None:
        body = "## Summary\n\n  - Indented item  \n\n## Other"
        result = extract_summary(body)
        assert result.strip() == "- Indented item"

    def test_multiline_summary(self) -> None:
        body = "## Summary\n- Line 1\n- Line 2\n- Line 3\n\n## Test plan"
        result = extract_summary(body)
        assert "Line 1" in result
        assert "Line 2" in result
        assert "Line 3" in result


# ---------------------------------------------------------------------------
# format_changelog
# ---------------------------------------------------------------------------


class TestFormatChangelog:
    def test_basic_formatting(self) -> None:
        entries = [
            ChangelogEntry(
                category=ChangeCategory.FEATURES,
                title="feat: add login",
                issue_number=10,
                pr_number=11,
            ),
        ]
        result = format_changelog("1.0.0", entries, date="2026-02-28")
        assert "## [1.0.0] - 2026-02-28" in result
        assert "### Features" in result
        assert "- add login (#10, PR #11)" in result

    def test_multiple_categories(self) -> None:
        entries = [
            ChangelogEntry(
                category=ChangeCategory.FEATURES,
                title="feat: add feature",
                issue_number=1,
                pr_number=2,
            ),
            ChangelogEntry(
                category=ChangeCategory.BUG_FIXES,
                title="fix: resolve bug",
                issue_number=3,
                pr_number=4,
            ),
            ChangelogEntry(
                category=ChangeCategory.IMPROVEMENTS,
                title="refactor: clean up",
                issue_number=5,
                pr_number=6,
            ),
        ]
        result = format_changelog("2.0.0", entries, date="2026-02-28")
        assert "### Features" in result
        assert "### Bug Fixes" in result
        assert "### Improvements" in result

    def test_empty_entries(self) -> None:
        result = format_changelog("1.0.0", [], date="2026-02-28")
        assert "## [1.0.0] - 2026-02-28" in result
        assert "No changes recorded." in result

    def test_category_order_preserved(self) -> None:
        entries = [
            ChangelogEntry(
                category=ChangeCategory.MISCELLANEOUS,
                title="chore: something",
                issue_number=5,
                pr_number=6,
            ),
            ChangelogEntry(
                category=ChangeCategory.FEATURES,
                title="feat: first",
                issue_number=1,
                pr_number=2,
            ),
        ]
        result = format_changelog("1.0.0", entries, date="2026-02-28")
        feat_pos = result.index("### Features")
        misc_pos = result.index("### Miscellaneous")
        assert feat_pos < misc_pos

    def test_no_issue_number(self) -> None:
        entries = [
            ChangelogEntry(
                category=ChangeCategory.FEATURES,
                title="feat: something",
                pr_number=10,
            ),
        ]
        result = format_changelog("1.0.0", entries, date="2026-02-28")
        assert "- something (PR #10)" in result

    def test_no_pr_number(self) -> None:
        entries = [
            ChangelogEntry(
                category=ChangeCategory.FEATURES,
                title="feat: something",
                issue_number=5,
            ),
        ]
        result = format_changelog("1.0.0", entries, date="2026-02-28")
        assert "- something (#5)" in result

    def test_no_refs(self) -> None:
        entries = [
            ChangelogEntry(
                category=ChangeCategory.FEATURES,
                title="feat: something",
            ),
        ]
        result = format_changelog("1.0.0", entries, date="2026-02-28")
        assert "- something\n" in result

    def test_title_prefix_stripped(self) -> None:
        entries = [
            ChangelogEntry(
                category=ChangeCategory.FEATURES,
                title="feat(scope): add thing",
                issue_number=1,
                pr_number=2,
            ),
        ]
        result = format_changelog("1.0.0", entries, date="2026-02-28")
        assert "- add thing (#1, PR #2)" in result
        assert "feat" not in result.split("### Features")[1].split("\n")[1]

    def test_breaking_change_title_stripped_cleanly(self) -> None:
        entries = [
            ChangelogEntry(
                category=ChangeCategory.FEATURES,
                title="feat!: breaking change",
            ),
        ]
        result = format_changelog("1.0.0", entries, date="2026-02-28")
        assert "- breaking change\n" in result

    def test_non_conventional_title_unchanged(self) -> None:
        entries = [
            ChangelogEntry(
                category=ChangeCategory.MISCELLANEOUS,
                title="Add new feature",
            ),
        ]
        result = format_changelog("1.0.0", entries, date="2026-02-28")
        assert "- Add new feature\n" in result

    def test_non_conventional_colon_prefix_preserved(self) -> None:
        """Titles like 'HTTP: ...' or 'WIP: ...' must NOT have their prefix stripped."""
        entries = [
            ChangelogEntry(
                category=ChangeCategory.MISCELLANEOUS,
                title="HTTP: improve request handling",
            ),
        ]
        result = format_changelog("1.0.0", entries, date="2026-02-28")
        assert "- HTTP: improve request handling\n" in result

    def test_chore_prefix_preserved(self) -> None:
        """'chore:' is not in the categorized prefix map — keep it in display."""
        entries = [
            ChangelogEntry(
                category=ChangeCategory.MISCELLANEOUS,
                title="chore: update dependencies",
            ),
        ]
        result = format_changelog("1.0.0", entries, date="2026-02-28")
        assert "- chore: update dependencies\n" in result

    def test_summary_rendered_below_title(self) -> None:
        """Entry summaries are rendered as indented lines below the title."""
        entries = [
            ChangelogEntry(
                category=ChangeCategory.FEATURES,
                title="feat: add auth",
                summary="- Added OAuth flow\n- Added token refresh",
                issue_number=1,
                pr_number=2,
            ),
        ]
        result = format_changelog("1.0.0", entries, date="2026-02-28")
        assert "- add auth (#1, PR #2)\n" in result
        assert "  - Added OAuth flow\n" in result
        assert "  - Added token refresh\n" in result

    def test_summary_blank_lines_skipped(self) -> None:
        """Blank lines in summaries are skipped rather than producing empty indented lines."""
        entries = [
            ChangelogEntry(
                category=ChangeCategory.FEATURES,
                title="feat: add feature",
                summary="- Line 1\n\n- Line 2",
                issue_number=1,
                pr_number=2,
            ),
        ]
        result = format_changelog("1.0.0", entries, date="2026-02-28")
        assert "  - Line 1\n" in result
        assert "  - Line 2\n" in result
        # No empty indented line
        assert "  \n" not in result

    def test_empty_summary_not_rendered(self) -> None:
        """Entries with empty summaries produce no indented lines."""
        entries = [
            ChangelogEntry(
                category=ChangeCategory.FEATURES,
                title="feat: add feature",
                summary="",
                issue_number=1,
                pr_number=2,
            ),
        ]
        result = format_changelog("1.0.0", entries, date="2026-02-28")
        lines = result.strip().splitlines()
        # The entry line should be the last non-empty line in the Features section
        entry_line = [line for line in lines if line.startswith("- ")][0]
        assert entry_line == "- add feature (#1, PR #2)"
        # No indented summary lines
        assert not any(line.startswith("  ") for line in lines)


# ---------------------------------------------------------------------------
# generate_changelog (async integration)
# ---------------------------------------------------------------------------


class TestGenerateChangelog:
    @pytest.mark.asyncio
    async def test_generates_from_sub_issues(self) -> None:
        pr_manager = AsyncMock()
        pr_manager.get_pr_for_issue = AsyncMock(side_effect=[101, 102])
        pr_manager.get_pr_title_and_body = AsyncMock(
            side_effect=[
                ("feat: add auth", "## Summary\n- Added OAuth\n\n## Details\nMore"),
                ("fix: crash on login", "## Summary\n- Fixed null pointer\n"),
            ]
        )

        result = await generate_changelog(
            pr_manager=pr_manager,
            sub_issues=[1, 2],
            version="1.0.0",
            date="2026-02-28",
        )

        assert "## [1.0.0] - 2026-02-28" in result
        assert "### Features" in result
        assert "add auth" in result
        assert "Added OAuth" in result
        assert "### Bug Fixes" in result
        assert "crash on login" in result
        assert "Fixed null pointer" in result

    @pytest.mark.asyncio
    async def test_skips_issues_without_prs(self) -> None:
        pr_manager = AsyncMock()
        pr_manager.get_pr_for_issue = AsyncMock(side_effect=[0, 102])
        pr_manager.get_pr_title_and_body = AsyncMock(
            return_value=("feat: only one", "## Summary\n- One change\n")
        )

        result = await generate_changelog(
            pr_manager=pr_manager,
            sub_issues=[1, 2],
            version="1.0.0",
            date="2026-02-28",
        )

        assert "only one" in result
        # get_pr_title_and_body should only be called once (for issue 2)
        pr_manager.get_pr_title_and_body.assert_called_once_with(102)

    @pytest.mark.asyncio
    async def test_skips_prs_with_empty_title(self) -> None:
        pr_manager = AsyncMock()
        pr_manager.get_pr_for_issue = AsyncMock(return_value=101)
        pr_manager.get_pr_title_and_body = AsyncMock(return_value=("", "some body"))

        result = await generate_changelog(
            pr_manager=pr_manager,
            sub_issues=[1],
            version="1.0.0",
            date="2026-02-28",
        )

        assert "No changes recorded." in result

    @pytest.mark.asyncio
    async def test_handles_empty_sub_issues(self) -> None:
        pr_manager = AsyncMock()

        result = await generate_changelog(
            pr_manager=pr_manager,
            sub_issues=[],
            version="1.0.0",
            date="2026-02-28",
        )

        assert "No changes recorded." in result
        pr_manager.get_pr_for_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_missing_pr_body(self) -> None:
        pr_manager = AsyncMock()
        pr_manager.get_pr_for_issue = AsyncMock(return_value=101)
        pr_manager.get_pr_title_and_body = AsyncMock(
            return_value=("feat: add feature", "")
        )

        result = await generate_changelog(
            pr_manager=pr_manager,
            sub_issues=[1],
            version="1.0.0",
            date="2026-02-28",
        )

        assert "add feature" in result


# ---------------------------------------------------------------------------
# EpicCompletionChecker changelog integration
# ---------------------------------------------------------------------------


def _make_epic_issue(number: int, sub_issues: list[int]) -> GitHubIssue:
    lines = [f"- [ ] #{n} — Sub-issue {n}" for n in sub_issues]
    body = "## Epic\n\n" + "\n".join(lines)
    return GitHubIssue(
        number=number, title="[Epic] Test", body=body, labels=["hydraflow-epic"]
    )


class TestEpicChangelogIntegration:
    @pytest.mark.asyncio
    async def test_epic_close_generates_changelog_and_release(self) -> None:
        epic = _make_epic_issue(100, [1, 2])
        epic = GitHubIssue(
            number=100,
            title="[Epic] v1.0.0 — Features",
            body=epic.body,
            labels=["hydraflow-epic"],
        )
        sub_issues = {
            1: IssueFactory.create(
                number=1, labels=["hydraflow-fixed"], title="Issue #1"
            ),
            2: IssueFactory.create(
                number=2, labels=["hydraflow-fixed"], title="Issue #2"
            ),
        }
        config = ConfigFactory.create(
            epic_label=["hydraflow-epic"],
            release_on_epic_close=True,
        )
        prs = AsyncMock()
        prs.create_tag = AsyncMock(return_value=True)
        prs.create_release = AsyncMock(return_value=True)
        fetcher = AsyncMock()
        fetcher.fetch_issues_by_labels = AsyncMock(return_value=[epic])
        fetcher.fetch_issue_by_number = AsyncMock(side_effect=sub_issues.get)
        checker = EpicCompletionChecker(config, prs, fetcher)

        changelog_body = "## [1.0.0] - 2026-02-28\n\n### Features\n- stuff"
        with patch(
            "epic.generate_changelog",
            AsyncMock(return_value=changelog_body),
        ) as mock_gen:
            await checker.check_and_close_epics(1)

            # Changelog generation was called with the real version, not "epic-N"
            mock_gen.assert_called_once()
            call_kwargs = mock_gen.call_args
            assert call_kwargs[1]["sub_issues"] == [1, 2]
            assert call_kwargs[1]["version"] == "1.0.0"

        # Release was created
        prs.create_tag.assert_called_once_with("v1.0.0")
        prs.create_release.assert_called_once()
        release_args = prs.create_release.call_args
        assert release_args[0][0] == "v1.0.0"

        # Comment includes release URL
        comment = prs.post_comment.call_args[0][1]
        assert "All sub-issues completed" in comment
        assert "Release" in comment

    @pytest.mark.asyncio
    async def test_epic_close_skips_release_when_changelog_empty(self) -> None:
        epic = _make_epic_issue(100, [1])
        sub_issues = {
            1: IssueFactory.create(
                number=1, labels=["hydraflow-fixed"], title="Issue #1"
            ),
        }
        config = ConfigFactory.create(epic_label=["hydraflow-epic"])
        prs = AsyncMock()
        fetcher = AsyncMock()
        fetcher.fetch_issues_by_labels = AsyncMock(return_value=[epic])
        fetcher.fetch_issue_by_number = AsyncMock(side_effect=sub_issues.get)
        checker = EpicCompletionChecker(config, prs, fetcher)

        with patch("epic.generate_changelog", AsyncMock(return_value="")):
            await checker.check_and_close_epics(1)

        # No release when changelog is empty
        prs.create_release.assert_not_called()

    @pytest.mark.asyncio
    async def test_epic_close_writes_changelog_file(self, tmp_path: Path) -> None:
        epic = _make_epic_issue(100, [1])
        sub_issues = {
            1: IssueFactory.create(
                number=1, labels=["hydraflow-fixed"], title="Issue #1"
            ),
        }
        changelog_path = tmp_path / "CHANGELOG.md"
        config = ConfigFactory.create(
            epic_label=["hydraflow-epic"],
            repo_root=tmp_path,
        )
        # Set changelog_file directly
        config.changelog_file = "CHANGELOG.md"

        prs = AsyncMock()
        fetcher = AsyncMock()
        fetcher.fetch_issues_by_labels = AsyncMock(return_value=[epic])
        fetcher.fetch_issue_by_number = AsyncMock(side_effect=sub_issues.get)
        checker = EpicCompletionChecker(config, prs, fetcher)

        changelog_content = "## [epic-100] - 2026-02-28\n\n### Features\n- stuff\n"
        with patch(
            "epic.generate_changelog", AsyncMock(return_value=changelog_content)
        ):
            await checker.check_and_close_epics(1)

        assert changelog_path.exists()
        content = changelog_path.read_text()
        assert "Features" in content

    @pytest.mark.asyncio
    async def test_epic_close_no_changelog_file_when_not_configured(self) -> None:
        epic = _make_epic_issue(100, [1])
        epic = GitHubIssue(
            number=100,
            title="[Epic] v1.0.0 — Feature",
            body=epic.body,
            labels=["hydraflow-epic"],
        )
        sub_issues = {
            1: IssueFactory.create(
                number=1, labels=["hydraflow-fixed"], title="Issue #1"
            ),
        }
        config = ConfigFactory.create(
            epic_label=["hydraflow-epic"],
            release_on_epic_close=True,
        )
        # Default is empty string — no file output
        assert config.changelog_file == ""

        prs = AsyncMock()
        prs.create_tag = AsyncMock(return_value=True)
        prs.create_release = AsyncMock(return_value=True)
        fetcher = AsyncMock()
        fetcher.fetch_issues_by_labels = AsyncMock(return_value=[epic])
        fetcher.fetch_issue_by_number = AsyncMock(side_effect=sub_issues.get)
        checker = EpicCompletionChecker(config, prs, fetcher)

        with patch(
            "epic.generate_changelog",
            AsyncMock(return_value="## [epic-100]\n\n### Features\n- stuff"),
        ):
            await checker.check_and_close_epics(1)

        # Release still created even without changelog file config
        prs.create_release.assert_called_once()

    @pytest.mark.asyncio
    async def test_changelog_generation_failure_doesnt_block_close(self) -> None:
        epic = _make_epic_issue(100, [1])
        sub_issues = {
            1: IssueFactory.create(
                number=1, labels=["hydraflow-fixed"], title="Issue #1"
            ),
        }
        config = ConfigFactory.create(epic_label=["hydraflow-epic"])
        prs = AsyncMock()
        fetcher = AsyncMock()
        fetcher.fetch_issues_by_labels = AsyncMock(return_value=[epic])
        fetcher.fetch_issue_by_number = AsyncMock(side_effect=sub_issues.get)
        checker = EpicCompletionChecker(config, prs, fetcher)

        with patch(
            "epic.generate_changelog",
            AsyncMock(side_effect=RuntimeError("API failure")),
        ):
            await checker.check_and_close_epics(1)

        # Epic should still be closed despite changelog failure
        prs.close_issue.assert_called_once_with(100)
        # No release when changelog generation fails
        prs.create_release.assert_not_called()

    @pytest.mark.asyncio
    async def test_release_and_changelog_file_generates_once(
        self, tmp_path: Path
    ) -> None:
        """With both release_on_epic_close and changelog_file set, generate_changelog
        should only be called once — the result is reused for both paths."""
        epic = _make_epic_issue(100, [1])
        epic = GitHubIssue(
            number=100,
            title="[Epic] v2.0.0 — Big Release",
            body=epic.body,
            labels=["hydraflow-epic"],
        )
        sub_issues = {
            1: IssueFactory.create(
                number=1, labels=["hydraflow-fixed"], title="Issue #1"
            ),
        }
        config = ConfigFactory.create(
            epic_label=["hydraflow-epic"],
            release_on_epic_close=True,
            repo_root=tmp_path,
        )
        config.changelog_file = "CHANGELOG.md"

        prs = AsyncMock()
        prs.create_tag = AsyncMock(return_value=True)
        prs.create_release = AsyncMock(return_value=True)
        fetcher = AsyncMock()
        fetcher.fetch_issues_by_labels = AsyncMock(return_value=[epic])
        fetcher.fetch_issue_by_number = AsyncMock(side_effect=sub_issues.get)
        checker = EpicCompletionChecker(config, prs, fetcher)

        changelog_content = "## [2.0.0] - 2026-02-28\n\n### Features\n- big thing\n"
        with patch(
            "epic.generate_changelog",
            AsyncMock(return_value=changelog_content),
        ) as mock_gen:
            await checker.check_and_close_epics(1)

        # Only one changelog generation despite both release and file paths
        mock_gen.assert_called_once()
        # Release was created
        prs.create_release.assert_called_once()
        # File was written
        changelog_path = tmp_path / "CHANGELOG.md"
        assert changelog_path.exists()
        assert "2.0.0" in changelog_path.read_text()

    @pytest.mark.asyncio
    async def test_write_changelog_prepends_after_heading(self, tmp_path: Path) -> None:
        """Existing file starting with '# Changelog' gets new entry inserted after heading."""
        epic = _make_epic_issue(100, [1])
        sub_issues = {
            1: IssueFactory.create(
                number=1, labels=["hydraflow-fixed"], title="Issue #1"
            ),
        }
        changelog_path = tmp_path / "CHANGELOG.md"
        # Pre-populate with a heading + prior release
        changelog_path.write_text(
            "# Changelog\n\n## [0.9.0] - 2025-01-01\n\n### Features\n- old thing\n",
            encoding="utf-8",
        )
        config = ConfigFactory.create(
            epic_label=["hydraflow-epic"],
            repo_root=tmp_path,
        )
        config.changelog_file = "CHANGELOG.md"

        prs = AsyncMock()
        fetcher = AsyncMock()
        fetcher.fetch_issues_by_labels = AsyncMock(return_value=[epic])
        fetcher.fetch_issue_by_number = AsyncMock(side_effect=sub_issues.get)
        checker = EpicCompletionChecker(config, prs, fetcher)

        new_entry = "## [1.0.0] - 2026-02-28\n\n### Features\n- new thing\n"
        with patch("epic.generate_changelog", AsyncMock(return_value=new_entry)):
            await checker.check_and_close_epics(1)

        content = changelog_path.read_text()
        # Heading must be first; new entry must precede old entry
        assert content.startswith("# Changelog\n")
        new_pos = content.index("## [1.0.0]")
        old_pos = content.index("## [0.9.0]")
        assert new_pos < old_pos

    @pytest.mark.asyncio
    async def test_write_changelog_prepends_to_existing_without_heading(
        self, tmp_path: Path
    ) -> None:
        """Existing file without a top-level heading gets new entry prepended."""
        epic = _make_epic_issue(100, [1])
        sub_issues = {
            1: IssueFactory.create(
                number=1, labels=["hydraflow-fixed"], title="Issue #1"
            ),
        }
        changelog_path = tmp_path / "CHANGELOG.md"
        changelog_path.write_text(
            "## [0.9.0] - 2025-01-01\n\n### Features\n- old thing\n",
            encoding="utf-8",
        )
        config = ConfigFactory.create(
            epic_label=["hydraflow-epic"],
            repo_root=tmp_path,
        )
        config.changelog_file = "CHANGELOG.md"

        prs = AsyncMock()
        fetcher = AsyncMock()
        fetcher.fetch_issues_by_labels = AsyncMock(return_value=[epic])
        fetcher.fetch_issue_by_number = AsyncMock(side_effect=sub_issues.get)
        checker = EpicCompletionChecker(config, prs, fetcher)

        new_entry = "## [1.0.0] - 2026-02-28\n\n### Features\n- new thing\n"
        with patch("epic.generate_changelog", AsyncMock(return_value=new_entry)):
            await checker.check_and_close_epics(1)

        content = changelog_path.read_text()
        new_pos = content.index("## [1.0.0]")
        old_pos = content.index("## [0.9.0]")
        assert new_pos < old_pos

    @pytest.mark.asyncio
    async def test_write_changelog_file_blocks_absolute_path_traversal(
        self, tmp_path: Path
    ) -> None:
        """Absolute changelog_file paths outside repo_root must be silently skipped."""
        epic = _make_epic_issue(100, [1])
        sub_issues = {
            1: IssueFactory.create(
                number=1, labels=["hydraflow-fixed"], title="Issue #1"
            ),
        }
        config = ConfigFactory.create(
            epic_label=["hydraflow-epic"],
            repo_root=tmp_path,
        )
        evil_path = tmp_path.parent / "evil_changelog.md"
        config.changelog_file = str(evil_path)

        prs = AsyncMock()
        fetcher = AsyncMock()
        fetcher.fetch_issues_by_labels = AsyncMock(return_value=[epic])
        fetcher.fetch_issue_by_number = AsyncMock(side_effect=sub_issues.get)
        checker = EpicCompletionChecker(config, prs, fetcher)

        changelog_content = "## [epic-100]\n\n### Features\n- stuff\n"
        with patch(
            "epic.generate_changelog", AsyncMock(return_value=changelog_content)
        ):
            await checker.check_and_close_epics(1)

        assert not evil_path.exists()
        prs.close_issue.assert_called_once_with(100)

    @pytest.mark.asyncio
    async def test_write_changelog_file_blocks_path_traversal(
        self, tmp_path: Path
    ) -> None:
        """changelog_file values that resolve outside repo_root must be silently skipped."""
        epic = _make_epic_issue(100, [1])
        sub_issues = {
            1: IssueFactory.create(
                number=1, labels=["hydraflow-fixed"], title="Issue #1"
            ),
        }
        config = ConfigFactory.create(
            epic_label=["hydraflow-epic"],
            repo_root=tmp_path,
        )
        # Attempt path traversal
        config.changelog_file = "../../outside.md"

        prs = AsyncMock()
        fetcher = AsyncMock()
        fetcher.fetch_issues_by_labels = AsyncMock(return_value=[epic])
        fetcher.fetch_issue_by_number = AsyncMock(side_effect=sub_issues.get)
        checker = EpicCompletionChecker(config, prs, fetcher)

        changelog_content = "## [epic-100]\n\n### Features\n- stuff\n"
        with patch(
            "epic.generate_changelog", AsyncMock(return_value=changelog_content)
        ):
            await checker.check_and_close_epics(1)

        # The traversal target must not have been written
        outside_path = (tmp_path / "../../outside.md").resolve()
        assert not outside_path.exists()
        # Epic is still closed normally
        prs.close_issue.assert_called_once_with(100)
