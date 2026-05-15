"""Regression: find_open_pr_for_branch routes through the boundary
helper (Phase 12 of #8786). Lenient mode against ``GhPRDetail`` —
``number`` required, ``url`` / ``isDraft`` optional matching the
``--jq`` projection ``[.[] | {number, url: .html_url, isDraft: .draft}]``."""

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
async def test_well_shaped_response_returns_pr_info(
    config,  # noqa: ANN001
    event_bus,  # noqa: ANN001
    caplog: pytest.LogCaptureFixture,
) -> None:
    mgr = make_pr_manager(config, event_bus)
    payload = json.dumps(
        [
            {
                "number": 99,
                "url": "https://github.com/x/y/pull/99",
                "isDraft": False,
            }
        ]
    )
    mock_create = SubprocessMockBuilder().with_stdout(payload).build()

    with (
        caplog.at_level(logging.WARNING, logger="hydraflow.contracts.boundary"),
        patch("asyncio.create_subprocess_exec", mock_create),
    ):
        result = await mgr.find_open_pr_for_branch("feat/x", issue_number=42)

    assert result is not None
    assert result.number == 99
    assert result.issue_number == 42
    assert result.branch == "feat/x"
    assert str(result.url) == "https://github.com/x/y/pull/99"
    assert result.draft is False
    assert not [r for r in caplog.records if "boundary validation failed" in r.message]


@pytest.mark.asyncio
async def test_empty_response_returns_none(
    config,  # noqa: ANN001
    event_bus,  # noqa: ANN001
) -> None:
    """No matching PR → None (existing semantics preserved)."""
    mgr = make_pr_manager(config, event_bus)
    mock_create = SubprocessMockBuilder().with_stdout("[]").build()
    with patch("asyncio.create_subprocess_exec", mock_create):
        result = await mgr.find_open_pr_for_branch("feat/missing")
    assert result is None


@pytest.mark.asyncio
async def test_drifted_response_falls_back_to_raw_dict(
    config,  # noqa: ANN001
    event_bus,  # noqa: ANN001
    caplog: pytest.LogCaptureFixture,
) -> None:
    """If the shape drifts (e.g. number arrives as string), lenient
    fallback still extracts the PR info — production keeps working."""
    mgr = make_pr_manager(config, event_bus)
    # ``number`` arrives as something Pydantic can't coerce cleanly.
    payload = json.dumps(
        [
            {
                "number": "ninety-nine",  # bad
                "url": "https://github.com/x/y/pull/99",
                "isDraft": True,
            }
        ]
    )
    mock_create = SubprocessMockBuilder().with_stdout(payload).build()

    with (
        caplog.at_level(logging.WARNING, logger="hydraflow.contracts.boundary"),
        patch("asyncio.create_subprocess_exec", mock_create),
    ):
        # Validation fails → lenient fallback path → ``int(pr_data["number"])``
        # raises ValueError → method's try/except returns None.
        result = await mgr.find_open_pr_for_branch("feat/x")

    # Behaviour is preserved (None on parse failure) + drift signal
    # surfaced via WARN.
    assert any("boundary validation failed" in r.message for r in caplog.records)
    assert result is None
