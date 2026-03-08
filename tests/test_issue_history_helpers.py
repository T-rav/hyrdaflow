"""Tests for extracted issue-history helpers in dashboard_routes.py.

The helpers (_build_issue_history_entry, _aggregate_telemetry_record,
_process_events_into_rows, _filter_rows_to_items, _apply_enrichment_and_crate_titles)
are inner functions inside ``create_router``.  We exercise them indirectly via
the GET /api/issues/history endpoint and verify their isolated behaviours.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from events import EventBus, EventType, HydraFlowEvent


@pytest.fixture(autouse=True)
def _disable_hitl_summary(config) -> None:
    config.transcript_summarization_enabled = False
    config.gh_token = ""


def _make_router(config, event_bus, state, tmp_path):
    from dashboard_routes import create_router
    from pr_manager import PRManager

    pr_mgr = PRManager(config, event_bus)
    return create_router(
        config=config,
        event_bus=event_bus,
        state=state,
        pr_manager=pr_mgr,
        get_orchestrator=lambda: None,
        set_orchestrator=lambda o: None,
        set_run_task=lambda t: None,
        ui_dist_dir=tmp_path / "no-dist",
        template_dir=tmp_path / "no-templates",
    )


def _get_endpoint(router, path="/api/issues/history"):
    return next(r.endpoint for r in router.routes if getattr(r, "path", "") == path)


# ---------------------------------------------------------------------------
# _build_issue_history_entry tests (via endpoint output)
# ---------------------------------------------------------------------------


class TestBuildIssueHistoryEntry:
    """Verify the deduplicated entry builder produces correct output."""

    @pytest.mark.asyncio
    async def test_entry_has_coerced_status(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """_coerce_history_status is applied (regression for prior bug)."""
        from prompt_telemetry import PromptTelemetry

        telemetry = PromptTelemetry(config)
        telemetry.record(
            source="planner",
            tool="claude",
            model="gpt-5",
            issue_number=10,
            pr_number=0,
            session_id="s1",
            prompt_chars=10,
            transcript_chars=5,
            duration_seconds=0.1,
            success=True,
        )

        router = _make_router(config, event_bus, state, tmp_path)
        endpoint = _get_endpoint(router)
        resp = await endpoint(limit=100)
        payload = json.loads(resp.body)
        item = next((x for x in payload["items"] if x["issue_number"] == 10), None)
        assert item is not None
        # Status should be a valid history status string, not raw data.
        assert item["status"] == "unknown"

    @pytest.mark.asyncio
    async def test_entry_sorts_prs_descending(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """PR rows should be sorted by number descending."""
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.PR_CREATED,
                data={"issue": 20, "pr": 100},
            )
        )
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.PR_CREATED,
                data={"issue": 20, "pr": 200},
            )
        )
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.PR_CREATED,
                data={"issue": 20, "pr": 150},
            )
        )

        router = _make_router(config, event_bus, state, tmp_path)
        endpoint = _get_endpoint(router)
        resp = await endpoint(limit=100)
        payload = json.loads(resp.body)
        item = next(x for x in payload["items"] if x["issue_number"] == 20)
        pr_numbers = [p["number"] for p in item["prs"]]
        assert pr_numbers == [200, 150, 100]

    @pytest.mark.asyncio
    async def test_entry_handles_empty_prs_map(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """An issue with no PRs should produce an empty prs list."""
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                data={"issue": 30, "title": "No PRs"},
            )
        )

        router = _make_router(config, event_bus, state, tmp_path)
        endpoint = _get_endpoint(router)
        resp = await endpoint(limit=100)
        payload = json.loads(resp.body)
        item = next(x for x in payload["items"] if x["issue_number"] == 30)
        assert item["prs"] == []

    @pytest.mark.asyncio
    async def test_entry_session_ids_sorted(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """session_ids should be sorted alphabetically."""
        from prompt_telemetry import PromptTelemetry

        telemetry = PromptTelemetry(config)
        for sid in ["z-sess", "a-sess", "m-sess"]:
            telemetry.record(
                source="implementer",
                tool="claude",
                model="gpt-5",
                issue_number=40,
                pr_number=0,
                session_id=sid,
                prompt_chars=10,
                transcript_chars=5,
                duration_seconds=0.1,
                success=True,
            )

        router = _make_router(config, event_bus, state, tmp_path)
        endpoint = _get_endpoint(router)
        resp = await endpoint(limit=100)
        payload = json.loads(resp.body)
        item = next(x for x in payload["items"] if x["issue_number"] == 40)
        assert item["session_ids"] == ["a-sess", "m-sess", "z-sess"]


# ---------------------------------------------------------------------------
# _aggregate_telemetry_record tests
# ---------------------------------------------------------------------------


class TestAggregateTelemetryRecord:
    """Verify telemetry metadata extraction works for both paths."""

    @pytest.mark.asyncio
    async def test_rollup_path_does_not_double_count(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Rollup path uses get_issue_totals for counters and only metadata
        from per-record pass (sum_counters=False)."""
        from prompt_telemetry import PromptTelemetry

        telemetry = PromptTelemetry(config)
        telemetry.record(
            source="implementer",
            tool="claude",
            model="gpt-5",
            issue_number=50,
            pr_number=600,
            session_id="s-50",
            prompt_chars=100,
            transcript_chars=50,
            duration_seconds=1.0,
            success=True,
            stats={"total_tokens": 500, "input_tokens": 300, "output_tokens": 200},
        )

        router = _make_router(config, event_bus, state, tmp_path)
        endpoint = _get_endpoint(router)
        # Unfiltered call uses rollup path.
        resp = await endpoint(limit=100)
        payload = json.loads(resp.body)
        item = next(x for x in payload["items"] if x["issue_number"] == 50)
        # Metadata should be populated.
        assert item["session_ids"] == ["s-50"]
        assert "implementer" in item["source_calls"]
        assert "gpt-5" in item["model_calls"]
        # Tokens should come from rollup, not be doubled.
        assert item["inference"]["total_tokens"] == 500

    @pytest.mark.asyncio
    async def test_per_record_path_sums_counters(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Non-rollup path (with date filter) sums inference counters."""
        from prompt_telemetry import PromptTelemetry

        telemetry = PromptTelemetry(config)
        for i in range(3):
            telemetry.record(
                source="implementer",
                tool="claude",
                model="gpt-5",
                issue_number=55,
                pr_number=0,
                session_id=f"s-{i}",
                prompt_chars=10,
                transcript_chars=5,
                duration_seconds=0.1,
                success=True,
                stats={"total_tokens": 100},
            )

        router = _make_router(config, event_bus, state, tmp_path)
        endpoint = _get_endpoint(router)
        # Use since filter to trigger per-record path.
        resp = await endpoint(since="2020-01-01T00:00:00+00:00", limit=100)
        payload = json.loads(resp.body)
        item = next((x for x in payload["items"] if x["issue_number"] == 55), None)
        assert item is not None
        assert item["inference"]["total_tokens"] == 300

    @pytest.mark.asyncio
    async def test_pr_link_from_telemetry(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """PR number from telemetry record is added to the row's prs map."""
        from prompt_telemetry import PromptTelemetry

        telemetry = PromptTelemetry(config)
        telemetry.record(
            source="implementer",
            tool="claude",
            model="gpt-5",
            issue_number=60,
            pr_number=700,
            session_id="s-60",
            prompt_chars=10,
            transcript_chars=5,
            duration_seconds=0.1,
            success=True,
        )

        router = _make_router(config, event_bus, state, tmp_path)
        endpoint = _get_endpoint(router)
        resp = await endpoint(limit=100)
        payload = json.loads(resp.body)
        item = next(x for x in payload["items"] if x["issue_number"] == 60)
        assert any(p["number"] == 700 for p in item["prs"])


# ---------------------------------------------------------------------------
# _process_events_into_rows tests
# ---------------------------------------------------------------------------


class TestProcessEventsIntoRows:
    """Verify event processing populates rows correctly."""

    @pytest.mark.asyncio
    async def test_merge_event_resolves_via_pr_to_issue(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """MERGE_UPDATE events without an issue field resolve via pr_to_issue."""
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.PR_CREATED,
                timestamp="2026-01-01T00:00:00+00:00",
                data={"issue": 70, "pr": 800},
            )
        )
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.MERGE_UPDATE,
                timestamp="2026-01-01T00:01:00+00:00",
                data={"pr": 800, "status": "merged"},
            )
        )

        router = _make_router(config, event_bus, state, tmp_path)
        endpoint = _get_endpoint(router)
        resp = await endpoint(limit=100)
        payload = json.loads(resp.body)
        item = next(x for x in payload["items"] if x["issue_number"] == 70)
        assert item["status"] == "merged"
        assert item["prs"][0]["merged"] is True

    @pytest.mark.asyncio
    async def test_issue_created_sets_epic_and_title(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                timestamp="2026-01-01T00:00:00+00:00",
                data={
                    "issue": 80,
                    "title": "Epic task",
                    "labels": ["epic:infra"],
                },
            )
        )

        router = _make_router(config, event_bus, state, tmp_path)
        endpoint = _get_endpoint(router)
        resp = await endpoint(limit=100)
        payload = json.loads(resp.body)
        item = next(x for x in payload["items"] if x["issue_number"] == 80)
        assert item["title"] == "Epic task"
        assert item["epic"] == "epic:infra"

    @pytest.mark.asyncio
    async def test_events_filtered_by_date_range(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Events outside the since/until range are excluded."""
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                timestamp="2025-01-01T00:00:00+00:00",
                data={"issue": 90, "title": "Old issue"},
            )
        )
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                timestamp="2026-06-01T00:00:00+00:00",
                data={"issue": 91, "title": "New issue"},
            )
        )

        router = _make_router(config, event_bus, state, tmp_path)
        endpoint = _get_endpoint(router)
        resp = await endpoint(
            since="2026-01-01T00:00:00+00:00",
            until="2026-12-31T00:00:00+00:00",
            limit=100,
        )
        payload = json.loads(resp.body)
        numbers = [x["issue_number"] for x in payload["items"]]
        assert 91 in numbers
        assert 90 not in numbers


# ---------------------------------------------------------------------------
# _filter_rows_to_items tests
# ---------------------------------------------------------------------------


class TestFilterRowsToItems:
    """Verify filtering by status and query text."""

    @pytest.mark.asyncio
    async def test_status_filter(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                timestamp="2026-01-01T00:00:00+00:00",
                data={"issue": 111, "title": "Active one"},
            )
        )
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.WORKER_UPDATE,
                timestamp="2026-01-01T00:01:00+00:00",
                data={"issue": 111, "status": "running", "worker": 1},
            )
        )
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                timestamp="2026-01-01T00:00:00+00:00",
                data={"issue": 112, "title": "Another"},
            )
        )

        router = _make_router(config, event_bus, state, tmp_path)
        endpoint = _get_endpoint(router)
        resp = await endpoint(status="active", limit=100)
        payload = json.loads(resp.body)
        numbers = [x["issue_number"] for x in payload["items"]]
        assert 111 in numbers
        assert 112 not in numbers

    @pytest.mark.asyncio
    async def test_query_filter_by_title(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                data={"issue": 121, "title": "Fix authentication"},
            )
        )
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                data={"issue": 122, "title": "Add dashboard"},
            )
        )

        router = _make_router(config, event_bus, state, tmp_path)
        endpoint = _get_endpoint(router)
        resp = await endpoint(query="auth", limit=100)
        payload = json.loads(resp.body)
        numbers = [x["issue_number"] for x in payload["items"]]
        assert 121 in numbers
        assert 122 not in numbers

    @pytest.mark.asyncio
    async def test_query_filter_by_issue_number(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                data={"issue": 131, "title": "Some title"},
            )
        )
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                data={"issue": 132, "title": "Other title"},
            )
        )

        router = _make_router(config, event_bus, state, tmp_path)
        endpoint = _get_endpoint(router)
        resp = await endpoint(query="131", limit=100)
        payload = json.loads(resp.body)
        numbers = [x["issue_number"] for x in payload["items"]]
        assert 131 in numbers
        assert 132 not in numbers


# ---------------------------------------------------------------------------
# _apply_enrichment_and_crate_titles tests
# ---------------------------------------------------------------------------


class TestApplyEnrichmentAndCrateTitles:
    """Verify enrichment and crate-title backfill logic."""

    @pytest.mark.asyncio
    async def test_crate_title_backfilled_from_milestones(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Items with crate_number get title from milestones."""
        from unittest.mock import MagicMock

        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                data={"issue": 140, "title": "Crate issue", "milestone_number": 5},
            )
        )

        router = _make_router(config, event_bus, state, tmp_path)
        endpoint = _get_endpoint(router)

        mock_milestone = MagicMock()
        mock_milestone.number = 5
        mock_milestone.title = "Sprint Alpha"

        with patch(
            "pr_manager.PRManager.list_milestones",
            new_callable=AsyncMock,
            return_value=[mock_milestone],
        ):
            resp = await endpoint(limit=100)
        payload = json.loads(resp.body)
        item = next(x for x in payload["items"] if x["issue_number"] == 140)
        assert item["crate_number"] == 5
        assert item["crate_title"] == "Sprint Alpha"

    @pytest.mark.asyncio
    async def test_crate_title_empty_when_no_milestone_match(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """When milestone is not found, crate_title stays empty."""
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                data={"issue": 141, "title": "No match", "milestone_number": 99},
            )
        )

        router = _make_router(config, event_bus, state, tmp_path)
        endpoint = _get_endpoint(router)

        with patch(
            "pr_manager.PRManager.list_milestones",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = await endpoint(limit=100)
        payload = json.loads(resp.body)
        item = next(x for x in payload["items"] if x["issue_number"] == 141)
        assert item["crate_title"] == ""

    @pytest.mark.asyncio
    async def test_enrichment_rebuilds_items_after_github_fetch(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """After GitHub enrichment, items are rebuilt with updated data."""
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                data={"issue": 150, "title": "Issue #150"},
            )
        )

        router = _make_router(config, event_bus, state, tmp_path)
        endpoint = _get_endpoint(router)

        mock_issue = MagicMock()
        mock_issue.title = "Enriched Title"
        mock_issue.url = "https://github.com/test/repo/issues/150"
        mock_issue.labels = []
        mock_issue.body = ""

        with patch(
            "issue_fetcher.IssueFetcher.fetch_issue_by_number",
            new_callable=AsyncMock,
            return_value=mock_issue,
        ):
            resp = await endpoint(limit=100)

        payload = json.loads(resp.body)
        item = next(x for x in payload["items"] if x["issue_number"] == 150)
        assert item["title"] == "Enriched Title"

    @pytest.mark.asyncio
    async def test_items_sorted_by_last_seen_descending(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Items are sorted by last_seen descending."""
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                timestamp="2026-01-01T00:00:00+00:00",
                data={"issue": 160, "title": "Older"},
            )
        )
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                timestamp="2026-06-01T00:00:00+00:00",
                data={"issue": 161, "title": "Newer"},
            )
        )

        router = _make_router(config, event_bus, state, tmp_path)
        endpoint = _get_endpoint(router)
        resp = await endpoint(limit=100)
        payload = json.loads(resp.body)
        numbers = [x["issue_number"] for x in payload["items"]]
        idx_160 = numbers.index(160)
        idx_161 = numbers.index(161)
        assert idx_161 < idx_160  # Newer first
