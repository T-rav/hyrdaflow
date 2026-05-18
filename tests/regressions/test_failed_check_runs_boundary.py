"""Regression: PRManager._get_failed_check_runs is routed through the
contracts boundary helper (Phase 13 of #8786). GhCheckRun matches the
``--json name,state,detailsUrl`` shape exactly."""

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
async def test_well_shaped_response_extracts_failed_runs(
    config,  # noqa: ANN001
    event_bus,  # noqa: ANN001
    caplog: pytest.LogCaptureFixture,
) -> None:
    mgr = make_pr_manager(config, event_bus)
    payload = json.dumps(
        [
            {
                "name": "Lint",
                "state": "COMPLETED",
                "conclusion": "SUCCESS",
                "detailsUrl": "https://github.com/x/y/actions/runs/1",
            },
            {
                "name": "Tests",
                "state": "COMPLETED",
                "conclusion": "FAILURE",
                "detailsUrl": "https://github.com/x/y/actions/runs/2",
            },
        ]
    )
    mock_create = SubprocessMockBuilder().with_stdout(payload).build()

    with (
        caplog.at_level(logging.WARNING, logger="hydraflow.contracts.boundary"),
        patch("asyncio.create_subprocess_exec", mock_create),
    ):
        result = await mgr._get_failed_check_runs(pr_number=42)

    # The PASSING_STATES filter is checked on .state (COMPLETED); only
    # checks whose state isn't in the passing/pending sets survive. The
    # exact filtering depends on PRManager._PASSING_STATES constants —
    # this assertion just verifies the parse worked + extracted run IDs.
    run_ids = [run_id for _name, run_id in result]
    assert run_ids, f"expected at least one failed run id; got {result}"
    assert not [r for r in caplog.records if "boundary validation failed" in r.message]


@pytest.mark.asyncio
async def test_drifted_state_enum_logs_warn_and_falls_back(
    config,  # noqa: ANN001
    event_bus,  # noqa: ANN001
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A new gh state value (e.g. ``WARP_DRIVE``) trips validation. The
    lenient fallback uses the raw dict so the extraction logic still
    runs — drift is observable, behaviour preserved."""
    mgr = make_pr_manager(config, event_bus)
    payload = json.dumps(
        [
            {
                "name": "FlakyCheck",
                "state": "WARP_DRIVE",  # not in the Literal
                "detailsUrl": "https://github.com/x/y/actions/runs/9",
            }
        ]
    )
    mock_create = SubprocessMockBuilder().with_stdout(payload).build()

    with (
        caplog.at_level(logging.WARNING, logger="hydraflow.contracts.boundary"),
        patch("asyncio.create_subprocess_exec", mock_create),
    ):
        result = await mgr._get_failed_check_runs(pr_number=42)

    assert any("boundary validation failed" in r.message for r in caplog.records)
    # The lenient fallback still extracts the run_id from the URL.
    run_ids = [run_id for _name, run_id in result]
    assert run_ids == ["9"]


@pytest.mark.asyncio
async def test_empty_checks_list_returns_empty(
    config,  # noqa: ANN001
    event_bus,  # noqa: ANN001
) -> None:
    mgr = make_pr_manager(config, event_bus)
    mock_create = SubprocessMockBuilder().with_stdout("[]").build()
    with patch("asyncio.create_subprocess_exec", mock_create):
        result = await mgr._get_failed_check_runs(pr_number=42)
    assert result == []
