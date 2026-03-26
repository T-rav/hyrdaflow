"""Tests for manifest issue syncer."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from manifest_issue_syncer import ManifestIssueSyncer
from state import StateTracker
from tests.helpers import ConfigFactory


def _make_prs_mock(
    existing_issue: int | None = None,
    new_issue_number: int = 42,
) -> MagicMock:
    prs = MagicMock()
    prs.find_issue_number_by_label_and_title = AsyncMock(return_value=existing_issue)
    prs.create_issue = AsyncMock(return_value=new_issue_number)
    prs.post_comment = AsyncMock()
    prs.close_issue = AsyncMock()
    return prs


@pytest.mark.asyncio
async def test_manifest_issue_syncer_posts_comment(tmp_path: Path) -> None:
    config = ConfigFactory.create(
        repo_root=tmp_path, git_user_name="tester", manifest_issue_enabled=True
    )
    state = StateTracker(config.state_file)
    prs = _make_prs_mock(existing_issue=None, new_issue_number=123)

    syncer = ManifestIssueSyncer(config, state, prs)
    await syncer.sync("## Manifest Body", "deadbeef", source="unit-test")

    prs.find_issue_number_by_label_and_title.assert_awaited_once_with(
        "hydraflow-manifest", "tester", state="all"
    )
    prs.create_issue.assert_awaited_once()
    prs.post_comment.assert_awaited_once()
    prs.close_issue.assert_awaited_once_with(123)
    assert state.get_manifest_issue_number() == 123
    assert state.get_manifest_snapshot_hash() == "deadbeef"


@pytest.mark.asyncio
async def test_manifest_issue_syncer_reuses_existing_issue(tmp_path: Path) -> None:
    config = ConfigFactory.create(
        repo_root=tmp_path, git_user_name="tester", manifest_issue_enabled=True
    )
    state = StateTracker(config.state_file)
    prs = _make_prs_mock(existing_issue=77)

    syncer = ManifestIssueSyncer(config, state, prs)
    await syncer.sync("## Body", "hash456", source="unit-test")

    prs.create_issue.assert_not_called()
    prs.post_comment.assert_awaited_once()
    prs.close_issue.assert_awaited_once_with(77)
    assert state.get_manifest_issue_number() == 77
    assert state.get_manifest_snapshot_hash() == "hash456"


@pytest.mark.asyncio
async def test_manifest_issue_syncer_creates_when_no_existing_issue(
    tmp_path: Path,
) -> None:
    config = ConfigFactory.create(
        repo_root=tmp_path, git_user_name="tester", manifest_issue_enabled=True
    )
    state = StateTracker(config.state_file)
    prs = _make_prs_mock(existing_issue=None, new_issue_number=200)

    syncer = ManifestIssueSyncer(config, state, prs)
    await syncer.sync("## Another Body", "abc999", source="unit-test")

    prs.create_issue.assert_awaited_once()
    prs.post_comment.assert_awaited_once()
    prs.close_issue.assert_awaited_once_with(200)
    assert state.get_manifest_issue_number() == 200
    assert state.get_manifest_snapshot_hash() == "abc999"


@pytest.mark.asyncio
async def test_manifest_issue_syncer_skips_when_hash_matches(tmp_path: Path) -> None:
    config = ConfigFactory.create(repo_root=tmp_path, git_user_name="tester")
    state = StateTracker(config.state_file)
    state.set_manifest_issue_number(55)
    state.set_manifest_snapshot_hash("hash123")
    prs = _make_prs_mock()

    syncer = ManifestIssueSyncer(config, state, prs)
    await syncer.sync("## Manifest Body", "hash123", source="unit-test")

    prs.post_comment.assert_not_called()
    prs.close_issue.assert_not_called()


class TestManifestIssueOptIn:
    """Manifest issue creation should be opt-in."""

    @pytest.mark.asyncio
    async def test_sync_returns_early_when_disabled(self, tmp_path: Path) -> None:
        """sync() should do nothing when manifest_issue_enabled is False."""
        config = ConfigFactory.create(
            repo_root=tmp_path,
            git_user_name="tester",
            manifest_issue_enabled=False,
        )
        state = StateTracker(config.state_file)
        prs = _make_prs_mock()

        syncer = ManifestIssueSyncer(config, state, prs)
        await syncer.sync("# Manifest", "abc123")

        prs.create_issue.assert_not_called()
        prs.post_comment.assert_not_called()

    @pytest.mark.asyncio
    async def test_sync_proceeds_when_enabled(self, tmp_path: Path) -> None:
        """sync() should post when manifest_issue_enabled is True."""
        config = ConfigFactory.create(
            repo_root=tmp_path,
            git_user_name="tester",
            manifest_issue_enabled=True,
        )
        state = StateTracker(config.state_file)
        prs = _make_prs_mock(existing_issue=None, new_issue_number=10)

        syncer = ManifestIssueSyncer(config, state, prs)
        await syncer.sync("# Manifest", "abc123")

        prs.post_comment.assert_awaited_once()
