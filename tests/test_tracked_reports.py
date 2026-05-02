"""Tests for tracked bug report feature: models, state, and API endpoints."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from models import (
    ReportHistoryEntry,
    ReportIssueRequest,
    TrackedReport,
    TrackedReportUpdate,
)

# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------


def _build_router_and_mgr(config, event_bus, state, tmp_path):
    """Build a dashboard router and PRManager for endpoint tests."""
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
    return router, pr_mgr


def _find_route_endpoint(router, path, method="GET"):
    """Return the endpoint function for *path* + *method*, or None."""
    for route in router.routes:
        if not (
            hasattr(route, "path") and route.path == path and hasattr(route, "endpoint")
        ):
            continue
        if hasattr(route, "methods") and method in route.methods:
            return route.endpoint
        if not hasattr(route, "methods"):
            return route.endpoint
    return None


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestTrackedReportModel:
    def test_tracked_report_defaults(self) -> None:
        report = TrackedReport(reporter_id="user-1", description="Bug")
        assert report.status == "queued"
        assert report.reporter_id == "user-1"
        assert report.description == "Bug"
        assert report.linked_issue_url == ""
        assert report.linked_pr_url == ""
        assert report.progress_summary == ""
        assert report.history == []
        assert report.id  # auto-generated
        assert report.created_at  # auto-generated
        assert report.updated_at  # auto-generated

    def test_report_history_entry_defaults(self) -> None:
        entry = ReportHistoryEntry(action="submitted")
        assert entry.action == "submitted"
        assert entry.detail == ""
        assert entry.timestamp  # auto-generated

    def test_report_history_entry_with_detail(self) -> None:
        entry = ReportHistoryEntry(action="reopened", detail="Still broken")
        assert entry.detail == "Still broken"

    def test_tracked_report_update_validation(self) -> None:
        update = TrackedReportUpdate(action="confirm_fixed")
        assert update.action == "confirm_fixed"
        assert update.detail == ""

    def test_tracked_report_update_with_detail(self) -> None:
        update = TrackedReportUpdate(action="reopen", detail="Not quite right")
        assert update.detail == "Not quite right"

    def test_tracked_report_update_invalid_action(self) -> None:
        with pytest.raises(ValidationError):
            TrackedReportUpdate(action="invalid_action")

    def test_report_issue_request_has_reporter_id(self) -> None:
        req = ReportIssueRequest(description="test", reporter_id="abc-123")
        assert req.reporter_id == "abc-123"

    def test_report_issue_request_reporter_id_default(self) -> None:
        req = ReportIssueRequest(description="test")
        assert req.reporter_id == ""


# ---------------------------------------------------------------------------
# State tests
# ---------------------------------------------------------------------------


class TestTrackedReportState:
    def test_add_and_get_tracked_reports(self, state) -> None:
        report = TrackedReport(id="rpt-1", reporter_id="user-1", description="Bug A")
        state.add_tracked_report(report)
        results = state.get_tracked_reports("user-1")
        assert len(results) == 1
        assert results[0].id == "rpt-1"

    def test_get_tracked_reports_filters_by_reporter(self, state) -> None:
        state.add_tracked_report(
            TrackedReport(id="r1", reporter_id="user-1", description="A")
        )
        state.add_tracked_report(
            TrackedReport(id="r2", reporter_id="user-2", description="B")
        )
        assert len(state.get_tracked_reports("user-1")) == 1
        assert len(state.get_tracked_reports("user-2")) == 1
        assert len(state.get_tracked_reports("user-3")) == 0

    def test_get_tracked_report_by_id(self, state) -> None:
        state.add_tracked_report(
            TrackedReport(id="r1", reporter_id="u1", description="X")
        )
        result = state.get_tracked_report("r1")
        assert result is not None
        assert result.description == "X"

    def test_get_tracked_report_not_found(self, state) -> None:
        assert state.get_tracked_report("nonexistent") is None

    def test_update_tracked_report_status(self, state) -> None:
        state.add_tracked_report(
            TrackedReport(id="r1", reporter_id="u1", description="Y")
        )
        updated = state.update_tracked_report(
            "r1", status="closed", detail="Done", action_label="confirm_fixed"
        )
        assert updated is not None
        assert updated.status == "closed"
        assert len(updated.history) == 1
        assert updated.history[0].action == "confirm_fixed"
        assert updated.history[0].detail == "Done"

    def test_update_tracked_report_not_found(self, state) -> None:
        result = state.update_tracked_report(
            "missing", status="closed", action_label="cancel"
        )
        assert result is None

    def test_update_tracked_report_appends_history(self, state) -> None:
        state.add_tracked_report(
            TrackedReport(
                id="r1",
                reporter_id="u1",
                description="Z",
                status="closed",
                history=[ReportHistoryEntry(action="submitted", detail="init")],
            )
        )
        state.update_tracked_report(
            "r1", status="reopened", detail="More info", action_label="reopen"
        )
        report = state.get_tracked_report("r1")
        assert report is not None
        assert len(report.history) == 2
        assert report.history[1].action == "reopen"

    def test_get_tracked_reports_filters_by_status(self, state) -> None:
        """get_tracked_reports(status='filed') returns only filed reports."""
        state.add_tracked_report(
            TrackedReport(id="r1", reporter_id="u1", description="A", status="queued")
        )
        state.add_tracked_report(
            TrackedReport(id="r2", reporter_id="u1", description="B", status="filed")
        )
        state.add_tracked_report(
            TrackedReport(id="r3", reporter_id="u1", description="C", status="filed")
        )
        results = state.get_tracked_reports("u1", status="filed")
        assert len(results) == 2
        assert all(r.status == "filed" for r in results)

    def test_get_tracked_reports_no_status_returns_all(self, state) -> None:
        """get_tracked_reports without status returns all reports for the reporter."""
        state.add_tracked_report(
            TrackedReport(id="r1", reporter_id="u1", description="A", status="queued")
        )
        state.add_tracked_report(
            TrackedReport(id="r2", reporter_id="u1", description="B", status="filed")
        )
        results = state.get_tracked_reports("u1")
        assert len(results) == 2

    def test_get_tracked_reports_status_and_reporter_filter(self, state) -> None:
        """Status filter does not leak reports from other reporters."""
        state.add_tracked_report(
            TrackedReport(id="r1", reporter_id="u1", description="A", status="filed")
        )
        state.add_tracked_report(
            TrackedReport(id="r2", reporter_id="u2", description="B", status="filed")
        )
        results = state.get_tracked_reports("u1", status="filed")
        assert len(results) == 1
        assert results[0].reporter_id == "u1"

    def test_get_tracked_reports_nonexistent_status_returns_empty(self, state) -> None:
        """Filtering by a status with no matches returns empty list."""
        state.add_tracked_report(
            TrackedReport(id="r1", reporter_id="u1", description="A", status="queued")
        )
        results = state.get_tracked_reports("u1", status="fixed")
        assert results == []


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


class TestTrackedReportEndpoints:
    def _make_router(self, config, event_bus, state, tmp_path):
        return _build_router_and_mgr(config, event_bus, state, tmp_path)

    def _find_endpoint(self, router, path, method="GET"):
        return _find_route_endpoint(router, path, method)

    @pytest.mark.asyncio
    async def test_submit_report_creates_tracked_report(
        self, config, event_bus, state, tmp_path
    ) -> None:
        router, _pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/report", "POST")
        request = ReportIssueRequest(
            description="Widget broken", reporter_id="user-abc"
        )
        await endpoint(request)
        reports = state.get_tracked_reports("user-abc")
        assert len(reports) == 1
        assert reports[0].description == "Widget broken"
        assert reports[0].status == "queued"
        assert len(reports[0].history) == 1
        assert reports[0].history[0].action == "submitted"

    @pytest.mark.asyncio
    async def test_submit_report_without_reporter_id_no_tracked(
        self, config, event_bus, state, tmp_path
    ) -> None:
        router, _pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/report", "POST")
        request = ReportIssueRequest(description="No reporter")
        await endpoint(request)
        assert len(state.get_tracked_reports("")) == 0

    @pytest.mark.asyncio
    async def test_list_tracked_reports_empty(
        self, config, event_bus, state, tmp_path
    ) -> None:
        router, _pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/reports", "GET")
        response = await endpoint(reporter_id="user-1")
        data = json.loads(response.body)
        assert data == []

    @pytest.mark.asyncio
    async def test_list_tracked_reports_returns_user_reports(
        self, config, event_bus, state, tmp_path
    ) -> None:
        state.add_tracked_report(
            TrackedReport(id="r1", reporter_id="user-1", description="Bug")
        )
        router, _pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/reports", "GET")
        response = await endpoint(reporter_id="user-1")
        data = json.loads(response.body)
        assert len(data) == 1
        assert data[0]["id"] == "r1"

    @pytest.mark.asyncio
    async def test_list_tracked_reports_no_reporter_id(
        self, config, event_bus, state, tmp_path
    ) -> None:
        router, _pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/reports", "GET")
        response = await endpoint(reporter_id="")
        data = json.loads(response.body)
        assert data == []

    @pytest.mark.asyncio
    async def test_update_tracked_report_confirm_fixed(
        self, config, event_bus, state, tmp_path
    ) -> None:
        state.add_tracked_report(
            TrackedReport(id="r1", reporter_id="u1", description="X", status="fixed")
        )
        router, _pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/reports/{report_id}", "PATCH")
        body = TrackedReportUpdate(action="confirm_fixed")
        response = await endpoint("r1", body)
        data = json.loads(response.body)
        assert data["status"] == "closed"

    @pytest.mark.asyncio
    async def test_update_tracked_report_reopen(
        self, config, event_bus, state, tmp_path
    ) -> None:
        state.add_tracked_report(
            TrackedReport(id="r1", reporter_id="u1", description="X", status="fixed")
        )
        router, _pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/reports/{report_id}", "PATCH")
        body = TrackedReportUpdate(action="reopen", detail="Still fails")
        response = await endpoint("r1", body)
        data = json.loads(response.body)
        assert data["status"] == "reopened"
        # Check history has the reopen entry
        assert any(h["action"] == "reopen" for h in data["history"])

    @pytest.mark.asyncio
    async def test_update_tracked_report_cancel(
        self, config, event_bus, state, tmp_path
    ) -> None:
        state.add_tracked_report(
            TrackedReport(id="r1", reporter_id="u1", description="X")
        )
        router, _pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/reports/{report_id}", "PATCH")
        body = TrackedReportUpdate(action="cancel")
        response = await endpoint("r1", body)
        data = json.loads(response.body)
        assert data["status"] == "closed"

    @pytest.mark.asyncio
    async def test_update_tracked_report_not_found(
        self, config, event_bus, state, tmp_path
    ) -> None:
        router, _pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/reports/{report_id}", "PATCH")
        body = TrackedReportUpdate(action="cancel")
        response = await endpoint("nonexistent", body)
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_report_history(self, config, event_bus, state, tmp_path) -> None:
        state.add_tracked_report(
            TrackedReport(
                id="r1",
                reporter_id="u1",
                description="X",
                history=[
                    ReportHistoryEntry(action="submitted", detail="init"),
                    ReportHistoryEntry(action="processing", detail="in progress"),
                ],
            )
        )
        router, _pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(
            router, "/api/reports/{report_id}/history", "GET"
        )
        response = await endpoint("r1")
        data = json.loads(response.body)
        assert len(data) == 2
        assert data[0]["action"] == "submitted"
        assert data[1]["action"] == "processing"

    @pytest.mark.asyncio
    async def test_get_report_history_not_found(
        self, config, event_bus, state, tmp_path
    ) -> None:
        router, _pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(
            router, "/api/reports/{report_id}/history", "GET"
        )
        response = await endpoint("missing")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_submit_report_links_pending_and_tracked_ids(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """The pending report and tracked report should share the same ID."""
        router, _pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/report", "POST")
        request = ReportIssueRequest(description="Shared ID test", reporter_id="user-x")
        await endpoint(request)
        pending = state.get_pending_reports()
        tracked = state.get_tracked_reports("user-x")
        assert len(pending) == 1
        assert len(tracked) == 1
        assert pending[0].id == tracked[0].id

    @pytest.mark.asyncio
    async def test_update_tracked_report_ownership_rejected(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """PATCH with a mismatched reporter_id returns 403."""
        state.add_tracked_report(
            TrackedReport(
                id="r1", reporter_id="owner-1", description="X", status="fixed"
            )
        )
        router, _pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/reports/{report_id}", "PATCH")
        body = TrackedReportUpdate(action="confirm_fixed", reporter_id="attacker-2")
        response = await endpoint("r1", body)
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_update_tracked_report_invalid_transition_queued_reopen(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Reopening a queued report is not a valid transition."""
        state.add_tracked_report(
            TrackedReport(id="r1", reporter_id="u1", description="X", status="queued")
        )
        router, _pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/reports/{report_id}", "PATCH")
        body = TrackedReportUpdate(action="reopen")
        response = await endpoint("r1", body)
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_update_tracked_report_invalid_transition_confirm_queued(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Confirming a fix on a queued report is not a valid transition."""
        state.add_tracked_report(
            TrackedReport(id="r1", reporter_id="u1", description="X", status="queued")
        )
        router, _pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/reports/{report_id}", "PATCH")
        body = TrackedReportUpdate(action="confirm_fixed")
        response = await endpoint("r1", body)
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Persistence tests
# ---------------------------------------------------------------------------


class TestTrackedReportPersistence:
    """Verify tracked reports survive a full save/reload cycle."""

    def test_tracked_reports_persist_across_reload(self, tmp_path) -> None:
        from state import StateTracker

        state1 = StateTracker(tmp_path / "state.json")
        state1.add_tracked_report(
            TrackedReport(id="r1", reporter_id="u1", description="Persist me")
        )
        state1.update_tracked_report(
            "r1",
            status="in-progress",
            detail="Working on it",
            action_label="processing",
        )

        # Reload from the same file
        state2 = StateTracker(tmp_path / "state.json")
        reports = state2.get_tracked_reports("u1")
        assert len(reports) == 1
        assert reports[0].id == "r1"
        assert reports[0].status == "in-progress"
        assert len(reports[0].history) == 1
        assert reports[0].history[0].action == "processing"


# ---------------------------------------------------------------------------
# Filed status model tests
# ---------------------------------------------------------------------------


class TestFiledStatus:
    def test_tracked_report_filed_status_valid(self) -> None:
        report = TrackedReport(reporter_id="u1", description="Bug", status="filed")
        assert report.status == "filed"

    def test_tracked_report_filed_linked_issue(self) -> None:
        report = TrackedReport(
            reporter_id="u1",
            description="Bug",
            status="filed",
            linked_issue_url="https://github.com/acme/repo/issues/42",
        )
        assert report.linked_issue_url == "https://github.com/acme/repo/issues/42"


# ---------------------------------------------------------------------------
# State methods for filed/stale reports
# ---------------------------------------------------------------------------


class TestFiledAndStaleStateMethods:
    def test_get_filed_reports_returns_only_filed(self, state) -> None:
        state.add_tracked_report(
            TrackedReport(id="r1", reporter_id="u1", description="A", status="filed")
        )
        state.add_tracked_report(
            TrackedReport(id="r2", reporter_id="u1", description="B", status="queued")
        )
        state.add_tracked_report(
            TrackedReport(id="r3", reporter_id="u1", description="C", status="fixed")
        )
        filed = state.get_filed_reports()
        assert len(filed) == 1
        assert filed[0].id == "r1"

    def test_get_filed_reports_empty(self, state) -> None:
        state.add_tracked_report(
            TrackedReport(id="r1", reporter_id="u1", description="A", status="queued")
        )
        assert state.get_filed_reports() == []

    def test_get_stale_queued_reports_returns_old_queued(self, state) -> None:
        from datetime import UTC, datetime, timedelta

        old_time = (datetime.now(UTC) - timedelta(minutes=60)).isoformat()
        state.add_tracked_report(
            TrackedReport(
                id="r1",
                reporter_id="u1",
                description="Old",
                status="queued",
                created_at=old_time,
            )
        )
        state.add_tracked_report(
            TrackedReport(
                id="r2",
                reporter_id="u1",
                description="New",
                status="queued",
            )
        )
        stale = state.get_stale_queued_reports(stale_minutes=30)
        assert len(stale) == 1
        assert stale[0].id == "r1"

    def test_get_stale_queued_reports_ignores_non_queued(self, state) -> None:
        from datetime import UTC, datetime, timedelta

        old_time = (datetime.now(UTC) - timedelta(minutes=60)).isoformat()
        state.add_tracked_report(
            TrackedReport(
                id="r1",
                reporter_id="u1",
                description="Old filed",
                status="filed",
                created_at=old_time,
            )
        )
        stale = state.get_stale_queued_reports(stale_minutes=30)
        assert stale == []


# ---------------------------------------------------------------------------
# Extract issue number helper tests
# ---------------------------------------------------------------------------


class TestExtractIssueNumber:
    def test_valid_issue_url(self) -> None:
        from dashboard_routes._routes import _extract_issue_number

        assert _extract_issue_number("https://github.com/acme/repo/issues/42") == 42

    def test_no_issue_url(self) -> None:
        from dashboard_routes._routes import _extract_issue_number

        assert _extract_issue_number("no url here") == 0

    def test_empty_string(self) -> None:
        from dashboard_routes._routes import _extract_issue_number

        assert _extract_issue_number("") == 0


# ---------------------------------------------------------------------------
# Refresh endpoint tests
# ---------------------------------------------------------------------------


class TestRefreshReportStatuses:
    def _make_router(self, config, event_bus, state, tmp_path):
        return _build_router_and_mgr(config, event_bus, state, tmp_path)

    def _find_endpoint(self, router, path, method="POST"):
        return _find_route_endpoint(router, path, method)

    @pytest.mark.asyncio
    async def test_filed_report_transitions_to_fixed_when_issue_closed(
        self, config, event_bus, state, tmp_path
    ) -> None:
        from unittest.mock import AsyncMock, patch

        state.add_tracked_report(
            TrackedReport(
                id="r1",
                reporter_id="u1",
                description="Bug",
                status="filed",
                linked_issue_url="https://github.com/acme/repo/issues/42",
            )
        )
        router, pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/reports/refresh")
        assert endpoint is not None

        with patch.object(
            pr_mgr, "get_issue_state", new_callable=AsyncMock, return_value="COMPLETED"
        ):
            response = await endpoint(reporter_id="u1")

        data = json.loads(response.body)
        assert len(data["refreshed"]) == 1
        assert data["refreshed"][0]["new_status"] == "fixed"

        report = state.get_tracked_report("r1")
        assert report is not None
        assert report.status == "fixed"

    @pytest.mark.asyncio
    async def test_filed_report_stays_filed_when_issue_open(
        self, config, event_bus, state, tmp_path
    ) -> None:
        from unittest.mock import AsyncMock, patch

        state.add_tracked_report(
            TrackedReport(
                id="r1",
                reporter_id="u1",
                description="Bug",
                status="filed",
                linked_issue_url="https://github.com/acme/repo/issues/42",
            )
        )
        router, pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/reports/refresh")

        with patch.object(
            pr_mgr, "get_issue_state", new_callable=AsyncMock, return_value="OPEN"
        ):
            response = await endpoint(reporter_id="u1")

        data = json.loads(response.body)
        assert len(data["refreshed"]) == 0

        report = state.get_tracked_report("r1")
        assert report is not None
        assert report.status == "filed"

    @pytest.mark.asyncio
    async def test_filed_report_transitions_to_closed_when_issue_not_planned(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Issue closed as 'won't fix' should transition report to 'closed', not 'fixed'."""
        from unittest.mock import AsyncMock, patch

        state.add_tracked_report(
            TrackedReport(
                id="r1",
                reporter_id="u1",
                description="Bug",
                status="filed",
                linked_issue_url="https://github.com/acme/repo/issues/42",
            )
        )
        router, pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/reports/refresh")

        with patch.object(
            pr_mgr,
            "get_issue_state",
            new_callable=AsyncMock,
            return_value="NOT_PLANNED",
        ):
            response = await endpoint(reporter_id="u1")

        data = json.loads(response.body)
        assert len(data["refreshed"]) == 1
        assert data["refreshed"][0]["new_status"] == "closed"

        report = state.get_tracked_report("r1")
        assert report is not None
        assert report.status == "closed"

    @pytest.mark.asyncio
    async def test_stale_queued_report_reenqueued(
        self, config, event_bus, state, tmp_path
    ) -> None:
        from datetime import UTC, datetime, timedelta

        old_time = (datetime.now(UTC) - timedelta(minutes=60)).isoformat()
        state.add_tracked_report(
            TrackedReport(
                id="r-stale",
                reporter_id="u1",
                description="Stale bug",
                status="queued",
                created_at=old_time,
            )
        )
        router, pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/reports/refresh")

        response = await endpoint(reporter_id="u1")
        data = json.loads(response.body)
        assert len(data["refreshed"]) == 1
        assert data["refreshed"][0]["id"] == "r-stale"

        # Verify it was re-enqueued in pending
        pending = state.get_pending_reports()
        assert any(p.id == "r-stale" for p in pending)

    @pytest.mark.asyncio
    async def test_stale_not_reenqueued_if_already_pending(
        self, config, event_bus, state, tmp_path
    ) -> None:
        from datetime import UTC, datetime, timedelta

        from models import PendingReport

        old_time = (datetime.now(UTC) - timedelta(minutes=60)).isoformat()
        state.add_tracked_report(
            TrackedReport(
                id="r-stale",
                reporter_id="u1",
                description="Stale bug",
                status="queued",
                created_at=old_time,
            )
        )
        # Already in pending queue
        state.enqueue_report(
            PendingReport(id="r-stale", description="Stale bug", reporter_id="u1")
        )
        router, pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/reports/refresh")

        response = await endpoint(reporter_id="u1")
        data = json.loads(response.body)
        # Should NOT be re-enqueued since it's already pending
        assert len(data["refreshed"]) == 0

    @pytest.mark.asyncio
    async def test_filed_report_stays_filed_when_state_unknown(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """When get_issue_state returns '' (error or null stateReason), report stays filed."""
        from unittest.mock import AsyncMock, patch

        state.add_tracked_report(
            TrackedReport(
                id="r1",
                reporter_id="u1",
                description="Bug",
                status="filed",
                linked_issue_url="https://github.com/acme/repo/issues/99",
            )
        )
        router, pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/reports/refresh")

        with patch.object(
            pr_mgr, "get_issue_state", new_callable=AsyncMock, return_value=""
        ):
            response = await endpoint(reporter_id="u1")

        data = json.loads(response.body)
        assert len(data["refreshed"]) == 0

        report = state.get_tracked_report("r1")
        assert report is not None
        assert report.status == "filed"


# ---------------------------------------------------------------------------
# Updated state machine transition tests
# ---------------------------------------------------------------------------


class TestFiledStatusTransitions:
    def _make_router(self, config, event_bus, state, tmp_path):
        return _build_router_and_mgr(config, event_bus, state, tmp_path)

    def _find_endpoint(self, router, path, method="PATCH"):
        return _find_route_endpoint(router, path, method)

    @pytest.mark.asyncio
    async def test_cancel_filed_report(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """A filed report can be cancelled."""
        state.add_tracked_report(
            TrackedReport(id="r1", reporter_id="u1", description="X", status="filed")
        )
        router, _pr = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/reports/{report_id}")
        body = TrackedReportUpdate(action="cancel")
        response = await endpoint("r1", body)
        data = json.loads(response.body)
        assert data["status"] == "closed"

    @pytest.mark.asyncio
    async def test_reopen_filed_report(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """A filed report can be reopened."""
        state.add_tracked_report(
            TrackedReport(id="r1", reporter_id="u1", description="X", status="filed")
        )
        router, _pr = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/reports/{report_id}")
        body = TrackedReportUpdate(action="reopen")
        response = await endpoint("r1", body)
        data = json.loads(response.body)
        assert data["status"] == "reopened"

    @pytest.mark.asyncio
    async def test_confirm_fixed_on_filed_not_allowed(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Confirm fixed is NOT allowed on a filed report (only on 'fixed')."""
        state.add_tracked_report(
            TrackedReport(id="r1", reporter_id="u1", description="X", status="filed")
        )
        router, _pr = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/reports/{report_id}")
        body = TrackedReportUpdate(action="confirm_fixed")
        response = await endpoint("r1", body)
        assert response.status_code == 422
