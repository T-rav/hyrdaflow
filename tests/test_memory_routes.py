"""Tests for memory context route handlers (_memory_routes.py).

Covers:
- /api/memory/banks listing
- /api/memory/search with various filters
- /api/memory/issue/{n} per-issue context
- /api/memory/hitl/{n} HITL-specific context
- Graceful degradation when Hindsight is unavailable
- Edge cases: empty query, invalid bank filter
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from events import EventBus
from hindsight_types import Bank, HindsightMemory
from models import MemoryBankInfo, MemoryContextItem, MemoryContextResponse
from tests.helpers import find_endpoint, make_dashboard_router

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_hindsight():
    """Create a mock HindsightClient with recall_banks."""
    client = AsyncMock()
    client.recall_banks = AsyncMock(return_value={})
    client.health_check = AsyncMock(return_value=True)
    return client


@pytest.fixture()
def router_with_hindsight(config, event_bus: EventBus, state, tmp_path, mock_hindsight):
    """Build a dashboard router with a mock hindsight client."""
    from dashboard_routes import create_router
    from pr_manager import PRManager

    pr_mgr = PRManager(config, event_bus)
    router = create_router(
        config=config,
        event_bus=event_bus,
        state=state,
        pr_manager=pr_mgr,
        get_orchestrator=lambda: None,
        set_orchestrator=lambda o: None,
        set_run_task=lambda t: None,
        ui_dist_dir=tmp_path / "no-dist",
        template_dir=tmp_path / "no-templates",
        hindsight_client=mock_hindsight,
    )
    return router, mock_hindsight, state


@pytest.fixture()
def router_no_hindsight(config, event_bus: EventBus, state, tmp_path):
    """Build a dashboard router without hindsight."""
    router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
    return router


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestMemoryModels:
    """Basic model serialization tests."""

    def test_memory_context_item_defaults(self):
        item = MemoryContextItem(bank="test-bank", content="some content")
        assert item.relevance_score == 0.0
        assert item.timestamp == ""
        assert item.context == ""

    def test_memory_context_response_defaults(self):
        resp = MemoryContextResponse()
        assert resp.items == []
        assert resp.query == ""
        assert resp.bank_filter is None

    def test_memory_context_response_with_items(self):
        items = [
            MemoryContextItem(bank="b1", content="c1", relevance_score=0.9),
            MemoryContextItem(bank="b2", content="c2", relevance_score=0.5),
        ]
        resp = MemoryContextResponse(items=items, query="test", bank_filter="b1")
        dumped = resp.model_dump()
        assert len(dumped["items"]) == 2
        assert dumped["query"] == "test"
        assert dumped["bank_filter"] == "b1"

    def test_memory_bank_info(self):
        info = MemoryBankInfo(id="hydraflow-learnings", name="LEARNINGS")
        assert info.item_count == 0
        dumped = info.model_dump()
        assert dumped["id"] == "hydraflow-learnings"
        assert dumped["name"] == "LEARNINGS"


# ---------------------------------------------------------------------------
# /api/memory/banks
# ---------------------------------------------------------------------------


class TestMemoryBanksEndpoint:
    """Tests for GET /api/memory/banks."""

    @pytest.mark.asyncio
    async def test_lists_all_banks(self, router_with_hindsight):
        router, _, _ = router_with_hindsight
        handler = find_endpoint(router, "/api/memory/banks", "GET")
        assert handler is not None

        resp = await handler()
        data = resp.body  # JSONResponse stores bytes

        payload = json.loads(data)
        assert "banks" in payload
        bank_ids = {b["id"] for b in payload["banks"]}
        # Should have all Bank enum values
        for b in Bank:
            assert str(b) in bank_ids

    @pytest.mark.asyncio
    async def test_banks_without_hindsight(self, router_no_hindsight):
        """Banks endpoint works even without hindsight (static list)."""
        handler = find_endpoint(router_no_hindsight, "/api/memory/banks", "GET")
        assert handler is not None

        resp = await handler()

        payload = json.loads(resp.body)
        assert len(payload["banks"]) == len(Bank)


# ---------------------------------------------------------------------------
# /api/memory/search
# ---------------------------------------------------------------------------


class TestMemorySearchEndpoint:
    """Tests for GET /api/memory/search."""

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self, router_with_hindsight):
        router, mock_hs, _ = router_with_hindsight
        handler = find_endpoint(router, "/api/memory/search", "GET")

        resp = await handler(q="", bank=None, limit=10)

        payload = json.loads(resp.body)
        assert payload["items"] == []
        assert payload["query"] == ""
        mock_hs.recall_banks.assert_not_called()

    @pytest.mark.asyncio
    async def test_search_with_results(self, router_with_hindsight):
        router, mock_hs, _ = router_with_hindsight
        mock_hs.recall_banks.return_value = {
            Bank.LEARNINGS: [
                HindsightMemory(
                    text="CI timeout fix: increase timeout to 300s",
                    content="CI timeout fix",
                    relevance_score=0.85,
                    context="issue #100",
                ),
            ],
            Bank.TROUBLESHOOTING: [
                HindsightMemory(
                    text="Flaky test in auth module",
                    content="Flaky test",
                    relevance_score=0.7,
                ),
            ],
        }

        handler = find_endpoint(router, "/api/memory/search", "GET")
        resp = await handler(q="CI timeout", bank=None, limit=10)

        payload = json.loads(resp.body)
        assert len(payload["items"]) == 2
        assert payload["query"] == "CI timeout"
        # Should be sorted by relevance (highest first)
        assert (
            payload["items"][0]["relevance_score"]
            >= payload["items"][1]["relevance_score"]
        )

    @pytest.mark.asyncio
    async def test_search_with_bank_filter(self, router_with_hindsight):
        router, mock_hs, _ = router_with_hindsight
        mock_hs.recall_banks.return_value = {
            Bank.LEARNINGS: [
                HindsightMemory(
                    text="something", content="something", relevance_score=0.5
                ),
            ],
        }

        handler = find_endpoint(router, "/api/memory/search", "GET")
        resp = await handler(q="test", bank=str(Bank.LEARNINGS), limit=10)

        payload = json.loads(resp.body)
        assert payload["bank_filter"] == str(Bank.LEARNINGS)
        # recall_banks should have been called with specific bank
        mock_hs.recall_banks.assert_called_once()
        call_args = mock_hs.recall_banks.call_args
        assert call_args[0][1] == [Bank.LEARNINGS]

    @pytest.mark.asyncio
    async def test_search_invalid_bank_returns_empty(self, router_with_hindsight):
        """Invalid bank filter returns empty response (not all-banks fallthrough)."""
        router, mock_hs, _ = router_with_hindsight

        handler = find_endpoint(router, "/api/memory/search", "GET")
        resp = await handler(q="test", bank="nonexistent-bank", limit=10)

        payload = json.loads(resp.body)
        assert payload["items"] == []
        assert payload["bank_filter"] == "nonexistent-bank"
        mock_hs.recall_banks.assert_not_called()

    @pytest.mark.asyncio
    async def test_search_without_hindsight(self, router_no_hindsight):
        """Search gracefully returns empty when Hindsight is unavailable."""
        handler = find_endpoint(router_no_hindsight, "/api/memory/search", "GET")
        resp = await handler(q="test query", bank=None, limit=10)

        payload = json.loads(resp.body)
        assert payload["items"] == []
        assert payload["query"] == "test query"

    @pytest.mark.asyncio
    async def test_search_hindsight_failure(self, router_with_hindsight):
        """Search returns empty response when recall_banks raises."""
        router, mock_hs, _ = router_with_hindsight
        mock_hs.recall_banks.side_effect = Exception("connection refused")

        handler = find_endpoint(router, "/api/memory/search", "GET")
        resp = await handler(q="test", bank=None, limit=10)

        payload = json.loads(resp.body)
        assert payload["items"] == []

    @pytest.mark.asyncio
    async def test_search_bank_filter_by_name(self, router_with_hindsight):
        """Bank filter works by enum name as well as string value."""
        router, mock_hs, _ = router_with_hindsight
        mock_hs.recall_banks.return_value = {
            Bank.TROUBLESHOOTING: [],
        }

        handler = find_endpoint(router, "/api/memory/search", "GET")
        resp = await handler(q="test", bank="TROUBLESHOOTING", limit=10)

        json.loads(resp.body)
        # Should resolve the bank name and call recall_banks
        mock_hs.recall_banks.assert_called_once()


# ---------------------------------------------------------------------------
# /api/memory/issue/{issue_number}
# ---------------------------------------------------------------------------


class TestMemoryForIssueEndpoint:
    """Tests for GET /api/memory/issue/{issue_number}."""

    @pytest.mark.asyncio
    async def test_returns_context_for_issue(self, router_with_hindsight):
        router, mock_hs, _ = router_with_hindsight
        mock_hs.recall_banks.return_value = {
            Bank.LEARNINGS: [
                HindsightMemory(
                    text="Relevant learning",
                    content="Relevant learning",
                    relevance_score=0.9,
                ),
            ],
        }

        handler = find_endpoint(router, "/api/memory/issue/{issue_number}", "GET")
        resp = await handler(42)

        payload = json.loads(resp.body)
        assert payload["query"] == "issue #42"
        assert len(payload["items"]) == 1
        assert payload["items"][0]["content"] == "Relevant learning"

    @pytest.mark.asyncio
    async def test_issue_without_hindsight(self, router_no_hindsight):
        handler = find_endpoint(
            router_no_hindsight,
            "/api/memory/issue/{issue_number}",
            "GET",
        )
        resp = await handler(42)

        payload = json.loads(resp.body)
        assert payload["items"] == []
        assert payload["query"] == "issue #42"

    @pytest.mark.asyncio
    async def test_issue_recall_failure(self, router_with_hindsight):
        router, mock_hs, _ = router_with_hindsight
        mock_hs.recall_banks.side_effect = Exception("timeout")

        handler = find_endpoint(router, "/api/memory/issue/{issue_number}", "GET")
        resp = await handler(99)

        payload = json.loads(resp.body)
        assert payload["items"] == []


# ---------------------------------------------------------------------------
# /api/memory/hitl/{issue_number}
# ---------------------------------------------------------------------------


class TestMemoryForHITLEndpoint:
    """Tests for GET /api/memory/hitl/{issue_number}."""

    @pytest.mark.asyncio
    async def test_includes_cause_in_query(self, router_with_hindsight):
        router, mock_hs, st = router_with_hindsight
        st.set_hitl_cause(123, "CI timeout after 300s")
        mock_hs.recall_banks.return_value = {
            Bank.TROUBLESHOOTING: [
                HindsightMemory(
                    text="Increase CI timeout",
                    content="Increase CI timeout",
                    relevance_score=0.95,
                ),
            ],
        }

        handler = find_endpoint(router, "/api/memory/hitl/{issue_number}", "GET")
        resp = await handler(123)

        payload = json.loads(resp.body)
        assert "CI timeout after 300s" in payload["query"]
        assert "issue #123" in payload["query"]
        assert len(payload["items"]) == 1

    @pytest.mark.asyncio
    async def test_hitl_without_cause(self, router_with_hindsight):
        router, mock_hs, _ = router_with_hindsight
        mock_hs.recall_banks.return_value = {}

        handler = find_endpoint(router, "/api/memory/hitl/{issue_number}", "GET")
        resp = await handler(456)

        payload = json.loads(resp.body)
        assert payload["query"] == "issue #456"

    @pytest.mark.asyncio
    async def test_hitl_uses_targeted_banks(self, router_with_hindsight):
        """HITL endpoint should query TROUBLESHOOTING, LEARNINGS, and REVIEW_INSIGHTS."""
        router, mock_hs, _ = router_with_hindsight
        mock_hs.recall_banks.return_value = {}

        handler = find_endpoint(router, "/api/memory/hitl/{issue_number}", "GET")
        await handler(789)

        mock_hs.recall_banks.assert_called_once()
        call_args = mock_hs.recall_banks.call_args
        banks_arg = call_args[0][1]
        assert Bank.TROUBLESHOOTING in banks_arg
        assert Bank.LEARNINGS in banks_arg
        assert Bank.REVIEW_INSIGHTS in banks_arg

    @pytest.mark.asyncio
    async def test_hitl_without_hindsight(self, router_no_hindsight):
        handler = find_endpoint(
            router_no_hindsight,
            "/api/memory/hitl/{issue_number}",
            "GET",
        )
        resp = await handler(42)

        payload = json.loads(resp.body)
        assert payload["items"] == []

    @pytest.mark.asyncio
    async def test_hitl_recall_failure(self, router_with_hindsight):
        router, mock_hs, _ = router_with_hindsight
        mock_hs.recall_banks.side_effect = Exception("unavailable")

        handler = find_endpoint(router, "/api/memory/hitl/{issue_number}", "GET")
        resp = await handler(42)

        payload = json.loads(resp.body)
        assert payload["items"] == []


# ---------------------------------------------------------------------------
# recall_banks helper tests
# ---------------------------------------------------------------------------


class TestRecallBanks:
    """Tests for HindsightClient.recall_banks."""

    @pytest.mark.asyncio
    async def test_recall_banks_all(self):
        """recall_banks without bank filter queries all banks."""
        from hindsight import HindsightClient

        client = HindsightClient("http://localhost:9999")
        # Mock the recall method
        client.recall = AsyncMock(
            return_value=[
                HindsightMemory(text="mem1", content="mem1", relevance_score=0.8),
            ]
        )

        results = await client.recall_banks("test query")
        assert len(results) == len(Bank)
        for b in Bank:
            assert b in results
        await client.close()

    @pytest.mark.asyncio
    async def test_recall_banks_specific(self):
        """recall_banks with specific banks only queries those."""
        from hindsight import HindsightClient

        client = HindsightClient("http://localhost:9999")
        client.recall = AsyncMock(
            return_value=[
                HindsightMemory(text="mem1", content="mem1", relevance_score=0.9),
            ]
        )

        results = await client.recall_banks(
            "test",
            [Bank.LEARNINGS, Bank.TROUBLESHOOTING],
        )
        assert len(results) == 2
        assert Bank.LEARNINGS in results
        assert Bank.TROUBLESHOOTING in results
        assert client.recall.call_count == 2
        await client.close()

    @pytest.mark.asyncio
    async def test_recall_banks_partial_failure(self):
        """One bank failing doesn't block others."""
        from hindsight import HindsightClient

        client = HindsightClient("http://localhost:9999")

        call_count = 0

        async def mock_recall(bank, query, *, limit=10):
            nonlocal call_count
            call_count += 1
            if bank == Bank.LEARNINGS:
                raise Exception("timeout")
            return [HindsightMemory(text="ok", content="ok", relevance_score=0.5)]

        client.recall = mock_recall

        results = await client.recall_banks(
            "test",
            [Bank.LEARNINGS, Bank.TROUBLESHOOTING],
        )
        assert results[Bank.LEARNINGS] == []
        assert len(results[Bank.TROUBLESHOOTING]) == 1
        await client.close()
