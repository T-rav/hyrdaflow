"""Tests for manifest issue syncer."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from manifest_issue_syncer import ManifestIssueSyncer
from state import StateTracker
from tests.helpers import ConfigFactory


def _issues_payload(entries: list[dict]) -> str:
    return json.dumps(entries)


@pytest.mark.asyncio
async def test_manifest_issue_syncer_posts_comment(tmp_path: Path, monkeypatch) -> None:
    config = ConfigFactory.create(repo_root=tmp_path, git_user_name="tester")
    state = StateTracker(config.state_file)
    prs = MagicMock()
    prs.create_issue = AsyncMock(return_value=123)
    prs.post_comment = AsyncMock()
    prs.close_issue = AsyncMock()
    monkeypatch.setattr(
        "manifest_issue_syncer.run_subprocess",
        AsyncMock(return_value=_issues_payload([])),
    )

    syncer = ManifestIssueSyncer(config, state, prs)
    await syncer.sync("## Manifest Body", "deadbeef", source="unit-test")

    prs.create_issue.assert_awaited_once()
    prs.post_comment.assert_awaited_once()
    prs.close_issue.assert_awaited_once_with(123)
    assert state.get_manifest_issue_number() == 123
    assert state.get_manifest_snapshot_hash() == "deadbeef"


@pytest.mark.asyncio
async def test_manifest_issue_syncer_reuses_existing_issue(tmp_path: Path, monkeypatch):
    config = ConfigFactory.create(repo_root=tmp_path, git_user_name="tester")
    state = StateTracker(config.state_file)
    prs = MagicMock()
    prs.create_issue = AsyncMock()
    prs.post_comment = AsyncMock()
    prs.close_issue = AsyncMock()
    monkeypatch.setattr(
        "manifest_issue_syncer.run_subprocess",
        AsyncMock(
            return_value=_issues_payload(
                [
                    {
                        "number": 77,
                        "title": "HydraFlow Manifest — " + config.git_user_name,
                        "state": "closed",
                    }
                ]
            )
        ),
    )

    syncer = ManifestIssueSyncer(config, state, prs)
    await syncer.sync("## Body", "hash456", source="unit-test")

    prs.create_issue.assert_not_called()
    prs.post_comment.assert_awaited_once()
    prs.close_issue.assert_awaited_once_with(77)
    assert state.get_manifest_issue_number() == 77
    assert state.get_manifest_snapshot_hash() == "hash456"


@pytest.mark.asyncio
async def test_manifest_issue_syncer_creates_when_owner_missing(
    tmp_path: Path, monkeypatch
):
    config = ConfigFactory.create(repo_root=tmp_path, git_user_name="tester")
    state = StateTracker(config.state_file)
    prs = MagicMock()
    prs.create_issue = AsyncMock(return_value=200)
    prs.post_comment = AsyncMock()
    prs.close_issue = AsyncMock()
    monkeypatch.setattr(
        "manifest_issue_syncer.run_subprocess",
        AsyncMock(
            return_value=_issues_payload(
                [
                    {
                        "number": 55,
                        "title": "HydraFlow Manifest — other-user",
                        "state": "open",
                    }
                ]
            )
        ),
    )

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
    prs = MagicMock()
    prs.post_comment = AsyncMock()
    prs.close_issue = AsyncMock()

    syncer = ManifestIssueSyncer(config, state, prs)
    await syncer.sync("## Manifest Body", "hash123", source="unit-test")

    prs.post_comment.assert_not_called()
    prs.close_issue.assert_not_called()
