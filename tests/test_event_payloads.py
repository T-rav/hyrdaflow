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


# ---------------------------------------------------------------------------
# ReviewerStatus.FIXING_REVIEW_FINDINGS
# ---------------------------------------------------------------------------


class TestReviewerStatusFixingReviewFindings:
    """Verify the FIXING_REVIEW_FINDINGS enum member."""

    def test_member_exists(self) -> None:
        from models import ReviewerStatus

        assert hasattr(ReviewerStatus, "FIXING_REVIEW_FINDINGS")

    def test_fixing_review_findings_has_expected_string_value(self) -> None:
        from models import ReviewerStatus

        assert ReviewerStatus.FIXING_REVIEW_FINDINGS == "fixing_review_findings"

    def test_fixing_review_findings_roundtrips_from_string(self) -> None:
        from models import ReviewerStatus

        assert (
            ReviewerStatus("fixing_review_findings")
            is ReviewerStatus.FIXING_REVIEW_FINDINGS
        )


# ---------------------------------------------------------------------------
# HydraFlowEvent.typed_data()
# ---------------------------------------------------------------------------


class TestTypedData:
    """Test the typed_data() helper on HydraFlowEvent."""

    def test_returns_payload_keys(self) -> None:
        from events import EventType, HydraFlowEvent
        from models import WorkerUpdatePayload

        event = HydraFlowEvent(
            type=EventType.WORKER_UPDATE,
            data={"issue": 42, "worker": 1, "status": "running", "role": "agent"},
        )
        payload = event.typed_data(WorkerUpdatePayload)
        assert payload["issue"] == 42
        assert payload["worker"] == 1
        assert payload["status"] == "running"
        assert payload["role"] == "agent"

    def test_review_update(self) -> None:
        from events import EventType, HydraFlowEvent
        from models import ReviewUpdatePayload

        event = HydraFlowEvent(
            type=EventType.REVIEW_UPDATE,
            data={
                "pr": 10,
                "issue": 5,
                "worker": 2,
                "status": "reviewing",
                "role": "reviewer",
            },
        )
        payload = event.typed_data(ReviewUpdatePayload)
        assert payload["pr"] == 10
        assert payload["issue"] == 5

    def test_ci_check(self) -> None:
        from events import EventType, HydraFlowEvent
        from models import CICheckPayload

        event = HydraFlowEvent(
            type=EventType.CI_CHECK,
            data={"pr": 7, "issue": 3, "status": "pending", "pending": 2, "total": 5},
        )
        payload = event.typed_data(CICheckPayload)
        assert payload["pending"] == 2
        assert payload["total"] == 5

    def test_empty_data(self) -> None:
        from events import EventType, HydraFlowEvent
        from models import WorkerUpdatePayload

        event = HydraFlowEvent(type=EventType.WORKER_UPDATE, data={})
        payload = event.typed_data(WorkerUpdatePayload)
        assert isinstance(payload, dict)


# ---------------------------------------------------------------------------
# New payload TypedDicts — construction tests
# ---------------------------------------------------------------------------


class TestTranscriptLinePayload:
    def test_construct_minimal(self) -> None:
        from models import TranscriptLinePayload

        p: TranscriptLinePayload = {"line": "hello"}
        assert p["line"] == "hello"

    def test_construct_full(self) -> None:
        from models import TranscriptLinePayload

        p: TranscriptLinePayload = {
            "issue": 1,
            "pr": 2,
            "source": "agent",
            "line": "hello",
        }
        assert p["issue"] == 1
        assert p["line"] == "hello"


class TestSystemAlertPayload:
    def test_system_alert_payload_accepts_required_keys(self) -> None:
        from models import SystemAlertPayload

        p: SystemAlertPayload = {"message": "alert", "source": "loop"}
        assert p["message"] == "alert"

    def test_with_optional_fields(self) -> None:
        from models import SystemAlertPayload

        p: SystemAlertPayload = {
            "message": "epic stale",
            "source": "epic_monitor",
            "epic_number": 5,
        }
        assert p["epic_number"] == 5

    def test_with_resume_at_field(self) -> None:
        from models import SystemAlertPayload

        p: SystemAlertPayload = {
            "message": "Credit limit reached.",
            "source": "plan",
            "resume_at": "2026-03-15T18:00:00+00:00",
        }
        assert p["resume_at"] == "2026-03-15T18:00:00+00:00"


class TestTranscriptSummaryPayload:
    def test_as_comment(self) -> None:
        from models import TranscriptSummaryPayload

        p: TranscriptSummaryPayload = {
            "source_issue": 1,
            "phase": "implement",
            "posted_as": "comment",
        }
        assert p["posted_as"] == "comment"

    def test_as_issue(self) -> None:
        from models import TranscriptSummaryPayload

        p: TranscriptSummaryPayload = {
            "source_issue": 1,
            "phase": "plan",
            "summary_issue": 99,
        }
        assert p["summary_issue"] == 99


class TestVerificationJudgePayload:
    def test_verification_judge_payload_accepts_required_keys(self) -> None:
        from models import VerificationJudgePayload

        p: VerificationJudgePayload = {
            "issue": 1,
            "pr": 2,
            "all_criteria_pass": True,
            "instructions_quality": "good",
            "summary": "all pass",
        }
        assert p["all_criteria_pass"] is True


class TestVisualGatePayload:
    def test_visual_gate_payload_accepts_required_keys(self) -> None:
        from models import VisualGatePayload

        p: VisualGatePayload = {
            "pr": 1,
            "issue": 2,
            "worker": 3,
            "verdict": "pass",
            "reason": "ok",
        }
        assert p["verdict"] == "pass"

    def test_with_runtime(self) -> None:
        from models import VisualGatePayload

        p: VisualGatePayload = {
            "pr": 1,
            "issue": 2,
            "worker": 3,
            "verdict": "bypass",
            "reason": "emergency",
            "runtime_seconds": 1.5,
            "retries": 0,
        }
        assert p["runtime_seconds"] == 1.5


class TestBaselineUpdatePayload:
    def test_baseline_update_payload_sets_approved_flag(self) -> None:
        from models import BaselineUpdatePayload

        p: BaselineUpdatePayload = {
            "pr_number": 1,
            "issue_number": 2,
            "baseline_files": ["a.py"],
            "approved": True,
            "approver": "bot",
        }
        assert p["approved"] is True

    def test_baseline_update_payload_includes_rollback_reason(self) -> None:
        from models import BaselineUpdatePayload

        p: BaselineUpdatePayload = {
            "pr_number": 1,
            "issue_number": 2,
            "baseline_files": ["a.py"],
            "rollback": True,
            "approver": "admin",
            "reason": "regression",
        }
        assert p["rollback"] is True
        assert p["reason"] == "regression"


class TestEpicPayloads:
    def test_epic_progress_payload_carries_epic_number(self) -> None:
        from models import EpicProgressPayload

        p: EpicProgressPayload = {
            "epic_number": 1,
            "progress": {"total": 5, "done": 3},
        }
        assert p["epic_number"] == 1

    def test_epic_ready_payload_carries_readiness(self) -> None:
        from models import EpicReadyPayload

        p: EpicReadyPayload = {
            "epic_number": 1,
            "readiness": {"ready": True},
        }
        assert p["readiness"]["ready"] is True

    def test_epic_releasing_payload_carries_job_id(self) -> None:
        from models import EpicReleasingPayload

        p: EpicReleasingPayload = {"epic_number": 1, "job_id": "j-1"}
        assert p["job_id"] == "j-1"

    def test_released_completed(self) -> None:
        from models import EpicReleasedPayload

        p: EpicReleasedPayload = {
            "epic_number": 1,
            "job_id": "j-1",
            "status": "completed",
        }
        assert p["status"] == "completed"

    def test_released_failed(self) -> None:
        from models import EpicReleasedPayload

        p: EpicReleasedPayload = {
            "epic_number": 1,
            "job_id": "j-1",
            "status": "failed",
            "error": "merge conflict",
        }
        assert p["error"] == "merge conflict"

    def test_epic_update_payload_carries_action(self) -> None:
        from models import EpicUpdatePayload

        p: EpicUpdatePayload = {"epic_number": 1, "action": "released"}
        assert p["action"] == "released"


class TestCratePayloads:
    def test_crate_activated_payload_carries_crate_number(self) -> None:
        from models import CrateActivatedPayload

        p: CrateActivatedPayload = {"crate_number": 1}
        assert p["crate_number"] == 1

    def test_crate_completed_payload_carries_crate_number(self) -> None:
        from models import CrateCompletedPayload

        p: CrateCompletedPayload = {"crate_number": 1}
        assert p["crate_number"] == 1


class TestOrchestratorStatusCreditsPausedUntil:
    """Verify credits_paused_until is accepted by OrchestratorStatusPayload."""

    def test_with_field(self) -> None:
        from models import OrchestratorStatusPayload

        p: OrchestratorStatusPayload = {
            "status": "paused",
            "credits_paused_until": "2024-01-01T12:00:00Z",
        }
        assert p["credits_paused_until"] == "2024-01-01T12:00:00Z"

    def test_without_field(self) -> None:
        from models import OrchestratorStatusPayload

        p: OrchestratorStatusPayload = {"status": "running"}
        assert "credits_paused_until" not in p


# ---------------------------------------------------------------------------
# Reviewer raw string replacement — source-level check
# ---------------------------------------------------------------------------


class TestReviewerUsesEnumStatus:
    """Verify reviewer.py uses ReviewerStatus enum, not a raw string."""

    def test_no_raw_fixing_review_findings_string(self) -> None:
        import pathlib

        src = (pathlib.Path(__file__).parent.parent / "src" / "reviewer.py").read_text()
        # The old raw string must be replaced by the enum reference everywhere
        assert '"fixing_review_findings"' not in src
