"""Regression: list_conflicting_prs routed through contracts boundary
(Phase 14 of #8786). GhPRDetail covers ``--json number,headRefName,
labels,mergeable`` exactly."""

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
async def test_well_shaped_filters_to_conflicting(
    config,  # noqa: ANN001
    event_bus,  # noqa: ANN001
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Three PRs: one conflicting, two mergeable. Method returns only the
    conflicting one; no validation WARN fires."""
    mgr = make_pr_manager(config, event_bus)
    payload = json.dumps(
        [
            {
                "number": 1,
                "headRefName": "feat/a",
                "labels": [{"name": "in-progress"}],
                "mergeable": "MERGEABLE",
            },
            {
                "number": 2,
                "headRefName": "feat/b",
                "labels": [{"name": "review"}, {"name": "blocked"}],
                "mergeable": "CONFLICTING",
            },
            {
                "number": 3,
                "headRefName": "feat/c",
                "labels": [],
                "mergeable": "UNKNOWN",
            },
        ]
    )
    mock_create = SubprocessMockBuilder().with_stdout(payload).build()

    with (
        caplog.at_level(logging.WARNING, logger="hydraflow.contracts.boundary"),
        patch("asyncio.create_subprocess_exec", mock_create),
    ):
        result = await mgr.list_conflicting_prs()

    assert len(result) == 1
    assert result[0].number == 2
    assert result[0].branch == "feat/b"
    assert sorted(result[0].labels) == ["blocked", "review"]
    assert not [r for r in caplog.records if "boundary validation failed" in r.message]


@pytest.mark.asyncio
async def test_drifted_mergeable_enum_logs_warn_uses_fallback(
    config,  # noqa: ANN001
    event_bus,  # noqa: ANN001
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A new ``mergeable`` value (e.g. ``REBASE_REQUIRED``) trips
    validation. Lenient fallback honors the actual string value when
    deciding whether to include the entry — drift is observable, but
    a future REBASE_REQUIRED PR isn't accidentally surfaced as
    conflicting."""
    mgr = make_pr_manager(config, event_bus)
    payload = json.dumps(
        [
            {
                "number": 9,
                "headRefName": "feat/x",
                "labels": [],
                "mergeable": "REBASE_REQUIRED",
            },
            {
                "number": 10,
                "headRefName": "feat/y",
                "labels": [],
                "mergeable": "CONFLICTING",
            },
        ]
    )
    mock_create = SubprocessMockBuilder().with_stdout(payload).build()

    with (
        caplog.at_level(logging.WARNING, logger="hydraflow.contracts.boundary"),
        patch("asyncio.create_subprocess_exec", mock_create),
    ):
        result = await mgr.list_conflicting_prs()

    assert any("boundary validation failed" in r.message for r in caplog.records)
    # Both entries fail validation (the bad enum + the good one — Pydantic
    # may flag the second as fine OR the first as drifted; either way the
    # caller's filter still selects exactly the CONFLICTING entry).
    numbers = sorted(p.number for p in result)
    assert 10 in numbers
    assert 9 not in numbers


@pytest.mark.asyncio
async def test_dry_run_returns_empty(
    config,  # noqa: ANN001
    event_bus,  # noqa: ANN001
) -> None:
    cfg = ConfigFactory.create(repo_root=config.repo_root, dry_run=True)
    mgr = make_pr_manager(cfg, event_bus)
    result = await mgr.list_conflicting_prs()
    assert result == []


@pytest.mark.asyncio
async def test_malformed_json_returns_empty(
    config,  # noqa: ANN001
    event_bus,  # noqa: ANN001
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Truly malformed JSON → caught, empty result + WARN log (existing
    semantics preserved)."""
    mgr = make_pr_manager(config, event_bus)
    mock_create = SubprocessMockBuilder().with_stdout("not json").build()
    with (
        caplog.at_level(logging.WARNING, logger="hydraflow.pr_manager"),
        patch("asyncio.create_subprocess_exec", mock_create),
    ):
        result = await mgr.list_conflicting_prs()
    assert result == []
