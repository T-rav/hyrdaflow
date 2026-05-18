"""Regression: find_existing_issue routed through the boundary helper
(Phase 15 of #8786) — ``--json number,title`` shape vs GhIssueListItem."""

from __future__ import annotations

import json
import logging
from unittest.mock import patch

import pytest

from tests.conftest import SubprocessMockBuilder
from tests.helpers import ConfigFactory, make_pr_manager


@pytest.fixture
def config(tmp_path):  # noqa: ANN001
    return ConfigFactory.create(repo_root=tmp_path / "repo")


@pytest.fixture
def event_bus():  # noqa: ANN201
    from events import EventBus

    return EventBus()


@pytest.mark.asyncio
async def test_returns_matching_issue_number(
    config,  # noqa: ANN001
    event_bus,  # noqa: ANN001
    caplog: pytest.LogCaptureFixture,
) -> None:
    mgr = make_pr_manager(config, event_bus)
    payload = json.dumps(
        [
            {"number": 100, "title": "different bug"},
            {"number": 101, "title": "exact match"},
        ]
    )
    mock_create = SubprocessMockBuilder().with_stdout(payload).build()
    with (
        caplog.at_level(logging.WARNING, logger="hydraflow.contracts.boundary"),
        patch("asyncio.create_subprocess_exec", mock_create),
    ):
        result = await mgr.find_existing_issue("exact match")
    assert result == 101
    assert not [r for r in caplog.records if "boundary validation failed" in r.message]


@pytest.mark.asyncio
async def test_no_match_returns_zero(
    config,  # noqa: ANN001
    event_bus,  # noqa: ANN001
) -> None:
    mgr = make_pr_manager(config, event_bus)
    payload = json.dumps([{"number": 100, "title": "different bug"}])
    mock_create = SubprocessMockBuilder().with_stdout(payload).build()
    with patch("asyncio.create_subprocess_exec", mock_create):
        result = await mgr.find_existing_issue("nothing matches")
    assert result == 0


@pytest.mark.asyncio
async def test_drifted_payload_falls_back_to_dict_access(
    config,  # noqa: ANN001
    event_bus,  # noqa: ANN001
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A drifted ``number`` field (e.g. as string) trips validation. The
    lenient fallback uses dict access — when ``int(item["number"])`` then
    raises, the method's outer except returns 0 cleanly."""
    mgr = make_pr_manager(config, event_bus)
    payload = json.dumps([{"number": "not-an-int", "title": "exact match"}])
    mock_create = SubprocessMockBuilder().with_stdout(payload).build()
    with (
        caplog.at_level(logging.WARNING, logger="hydraflow.contracts.boundary"),
        patch("asyncio.create_subprocess_exec", mock_create),
    ):
        result = await mgr.find_existing_issue("exact match")
    assert any("boundary validation failed" in r.message for r in caplog.records)
    assert result == 0


@pytest.mark.asyncio
async def test_empty_response_returns_zero(
    config,  # noqa: ANN001
    event_bus,  # noqa: ANN001
) -> None:
    mgr = make_pr_manager(config, event_bus)
    mock_create = SubprocessMockBuilder().with_stdout("").build()
    with patch("asyncio.create_subprocess_exec", mock_create):
        result = await mgr.find_existing_issue("anything")
    assert result == 0
