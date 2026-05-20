"""Regression test for issue #6722.

``MetricsManager._build_snapshot()`` wraps ``get_label_counts()`` in a broad
``try/except Exception`` block.  The three dict key accesses on lines 208-210::

    github_open_by_label = counts["open_by_label"]
    github_total_closed  = counts["total_closed"]
    github_total_merged  = counts["total_merged"]

use bare subscript (``counts["key"]``) instead of ``.get("key", default)``.

If the API returns a partial dict (e.g. missing ``open_by_label``), a
``KeyError`` is raised on the *first* missing key.  Because the KeyError is
caught by the same ``except Exception`` meant for network errors, every key
that was already successfully extracted is silently discarded — the snapshot
falls back to all-zero defaults even though some data *was* available.

These tests will be RED until the code uses ``.get()`` with safe defaults
so that each key is independently defaulted.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from events import EventBus
from metrics_manager import MetricsManager
from state import StateTracker
from tests.helpers import ConfigFactory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pr_manager(label_counts: dict[str, Any]) -> MagicMock:
    """Return a mock PRManager whose get_label_counts returns *label_counts*."""
    pr = MagicMock()
    pr.post_comment = AsyncMock()
    pr.create_issue = AsyncMock(return_value=42)
    pr.get_label_counts = AsyncMock(return_value=label_counts)
    return pr


def _make_manager(
    state: StateTracker,
    event_bus: EventBus,
    label_counts: dict[str, Any],
) -> MetricsManager:
    config = ConfigFactory.create(repo="test-owner/test-repo")
    prs = _make_pr_manager(label_counts)
    return MetricsManager(config, state, prs, event_bus)


# ---------------------------------------------------------------------------
# Test 1 — partial dict missing "open_by_label": present keys are lost
# ---------------------------------------------------------------------------


class TestPartialLabelCountsMissingFirstKey:
    """When open_by_label is missing but total_closed/total_merged exist,
    the snapshot should still surface the values that *were* returned.

    Currently FAILS: the KeyError on "open_by_label" causes the except
    block to fire, discarding the total_closed and total_merged values
    that were present in the response.
    """

    @pytest.mark.asyncio
    async def test_partial_dict_missing_open_by_label(
        self, state: StateTracker, event_bus: EventBus
    ) -> None:
        partial = {"total_closed": 5, "total_merged": 2}
        mgr = _make_manager(state, event_bus, label_counts=partial)

        snapshot = await mgr._build_snapshot()

        # The values that WERE present should be preserved, not zeroed out.
        assert snapshot.github_total_closed == 5
        assert snapshot.github_total_merged == 2
        # open_by_label was missing — should default to {}
        assert snapshot.github_open_by_label == {}


# ---------------------------------------------------------------------------
# Test 2 — partial dict missing "total_merged": earlier keys are preserved
#           but total_merged defaults to 0 instead of crashing
# ---------------------------------------------------------------------------


class TestPartialLabelCountsMissingLastKey:
    """When total_merged is missing but open_by_label and total_closed exist,
    the snapshot should keep the successfully-read values and default the
    missing one.

    This test currently PASSES by accident (the KeyError fires *after* the
    first two assignments).  It is included to lock in the desired contract
    so a future refactor can't regress.
    """

    @pytest.mark.asyncio
    async def test_partial_dict_missing_total_merged(
        self, state: StateTracker, event_bus: EventBus
    ) -> None:
        partial = {"open_by_label": {"bug": 3}, "total_closed": 7}
        mgr = _make_manager(state, event_bus, label_counts=partial)

        snapshot = await mgr._build_snapshot()

        assert snapshot.github_open_by_label == {"bug": 3}
        assert snapshot.github_total_closed == 7
        assert snapshot.github_total_merged == 0


# ---------------------------------------------------------------------------
# Test 3 — completely empty dict: snapshot should succeed with defaults
# ---------------------------------------------------------------------------


class TestEmptyLabelCounts:
    """An empty dict from get_label_counts should not crash the snapshot."""

    @pytest.mark.asyncio
    async def test_empty_dict_returns_defaults(
        self, state: StateTracker, event_bus: EventBus
    ) -> None:
        mgr = _make_manager(state, event_bus, label_counts={})

        snapshot = await mgr._build_snapshot()

        assert snapshot.github_open_by_label == {}
        assert snapshot.github_total_closed == 0
        assert snapshot.github_total_merged == 0
