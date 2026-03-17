"""Tests for hindsight.py — HindsightClient and helpers."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from hindsight import (
    Bank,
    HindsightClient,
    HindsightMemory,
    format_memories_as_markdown,
    recall_safe,
    retain_safe,
)

# ---------------------------------------------------------------------------
# Bank enum
# ---------------------------------------------------------------------------


class TestBank:
    """Tests for the Bank enum."""

    def test_bank_values(self) -> None:
        assert Bank.LEARNINGS == "hydraflow-learnings"
        assert Bank.RETROSPECTIVES == "hydraflow-retrospectives"
        assert Bank.REVIEW_INSIGHTS == "hydraflow-review-insights"
        assert Bank.HARNESS_INSIGHTS == "hydraflow-harness-insights"
        assert Bank.TROUBLESHOOTING == "hydraflow-troubleshooting"

    def test_bank_is_str(self) -> None:
        assert isinstance(Bank.LEARNINGS, str)


# ---------------------------------------------------------------------------
# HindsightMemory
# ---------------------------------------------------------------------------


class TestHindsightMemory:
    """Tests for the HindsightMemory model."""

    def test_defaults(self) -> None:
        mem = HindsightMemory(content="test")
        assert mem.content == "test"
        assert mem.context == ""
        assert mem.metadata == {}
        assert mem.relevance_score == 0.0
        assert mem.timestamp == ""

    def test_full_construction(self) -> None:
        mem = HindsightMemory(
            content="lesson",
            context="fixing bug",
            metadata={"issue": 42},
            relevance_score=0.95,
            timestamp="2026-01-01T00:00:00Z",
        )
        assert mem.relevance_score == 0.95
        assert mem.metadata["issue"] == 42


# ---------------------------------------------------------------------------
# HindsightClient
# ---------------------------------------------------------------------------


class TestHindsightClient:
    """Tests for HindsightClient methods."""

    @pytest.mark.asyncio
    async def test_health_check_success(self) -> None:
        client = HindsightClient("http://localhost:8080")
        mock_resp = MagicMock(status_code=200)
        with patch.object(
            client._client, "get", new_callable=AsyncMock, return_value=mock_resp
        ):
            assert await client.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self) -> None:
        client = HindsightClient("http://localhost:8080")
        with patch.object(
            client._client,
            "get",
            new_callable=AsyncMock,
            side_effect=httpx.ConnectError("down"),
        ):
            assert await client.health_check() is False

    @pytest.mark.asyncio
    async def test_retain_posts_payload(self) -> None:
        client = HindsightClient("http://localhost:8080", api_key="test-key")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"id": "abc"}
        mock_resp.raise_for_status = MagicMock()
        with patch.object(
            client._client, "post", new_callable=AsyncMock, return_value=mock_resp
        ) as mock_post:
            result = await client.retain(
                Bank.LEARNINGS, "lesson learned", context="fixing bug"
            )

        assert result == {"id": "abc"}
        call_args = mock_post.call_args
        assert "/hydraflow-learnings/memories" in call_args[0][0]
        payload = call_args[1]["json"]
        assert payload["items"][0]["content"] == "lesson learned"
        assert payload["items"][0]["context"] == "fixing bug"

    @pytest.mark.asyncio
    async def test_retain_raises_on_http_error(self) -> None:
        client = HindsightClient("http://localhost:8080")
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock()
        )
        with (
            patch.object(
                client._client, "post", new_callable=AsyncMock, return_value=mock_resp
            ),
            pytest.raises(httpx.HTTPStatusError),
        ):
            await client.retain(Bank.LEARNINGS, "content")

    @pytest.mark.asyncio
    async def test_recall_returns_memories(self) -> None:
        client = HindsightClient("http://localhost:8080")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "results": [
                {"text": "Always lint first", "context": "CI"},
                {"text": "Check types"},
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        with patch.object(
            client._client, "post", new_callable=AsyncMock, return_value=mock_resp
        ):
            memories = await client.recall(Bank.LEARNINGS, "how to fix CI")

        assert len(memories) == 2
        assert memories[0].display_text == "Always lint first"
        assert memories[0].context == "CI"
        assert memories[1].display_text == "Check types"

    @pytest.mark.asyncio
    async def test_recall_uses_results_key(self) -> None:
        """Hindsight API uses 'results' key in recall response."""
        client = HindsightClient("http://localhost:8080")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"results": [{"text": "one result"}]}
        mock_resp.raise_for_status = MagicMock()
        with patch.object(
            client._client, "post", new_callable=AsyncMock, return_value=mock_resp
        ):
            memories = await client.recall(Bank.LEARNINGS, "query")

        assert len(memories) == 1
        assert memories[0].display_text == "one result"

    @pytest.mark.asyncio
    async def test_recall_raises_on_http_error(self) -> None:
        client = HindsightClient("http://localhost:8080")
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock()
        )
        with (
            patch.object(
                client._client, "post", new_callable=AsyncMock, return_value=mock_resp
            ),
            pytest.raises(httpx.HTTPStatusError),
        ):
            await client.recall(Bank.LEARNINGS, "query")

    @pytest.mark.asyncio
    async def test_reflect_returns_reflection(self) -> None:
        client = HindsightClient("http://localhost:8080")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"text": "Key insight: always test first"}
        mock_resp.raise_for_status = MagicMock()
        with patch.object(
            client._client, "post", new_callable=AsyncMock, return_value=mock_resp
        ):
            result = await client.reflect(Bank.LEARNINGS, "what have we learned?")

        assert result == "Key insight: always test first"

    @pytest.mark.asyncio
    async def test_reflect_returns_empty_on_missing_key(self) -> None:
        client = HindsightClient("http://localhost:8080")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {}
        mock_resp.raise_for_status = MagicMock()
        with patch.object(
            client._client, "post", new_callable=AsyncMock, return_value=mock_resp
        ):
            result = await client.reflect(Bank.LEARNINGS, "query")

        assert result == ""

    def test_api_key_sets_auth_header(self) -> None:
        client = HindsightClient("http://localhost:8080", api_key="secret")
        assert client._client.headers["Authorization"] == "Bearer secret"

    def test_no_api_key_omits_auth_header(self) -> None:
        client = HindsightClient("http://localhost:8080")
        assert "Authorization" not in client._client.headers

    def test_trailing_slash_stripped_from_url(self) -> None:
        client = HindsightClient("http://localhost:8080/")
        assert str(client._client.base_url).rstrip("/") == "http://localhost:8080"


# ---------------------------------------------------------------------------
# Safe wrappers
# ---------------------------------------------------------------------------


class TestRetainSafe:
    """Tests for retain_safe."""

    @pytest.mark.asyncio
    async def test_none_client_is_noop(self) -> None:
        await retain_safe(None, Bank.LEARNINGS, "content")  # should not raise

    @pytest.mark.asyncio
    async def test_swallows_exceptions(self) -> None:
        mock_client = MagicMock(spec=HindsightClient)
        mock_client.retain = AsyncMock(side_effect=RuntimeError("boom"))
        await retain_safe(mock_client, Bank.LEARNINGS, "content")  # should not raise

    @pytest.mark.asyncio
    async def test_calls_retain(self) -> None:
        mock_client = MagicMock(spec=HindsightClient)
        mock_client.retain = AsyncMock(return_value={"id": "ok"})
        await retain_safe(mock_client, Bank.LEARNINGS, "lesson", context="ctx")
        mock_client.retain.assert_awaited_once_with(
            Bank.LEARNINGS, "lesson", context="ctx", metadata=None
        )


class TestRecallSafe:
    """Tests for recall_safe."""

    @pytest.mark.asyncio
    async def test_none_client_returns_empty(self) -> None:
        result = await recall_safe(None, Bank.LEARNINGS, "query")
        assert result == []

    @pytest.mark.asyncio
    async def test_swallows_exceptions(self) -> None:
        mock_client = MagicMock(spec=HindsightClient)
        mock_client.recall = AsyncMock(side_effect=RuntimeError("boom"))
        result = await recall_safe(mock_client, Bank.LEARNINGS, "query")
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_memories(self) -> None:
        mock_client = MagicMock(spec=HindsightClient)
        memories = [HindsightMemory(content="test")]
        mock_client.recall = AsyncMock(return_value=memories)
        result = await recall_safe(mock_client, Bank.LEARNINGS, "query")
        assert result == memories


# ---------------------------------------------------------------------------
# format_memories_as_markdown
# ---------------------------------------------------------------------------


class TestFormatMemoriesAsMarkdown:
    """Tests for format_memories_as_markdown."""

    def test_empty_list_returns_empty_string(self) -> None:
        assert format_memories_as_markdown([]) == ""

    def test_single_memory_without_context(self) -> None:
        memories = [HindsightMemory(content="Always lint first")]
        result = format_memories_as_markdown(memories)
        assert result == "- Always lint first"

    def test_single_memory_with_context(self) -> None:
        memories = [HindsightMemory(content="Check types", context="CI pipeline")]
        result = format_memories_as_markdown(memories)
        assert "- Check types" in result
        assert "_Context: CI pipeline_" in result

    def test_multiple_memories(self) -> None:
        memories = [
            HindsightMemory(content="Lesson 1"),
            HindsightMemory(content="Lesson 2", context="bug fix"),
        ]
        result = format_memories_as_markdown(memories)
        assert "- Lesson 1" in result
        assert "- Lesson 2" in result
        assert "_Context: bug fix_" in result


# ---------------------------------------------------------------------------
# Recall field extraction
# ---------------------------------------------------------------------------


class TestRecallFieldExtraction:
    """Tests that recall extracts metadata, relevance_score, and timestamp."""

    @pytest.mark.asyncio
    async def test_recall_extracts_metadata(self) -> None:
        client = HindsightClient("http://localhost:8080")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "results": [
                {
                    "text": "Always lint first",
                    "context": "CI",
                    "metadata": {"issue": "42", "repo": "org/repo"},
                    "relevance_score": 0.95,
                    "occurred_start": "2026-01-15T10:00:00Z",
                }
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        with patch.object(
            client._client, "post", new_callable=AsyncMock, return_value=mock_resp
        ):
            memories = await client.recall(Bank.LEARNINGS, "how to fix CI")

        assert len(memories) == 1
        assert memories[0].metadata == {"issue": "42", "repo": "org/repo"}
        assert memories[0].relevance_score == 0.95
        assert memories[0].timestamp == "2026-01-15T10:00:00Z"

    @pytest.mark.asyncio
    async def test_recall_uses_occurred_start_over_timestamp(self) -> None:
        """Hindsight API uses ``occurred_start`` for timestamps in recall responses."""
        client = HindsightClient("http://localhost:8080")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "results": [
                {
                    "text": "lesson",
                    "context": "",
                    "occurred_start": "2026-02-01T00:00:00Z",
                    "timestamp": "2026-01-01T00:00:00Z",
                }
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        with patch.object(
            client._client, "post", new_callable=AsyncMock, return_value=mock_resp
        ):
            memories = await client.recall(Bank.LEARNINGS, "query")

        assert memories[0].timestamp == "2026-02-01T00:00:00Z"

    @pytest.mark.asyncio
    async def test_recall_falls_back_to_timestamp_field(self) -> None:
        """When ``occurred_start`` is absent, fall back to ``timestamp``."""
        client = HindsightClient("http://localhost:8080")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "results": [
                {
                    "text": "lesson",
                    "context": "",
                    "timestamp": "2026-01-01T00:00:00Z",
                }
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        with patch.object(
            client._client, "post", new_callable=AsyncMock, return_value=mock_resp
        ):
            memories = await client.recall(Bank.LEARNINGS, "query")

        assert memories[0].timestamp == "2026-01-01T00:00:00Z"

    @pytest.mark.asyncio
    async def test_recall_handles_missing_optional_fields(self) -> None:
        """Missing metadata/relevance_score/timestamp default gracefully."""
        client = HindsightClient("http://localhost:8080")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"results": [{"text": "bare result"}]}
        mock_resp.raise_for_status = MagicMock()
        with patch.object(
            client._client, "post", new_callable=AsyncMock, return_value=mock_resp
        ):
            memories = await client.recall(Bank.LEARNINGS, "query")

        assert memories[0].metadata == {}
        assert memories[0].relevance_score == 0.0
        assert memories[0].timestamp == ""
