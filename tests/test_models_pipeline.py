"""Tests for models — pipeline."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from models import (
    HITLItem,
    LifetimeStats,
    PipelineStats,
    PlanResult,
    QueueStats,
    StageStats,
    StateData,
    ThroughputStats,
    TriageResult,
    VisualEvidence,
    VisualEvidenceItem,
)
from tests.conftest import PlanResultFactory

# ---------------------------------------------------------------------------
# IssueOutcomeType, IssueOutcome, HookFailureRecord
# ---------------------------------------------------------------------------


class TestIssueOutcomeModels:
    def test_issue_outcome_type_values(self) -> None:
        from models import IssueOutcomeType

        assert IssueOutcomeType.MERGED == "merged"
        assert IssueOutcomeType.ALREADY_SATISFIED == "already_satisfied"
        assert IssueOutcomeType.HITL_CLOSED == "hitl_closed"
        assert IssueOutcomeType.HITL_SKIPPED == "hitl_skipped"
        assert IssueOutcomeType.HITL_APPROVED == "hitl_approved"
        assert IssueOutcomeType.FAILED == "failed"
        assert IssueOutcomeType.MANUAL_CLOSE == "manual_close"

    def test_issue_outcome_creation(self) -> None:
        from models import IssueOutcome, IssueOutcomeType

        outcome = IssueOutcome(
            outcome=IssueOutcomeType.MERGED,
            reason="PR approved and merged",
            closed_at="2024-01-15T10:00:00Z",
            pr_number=42,
            phase="review",
        )
        assert outcome.outcome == IssueOutcomeType.MERGED
        assert outcome.reason == "PR approved and merged"
        assert outcome.pr_number == 42
        assert outcome.phase == "review"

    def test_issue_outcome_without_pr_number(self) -> None:
        from models import IssueOutcome, IssueOutcomeType

        outcome = IssueOutcome(
            outcome=IssueOutcomeType.HITL_CLOSED,
            reason="Duplicate issue",
            closed_at="2024-01-15T10:00:00Z",
            phase="hitl",
        )
        assert outcome.pr_number is None

    def test_hook_failure_record_creation(self) -> None:
        from models import HookFailureRecord

        record = HookFailureRecord(
            hook_name="AC generation",
            error="Connection timeout",
            timestamp="2024-01-15T10:00:00Z",
        )
        assert record.hook_name == "AC generation"
        assert record.error == "Connection timeout"

    def test_hitl_close_request_requires_reason(self) -> None:
        from models import HITLCloseRequest

        with pytest.raises(ValidationError):
            HITLCloseRequest(reason="")

    def test_hitl_close_request_accepts_valid_reason(self) -> None:
        from models import HITLCloseRequest

        req = HITLCloseRequest(reason="Duplicate of #123")
        assert req.reason == "Duplicate of #123"

    def test_hitl_skip_request_requires_reason(self) -> None:
        from models import HITLSkipRequest

        with pytest.raises(ValidationError):
            HITLSkipRequest(reason="")

    def test_hitl_skip_request_accepts_valid_reason(self) -> None:
        from models import HITLSkipRequest

        req = HITLSkipRequest(reason="Not actionable")
        assert req.reason == "Not actionable"

    def test_issue_history_entry_outcome_defaults_to_none(self) -> None:
        from models import IssueHistoryEntry

        entry = IssueHistoryEntry(issue_number=42)
        assert entry.outcome is None

    def test_issue_history_entry_outcome_can_be_set(self) -> None:
        from models import IssueHistoryEntry, IssueOutcome, IssueOutcomeType

        outcome = IssueOutcome(
            outcome=IssueOutcomeType.MERGED,
            reason="merged",
            closed_at="2024-01-15T10:00:00Z",
            pr_number=1,
            phase="review",
        )
        entry = IssueHistoryEntry(issue_number=42, outcome=outcome)
        assert entry.outcome is not None
        assert entry.outcome.outcome == IssueOutcomeType.MERGED

    def test_state_data_new_fields_default(self) -> None:
        data = StateData()
        assert data.issue_outcomes == {}
        assert data.hook_failures == {}

    def test_issue_history_link_defaults(self) -> None:
        from models import IssueHistoryLink, TaskLinkKind

        link = IssueHistoryLink(target_id=42)
        assert link.target_id == 42
        assert link.kind == TaskLinkKind.RELATES_TO
        assert link.target_url is None

    def test_issue_history_link_with_kind(self) -> None:
        from models import IssueHistoryLink, TaskLinkKind

        link = IssueHistoryLink(
            target_id=10,
            kind=TaskLinkKind.DUPLICATES,
            target_url="https://github.com/org/repo/issues/10",
        )
        assert link.target_id == 10
        assert link.kind == TaskLinkKind.DUPLICATES
        assert link.target_url == "https://github.com/org/repo/issues/10"

    def test_issue_history_link_serialization_round_trip(self) -> None:
        from models import IssueHistoryLink, TaskLinkKind

        link = IssueHistoryLink(target_id=5, kind=TaskLinkKind.SUPERSEDES)
        data = link.model_dump()
        assert data == {"target_id": 5, "kind": "supersedes", "target_url": None}
        restored = IssueHistoryLink.model_validate(data)
        assert restored == link
        assert restored.kind == TaskLinkKind.SUPERSEDES

    def test_issue_history_entry_linked_issues_accepts_history_links(self) -> None:
        from models import IssueHistoryEntry, IssueHistoryLink, TaskLinkKind

        links = [
            IssueHistoryLink(target_id=1, kind=TaskLinkKind.RELATES_TO),
            IssueHistoryLink(target_id=2, kind=TaskLinkKind.DUPLICATES),
        ]
        entry = IssueHistoryEntry(issue_number=42, linked_issues=links)
        assert len(entry.linked_issues) == 2
        assert entry.linked_issues[0].target_id == 1
        assert entry.linked_issues[1].kind == TaskLinkKind.DUPLICATES

    def test_issue_history_entry_linked_issues_defaults_empty(self) -> None:
        from models import IssueHistoryEntry

        entry = IssueHistoryEntry(issue_number=42)
        assert entry.linked_issues == []

    def test_issue_history_entry_crate_fields_default(self) -> None:
        from models import IssueHistoryEntry

        entry = IssueHistoryEntry(issue_number=42)
        assert entry.crate_number is None
        assert entry.crate_title == ""

    def test_issue_history_entry_crate_fields_can_be_set(self) -> None:
        from models import IssueHistoryEntry

        entry = IssueHistoryEntry(
            issue_number=42, crate_number=3, crate_title="Sprint 1"
        )
        assert entry.crate_number == 3
        assert entry.crate_title == "Sprint 1"

    def test_lifetime_stats_outcome_counters_default_zero(self) -> None:
        stats = LifetimeStats()
        assert stats.total_outcomes_merged == 0
        assert stats.total_outcomes_already_satisfied == 0
        assert stats.total_outcomes_hitl_closed == 0
        assert stats.total_outcomes_hitl_skipped == 0
        assert stats.total_outcomes_failed == 0


class TestStageStats:
    def test_defaults_all_zero(self) -> None:
        s = StageStats()
        assert s.queued == 0
        assert s.active == 0
        assert s.completed_session == 0
        assert s.completed_lifetime == 0
        assert s.worker_count == 0
        assert s.worker_cap is None

    def test_with_values(self) -> None:
        s = StageStats(
            queued=3,
            active=2,
            completed_session=10,
            completed_lifetime=50,
            worker_count=2,
            worker_cap=4,
        )
        assert s.queued == 3
        assert s.worker_cap == 4


class TestThroughputStats:
    def test_defaults_all_zero(self) -> None:
        t = ThroughputStats()
        assert t.triage == 0.0
        assert t.plan == 0.0
        assert t.implement == 0.0
        assert t.review == 0.0
        assert t.hitl == 0.0

    def test_with_values(self) -> None:
        t = ThroughputStats(triage=1.5, implement=3.0)
        assert t.triage == 1.5
        assert t.implement == 3.0


class TestPipelineStats:
    def test_minimal_creation(self) -> None:
        ps = PipelineStats(timestamp="2026-02-28T12:00:00+00:00")
        assert ps.timestamp == "2026-02-28T12:00:00+00:00"
        assert ps.stages == {}
        assert ps.uptime_seconds == 0.0

    def test_full_creation(self) -> None:
        ps = PipelineStats(
            timestamp="2026-02-28T12:00:00+00:00",
            stages={
                "triage": StageStats(queued=1, active=1, worker_count=1, worker_cap=1),
                "plan": StageStats(queued=2),
                "implement": StageStats(active=3, worker_count=2, worker_cap=2),
                "review": StageStats(completed_session=5, completed_lifetime=20),
                "hitl": StageStats(),
                "merged": StageStats(completed_session=4, completed_lifetime=15),
            },
            queue=QueueStats(queue_depth={"find": 1, "plan": 2}),
            throughput=ThroughputStats(triage=2.5, implement=1.0),
            uptime_seconds=3600.0,
        )
        assert len(ps.stages) == 6
        assert ps.stages["triage"].queued == 1
        assert ps.stages["merged"].completed_lifetime == 15
        assert ps.throughput.triage == 2.5
        assert ps.uptime_seconds == 3600.0

    def test_json_serializable(self) -> None:
        ps = PipelineStats(
            timestamp="2026-02-28T12:00:00+00:00",
            stages={"triage": StageStats(queued=1)},
            throughput=ThroughputStats(triage=1.0),
            uptime_seconds=60.0,
        )
        data = ps.model_dump()
        assert isinstance(data, dict)
        assert data["stages"]["triage"]["queued"] == 1
        assert data["throughput"]["triage"] == 1.0
        # Round-trip through JSON
        import json

        json_str = json.dumps(data)
        restored = PipelineStats.model_validate_json(json_str)
        assert restored.stages["triage"].queued == 1


# ---------------------------------------------------------------------------
# VisualEvidenceItem
# ---------------------------------------------------------------------------


class TestVisualEvidenceItem:
    def test_minimal_instantiation(self) -> None:
        item = VisualEvidenceItem(screen_name="login", status="pass")
        assert item.screen_name == "login"
        assert item.diff_percent == 0.0
        assert item.status == "pass"

    def test_status_is_required(self) -> None:
        with pytest.raises(ValidationError):
            VisualEvidenceItem(screen_name="login")

    def test_all_fields(self) -> None:
        item = VisualEvidenceItem(
            screen_name="dashboard",
            diff_percent=12.5,
            baseline_url="https://example.com/baseline.png",
            actual_url="https://example.com/actual.png",
            diff_url="https://example.com/diff.png",
            status="warn",
        )
        assert item.screen_name == "dashboard"
        assert item.diff_percent == 12.5
        assert item.status == "warn"
        assert str(item.baseline_url) == "https://example.com/baseline.png"

    def test_status_pass(self) -> None:
        item = VisualEvidenceItem(screen_name="home", status="pass")
        assert item.status == "pass"


# ---------------------------------------------------------------------------
# VisualEvidence
# ---------------------------------------------------------------------------


class TestVisualEvidence:
    def test_visual_evidence_has_empty_defaults(self) -> None:
        ev = VisualEvidence()
        assert ev.items == []
        assert ev.summary == ""
        assert ev.attempt == 1

    def test_with_items(self) -> None:
        ev = VisualEvidence(
            items=[
                VisualEvidenceItem(
                    screen_name="login", diff_percent=5.0, status="warn"
                ),
                VisualEvidenceItem(
                    screen_name="dashboard", diff_percent=20.0, status="fail"
                ),
            ],
            summary="2 screens failed visual check",
            run_url="https://ci.example.com/run/42",
            attempt=2,
        )
        assert len(ev.items) == 2
        assert ev.items[0].screen_name == "login"
        assert ev.items[1].status == "fail"
        assert ev.attempt == 2

    def test_model_dump_roundtrip(self) -> None:
        ev = VisualEvidence(
            items=[
                VisualEvidenceItem(screen_name="page", diff_percent=3.0, status="pass")
            ],
            summary="All checks passed",
        )
        data = ev.model_dump()
        restored = VisualEvidence.model_validate(data)
        assert restored.items[0].screen_name == "page"
        assert restored.summary == "All checks passed"


# ---------------------------------------------------------------------------
# HITLItem — visual_evidence field
# ---------------------------------------------------------------------------


class TestHITLItemVisualEvidence:
    def test_default_is_none(self) -> None:
        item = HITLItem(issue=1)
        assert item.visual_evidence is None

    def test_with_visual_evidence(self) -> None:
        ev = VisualEvidence(
            items=[
                VisualEvidenceItem(screen_name="home", diff_percent=10.0, status="fail")
            ],
            summary="1 screen failed",
        )
        item = HITLItem(issue=1, visual_evidence=ev)
        assert item.visual_evidence is not None
        assert item.visual_evidence.items[0].screen_name == "home"

    def test_model_dump_includes_visual_evidence(self) -> None:
        ev = VisualEvidence(
            items=[
                VisualEvidenceItem(screen_name="nav", diff_percent=2.0, status="warn")
            ],
        )
        item = HITLItem(issue=1, visual_evidence=ev)
        data = item.model_dump()
        assert data["visual_evidence"]["items"][0]["screen_name"] == "nav"

    def test_model_dump_excludes_none_visual_evidence(self) -> None:
        item = HITLItem(issue=1)
        data = item.model_dump()
        assert data["visual_evidence"] is None


# ---------------------------------------------------------------------------
# Field validators and descriptions (issue #2402)
# ---------------------------------------------------------------------------


class TestTriageResultValidators:
    def test_complexity_score_accepts_valid_range(self) -> None:
        for score in (0, 5, 10):
            result = TriageResult(issue_number=1, complexity_score=score)
            assert result.complexity_score == score

    def test_complexity_score_rejects_negative(self) -> None:
        with pytest.raises(ValidationError, match="complexity_score"):
            TriageResult(issue_number=1, complexity_score=-1)

    def test_complexity_score_rejects_above_ten(self) -> None:
        with pytest.raises(ValidationError, match="complexity_score"):
            TriageResult(issue_number=1, complexity_score=11)

    def test_field_descriptions_present(self) -> None:
        fields = TriageResult.model_fields
        for name, info in fields.items():
            assert info.description, f"TriageResult.{name} missing description"


class TestPlanResultValidators:
    def test_duration_seconds_rejects_negative(self) -> None:
        with pytest.raises(ValidationError, match="duration_seconds"):
            PlanResultFactory.create(
                use_defaults=True, issue_number=1, duration_seconds=-1.0
            )

    def test_duration_seconds_accepts_zero(self) -> None:
        result = PlanResultFactory.create(
            use_defaults=True, issue_number=1, duration_seconds=0.0
        )
        assert result.duration_seconds == pytest.approx(0.0)

    def test_field_descriptions_present(self) -> None:
        fields = PlanResult.model_fields
        for name, info in fields.items():
            assert info.description, f"PlanResult.{name} missing description"
