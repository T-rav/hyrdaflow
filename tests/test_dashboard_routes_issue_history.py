"""Tests for dashboard_routes.py — issue history endpoints and cache."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from events import EventBus, EventType, HydraFlowEvent
from tests.helpers import find_endpoint, make_dashboard_router


class TestIssueHistoryEndpoint:
    @pytest.mark.asyncio
    async def test_issue_history_aggregates_inference_and_events(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        from prompt_telemetry import PromptTelemetry

        telemetry = PromptTelemetry(config)
        telemetry.record(
            source="implementer",
            tool="codex",
            model="gpt-5",
            issue_number=77,
            pr_number=501,
            session_id="sess-x",
            prompt_chars=400,
            transcript_chars=200,
            duration_seconds=1.5,
            success=True,
            stats={"total_tokens": 123, "input_tokens": 80, "output_tokens": 43},
        )

        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                data={
                    "issue": 77,
                    "title": "Improve planner quality",
                    "labels": ["epic:quality"],
                },
            )
        )
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.PR_CREATED,
                data={"issue": 77, "pr": 501, "url": "https://example.com/pull/501"},
            )
        )
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.MERGE_UPDATE,
                data={"pr": 501, "status": "merged"},
            )
        )

        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)

        endpoint = find_endpoint(router, "/api/issues/history")
        assert endpoint is not None

        response = await endpoint(limit=100)
        payload = json.loads(response.body)
        assert payload["totals"]["issues"] >= 1
        assert payload["totals"]["total_tokens"] >= 123

        issue = next((x for x in payload["items"] if x["issue_number"] == 77), None)
        assert issue is not None
        assert issue["status"] == "merged"
        assert issue["epic"] == "epic:quality"
        assert issue["inference"]["total_tokens"] == 123
        assert issue["session_ids"] == ["sess-x"]
        assert issue["prs"][0]["number"] == 501
        assert issue["prs"][0]["merged"] is True

    @pytest.mark.asyncio
    async def test_issue_history_provides_issue_url_fallback(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        from prompt_telemetry import PromptTelemetry

        issue_number = 314
        telemetry = PromptTelemetry(config)
        telemetry.record(
            source="implementer",
            tool="codex",
            model="gpt-5",
            issue_number=issue_number,
            pr_number=0,
            session_id="sess-fallback",
            prompt_chars=10,
            transcript_chars=5,
            duration_seconds=0.1,
            success=True,
            stats={"total_tokens": 11, "input_tokens": 6, "output_tokens": 5},
        )

        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/issues/history")

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_issue_by_number = AsyncMock(return_value=None)
        with patch("dashboard_routes.IssueFetcher", return_value=mock_fetcher):
            response = await endpoint(limit=100)

        payload = json.loads(response.body)
        issue = next(
            (x for x in payload["items"] if x["issue_number"] == issue_number), None
        )
        assert issue is not None
        assert (
            issue["issue_url"]
            == f"https://github.com/{config.repo}/issues/{issue_number}"
        )

    @pytest.mark.asyncio
    async def test_issue_history_fallback_skips_when_repo_missing(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        from prompt_telemetry import PromptTelemetry

        config.repo = ""
        issue_number = 271
        telemetry = PromptTelemetry(config)
        telemetry.record(
            source="implementer",
            tool="codex",
            model="gpt-5",
            issue_number=issue_number,
            pr_number=0,
            session_id="sess-no-repo",
            prompt_chars=10,
            transcript_chars=5,
            duration_seconds=0.1,
            success=True,
            stats={"total_tokens": 9, "input_tokens": 4, "output_tokens": 5},
        )

        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/issues/history")

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_issue_by_number = AsyncMock(return_value=None)
        with patch("dashboard_routes.IssueFetcher", return_value=mock_fetcher):
            response = await endpoint(limit=100)

        payload = json.loads(response.body)
        issue = next(
            (x for x in payload["items"] if x["issue_number"] == issue_number), None
        )
        assert issue is not None
        assert issue["issue_url"] == ""

    @pytest.mark.asyncio
    async def test_issue_history_fallback_strips_github_url_prefix(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        from prompt_telemetry import PromptTelemetry

        config.repo = "https://github.com/test-org/test-repo"
        issue_number = 419
        telemetry = PromptTelemetry(config)
        telemetry.record(
            source="implementer",
            tool="codex",
            model="gpt-5",
            issue_number=issue_number,
            pr_number=0,
            session_id="sess-strip-prefix",
            prompt_chars=10,
            transcript_chars=5,
            duration_seconds=0.1,
            success=True,
            stats={"total_tokens": 7, "input_tokens": 3, "output_tokens": 4},
        )

        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/issues/history")

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_issue_by_number = AsyncMock(return_value=None)
        with patch("dashboard_routes.IssueFetcher", return_value=mock_fetcher):
            response = await endpoint(limit=100)

        payload = json.loads(response.body)
        issue = next(
            (x for x in payload["items"] if x["issue_number"] == issue_number), None
        )
        assert issue is not None
        assert (
            issue["issue_url"]
            == f"https://github.com/test-org/test-repo/issues/{issue_number}"
        )

    @pytest.mark.asyncio
    async def test_issue_history_fallback_strips_http_github_url_prefix(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        from prompt_telemetry import PromptTelemetry

        config.repo = "http://github.com/test-org/test-repo"
        issue_number = 420
        telemetry = PromptTelemetry(config)
        telemetry.record(
            source="implementer",
            tool="codex",
            model="gpt-5",
            issue_number=issue_number,
            pr_number=0,
            session_id="sess-strip-http-prefix",
            prompt_chars=10,
            transcript_chars=5,
            duration_seconds=0.1,
            success=True,
            stats={"total_tokens": 6, "input_tokens": 3, "output_tokens": 3},
        )

        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/issues/history")

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_issue_by_number = AsyncMock(return_value=None)
        with patch("dashboard_routes.IssueFetcher", return_value=mock_fetcher):
            response = await endpoint(limit=100)

        payload = json.loads(response.body)
        issue = next(
            (x for x in payload["items"] if x["issue_number"] == issue_number), None
        )
        assert issue is not None
        assert (
            issue["issue_url"]
            == f"https://github.com/test-org/test-repo/issues/{issue_number}"
        )

    @pytest.mark.asyncio
    async def test_issue_history_uses_latest_status_not_highest_rank(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)

        endpoint = find_endpoint(router, "/api/issues/history")

        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.WORKER_UPDATE,
                timestamp="2026-02-25T00:00:00+00:00",
                data={"issue": 88, "status": "failed", "worker": 1},
            )
        )
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.WORKER_UPDATE,
                timestamp="2026-02-25T00:05:00+00:00",
                data={"issue": 88, "status": "running", "worker": 1},
            )
        )

        response = await endpoint(limit=100)
        payload = json.loads(response.body)
        issue = next((x for x in payload["items"] if x["issue_number"] == 88), None)
        assert issue is not None
        assert issue["status"] == "active"

    @pytest.mark.asyncio
    async def test_issue_history_merges_with_pr_created_outside_range(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/issues/history")

        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.PR_CREATED,
                timestamp="2026-02-01T00:00:00+00:00",
                data={"issue": 99, "pr": 9001},
            )
        )
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.MERGE_UPDATE,
                timestamp="2026-02-20T00:00:00+00:00",
                data={"pr": 9001, "status": "merged"},
            )
        )

        response = await endpoint(
            since="2026-02-10T00:00:00+00:00", until="2026-02-28T00:00:00+00:00"
        )
        payload = json.loads(response.body)
        issue = next((x for x in payload["items"] if x["issue_number"] == 99), None)
        assert issue is not None
        assert issue["status"] == "merged"
        assert issue["prs"][0]["number"] == 9001
        assert issue["prs"][0]["merged"] is True

    @pytest.mark.asyncio
    async def test_issue_history_filters_by_status_and_query(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/issues/history")

        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                timestamp="2026-02-21T00:00:00+00:00",
                data={"issue": 101, "title": "Fix auth cache"},
            )
        )
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.WORKER_UPDATE,
                timestamp="2026-02-21T00:01:00+00:00",
                data={"issue": 101, "status": "running", "worker": 1},
            )
        )

        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                timestamp="2026-02-21T00:00:00+00:00",
                data={"issue": 102, "title": "Merge docs"},
            )
        )
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.PR_CREATED,
                timestamp="2026-02-21T00:02:00+00:00",
                data={"issue": 102, "pr": 3002},
            )
        )
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.MERGE_UPDATE,
                timestamp="2026-02-21T00:03:00+00:00",
                data={"pr": 3002, "status": "merged"},
            )
        )

        response = await endpoint(status="merged", query="docs")
        payload = json.loads(response.body)
        assert len(payload["items"]) == 1
        assert payload["items"][0]["issue_number"] == 102

    @pytest.mark.asyncio
    async def test_issue_history_linked_issues_carry_kind(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """linked_issues populated via GitHub enrichment carry kind through."""
        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/issues/history")

        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                timestamp="2026-02-21T00:00:00+00:00",
                data={"issue": 200, "title": "Test linked kinds"},
            )
        )

        # Mock GitHub enrichment to return an issue with link patterns in body
        mock_issue = type(
            "MockIssue",
            (),
            {
                "number": 200,
                "title": "Test linked kinds",
                "url": "https://example.com/issues/200",
                "labels": [],
                "body": "relates to #5\nduplicates #10",
            },
        )()
        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_issue_by_number = AsyncMock(return_value=mock_issue)
        with patch("dashboard_routes.IssueFetcher", return_value=mock_fetcher):
            response = await endpoint(limit=100)

        payload = json.loads(response.body)
        issue = next((x for x in payload["items"] if x["issue_number"] == 200), None)
        assert issue is not None
        links = issue["linked_issues"]
        assert len(links) >= 2
        by_id = {lnk["target_id"]: lnk for lnk in links}
        assert by_id[5]["kind"] == "relates_to"
        assert by_id[10]["kind"] == "duplicates"
        for link in links:
            assert isinstance(link, dict)
            assert "target_id" in link
            assert "kind" in link
            assert "target_url" in link

    @pytest.mark.asyncio
    async def test_issue_history_linked_issues_empty_is_list(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """An issue with no links still returns an empty list (not ints)."""
        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/issues/history")

        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                timestamp="2026-02-21T00:00:00+00:00",
                data={"issue": 201, "title": "No links here"},
            )
        )

        response = await endpoint(limit=100)
        payload = json.loads(response.body)
        issue = next((x for x in payload["items"] if x["issue_number"] == 201), None)
        assert issue is not None
        assert issue["linked_issues"] == []

    @pytest.mark.asyncio
    async def test_issue_history_includes_crate_fields(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Issue history items include crate_number and crate_title fields."""
        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/issues/history")

        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                timestamp="2026-02-21T00:00:00+00:00",
                data={"issue": 301, "title": "Crate test issue"},
            )
        )

        response = await endpoint(limit=100)
        payload = json.loads(response.body)
        issue = next((x for x in payload["items"] if x["issue_number"] == 301), None)
        assert issue is not None
        assert "crate_number" in issue
        assert "crate_title" in issue
        # Default values when no milestone is attached
        assert issue["crate_number"] is None
        assert issue["crate_title"] == ""

    @pytest.mark.asyncio
    async def test_issue_history_crate_number_from_event(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Milestone number from ISSUE_CREATED event flows into crate_number."""
        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/issues/history")

        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                timestamp="2026-02-21T00:00:00+00:00",
                data={
                    "issue": 302,
                    "title": "Issue with milestone",
                    "milestone_number": 5,
                },
            )
        )

        response = await endpoint(limit=100)
        payload = json.loads(response.body)
        issue = next((x for x in payload["items"] if x["issue_number"] == 302), None)
        assert issue is not None
        assert issue["crate_number"] == 5

    @pytest.mark.asyncio
    async def test_issue_history_crate_number_string_coerced(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Milestone number supplied as string is coerced to int."""
        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/issues/history")

        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                timestamp="2026-02-21T00:00:00+00:00",
                data={
                    "issue": 303,
                    "title": "String milestone",
                    "milestone_number": "7",
                },
            )
        )

        response = await endpoint(limit=100)
        payload = json.loads(response.body)
        issue = next((x for x in payload["items"] if x["issue_number"] == 303), None)
        assert issue is not None
        assert issue["crate_number"] == 7

    @pytest.mark.asyncio
    async def test_issue_history_crate_number_not_overwritten(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """First milestone_number wins; later events do not overwrite."""
        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/issues/history")

        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                timestamp="2026-02-21T00:00:00+00:00",
                data={
                    "issue": 304,
                    "title": "First milestone",
                    "milestone_number": 3,
                },
            )
        )
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                timestamp="2026-02-21T01:00:00+00:00",
                data={
                    "issue": 304,
                    "title": "Second milestone",
                    "milestone_number": 9,
                },
            )
        )

        response = await endpoint(limit=100)
        payload = json.loads(response.body)
        issue = next((x for x in payload["items"] if x["issue_number"] == 304), None)
        assert issue is not None
        assert issue["crate_number"] == 3

    @pytest.mark.asyncio
    async def test_issue_history_crate_title_empty_on_fetch_failure(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """When milestone lookup fails, items still have empty crate_title."""
        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/issues/history")

        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                timestamp="2026-02-21T00:00:00+00:00",
                data={
                    "issue": 305,
                    "title": "Milestone fetch fails",
                    "milestone_number": 10,
                },
            )
        )

        with patch.object(
            pr_mgr,
            "list_milestones",
            new_callable=AsyncMock,
            side_effect=RuntimeError("API down"),
        ):
            response = await endpoint(limit=100)

        payload = json.loads(response.body)
        issue = next((x for x in payload["items"] if x["issue_number"] == 305), None)
        assert issue is not None
        assert issue["crate_number"] == 10
        assert issue["crate_title"] == ""


class TestIssueHistoryEpicBackfill:
    """Tests that epic field is backfilled from state's epic tracking."""

    @pytest.mark.asyncio
    async def test_epic_backfilled_from_epic_state(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """When an issue is a child of an epic, the epic title is shown."""
        from models import EpicState

        # Register the epic with a child issue in state
        state.upsert_epic_state(
            EpicState(epic_number=100, title="My Big Epic", child_issues=[42])
        )

        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/issues/history")

        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                data={"issue": 42, "title": "Child issue"},
            )
        )

        response = await endpoint(limit=100)
        payload = json.loads(response.body)
        issue = next((x for x in payload["items"] if x["issue_number"] == 42), None)
        assert issue is not None
        assert issue["epic"] == "My Big Epic"

    @pytest.mark.asyncio
    async def test_epic_not_overwritten_when_already_set(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Epic from event labels takes precedence over state backfill."""
        from models import EpicState

        state.upsert_epic_state(
            EpicState(epic_number=100, title="State Epic", child_issues=[43])
        )

        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/issues/history")

        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                data={
                    "issue": 43,
                    "title": "Child with label",
                    "labels": ["epic:ui-overhaul"],
                },
            )
        )

        response = await endpoint(limit=100)
        payload = json.loads(response.body)
        issue = next((x for x in payload["items"] if x["issue_number"] == 43), None)
        assert issue is not None
        # Label-derived epic takes precedence
        assert issue["epic"] == "epic:ui-overhaul"

    @pytest.mark.asyncio
    async def test_epic_empty_when_no_epic(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Issues not belonging to any epic have empty epic field."""
        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/issues/history")

        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                data={"issue": 44, "title": "Standalone issue"},
            )
        )

        response = await endpoint(limit=100)
        payload = json.loads(response.body)
        issue = next((x for x in payload["items"] if x["issue_number"] == 44), None)
        assert issue is not None
        assert issue["epic"] == ""

    @pytest.mark.asyncio
    async def test_epic_fallback_title_when_epic_has_no_title(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """When epic state has no title, fallback to 'Epic #N'."""
        from models import EpicState

        state.upsert_epic_state(EpicState(epic_number=200, title="", child_issues=[45]))

        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/issues/history")

        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                data={"issue": 45, "title": "Child of untitled epic"},
            )
        )

        response = await endpoint(limit=100)
        payload = json.loads(response.body)
        issue = next((x for x in payload["items"] if x["issue_number"] == 45), None)
        assert issue is not None
        assert issue["epic"] == "Epic #200"


class TestIssueHistoryEpicLabelFiltering:
    """Tests that internal epic labels are filtered out during enrichment."""

    @pytest.mark.asyncio
    async def test_internal_epic_labels_skipped(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Labels like 'hydraflow-epic-child' should not be used as epic name."""
        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/issues/history")

        # Emit event with internal epic label only
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                data={
                    "issue": 50,
                    "title": "Issue with internal label",
                    "labels": ["hydraflow-epic-child", "bug"],
                },
            )
        )

        response = await endpoint(limit=100)
        payload = json.loads(response.body)
        issue = next((x for x in payload["items"] if x["issue_number"] == 50), None)
        assert issue is not None
        # Internal labels should be filtered out, leaving epic empty
        assert issue["epic"] == ""

    @pytest.mark.asyncio
    async def test_real_epic_label_kept(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Real epic labels like 'epic:payments' should be used."""
        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/issues/history")

        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                data={
                    "issue": 51,
                    "title": "Issue with real epic label",
                    "labels": ["hydraflow-epic-child", "epic:payments"],
                },
            )
        )

        response = await endpoint(limit=100)
        payload = json.loads(response.body)
        issue = next((x for x in payload["items"] if x["issue_number"] == 51), None)
        assert issue is not None
        assert issue["epic"] == "epic:payments"


class TestIssueHistoryOutcomeDerivation:
    """Tests that outcome is derived from merged PRs when not explicitly recorded."""

    @pytest.mark.asyncio
    async def test_outcome_derived_from_merged_pr(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Issue with a merged PR but no recorded outcome should derive 'merged'."""
        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/issues/history")

        # Create issue and add a merged PR
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                data={"issue": 60, "title": "Issue with merged PR"},
            )
        )
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.PR_CREATED,
                data={"issue": 60, "pr_number": 100, "title": "Fix #60"},
            )
        )
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.MERGE_UPDATE,
                data={"issue": 60, "pr": 100, "status": "merged"},
            )
        )

        response = await endpoint(limit=100)
        payload = json.loads(response.body)
        issue = next((x for x in payload["items"] if x["issue_number"] == 60), None)
        assert issue is not None
        assert issue["outcome"] is not None
        assert issue["outcome"]["outcome"] == "merged"
        assert issue["outcome"]["pr_number"] == 100

    @pytest.mark.asyncio
    async def test_outcome_not_derived_when_already_recorded(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Explicit outcome should not be overwritten by PR-derived one."""
        from models import IssueOutcomeType

        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/issues/history")

        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                data={"issue": 61, "title": "Issue with explicit outcome"},
            )
        )
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.PR_CREATED,
                data={"issue": 61, "pr_number": 101, "title": "Fix #61"},
            )
        )
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.MERGE_UPDATE,
                data={"issue": 61, "pr": 101, "status": "merged"},
            )
        )

        # Record an explicit outcome
        state.record_outcome(
            issue_number=61,
            outcome=IssueOutcomeType.HITL_APPROVED,
            reason="Approved by human",
            phase="hitl",
        )

        response = await endpoint(limit=100)
        payload = json.loads(response.body)
        issue = next((x for x in payload["items"] if x["issue_number"] == 61), None)
        assert issue is not None
        assert issue["outcome"]["outcome"] == "hitl_approved"

    @pytest.mark.asyncio
    async def test_outcome_not_derived_without_merged_pr(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Issue with unmerged PR and no outcome should have no outcome."""
        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/issues/history")

        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                data={"issue": 62, "title": "Issue with open PR"},
            )
        )
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.PR_CREATED,
                data={"issue": 62, "pr_number": 102, "title": "Fix #62"},
            )
        )

        response = await endpoint(limit=100)
        payload = json.loads(response.body)
        issue = next((x for x in payload["items"] if x["issue_number"] == 62), None)
        assert issue is not None
        assert issue["outcome"] is None


class TestIssueHistoryCache:
    """Tests for issue history disk cache (save / load / warm-up / invalidation)."""

    @pytest.mark.asyncio
    async def test_save_load_round_trip_preserves_int_keys(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Cache round-trip: int keys for prs / linked_issues survive JSON."""
        from prompt_telemetry import PromptTelemetry

        telemetry = PromptTelemetry(config)
        telemetry.record(
            source="implementer",
            tool="claude",
            model="sonnet",
            issue_number=50,
            pr_number=200,
            session_id="sess-cache",
            prompt_chars=100,
            transcript_chars=50,
            duration_seconds=1.0,
            success=True,
            stats={"total_tokens": 500, "input_tokens": 300, "output_tokens": 200},
        )

        # First request — populates and saves cache.
        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)
        ep = find_endpoint(router, "/api/issues/history")
        resp = await ep(limit=100)
        payload = json.loads(resp.body)
        assert payload["totals"]["issues"] >= 1

        # Verify disk file was written.
        cache_file = config.data_path("metrics", "history_cache.json")
        assert cache_file.is_file()
        raw = json.loads(cache_file.read_text())
        assert "issue_rows" in raw

        # Verify round-trip: load the cache in a fresh router and query again.
        router2, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        ep2 = find_endpoint(router2, "/api/issues/history")
        resp2 = await ep2(limit=100)
        payload2 = json.loads(resp2.body)
        issue = next((x for x in payload2["items"] if x["issue_number"] == 50), None)
        assert issue is not None
        assert issue["prs"][0]["number"] == 200

    @pytest.mark.asyncio
    async def test_corrupt_cache_file_is_ignored(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """A corrupt JSON cache file should not crash router creation."""
        cache_file = config.data_path("metrics", "history_cache.json")
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text("NOT VALID JSON {{{")

        # Router should create without error — corrupt file is silently skipped.
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        ep = find_endpoint(router, "/api/issues/history")

        resp = await ep(limit=10)
        payload = json.loads(resp.body)
        # No crash, returns valid (possibly empty) response.
        assert "items" in payload
        assert "totals" in payload

    @pytest.mark.asyncio
    async def test_missing_cache_file_is_handled(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Missing cache file should not crash router creation."""
        cache_file = config.data_path("metrics", "history_cache.json")
        assert not cache_file.exists()

        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        ep = find_endpoint(router, "/api/issues/history")

        resp = await ep(limit=10)
        payload = json.loads(resp.body)
        assert "items" in payload

    @pytest.mark.asyncio
    async def test_cache_hit_skips_aggregation(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Second identical request within TTL should hit cache."""
        from prompt_telemetry import PromptTelemetry

        telemetry = PromptTelemetry(config)
        telemetry.record(
            source="planner",
            tool="claude",
            model="opus",
            issue_number=99,
            pr_number=0,
            session_id="sess-hit",
            prompt_chars=50,
            transcript_chars=20,
            duration_seconds=0.5,
            success=True,
            stats={"total_tokens": 80},
        )

        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        ep = find_endpoint(router, "/api/issues/history")

        resp1 = await ep(limit=100)
        p1 = json.loads(resp1.body)
        assert p1["totals"]["issues"] >= 1

        # Second call — same event count and telemetry mtime → cache hit.
        resp2 = await ep(limit=100)
        p2 = json.loads(resp2.body)
        assert p2["totals"]["issues"] == p1["totals"]["issues"]

    @pytest.mark.asyncio
    async def test_cache_invalidated_by_new_event(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Publishing a new event should invalidate the cache."""
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        ep = find_endpoint(router, "/api/issues/history")

        resp1 = await ep(limit=100)
        json.loads(resp1.body)  # populate cache

        # Publish a new event, changing the event count.
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                data={"issue": 999, "title": "New after cache"},
            )
        )

        resp2 = await ep(limit=100)
        p2 = json.loads(resp2.body)
        # The new issue should appear.
        found = any(x["issue_number"] == 999 for x in p2["items"])
        assert found is True

    @pytest.mark.asyncio
    async def test_load_restores_linked_issues_with_int_keys(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Ensure _load_history_cache restores linked_issues dict keys to int."""
        cache_file = config.data_path("metrics", "history_cache.json")
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        # Simulate JSON file with string keys (as produced by json.dumps).
        cache_data = {
            "event_count": 0,
            "telemetry_mtime": 0.0,
            "issue_rows": {
                "42": {
                    "issue_number": 42,
                    "title": "Test issue",
                    "issue_url": "",
                    "status": "active",
                    "epic": "",
                    "linked_issues": {
                        "5": {"target_id": 5, "kind": "relates_to", "target_url": None},
                        "10": {
                            "target_id": 10,
                            "kind": "duplicates",
                            "target_url": None,
                        },
                    },
                    "prs": {
                        "200": {
                            "number": 200,
                            "url": "https://example.com/pull/200",
                            "merged": False,
                        },
                    },
                    "session_ids": ["sess-a"],
                    "source_calls": {"implementer": 1},
                    "model_calls": {"sonnet": 1},
                    "inference": {
                        "inference_calls": 1,
                        "total_tokens": 100,
                        "input_tokens": 60,
                        "output_tokens": 40,
                        "pruned_chars_total": 0,
                    },
                    "first_seen": "2026-02-20T00:00:00+00:00",
                    "last_seen": "2026-02-21T00:00:00+00:00",
                    "status_updated_at": None,
                },
            },
            "pr_to_issue": {"200": 42},
            "enriched_issues": [42],
        }
        cache_file.write_text(json.dumps(cache_data))

        # Load via router warm-up.
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        ep = find_endpoint(router, "/api/issues/history")

        resp = await ep(limit=100)
        payload = json.loads(resp.body)
        issue = next((x for x in payload["items"] if x["issue_number"] == 42), None)
        assert issue is not None
        assert issue["prs"][0]["number"] == 200
        # linked_issues should have been rebuilt via _build_history_links.
        assert len(issue["linked_issues"]) == 2
        ids = {li["target_id"] for li in issue["linked_issues"]}
        assert ids == {5, 10}


class TestEnrichmentErrorResilience:
    """Tests for error handling in _enrich_issue_history_with_github (issue #2573)."""

    @pytest.mark.asyncio
    async def test_gather_return_exceptions_survives_failing_fetch(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """One failing fetch should not crash enrichment for other issues."""
        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/issues/history")
        assert endpoint is not None, "/api/issues/history route not found"

        # Create two issues
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                timestamp="2026-03-01T00:00:00+00:00",
                data={"issue": 301, "title": "Issue #301"},
            )
        )
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                timestamp="2026-03-01T00:00:01+00:00",
                data={"issue": 302, "title": "Issue #302"},
            )
        )

        # Issue 301 raises, issue 302 succeeds
        good_issue = type(
            "MockIssue",
            (),
            {
                "number": 302,
                "title": "Good issue",
                "url": "https://example.com/issues/302",
                "labels": [],
                "body": "",
                "milestone_number": None,
            },
        )()

        async def _side_effect(num: int):
            if num == 301:
                raise RuntimeError("Network error")
            return good_issue

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_issue_by_number = AsyncMock(side_effect=_side_effect)
        with (
            patch("dashboard_routes.IssueFetcher", return_value=mock_fetcher),
            patch("dashboard_routes.logger") as mock_logger,
        ):
            response = await endpoint(limit=100)

        # Failing fetch for issue 301 should have been logged as a warning
        assert mock_logger.warning.called
        warning_args = mock_logger.warning.call_args[0]
        assert "enrichment" in warning_args[0].lower() or isinstance(
            warning_args[-1], RuntimeError
        )

        payload = json.loads(response.body)
        issue_302 = next(
            (x for x in payload["items"] if x["issue_number"] == 302), None
        )
        assert issue_302 is not None
        assert issue_302["title"] == "Good issue"

    @pytest.mark.asyncio
    async def test_non_integer_target_id_is_skipped(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """A link with a non-integer target_id should be silently skipped."""
        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/issues/history")
        assert endpoint is not None, "/api/issues/history route not found"

        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                timestamp="2026-03-01T00:00:00+00:00",
                data={"issue": 400, "title": "Issue #400"},
            )
        )

        # Return issue with valid link text; we patch parse_task_links
        # to return a link with a non-integer target_id
        mock_issue = type(
            "MockIssue",
            (),
            {
                "number": 400,
                "title": "Has bad link",
                "url": "https://example.com/issues/400",
                "labels": [],
                "body": "relates to #5",
                "milestone_number": None,
            },
        )()

        from models import TaskLink, TaskLinkKind

        bad_link = TaskLink(kind=TaskLinkKind.RELATES_TO, target_id=5)
        # Force target_id to a non-integer via object.__setattr__
        object.__setattr__(bad_link, "target_id", "not-a-number")

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_issue_by_number = AsyncMock(return_value=mock_issue)
        with (
            patch("dashboard_routes.IssueFetcher", return_value=mock_fetcher),
            patch("dashboard_routes.parse_task_links", return_value=[bad_link]),
        ):
            response = await endpoint(limit=100)

        payload = json.loads(response.body)
        issue_400 = next(
            (x for x in payload["items"] if x["issue_number"] == 400), None
        )
        assert issue_400 is not None
        # The bad link should have been skipped
        assert issue_400["linked_issues"] == []


# ---------------------------------------------------------------------------
# Repo-scoped API contract tests
# ---------------------------------------------------------------------------
