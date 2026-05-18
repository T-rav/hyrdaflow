"""Regression: get_pr_approvers routes through the boundary helper
(Phase 16 of #8786). New ``GhPRReviewsResponse`` shape wraps a list of
``GhReview`` entries."""

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
async def test_returns_unique_approver_logins(
    config,  # noqa: ANN001
    event_bus,  # noqa: ANN001
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Multiple reviews from the same author → dedup. Non-approved
    states filtered out."""
    mgr = make_pr_manager(config, event_bus)
    payload = json.dumps(
        {
            "reviews": [
                {"state": "COMMENTED", "author": {"login": "alice"}},
                {"state": "APPROVED", "author": {"login": "alice"}},
                {"state": "APPROVED", "author": {"login": "bob"}},
                {"state": "CHANGES_REQUESTED", "author": {"login": "carol"}},
                {"state": "APPROVED", "author": {"login": "alice"}},  # dup
            ]
        }
    )
    mock_create = SubprocessMockBuilder().with_stdout(payload).build()
    with (
        caplog.at_level(logging.WARNING, logger="hydraflow.contracts.boundary"),
        patch("asyncio.create_subprocess_exec", mock_create),
    ):
        result = await mgr.get_pr_approvers(pr_number=42)
    assert result == ["alice", "bob"]
    assert not [r for r in caplog.records if "boundary validation failed" in r.message]


@pytest.mark.asyncio
async def test_drifted_state_logs_warn_and_falls_back(
    config,  # noqa: ANN001
    event_bus,  # noqa: ANN001
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A new state enum value trips validation. The lenient fallback
    walks the raw dict — APPROVED entries still surface, drifted ones
    don't get treated as approvals."""
    mgr = make_pr_manager(config, event_bus)
    payload = json.dumps(
        {
            "reviews": [
                {"state": "AUTO_APPROVED", "author": {"login": "bot"}},  # drifted
                {"state": "APPROVED", "author": {"login": "alice"}},
            ]
        }
    )
    mock_create = SubprocessMockBuilder().with_stdout(payload).build()
    with (
        caplog.at_level(logging.WARNING, logger="hydraflow.contracts.boundary"),
        patch("asyncio.create_subprocess_exec", mock_create),
    ):
        result = await mgr.get_pr_approvers(pr_number=42)
    assert any("boundary validation failed" in r.message for r in caplog.records)
    # The lenient fallback uses dict-access; AUTO_APPROVED ≠ APPROVED so
    # the bot isn't counted as an approver. Only alice surfaces.
    assert "alice" in result
    assert "bot" not in result


@pytest.mark.asyncio
async def test_empty_reviews_returns_empty(
    config,  # noqa: ANN001
    event_bus,  # noqa: ANN001
) -> None:
    mgr = make_pr_manager(config, event_bus)
    payload = json.dumps({"reviews": []})
    mock_create = SubprocessMockBuilder().with_stdout(payload).build()
    with patch("asyncio.create_subprocess_exec", mock_create):
        result = await mgr.get_pr_approvers(pr_number=42)
    assert result == []


@pytest.mark.asyncio
async def test_subprocess_failure_returns_empty(
    config,  # noqa: ANN001
    event_bus,  # noqa: ANN001
) -> None:
    mgr = make_pr_manager(config, event_bus)
    mock_create = (
        SubprocessMockBuilder().with_returncode(1).with_stderr("api error").build()
    )
    with patch("asyncio.create_subprocess_exec", mock_create):
        result = await mgr.get_pr_approvers(pr_number=42)
    assert result == []
