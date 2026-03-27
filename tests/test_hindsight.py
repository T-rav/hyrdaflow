"""Tests for hindsight module helpers."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hindsight import HindsightClient, schedule_retain

# ---------------------------------------------------------------------------
# schedule_retain tests
# ---------------------------------------------------------------------------


class TestScheduleRetain:
    """Tests for the schedule_retain fire-and-forget helper."""

    def test_noop_when_client_is_none(self) -> None:
        """schedule_retain should silently do nothing when client is None."""
        # Should not raise
        schedule_retain(None, "some-bank", "content")

    @pytest.mark.asyncio()
    async def test_creates_task_with_running_loop(self) -> None:
        """schedule_retain should create an asyncio task when a loop is running."""
        client = MagicMock(spec=HindsightClient)
        client.retain = AsyncMock(return_value={})

        with patch("hindsight.retain_safe", new_callable=AsyncMock) as mock_retain:
            schedule_retain(
                client,
                "test-bank",
                "test content",
                context="ctx",
                metadata={"key": "val"},
            )
            # Let the scheduled task run
            await asyncio.sleep(0)
            mock_retain.assert_awaited_once_with(
                client,
                "test-bank",
                "test content",
                context="ctx",
                metadata={"key": "val"},
                wal=None,
            )

    def test_noop_when_no_event_loop(self) -> None:
        """schedule_retain should not crash when no event loop is running."""
        client = MagicMock(spec=HindsightClient)
        # Should not raise even without a running loop
        schedule_retain(client, "test-bank", "content")


# ---------------------------------------------------------------------------
# Sentry breadcrumb tests
# ---------------------------------------------------------------------------


class TestSentryBreadcrumbs:
    """Sentry breadcrumbs are emitted on retain/recall failures."""

    @pytest.mark.asyncio()
    async def test_retain_safe_adds_breadcrumb_on_failure(self) -> None:
        from hindsight import retain_safe

        client = MagicMock(spec=HindsightClient)
        client.retain = AsyncMock(side_effect=RuntimeError("boom"))

        with patch.dict("sys.modules", {"sentry_sdk": MagicMock()}) as modules:
            sentry_mock = modules["sentry_sdk"]
            await retain_safe(client, "test-bank", "content")
            sentry_mock.add_breadcrumb.assert_called_once()
            call_kwargs = sentry_mock.add_breadcrumb.call_args[1]
            assert call_kwargs["category"] == "hindsight.retain_failed"
            assert call_kwargs["level"] == "warning"

    @pytest.mark.asyncio()
    async def test_recall_safe_adds_breadcrumb_on_failure(self) -> None:
        from hindsight import recall_safe

        client = MagicMock(spec=HindsightClient)
        client.recall = AsyncMock(side_effect=RuntimeError("boom"))

        with patch.dict("sys.modules", {"sentry_sdk": MagicMock()}) as modules:
            sentry_mock = modules["sentry_sdk"]
            result = await recall_safe(client, "test-bank", "query")
            assert result == []
            sentry_mock.add_breadcrumb.assert_called_once()
            call_kwargs = sentry_mock.add_breadcrumb.call_args[1]
            assert call_kwargs["category"] == "hindsight.recall_failed"
