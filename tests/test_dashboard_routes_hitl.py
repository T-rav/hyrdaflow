"""Tests for dashboard_routes.py — HITL endpoints."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from events import EventBus, EventType
from models import HITLItem
from tests.conftest import make_orchestrator_mock, make_state
from tests.helpers import find_endpoint, make_dashboard_router


class TestHITLEndpointCause:
    """Tests that /api/hitl includes the cause from state."""

    @pytest.mark.asyncio
    async def test_hitl_endpoint_includes_cause_from_state(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """When a HITL cause is set in state, it should appear in the response."""
        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)

        # Set a cause in state for issue 42
        state.set_hitl_cause(42, "CI failed after 2 fix attempt(s)")

        # Mock list_hitl_items to return a single item
        hitl_item = HITLItem(issue=42, title="Fix bug", pr=101)
        pr_mgr.list_hitl_items = AsyncMock(return_value=[hitl_item])  # type: ignore[method-assign]

        # Find and call the get_hitl handler
        get_hitl = find_endpoint(router, "/api/hitl")
        assert get_hitl is not None
        response = await get_hitl()
        data = response.body  # JSONResponse stores body as bytes

        items = json.loads(data)
        assert len(items) == 1
        assert items[0]["cause"] == "CI failed after 2 fix attempt(s)"
        called_labels = pr_mgr.list_hitl_items.await_args.args[0]  # type: ignore[union-attr]
        assert set(called_labels) == {
            *config.hitl_label,
            *config.hitl_active_label,
        }

    @pytest.mark.asyncio
    async def test_hitl_endpoint_includes_cached_llm_summary(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Cached HITL summary should be included in /api/hitl payload."""
        state.set_hitl_summary(42, "Line one\nLine two\nLine three")

        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)

        hitl_item = HITLItem(issue=42, title="Fix bug", pr=101)
        pr_mgr.list_hitl_items = AsyncMock(return_value=[hitl_item])  # type: ignore[method-assign]

        get_hitl = find_endpoint(router, "/api/hitl")
        get_hitl_summary = find_endpoint(router, "/api/hitl/{issue_number}/summary")

        assert get_hitl is not None
        assert get_hitl_summary is not None

        response = await get_hitl()

        items = json.loads(response.body)
        assert items[0]["llmSummary"].startswith("Line one")
        assert items[0]["llmSummaryUpdatedAt"] is not None

        summary_response = await get_hitl_summary(42)
        summary_payload = json.loads(summary_response.body)
        assert summary_payload["cached"] is True
        assert summary_payload["summary"].startswith("Line one")

    @pytest.mark.asyncio
    async def test_hitl_endpoint_skips_background_warm_during_failure_cooldown(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Recent summary failures should suppress warm task creation until cooldown."""
        config.transcript_summarization_enabled = True
        config.dry_run = False
        config.gh_token = "test-token"

        state.set_hitl_summary_failure(42, "model timeout")

        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)

        hitl_item = HITLItem(issue=42, title="Needs context", pr=0)
        pr_mgr.list_hitl_items = AsyncMock(return_value=[hitl_item])  # type: ignore[method-assign]

        get_hitl = find_endpoint(router, "/api/hitl")
        assert get_hitl is not None
        with patch("dashboard_routes._routes.asyncio.create_task") as mock_create_task:
            response = await get_hitl()

            payload = json.loads(response.body)
            assert payload[0]["llmSummary"] == ""
            mock_create_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_hitl_endpoint_includes_items_from_hitl_active_label(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """`/api/hitl` should return items tagged with either HITL label."""
        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)

        async def fake_run_gh(*args: str, **_kwargs: object) -> str:
            # list_hitl_items -> _fetch_hitl_raw_issues
            if args[0] == "gh" and args[1] == "api" and "issues" in args[2]:
                label_arg = next(
                    (
                        arg
                        for arg in args
                        if isinstance(arg, str) and arg.startswith("labels=")
                    ),
                    "",
                )
                if label_arg == f"labels={config.hitl_label[0]}":
                    return (
                        '[{"number": 42, "title": "Issue from hitl", '
                        '"url": "https://github.com/T-rav/hyrdaflow/issues/42"}]'
                    )
                if label_arg == f"labels={config.hitl_active_label[0]}":
                    return (
                        '[{"number": 77, "title": "Issue from hitl-active", '
                        '"url": "https://github.com/T-rav/hyrdaflow/issues/77"}]'
                    )
                return "[]"
            # list_hitl_items -> _build_hitl_item PR lookup
            if args[0] == "gh" and args[1] == "api" and "/pulls" in args[2]:
                return "[]"
            raise AssertionError(f"Unexpected gh invocation: {args}")

        pr_mgr._run_gh = fake_run_gh  # type: ignore[method-assign]

        get_hitl = find_endpoint(router, "/api/hitl")
        assert get_hitl is not None
        response = await get_hitl()

        items = json.loads(response.body)
        issue_numbers = {item["issue"] for item in items}
        assert {42, 77}.issubset(issue_numbers)

    @pytest.mark.asyncio
    async def test_hitl_endpoint_omits_cause_when_not_set(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """When no cause is set, the default empty string from model should be present."""
        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)

        # No cause set in state
        hitl_item = HITLItem(issue=42, title="Fix bug", pr=101)
        pr_mgr.list_hitl_items = AsyncMock(return_value=[hitl_item])  # type: ignore[method-assign]

        get_hitl = find_endpoint(router, "/api/hitl")
        assert get_hitl is not None
        response = await get_hitl()

        items = json.loads(response.body)
        assert len(items) == 1
        # No cause or origin — should remain empty
        assert items[0]["cause"] == ""

    @pytest.mark.asyncio
    async def test_hitl_endpoint_falls_back_to_origin_label(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """When no cause is set but origin is, should fall back to origin description."""
        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)

        # Set origin but not cause
        state.set_hitl_origin(42, "hydraflow-review")

        hitl_item = HITLItem(issue=42, title="Fix bug", pr=101)
        pr_mgr.list_hitl_items = AsyncMock(return_value=[hitl_item])  # type: ignore[method-assign]

        get_hitl = find_endpoint(router, "/api/hitl")
        assert get_hitl is not None
        response = await get_hitl()

        items = json.loads(response.body)
        assert len(items) == 1
        assert items[0]["cause"] == "Review escalation"

    @pytest.mark.asyncio
    async def test_hitl_endpoint_origin_fallback_unknown_label(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Unknown origin label should produce generic fallback message."""
        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)

        state.set_hitl_origin(42, "some-unknown-label")

        hitl_item = HITLItem(issue=42, title="Fix bug", pr=101)
        pr_mgr.list_hitl_items = AsyncMock(return_value=[hitl_item])  # type: ignore[method-assign]

        get_hitl = find_endpoint(router, "/api/hitl")
        assert get_hitl is not None
        response = await get_hitl()

        items = json.loads(response.body)
        assert len(items) == 1
        assert items[0]["cause"] == "Escalation (reason not recorded)"

    @pytest.mark.asyncio
    async def test_hitl_endpoint_cause_takes_precedence_over_origin(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """When both cause and origin are set, cause should take precedence."""
        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)

        state.set_hitl_cause(42, "CI failed after 2 fix attempt(s)")
        state.set_hitl_origin(42, "hydraflow-review")

        hitl_item = HITLItem(issue=42, title="Fix bug", pr=101)
        pr_mgr.list_hitl_items = AsyncMock(return_value=[hitl_item])  # type: ignore[method-assign]

        get_hitl = find_endpoint(router, "/api/hitl")
        assert get_hitl is not None
        response = await get_hitl()

        items = json.loads(response.body)
        assert len(items) == 1
        assert items[0]["cause"] == "CI failed after 2 fix attempt(s)"

    @pytest.mark.asyncio
    async def test_hitl_endpoint_includes_visual_evidence_when_set(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """When visual evidence is stored in state, it should appear in the response."""
        from models import VisualEvidence, VisualEvidenceItem

        ev = VisualEvidence(
            items=[
                VisualEvidenceItem(
                    screen_name="login", diff_percent=12.5, status="fail"
                )
            ],
            summary="1 screen exceeded threshold",
            attempt=2,
        )
        state.set_hitl_visual_evidence(42, ev)

        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)

        hitl_item = HITLItem(issue=42, title="Fix visual regression", pr=101)
        pr_mgr.list_hitl_items = AsyncMock(return_value=[hitl_item])  # type: ignore[method-assign]

        get_hitl = find_endpoint(router, "/api/hitl")
        assert get_hitl is not None
        response = await get_hitl()

        items = json.loads(response.body)
        assert len(items) == 1
        visual = items[0]["visualEvidence"]
        assert visual is not None
        assert visual["summary"] == "1 screen exceeded threshold"
        assert visual["attempt"] == 2
        assert visual["items"][0]["screen_name"] == "login"
        assert visual["items"][0]["diff_percent"] == 12.5
        assert visual["items"][0]["status"] == "fail"

    @pytest.mark.asyncio
    async def test_hitl_endpoint_omits_visual_evidence_when_not_set(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """When no visual evidence is stored, visualEvidence key should be absent."""
        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)

        hitl_item = HITLItem(issue=42, title="Fix bug", pr=101)
        pr_mgr.list_hitl_items = AsyncMock(return_value=[hitl_item])  # type: ignore[method-assign]

        get_hitl = find_endpoint(router, "/api/hitl")
        assert get_hitl is not None
        response = await get_hitl()

        items = json.loads(response.body)
        assert len(items) == 1
        assert items[0].get("visualEvidence") is None


# ---------------------------------------------------------------------------
# /api/metrics endpoint
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# HITL skip with improve origin → triage transition
# ---------------------------------------------------------------------------


class TestHITLSkipImproveTransition:
    """Tests that /api/hitl/{issue}/skip transitions improve issues to triage."""

    @pytest.mark.asyncio
    async def test_hitl_skip_closes_issue(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Skipping a HITL item should close the issue."""
        from models import HITLSkipRequest

        state.set_hitl_origin(42, "hydraflow-review")

        mock_orch = MagicMock()
        mock_orch.skip_hitl_issue = MagicMock()
        router, pr_mgr = make_dashboard_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        pr_mgr.remove_label = AsyncMock()
        pr_mgr.add_labels = AsyncMock()
        pr_mgr.swap_pipeline_labels = AsyncMock()
        pr_mgr.close_issue = AsyncMock()
        pr_mgr.post_comment = AsyncMock()

        skip = find_endpoint(router, "/api/hitl/{issue_number}/skip")
        assert skip is not None
        await skip(42, HITLSkipRequest(reason="Not needed"))

        # Non-improve origin should close the issue, not strip labels
        pr_mgr.close_issue.assert_awaited_once_with(42)

    @pytest.mark.asyncio
    async def test_hitl_skip_no_origin_no_triage_transition(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """When no origin is set, skip should close the issue."""
        from models import HITLSkipRequest

        mock_orch = MagicMock()
        mock_orch.skip_hitl_issue = MagicMock()
        router, pr_mgr = make_dashboard_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        pr_mgr.remove_label = AsyncMock()
        pr_mgr.add_labels = AsyncMock()
        pr_mgr.swap_pipeline_labels = AsyncMock()
        pr_mgr.close_issue = AsyncMock()
        pr_mgr.post_comment = AsyncMock()

        skip = find_endpoint(router, "/api/hitl/{issue_number}/skip")
        assert skip is not None
        await skip(42, HITLSkipRequest(reason="Skipping"))

        # No origin → close the issue instead of stripping labels
        pr_mgr.close_issue.assert_awaited_once_with(42)

    @pytest.mark.asyncio
    async def test_hitl_skip_cleans_up_hitl_cause(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Skip should clean up hitl_cause in addition to hitl_origin."""
        from models import HITLSkipRequest

        state.set_hitl_origin(42, "hydraflow-review")
        state.set_hitl_cause(42, "CI failed after 2 fix attempt(s)")
        state.set_hitl_summary(42, "cached summary")

        mock_orch = MagicMock()
        mock_orch.skip_hitl_issue = MagicMock()
        router, pr_mgr = make_dashboard_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        pr_mgr.remove_label = AsyncMock()
        pr_mgr.add_labels = AsyncMock()
        pr_mgr.swap_pipeline_labels = AsyncMock()
        pr_mgr.close_issue = AsyncMock()
        pr_mgr.post_comment = AsyncMock()

        skip = find_endpoint(router, "/api/hitl/{issue_number}/skip")
        assert skip is not None
        await skip(42, HITLSkipRequest(reason="No longer needed"))

        assert state.get_hitl_origin(42) is None
        assert state.get_hitl_cause(42) is None
        assert state.get_hitl_summary(42) is None

    @pytest.mark.asyncio
    async def test_hitl_skip_records_outcome(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Skip should record an HITL_SKIPPED outcome."""
        from models import HITLSkipRequest

        mock_orch = MagicMock()
        mock_orch.skip_hitl_issue = MagicMock()
        router, pr_mgr = make_dashboard_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        pr_mgr.remove_label = AsyncMock()
        pr_mgr.add_labels = AsyncMock()
        pr_mgr.swap_pipeline_labels = AsyncMock()
        pr_mgr.close_issue = AsyncMock()
        pr_mgr.post_comment = AsyncMock()

        skip = find_endpoint(router, "/api/hitl/{issue_number}/skip")
        assert skip is not None
        await skip(42, HITLSkipRequest(reason="Not actionable"))

        outcome = state.get_outcome(42)
        assert outcome is not None
        assert outcome.outcome.value == "hitl_skipped"
        assert outcome.reason == "Not actionable"

    def test_hitl_skip_rejects_empty_reason(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Skip with empty reason should raise a Pydantic validation error."""
        from pydantic import ValidationError

        from models import HITLSkipRequest

        with pytest.raises(ValidationError):
            HITLSkipRequest(reason="")

    @pytest.mark.asyncio
    async def test_hitl_skip_posts_reason_as_comment(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Skip should post the reason as a GitHub comment."""
        from models import HITLSkipRequest

        mock_orch = MagicMock()
        mock_orch.skip_hitl_issue = MagicMock()
        router, pr_mgr = make_dashboard_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        pr_mgr.remove_label = AsyncMock()
        pr_mgr.add_labels = AsyncMock()
        pr_mgr.swap_pipeline_labels = AsyncMock()
        pr_mgr.close_issue = AsyncMock()
        pr_mgr.post_comment = AsyncMock()

        skip = find_endpoint(router, "/api/hitl/{issue_number}/skip")
        await skip(42, HITLSkipRequest(reason="Not actionable"))

        pr_mgr.post_comment.assert_awaited()
        comment = pr_mgr.post_comment.call_args.args[1]
        assert "Not actionable" in comment


# ---------------------------------------------------------------------------
# GET /api/issues/outcomes endpoint
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# POST /api/hitl/{issue_number}/close
# ---------------------------------------------------------------------------


class TestHITLCloseEndpoint:
    """Tests for POST /api/hitl/{issue_number}/close."""

    @pytest.mark.asyncio
    async def test_returns_error_without_orchestrator(
        self, config, event_bus, state, tmp_path
    ) -> None:
        from models import HITLCloseRequest

        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/hitl/{issue_number}/close")
        response = await endpoint(42, HITLCloseRequest(reason="test"))
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_close_issue_with_orchestrator(
        self, config, event_bus, state, tmp_path
    ) -> None:
        from models import HITLCloseRequest

        mock_orch = MagicMock()
        mock_orch.skip_hitl_issue = MagicMock()
        router, pr_mgr = make_dashboard_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        pr_mgr.close_issue = AsyncMock()  # type: ignore[method-assign]
        pr_mgr.post_comment = AsyncMock()  # type: ignore[method-assign]
        state.set_hitl_origin(42, "hydraflow-review")
        state.set_hitl_cause(42, "CI failure")
        state.set_hitl_summary(42, "cached summary")
        endpoint = find_endpoint(router, "/api/hitl/{issue_number}/close")
        response = await endpoint(42, HITLCloseRequest(reason="Duplicate of #123"))
        data = json.loads(response.body)
        assert data["status"] == "ok"
        mock_orch.skip_hitl_issue.assert_called_once_with(42)
        pr_mgr.close_issue.assert_called_once_with(42)
        assert state.get_hitl_origin(42) is None
        assert state.get_hitl_cause(42) is None
        assert state.get_hitl_summary(42) is None
        # Verify reason posted as comment
        pr_mgr.post_comment.assert_awaited()
        comment = pr_mgr.post_comment.call_args.args[1]
        assert "Duplicate of #123" in comment
        # Verify outcome recorded
        outcome = state.get_outcome(42)
        assert outcome is not None
        assert outcome.outcome.value == "hitl_closed"
        assert outcome.reason == "Duplicate of #123"

    def test_hitl_close_rejects_empty_reason(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Close with empty reason should raise a Pydantic validation error."""
        from pydantic import ValidationError

        from models import HITLCloseRequest

        with pytest.raises(ValidationError):
            HITLCloseRequest(reason="")

    @pytest.mark.asyncio
    async def test_hitl_close_succeeds_even_if_comment_fails(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Close should succeed even if post_comment raises."""

        from models import HITLCloseRequest

        mock_orch = MagicMock()
        mock_orch.skip_hitl_issue = MagicMock()
        router, pr_mgr = make_dashboard_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        pr_mgr.close_issue = AsyncMock()
        pr_mgr.remove_label = AsyncMock()
        pr_mgr.post_comment = AsyncMock(side_effect=RuntimeError("GitHub down"))

        # Pre-populate HITL state
        state.set_hitl_origin(42, "hydraflow-review")
        state.set_hitl_cause(42, "CI failure")
        state.set_hitl_summary(42, "cached summary")

        endpoint = find_endpoint(router, "/api/hitl/{issue_number}/close")
        response = await endpoint(42, HITLCloseRequest(reason="Duplicate"))

        assert response.status_code == 200
        data = json.loads(response.body)
        assert data["status"] == "ok"
        pr_mgr.close_issue.assert_called_once_with(42)
        # State should be cleaned up despite comment failure
        assert state.get_hitl_origin(42) is None
        assert state.get_hitl_cause(42) is None
        assert state.get_hitl_summary(42) is None
        outcome = state.get_outcome(42)
        assert outcome is not None
        assert outcome.outcome.value == "hitl_closed"


# ---------------------------------------------------------------------------
# HITL skip — comment failure resilience
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# HITL skip — comment failure resilience
# ---------------------------------------------------------------------------


class TestHITLSkipCommentResilience:
    """Test that hitl_skip succeeds even when post_comment fails."""

    @pytest.mark.asyncio
    async def test_hitl_skip_succeeds_even_if_comment_fails(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Skip should succeed even if post_comment raises."""

        from models import HITLSkipRequest

        mock_orch = MagicMock()
        mock_orch.skip_hitl_issue = MagicMock()
        router, pr_mgr = make_dashboard_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        pr_mgr.remove_label = AsyncMock()
        pr_mgr.add_labels = AsyncMock()
        pr_mgr.swap_pipeline_labels = AsyncMock()
        pr_mgr.close_issue = AsyncMock()
        pr_mgr.post_comment = AsyncMock(side_effect=RuntimeError("GitHub down"))

        # Pre-populate HITL state
        state.set_hitl_origin(42, "hydraflow-plan")
        state.set_hitl_cause(42, "Evidence rejected")
        state.set_hitl_summary(42, "some summary")

        skip = find_endpoint(router, "/api/hitl/{issue_number}/skip")
        assert skip is not None
        response = await skip(42, HITLSkipRequest(reason="Not needed"))

        assert response.status_code == 200
        data = json.loads(response.body)
        assert data["status"] == "ok"
        mock_orch.skip_hitl_issue.assert_called_once_with(42)
        # State should be cleaned up despite comment failure
        assert state.get_hitl_origin(42) is None
        assert state.get_hitl_cause(42) is None
        assert state.get_hitl_summary(42) is None
        outcome = state.get_outcome(42)
        assert outcome is not None
        assert outcome.outcome.value == "hitl_skipped"


class TestClearHitlStateHelper:
    """Tests for the _clear_hitl_state internal helper."""

    @pytest.mark.asyncio
    async def test_clear_hitl_state_clears_all_fields_via_skip(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """All HITL state fields are cleared by endpoints using _clear_hitl_state."""
        from models import HITLSkipRequest

        mock_orch = MagicMock()
        mock_orch.skip_hitl_issue = MagicMock()
        router, pr_mgr = make_dashboard_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        pr_mgr.remove_label = AsyncMock()
        pr_mgr.add_labels = AsyncMock()
        pr_mgr.swap_pipeline_labels = AsyncMock()
        pr_mgr.close_issue = AsyncMock()
        pr_mgr.post_comment = AsyncMock()

        state.set_hitl_origin(99, "hydraflow-review")
        state.set_hitl_cause(99, "CI failure")
        state.set_hitl_summary(99, "some summary")

        skip = find_endpoint(router, "/api/hitl/{issue_number}/skip")
        await skip(99, HITLSkipRequest(reason="test cleanup"))

        mock_orch.skip_hitl_issue.assert_called_once_with(99)
        assert state.get_hitl_origin(99) is None
        assert state.get_hitl_cause(99) is None
        assert state.get_hitl_summary(99) is None


class TestHITLApproveProcessEndpoint:
    """Tests for POST /api/hitl/{issue_number}/approve-process."""

    @pytest.mark.asyncio
    async def test_approve_process_returns_400_without_orchestrator(
        self, config, event_bus, state, tmp_path
    ) -> None:
        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/hitl/{issue_number}/approve-process")
        assert endpoint is not None
        response = await endpoint(42)
        data = json.loads(response.body)
        assert response.status_code == 400
        assert data["status"] == "no orchestrator"

    @pytest.mark.asyncio
    async def test_approve_process_swaps_labels_and_clears_state(
        self, config, event_bus, state, tmp_path
    ) -> None:
        mock_orch = MagicMock()
        mock_orch.skip_hitl_issue = MagicMock()
        router, pr_mgr = make_dashboard_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        pr_mgr.swap_pipeline_labels = AsyncMock()  # type: ignore[method-assign]
        pr_mgr.post_comment = AsyncMock()

        state.set_hitl_origin(42, "hydraflow-review")
        state.set_hitl_cause(42, "issue type hold")
        state.set_hitl_summary(42, "cached summary")

        endpoint = find_endpoint(router, "/api/hitl/{issue_number}/approve-process")
        response = await endpoint(42)
        data = json.loads(response.body)
        assert data["status"] == "ok"

        # Label swap to find/triage label
        pr_mgr.swap_pipeline_labels.assert_called_once_with(42, config.find_label[0])

        # HITL state cleaned up
        mock_orch.skip_hitl_issue.assert_called_once_with(42)
        assert state.get_hitl_origin(42) is None
        assert state.get_hitl_cause(42) is None
        assert state.get_hitl_summary(42) is None

    @pytest.mark.asyncio
    async def test_approve_process_records_outcome(
        self, config, event_bus, state, tmp_path
    ) -> None:
        mock_orch = MagicMock()
        mock_orch.skip_hitl_issue = MagicMock()
        router, pr_mgr = make_dashboard_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        pr_mgr.swap_pipeline_labels = AsyncMock()  # type: ignore[method-assign]
        pr_mgr.post_comment = AsyncMock()

        endpoint = find_endpoint(router, "/api/hitl/{issue_number}/approve-process")
        await endpoint(42)

        outcome = state.get_outcome(42)
        assert outcome is not None
        assert outcome.outcome.value == "hitl_approved"

    @pytest.mark.asyncio
    async def test_approve_process_posts_comment(
        self, config, event_bus, state, tmp_path
    ) -> None:
        mock_orch = MagicMock()
        mock_orch.skip_hitl_issue = MagicMock()
        router, pr_mgr = make_dashboard_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        pr_mgr.swap_pipeline_labels = AsyncMock()  # type: ignore[method-assign]
        pr_mgr.post_comment = AsyncMock()

        endpoint = find_endpoint(router, "/api/hitl/{issue_number}/approve-process")
        await endpoint(42)

        pr_mgr.post_comment.assert_called_once()
        comment_text = pr_mgr.post_comment.call_args[0][1]
        assert "Approved for processing" in comment_text
        assert "triage" in comment_text

    @pytest.mark.asyncio
    async def test_approve_process_succeeds_if_comment_fails(
        self, config, event_bus, state, tmp_path
    ) -> None:
        mock_orch = MagicMock()
        mock_orch.skip_hitl_issue = MagicMock()
        router, pr_mgr = make_dashboard_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        pr_mgr.swap_pipeline_labels = AsyncMock()  # type: ignore[method-assign]
        pr_mgr.post_comment = AsyncMock(side_effect=RuntimeError("API error"))

        endpoint = find_endpoint(router, "/api/hitl/{issue_number}/approve-process")
        response = await endpoint(42)
        data = json.loads(response.body)
        assert data["status"] == "ok"
        # State should still be cleaned up
        mock_orch.skip_hitl_issue.assert_called_once_with(42)

    @pytest.mark.asyncio
    async def test_approve_process_publishes_hitl_update_event(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """approve-process should publish a HITL_UPDATE event with resolved status."""
        mock_orch = MagicMock()
        mock_orch.skip_hitl_issue = MagicMock()
        router, pr_mgr = make_dashboard_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        pr_mgr.swap_pipeline_labels = AsyncMock()  # type: ignore[method-assign]
        pr_mgr.post_comment = AsyncMock()

        endpoint = find_endpoint(router, "/api/hitl/{issue_number}/approve-process")
        await endpoint(42)

        hitl_events = [e for e in event_bus._history if e.type == EventType.HITL_UPDATE]
        assert len(hitl_events) == 1
        assert hitl_events[0].data["status"] == "resolved"
        assert hitl_events[0].data["action"] == "approved_for_processing"
        assert hitl_events[0].data["issue"] == 42


# ---------------------------------------------------------------------------
# POST /api/intent
# ---------------------------------------------------------------------------


class TestResolveHitlItemHelper:
    """Tests for the _resolve_hitl_item internal helper."""

    @pytest.mark.asyncio
    async def test_resolve_records_outcome_and_publishes_event(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """_resolve_hitl_item should record outcome and publish HITL_UPDATE event."""

        from models import HITLCloseRequest

        mock_orch = MagicMock()
        mock_orch.skip_hitl_issue = MagicMock()
        router, pr_mgr = make_dashboard_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        pr_mgr.remove_label = AsyncMock()
        pr_mgr.add_labels = AsyncMock()
        pr_mgr.swap_pipeline_labels = AsyncMock()
        pr_mgr.close_issue = AsyncMock()
        pr_mgr.post_comment = AsyncMock()

        endpoint = find_endpoint(router, "/api/hitl/{issue_number}/close")
        response = await endpoint(77, HITLCloseRequest(reason="Resolved elsewhere"))

        data = json.loads(response.body)
        assert data["status"] == "ok"

        outcome = state.get_outcome(77)
        assert outcome is not None
        assert outcome.outcome.value == "hitl_closed"
        assert outcome.reason == "Resolved elsewhere"

        # Verify HITL_UPDATE event was published
        hitl_events = [e for e in event_bus._history if e.type == EventType.HITL_UPDATE]
        assert len(hitl_events) == 1
        assert hitl_events[0].data["action"] == "close"
        assert hitl_events[0].data["status"] == "resolved"

    @pytest.mark.asyncio
    async def test_resolve_returns_400_without_orchestrator(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Endpoints using _resolve_hitl_item return 400 when no orchestrator."""
        from models import HITLCloseRequest, HITLSkipRequest

        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)
        pr_mgr.remove_label = AsyncMock()
        pr_mgr.add_labels = AsyncMock()
        pr_mgr.swap_pipeline_labels = AsyncMock()
        pr_mgr.close_issue = AsyncMock()

        skip = find_endpoint(router, "/api/hitl/{issue_number}/skip")
        response = await skip(42, HITLSkipRequest(reason="test"))
        assert response.status_code == 400

        close = find_endpoint(router, "/api/hitl/{issue_number}/close")
        response = await close(42, HITLCloseRequest(reason="test"))
        assert response.status_code == 400
        pr_mgr.close_issue.assert_not_called()

        approve = find_endpoint(router, "/api/hitl/{issue_number}/approve-process")
        response = await approve(42)
        assert response.status_code == 400
        pr_mgr.swap_pipeline_labels.assert_not_called()

    @pytest.mark.asyncio
    async def test_resolve_comment_failure_does_not_break_response(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Comment posting failure in _resolve_hitl_item should not prevent success."""

        from models import HITLSkipRequest

        mock_orch = MagicMock()
        mock_orch.skip_hitl_issue = MagicMock()
        router, pr_mgr = make_dashboard_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        pr_mgr.remove_label = AsyncMock()
        pr_mgr.add_labels = AsyncMock()
        pr_mgr.swap_pipeline_labels = AsyncMock()
        pr_mgr.close_issue = AsyncMock()
        pr_mgr.post_comment = AsyncMock(side_effect=RuntimeError("API error"))

        endpoint = find_endpoint(router, "/api/hitl/{issue_number}/skip")
        response = await endpoint(42, HITLSkipRequest(reason="test"))

        assert response.status_code == 200
        data = json.loads(response.body)
        assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_resolve_all_three_endpoints_use_same_pattern(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """skip, close, and approve-process all clear state via _resolve_hitl_item."""

        from models import HITLCloseRequest, HITLSkipRequest

        mock_orch = MagicMock()
        mock_orch.skip_hitl_issue = MagicMock()
        router, pr_mgr = make_dashboard_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        pr_mgr.remove_label = AsyncMock()
        pr_mgr.add_labels = AsyncMock()
        pr_mgr.swap_pipeline_labels = AsyncMock()
        pr_mgr.close_issue = AsyncMock()
        pr_mgr.post_comment = AsyncMock()

        # Test skip
        state.set_hitl_origin(1, "hydraflow-plan")
        skip = find_endpoint(router, "/api/hitl/{issue_number}/skip")
        resp = await skip(1, HITLSkipRequest(reason="r1"))
        assert json.loads(resp.body)["status"] == "ok"
        assert state.get_hitl_origin(1) is None

        # Test close
        state.set_hitl_origin(2, "hydraflow-plan")
        close = find_endpoint(router, "/api/hitl/{issue_number}/close")
        resp = await close(2, HITLCloseRequest(reason="r2"))
        assert json.loads(resp.body)["status"] == "ok"
        assert state.get_hitl_origin(2) is None

        # Test approve-process
        state.set_hitl_origin(3, "hydraflow-plan")
        approve = find_endpoint(router, "/api/hitl/{issue_number}/approve-process")
        resp = await approve(3)
        assert json.loads(resp.body)["status"] == "ok"
        assert state.get_hitl_origin(3) is None


class TestBuildHitlContextNoneBody:
    """Test that _build_hitl_context handles None body (issue #2573)."""

    @pytest.mark.asyncio
    async def test_none_body_does_not_crash_hitl_summary(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """When issue.body is None, _build_hitl_context should not raise."""
        from tests.conftest import IssueFactory

        config.transcript_summarization_enabled = True
        config.gh_token = "fake-token"

        # Build a GitHubIssue and force body to None
        issue = IssueFactory.create(number=99, title="Test issue")
        object.__setattr__(issue, "body", None)

        # Access _compute_hitl_summary through the module's closure.
        # We mock the fetcher to return our None-body issue and the
        # summarizer to capture what context it receives.
        captured_context: list[str] = []

        async def _mock_summarize(ctx: str) -> str:
            captured_context.append(ctx)
            return "summary line"

        with (
            patch(
                "dashboard_routes._routes.IssueFetcher",
                return_value=MagicMock(
                    fetch_issue_by_number=AsyncMock(return_value=issue)
                ),
            ),
            patch(
                "dashboard_routes._routes.TranscriptSummarizer",
                return_value=MagicMock(
                    summarize_hitl_context=AsyncMock(side_effect=_mock_summarize)
                ),
            ),
        ):
            # Re-create router to pick up the patched classes
            router2, _ = make_dashboard_router(config, event_bus, state, tmp_path)

            # Find the HITL summary endpoint
            endpoint = find_endpoint(router2, "/api/hitl/{issue_number}/summary")
            assert endpoint is not None, "summary endpoint not found"

            state.set_hitl_cause(99, "test-cause")
            resp = await endpoint(99)

        payload = json.loads(resp.body)
        assert payload.get("summary") == "summary line"
        # The context should have been built without error
        assert len(captured_context) == 1
        assert "Issue #99" in captured_context[0]


# ---------------------------------------------------------------------------
# Moved from test_dashboard_websocket.py — HITL REST endpoint tests
# (TestClient / HydraFlowDashboard integration style)
# ---------------------------------------------------------------------------


class TestHITLRoute:
    """Tests for the GET /api/hitl route."""

    def test_hitl_returns_200(self, config, event_bus: EventBus, state) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        with patch("pr_manager.PRManager.list_hitl_items", return_value=[]):
            response = client.get("/api/hitl")

        assert response.status_code == 200

    def test_hitl_returns_empty_list_when_no_issues(
        self, config, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        with patch("pr_manager.PRManager.list_hitl_items", return_value=[]):
            response = client.get("/api/hitl")

        assert response.json() == []

    def test_hitl_returns_issues_with_pr_info(
        self, config, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        mock_items = [
            HITLItem(
                issue=42,
                title="Fix widget",
                issue_url="https://github.com/org/repo/issues/42",
                pr=99,
                pr_url="https://github.com/org/repo/pull/99",
                branch="agent/issue-42",
            ),
        ]

        client = TestClient(app)
        with patch("pr_manager.PRManager.list_hitl_items", return_value=mock_items):
            response = client.get("/api/hitl")

        body = response.json()
        assert len(body) == 1
        assert body[0]["issue"] == 42
        assert body[0]["title"] == "Fix widget"
        assert body[0]["pr"] == 99
        assert body[0]["branch"] == "agent/issue-42"

    def test_hitl_returns_empty_on_gh_failure(
        self, config, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        # PRManager.list_hitl_items handles errors internally, returns []
        with patch("pr_manager.PRManager.list_hitl_items", return_value=[]):
            response = client.get("/api/hitl")

        assert response.json() == []

    def test_hitl_shows_zero_pr_when_no_pr_found(
        self, config, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        mock_items = [
            HITLItem(
                issue=10,
                title="Broken thing",
                issue_url="",
                pr=0,
                pr_url="",
                branch="agent/issue-10",
            ),
        ]

        client = TestClient(app)
        with patch("pr_manager.PRManager.list_hitl_items", return_value=mock_items):
            response = client.get("/api/hitl")

        body = response.json()
        assert len(body) == 1
        assert body[0]["pr"] == 0
        assert body[0]["prUrl"] == ""


# ---------------------------------------------------------------------------
# POST /api/hitl/{issue}/correct
# ---------------------------------------------------------------------------


class TestHITLCorrectEndpoint:
    """Tests for the POST /api/hitl/{issue}/correct route."""

    def test_correct_returns_ok_with_orchestrator(
        self, config, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        orch.submit_hitl_correction = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with patch("pr_manager.PRManager.swap_pipeline_labels", new_callable=AsyncMock):
            response = client.post(
                "/api/hitl/42/correct",
                json={"correction": "Mock the DB connection"},
            )

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_correct_calls_orchestrator_submit(
        self, config, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        orch.submit_hitl_correction = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with patch("pr_manager.PRManager.swap_pipeline_labels", new_callable=AsyncMock):
            client.post(
                "/api/hitl/42/correct",
                json={"correction": "Fix the test"},
            )

        orch.submit_hitl_correction.assert_called_once_with(42, "Fix the test")

    def test_correct_returns_400_without_orchestrator(
        self, config, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=None)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.post(
            "/api/hitl/42/correct",
            json={"correction": "Something"},
        )

        assert response.status_code == 400
        assert response.json() == {"status": "no orchestrator"}

    def test_correct_publishes_hitl_update_event(
        self, config, event_bus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        orch.submit_hitl_correction = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with patch("pr_manager.PRManager.swap_pipeline_labels", new_callable=AsyncMock):
            client.post(
                "/api/hitl/42/correct",
                json={"correction": "Fix it"},
            )

        history = event_bus.get_history()
        hitl_events = [e for e in history if e.type.value == "hitl_update"]
        assert len(hitl_events) == 1
        assert hitl_events[0].data["issue"] == 42
        assert hitl_events[0].data["status"] == "processing"
        assert hitl_events[0].data["action"] == "correct"

    def test_correct_rejects_empty_correction(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        state = make_state(tmp_path)
        orch = make_orchestrator_mock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.post(
            "/api/hitl/42/correct",
            json={"correction": ""},
        )

        assert response.status_code == 400
        assert "must not be empty" in response.json()["detail"]

    def test_correct_rejects_whitespace_only_correction(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        state = make_state(tmp_path)
        orch = make_orchestrator_mock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.post(
            "/api/hitl/42/correct",
            json={"correction": "   "},
        )

        assert response.status_code == 400
        assert "must not be empty" in response.json()["detail"]

    def test_correct_rejects_null_correction(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        state = make_state(tmp_path)
        orch = make_orchestrator_mock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.post(
            "/api/hitl/42/correct",
            json={"correction": None},
        )

        assert response.status_code == 400
        assert "must not be empty" in response.json()["detail"]


# ---------------------------------------------------------------------------
# POST /api/hitl/{issue}/skip
# ---------------------------------------------------------------------------


class TestHITLSkipEndpoint:
    """Tests for the POST /api/hitl/{issue}/skip route."""

    def test_skip_returns_ok_with_orchestrator(
        self, config, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        orch.skip_hitl_issue = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with (
            patch("pr_manager.PRManager.remove_label", new_callable=AsyncMock),
            patch("pr_manager.PRManager.close_issue", new_callable=AsyncMock),
            patch("pr_manager.PRManager.post_comment", new_callable=AsyncMock),
        ):
            response = client.post("/api/hitl/42/skip", json={"reason": "not needed"})

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_skip_calls_orchestrator_skip(
        self, config, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        orch.skip_hitl_issue = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with (
            patch("pr_manager.PRManager.remove_label", new_callable=AsyncMock),
            patch("pr_manager.PRManager.close_issue", new_callable=AsyncMock),
            patch("pr_manager.PRManager.post_comment", new_callable=AsyncMock),
        ):
            client.post("/api/hitl/42/skip", json={"reason": "not needed"})

        orch.skip_hitl_issue.assert_called_once_with(42)

    def test_skip_returns_400_without_orchestrator(
        self, config, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=None)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.post("/api/hitl/42/skip", json={"reason": "not needed"})

        assert response.status_code == 400
        assert response.json() == {"status": "no orchestrator"}

    def test_skip_publishes_hitl_update_event(self, config, event_bus, state) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        orch.skip_hitl_issue = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with (
            patch("pr_manager.PRManager.remove_label", new_callable=AsyncMock),
            patch("pr_manager.PRManager.close_issue", new_callable=AsyncMock),
            patch("pr_manager.PRManager.post_comment", new_callable=AsyncMock),
        ):
            client.post("/api/hitl/42/skip", json={"reason": "not needed"})

        history = event_bus.get_history()
        hitl_events = [e for e in history if e.type.value == "hitl_update"]
        assert len(hitl_events) == 1
        assert hitl_events[0].data["issue"] == 42
        assert hitl_events[0].data["status"] == "resolved"
        assert hitl_events[0].data["action"] == "skip"

    def test_skip_removes_hitl_origin_from_state(
        self, config, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        state.set_hitl_origin(42, "hydraflow-review")
        orch = make_orchestrator_mock()
        orch.skip_hitl_issue = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with (
            patch("pr_manager.PRManager.remove_label", new_callable=AsyncMock),
            patch("pr_manager.PRManager.close_issue", new_callable=AsyncMock),
            patch("pr_manager.PRManager.post_comment", new_callable=AsyncMock),
        ):
            client.post("/api/hitl/42/skip", json={"reason": "not needed"})

        assert state.get_hitl_origin(42) is None


# ---------------------------------------------------------------------------
# POST /api/hitl/{issue}/close (TestClient style)
# ---------------------------------------------------------------------------


class TestHITLCloseEndpointViaTestClient:
    """Tests for the POST /api/hitl/{issue}/close route (TestClient integration style)."""

    def test_close_returns_ok_with_orchestrator(
        self, config, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        orch.skip_hitl_issue = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with (
            patch("pr_manager.PRManager.close_issue", new_callable=AsyncMock),
            patch("pr_manager.PRManager.post_comment", new_callable=AsyncMock),
        ):
            response = client.post("/api/hitl/42/close", json={"reason": "duplicate"})

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_close_calls_orchestrator_skip(
        self, config, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        orch.skip_hitl_issue = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with (
            patch("pr_manager.PRManager.close_issue", new_callable=AsyncMock),
            patch("pr_manager.PRManager.post_comment", new_callable=AsyncMock),
        ):
            client.post("/api/hitl/42/close", json={"reason": "duplicate"})

        orch.skip_hitl_issue.assert_called_once_with(42)

    def test_close_returns_400_without_orchestrator(
        self, config, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=None)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.post("/api/hitl/42/close", json={"reason": "duplicate"})

        assert response.status_code == 400
        assert response.json() == {"status": "no orchestrator"}

    def test_close_publishes_hitl_update_event(self, config, event_bus, state) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        orch.skip_hitl_issue = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with (
            patch("pr_manager.PRManager.close_issue", new_callable=AsyncMock),
            patch("pr_manager.PRManager.post_comment", new_callable=AsyncMock),
        ):
            client.post("/api/hitl/42/close", json={"reason": "duplicate"})

        history = event_bus.get_history()
        hitl_events = [e for e in history if e.type.value == "hitl_update"]
        assert len(hitl_events) == 1
        assert hitl_events[0].data["issue"] == 42
        assert hitl_events[0].data["status"] == "resolved"
        assert hitl_events[0].data["action"] == "close"

    def test_close_removes_hitl_origin_from_state(
        self, config, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        state.set_hitl_origin(42, "hydraflow-review")
        orch = make_orchestrator_mock()
        orch.skip_hitl_issue = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with (
            patch("pr_manager.PRManager.close_issue", new_callable=AsyncMock),
            patch("pr_manager.PRManager.post_comment", new_callable=AsyncMock),
        ):
            client.post("/api/hitl/42/close", json={"reason": "duplicate"})

        assert state.get_hitl_origin(42) is None


# ---------------------------------------------------------------------------
# POST /api/hitl/{issue}/approve-process (TestClient style)
# ---------------------------------------------------------------------------


class TestHITLApproveProcessEndpointViaTestClient:
    """Tests for the POST /api/hitl/{issue}/approve-process route (TestClient integration style)."""

    def test_bug_report_routes_to_find_label(
        self, config, event_bus: EventBus, state
    ) -> None:
        """Bug reports approved from HITL go to triage first."""
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        orch.skip_hitl_issue = MagicMock()
        state.set_hitl_cause(42, "Bug report detected — awaiting human review")
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        swapped: list[tuple[int, str]] = []

        async def _fake_swap(issue_number: int, label: str, **_kw: object) -> None:
            swapped.append((issue_number, label))

        with (
            patch("pr_manager.PRManager.swap_pipeline_labels", side_effect=_fake_swap),
            patch("pr_manager.PRManager.post_comment", new_callable=AsyncMock),
        ):
            response = client.post("/api/hitl/42/approve-process")

        assert response.status_code == 200
        assert swapped == [(42, config.find_label[0])]

    def test_epic_routes_to_find_label(
        self, config, event_bus: EventBus, state
    ) -> None:
        """Epic issues approved from HITL also go to triage first."""
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        orch.skip_hitl_issue = MagicMock()
        state.set_hitl_cause(42, "Epic detected — awaiting human review")
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        swapped: list[tuple[int, str]] = []

        async def _fake_swap(issue_number: int, label: str, **_kw: object) -> None:
            swapped.append((issue_number, label))

        with (
            patch("pr_manager.PRManager.swap_pipeline_labels", side_effect=_fake_swap),
            patch("pr_manager.PRManager.post_comment", new_callable=AsyncMock),
        ):
            response = client.post("/api/hitl/42/approve-process")

        assert response.status_code == 200
        assert swapped == [(42, config.find_label[0])]

    def test_returns_400_without_orchestrator(
        self, config, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()
        client = TestClient(app)
        response = client.post("/api/hitl/42/approve-process")
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# GET /api/hitl enriched with status
# ---------------------------------------------------------------------------


class TestHITLEnrichedRoute:
    """Tests for the enriched GET /api/hitl response with status."""

    def test_hitl_includes_status_from_orchestrator(
        self, config, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock(running=True)
        orch.get_hitl_status = MagicMock(return_value="processing")
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        mock_items = [
            HITLItem(issue=42, title="Fix widget", branch="agent/issue-42"),
        ]

        client = TestClient(app)
        with patch("pr_manager.PRManager.list_hitl_items", return_value=mock_items):
            response = client.get("/api/hitl")

        body = response.json()
        assert len(body) == 1
        assert body[0]["status"] == "processing"
        orch.get_hitl_status.assert_called_once_with(42)

    def test_hitl_defaults_status_when_no_orchestrator(
        self, config, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=None)
        app = dashboard.create_app()

        mock_items = [
            HITLItem(issue=42, title="Fix widget", branch="agent/issue-42"),
        ]

        client = TestClient(app)
        with patch("pr_manager.PRManager.list_hitl_items", return_value=mock_items):
            response = client.get("/api/hitl")

        body = response.json()
        assert len(body) == 1
        assert body[0]["status"] == "pending"

    def test_hitl_includes_cause_and_status_fields(
        self, config, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        mock_items = [
            HITLItem(
                issue=42,
                title="Fix widget",
                branch="agent/issue-42",
                cause="CI failure",
                status="pending",
            ),
        ]

        client = TestClient(app)
        with patch("pr_manager.PRManager.list_hitl_items", return_value=mock_items):
            response = client.get("/api/hitl")

        body = response.json()
        assert "cause" in body[0]
        assert "status" in body[0]
        assert body[0]["cause"] == "CI failure"
