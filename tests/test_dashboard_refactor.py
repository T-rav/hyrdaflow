"""Tests for the dashboard_routes refactoring (issue #2389).

Validates that the extracted modules (RouterDeps, worker defs,
crate routes, HITL routes, history) work correctly and integrate
via router.include_router() composition.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from dashboard_history import (
    _build_history_links,
    _build_issue_history_entry,
    _new_issue_history_entry,
    _process_events_into_rows,
    _touch_issue_timestamps,
    load_history_cache,
    save_history_cache,
)
from dashboard_router_deps import RouterDeps
from dashboard_worker_defs import (
    BG_WORKER_DEFS,
    INTERVAL_BOUNDS,
    INTERVAL_WORKERS,
    PIPELINE_WORKERS,
    WORKER_SOURCE_ALIASES,
)
from events import EventBus, EventType, HydraFlowEvent
from models import IssueOutcome, IssueOutcomeType


@pytest.fixture(autouse=True)
def _disable_hitl_summary_autowarm(config) -> None:
    """Keep route tests deterministic."""
    config.transcript_summarization_enabled = False
    config.gh_token = ""


# ------------------------------------------------------------------
# RouterDeps
# ------------------------------------------------------------------


class TestRouterDeps:
    """Tests for the RouterDeps dependency container."""

    def test_resolve_runtime_no_registry(self, config, state, event_bus: EventBus):
        """Without registry, resolve_runtime returns closure defaults."""
        deps = _make_deps(config, event_bus, state)
        cfg, st, bus, get_orch = deps.resolve_runtime(None)
        assert cfg is config
        assert st is state
        assert bus is event_bus

    def test_resolve_runtime_with_slug_no_registry(
        self, config, state, event_bus: EventBus
    ):
        """With slug but no registry, returns defaults."""
        deps = _make_deps(config, event_bus, state)
        cfg, st, bus, get_orch = deps.resolve_runtime("some-repo")
        assert cfg is config

    def test_resolve_runtime_unknown_repo(self, config, state, event_bus: EventBus):
        """Unknown repo raises HTTPException 404."""
        from fastapi import HTTPException

        mock_registry = MagicMock()
        mock_registry.get.return_value = None
        deps = _make_deps(config, event_bus, state, registry=mock_registry)
        with pytest.raises(HTTPException) as exc_info:
            deps.resolve_runtime("unknown")
        assert exc_info.value.status_code == 404

    def test_pr_manager_for_returns_shared(self, config, state, event_bus: EventBus):
        """When config/bus match, returns the shared pr_manager."""
        from pr_manager import PRManager

        pr_mgr = PRManager(config, event_bus)
        deps = _make_deps(config, event_bus, state, pr_manager=pr_mgr)
        result = deps.pr_manager_for(config, event_bus)
        assert result is pr_mgr

    def test_pr_manager_for_creates_new(self, config, state, event_bus: EventBus):
        """When config differs, creates a new PRManager."""
        from config import HydraFlowConfig
        from pr_manager import PRManager

        pr_mgr = PRManager(config, event_bus)
        deps = _make_deps(config, event_bus, state, pr_manager=pr_mgr)
        other_config = HydraFlowConfig(repo="other/repo")
        result = deps.pr_manager_for(other_config, event_bus)
        assert result is not pr_mgr


# ------------------------------------------------------------------
# Worker Defs
# ------------------------------------------------------------------


class TestWorkerDefs:
    """Tests for the extracted worker definition constants."""

    def test_bg_worker_defs_is_list_of_tuples(self):
        assert isinstance(BG_WORKER_DEFS, list)
        assert len(BG_WORKER_DEFS) >= 10
        for entry in BG_WORKER_DEFS:
            assert len(entry) == 3
            name, label, desc = entry
            assert isinstance(name, str)
            assert isinstance(label, str)
            assert isinstance(desc, str)

    def test_interval_workers_subset_of_defs(self):
        names = {d[0] for d in BG_WORKER_DEFS}
        assert INTERVAL_WORKERS.issubset(names)

    def test_pipeline_workers_subset_of_defs(self):
        names = {d[0] for d in BG_WORKER_DEFS}
        assert PIPELINE_WORKERS.issubset(names)

    def test_no_overlap_between_interval_and_pipeline(self):
        assert INTERVAL_WORKERS.isdisjoint(PIPELINE_WORKERS)

    def test_worker_source_aliases_keys_are_worker_names(self):
        names = {d[0] for d in BG_WORKER_DEFS}
        for key in WORKER_SOURCE_ALIASES:
            assert key in names

    def test_interval_bounds_keys_are_interval_workers_or_special(self):
        for key in INTERVAL_BOUNDS:
            lo, hi = INTERVAL_BOUNDS[key]
            assert lo < hi
            assert lo > 0


# ------------------------------------------------------------------
# History helpers
# ------------------------------------------------------------------


class TestHistoryHelpers:
    """Tests for pure history helper functions."""

    def test_new_issue_history_entry_with_github_url(self):
        row = _new_issue_history_entry(42, "https://github.com/owner/repo")
        assert row["issue_number"] == 42
        assert row["issue_url"] == "https://github.com/owner/repo/issues/42"
        assert row["title"] == "Issue #42"
        assert row["status"] == "unknown"
        assert isinstance(row["session_ids"], set)

    def test_new_issue_history_entry_empty_repo(self):
        row = _new_issue_history_entry(99, "")
        assert row["issue_url"] == ""

    def test_touch_issue_timestamps_first(self):
        row = {"first_seen": None, "last_seen": None}
        _touch_issue_timestamps(row, "2024-01-01T00:00:00Z")
        assert row["first_seen"] == "2024-01-01T00:00:00Z"
        assert row["last_seen"] == "2024-01-01T00:00:00Z"

    def test_touch_issue_timestamps_updates_bounds(self):
        row = {
            "first_seen": "2024-01-02T00:00:00Z",
            "last_seen": "2024-01-02T00:00:00Z",
        }
        _touch_issue_timestamps(row, "2024-01-01T00:00:00Z")
        assert row["first_seen"] == "2024-01-01T00:00:00Z"
        _touch_issue_timestamps(row, "2024-01-03T00:00:00Z")
        assert row["last_seen"] == "2024-01-03T00:00:00Z"

    def test_touch_issue_timestamps_none_ignored(self):
        row = {
            "first_seen": "2024-01-01T00:00:00Z",
            "last_seen": "2024-01-01T00:00:00Z",
        }
        _touch_issue_timestamps(row, None)
        assert row["first_seen"] == "2024-01-01T00:00:00Z"

    def test_build_history_links_from_dict(self):
        raw = {
            5: {"target_id": 5, "kind": "blocks", "target_url": "http://x"},
            3: {"target_id": 3, "kind": "relates_to"},
        }
        links = _build_history_links(raw)
        assert len(links) == 2
        assert links[0].target_id == 3
        assert links[1].target_id == 5
        assert links[1].kind == "blocks"

    def test_build_history_links_from_set(self):
        raw = [10, 5, 0]  # 0 should be filtered out
        links = _build_history_links(raw)
        assert len(links) == 2
        assert links[0].target_id == 5
        assert links[1].target_id == 10

    def test_build_issue_history_entry(self):
        row = _new_issue_history_entry(7, "owner/repo")
        row["title"] = "Test issue"
        row["status"] = "merged"
        row["prs"] = {100: {"number": 100, "url": "http://pr", "merged": True}}
        outcome = IssueOutcome(
            outcome=IssueOutcomeType.MERGED,
            reason="test",
            closed_at="2024-01-01",
            phase="review",
        )
        entry = _build_issue_history_entry(row, outcome)
        assert entry.issue_number == 7
        assert entry.title == "Test issue"
        assert entry.status == "merged"
        assert len(entry.prs) == 1
        assert entry.outcome is not None

    def test_process_events_into_rows_issue_created(self):
        events = [
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                data={
                    "issue": 10,
                    "title": "New Issue",
                    "labels": ["epic:perf"],
                },
            )
        ]
        issue_rows: dict[int, dict[str, Any]] = {}
        pr_to_issue: dict[int, int] = {}
        _process_events_into_rows(
            events, issue_rows, pr_to_issue, None, None, "owner/repo"
        )
        assert 10 in issue_rows
        assert issue_rows[10]["title"] == "New Issue"
        assert issue_rows[10]["epic"] == "epic:perf"

    def test_process_events_pr_created_and_merged(self):
        events = [
            HydraFlowEvent(
                type=EventType.PR_CREATED,
                data={"issue": 5, "pr": 50, "url": "https://pr/50"},
            ),
            HydraFlowEvent(
                type=EventType.MERGE_UPDATE,
                data={"pr": 50, "status": "merged"},
            ),
        ]
        issue_rows: dict[int, dict[str, Any]] = {}
        pr_to_issue: dict[int, int] = {}
        _process_events_into_rows(
            events, issue_rows, pr_to_issue, None, None, "owner/repo"
        )
        assert 5 in issue_rows
        assert pr_to_issue[50] == 5
        assert issue_rows[5]["prs"][50]["merged"] is True


# ------------------------------------------------------------------
# History cache I/O
# ------------------------------------------------------------------


class TestHistoryCacheIO:
    """Tests for save/load history cache."""

    def test_save_and_load_roundtrip(self, tmp_path: Path):
        cache_file = tmp_path / "cache.json"
        cache: dict[str, Any] = {
            "event_count": 5,
            "telemetry_mtime": 1.0,
            "issue_rows": {
                10: {
                    "issue_number": 10,
                    "title": "Test",
                    "session_ids": {"s1", "s2"},
                    "prs": {100: {"number": 100, "url": "", "merged": False}},
                    "linked_issues": {5: {"target_id": 5, "kind": "blocks"}},
                }
            },
            "pr_to_issue": {100: 10},
            "enriched_issues": {10, 20},
        }

        save_history_cache(cache, cache_file)
        assert cache_file.exists()

        loaded: dict[str, Any] = {
            "event_count": -1,
            "telemetry_mtime": 0.0,
            "issue_rows": None,
            "pr_to_issue": None,
            "enriched_issues": set(),
        }
        loaded_ts: list[float] = [0.0]
        load_history_cache(loaded, loaded_ts, cache_file)

        assert loaded["event_count"] == 5
        assert 10 in loaded["issue_rows"]
        assert loaded["pr_to_issue"][100] == 10
        assert loaded["enriched_issues"] == {10, 20}
        # session_ids should be restored as a set
        assert isinstance(loaded["issue_rows"][10]["session_ids"], set)
        # PR keys should be ints
        assert 100 in loaded["issue_rows"][10]["prs"]

    def test_save_skips_when_no_rows(self, tmp_path: Path):
        cache_file = tmp_path / "cache.json"
        cache: dict[str, Any] = {"issue_rows": None}
        save_history_cache(cache, cache_file)
        assert not cache_file.exists()

    def test_load_ignores_corrupt_file(self, tmp_path: Path):
        cache_file = tmp_path / "cache.json"
        cache_file.write_text("not json{{{")
        cache: dict[str, Any] = {"issue_rows": None}
        ts: list[float] = [0.0]
        load_history_cache(cache, ts, cache_file)
        assert cache["issue_rows"] is None  # unchanged


# ------------------------------------------------------------------
# Sub-router composition
# ------------------------------------------------------------------


class TestSubRouterComposition:
    """Tests that sub-routers are properly composed into the main router."""

    def test_crate_routes_registered(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ):
        """Crate routes should be discoverable on the composed router."""
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
        paths = {getattr(r, "path", "") for r in router.routes}
        assert "/api/crates" in paths
        assert "/api/crates/active" in paths
        assert "/api/crates/advance" in paths
        assert "/api/crates/{crate_number}" in paths

    def test_hitl_routes_registered(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ):
        """HITL routes should be discoverable on the composed router."""
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
        paths = {getattr(r, "path", "") for r in router.routes}
        assert "/api/hitl" in paths
        assert "/api/hitl/{issue_number}/summary" in paths
        assert "/api/hitl/{issue_number}/correct" in paths
        assert "/api/hitl/{issue_number}/skip" in paths

    def test_history_routes_registered(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ):
        """History routes should be discoverable on the composed router."""
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
        paths = {getattr(r, "path", "") for r in router.routes}
        assert "/api/issues/history" in paths
        assert "/api/issues/outcomes" in paths

    def test_core_routes_still_registered(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ):
        """Core routes (health, state, pipeline, etc.) must remain."""
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
        paths = {getattr(r, "path", "") for r in router.routes}
        assert "/healthz" in paths
        assert "/api/state" in paths
        assert "/api/pipeline" in paths
        assert "/api/system/workers" in paths
        assert "/api/metrics" in paths


# ------------------------------------------------------------------
# Crate routes via sub-router
# ------------------------------------------------------------------


class TestCrateSubRouter:
    """Tests for crate routes served via the extracted sub-router."""

    @pytest.mark.asyncio
    async def test_get_crates_calls_pr_manager(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ):
        from dashboard_crate_routes import create_crate_router
        from pr_manager import PRManager

        pr_mgr = PRManager(config, event_bus)
        mock_milestone = MagicMock()
        mock_milestone.model_dump.return_value = {
            "number": 1,
            "title": "v1.0",
            "open_issues": 3,
            "closed_issues": 7,
        }
        mock_milestone.open_issues = 3
        mock_milestone.closed_issues = 7
        pr_mgr.list_milestones = AsyncMock(return_value=[mock_milestone])  # type: ignore[method-assign]

        deps = _make_deps(config, event_bus, state, pr_manager=pr_mgr)
        router = create_crate_router(deps)

        endpoint = next(
            r.endpoint for r in router.routes if getattr(r, "path", "") == "/api/crates"
        )
        response = await endpoint()
        data = json.loads(response.body)
        assert len(data) == 1
        assert data[0]["progress"] == 70

    @pytest.mark.asyncio
    async def test_create_crate_empty_title(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ):
        from dashboard_crate_routes import create_crate_router
        from models import CrateCreateRequest

        deps = _make_deps(config, event_bus, state)
        router = create_crate_router(deps)

        endpoint = next(
            r.endpoint
            for r in router.routes
            if getattr(r, "path", "") == "/api/crates"
            and "POST" in getattr(r, "methods", set())
        )
        body = CrateCreateRequest(title="  ", description="", due_on="")
        response = await endpoint(body)
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_advance_crate_no_orchestrator(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ):
        from dashboard_crate_routes import create_crate_router

        deps = _make_deps(config, event_bus, state)
        router = create_crate_router(deps)

        endpoint = next(
            r.endpoint
            for r in router.routes
            if getattr(r, "path", "") == "/api/crates/advance"
        )
        response = await endpoint()
        data = json.loads(response.body)
        assert data["status"] == "ok"
        assert data["previous"] is None
        assert data["next"] is None


# ------------------------------------------------------------------
# HITL routes via sub-router
# ------------------------------------------------------------------


class TestHITLSubRouter:
    """Tests for HITL routes served via the extracted sub-router."""

    @pytest.mark.asyncio
    async def test_hitl_correct_no_orchestrator(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ):
        from dashboard_hitl_routes import create_hitl_router

        deps = _make_deps(config, event_bus, state)
        router = create_hitl_router(deps)

        endpoint = next(
            r.endpoint
            for r in router.routes
            if getattr(r, "path", "") == "/api/hitl/{issue_number}/correct"
        )
        response = await endpoint(42, {"correction": "fix the bug"})
        assert response.status_code == 400  # no orchestrator

    @pytest.mark.asyncio
    async def test_hitl_correct_empty_correction(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ):
        from dashboard_hitl_routes import create_hitl_router

        mock_orch = MagicMock()
        deps = _make_deps(config, event_bus, state, get_orchestrator=lambda: mock_orch)
        router = create_hitl_router(deps)

        endpoint = next(
            r.endpoint
            for r in router.routes
            if getattr(r, "path", "") == "/api/hitl/{issue_number}/correct"
        )
        response = await endpoint(42, {"correction": "  "})
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_hitl_skip_no_orchestrator(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ):
        from dashboard_hitl_routes import create_hitl_router
        from models import HITLSkipRequest

        deps = _make_deps(config, event_bus, state)
        router = create_hitl_router(deps)

        endpoint = next(
            r.endpoint
            for r in router.routes
            if getattr(r, "path", "") == "/api/hitl/{issue_number}/skip"
        )
        response = await endpoint(42, HITLSkipRequest(reason="not needed"))
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_hitl_close_no_orchestrator(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ):
        from dashboard_hitl_routes import create_hitl_router
        from models import HITLCloseRequest

        deps = _make_deps(config, event_bus, state)
        router = create_hitl_router(deps)

        endpoint = next(
            r.endpoint
            for r in router.routes
            if getattr(r, "path", "") == "/api/hitl/{issue_number}/close"
        )
        response = await endpoint(42, HITLCloseRequest(reason="obsolete"))
        assert response.status_code == 400


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_deps(
    config,
    event_bus: EventBus,
    state,
    *,
    pr_manager=None,
    registry=None,
    get_orchestrator=None,
) -> RouterDeps:
    """Build a RouterDeps for testing with sensible defaults."""
    from pr_manager import PRManager

    if pr_manager is None:
        pr_manager = PRManager(config, event_bus)
    return RouterDeps(
        config=config,
        event_bus=event_bus,
        state=state,
        pr_manager=pr_manager,
        get_orchestrator=get_orchestrator or (lambda: None),
        set_orchestrator=lambda o: None,
        set_run_task=lambda t: None,
        ui_dist_dir=Path("/tmp/no-dist"),
        template_dir=Path("/tmp/no-templates"),
        registry=registry,
    )
