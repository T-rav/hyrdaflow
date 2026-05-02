"""Tests for dashboard_routes.py — JSONL data endpoints.

Covers /api/hitl-recommendations, /api/adr-decisions, /api/verification-records.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from events import EventBus
from tests.helpers import find_endpoint, make_dashboard_router

# ---------------------------------------------------------------------------
# /api/hitl-recommendations
# ---------------------------------------------------------------------------


class TestHitlRecommendationsEndpoint:
    @pytest.mark.asyncio
    async def test_returns_empty_list_when_file_missing(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/hitl-recommendations")
        assert endpoint is not None

        response = await endpoint()
        data = json.loads(response.body)
        assert data == []

    @pytest.mark.asyncio
    async def test_returns_records_from_file(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        rec_path = config.data_path("memory", "hitl_recommendations.jsonl")
        rec_path.parent.mkdir(parents=True, exist_ok=True)
        recs = [
            {
                "title": "rec 1",
                "type": "recommendation",
                "timestamp": "2026-01-01T00:00:00+00:00",
            },
            {
                "title": "rec 2",
                "type": "recommendation",
                "timestamp": "2026-01-02T00:00:00+00:00",
            },
        ]
        rec_path.write_text(
            "\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8"
        )

        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/hitl-recommendations")
        assert endpoint is not None

        response = await endpoint()
        data = json.loads(response.body)
        assert len(data) == 2
        assert data[0]["title"] == "rec 1"
        assert data[1]["title"] == "rec 2"

    @pytest.mark.asyncio
    async def test_skips_malformed_lines(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        rec_path = config.data_path("memory", "hitl_recommendations.jsonl")
        rec_path.parent.mkdir(parents=True, exist_ok=True)
        rec_path.write_text(
            '{"title": "good"}\nnot valid json\n{"title": "also good"}\n',
            encoding="utf-8",
        )

        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/hitl-recommendations")
        assert endpoint is not None

        response = await endpoint()
        data = json.loads(response.body)
        assert len(data) == 2
        assert data[0]["title"] == "good"
        assert data[1]["title"] == "also good"


# ---------------------------------------------------------------------------
# /api/adr-decisions
# ---------------------------------------------------------------------------


class TestAdrDecisionsEndpoint:
    @pytest.mark.asyncio
    async def test_returns_empty_list_when_file_missing(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/adr-decisions")
        assert endpoint is not None

        response = await endpoint()
        data = json.loads(response.body)
        assert data == []

    @pytest.mark.asyncio
    async def test_returns_adr_records(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        adr_path = config.data_path("memory", "adr_decisions.jsonl")
        adr_path.parent.mkdir(parents=True, exist_ok=True)
        recs = [
            {
                "adr_id": "ADR-001",
                "status": "accepted",
                "title": "Use asyncio",
                "timestamp": "2026-01-01T00:00:00+00:00",
            },
            {
                "adr_id": "ADR-002",
                "status": "rejected",
                "title": "Use threading",
                "timestamp": "2026-01-02T00:00:00+00:00",
            },
        ]
        adr_path.write_text(
            "\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8"
        )

        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/adr-decisions")
        assert endpoint is not None

        response = await endpoint()
        data = json.loads(response.body)
        assert len(data) == 2
        assert data[0]["adr_id"] == "ADR-001"
        assert data[1]["status"] == "rejected"


# ---------------------------------------------------------------------------
# /api/verification-records
# ---------------------------------------------------------------------------


class TestVerificationRecordsEndpoint:
    @pytest.mark.asyncio
    async def test_returns_empty_list_when_file_missing(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/verification-records")
        assert endpoint is not None

        response = await endpoint()
        data = json.loads(response.body)
        assert data == []

    @pytest.mark.asyncio
    async def test_returns_verification_records(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        vr_path = config.data_path("memory", "verification_records.jsonl")
        vr_path.parent.mkdir(parents=True, exist_ok=True)
        recs = [
            {
                "pr_number": 42,
                "issue_number": 10,
                "reason": "merge conflict resolved",
                "timestamp": "2026-01-01T00:00:00+00:00",
            }
        ]
        vr_path.write_text(json.dumps(recs[0]) + "\n", encoding="utf-8")

        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/verification-records")
        assert endpoint is not None

        response = await endpoint()
        data = json.loads(response.body)
        assert len(data) == 1
        assert data[0]["pr_number"] == 42
        assert data[0]["reason"] == "merge conflict resolved"

    @pytest.mark.asyncio
    async def test_skips_malformed_lines(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        vr_path = config.data_path("memory", "verification_records.jsonl")
        vr_path.parent.mkdir(parents=True, exist_ok=True)
        vr_path.write_text(
            '{"pr_number": 1}\nBAD\n{"pr_number": 2}\n', encoding="utf-8"
        )

        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/verification-records")
        assert endpoint is not None

        response = await endpoint()
        data = json.loads(response.body)
        assert len(data) == 2
        assert data[0]["pr_number"] == 1
        assert data[1]["pr_number"] == 2
