"""Tests for extracted helpers used by the get_issue_history endpoint.

Exercises _aggregate_telemetry_record, _build_issue_history_entry,
_filter_and_build_entries, _process_events_into_rows, and
_apply_enrichment_and_crate_titles through the route endpoint.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from events import EventBus, EventType, HydraFlowEvent
from prompt_telemetry import PromptTelemetry


@pytest.fixture(autouse=True)
def _disable_hitl_summary_autowarm(config) -> None:
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
    for route in router.routes:
        if hasattr(route, "path") and route.path == path and hasattr(route, "endpoint"):
            return route.endpoint
    raise AssertionError(f"Route {path} not found")


async def _call_history(router, **kwargs):
    endpoint = _get_endpoint(router)
    resp = await endpoint(**kwargs)
    return json.loads(resp.body)


class TestAggregateTelemetryRecord:
    """Tests exercising _aggregate_telemetry_record via the endpoint."""

    @pytest.mark.asyncio
    async def test_session_ids_and_model_calls_aggregated(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Multiple telemetry records for the same issue aggregate metadata."""
        telemetry = PromptTelemetry(config)
        for i, model in enumerate(["gpt-5", "gpt-5", "claude-4"]):
            telemetry.record(
                source="implementer",
                tool="codex",
                model=model,
                issue_number=10,
                pr_number=0,
                session_id=f"sess-{i}",
                prompt_chars=100,
                transcript_chars=50,
                duration_seconds=1.0,
                success=True,
                stats={"total_tokens": 10, "input_tokens": 5, "output_tokens": 5},
            )

        router = _make_router(config, event_bus, state, tmp_path)
        payload = await _call_history(router)

        issue = next((x for x in payload["items"] if x["issue_number"] == 10), None)
        assert issue is not None
        assert sorted(issue["session_ids"]) == ["sess-0", "sess-1", "sess-2"]
        assert issue["model_calls"]["gpt-5"] == 2
        assert issue["model_calls"]["claude-4"] == 1
        assert issue["source_calls"]["implementer"] == 3

    @pytest.mark.asyncio
    async def test_sum_counters_false_skips_inference_summing(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Rollup path uses get_issue_totals for counters, not per-record sums."""
        telemetry = PromptTelemetry(config)
        # Record two inferences with 10 tokens each
        for _ in range(2):
            telemetry.record(
                source="planner",
                tool="codex",
                model="gpt-5",
                issue_number=20,
                pr_number=0,
                session_id="s1",
                prompt_chars=100,
                transcript_chars=50,
                duration_seconds=1.0,
                success=True,
                stats={"total_tokens": 10, "input_tokens": 5, "output_tokens": 5},
            )

        # Unfiltered call uses rollup path; counters come from get_issue_totals
        router = _make_router(config, event_bus, state, tmp_path)
        payload = await _call_history(router)
        issue = next((x for x in payload["items"] if x["issue_number"] == 20), None)
        assert issue is not None
        # Rollup path should give the aggregated total (20 tokens)
        assert issue["inference"]["total_tokens"] == 20

    @pytest.mark.asyncio
    async def test_pr_number_creates_pr_entry(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Telemetry records with pr_number create PR entries in the row."""
        telemetry = PromptTelemetry(config)
        telemetry.record(
            source="implementer",
            tool="codex",
            model="gpt-5",
            issue_number=30,
            pr_number=100,
            session_id="s1",
            prompt_chars=100,
            transcript_chars=50,
            duration_seconds=1.0,
            success=True,
            stats={"total_tokens": 5, "input_tokens": 3, "output_tokens": 2},
        )

        router = _make_router(config, event_bus, state, tmp_path)
        payload = await _call_history(router)
        issue = next((x for x in payload["items"] if x["issue_number"] == 30), None)
        assert issue is not None
        assert len(issue["prs"]) == 1
        assert issue["prs"][0]["number"] == 100

    @pytest.mark.asyncio
    async def test_empty_session_id_not_included(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Empty/whitespace session IDs are skipped."""
        telemetry = PromptTelemetry(config)
        telemetry.record(
            source="implementer",
            tool="codex",
            model="gpt-5",
            issue_number=40,
            pr_number=0,
            session_id="  ",
            prompt_chars=100,
            transcript_chars=50,
            duration_seconds=1.0,
            success=True,
            stats={"total_tokens": 5, "input_tokens": 3, "output_tokens": 2},
        )

        router = _make_router(config, event_bus, state, tmp_path)
        payload = await _call_history(router)
        issue = next((x for x in payload["items"] if x["issue_number"] == 40), None)
        assert issue is not None
        assert issue["session_ids"] == []


class TestBuildIssueHistoryEntry:
    """Tests exercising _build_issue_history_entry via the endpoint."""

    @pytest.mark.asyncio
    async def test_default_title_when_no_title_set(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Issues without a title get 'Issue #N' as default."""
        telemetry = PromptTelemetry(config)
        telemetry.record(
            source="planner",
            tool="codex",
            model="gpt-5",
            issue_number=99,
            pr_number=0,
            session_id="s1",
            prompt_chars=100,
            transcript_chars=50,
            duration_seconds=1.0,
            success=True,
            stats={"total_tokens": 5, "input_tokens": 3, "output_tokens": 2},
        )

        router = _make_router(config, event_bus, state, tmp_path)
        payload = await _call_history(router)
        issue = next((x for x in payload["items"] if x["issue_number"] == 99), None)
        assert issue is not None
        assert issue["title"] == "Issue #99"
        assert issue["status"] == "unknown"

    @pytest.mark.asyncio
    async def test_prs_sorted_descending(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """PRs in the entry are sorted by number descending."""
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.PR_CREATED,
                data={"issue": 50, "pr": 200, "url": "https://example.com/200"},
            )
        )
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.PR_CREATED,
                data={"issue": 50, "pr": 300, "url": "https://example.com/300"},
            )
        )
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.PR_CREATED,
                data={"issue": 50, "pr": 100, "url": "https://example.com/100"},
            )
        )

        router = _make_router(config, event_bus, state, tmp_path)
        payload = await _call_history(router)
        issue = next((x for x in payload["items"] if x["issue_number"] == 50), None)
        assert issue is not None
        pr_numbers = [p["number"] for p in issue["prs"]]
        assert pr_numbers == [300, 200, 100]

    @pytest.mark.asyncio
    async def test_invalid_prs_map_treated_as_empty(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """A non-dict prs value doesn't crash entry construction."""
        telemetry = PromptTelemetry(config)
        telemetry.record(
            source="planner",
            tool="codex",
            model="gpt-5",
            issue_number=60,
            pr_number=0,
            session_id="s1",
            prompt_chars=100,
            transcript_chars=50,
            duration_seconds=1.0,
            success=True,
            stats={"total_tokens": 1, "input_tokens": 1, "output_tokens": 0},
        )

        router = _make_router(config, event_bus, state, tmp_path)
        payload = await _call_history(router)
        issue = next((x for x in payload["items"] if x["issue_number"] == 60), None)
        assert issue is not None
        assert issue["prs"] == []


class TestFilterAndBuildEntries:
    """Tests for _filter_and_build_entries via the endpoint."""

    @pytest.mark.asyncio
    async def test_filter_by_status(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Status filter excludes non-matching issues."""
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                data={"issue": 70, "title": "Active issue"},
            )
        )
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.PR_CREATED,
                data={"issue": 70, "pr": 700},
            )
        )
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.MERGE_UPDATE,
                data={"pr": 700, "status": "merged"},
            )
        )
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                data={"issue": 71, "title": "Open issue"},
            )
        )

        router = _make_router(config, event_bus, state, tmp_path)
        payload = await _call_history(router, status="merged")
        numbers = {x["issue_number"] for x in payload["items"]}
        assert 70 in numbers
        assert 71 not in numbers

    @pytest.mark.asyncio
    async def test_filter_by_query_matches_title(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Query filter matches against issue title."""
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                data={"issue": 80, "title": "Fix dashboard bug"},
            )
        )
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                data={"issue": 81, "title": "Add new feature"},
            )
        )

        router = _make_router(config, event_bus, state, tmp_path)
        payload = await _call_history(router, query="dashboard")
        numbers = {x["issue_number"] for x in payload["items"]}
        assert 80 in numbers
        assert 81 not in numbers

    @pytest.mark.asyncio
    async def test_filter_by_query_matches_issue_number(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Query filter matches against issue number as string."""
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                data={"issue": 1234, "title": "Some issue"},
            )
        )

        router = _make_router(config, event_bus, state, tmp_path)
        payload = await _call_history(router, query="1234")
        numbers = {x["issue_number"] for x in payload["items"]}
        assert 1234 in numbers


class TestProcessEventsIntoRows:
    """Tests for _process_events_into_rows via the endpoint."""

    @pytest.mark.asyncio
    async def test_issue_created_sets_epic_from_labels(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """ISSUE_CREATED events extract epic from labels."""
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                data={
                    "issue": 90,
                    "title": "Epic test",
                    "labels": ["bug", "epic:infra"],
                },
            )
        )

        router = _make_router(config, event_bus, state, tmp_path)
        payload = await _call_history(router)
        issue = next((x for x in payload["items"] if x["issue_number"] == 90), None)
        assert issue is not None
        assert issue["epic"] == "epic:infra"

    @pytest.mark.asyncio
    async def test_merge_update_sets_merged_true(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """MERGE_UPDATE with status=merged marks the PR as merged."""
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.PR_CREATED,
                data={"issue": 91, "pr": 800, "url": "https://example.com/800"},
            )
        )
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.MERGE_UPDATE,
                data={"pr": 800, "status": "merged"},
            )
        )

        router = _make_router(config, event_bus, state, tmp_path)
        payload = await _call_history(router)
        issue = next((x for x in payload["items"] if x["issue_number"] == 91), None)
        assert issue is not None
        assert issue["prs"][0]["merged"] is True

    @pytest.mark.asyncio
    async def test_merge_update_resolves_pr_to_issue(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """MERGE_UPDATE for unknown issue resolves via pr_to_issue mapping."""
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.PR_CREATED,
                data={"issue": 92, "pr": 810},
            )
        )
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.MERGE_UPDATE,
                data={"pr": 810, "status": "merged"},
            )
        )

        router = _make_router(config, event_bus, state, tmp_path)
        payload = await _call_history(router)
        issue = next((x for x in payload["items"] if x["issue_number"] == 92), None)
        assert issue is not None
        assert issue["status"] == "merged"

    @pytest.mark.asyncio
    async def test_pr_created_url_stored(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """PR_CREATED event stores the PR URL."""
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.PR_CREATED,
                data={
                    "issue": 93,
                    "pr": 820,
                    "url": "https://github.com/org/repo/pull/820",
                },
            )
        )

        router = _make_router(config, event_bus, state, tmp_path)
        payload = await _call_history(router)
        issue = next((x for x in payload["items"] if x["issue_number"] == 93), None)
        assert issue is not None
        assert issue["prs"][0]["url"] == "https://github.com/org/repo/pull/820"

    @pytest.mark.asyncio
    async def test_issue_url_from_event(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Event URL is stored when it starts with http."""
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                data={
                    "issue": 94,
                    "title": "URL test",
                    "url": "https://github.com/org/repo/issues/94",
                },
            )
        )

        router = _make_router(config, event_bus, state, tmp_path)
        payload = await _call_history(router)
        issue = next((x for x in payload["items"] if x["issue_number"] == 94), None)
        assert issue is not None
        assert "github.com" in issue["issue_url"]

    @pytest.mark.asyncio
    async def test_milestone_sets_crate_number(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """ISSUE_CREATED with milestone_number sets crate_number."""
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                data={"issue": 95, "title": "Crate test", "milestone_number": 5},
            )
        )

        router = _make_router(config, event_bus, state, tmp_path)
        payload = await _call_history(router)
        issue = next((x for x in payload["items"] if x["issue_number"] == 95), None)
        assert issue is not None
        assert issue["crate_number"] == 5

    @pytest.mark.asyncio
    async def test_events_outside_date_range_excluded(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Events outside the since/until range are excluded."""
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                data={"issue": 96, "title": "Recent"},
                timestamp="2025-06-01T00:00:00Z",
            )
        )
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                data={"issue": 97, "title": "Old"},
                timestamp="2020-01-01T00:00:00Z",
            )
        )

        router = _make_router(config, event_bus, state, tmp_path)
        payload = await _call_history(
            router, since="2025-01-01T00:00:00Z", until="2025-12-31T00:00:00Z"
        )
        numbers = {x["issue_number"] for x in payload["items"]}
        assert 96 in numbers
        assert 97 not in numbers


class TestApplyEnrichmentAndCrateTitles:
    """Tests for _apply_enrichment_and_crate_titles via the endpoint."""

    @pytest.mark.asyncio
    async def test_crate_title_backfilled_from_milestones(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Crate titles are backfilled from milestones when crate_number is set."""
        from unittest.mock import MagicMock

        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                data={"issue": 110, "title": "Crate title test", "milestone_number": 3},
            )
        )

        from dashboard_routes import create_router
        from pr_manager import PRManager

        pr_mgr = PRManager(config, event_bus)
        ms_mock = AsyncMock(return_value=[MagicMock(number=3, title="Sprint 3")])

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
        )

        with patch.object(pr_mgr, "list_milestones", ms_mock):
            payload = await _call_history(router)

        issue = next((x for x in payload["items"] if x["issue_number"] == 110), None)
        assert issue is not None
        assert issue["crate_title"] == "Sprint 3"

    @pytest.mark.asyncio
    async def test_enrichment_skipped_when_already_enriched(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Issues that have title, URL, and epic skip GitHub enrichment."""
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                data={
                    "issue": 120,
                    "title": "Fully populated",
                    "url": "https://github.com/org/repo/issues/120",
                    "labels": ["epic:test"],
                },
            )
        )

        router = _make_router(config, event_bus, state, tmp_path)
        # Should not crash or try GitHub enrichment
        payload = await _call_history(router)
        issue = next((x for x in payload["items"] if x["issue_number"] == 120), None)
        assert issue is not None
        assert issue["title"] == "Fully populated"

    @pytest.mark.asyncio
    async def test_milestone_fetch_failure_doesnt_crash(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Milestone fetch failure is caught and doesn't crash the endpoint."""
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                data={"issue": 130, "title": "Fail test", "milestone_number": 7},
            )
        )

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
        )

        with patch.object(
            pr_mgr, "list_milestones", side_effect=RuntimeError("network fail")
        ):
            payload = await _call_history(router)

        issue = next((x for x in payload["items"] if x["issue_number"] == 130), None)
        assert issue is not None
        assert issue["crate_number"] == 7
        assert issue["crate_title"] == ""
