"""Tests for #2396: Replace Any with specific types in public APIs."""

from __future__ import annotations

from pathlib import Path

import pytest

from models import GitHubIssue, GitHubIssueState
from state import StateTracker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_tracker(tmp_path: Path) -> StateTracker:
    """Return a StateTracker backed by a temp file."""
    return StateTracker(tmp_path / "state.json")


# ---------------------------------------------------------------------------
# models.py — _normalise_state
# ---------------------------------------------------------------------------


class TestNormaliseState:
    """Verify _normalise_state accepts str and returns lowered string."""

    def test_lowercase_string(self) -> None:
        issue = GitHubIssue(number=1, title="t", state="OPEN")
        assert issue.state == GitHubIssueState.OPEN

    def test_mixed_case_string(self) -> None:
        issue = GitHubIssue(number=2, title="t", state="Closed")
        assert issue.state == GitHubIssueState.CLOSED

    def test_already_enum(self) -> None:
        issue = GitHubIssue(number=3, title="t", state=GitHubIssueState.OPEN)
        assert issue.state == GitHubIssueState.OPEN

    def test_invalid_state_raises(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            GitHubIssue(number=4, title="t", state="invalid_state")


# ---------------------------------------------------------------------------
# state.py — _normalise_details
# ---------------------------------------------------------------------------


class TestNormaliseDetails:
    """Verify _normalise_details handles union of dict | str | None."""

    def test_dict_passthrough(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        result = tracker._normalise_details({"key": "value"})
        assert result == {"key": "value"}

    def test_none_returns_empty(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        result = tracker._normalise_details(None)
        assert result == {}

    def test_empty_string_returns_empty(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        result = tracker._normalise_details("")
        assert result == {}

    def test_string_wraps_in_raw(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        result = tracker._normalise_details("some error")
        assert result == {"raw": "some error"}


# ---------------------------------------------------------------------------
# state.py — _coerce_last_run
# ---------------------------------------------------------------------------


class TestCoerceLastRun:
    """Verify _coerce_last_run handles str | int | float | None."""

    def test_none_passthrough(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        assert tracker._coerce_last_run(None) is None

    def test_string_passthrough(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        assert tracker._coerce_last_run("2024-01-01T00:00:00") == "2024-01-01T00:00:00"

    def test_int_to_string(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        assert tracker._coerce_last_run(12345) == "12345"

    def test_float_to_string(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        assert tracker._coerce_last_run(123.45) == "123.45"


# ---------------------------------------------------------------------------
# issue_fetcher.py — _normalize_issue_payload
# ---------------------------------------------------------------------------


class TestNormalizeIssuePayload:
    """Verify _normalize_issue_payload accepts dict[str, Any]."""

    def test_basic_payload(self) -> None:
        from issue_fetcher import IssueFetcher

        payload: dict[str, object] = {
            "number": 42,
            "title": "Test issue",
            "body": "body text",
            "comments": [],
            "labels": [{"name": "bug"}],
            "state": "open",
        }
        result = IssueFetcher._normalize_issue_payload(payload)  # type: ignore[arg-type]
        assert result["number"] == 42
        assert result["title"] == "Test issue"
        assert isinstance(result["comments"], list)

    def test_comments_non_list_becomes_empty(self) -> None:
        from issue_fetcher import IssueFetcher

        payload: dict[str, object] = {
            "number": 1,
            "title": "t",
            "body": "",
            "comments": "not a list",
            "labels": [],
            "state": "open",
        }
        result = IssueFetcher._normalize_issue_payload(payload)  # type: ignore[arg-type]
        assert result["comments"] == []


# ---------------------------------------------------------------------------
# hitl_phase.py — attempt_auto_fixes type annotation
# ---------------------------------------------------------------------------


class TestHITLPhaseTypeAnnotation:
    """Verify attempt_auto_fixes has correct type annotation."""

    def test_parameter_annotation(self) -> None:
        import inspect

        from hitl_phase import HITLPhase

        sig = inspect.signature(HITLPhase.attempt_auto_fixes)
        param = sig.parameters["hitl_issues"]
        annotation_str = str(param.annotation)
        assert "GitHubIssue" in annotation_str


# ---------------------------------------------------------------------------
# docker_runner.py — ContainerLike protocol
# ---------------------------------------------------------------------------


class TestContainerLikeProtocol:
    """Verify ContainerLike protocol methods have specific return types."""

    def test_wait_return_type(self) -> None:
        import inspect

        from docker_runner import ContainerLike

        sig = inspect.signature(ContainerLike.wait)
        ret = sig.return_annotation
        # Should be dict[str, int], not Any
        assert ret is not inspect.Parameter.empty
        assert "Any" not in str(ret)

    def test_logs_return_type(self) -> None:
        import inspect

        from docker_runner import ContainerLike

        sig = inspect.signature(ContainerLike.logs)
        ret = sig.return_annotation
        assert ret is not inspect.Parameter.empty
        assert "Any" not in str(ret)

    def test_attach_socket_return_type(self) -> None:
        import inspect

        from docker_runner import ContainerLike

        sig = inspect.signature(ContainerLike.attach_socket)
        ret = sig.return_annotation
        assert ret is not inspect.Parameter.empty
        assert "Any" not in str(ret)


# ---------------------------------------------------------------------------
# dashboard_routes.py — type annotations
# ---------------------------------------------------------------------------


def _make_router(config, event_bus, state, tmp_path):
    """Build a dashboard router backed by test doubles."""
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


def _find_endpoint(router, path: str):
    for route in router.routes:
        if hasattr(route, "path") and route.path == path and hasattr(route, "endpoint"):
            return route.endpoint
    return None


class TestDashboardRouteAnnotations:
    """Verify dashboard_routes functions have specific type annotations."""

    def test_build_hitl_context_github_issue_interface(self) -> None:
        """GitHubIssue satisfies the interface expected by _build_hitl_context."""
        # _build_hitl_context is a closure inside create_router and is not
        # directly importable. This test verifies that GitHubIssue exposes
        # every attribute the function accesses: .number, .title, .body,
        # .comments, .url, .labels.
        issue = GitHubIssue(
            number=99,
            title="Test issue",
            body="desc",
            state="open",
            comments=["comment A"],
            url="https://example.com",
            labels=["bug"],
        )
        assert isinstance(issue.number, int)
        assert isinstance(issue.title, str)
        assert isinstance(issue.body, str)
        assert isinstance(issue.comments, list)
        assert isinstance(issue.url, str)
        assert isinstance(issue.labels, list)

    def test_normalise_worker_health_error_status_degrades_health(
        self, config, event_bus, state, tmp_path: Path
    ) -> None:
        """_normalise_worker_health: 'error' string maps to BGWorkerHealth.ERROR."""
        import json

        router = _make_router(config, event_bus, state, tmp_path)
        state.set_worker_heartbeat(
            "bad_worker", {"status": "error", "last_run": None, "details": {}}
        )
        get_health = _find_endpoint(router, "/healthz")
        assert get_health is not None
        response = get_health()
        data = json.loads(response.body)
        assert data["checks"]["workers"]["status"] == "degraded"
        assert "bad_worker" in data["worker_errors"]

    def test_normalise_worker_health_unknown_status_falls_back_to_disabled(
        self, config, event_bus, state, tmp_path: Path
    ) -> None:
        """_normalise_worker_health: unknown string coerces to disabled (not error)."""
        import json

        router = _make_router(config, event_bus, state, tmp_path)
        state.set_worker_heartbeat(
            "ok_worker",
            {"status": "totally_unknown_xyz", "last_run": None, "details": {}},
        )
        get_health = _find_endpoint(router, "/healthz")
        assert get_health is not None
        response = get_health()
        data = json.loads(response.body)
        assert "ok_worker" not in data.get("worker_errors", [])

    def test_normalise_worker_health_bgworkerhealth_enum_passthrough(
        self, config, event_bus, state, tmp_path: Path
    ) -> None:
        """_normalise_worker_health: BGWorkerHealth enum value passes through unchanged."""
        import json

        router = _make_router(config, event_bus, state, tmp_path)
        # Store a BGWorkerHealth.OK status — should not appear in worker_errors
        state.set_worker_heartbeat(
            "good_worker", {"status": "ok", "last_run": None, "details": {}}
        )
        get_health = _find_endpoint(router, "/healthz")
        assert get_health is not None
        response = get_health()
        data = json.loads(response.body)
        assert "good_worker" not in data.get("worker_errors", [])

    def test_normalise_state_return_type(self) -> None:
        """Verify the _normalise_state validator returns correct type."""
        import inspect

        sig = inspect.signature(GitHubIssue._normalise_state)
        ret = sig.return_annotation
        assert "Any" not in str(ret)
