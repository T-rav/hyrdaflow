"""Tests for release creation on epic completion."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from epic import (
    EpicCompletionChecker,
    extract_version_from_title,
)
from models import GitHubIssue, Release
from state import StateTracker
from tests.conftest import IssueFactory
from tests.helpers import ConfigFactory

# ---------------------------------------------------------------------------
# Release model
# ---------------------------------------------------------------------------


class TestReleaseModel:
    def test_release_has_expected_defaults(self) -> None:
        release = Release(version="1.0.0", epic_number=100)
        assert release.version == "1.0.0"
        assert release.epic_number == 100
        assert release.sub_issues == []
        assert release.pr_numbers == []
        assert release.status == "pending"
        assert release.released_at is None
        assert release.changelog == ""
        assert release.tag == ""

    def test_full_construction(self) -> None:
        now = datetime.now(UTC).isoformat()
        release = Release(
            version="2.1.0",
            epic_number=200,
            sub_issues=[1, 2, 3],
            pr_numbers=[10, 11, 12],
            status="released",
            created_at=now,
            released_at=now,
            changelog="## Changes\n- Feature A",
            tag="v2.1.0",
        )
        assert release.status == "released"
        assert release.sub_issues == [1, 2, 3]
        assert release.pr_numbers == [10, 11, 12]
        assert release.tag == "v2.1.0"
        assert release.released_at == now

    def test_serialization_roundtrip(self) -> None:
        release = Release(
            version="1.0.0",
            epic_number=100,
            sub_issues=[1, 2],
            tag="v1.0.0",
        )
        data = json.loads(release.model_dump_json())
        restored = Release.model_validate(data)
        assert restored.version == release.version
        assert restored.epic_number == release.epic_number
        assert restored.sub_issues == release.sub_issues

    def test_invalid_status_rejected(self) -> None:
        with pytest.raises(Exception):  # noqa: B017, PT011
            Release(version="1.0.0", epic_number=1, status="invalid")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# extract_version_from_title
# ---------------------------------------------------------------------------


class TestExtractVersionFromTitle:
    def test_extracts_semver_with_v_prefix(self) -> None:
        assert extract_version_from_title("[Epic] v1.2.0 — Feature set") == "1.2.0"

    def test_extracts_semver_without_prefix(self) -> None:
        assert extract_version_from_title("[Epic] 2.0.0 release") == "2.0.0"

    def test_extracts_two_part_version(self) -> None:
        assert extract_version_from_title("Release 3.1") == "3.1"

    def test_extracts_single_number(self) -> None:
        assert extract_version_from_title("v5 release") == "5"

    def test_returns_empty_for_no_version(self) -> None:
        assert extract_version_from_title("[Epic] No version here") == ""

    def test_returns_empty_for_empty_string(self) -> None:
        assert extract_version_from_title("") == ""

    def test_extracts_first_version_match(self) -> None:
        assert extract_version_from_title("v1.0 and v2.0") == "1.0"

    def test_handles_complex_title(self) -> None:
        title = "[Epic] Release v0.9.1-beta — Improvements"
        assert extract_version_from_title(title) == "0.9.1"

    def test_bare_integer_not_extracted(self) -> None:
        # "Phase 3" or "Sprint 5" should NOT be treated as a release version
        assert extract_version_from_title("[Epic] Phase 3 Backend") == ""
        assert extract_version_from_title("[Epic] Sprint 5 improvements") == ""

    def test_bare_integer_without_prefix_not_extracted(self) -> None:
        # A bare number without v-prefix should not create a spurious release
        assert extract_version_from_title("5 Features") == ""


# ---------------------------------------------------------------------------
# Release state tracking
# ---------------------------------------------------------------------------


class TestReleaseStateTracking:
    def test_upsert_and_get(self, tmp_path: Path) -> None:
        state = StateTracker(tmp_path / "state.json")
        release = Release(
            version="1.0.0",
            epic_number=100,
            sub_issues=[1, 2],
            tag="v1.0.0",
        )
        state.upsert_release(release)
        got = state.get_release(100)
        assert got is not None
        assert got.version == "1.0.0"
        assert got.tag == "v1.0.0"
        assert got.sub_issues == [1, 2]

    def test_get_returns_none_for_missing(self, tmp_path: Path) -> None:
        state = StateTracker(tmp_path / "state.json")
        assert state.get_release(999) is None

    def test_upsert_updates_existing(self, tmp_path: Path) -> None:
        state = StateTracker(tmp_path / "state.json")
        release = Release(version="1.0.0", epic_number=100)
        state.upsert_release(release)

        updated = Release(
            version="1.0.0",
            epic_number=100,
            status="released",
            tag="v1.0.0",
        )
        state.upsert_release(updated)
        got = state.get_release(100)
        assert got is not None
        assert got.status == "released"
        assert got.tag == "v1.0.0"

    def test_get_all_releases(self, tmp_path: Path) -> None:
        state = StateTracker(tmp_path / "state.json")
        state.upsert_release(Release(version="1.0", epic_number=10))
        state.upsert_release(Release(version="2.0", epic_number=20))
        all_releases = state.get_all_releases()
        assert len(all_releases) == 2
        assert "10" in all_releases
        assert "20" in all_releases

    def test_release_persists_across_load(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        state = StateTracker(state_file)
        state.upsert_release(Release(version="1.0.0", epic_number=100, tag="v1.0.0"))
        # Reload state from disk
        state2 = StateTracker(state_file)
        got = state2.get_release(100)
        assert got is not None
        assert got.version == "1.0.0"

    def test_get_release_returns_deep_copy(self, tmp_path: Path) -> None:
        state = StateTracker(tmp_path / "state.json")
        state.upsert_release(
            Release(version="1.0.0", epic_number=100, sub_issues=[1, 2])
        )
        copy = state.get_release(100)
        assert copy is not None
        copy.sub_issues.append(99)
        original = state.get_release(100)
        assert original is not None
        assert 99 not in original.sub_issues


# ---------------------------------------------------------------------------
# Config fields
# ---------------------------------------------------------------------------


class TestReleaseConfig:
    def test_release_config_has_expected_defaults(self) -> None:
        config = ConfigFactory.create()
        assert config.release_on_epic_close is False
        assert config.release_version_source == "epic_title"
        assert config.release_tag_prefix == "v"

    def test_release_config_enabled_flag(self) -> None:
        config = ConfigFactory.create(release_on_epic_close=True)
        assert config.release_on_epic_close is True

    def test_custom_prefix(self) -> None:
        config = ConfigFactory.create(release_tag_prefix="release-")
        assert config.release_tag_prefix == "release-"


# ---------------------------------------------------------------------------
# PRManager.create_tag / create_release
# ---------------------------------------------------------------------------


def _make_pr_manager(*, dry_run: bool = False):
    """Build a PRManager with an EventBus for testing."""
    from events import EventBus
    from pr_manager import PRManager

    config = ConfigFactory.create(dry_run=dry_run, repo="org/repo")
    bus = EventBus()
    return PRManager(config, bus)


class TestPRManagerReleaseMethods:
    @pytest.mark.asyncio
    async def test_create_tag_dry_run(self) -> None:
        prs = _make_pr_manager(dry_run=True)
        result = await prs.create_tag("v1.0.0")
        assert result is True

    @pytest.mark.asyncio
    async def test_create_release_dry_run(self) -> None:
        prs = _make_pr_manager(dry_run=True)
        result = await prs.create_release("v1.0.0", "Release v1.0.0", "Changes")
        assert result is True

    @pytest.mark.asyncio
    async def test_create_tag_success(self) -> None:
        prs = _make_pr_manager()
        with patch.object(prs, "_run_gh", new_callable=AsyncMock, return_value=""):
            result = await prs.create_tag("v1.0.0")
        assert result is True

    @pytest.mark.asyncio
    async def test_create_tag_failure(self) -> None:
        prs = _make_pr_manager()
        with patch.object(
            prs,
            "_run_gh",
            new_callable=AsyncMock,
            side_effect=RuntimeError("git error"),
        ):
            result = await prs.create_tag("v1.0.0")
        assert result is False

    @pytest.mark.asyncio
    async def test_create_release_success(self) -> None:
        prs = _make_pr_manager()
        with patch.object(prs, "_run_gh", new_callable=AsyncMock, return_value=""):
            result = await prs.create_release("v1.0.0", "Release", "Body")
        assert result is True

    @pytest.mark.asyncio
    async def test_create_release_failure(self) -> None:
        prs = _make_pr_manager()
        with patch.object(
            prs,
            "_run_gh",
            new_callable=AsyncMock,
            side_effect=RuntimeError("gh error"),
        ):
            result = await prs.create_release("v1.0.0", "Release", "Body")
        assert result is False


# ---------------------------------------------------------------------------
# EpicCompletionChecker with release
# ---------------------------------------------------------------------------


def _make_epic_issue(
    number: int, sub_issues: list[int], title: str = "[Epic] Test"
) -> GitHubIssue:
    lines = [f"- [ ] #{n} — Sub-issue {n}" for n in sub_issues]
    body = "## Epic\n\n" + "\n".join(lines)
    return GitHubIssue(number=number, title=title, body=body, labels=["hydraflow-epic"])


def _make_release_checker(
    *,
    epics: list[GitHubIssue] | None = None,
    sub_issues: dict[int, GitHubIssue] | None = None,
    release_on_epic_close: bool = False,
    release_tag_prefix: str = "v",
    tmp_path: Path | None = None,
) -> tuple[EpicCompletionChecker, AsyncMock, AsyncMock, StateTracker | None]:
    config = ConfigFactory.create(
        epic_label=["hydraflow-epic"],
        release_on_epic_close=release_on_epic_close,
        release_tag_prefix=release_tag_prefix,
        repo="test-org/test-repo",
    )
    prs = AsyncMock()
    fetcher = AsyncMock()
    fetcher.fetch_issues_by_labels = AsyncMock(return_value=epics or [])
    sub_map = sub_issues or {}

    async def fetch_by_number(num: int) -> GitHubIssue | None:
        return sub_map.get(num)

    fetcher.fetch_issue_by_number = AsyncMock(side_effect=fetch_by_number)

    state = None
    if tmp_path is not None:
        state = StateTracker(tmp_path / "state.json")

    prs.create_tag = AsyncMock(return_value=True)
    prs.create_release = AsyncMock(return_value=True)
    prs._run_gh = AsyncMock(return_value="[]")

    checker = EpicCompletionChecker(config, prs, fetcher, state=state)
    return checker, prs, fetcher, state


class TestEpicCompletionWithRelease:
    @pytest.mark.asyncio
    async def test_no_release_when_feature_disabled(self) -> None:
        epic = _make_epic_issue(100, [1, 2], title="[Epic] v1.0.0 — Features")
        sub_issues = {
            1: IssueFactory.create(
                number=1, labels=["hydraflow-fixed"], title="Issue #1"
            ),
            2: IssueFactory.create(
                number=2, labels=["hydraflow-fixed"], title="Issue #2"
            ),
            100: GitHubIssue(
                number=100,
                title="[Epic] v1.0.0 — Features",
                body="",
                labels=["hydraflow-epic"],
            ),
        }
        checker, prs, _, _ = _make_release_checker(
            epics=[epic], sub_issues=sub_issues, release_on_epic_close=False
        )

        await checker.check_and_close_epics(1)

        prs.close_issue.assert_called_once_with(100)
        prs.create_tag.assert_not_called()
        prs.create_release.assert_not_called()

    @pytest.mark.asyncio
    async def test_release_created_when_feature_enabled(self, tmp_path: Path) -> None:
        epic = _make_epic_issue(100, [1, 2], title="[Epic] v1.0.0 — Features")
        sub_issues = {
            1: IssueFactory.create(
                number=1, labels=["hydraflow-fixed"], title="Add login"
            ),
            2: IssueFactory.create(
                number=2, labels=["hydraflow-fixed"], title="Fix auth"
            ),
            100: GitHubIssue(
                number=100,
                title="[Epic] v1.0.0 — Features",
                body="",
                labels=["hydraflow-epic"],
            ),
        }
        checker, prs, _, state = _make_release_checker(
            epics=[epic],
            sub_issues=sub_issues,
            release_on_epic_close=True,
            tmp_path=tmp_path,
        )

        changelog_body = "## [epic-100]\n\n### Features\n- Add login\n- Fix auth\n"
        with patch(
            "epic.generate_changelog",
            AsyncMock(return_value=changelog_body),
        ):
            await checker.check_and_close_epics(1)

        prs.create_tag.assert_called_once_with("v1.0.0")
        prs.create_release.assert_called_once()
        call_args = prs.create_release.call_args
        assert call_args[0][0] == "v1.0.0"
        assert "Release v1.0.0" in call_args[0][1]
        assert "Add login" in call_args[0][2]
        assert "Fix auth" in call_args[0][2]

        # Release state persisted
        assert state is not None
        release = state.get_release(100)
        assert release is not None
        assert release.version == "1.0.0"
        assert release.tag == "v1.0.0"
        assert release.status == "released"
        assert release.sub_issues == [1, 2]

    @pytest.mark.asyncio
    async def test_release_url_in_close_comment(self, tmp_path: Path) -> None:
        epic = _make_epic_issue(100, [1], title="[Epic] v2.0.0 release")
        sub_issues = {
            1: IssueFactory.create(
                number=1, labels=["hydraflow-fixed"], title="Feature A"
            ),
            100: GitHubIssue(
                number=100,
                title="[Epic] v2.0.0 release",
                body="",
                labels=["hydraflow-epic"],
            ),
        }
        checker, prs, _, _ = _make_release_checker(
            epics=[epic],
            sub_issues=sub_issues,
            release_on_epic_close=True,
            tmp_path=tmp_path,
        )

        with patch("epic.generate_changelog", AsyncMock(return_value="changelog")):
            await checker.check_and_close_epics(1)

        comment = prs.post_comment.call_args[0][1]
        assert "Release" in comment
        assert "test-org/test-repo/releases/tag/v2.0.0" in comment

    @pytest.mark.asyncio
    async def test_no_release_when_no_version_in_title(self) -> None:
        epic = _make_epic_issue(100, [1], title="[Epic] Feature set without version")
        sub_issues = {
            1: IssueFactory.create(number=1, labels=["hydraflow-fixed"], title="Sub"),
            100: GitHubIssue(
                number=100,
                title="[Epic] Feature set without version",
                body="",
                labels=["hydraflow-epic"],
            ),
        }
        checker, prs, _, _ = _make_release_checker(
            epics=[epic], sub_issues=sub_issues, release_on_epic_close=True
        )

        await checker.check_and_close_epics(1)

        prs.close_issue.assert_called_once_with(100)
        prs.create_tag.assert_not_called()
        prs.create_release.assert_not_called()

    @pytest.mark.asyncio
    async def test_custom_tag_prefix(self, tmp_path: Path) -> None:
        epic = _make_epic_issue(100, [1], title="[Epic] 3.0.0 release")
        sub_issues = {
            1: IssueFactory.create(number=1, labels=["hydraflow-fixed"], title="Sub"),
            100: GitHubIssue(
                number=100,
                title="[Epic] 3.0.0 release",
                body="",
                labels=["hydraflow-epic"],
            ),
        }
        checker, prs, _, _ = _make_release_checker(
            epics=[epic],
            sub_issues=sub_issues,
            release_on_epic_close=True,
            release_tag_prefix="release-",
            tmp_path=tmp_path,
        )

        await checker.check_and_close_epics(1)

        prs.create_tag.assert_called_once_with("release-3.0.0")

    @pytest.mark.asyncio
    async def test_tag_failure_skips_release(self) -> None:
        epic = _make_epic_issue(100, [1], title="[Epic] v1.0.0")
        sub_issues = {
            1: IssueFactory.create(number=1, labels=["hydraflow-fixed"], title="Sub"),
            100: GitHubIssue(
                number=100, title="[Epic] v1.0.0", body="", labels=["hydraflow-epic"]
            ),
        }
        checker, prs, _, _ = _make_release_checker(
            epics=[epic], sub_issues=sub_issues, release_on_epic_close=True
        )
        prs.create_tag = AsyncMock(return_value=False)

        await checker.check_and_close_epics(1)

        prs.create_tag.assert_called_once()
        prs.create_release.assert_not_called()
        # Epic should still close
        prs.close_issue.assert_called_once_with(100)

    @pytest.mark.asyncio
    async def test_release_failure_still_closes_epic(self) -> None:
        epic = _make_epic_issue(100, [1], title="[Epic] v1.0.0")
        sub_issues = {
            1: IssueFactory.create(number=1, labels=["hydraflow-fixed"], title="Sub"),
            100: GitHubIssue(
                number=100, title="[Epic] v1.0.0", body="", labels=["hydraflow-epic"]
            ),
        }
        checker, prs, _, _ = _make_release_checker(
            epics=[epic], sub_issues=sub_issues, release_on_epic_close=True
        )
        prs.create_release = AsyncMock(return_value=False)

        await checker.check_and_close_epics(1)

        prs.close_issue.assert_called_once_with(100)
        # No release URL in comment
        comment = prs.post_comment.call_args[0][1]
        assert "releases/tag" not in comment

    @pytest.mark.asyncio
    async def test_existing_tests_still_pass_without_state(self) -> None:
        """Backward compatibility: EpicCompletionChecker works without state."""
        epic = _make_epic_issue(100, [1, 2])
        sub_issues = {
            1: IssueFactory.create(number=1, labels=["hydraflow-fixed"], title="A"),
            2: IssueFactory.create(number=2, labels=["hydraflow-fixed"], title="B"),
        }
        checker, prs, _, _ = _make_release_checker(epics=[epic], sub_issues=sub_issues)
        # No state, no release_on_epic_close
        await checker.check_and_close_epics(1)
        prs.close_issue.assert_called_once_with(100)
