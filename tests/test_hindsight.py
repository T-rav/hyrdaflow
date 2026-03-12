"""Tests for the Hindsight memory client."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from hindsight import (
    BANK_LEARNINGS,
    BANK_RETROSPECTIVES,
    BANK_REVIEW_INSIGHTS,
    BANK_TROUBLESHOOTING,
    HindsightClient,
    HindsightMemory,
    format_memories_as_markdown,
    recall_safe,
    retain_safe,
)

# ---------------------------------------------------------------------------
# Bank constant tests
# ---------------------------------------------------------------------------


class TestBankConstants:
    def test_bank_ids_are_distinct(self):
        banks = {
            BANK_LEARNINGS,
            BANK_RETROSPECTIVES,
            BANK_REVIEW_INSIGHTS,
            BANK_TROUBLESHOOTING,
        }
        assert len(banks) == 4

    def test_bank_ids_have_prefix(self):
        for bank in [
            BANK_LEARNINGS,
            BANK_RETROSPECTIVES,
            BANK_REVIEW_INSIGHTS,
            BANK_TROUBLESHOOTING,
        ]:
            assert bank.startswith("hydraflow-")


# ---------------------------------------------------------------------------
# HindsightMemory model tests
# ---------------------------------------------------------------------------


class TestHindsightMemory:
    def test_defaults(self):
        m = HindsightMemory()
        assert m.content == ""
        assert m.metadata == {}
        assert m.relevance_score == 0.0

    def test_from_dict(self):
        m = HindsightMemory(
            content="test learning",
            context="from issue #42",
            relevance_score=0.95,
        )
        assert m.content == "test learning"
        assert m.relevance_score == 0.95


# ---------------------------------------------------------------------------
# HindsightClient tests (mocked HTTP)
# ---------------------------------------------------------------------------


def _mock_response(status_code: int = 200, json_data: dict | None = None):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = ""
    resp.json.return_value = json_data or {}
    return resp


class TestHindsightClientRetain:
    @pytest.mark.asyncio
    async def test_retain_success(self):
        client = HindsightClient()
        client._client = AsyncMock()
        client._client.post = AsyncMock(return_value=_mock_response(200))

        result = await client.retain("bank", "content", context="ctx")

        assert result is True
        client._client.post.assert_called_once()
        call_args = client._client.post.call_args
        assert call_args[0][0] == "/v1/retain"
        payload = call_args[1]["json"]
        assert payload["bank_id"] == "bank"
        assert payload["content"] == "content"
        assert payload["context"] == "ctx"

    @pytest.mark.asyncio
    async def test_retain_with_metadata(self):
        client = HindsightClient()
        client._client = AsyncMock()
        client._client.post = AsyncMock(return_value=_mock_response(200))

        await client.retain(
            "bank", "content", metadata={"key": "value"}
        )

        payload = client._client.post.call_args[1]["json"]
        assert payload["metadata"] == {"key": "value"}

    @pytest.mark.asyncio
    async def test_retain_failure_returns_false(self):
        client = HindsightClient()
        client._client = AsyncMock()
        client._client.post = AsyncMock(return_value=_mock_response(500))

        result = await client.retain("bank", "content")

        assert result is False

    @pytest.mark.asyncio
    async def test_retain_http_error_returns_false(self):
        client = HindsightClient()
        client._client = AsyncMock()
        client._client.post = AsyncMock(side_effect=httpx.ConnectError("down"))

        result = await client.retain("bank", "content")

        assert result is False


class TestHindsightClientRecall:
    @pytest.mark.asyncio
    async def test_recall_success(self):
        client = HindsightClient()
        client._client = AsyncMock()
        client._client.post = AsyncMock(
            return_value=_mock_response(
                200,
                {
                    "memories": [
                        {
                            "content": "learned thing",
                            "context": "from review",
                            "relevance_score": 0.9,
                        }
                    ]
                },
            )
        )

        memories = await client.recall("bank", "query about tests")

        assert len(memories) == 1
        assert memories[0].content == "learned thing"
        assert memories[0].relevance_score == 0.9

    @pytest.mark.asyncio
    async def test_recall_with_filter(self):
        client = HindsightClient()
        client._client = AsyncMock()
        client._client.post = AsyncMock(
            return_value=_mock_response(200, {"memories": []})
        )

        await client.recall(
            "bank", "query", metadata_filter={"language": "python"}
        )

        payload = client._client.post.call_args[1]["json"]
        assert payload["metadata_filter"] == {"language": "python"}

    @pytest.mark.asyncio
    async def test_recall_failure_returns_empty(self):
        client = HindsightClient()
        client._client = AsyncMock()
        client._client.post = AsyncMock(return_value=_mock_response(500))

        memories = await client.recall("bank", "query")

        assert memories == []

    @pytest.mark.asyncio
    async def test_recall_http_error_returns_empty(self):
        client = HindsightClient()
        client._client = AsyncMock()
        client._client.post = AsyncMock(side_effect=httpx.ConnectError("down"))

        memories = await client.recall("bank", "query")

        assert memories == []


class TestHindsightClientReflect:
    @pytest.mark.asyncio
    async def test_reflect_success(self):
        client = HindsightClient()
        client._client = AsyncMock()
        client._client.post = AsyncMock(return_value=_mock_response(200))

        result = await client.reflect("bank")

        assert result is True

    @pytest.mark.asyncio
    async def test_reflect_failure(self):
        client = HindsightClient()
        client._client = AsyncMock()
        client._client.post = AsyncMock(return_value=_mock_response(500))

        result = await client.reflect("bank")

        assert result is False


class TestHindsightClientHealth:
    @pytest.mark.asyncio
    async def test_health_check_success(self):
        client = HindsightClient()
        client._client = AsyncMock()
        client._client.get = AsyncMock(return_value=_mock_response(200))

        assert await client.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self):
        client = HindsightClient()
        client._client = AsyncMock()
        client._client.get = AsyncMock(side_effect=httpx.ConnectError("down"))

        assert await client.health_check() is False


# ---------------------------------------------------------------------------
# Safe wrapper tests
# ---------------------------------------------------------------------------


class TestRetainSafe:
    @pytest.mark.asyncio
    async def test_none_client_is_noop(self):
        await retain_safe(None, "bank", "content")  # should not raise

    @pytest.mark.asyncio
    async def test_exception_is_swallowed(self):
        client = MagicMock(spec=HindsightClient)
        client.retain = AsyncMock(side_effect=RuntimeError("boom"))

        await retain_safe(client, "bank", "content")  # should not raise

    @pytest.mark.asyncio
    async def test_success_delegates_to_client(self):
        client = MagicMock(spec=HindsightClient)
        client.retain = AsyncMock(return_value=True)

        await retain_safe(
            client, "bank", "content", metadata={"k": "v"}
        )

        client.retain.assert_called_once_with(
            "bank", "content", context="", metadata={"k": "v"}
        )


class TestRecallSafe:
    @pytest.mark.asyncio
    async def test_none_client_returns_empty(self):
        result = await recall_safe(None, "bank", "query")
        assert result == []

    @pytest.mark.asyncio
    async def test_exception_returns_empty(self):
        client = MagicMock(spec=HindsightClient)
        client.recall = AsyncMock(side_effect=RuntimeError("boom"))

        result = await recall_safe(client, "bank", "query")
        assert result == []


# ---------------------------------------------------------------------------
# Format helpers
# ---------------------------------------------------------------------------


class TestFormatMemories:
    def test_empty_list(self):
        assert format_memories_as_markdown([]) == ""

    def test_formats_memories(self):
        memories = [
            HindsightMemory(content="learning 1", context="ctx 1"),
            HindsightMemory(content="learning 2"),
        ]
        result = format_memories_as_markdown(memories)
        assert "learning 1" in result
        assert "ctx 1" in result
        assert "learning 2" in result
        assert "2 memories" in result

    def test_no_context_no_dash(self):
        memories = [HindsightMemory(content="bare")]
        result = format_memories_as_markdown(memories)
        assert "— " not in result


# ---------------------------------------------------------------------------
# Client construction
# ---------------------------------------------------------------------------


class TestClientConstruction:
    def test_default_url(self):
        client = HindsightClient()
        assert client._base_url == "http://localhost:8888"

    def test_custom_url_strips_trailing_slash(self):
        client = HindsightClient(base_url="http://example.com/")
        assert client._base_url == "http://example.com"

    def test_api_key_sets_header(self):
        client = HindsightClient(api_key="secret")
        assert client._client.headers["Authorization"] == "Bearer secret"
