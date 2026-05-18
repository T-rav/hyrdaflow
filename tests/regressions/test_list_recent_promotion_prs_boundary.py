"""Regression: list_recent_promotion_prs routes through the contracts boundary
helper (Phase 11 of #8786). New shape ``GhPromotionPR`` covers the custom
``--jq`` projection used by this method."""

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
async def test_well_shaped_response_parses_cleanly(
    config,  # noqa: ANN001
    event_bus,  # noqa: ANN001
    caplog: pytest.LogCaptureFixture,
) -> None:
    mgr = make_pr_manager(config, event_bus)
    payload = json.dumps(
        [
            {
                "number": 42,
                "branch": "rc/2026-05-14-1000",
                "merged": True,
                "closed_at": "2026-05-14T11:00:00Z",
                "url": "https://github.com/x/y/pull/42",
            },
            {
                "number": 43,
                "branch": "rc/2026-05-14-1400",
                "merged": False,
                "closed_at": "2026-05-14T15:00:00Z",
                "url": "https://github.com/x/y/pull/43",
            },
        ]
    )
    mock_create = SubprocessMockBuilder().with_stdout(payload).build()

    with (
        caplog.at_level(logging.WARNING, logger="hydraflow.contracts.boundary"),
        patch("asyncio.create_subprocess_exec", mock_create),
    ):
        result = await mgr.list_recent_promotion_prs(days=7)

    assert len(result) == 2
    assert result[0]["number"] == 42
    assert result[0]["merged"] is True
    assert result[1]["merged"] is False
    assert not [r for r in caplog.records if "boundary validation failed" in r.message]


@pytest.mark.asyncio
async def test_drifted_response_logs_warn_and_falls_back(
    config,  # noqa: ANN001
    event_bus,  # noqa: ANN001
    caplog: pytest.LogCaptureFixture,
) -> None:
    """If gh's payload changes shape (e.g., ``merged`` becomes a string),
    the lenient wiring logs WARN but still returns the raw dict so the
    dashboard keeps working."""
    mgr = make_pr_manager(config, event_bus)
    payload = json.dumps(
        [
            {
                # ``number`` missing — required field. Pydantic raises.
                "branch": "rc/x",
                "merged": True,
                "closed_at": "2026-05-14T15:00:00Z",
                "url": "https://github.com/x/y/pull/99",
            }
        ]
    )
    mock_create = SubprocessMockBuilder().with_stdout(payload).build()

    with (
        caplog.at_level(logging.WARNING, logger="hydraflow.contracts.boundary"),
        patch("asyncio.create_subprocess_exec", mock_create),
    ):
        result = await mgr.list_recent_promotion_prs(days=7)

    assert any("boundary validation failed" in r.message for r in caplog.records)
    assert len(result) == 1
    # Lenient fallback returns the raw dict; the missing-required-field
    # is observable to the caller AND surfaced via WARN — both signals fire.
    assert result[0].get("branch") == "rc/x"


@pytest.mark.asyncio
async def test_empty_response_returns_empty_list(
    config,  # noqa: ANN001
    event_bus,  # noqa: ANN001
) -> None:
    mgr = make_pr_manager(config, event_bus)
    mock_create = SubprocessMockBuilder().with_stdout("").build()
    with patch("asyncio.create_subprocess_exec", mock_create):
        result = await mgr.list_recent_promotion_prs(days=7)
    assert result == []


@pytest.mark.asyncio
async def test_subprocess_failure_returns_empty(
    config,  # noqa: ANN001
    event_bus,  # noqa: ANN001
) -> None:
    """Existing behaviour: gh failure → empty list, no exception."""
    mgr = make_pr_manager(config, event_bus)
    mock_create = (
        SubprocessMockBuilder().with_returncode(1).with_stderr("api error").build()
    )
    with patch("asyncio.create_subprocess_exec", mock_create):
        result = await mgr.list_recent_promotion_prs(days=7)
    assert result == []
