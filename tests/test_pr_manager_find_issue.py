"""Tests for PRManager.find_issue_number_by_label_and_title()."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from pr_manager import PRManager
from tests.helpers import ConfigFactory


def _make_prs(tmp_path: Path, *, dry_run: bool = False) -> PRManager:
    config = ConfigFactory.create(repo_root=tmp_path, dry_run=dry_run)
    bus = AsyncMock()
    return PRManager(config, bus)


@pytest.mark.asyncio
async def test_find_issue_returns_matching_number(tmp_path: Path) -> None:
    """Returns the issue number when a title contains the substring."""
    prs = _make_prs(tmp_path)
    prs._run_gh = AsyncMock(
        return_value=json.dumps(
            [{"number": 42, "title": "HydraFlow Manifest — tester", "state": "open"}]
        )
    )

    result = await prs.find_issue_number_by_label_and_title(
        "hydraflow-manifest", "tester"
    )

    assert result == 42


@pytest.mark.asyncio
async def test_find_issue_case_insensitive(tmp_path: Path) -> None:
    """Title matching is case-insensitive."""
    prs = _make_prs(tmp_path)
    prs._run_gh = AsyncMock(
        return_value=json.dumps(
            [{"number": 10, "title": "HydraFlow Manifest — TESTER", "state": "open"}]
        )
    )

    result = await prs.find_issue_number_by_label_and_title(
        "hydraflow-manifest", "tester"
    )

    assert result == 10


@pytest.mark.asyncio
async def test_find_issue_returns_none_when_no_match(tmp_path: Path) -> None:
    """Returns None when no issue title contains the substring."""
    prs = _make_prs(tmp_path)
    prs._run_gh = AsyncMock(
        return_value=json.dumps(
            [
                {
                    "number": 5,
                    "title": "HydraFlow Manifest — other-user",
                    "state": "open",
                }
            ]
        )
    )

    result = await prs.find_issue_number_by_label_and_title(
        "hydraflow-manifest", "tester"
    )

    assert result is None


@pytest.mark.asyncio
async def test_find_issue_returns_none_on_empty_results(tmp_path: Path) -> None:
    """Returns None when gh returns an empty list."""
    prs = _make_prs(tmp_path)
    prs._run_gh = AsyncMock(return_value=json.dumps([]))

    result = await prs.find_issue_number_by_label_and_title(
        "hydraflow-manifest", "tester"
    )

    assert result is None


@pytest.mark.asyncio
async def test_find_issue_returns_none_on_error(tmp_path: Path) -> None:
    """Returns None when the gh command fails."""
    prs = _make_prs(tmp_path)
    prs._run_gh = AsyncMock(side_effect=RuntimeError("gh failed"))

    result = await prs.find_issue_number_by_label_and_title(
        "hydraflow-manifest", "tester"
    )

    assert result is None


@pytest.mark.asyncio
async def test_find_issue_returns_none_on_bad_json(tmp_path: Path) -> None:
    """Returns None when gh returns invalid JSON."""
    prs = _make_prs(tmp_path)
    prs._run_gh = AsyncMock(return_value="not json")

    result = await prs.find_issue_number_by_label_and_title(
        "hydraflow-manifest", "tester"
    )

    assert result is None


@pytest.mark.asyncio
async def test_find_issue_passes_state_param(tmp_path: Path) -> None:
    """The state parameter is forwarded to the gh command."""
    prs = _make_prs(tmp_path)
    prs._run_gh = AsyncMock(return_value=json.dumps([]))

    await prs.find_issue_number_by_label_and_title(
        "hydraflow-manifest", "tester", state="open"
    )

    call_args = prs._run_gh.call_args[0]
    assert "--state" in call_args
    state_idx = list(call_args).index("--state")
    assert call_args[state_idx + 1] == "open"


@pytest.mark.asyncio
async def test_find_issue_returns_first_match(tmp_path: Path) -> None:
    """When multiple issues match, returns the first one."""
    prs = _make_prs(tmp_path)
    prs._run_gh = AsyncMock(
        return_value=json.dumps(
            [
                {"number": 1, "title": "HydraFlow Manifest — tester", "state": "open"},
                {
                    "number": 2,
                    "title": "HydraFlow Manifest — tester",
                    "state": "closed",
                },
            ]
        )
    )

    result = await prs.find_issue_number_by_label_and_title(
        "hydraflow-manifest", "tester"
    )

    assert result == 1


@pytest.mark.asyncio
async def test_find_issue_skips_entry_with_null_number(tmp_path: Path) -> None:
    """Skips matching title entries where number is null; returns None if no valid match."""
    prs = _make_prs(tmp_path)
    prs._run_gh = AsyncMock(
        return_value=json.dumps(
            [{"number": None, "title": "HydraFlow Manifest — tester", "state": "open"}]
        )
    )

    result = await prs.find_issue_number_by_label_and_title(
        "hydraflow-manifest", "tester"
    )

    assert result is None


@pytest.mark.asyncio
async def test_find_issue_default_state_is_all(tmp_path: Path) -> None:
    """Default state parameter is 'all'."""
    prs = _make_prs(tmp_path)
    prs._run_gh = AsyncMock(return_value=json.dumps([]))

    await prs.find_issue_number_by_label_and_title("hydraflow-manifest", "tester")

    call_args = prs._run_gh.call_args[0]
    state_idx = list(call_args).index("--state")
    assert call_args[state_idx + 1] == "all"


@pytest.mark.asyncio
async def test_find_issue_dry_run_returns_none(tmp_path: Path) -> None:
    """In dry-run mode, returns None without calling gh."""
    prs = _make_prs(tmp_path, dry_run=True)
    prs._run_gh = AsyncMock()

    result = await prs.find_issue_number_by_label_and_title(
        "hydraflow-manifest", "tester"
    )

    assert result is None
    prs._run_gh.assert_not_called()
