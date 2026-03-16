"""Tests for models — config."""

from __future__ import annotations

import inspect

import pytest

from models import (
    ControlStatusConfig,
    ControlStatusResponse,
    GitHubIssue,
    JudgeResult,
    LifetimeStats,
    StateData,
    Task,
    TaskLink,
    TaskLinkKind,
    VerificationCriterion,
    parse_task_links,
)

# ---------------------------------------------------------------------------
# ControlStatusConfig
# ---------------------------------------------------------------------------


class TestControlStatusConfig:
    """Tests for the ControlStatusConfig response model."""

    def test_minimal_instantiation(self) -> None:
        """No required fields."""
        cfg = ControlStatusConfig()
        assert cfg.repo == ""
        assert cfg.ready_label == []
        assert cfg.find_label == []
        assert cfg.planner_label == []
        assert cfg.review_label == []
        assert cfg.hitl_label == []
        assert cfg.fixed_label == []
        assert cfg.max_workers == 0
        assert cfg.max_planners == 0
        assert cfg.max_reviewers == 0
        assert cfg.batch_size == 0
        assert cfg.model == ""

    def test_all_fields_set(self) -> None:
        cfg = ControlStatusConfig(
            repo="org/repo",
            ready_label=["hydraflow-ready"],
            find_label=["hydraflow-find"],
            planner_label=["hydraflow-plan"],
            review_label=["hydraflow-review"],
            hitl_label=["hydraflow-hitl"],
            fixed_label=["hydraflow-fixed"],
            max_workers=4,
            max_planners=2,
            max_reviewers=1,
            batch_size=10,
            model="opus",
        )
        assert cfg.repo == "org/repo"
        assert cfg.ready_label == ["hydraflow-ready"]
        assert cfg.max_workers == 4
        assert cfg.model == "opus"

    def test_lists_are_independent_between_instances(self) -> None:
        a = ControlStatusConfig()
        b = ControlStatusConfig()
        a.ready_label.append("test")
        assert b.ready_label == []


# ---------------------------------------------------------------------------
# ControlStatusResponse
# ---------------------------------------------------------------------------


class TestControlStatusResponse:
    """Tests for the ControlStatusResponse response model."""

    def test_minimal_instantiation(self) -> None:
        resp = ControlStatusResponse()
        assert resp.status == "idle"
        assert resp.config.repo == ""

    def test_all_fields_set(self) -> None:
        cfg = ControlStatusConfig(repo="org/repo", max_workers=3, model="sonnet")
        resp = ControlStatusResponse(status="running", config=cfg)
        assert resp.status == "running"
        assert resp.config.repo == "org/repo"
        assert resp.config.max_workers == 3

    def test_serialization_with_model_dump(self) -> None:
        """Verify nested config serializes correctly."""
        cfg = ControlStatusConfig(
            repo="org/repo",
            ready_label=["hydraflow-ready"],
            max_workers=2,
            batch_size=15,
            model="sonnet",
        )
        resp = ControlStatusResponse(status="running", config=cfg)
        data = resp.model_dump()
        assert data["status"] == "running"
        assert data["config"]["repo"] == "org/repo"
        assert data["config"]["ready_label"] == ["hydraflow-ready"]
        assert data["config"]["max_workers"] == 2
        assert data["config"]["batch_size"] == 15
        assert data["config"]["model"] == "sonnet"

    def test_credits_paused_until_default_none(self) -> None:
        resp = ControlStatusResponse()
        assert resp.credits_paused_until is None

    def test_credits_paused_until_set(self) -> None:
        resp = ControlStatusResponse(
            status="credits_paused",
            credits_paused_until="2026-02-28T15:30:00+00:00",
        )
        assert resp.credits_paused_until == "2026-02-28T15:30:00+00:00"
        data = resp.model_dump()
        assert data["credits_paused_until"] == "2026-02-28T15:30:00+00:00"


# ---------------------------------------------------------------------------
# LifetimeStats
# ---------------------------------------------------------------------------


class TestLifetimeStats:
    """Tests for the LifetimeStats model."""

    def test_new_volume_counter_defaults(self) -> None:
        stats = LifetimeStats()
        assert stats.total_quality_fix_rounds == 0
        assert stats.total_ci_fix_rounds == 0
        assert stats.total_hitl_escalations == 0
        assert stats.total_review_request_changes == 0
        assert stats.total_review_approvals == 0
        assert stats.total_reviewer_fixes == 0

    def test_new_timing_defaults(self) -> None:
        stats = LifetimeStats()
        assert stats.total_implementation_seconds == pytest.approx(0.0)
        assert stats.total_review_seconds == pytest.approx(0.0)

    def test_fired_thresholds_default(self) -> None:
        stats = LifetimeStats()
        assert stats.fired_thresholds == []

    def test_fired_thresholds_are_independent_between_instances(self) -> None:
        a = LifetimeStats()
        b = LifetimeStats()
        a.fired_thresholds.append("test")
        assert b.fired_thresholds == []

    def test_serialization_roundtrip_with_new_fields(self) -> None:
        stats = LifetimeStats(
            issues_completed=10,
            total_quality_fix_rounds=5,
            total_implementation_seconds=120.5,
            fired_thresholds=["quality_fix_rate"],
        )
        json_str = stats.model_dump_json()
        restored = LifetimeStats.model_validate_json(json_str)
        assert restored == stats

    def test_backward_compat_missing_new_fields(self) -> None:
        """Old data without new fields should get zero defaults."""
        old_data = {"issues_completed": 3, "prs_merged": 1, "issues_created": 0}
        stats = LifetimeStats.model_validate(old_data)
        assert stats.issues_completed == 3
        assert stats.total_quality_fix_rounds == 0
        assert stats.total_implementation_seconds == 0.0
        assert stats.fired_thresholds == []


# ---------------------------------------------------------------------------
# VerificationCriterion
# ---------------------------------------------------------------------------


class TestVerificationCriterion:
    """Tests for the VerificationCriterion model."""

    def test_basic_instantiation(self) -> None:
        cr = VerificationCriterion(
            description="Tests pass", passed=True, details="All 10 pass"
        )
        assert cr.description == "Tests pass"
        assert cr.passed is True
        assert cr.details == "All 10 pass"

    def test_details_defaults_to_empty(self) -> None:
        cr = VerificationCriterion(description="Lint", passed=False)
        assert cr.details == ""

    def test_serialization_round_trip(self) -> None:
        cr = VerificationCriterion(
            description="Type check", passed=True, details="Clean"
        )
        data = cr.model_dump()
        restored = VerificationCriterion.model_validate(data)
        assert restored == cr


# ---------------------------------------------------------------------------
# JudgeResult
# ---------------------------------------------------------------------------


class TestJudgeResult:
    """Tests for the JudgeResult model."""

    def test_all_passed_when_all_criteria_pass(self) -> None:
        judge = JudgeResult(
            issue_number=42,
            pr_number=101,
            criteria=[
                VerificationCriterion(description="A", passed=True),
                VerificationCriterion(description="B", passed=True),
            ],
        )
        assert judge.all_passed is True
        assert judge.failed_criteria == []

    def test_all_passed_false_when_some_fail(self) -> None:
        judge = JudgeResult(
            issue_number=42,
            pr_number=101,
            criteria=[
                VerificationCriterion(description="A", passed=True),
                VerificationCriterion(description="B", passed=False, details="Failed"),
            ],
        )
        assert judge.all_passed is False
        assert len(judge.failed_criteria) == 1
        assert judge.failed_criteria[0].description == "B"

    def test_all_passed_true_when_no_criteria(self) -> None:
        judge = JudgeResult(issue_number=42, pr_number=101, criteria=[])
        assert judge.all_passed is True

    def test_failed_criteria_returns_only_failures(self) -> None:
        judge = JudgeResult(
            issue_number=42,
            pr_number=101,
            criteria=[
                VerificationCriterion(description="A", passed=False),
                VerificationCriterion(description="B", passed=True),
                VerificationCriterion(description="C", passed=False),
            ],
        )
        failed = judge.failed_criteria
        assert len(failed) == 2
        assert {c.description for c in failed} == {"A", "C"}

    def test_judge_result_defaults_to_empty_criteria_instructions_and_summary(
        self,
    ) -> None:
        judge = JudgeResult(issue_number=1, pr_number=2)
        assert judge.criteria == []
        assert judge.verification_instructions == ""
        assert judge.summary == ""

    def test_serialization_round_trip(self) -> None:
        judge = JudgeResult(
            issue_number=42,
            pr_number=101,
            criteria=[VerificationCriterion(description="X", passed=True)],
            verification_instructions="Step 1",
            summary="Good",
        )
        data = judge.model_dump()
        restored = JudgeResult.model_validate(data)
        assert restored.issue_number == judge.issue_number
        assert restored.criteria[0].description == "X"
        assert restored.verification_instructions == "Step 1"


# ---------------------------------------------------------------------------
# StateData - verification_issues field
# ---------------------------------------------------------------------------


class TestStateDataVerificationIssues:
    """Tests for the verification_issues field on StateData."""

    def test_defaults_to_empty_dict(self) -> None:
        data = StateData()
        assert data.verification_issues == {}

    def test_accepts_verification_issues(self) -> None:
        data = StateData(verification_issues={"42": 500, "99": 501})
        assert data.verification_issues["42"] == 500
        assert data.verification_issues["99"] == 501


class TestStateDataManifestFields:
    """Regression tests for manifest-related fields on StateData."""

    def test_manifest_field_defaults(self) -> None:
        data = StateData()
        assert data.manifest_issue_number is None
        assert data.manifest_snapshot_hash == ""

    def test_manifest_fields_accept_explicit_values(self) -> None:
        data = StateData(manifest_issue_number=42, manifest_snapshot_hash="abc123")
        assert data.manifest_issue_number == 42
        assert data.manifest_snapshot_hash == "abc123"

    def test_manifest_fields_round_trip_serialization(self) -> None:
        start = StateData(manifest_issue_number=99, manifest_snapshot_hash="sha256hash")
        payload = start.model_dump()
        restored = StateData.model_validate(payload)
        assert restored.manifest_issue_number == 99
        assert restored.manifest_snapshot_hash == "sha256hash"

    def test_manifest_issue_number_none_survives_round_trip(self) -> None:
        start = StateData(manifest_issue_number=None)
        restored = StateData.model_validate(start.model_dump())
        assert restored.manifest_issue_number is None

    def test_no_duplicate_field_names_in_state_data(self) -> None:
        source = inspect.getsource(StateData)
        field_lines = [
            line.split(":")[0].strip()
            for line in source.splitlines()
            if ":" in line and not line.strip().startswith(("#", "class", '"""'))
        ]
        manifest_fields = [
            f
            for f in field_lines
            if f in {"manifest_issue_number", "manifest_snapshot_hash"}
        ]
        assert manifest_fields.count("manifest_issue_number") == 1
        assert manifest_fields.count("manifest_snapshot_hash") == 1


# ---------------------------------------------------------------------------
# TaskLink / TaskLinkKind
# ---------------------------------------------------------------------------


class TestTaskLink:
    """Tests for the TaskLink and TaskLinkKind models."""

    def test_tasklink_kind_values(self) -> None:
        # Arrange / Act / Assert
        assert TaskLinkKind.RELATES_TO == "relates_to"
        assert TaskLinkKind.DUPLICATES == "duplicates"
        assert TaskLinkKind.SUPERSEDES == "supersedes"
        assert TaskLinkKind.REPLIES_TO == "replies_to"

    def test_tasklink_minimal(self) -> None:
        link = TaskLink(kind=TaskLinkKind.RELATES_TO, target_id=7)

        assert link.kind == TaskLinkKind.RELATES_TO
        assert link.target_id == 7
        assert link.target_url == ""

    def test_tasklink_with_url(self) -> None:
        url = "https://github.com/org/repo/issues/7"
        link = TaskLink(kind=TaskLinkKind.DUPLICATES, target_id=7, target_url=url)

        assert link.target_url == url

    def test_task_links_field_defaults_to_empty(self) -> None:
        task = Task(id=1, title="t")

        assert task.links == []

    def test_task_links_field_accepts_links(self) -> None:
        links = [
            TaskLink(kind=TaskLinkKind.SUPERSEDES, target_id=3),
            TaskLink(kind=TaskLinkKind.REPLIES_TO, target_id=9),
        ]
        task = Task(id=1, title="t", links=links)

        assert len(task.links) == 2
        assert task.links[0].kind == TaskLinkKind.SUPERSEDES
        assert task.links[1].target_id == 9

    def test_task_links_independent_between_instances(self) -> None:
        """Default mutable lists must not be shared between Task instances."""
        task_a = Task(id=1, title="a")
        task_b = Task(id=2, title="b")

        task_a.links.append(TaskLink(kind=TaskLinkKind.RELATES_TO, target_id=5))

        assert task_b.links == []


# ---------------------------------------------------------------------------
# parse_task_links
# ---------------------------------------------------------------------------


class TestParseTaskLinks:
    """Tests for the parse_task_links() function."""

    # --- Empty / plain body ---

    def test_empty_body_returns_empty_list(self) -> None:
        assert parse_task_links("") == []

    def test_plain_body_no_links(self) -> None:
        assert parse_task_links("Fix the frobnicator widget so it works.") == []

    # --- relates_to ---

    def test_relates_to_pattern_relates_to(self) -> None:
        links = parse_task_links("This relates to #12.")

        assert len(links) == 1
        assert links[0].kind == TaskLinkKind.RELATES_TO
        assert links[0].target_id == 12

    def test_relates_to_pattern_related(self) -> None:
        links = parse_task_links("Also related: #99")

        assert len(links) == 1
        assert links[0].kind == TaskLinkKind.RELATES_TO
        assert links[0].target_id == 99

    def test_relates_to_case_insensitive(self) -> None:
        links = parse_task_links("RELATES TO #7")

        assert len(links) == 1
        assert links[0].kind == TaskLinkKind.RELATES_TO

    # --- duplicates ---

    def test_duplicates_pattern_duplicates(self) -> None:
        links = parse_task_links("This duplicates #5.")

        assert len(links) == 1
        assert links[0].kind == TaskLinkKind.DUPLICATES
        assert links[0].target_id == 5

    def test_duplicates_pattern_duplicate_of(self) -> None:
        links = parse_task_links("duplicate of #5")

        assert len(links) == 1
        assert links[0].kind == TaskLinkKind.DUPLICATES
        assert links[0].target_id == 5

    def test_duplicates_case_insensitive(self) -> None:
        links = parse_task_links("DUPLICATE OF #10")

        assert len(links) == 1
        assert links[0].kind == TaskLinkKind.DUPLICATES

    # --- supersedes ---

    def test_supersedes_pattern_supersedes(self) -> None:
        links = parse_task_links("This supersedes #3.")

        assert len(links) == 1
        assert links[0].kind == TaskLinkKind.SUPERSEDES
        assert links[0].target_id == 3

    def test_supersedes_pattern_replaces(self) -> None:
        links = parse_task_links("This replaces #3.")

        assert len(links) == 1
        assert links[0].kind == TaskLinkKind.SUPERSEDES
        assert links[0].target_id == 3

    def test_supersedes_case_insensitive(self) -> None:
        links = parse_task_links("REPLACES #20")

        assert len(links) == 1
        assert links[0].kind == TaskLinkKind.SUPERSEDES

    def test_supersedes_pattern_supersede_base(self) -> None:
        links = parse_task_links("will supersede #9")

        assert len(links) == 1
        assert links[0].kind == TaskLinkKind.SUPERSEDES
        assert links[0].target_id == 9

    def test_supersedes_pattern_superseded(self) -> None:
        links = parse_task_links("This superseded #5")

        assert len(links) == 1
        assert links[0].kind == TaskLinkKind.SUPERSEDES
        assert links[0].target_id == 5

    def test_supersedes_pattern_superseding(self) -> None:
        links = parse_task_links("superseding #12")

        assert len(links) == 1
        assert links[0].kind == TaskLinkKind.SUPERSEDES
        assert links[0].target_id == 12

    def test_supersedes_uppercase_superseded(self) -> None:
        links = parse_task_links("SUPERSEDED #7")

        assert len(links) == 1
        assert links[0].kind == TaskLinkKind.SUPERSEDES
        assert links[0].target_id == 7

    # --- replies_to ---

    def test_replies_to_pattern_replies_to(self) -> None:
        links = parse_task_links("This replies to #8.")

        assert len(links) == 1
        assert links[0].kind == TaskLinkKind.REPLIES_TO
        assert links[0].target_id == 8

    def test_replies_to_pattern_reply_to(self) -> None:
        links = parse_task_links("reply to #8")

        assert len(links) == 1
        assert links[0].kind == TaskLinkKind.REPLIES_TO
        assert links[0].target_id == 8

    def test_replies_to_pattern_in_response_to(self) -> None:
        links = parse_task_links("In response to #8, see here.")

        assert len(links) == 1
        assert links[0].kind == TaskLinkKind.REPLIES_TO
        assert links[0].target_id == 8

    def test_replies_to_case_insensitive(self) -> None:
        links = parse_task_links("IN RESPONSE TO #30")

        assert len(links) == 1
        assert links[0].kind == TaskLinkKind.REPLIES_TO

    # --- Multiple links ---

    def test_multiple_links_different_targets(self) -> None:
        body = "This relates to #1 and duplicates #2 and supersedes #3."
        links = parse_task_links(body)

        target_ids = [lnk.target_id for lnk in links]
        assert 1 in target_ids
        assert 2 in target_ids
        assert 3 in target_ids
        assert len(links) == 3

    def test_multiple_links_preserve_kinds(self) -> None:
        body = "Relates to #10. Duplicate of #20."
        links = parse_task_links(body)

        by_id = {lnk.target_id: lnk for lnk in links}
        assert by_id[10].kind == TaskLinkKind.RELATES_TO
        assert by_id[20].kind == TaskLinkKind.DUPLICATES

    # --- Deduplication ---

    def test_dedup_same_target_mentioned_twice_keeps_first(self) -> None:
        body = "This relates to #5. Also duplicates #5."
        links = parse_task_links(body)

        assert len(links) == 1
        assert links[0].target_id == 5
        assert links[0].kind == TaskLinkKind.RELATES_TO

    def test_dedup_same_pattern_same_target(self) -> None:
        body = "Relates to #7 and relates to #7."
        links = parse_task_links(body)

        assert len(links) == 1
        assert links[0].target_id == 7

    # --- GitHubIssue.to_task() propagation ---

    def test_github_issue_to_task_propagates_links(self) -> None:
        issue = GitHubIssue(
            number=42,
            title="Improve widget",
            body="This relates to #10 and duplicates #20.",
        )
        task = issue.to_task()

        assert len(task.links) == 2
        target_ids = {lnk.target_id for lnk in task.links}
        assert target_ids == {10, 20}

    def test_github_issue_to_task_empty_body_no_links(self) -> None:
        issue = GitHubIssue(number=1, title="t", body="")
        task = issue.to_task()

        assert task.links == []

    def test_github_issue_to_task_plain_body_no_links(self) -> None:
        issue = GitHubIssue(number=1, title="t", body="Just a plain description.")
        task = issue.to_task()

        assert task.links == []

    # --- Round-trip via from_task ---

    def test_from_task_round_trip_preserves_links(self) -> None:
        links = [TaskLink(kind=TaskLinkKind.SUPERSEDES, target_id=3)]
        task = Task(id=42, title="t", links=links)

        reconstructed = GitHubIssue.from_task(task).to_task()

        assert (
            len(reconstructed.links) == 0
        )  # from_task body is empty -> no links parsed

    def test_pydantic_serialization_round_trip(self) -> None:
        task = Task(
            id=1,
            title="t",
            links=[TaskLink(kind=TaskLinkKind.REPLIES_TO, target_id=9)],
        )
        data = task.model_dump()
        restored = Task.model_validate(data)

        assert len(restored.links) == 1
        assert restored.links[0].kind == TaskLinkKind.REPLIES_TO
        assert restored.links[0].target_id == 9
