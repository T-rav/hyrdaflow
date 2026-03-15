"""Tests for dashboard_routes._context.RouterContext."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from config import HydraFlowConfig
from events import EventBus
from pr_manager import PRManager
from state import StateTracker


@pytest.fixture
def config(tmp_path: Path) -> HydraFlowConfig:
    return HydraFlowConfig(
        repo="owner/test-repo",
        gh_token="fake-token",
        data_dir=str(tmp_path / "data"),
    )


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def state(tmp_path: Path) -> StateTracker:
    return StateTracker(tmp_path / "state.json")


@pytest.fixture
def pr_manager(config: HydraFlowConfig, event_bus: EventBus) -> PRManager:
    return PRManager(config, event_bus)


@pytest.fixture
def ctx(
    config: HydraFlowConfig,
    event_bus: EventBus,
    state: StateTracker,
    pr_manager: PRManager,
    tmp_path: Path,
) -> Any:
    from dashboard_routes._context import RouterContext

    return RouterContext(
        config=config,
        event_bus=event_bus,
        state=state,
        pr_manager=pr_manager,
        get_orchestrator=lambda: None,
        set_orchestrator=lambda o: None,
        set_run_task=lambda t: None,
        ui_dist_dir=tmp_path / "ui-dist",
        template_dir=tmp_path / "templates",
    )


class TestRouterContextInit:
    """Test RouterContext initialization."""

    def test_stores_core_dependencies(self, ctx: Any, config: HydraFlowConfig) -> None:
        assert ctx.config is config
        assert ctx.hitl_summary_inflight == set()
        assert isinstance(ctx.history_cache, dict)

    def test_issue_fetcher_created(self, ctx: Any) -> None:
        from issue_fetcher import IssueFetcher

        assert isinstance(ctx.issue_fetcher, IssueFetcher)

    def test_hitl_summarizer_created(self, ctx: Any) -> None:
        from transcript_summarizer import TranscriptSummarizer

        assert isinstance(ctx.hitl_summarizer, TranscriptSummarizer)


class TestResolveRuntime:
    """Test resolve_runtime method."""

    def test_returns_defaults_when_no_registry(self, ctx: Any) -> None:
        cfg, st, bus, get_orch = ctx.resolve_runtime(None)
        assert cfg is ctx.config
        assert st is ctx.state
        assert bus is ctx.event_bus

    def test_returns_defaults_when_slug_none(self, ctx: Any) -> None:
        ctx.registry = MagicMock()
        cfg, st, bus, get_orch = ctx.resolve_runtime(None)
        assert cfg is ctx.config

    def test_raises_404_for_unknown_slug(self, ctx: Any) -> None:
        from fastapi import HTTPException

        registry = MagicMock()
        registry.get.return_value = None
        ctx.registry = registry

        with pytest.raises(HTTPException) as exc_info:
            ctx.resolve_runtime("unknown/repo")
        assert exc_info.value.status_code == 404

    def test_returns_runtime_for_known_slug(self, ctx: Any) -> None:
        runtime = SimpleNamespace(
            config=MagicMock(),
            state=MagicMock(),
            event_bus=MagicMock(),
            orchestrator=None,
        )
        registry = MagicMock()
        registry.get.return_value = runtime
        ctx.registry = registry

        cfg, st, bus, get_orch = ctx.resolve_runtime("org/repo")
        assert cfg is runtime.config
        assert st is runtime.state
        assert bus is runtime.event_bus


class TestPrManagerFor:
    """Test pr_manager_for method."""

    def test_returns_shared_when_same_config(self, ctx: Any) -> None:
        result = ctx.pr_manager_for(ctx.config, ctx.event_bus)
        assert result is ctx.pr_manager

    def test_creates_new_for_different_config(self, ctx: Any) -> None:
        other_config = MagicMock()
        result = ctx.pr_manager_for(other_config, ctx.event_bus)
        assert result is not ctx.pr_manager


class TestServeSpaIndex:
    """Test serve_spa_index method."""

    def test_serves_react_index(self, ctx: Any) -> None:
        ctx.ui_dist_dir.mkdir(parents=True)
        (ctx.ui_dist_dir / "index.html").write_text("<html>React</html>")
        resp = ctx.serve_spa_index()
        assert "React" in resp.body.decode()

    def test_falls_back_to_template(self, ctx: Any) -> None:
        ctx.template_dir.mkdir(parents=True)
        (ctx.template_dir / "index.html").write_text("<html>Template</html>")
        resp = ctx.serve_spa_index()
        assert "Template" in resp.body.decode()

    def test_falls_back_to_placeholder(self, ctx: Any) -> None:
        resp = ctx.serve_spa_index()
        assert "HydraFlow Dashboard" in resp.body.decode()


class TestBuildHitlContext:
    """Test build_hitl_context method."""

    def test_builds_context_string(self, ctx: Any) -> None:
        issue = SimpleNamespace(
            number=42,
            title="Test issue",
            body="Issue body text",
            comments=["comment1", "comment2"],
        )
        result = ctx.build_hitl_context(
            issue, cause="Manual escalation", origin="review"
        )
        assert "Issue #42" in result
        assert "Test issue" in result
        assert "Manual escalation" in result
        assert "Issue body text" in result

    def test_handles_none_body(self, ctx: Any) -> None:
        issue = SimpleNamespace(number=1, title="T", body=None, comments=[])
        result = ctx.build_hitl_context(issue, cause="test", origin=None)
        assert "Issue #1" in result


class TestNormaliseSummaryLines:
    """Test normalise_summary_lines static method."""

    def test_strips_bullet_prefixes(self, ctx: Any) -> None:
        raw = "- Line one\n- Line two\n- Line three"
        result = ctx.normalise_summary_lines(raw)
        assert result == "Line one\nLine two\nLine three"

    def test_caps_at_8_lines(self, ctx: Any) -> None:
        raw = "\n".join(f"Line {i}" for i in range(20))
        result = ctx.normalise_summary_lines(raw)
        assert len(result.splitlines()) == 8

    def test_strips_whitespace(self, ctx: Any) -> None:
        result = ctx.normalise_summary_lines("  hello  \n  world  ")
        assert result == "hello\nworld"


class TestHitlSummaryRetryDue:
    """Test hitl_summary_retry_due method."""

    def test_returns_true_when_no_failure(self, ctx: Any) -> None:
        assert ctx.hitl_summary_retry_due(999) is True

    def test_returns_false_when_recently_failed(self, ctx: Any) -> None:

        ctx.state.set_hitl_summary_failure(42, "test error")
        assert ctx.hitl_summary_retry_due(42) is False


class TestNewIssueHistoryEntry:
    """Test new_issue_history_entry method."""

    def test_creates_entry_with_issue_url(self, ctx: Any) -> None:
        entry = ctx.new_issue_history_entry(123)
        assert entry["issue_number"] == 123
        assert "owner/test-repo" in entry["issue_url"]
        assert "/issues/123" in entry["issue_url"]
        assert entry["status"] == "unknown"
        assert isinstance(entry["session_ids"], set)

    def test_entry_contains_inference_keys(self, ctx: Any) -> None:
        entry = ctx.new_issue_history_entry(1)
        assert "inference" in entry
        assert isinstance(entry["inference"], dict)


class TestHistoryCache:
    """Test save/load history cache methods."""

    def test_save_and_load_roundtrip(self, ctx: Any, tmp_path: Path) -> None:
        ctx.history_cache_file = tmp_path / "cache" / "history_cache.json"
        ctx.history_cache_file.parent.mkdir(parents=True, exist_ok=True)
        ctx.history_cache["issue_rows"] = {
            42: {
                "issue_number": 42,
                "session_ids": {"s1", "s2"},
                "prs": {},
                "linked_issues": {},
            }
        }
        ctx.history_cache["pr_to_issue"] = {100: 42}
        ctx.history_cache["event_count"] = 5
        ctx.history_cache["enriched_issues"] = {42}

        ctx.save_history_cache()
        assert ctx.history_cache_file.exists()

        # Reset and reload
        ctx.history_cache["issue_rows"] = None
        ctx.load_history_cache()
        assert ctx.history_cache["issue_rows"] is not None
        assert 42 in ctx.history_cache["issue_rows"]
        assert ctx.history_cache["event_count"] == 5

    def test_load_ignores_missing_file(self, ctx: Any, tmp_path: Path) -> None:
        ctx.history_cache_file = tmp_path / "no-cache" / "history_cache.json"
        ctx.history_cache["issue_rows"] = None
        ctx.load_history_cache()
        assert ctx.history_cache["issue_rows"] is None

    def test_load_ignores_corrupt_json(self, ctx: Any, tmp_path: Path) -> None:
        ctx.history_cache_file = tmp_path / "bad-cache" / "history_cache.json"
        ctx.history_cache["issue_rows"] = None
        ctx.history_cache_file.parent.mkdir(parents=True, exist_ok=True)
        ctx.history_cache_file.write_text("not json")
        ctx.load_history_cache()
        assert ctx.history_cache["issue_rows"] is None


class TestListRepoRecords:
    """Test list_repo_records method."""

    def test_returns_empty_when_no_callback_or_store(self, ctx: Any) -> None:
        assert ctx.list_repo_records() == []

    def test_uses_callback_when_available(self, ctx: Any) -> None:
        record = MagicMock()
        ctx.list_repos_cb = lambda: [record]
        assert ctx.list_repo_records() == [record]

    def test_falls_back_to_store(self, ctx: Any) -> None:
        record = MagicMock()
        store = MagicMock()
        store.list.return_value = [record]
        ctx.repo_store = store
        assert ctx.list_repo_records() == [record]

    def test_handles_callback_error(self, ctx: Any) -> None:
        def broken() -> list:
            raise RuntimeError("broken")

        ctx.list_repos_cb = broken
        assert ctx.list_repo_records() == []
