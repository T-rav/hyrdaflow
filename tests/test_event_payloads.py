"""Tests for TypedDict structural compatibility of event payload types."""

from __future__ import annotations

from models import (
    LabelCounts,
    ManifestRefreshSummary,
    PipelineIssue,
    PipelineSnapshotEntry,
    TranscriptEventData,
    WorkerResultMeta,
)


class TestTranscriptEventData:
    """TranscriptEventData is total=False — all keys are optional."""

    def test_issue_only(self) -> None:
        data: TranscriptEventData = {"issue": 42}
        assert data["issue"] == 42

    def test_all_keys(self) -> None:
        data: TranscriptEventData = {"issue": 42, "pr": 7, "source": "planner"}
        assert data["issue"] == 42
        assert data["pr"] == 7
        assert data["source"] == "planner"

    def test_spread_with_line(self) -> None:
        base: TranscriptEventData = {"issue": 42, "source": "agent"}
        combined = {**base, "line": "hello world"}
        assert combined["issue"] == 42
        assert combined["line"] == "hello world"


class TestEventPayloadTypes:
    """Verify event payload TypedDicts have correct required fields."""

    def test_worker_update_payload(self) -> None:
        from models import WorkerUpdatePayload

        payload: WorkerUpdatePayload = {
            "issue": 1,
            "worker": 0,
            "status": "running",
            "role": "implementer",
        }
        assert payload["issue"] == 1
        assert payload["worker"] == 0
        assert payload["status"] == "running"
        assert payload["role"] == "implementer"

    def test_pr_created_payload(self) -> None:
        from models import PRCreatedPayload

        payload: PRCreatedPayload = {
            "pr": 99,
            "issue": 42,
            "branch": "agent/issue-42",
            "draft": False,
            "url": "https://github.com/test/repo/pull/99",
        }
        assert payload["pr"] == 99
        assert payload["branch"] == "agent/issue-42"

    def test_ci_check_optional_fields(self) -> None:
        from models import CICheckPayload

        # Minimal — pending state
        pending: CICheckPayload = {"pr": 5, "status": "pending", "pending": 3}
        assert pending["pending"] == 3
        assert "verdict" not in pending

        # Final — with total
        final: CICheckPayload = {"pr": 5, "status": "passed", "total": 10}
        assert final["total"] == 10
        assert "verdict" not in final

        # Verdict supplied — approve
        with_verdict: CICheckPayload = {
            "pr": 5,
            "issue": 42,
            "status": "passed",
            "worker": 1,
            "attempt": 2,
            "verdict": "approve",
        }
        assert with_verdict["verdict"] == "approve"

        # Verdict supplied — request-changes (hyphenated, typo-prone)
        with_request_changes: CICheckPayload = {
            "pr": 5,
            "issue": 42,
            "status": "fix_done",
            "verdict": "request-changes",
        }
        assert with_request_changes["verdict"] == "request-changes"

        # Verdict supplied — comment (default when _parse_verdict finds no pattern)
        with_comment: CICheckPayload = {
            "pr": 5,
            "issue": 42,
            "status": "fix_done",
            "verdict": "comment",
        }
        assert with_comment["verdict"] == "comment"

    def test_hitl_escalation_with_ci_fix_attempts(self) -> None:
        from models import HITLEscalationPayload

        payload: HITLEscalationPayload = {
            "issue": 42,
            "cause": "CI failure",
            "origin": "hydraflow-review",
            "ci_fix_attempts": 3,
        }
        assert payload["ci_fix_attempts"] == 3

    def test_hitl_escalation_with_visual_evidence(self) -> None:
        from models import HITLEscalationPayload

        payload: HITLEscalationPayload = {
            "issue": 42,
            "cause": "Visual validation failed",
            "origin": "hydraflow-review",
            "visual_evidence": {"items": [], "summary": "login screen diff 12%"},
        }
        assert payload["visual_evidence"]["summary"] == "login screen diff 12%"

    def test_review_update_optional_verdict(self) -> None:
        from models import ReviewUpdatePayload

        # Without verdict
        no_verdict: ReviewUpdatePayload = {
            "pr": 5,
            "issue": 42,
            "status": "reviewing",
        }
        assert no_verdict["status"] == "reviewing"

        # With verdict
        with_verdict: ReviewUpdatePayload = {
            "pr": 5,
            "issue": 42,
            "status": "done",
            "verdict": "approve",
        }
        assert with_verdict["verdict"] == "approve"


class TestPipelineSnapshotEntry:
    """PipelineSnapshotEntry has four required keys."""

    def test_required_keys(self) -> None:
        entry: PipelineSnapshotEntry = {
            "issue_number": 42,
            "title": "Fix bug",
            "url": "https://github.com/test/repo/issues/42",
            "status": "queued",
        }
        assert entry["issue_number"] == 42
        assert entry["title"] == "Fix bug"
        assert entry["url"] == "https://github.com/test/repo/issues/42"
        assert entry["status"] == "queued"

    def test_compatible_with_pipeline_issue(self) -> None:
        entry: PipelineSnapshotEntry = {
            "issue_number": 42,
            "title": "Fix bug",
            "url": "https://github.com/test/repo/issues/42",
            "status": "queued",
        }
        issue = PipelineIssue(**entry)
        assert issue.issue_number == 42
        assert issue.title == "Fix bug"


class TestLabelCounts:
    """LabelCounts has three required keys."""

    def test_required_keys(self) -> None:
        counts: LabelCounts = {
            "open_by_label": {"hydraflow-plan": 2, "hydraflow-ready": 1},
            "total_closed": 10,
            "total_merged": 5,
        }
        assert counts["open_by_label"]["hydraflow-plan"] == 2
        assert counts["total_closed"] == 10
        assert counts["total_merged"] == 5

    def test_value_types(self) -> None:
        counts: LabelCounts = {
            "open_by_label": {},
            "total_closed": 0,
            "total_merged": 0,
        }
        assert isinstance(counts["open_by_label"], dict)
        assert isinstance(counts["total_closed"], int)
        assert isinstance(counts["total_merged"], int)


class TestWorkerResultMeta:
    """WorkerResultMeta is total=False — all fields are optional."""

    def test_all_fields(self) -> None:
        meta: WorkerResultMeta = {
            "quality_fix_attempts": 2,
            "duration_seconds": 120.5,
            "error": None,
            "commits": 3,
        }
        assert meta["quality_fix_attempts"] == 2
        assert meta["duration_seconds"] == 120.5
        assert meta["error"] is None
        assert meta["commits"] == 3

    def test_partial_fields(self) -> None:
        meta: WorkerResultMeta = {"quality_fix_attempts": 1}
        assert meta["quality_fix_attempts"] == 1
        assert "duration_seconds" not in meta

    def test_round_trips_through_state(self, tmp_path: object) -> None:
        from pathlib import Path

        from state import StateTracker

        state_file = Path(str(tmp_path)) / "state.json"
        tracker = StateTracker(state_file)

        meta: WorkerResultMeta = {
            "quality_fix_attempts": 2,
            "duration_seconds": 60.0,
            "error": "lint failed",
            "commits": 1,
        }
        tracker.set_worker_result_meta(42, meta)
        loaded = tracker.get_worker_result_meta(42)
        assert loaded["quality_fix_attempts"] == 2
        assert loaded["error"] == "lint failed"


class TestManifestRefreshSummary:
    """ManifestRefreshSummary has two required keys."""

    def test_required_keys(self) -> None:
        result: ManifestRefreshSummary = {"hash": "abc123", "length": 500}
        assert result["hash"] == "abc123"
        assert result["length"] == 500
