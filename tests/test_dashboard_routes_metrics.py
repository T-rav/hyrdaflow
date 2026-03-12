"""Tests for dashboard_routes.py — metrics, insights, and retrospectives."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from events import EventBus


@pytest.fixture(autouse=True)
def _disable_hitl_summary_autowarm(config) -> None:
    """Keep route tests deterministic unless a test explicitly opts in."""
    config.transcript_summarization_enabled = False
    config.gh_token = ""


# ---------------------------------------------------------------------------
# /api/metrics endpoint
# ---------------------------------------------------------------------------


class TestMetricsEndpoint:
    """Tests for the GET /api/metrics endpoint."""

    def _make_router(self, config, event_bus, state, tmp_path):
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

    def _find_endpoint(self, router, path):
        for route in router.routes:
            if (
                hasattr(route, "path")
                and route.path == path
                and hasattr(route, "endpoint")
            ):
                return route.endpoint  # type: ignore[union-attr]
        return None

    @pytest.mark.asyncio
    async def test_metrics_returns_zero_rates_when_no_data(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        router = self._make_router(config, event_bus, state, tmp_path)
        get_metrics = self._find_endpoint(router, "/api/metrics")
        assert get_metrics is not None

        response = await get_metrics()
        data = json.loads(response.body)

        assert data["rates"].get("quality_fix_rate", 0.0) == pytest.approx(0.0)
        assert data["rates"].get("first_pass_approval_rate", 0.0) == pytest.approx(0.0)
        assert data["rates"].get("hitl_escalation_rate", 0.0) == pytest.approx(0.0)
        assert data["lifetime"]["issues_completed"] == 0
        assert data["lifetime"]["prs_merged"] == 0

    @pytest.mark.asyncio
    async def test_metrics_returns_computed_rates(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        # Set up some stats
        for _ in range(10):
            state.record_issue_completed()
        for _ in range(5):
            state.record_pr_merged()
        state.record_quality_fix_rounds(4)
        state.record_review_verdict("approve", fixes_made=False)
        state.record_review_verdict("approve", fixes_made=False)
        state.record_review_verdict("request-changes", fixes_made=True)
        state.record_hitl_escalation()
        state.record_hitl_escalation()
        state.record_implementation_duration(100.0)

        router = self._make_router(config, event_bus, state, tmp_path)
        get_metrics = self._find_endpoint(router, "/api/metrics")
        response = await get_metrics()
        data = json.loads(response.body)

        assert data["rates"]["quality_fix_rate"] == pytest.approx(0.4)  # 4/10
        assert data["rates"]["first_pass_approval_rate"] == pytest.approx(
            2.0 / 3.0
        )  # 2/3
        assert data["rates"]["hitl_escalation_rate"] == pytest.approx(0.2)  # 2/10
        assert data["rates"]["avg_implementation_seconds"] == pytest.approx(
            10.0
        )  # 100/10
        assert data["rates"]["reviewer_fix_rate"] == pytest.approx(1.0 / 3.0)  # 1/3
        assert data["lifetime"]["issues_completed"] == 10
        assert data["lifetime"]["prs_merged"] == 5

    @pytest.mark.asyncio
    async def test_metrics_no_division_by_zero_on_reviews(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """When no reviews exist, approval rate should be 0 not crash."""
        import json

        for _ in range(5):
            state.record_issue_completed()

        router = self._make_router(config, event_bus, state, tmp_path)
        get_metrics = self._find_endpoint(router, "/api/metrics")
        response = await get_metrics()
        data = json.loads(response.body)

        assert data["rates"].get("first_pass_approval_rate", 0.0) == pytest.approx(0.0)
        assert data["rates"].get("reviewer_fix_rate", 0.0) == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_metrics_includes_inference_lifetime_and_session_totals(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        from prompt_telemetry import PromptTelemetry

        telemetry = PromptTelemetry(config)
        telemetry.record(
            source="planner",
            tool="claude",
            model="opus",
            issue_number=1,
            pr_number=0,
            session_id="session-1",
            prompt_chars=100,
            transcript_chars=50,
            duration_seconds=0.1,
            success=True,
            stats={"total_tokens": 60},
        )

        class Orch:
            current_session_id = "session-1"

        def _get_orch():
            return Orch()

        # Build router with orchestrator getter override
        from dashboard_routes import create_router
        from pr_manager import PRManager

        pr_mgr = PRManager(config, event_bus)
        router = create_router(
            config=config,
            event_bus=event_bus,
            state=state,
            pr_manager=pr_mgr,
            get_orchestrator=_get_orch,
            set_orchestrator=lambda o: None,
            set_run_task=lambda t: None,
            ui_dist_dir=tmp_path / "no-dist",
            template_dir=tmp_path / "no-templates",
        )
        get_metrics = self._find_endpoint(router, "/api/metrics")
        response = await get_metrics()
        data = json.loads(response.body)
        assert data["inference_lifetime"]["total_tokens"] == 60
        assert data["inference_session"]["total_tokens"] == 60


class TestGitHubMetricsEndpoint:
    """Tests for the GET /api/metrics/github endpoint."""

    def _make_router(self, config, event_bus, state, tmp_path):
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
        ), pr_mgr

    def _find_endpoint(self, router, path):
        for route in router.routes:
            if (
                hasattr(route, "path")
                and route.path == path
                and hasattr(route, "endpoint")
            ):
                return route.endpoint
        return None

    @pytest.mark.asyncio
    async def test_github_metrics_returns_label_counts(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        router, pr_mgr = self._make_router(config, event_bus, state, tmp_path)

        mock_counts = {
            "open_by_label": {
                "hydraflow-plan": 3,
                "hydraflow-ready": 1,
                "hydraflow-review": 2,
                "hydraflow-hitl": 0,
                "hydraflow-fixed": 0,
            },
            "total_closed": 10,
            "total_merged": 8,
        }
        pr_mgr.get_label_counts = AsyncMock(return_value=mock_counts)

        get_github_metrics = self._find_endpoint(router, "/api/metrics/github")
        assert get_github_metrics is not None

        response = await get_github_metrics()
        data = json.loads(response.body)

        assert data["open_by_label"]["hydraflow-plan"] == 3
        assert data["total_closed"] == 10
        assert data["total_merged"] == 8


class TestMetricsHistoryEndpoint:
    """Tests for GET /api/metrics/history endpoint — local-cache fallback path."""

    def _make_router(self, config, event_bus, state, tmp_path):
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

    def _find_endpoint(self, router, path):
        for route in router.routes:
            if (
                hasattr(route, "path")
                and route.path == path
                and hasattr(route, "endpoint")
            ):
                return route.endpoint
        return None

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_cache(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Returns empty snapshots list when orchestrator is None and no local cache."""
        import json

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/metrics/history")
        assert endpoint is not None

        response = await endpoint()
        data = json.loads(response.body)
        assert data["snapshots"] == []

    @pytest.mark.asyncio
    async def test_returns_local_cache_when_no_orchestrator(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Serves metrics snapshots from local disk cache when orchestrator is None."""
        import json

        from metrics_manager import get_metrics_cache_dir
        from models import MetricsSnapshot

        # Write a snapshot directly to the local cache
        snap = MetricsSnapshot(timestamp="2025-06-01T00:00:00", issues_completed=7)
        cache_dir = get_metrics_cache_dir(config)
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / "snapshots.jsonl"
        cache_file.write_text(snap.model_dump_json() + "\n")

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/metrics/history")
        assert endpoint is not None

        response = await endpoint()
        data = json.loads(response.body)
        assert len(data["snapshots"]) == 1
        assert data["snapshots"][0]["issues_completed"] == 7


# ---------------------------------------------------------------------------
# Narrowed exception handling (issue #879)
# ---------------------------------------------------------------------------


class TestLoadLocalMetricsCacheExceptionHandling:
    """Verify _load_local_metrics_cache skips corrupt lines with debug logging."""

    def test_skips_corrupt_lines_with_logging(
        self, config, event_bus: EventBus, state, tmp_path: Path, caplog
    ) -> None:
        """Corrupt lines in metrics cache should be skipped with debug logging."""
        import logging

        from dashboard_routes import create_router
        from metrics_manager import get_metrics_cache_dir
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

        # Write corrupt lines to the metrics cache file
        cache_dir = get_metrics_cache_dir(config)
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / "snapshots.jsonl"
        cache_file.write_text("corrupt line\nalso bad\n")

        # Find the _load_local_metrics_cache function through the metrics/history endpoint
        history_endpoint = None
        for route in router.routes:
            if (
                hasattr(route, "path")
                and route.path == "/api/metrics/history"
                and hasattr(route, "endpoint")
            ):
                history_endpoint = route.endpoint
                break

        assert history_endpoint is not None

        import asyncio

        with caplog.at_level(logging.DEBUG, logger="hydraflow.dashboard"):
            asyncio.run(history_endpoint())

        assert "Skipping corrupt metrics snapshot line" in caplog.text

    def test_load_local_metrics_cache_returns_empty_on_oserror(
        self, config, event_bus: EventBus, state, tmp_path: Path, caplog
    ) -> None:
        """When the cache file can't be read due to OSError, return empty snapshots."""
        import asyncio
        import logging
        from unittest.mock import patch

        from dashboard_routes import create_router
        from metrics_manager import get_metrics_cache_dir
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

        # Create a valid cache file first so exists() returns True
        cache_dir = get_metrics_cache_dir(config)
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / "snapshots.jsonl"
        cache_file.write_text('{"timestamp": "2025-01-01T00:00:00"}\n')

        # Find the metrics/history endpoint
        history_endpoint = None
        for route in router.routes:
            if (
                hasattr(route, "path")
                and route.path == "/api/metrics/history"
                and hasattr(route, "endpoint")
            ):
                history_endpoint = route.endpoint
                break

        assert history_endpoint is not None

        with (
            patch("builtins.open", side_effect=OSError("permission denied")),
            caplog.at_level(logging.WARNING, logger="hydraflow.dashboard"),
        ):
            response = asyncio.run(history_endpoint())

        assert "Could not read metrics cache" in caplog.text
        # Should return response with empty snapshots
        import json

        data = json.loads(response.body)
        assert data["snapshots"] == []


# ---------------------------------------------------------------------------
# /api/runs endpoints
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# GET /api/review-insights
# ---------------------------------------------------------------------------


class TestReviewInsightsEndpoint:
    """Tests for the /api/review-insights endpoint."""

    def _make_router(self, config, event_bus, state, tmp_path):
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

    def _find_endpoint(self, router, path):
        for route in router.routes:
            if (
                hasattr(route, "path")
                and route.path == path
                and hasattr(route, "endpoint")
            ):
                return route.endpoint
        return None

    @pytest.mark.asyncio
    async def test_review_insights_returns_empty(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/review-insights")
        response = await endpoint()
        data = json.loads(response.body)
        assert data["total_reviews"] == 0
        assert data["patterns"] == []
        assert data["verdict_counts"] == {}
        assert data["category_counts"] == {}
        assert data["fixes_made_count"] == 0
        assert data["proposed_categories"] == []

    @pytest.mark.asyncio
    async def test_review_insights_with_data(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json
        from unittest.mock import MagicMock, patch

        from hindsight import HindsightMemory
        from review_insights import ReviewRecord

        record1 = ReviewRecord(
            pr_number=1,
            issue_number=10,
            timestamp="2024-01-01T00:00:00Z",
            verdict="approve",
            summary="Looks good",
            fixes_made=False,
            categories=["code_quality"],
        )
        record2 = ReviewRecord(
            pr_number=2,
            issue_number=11,
            timestamp="2024-01-02T00:00:00Z",
            verdict="request-changes",
            summary="Missing tests",
            fixes_made=True,
            categories=["missing_tests"],
        )

        memories = [
            HindsightMemory(content=record1.model_dump_json()),
            HindsightMemory(content=record2.model_dump_json()),
        ]

        mock_hindsight = MagicMock()

        from dashboard_routes import create_router
        from pr_manager import PRManager

        pr_mgr = PRManager(config, event_bus)
        with patch(
            "hindsight.recall_safe", new_callable=AsyncMock, return_value=memories
        ):
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
                hindsight=mock_hindsight,
            )
            endpoint = self._find_endpoint(router, "/api/review-insights")
            response = await endpoint()

        data = json.loads(response.body)
        assert data["total_reviews"] == 2
        assert data["fixes_made_count"] == 1
        assert "approve" in data["verdict_counts"]
        assert "request-changes" in data["verdict_counts"]
        assert "code_quality" in data["category_counts"]
        assert "missing_tests" in data["category_counts"]


# ---------------------------------------------------------------------------
# GET /api/retrospectives
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# GET /api/retrospectives
# ---------------------------------------------------------------------------


class TestRetrospectivesEndpoint:
    """Tests for the /api/retrospectives endpoint."""

    def _make_router(self, config, event_bus, state, tmp_path):
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

    def _find_endpoint(self, router, path):
        for route in router.routes:
            if (
                hasattr(route, "path")
                and route.path == path
                and hasattr(route, "endpoint")
            ):
                return route.endpoint
        return None

    @pytest.mark.asyncio
    async def test_retrospectives_returns_empty(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/retrospectives")
        response = await endpoint()
        data = json.loads(response.body)
        assert data["total_entries"] == 0
        assert data["entries"] == []
        assert data["verdict_counts"] == {}

    @pytest.mark.asyncio
    async def test_retrospectives_with_data(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json
        from unittest.mock import MagicMock, patch

        from hindsight import HindsightMemory
        from retrospective import RetrospectiveEntry

        entry = RetrospectiveEntry(
            issue_number=10,
            pr_number=1,
            timestamp="2024-01-01T00:00:00Z",
            plan_accuracy_pct=85.0,
            quality_fix_rounds=1,
            review_verdict="approve",
            reviewer_fixes_made=False,
            ci_fix_rounds=0,
            duration_seconds=120.0,
        )

        memories = [HindsightMemory(content=entry.model_dump_json())]
        mock_hindsight = MagicMock()

        from dashboard_routes import create_router
        from pr_manager import PRManager

        pr_mgr = PRManager(config, event_bus)
        with patch(
            "hindsight.recall_safe", new_callable=AsyncMock, return_value=memories
        ):
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
                hindsight=mock_hindsight,
            )
            endpoint = self._find_endpoint(router, "/api/retrospectives")
            response = await endpoint()

        data = json.loads(response.body)
        assert data["total_entries"] == 1
        assert data["avg_plan_accuracy"] == 85.0
        assert data["avg_quality_fix_rounds"] == 1.0
        assert data["avg_ci_fix_rounds"] == 0.0
        assert data["avg_duration_seconds"] == 120.0
        assert data["reviewer_fix_rate"] == 0.0
        assert len(data["entries"]) == 1


# ---------------------------------------------------------------------------
# GET /api/memories
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# GET /api/retrospectives — edge cases
# ---------------------------------------------------------------------------


class TestRetrospectivesEdgeCases:
    """Edge-case tests for the /api/retrospectives endpoint."""

    def _make_router(self, config, event_bus, state, tmp_path):
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

    def _find_endpoint(self, router, path):
        for route in router.routes:
            if (
                hasattr(route, "path")
                and route.path == path
                and hasattr(route, "endpoint")
            ):
                return route.endpoint
        return None

    @pytest.mark.asyncio
    async def test_retrospectives_malformed_jsonl_skipped(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Malformed memories should be silently skipped."""
        import json
        from unittest.mock import MagicMock, patch

        from hindsight import HindsightMemory
        from retrospective import RetrospectiveEntry

        valid = RetrospectiveEntry(
            issue_number=10,
            pr_number=1,
            timestamp="2024-01-01T00:00:00Z",
            plan_accuracy_pct=90.0,
            quality_fix_rounds=0,
            review_verdict="approve",
            reviewer_fixes_made=False,
            ci_fix_rounds=0,
            duration_seconds=60.0,
        )
        # Simulate Hindsight returning a mix of valid and invalid memories
        memories = [
            HindsightMemory(content="not valid json at all"),
            HindsightMemory(content='{"issue_number": 99}'),
            HindsightMemory(content=valid.model_dump_json()),
        ]
        mock_hindsight = MagicMock()

        from dashboard_routes import create_router
        from pr_manager import PRManager

        pr_mgr = PRManager(config, event_bus)
        with patch(
            "hindsight.recall_safe", new_callable=AsyncMock, return_value=memories
        ):
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
                hindsight=mock_hindsight,
            )
            endpoint = self._find_endpoint(router, "/api/retrospectives")
            response = await endpoint()

        data = json.loads(response.body)
        assert data["total_entries"] == 1
        assert data["avg_plan_accuracy"] == 90.0


# ---------------------------------------------------------------------------
# Crate (milestone) endpoint tests
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# GET /api/harness-insights and /api/harness-insights/history
# ---------------------------------------------------------------------------


class TestHarnessInsightsEndpoints:
    """Tests for harness-insights endpoints."""

    def _make_router(self, config, event_bus, state, tmp_path):
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

    def _find_endpoint(self, router, path):
        for route in router.routes:
            if (
                hasattr(route, "path")
                and route.path == path
                and hasattr(route, "endpoint")
            ):
                return route.endpoint
        return None

    @pytest.mark.asyncio
    async def test_harness_insights_returns_empty(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/harness-insights")
        response = await endpoint()
        data = json.loads(response.body)
        assert data["total_failures"] == 0
        assert data["suggestions"] == []

    @pytest.mark.asyncio
    async def test_harness_insights_history_returns_empty(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/harness-insights/history")
        response = await endpoint()
        data = json.loads(response.body)
        assert data == []


# ---------------------------------------------------------------------------
# POST /api/hitl/{issue_number}/close
# ---------------------------------------------------------------------------
