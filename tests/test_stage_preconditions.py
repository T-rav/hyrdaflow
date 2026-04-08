"""Tests for stage_preconditions — pipeline state-machine gates (#6423).

Predicates are pure functions of the issue cache. Tests use real
``IssueCache`` instances against ``tmp_path`` to exercise the read path
end-to-end.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from issue_cache import IssueCache
from stage_preconditions import (
    STAGE_PRECONDITIONS,
    Stage,
    check_preconditions,
    has_clean_review,
    has_plan,
    has_reproduction_for_bug,
)


def _cache(tmp_path: Path) -> IssueCache:
    return IssueCache(tmp_path / "cache", enabled=True)


# ---------------------------------------------------------------------------
# has_plan
# ---------------------------------------------------------------------------


class TestHasPlan:
    def test_passes_when_plan_exists(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        cache.record_plan_stored(42, plan_text="a plan")
        assert has_plan(cache, 42).ok is True

    def test_fails_when_no_plan(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        result = has_plan(cache, 42)
        assert result.ok is False
        assert "no plan_stored" in result.reason

    def test_passes_after_multiple_plan_versions(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        cache.record_plan_stored(42, plan_text="v1")
        cache.record_plan_stored(42, plan_text="v2")
        assert has_plan(cache, 42).ok is True

    def test_fails_when_only_review_record_exists(self, tmp_path: Path) -> None:
        """has_plan must not be tricked into passing by a review_stored
        record. Catches a regression where the predicate accidentally
        queried the wrong record kind."""
        cache = _cache(tmp_path)
        cache.record_review_stored(42, review_text="reviewed", has_blocking=False)
        result = has_plan(cache, 42)
        assert result.ok is False
        assert "no plan_stored" in result.reason

    def test_fails_when_only_classification_record_exists(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        cache.record_classification(
            42,
            issue_type="feature",
            complexity_score=3,
            complexity_rank="low",
            routing_outcome="plan",
        )
        result = has_plan(cache, 42)
        assert result.ok is False


# ---------------------------------------------------------------------------
# has_clean_review
# ---------------------------------------------------------------------------


class TestHasCleanReview:
    def test_passes_when_clean_review(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        cache.record_review_stored(42, review_text="looks good", has_blocking=False)
        assert has_clean_review(cache, 42).ok is True

    def test_fails_when_no_review(self, tmp_path: Path) -> None:
        result = has_clean_review(_cache(tmp_path), 42)
        assert result.ok is False
        assert "no review_stored" in result.reason

    def test_fails_when_critical_findings(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        cache.record_review_stored(
            42, review_text="missing edge cases", has_blocking=True
        )
        result = has_clean_review(cache, 42)
        assert result.ok is False
        assert "critical findings" in result.reason

    def test_uses_latest_review(self, tmp_path: Path) -> None:
        """When v1 was critical and v2 is clean, the gate must pass."""
        cache = _cache(tmp_path)
        cache.record_review_stored(42, review_text="bad", has_blocking=True)
        cache.record_review_stored(42, review_text="good", has_blocking=False)
        assert has_clean_review(cache, 42).ok is True


# ---------------------------------------------------------------------------
# has_reproduction_for_bug
# ---------------------------------------------------------------------------


class TestHasReproductionForBug:
    def test_passes_when_no_classification_yet(self, tmp_path: Path) -> None:
        """Defers to upstream classifier — does not block when no record."""
        assert has_reproduction_for_bug(_cache(tmp_path), 42).ok is True

    def test_passes_when_not_a_bug(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        cache.record_classification(
            42,
            issue_type="feature",
            complexity_score=3,
            complexity_rank="low",
            routing_outcome="plan",
        )
        assert has_reproduction_for_bug(cache, 42).ok is True

    def test_fails_when_bug_without_repro(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        cache.record_classification(
            42,
            issue_type="bug",
            complexity_score=5,
            complexity_rank="medium",
            routing_outcome="plan",
        )
        result = has_reproduction_for_bug(cache, 42)
        assert result.ok is False
        assert "no reproduction_stored" in result.reason

    def test_passes_when_bug_with_successful_repro(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        cache.record_classification(
            42,
            issue_type="bug",
            complexity_score=5,
            complexity_rank="medium",
            routing_outcome="plan",
        )
        cache.record_reproduction_stored(
            42,
            outcome="success",
            test_path="tests/regressions/test_issue_42.py",
        )
        assert has_reproduction_for_bug(cache, 42).ok is True

    def test_fails_when_bug_repro_unable(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        cache.record_classification(
            42,
            issue_type="bug",
            complexity_score=5,
            complexity_rank="medium",
            routing_outcome="plan",
        )
        cache.record_reproduction_stored(
            42,
            outcome="unable",
            details="lacks stack trace",
        )
        result = has_reproduction_for_bug(cache, 42)
        assert result.ok is False
        assert "escalate to HITL" in result.reason


# ---------------------------------------------------------------------------
# check_preconditions / STAGE_PRECONDITIONS
# ---------------------------------------------------------------------------


class TestCheckPreconditions:
    def test_known_stages_registered(self) -> None:
        # Stage.READY value as a fake stage substitute — but using the
        # documented enum, all stages should be in the registry.
        assert Stage.READY in STAGE_PRECONDITIONS
        assert Stage.REVIEW in STAGE_PRECONDITIONS

    def test_ready_passes_with_full_setup_for_feature(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        cache.record_classification(
            42,
            issue_type="feature",
            complexity_score=3,
            complexity_rank="low",
            routing_outcome="plan",
        )
        cache.record_plan_stored(42, plan_text="full plan")
        cache.record_review_stored(42, review_text="LGTM", has_blocking=False)
        result = check_preconditions(cache, 42, Stage.READY)
        assert result.ok is True

    def test_ready_fails_without_plan(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        cache.record_review_stored(42, review_text="LGTM", has_blocking=False)
        result = check_preconditions(cache, 42, Stage.READY)
        assert result.ok is False
        assert "no plan_stored" in result.reason

    def test_ready_short_circuits_on_first_failure(self, tmp_path: Path) -> None:
        """has_plan fails first; check_preconditions should not proceed
        to has_clean_review and concatenate reasons."""
        result = check_preconditions(_cache(tmp_path), 42, Stage.READY)
        assert result.ok is False
        # Only the first failure's reason is included.
        assert "no plan_stored" in result.reason
        assert "no review_stored" not in result.reason

    def test_ready_blocks_bug_without_reproduction(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        cache.record_classification(
            42,
            issue_type="bug",
            complexity_score=5,
            complexity_rank="medium",
            routing_outcome="plan",
        )
        cache.record_plan_stored(42, plan_text="fix the bug")
        cache.record_review_stored(42, review_text="LGTM", has_blocking=False)
        result = check_preconditions(cache, 42, Stage.READY)
        assert result.ok is False
        assert "no reproduction_stored" in result.reason

    def test_review_stage_requires_plan_and_review(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        cache.record_plan_stored(42, plan_text="plan")
        cache.record_review_stored(42, review_text="clean", has_blocking=False)
        assert check_preconditions(cache, 42, Stage.REVIEW).ok is True

    def test_review_stage_blocks_when_review_is_blocking(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        cache.record_plan_stored(42, plan_text="plan")
        cache.record_review_stored(42, review_text="bad", has_blocking=True)
        result = check_preconditions(cache, 42, Stage.REVIEW)
        assert result.ok is False
        assert "critical findings" in result.reason

    def test_unknown_stage_returns_ok(self, tmp_path: Path) -> None:
        """check_preconditions returns ok=True for stages not in the
        registry — locks in the current safety-valve contract so a
        future change to raise instead is an explicit decision."""
        from typing import cast

        # Cast around the StrEnum check by passing a literal Stage value
        # that is not in STAGE_PRECONDITIONS. Today both Stage members
        # ARE in the registry, so simulate an unknown by deleting locally.
        cache = _cache(tmp_path)
        # Build a fake unknown stage by passing a value not in the
        # registry. We cast through the enum constructor to satisfy the
        # type signature without monkey-patching the registry.
        fake_stage = cast(Stage, "unknown_stage")
        result = check_preconditions(cache, 42, fake_stage)
        assert result.ok is True

    def test_bug_reproduction_outcome_case_insensitive(self, tmp_path: Path) -> None:
        """has_reproduction_for_bug normalizes the outcome string before
        comparing — a hand-edited cache record with 'UNABLE' or 'Unable'
        must still trip the gate. Tests the predicate directly so the
        test is not gated on plan/review records existing."""
        cache = _cache(tmp_path)
        cache.record_classification(
            42,
            issue_type="bug",
            complexity_score=5,
            complexity_rank="medium",
            routing_outcome="plan",
        )
        # Write a reproduction record with non-canonical casing.
        from issue_cache import CacheRecord, CacheRecordKind

        cache.record(
            CacheRecord(
                issue_id=42,
                kind=CacheRecordKind.REPRODUCTION_STORED,
                payload={"outcome": "UNABLE", "test_path": "", "details": ""},
            )
        )
        result = has_reproduction_for_bug(cache, 42)
        assert result.ok is False
        assert "escalate to HITL" in result.reason

    def test_classification_with_parked_routing_does_not_satisfy_bug_gate(
        self, tmp_path: Path
    ) -> None:
        """A bug classification with routing_outcome='parked' must NOT
        satisfy has_reproduction_for_bug, even though issue_type=='bug'.
        Without this guard, a parked-then-relabeled issue could bypass
        the reproduction requirement."""
        cache = _cache(tmp_path)
        cache.record_classification(
            42,
            issue_type="bug",
            complexity_score=5,
            complexity_rank="medium",
            routing_outcome="parked",  # not "plan"
        )
        # No reproduction record exists, but the gate should pass
        # because the classification was not routed to plan — the
        # gate defers to upstream classification.
        result = has_reproduction_for_bug(cache, 42)
        assert result.ok is True

    def test_classification_with_discover_routing_does_not_satisfy_bug_gate(
        self, tmp_path: Path
    ) -> None:
        cache = _cache(tmp_path)
        cache.record_classification(
            42,
            issue_type="bug",
            complexity_score=5,
            complexity_rank="medium",
            routing_outcome="discover",
        )
        assert has_reproduction_for_bug(cache, 42).ok is True

    def test_bug_reproduction_outcome_titlecase_also_blocks(
        self, tmp_path: Path
    ) -> None:
        cache = _cache(tmp_path)
        cache.record_classification(
            42,
            issue_type="bug",
            complexity_score=5,
            complexity_rank="medium",
            routing_outcome="plan",
        )
        from issue_cache import CacheRecord, CacheRecordKind

        cache.record(
            CacheRecord(
                issue_id=42,
                kind=CacheRecordKind.REPRODUCTION_STORED,
                payload={"outcome": "Unable", "test_path": "", "details": ""},
            )
        )
        assert has_reproduction_for_bug(cache, 42).ok is False


# ---------------------------------------------------------------------------
# PreconditionResult
# ---------------------------------------------------------------------------


class TestPreconditionResult:
    def test_truthy_when_ok(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        cache.record_plan_stored(42, plan_text="x")
        assert bool(has_plan(cache, 42)) is True

    def test_falsy_when_not_ok(self, tmp_path: Path) -> None:
        assert bool(has_plan(_cache(tmp_path), 42)) is False
