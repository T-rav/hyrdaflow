"""Regression: list_issues_by_label is now wired through the contracts boundary
helper (Phase 8 of #8786) — verify the lenient pattern.

Two invariants:
1. Behaviour is preserved for well-shaped responses (existing callers see the
   same dict shape they always did).
2. Drifted responses still parse to the legacy dict shape via the lenient
   ``payload`` fallback — a WARN is logged, but the method returns useful data.
   Strict-mode callers would handle the drift signal differently; that's a
   per-call-site decision.
"""

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


class TestListIssuesByLabelBoundaryWiring:
    @pytest.mark.asyncio
    async def test_well_shaped_response_returns_dict_shape_unchanged(
        self,
        config,
        event_bus,
        caplog,  # noqa: ANN001
    ) -> None:
        """Happy path: validation succeeds, dict shape preserved, no WARN."""
        mgr = make_pr_manager(config, event_bus)
        issues_json = json.dumps(
            [
                {
                    "number": 7,
                    "title": "fix bug",
                    "body": "details",
                    "updatedAt": "2026-05-13T00:00:00Z",
                },
                {
                    "number": 8,
                    "title": "add feature",
                    "body": "",
                    "updatedAt": "2026-05-14T00:00:00Z",
                },
            ]
        )
        mock_create = SubprocessMockBuilder().with_stdout(issues_json).build()

        with (
            caplog.at_level(logging.WARNING, logger="hydraflow.contracts.boundary"),
            patch("asyncio.create_subprocess_exec", mock_create),
        ):
            result = await mgr.list_issues_by_label("bug")

        assert len(result) == 2
        assert result[0]["number"] == 7
        assert result[0]["title"] == "fix bug"
        assert result[0]["updated_at"] == "2026-05-13T00:00:00Z"

        validation_warns = [
            r for r in caplog.records if "boundary validation failed" in r.message
        ]
        assert validation_warns == [], (
            "well-shaped responses must not trip the drift signal"
        )

    @pytest.mark.asyncio
    async def test_drifted_response_logs_warn_and_falls_back(
        self,
        config,
        event_bus,
        caplog,  # noqa: ANN001
    ) -> None:
        """If gh's response shape changes (e.g. an unexpected type for a
        required field), the lenient wiring logs WARN but still returns
        the parsed dict — production behaviour preserved."""
        mgr = make_pr_manager(config, event_bus)
        # ``number`` is the wrong type → validation fails. The lenient
        # wiring falls back to the raw dict.
        issues_json = json.dumps(
            [
                {
                    "number": "not-an-int",
                    "title": "x",
                    "body": "",
                    "updatedAt": "2026-05-13T00:00:00Z",
                }
            ]
        )
        mock_create = SubprocessMockBuilder().with_stdout(issues_json).build()

        with (
            caplog.at_level(logging.WARNING, logger="hydraflow.contracts.boundary"),
            patch("asyncio.create_subprocess_exec", mock_create),
        ):
            result = await mgr.list_issues_by_label("bug")

        # WARN was logged — drift signal fired.
        warn_msgs = [
            r.message
            for r in caplog.records
            if "boundary validation failed" in r.message
        ]
        assert warn_msgs, (
            f"expected boundary validation WARN, got records: "
            f"{[r.message for r in caplog.records]}"
        )

        # Method still returned dicts. The drifted field falls through
        # to the raw payload value.
        assert len(result) == 1
        assert result[0]["title"] == "x"
        assert result[0]["number"] == "not-an-int"
