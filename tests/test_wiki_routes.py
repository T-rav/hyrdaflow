"""Tests for /api/wiki/* routes (Phase 5 of the git-backed repo wiki).

Covers:

- Read endpoints traverse the tracked ``repo_wiki/`` layout and return
  the expected fields / 404s.
- Admin endpoints enqueue ``MaintenanceTask`` entries into the orchestrator's
  ``RepoWikiLoop._queue`` when present, 503 otherwise.
- ``/api/wiki/maintenance/status`` reports queue depth + open-PR state.

Tests use the ``make_dashboard_router`` helper + ``find_endpoint`` to
reach handlers directly — no FastAPI TestClient required.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from config import HydraFlowConfig
from events import EventBus
from state import StateTracker
from tests.helpers import find_endpoint, make_dashboard_router
from wiki_maint_queue import MaintenanceQueue, MaintenanceTask

REPO = "acme/widget"


@pytest.fixture
def wiki_root(tmp_path: Path) -> Path:
    """A tracked ``repo_wiki/`` tree with two entries + index.md + log."""
    root = tmp_path / "repo_wiki"
    repo_dir = root / "acme" / "widget"
    (repo_dir / "patterns").mkdir(parents=True)
    (repo_dir / "gotchas").mkdir()
    (repo_dir / "log").mkdir()

    (repo_dir / "index.md").write_text("# Wiki: acme/widget\n")

    (repo_dir / "patterns" / "0001-issue-10-first-pattern.md").write_text(
        "---\n"
        "id: 0001\n"
        "topic: patterns\n"
        "source_issue: 10\n"
        "source_phase: plan\n"
        "created_at: 2026-04-01T00:00:00Z\n"
        "status: active\n"
        "---\n"
        "\n"
        "# First pattern\n"
        "\n"
        "Pattern body content.\n"
    )
    (repo_dir / "gotchas" / "0001-issue-11-watch-out.md").write_text(
        "---\n"
        "id: 0001\n"
        "topic: gotchas\n"
        "source_issue: 11\n"
        "source_phase: review\n"
        "created_at: 2026-04-02T00:00:00Z\n"
        "status: stale\n"
        "---\n"
        "\n"
        "# Watch out\n"
        "\n"
        "Gotcha body.\n"
    )
    (repo_dir / "log" / "10.jsonl").write_text(
        json.dumps({"issue_number": 10, "phase": "plan", "action": "ingest"}) + "\n"
    )
    (repo_dir / "log" / "11.jsonl").write_text(
        json.dumps({"issue_number": 11, "phase": "review", "action": "ingest"}) + "\n"
    )
    return root


@pytest.fixture
def config(tmp_path: Path, wiki_root: Path) -> HydraFlowConfig:
    return HydraFlowConfig(
        repo=REPO,
        repo_root=wiki_root.parent,  # wiki_root is <repo_root>/repo_wiki
        repo_wiki_git_backed=True,
        repo_wiki_path="repo_wiki",
    )


@pytest.fixture
def maintenance_queue(tmp_path: Path) -> MaintenanceQueue:
    return MaintenanceQueue(path=tmp_path / "queue.json")


@pytest.fixture
def fake_orchestrator(maintenance_queue: MaintenanceQueue) -> MagicMock:
    """A mock orchestrator whose ``_svc.repo_wiki_loop._queue`` is the fixture."""
    loop = MagicMock()
    loop._queue = maintenance_queue
    loop._open_pr_url = "https://github.com/x/y/pull/99"
    loop._open_pr_branch = "hydraflow/wiki-maint-abc"

    svc = MagicMock()
    svc.repo_wiki_loop = loop

    orch = MagicMock()
    orch._svc = svc
    return orch


@pytest.fixture
def router(
    config: HydraFlowConfig,
    tmp_path: Path,
    fake_orchestrator: MagicMock,
) -> Any:
    bus = EventBus()
    state = StateTracker(tmp_path / "state.json")
    r, _pr = make_dashboard_router(
        config=config,
        event_bus=bus,
        state=state,
        tmp_path=tmp_path,
        get_orch=lambda: fake_orchestrator,
    )
    return r


class TestReadEndpoints:
    def test_list_repos(self, router: Any) -> None:
        handler = find_endpoint(router, "/api/wiki/repos", "GET")
        assert handler is not None
        result = handler()
        assert result == [{"owner": "acme", "repo": "widget"}]

    def test_list_entries_returns_all_by_default(self, router: Any) -> None:
        handler = find_endpoint(router, "/api/wiki/repos/{owner}/{repo}/entries", "GET")
        assert handler is not None
        entries = handler(owner="acme", repo="widget")
        assert len(entries) == 2
        topics = {e["topic"] for e in entries}
        assert topics == {"patterns", "gotchas"}

    def test_list_entries_filters_by_topic(self, router: Any) -> None:
        handler = find_endpoint(router, "/api/wiki/repos/{owner}/{repo}/entries", "GET")
        entries = handler(owner="acme", repo="widget", topic="patterns")
        assert len(entries) == 1
        assert entries[0]["topic"] == "patterns"

    def test_list_entries_filters_by_status(self, router: Any) -> None:
        handler = find_endpoint(router, "/api/wiki/repos/{owner}/{repo}/entries", "GET")
        stale = handler(owner="acme", repo="widget", status="stale")
        assert len(stale) == 1
        assert stale[0]["topic"] == "gotchas"

    def test_list_entries_rejects_path_traversal_in_owner(self, router: Any) -> None:
        handler = find_endpoint(router, "/api/wiki/repos/{owner}/{repo}/entries", "GET")
        assert handler(owner="../evil", repo="widget") == []

    def test_get_entry_returns_frontmatter_plus_body(self, router: Any) -> None:
        handler = find_endpoint(
            router, "/api/wiki/repos/{owner}/{repo}/entries/{entry_id}", "GET"
        )
        result = handler(owner="acme", repo="widget", entry_id="0001")
        assert result["frontmatter"]["source_phase"] in {"plan", "review"}
        assert "# " in result["body"] or result["body"].strip()

    def test_get_entry_404_for_unknown_id(self, router: Any) -> None:
        from fastapi import HTTPException

        handler = find_endpoint(
            router, "/api/wiki/repos/{owner}/{repo}/entries/{entry_id}", "GET"
        )
        with pytest.raises(HTTPException) as exc:
            handler(owner="acme", repo="widget", entry_id="9999")
        assert exc.value.status_code == 404

    def test_get_entry_400_for_non_numeric_id(self, router: Any) -> None:
        from fastapi import HTTPException

        handler = find_endpoint(
            router, "/api/wiki/repos/{owner}/{repo}/entries/{entry_id}", "GET"
        )
        with pytest.raises(HTTPException) as exc:
            handler(owner="acme", repo="widget", entry_id="../passwd")
        assert exc.value.status_code == 400

    def test_get_log_filters_by_issue(self, router: Any) -> None:
        handler = find_endpoint(router, "/api/wiki/repos/{owner}/{repo}/log", "GET")
        records = handler(owner="acme", repo="widget", issue=10)
        assert len(records) == 1
        assert records[0]["issue_number"] == 10

    def test_get_log_empty_for_unknown_repo(self, router: Any) -> None:
        handler = find_endpoint(router, "/api/wiki/repos/{owner}/{repo}/log", "GET")
        assert handler(owner="ghost", repo="ghost") == []


class TestMaintenanceStatus:
    def test_reports_open_pr_and_queue_depth(
        self, router: Any, maintenance_queue: MaintenanceQueue
    ) -> None:
        maintenance_queue.enqueue(
            MaintenanceTask(kind="rebuild-index", repo_slug=REPO, params={})
        )
        handler = find_endpoint(router, "/api/wiki/maintenance/status", "GET")
        status = handler()
        assert status["open_pr_url"] == "https://github.com/x/y/pull/99"
        assert status["open_pr_branch"] == "hydraflow/wiki-maint-abc"
        assert status["queue_depth"] == 1


class TestAdminEndpoints:
    def test_force_compile_enqueues(
        self, router: Any, maintenance_queue: MaintenanceQueue
    ) -> None:
        handler = find_endpoint(router, "/api/wiki/admin/force-compile", "POST")
        from dashboard_routes._wiki_routes import ForceCompilePayload

        response = handler(
            ForceCompilePayload(owner="acme", repo="widget", topic="patterns")
        )
        assert response == {"status": "queued"}
        queued = maintenance_queue.peek()
        assert len(queued) == 1
        assert queued[0].kind == "force-compile"
        assert queued[0].params == {"topic": "patterns"}

    def test_mark_stale_enqueues(
        self, router: Any, maintenance_queue: MaintenanceQueue
    ) -> None:
        handler = find_endpoint(router, "/api/wiki/admin/mark-stale", "POST")
        from dashboard_routes._wiki_routes import MarkStalePayload

        handler(
            MarkStalePayload(
                owner="acme",
                repo="widget",
                entry_id="0042",
                reason="superseded",
            )
        )
        queued = maintenance_queue.peek()
        assert queued[0].kind == "mark-stale"
        assert queued[0].params["entry_id"] == "0042"

    def test_rebuild_index_enqueues(
        self, router: Any, maintenance_queue: MaintenanceQueue
    ) -> None:
        handler = find_endpoint(router, "/api/wiki/admin/rebuild-index", "POST")
        from dashboard_routes._wiki_routes import RebuildIndexPayload

        handler(RebuildIndexPayload(owner="acme", repo="widget"))
        queued = maintenance_queue.peek()
        assert queued[0].kind == "rebuild-index"

    def test_admin_503_when_queue_unavailable(
        self,
        config: HydraFlowConfig,
        tmp_path: Path,
    ) -> None:
        """When the orchestrator is not up yet, admin endpoints return 503."""
        from fastapi import HTTPException

        bus = EventBus()
        state = StateTracker(tmp_path / "state.json")
        r, _ = make_dashboard_router(
            config=config,
            event_bus=bus,
            state=state,
            tmp_path=tmp_path,
            get_orch=lambda: None,
        )
        handler = find_endpoint(r, "/api/wiki/admin/force-compile", "POST")
        from dashboard_routes._wiki_routes import ForceCompilePayload

        with pytest.raises(HTTPException) as exc:
            handler(ForceCompilePayload(owner="acme", repo="widget", topic="patterns"))
        assert exc.value.status_code == 503

    def test_run_now_calls_trigger_hook_when_available(
        self,
        config: HydraFlowConfig,
        tmp_path: Path,
        maintenance_queue: MaintenanceQueue,
    ) -> None:
        loop = MagicMock()
        loop._queue = maintenance_queue
        loop.trigger_now = MagicMock()

        svc = MagicMock()
        svc.repo_wiki_loop = loop

        orch = MagicMock()
        orch._svc = svc

        bus = EventBus()
        state = StateTracker(tmp_path / "state.json")
        r, _ = make_dashboard_router(
            config=config,
            event_bus=bus,
            state=state,
            tmp_path=tmp_path,
            get_orch=lambda: orch,
        )
        handler = find_endpoint(r, "/api/wiki/admin/run-now", "POST")
        response = handler()

        loop.trigger_now.assert_called_once()
        assert response["status"] == "triggered"

    def test_run_now_acknowledges_when_no_trigger(
        self,
        config: HydraFlowConfig,
        tmp_path: Path,
        fake_orchestrator: MagicMock,
    ) -> None:
        """When the loop exposes no ``trigger_now`` / ``force_tick`` hook,
        the endpoint returns an acknowledgement rather than 503."""
        # The default fake_orchestrator's loop has no trigger_* attrs.
        del fake_orchestrator._svc.repo_wiki_loop.trigger_now
        del fake_orchestrator._svc.repo_wiki_loop.force_tick

        bus = EventBus()
        state = StateTracker(tmp_path / "state.json")
        r, _ = make_dashboard_router(
            config=config,
            event_bus=bus,
            state=state,
            tmp_path=tmp_path,
            get_orch=lambda: fake_orchestrator,
        )
        handler = find_endpoint(r, "/api/wiki/admin/run-now", "POST")
        assert handler()["status"] == "acknowledged"


def test_get_wiki_metrics_returns_snapshot_including_counters():
    """The metrics endpoint returns a JSON snapshot of all counters."""
    from unittest.mock import MagicMock

    from fastapi import APIRouter
    from fastapi.testclient import TestClient

    from dashboard_routes._wiki_routes import register
    from knowledge_metrics import metrics

    metrics.reset()
    metrics.increment("wiki_supersedes", 3)
    metrics.increment("tribal_promotions", 1)

    router = APIRouter()
    ctx = MagicMock()
    ctx.get_orchestrator = lambda: None  # no running loop — not needed for /metrics
    register(router, ctx)

    # Build a test app
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)

    client = TestClient(app)
    resp = client.get("/api/wiki/metrics")
    assert resp.status_code == 200
    body = resp.json()
    assert body["wiki_supersedes"] == 3
    assert body["tribal_promotions"] == 1
    assert body["adr_drafts_opened"] == 0

    metrics.reset()


def test_get_wiki_health_reports_unconfigured_when_no_loop():
    """When the orchestrator isn't running, health reports 'unconfigured'."""
    from unittest.mock import MagicMock

    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient

    from dashboard_routes._wiki_routes import register

    router = APIRouter()
    ctx = MagicMock()
    ctx.get_orchestrator = lambda: None
    register(router, ctx)

    app = FastAPI()
    app.include_router(router)
    resp = TestClient(app).get("/api/wiki/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["store"] == "unconfigured"
    assert body["tribal"] == "unconfigured"


def test_get_wiki_health_reports_populated_when_loop_has_stores(tmp_path):
    """When the loop exposes wiki + tribal stores, health reports their status."""
    from unittest.mock import MagicMock

    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient

    from dashboard_routes._wiki_routes import register
    from repo_wiki import RepoWikiStore, WikiEntry
    from tribal_wiki import TribalWikiStore

    store = RepoWikiStore(tmp_path / "per")
    store.ingest(
        "acme/widget",
        [
            WikiEntry(
                title="x",
                content="y",
                source_type="plan",
                topic="patterns",
            )
        ],
    )
    tribal = TribalWikiStore(tmp_path / "tribal")
    tribal.ingest(
        [
            WikiEntry(
                title="z",
                content="w",
                source_type="librarian",
                topic="patterns",
            )
        ]
    )

    loop = MagicMock()
    loop._wiki_store = store
    loop._tribal_store = tribal

    orch = MagicMock()
    orch._svc = MagicMock()
    orch._svc.repo_wiki_loop = loop

    router = APIRouter()
    ctx = MagicMock()
    ctx.get_orchestrator = lambda: orch
    register(router, ctx)

    app = FastAPI()
    app.include_router(router)
    resp = TestClient(app).get("/api/wiki/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["store"] == "populated"
    assert body["repos"] == 1
    assert body["tribal"] == "populated"
