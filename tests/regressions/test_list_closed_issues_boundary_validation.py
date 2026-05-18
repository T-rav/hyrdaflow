"""Regression: list_closed_issues_by_label routed through the contracts
boundary helper (Phase 10 of #8786). Mirrors the Phase 8 wiring for
list_issues_by_label."""

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
async def test_well_shaped_response_returns_dict_unchanged(
    config,  # noqa: ANN001
    event_bus,  # noqa: ANN001
    caplog: pytest.LogCaptureFixture,
) -> None:
    mgr = make_pr_manager(config, event_bus)
    issues_json = json.dumps(
        [
            {
                "number": 100,
                "title": "ancient bug",
                "body": "resolved",
                "updatedAt": "2026-04-01T00:00:00Z",
            }
        ]
    )
    mock_create = SubprocessMockBuilder().with_stdout(issues_json).build()

    with (
        caplog.at_level(logging.WARNING, logger="hydraflow.contracts.boundary"),
        patch("asyncio.create_subprocess_exec", mock_create),
    ):
        result = await mgr.list_closed_issues_by_label("bug")

    assert len(result) == 1
    assert result[0]["number"] == 100
    assert result[0]["title"] == "ancient bug"
    assert result[0]["updated_at"] == "2026-04-01T00:00:00Z"
    assert not [r for r in caplog.records if "boundary validation failed" in r.message]


@pytest.mark.asyncio
async def test_drifted_response_logs_warn_and_falls_back(
    config,  # noqa: ANN001
    event_bus,  # noqa: ANN001
    caplog: pytest.LogCaptureFixture,
) -> None:
    mgr = make_pr_manager(config, event_bus)
    # ``number`` is the wrong type — validation fails, lenient fallback used.
    issues_json = json.dumps(
        [
            {
                "number": None,
                "title": "x",
                "body": "",
                "updatedAt": "2026-04-01T00:00:00Z",
            }
        ]
    )
    mock_create = SubprocessMockBuilder().with_stdout(issues_json).build()

    with (
        caplog.at_level(logging.WARNING, logger="hydraflow.contracts.boundary"),
        patch("asyncio.create_subprocess_exec", mock_create),
    ):
        result = await mgr.list_closed_issues_by_label("bug")

    assert any("boundary validation failed" in r.message for r in caplog.records)
    assert len(result) == 1
    assert result[0]["title"] == "x"
