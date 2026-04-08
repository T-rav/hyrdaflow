"""Tests for issue_cache.IssueCache — append-only JSONL mirror.

Resolves #6422 (first slice). Covers append ordering, versioning,
latest-kind read queries, disabled-toggle no-op, malformed-record
tolerance, best-effort error handling, and the typed convenience
writers for classification / plan / review / reproduction / route-back.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from issue_cache import CacheRecord, CacheRecordKind, IssueCache

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cache(tmp_path: Path, *, enabled: bool = True) -> IssueCache:
    return IssueCache(tmp_path / "cache", enabled=enabled)


# ---------------------------------------------------------------------------
# Core write/read
# ---------------------------------------------------------------------------


class TestBasicAppend:
    def test_record_creates_file(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        cache.record(
            CacheRecord(
                issue_id=42,
                kind=CacheRecordKind.FETCH,
                payload={"title": "hello"},
            )
        )
        path = cache.issues_dir / "42.jsonl"
        assert path.exists()
        assert path.read_text().strip()

    def test_multiple_records_preserve_order(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        for i in range(5):
            cache.record(
                CacheRecord(
                    issue_id=42,
                    kind=CacheRecordKind.FETCH,
                    payload={"n": i},
                )
            )
        history = cache.read_history(42)
        assert [r.payload["n"] for r in history] == [0, 1, 2, 3, 4]

    def test_separate_issues_use_separate_files(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        cache.record_fetch(1, {"a": 1})
        cache.record_fetch(2, {"b": 2})
        assert (cache.issues_dir / "1.jsonl").exists()
        assert (cache.issues_dir / "2.jsonl").exists()
        assert cache.read_history(1)[0].payload == {"a": 1}
        assert cache.read_history(2)[0].payload == {"b": 2}

    def test_read_history_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert _cache(tmp_path).read_history(999) == []

    def test_read_history_skips_malformed_lines(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        cache.record_fetch(42, {"ok": True})
        # Append a garbage line directly.
        path = cache.issues_dir / "42.jsonl"
        with path.open("a") as f:
            f.write("{ not json\n")
        cache.record_fetch(42, {"ok": True, "n": 2})

        history = cache.read_history(42)
        assert len(history) == 2
        assert history[1].payload["n"] == 2


# ---------------------------------------------------------------------------
# Disabled toggle
# ---------------------------------------------------------------------------


class TestDisabledToggle:
    def test_disabled_cache_does_not_write(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path, enabled=False)
        cache.record_fetch(42, {"title": "hello"})
        assert not (cache.issues_dir / "42.jsonl").exists()

    def test_disabled_read_still_works(self, tmp_path: Path) -> None:
        """Read path remains functional when disabled — legacy data is still
        readable after a toggle flip."""
        # Seed with enabled cache first.
        enabled = _cache(tmp_path, enabled=True)
        enabled.record_fetch(42, {"seeded": True})

        disabled = _cache(tmp_path, enabled=False)
        history = disabled.read_history(42)
        assert len(history) == 1
        assert history[0].payload == {"seeded": True}

    def test_enabled_property(self, tmp_path: Path) -> None:
        assert _cache(tmp_path, enabled=True).enabled is True
        assert _cache(tmp_path, enabled=False).enabled is False


# ---------------------------------------------------------------------------
# Best-effort error handling
# ---------------------------------------------------------------------------


class TestBestEffort:
    def test_oserror_on_append_does_not_raise(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        cache = _cache(tmp_path)
        with patch("issue_cache.append_jsonl", side_effect=OSError("disk full")):
            # Must not raise.
            cache.record_fetch(42, {"ok": True})
        assert any("failed to append" in rec.getMessage() for rec in caplog.records)

    def test_oserror_on_read_returns_empty_not_raise(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        cache.record_fetch(42, {"ok": True})
        # Patch the Path symbol as imported by issue_cache rather than the
        # global pathlib.Path.read_text — keeps the mock blast radius
        # confined to issue_cache module reads, leaving pytest internals
        # and tmp_path fixtures unaffected.
        with patch("issue_cache.Path.read_text", side_effect=OSError("boom")):
            history = cache.read_history(42)
        assert history == []


# ---------------------------------------------------------------------------
# Typed writers
# ---------------------------------------------------------------------------


class TestClassificationRecord:
    def test_record_classification_round_trip(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        cache.record_classification(
            42,
            issue_type="bug",
            complexity_score=7,
            complexity_rank="high",
            reasoning="touches 3 modules",
        )
        latest = cache.latest_classification(42)
        assert latest is not None
        assert latest.kind == CacheRecordKind.CLASSIFIED
        assert latest.payload == {
            "issue_type": "bug",
            "complexity_score": 7,
            "complexity_rank": "high",
            "reasoning": "touches 3 modules",
        }

    def test_latest_classification_returns_most_recent(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        cache.record_classification(
            42,
            issue_type="feature",
            complexity_score=3,
            complexity_rank="low",
        )
        cache.record_classification(
            42,
            issue_type="bug",  # re-classified
            complexity_score=7,
            complexity_rank="high",
        )
        latest = cache.latest_classification(42)
        assert latest is not None
        assert latest.payload["issue_type"] == "bug"


class TestPlanVersioning:
    def test_first_plan_is_version_1(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        version = cache.record_plan_stored(
            42, plan_text="first plan", actionability_score=80
        )
        assert version == 1

    def test_plan_version_increments_per_issue(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        v1 = cache.record_plan_stored(42, plan_text="v1")
        v2 = cache.record_plan_stored(42, plan_text="v2")
        v3 = cache.record_plan_stored(42, plan_text="v3")
        assert (v1, v2, v3) == (1, 2, 3)

    def test_plan_versions_per_issue_are_independent(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        cache.record_plan_stored(1, plan_text="a")
        cache.record_plan_stored(1, plan_text="b")
        v = cache.record_plan_stored(2, plan_text="c")
        assert v == 1

    def test_latest_plan_returns_highest_version(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        cache.record_plan_stored(42, plan_text="v1")
        cache.record_plan_stored(42, plan_text="v2")
        latest = cache.latest_plan(42)
        assert latest is not None
        assert latest.version == 2
        assert latest.payload["plan_text"] == "v2"


class TestReviewRecord:
    def test_review_with_critical_finding(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        version = cache.record_review_stored(
            42,
            review_text="plan ignores the reproduction test",
            has_critical=True,
            findings=[{"severity": "critical", "note": "missing repro ref"}],
        )
        assert version == 1
        latest = cache.latest_review(42)
        assert latest is not None
        assert latest.payload["has_critical"] is True
        assert latest.payload["findings"][0]["severity"] == "critical"

    def test_review_versions_increment(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        v1 = cache.record_review_stored(42, review_text="first", has_critical=True)
        v2 = cache.record_review_stored(
            42, review_text="second — cleaner", has_critical=False
        )
        assert (v1, v2) == (1, 2)


class TestReproductionRecord:
    def test_reproduction_success_outcome(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        cache.record_reproduction_stored(
            42,
            outcome="success",
            test_path="tests/regressions/test_issue_42.py",
            details="test is red",
        )
        latest = cache.latest_reproduction(42)
        assert latest is not None
        assert latest.payload["outcome"] == "success"
        assert latest.payload["test_path"].endswith("test_issue_42.py")

    def test_reproduction_unable_outcome(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        cache.record_reproduction_stored(
            42, outcome="unable", details="could not reproduce manually"
        )
        latest = cache.latest_reproduction(42)
        assert latest is not None
        assert latest.payload["outcome"] == "unable"
        assert latest.payload["test_path"] == ""


class TestRouteBackRecord:
    def test_route_back_records_direction_and_reason(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        cache.record_route_back(
            42,
            from_stage="ready",
            to_stage="plan",
            reason="plan review found critical gaps",
            feedback_context="missing reproduction reference",
        )
        history = cache.read_history(42)
        assert len(history) == 1
        assert history[0].kind == CacheRecordKind.ROUTE_BACK
        assert history[0].payload["from_stage"] == "ready"
        assert history[0].payload["to_stage"] == "plan"
        assert "critical" in history[0].payload["reason"]


# ---------------------------------------------------------------------------
# Latest-kind lookups
# ---------------------------------------------------------------------------


class TestLatestRecordLookup:
    def test_latest_returns_none_when_no_records(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        assert cache.latest_plan(42) is None
        assert cache.latest_review(42) is None
        assert cache.latest_classification(42) is None

    def test_latest_kind_skips_unrelated_records(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        cache.record_fetch(42, {})
        cache.record_classification(
            42,
            issue_type="bug",
            complexity_score=5,
            complexity_rank="medium",
        )
        cache.record_fetch(42, {})
        cache.record_plan_stored(42, plan_text="a plan")
        cache.record_fetch(42, {})

        latest = cache.latest_plan(42)
        assert latest is not None
        assert latest.kind == CacheRecordKind.PLAN_STORED

        classification = cache.latest_classification(42)
        assert classification is not None
        assert classification.payload["issue_type"] == "bug"


# ---------------------------------------------------------------------------
# Issue discovery
# ---------------------------------------------------------------------------


class TestKnownIssueIds:
    def test_empty_when_no_records(self, tmp_path: Path) -> None:
        assert _cache(tmp_path).known_issue_ids() == []

    def test_returns_sorted_ids(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        cache.record_fetch(42, {})
        cache.record_fetch(7, {})
        cache.record_fetch(100, {})
        assert cache.known_issue_ids() == [7, 42, 100]

    def test_ignores_non_numeric_files(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        cache.record_fetch(42, {})
        # Drop a stray file into the issues dir.
        (cache.issues_dir / "scratch.txt").write_text("garbage")
        (cache.issues_dir / "not-a-number.jsonl").write_text('{"ok": 1}\n')
        assert cache.known_issue_ids() == [42]

    def test_sort_is_numeric_not_lexicographic(self, tmp_path: Path) -> None:
        """[1, 2, 10] must sort numerically as [1, 2, 10], not as the
        lexicographic [1, 10, 2]. Catches a regression where stems are
        sorted as strings instead of being parsed to int first."""
        cache = _cache(tmp_path)
        cache.record_fetch(2, {})
        cache.record_fetch(10, {})
        cache.record_fetch(1, {})
        assert cache.known_issue_ids() == [1, 2, 10]


# ---------------------------------------------------------------------------
# Concurrent versioned writes
# ---------------------------------------------------------------------------


class TestConcurrentVersioning:
    """Versioned writers serialize per-issue so concurrent calls cannot
    allocate duplicate version numbers. Without the per-issue lock, two
    threads racing on record_plan_stored would both read the same
    latest version, both compute version=N+1, and both append a record
    with the same number — silently corrupting the audit trail."""

    def test_concurrent_plan_writes_get_distinct_versions(self, tmp_path: Path) -> None:
        from concurrent.futures import ThreadPoolExecutor

        cache = _cache(tmp_path)
        n_writes = 20

        def write(_: int) -> int:
            return cache.record_plan_stored(42, plan_text="iteration")

        with ThreadPoolExecutor(max_workers=8) as ex:
            versions = sorted(ex.map(write, range(n_writes)))

        # Every version is distinct and the set is exactly 1..n_writes.
        assert versions == list(range(1, n_writes + 1))

        # And the JSONL file has exactly n_writes records.
        history = cache.read_history(42)
        assert len(history) == n_writes

    def test_concurrent_writes_for_different_issues_run_in_parallel(
        self, tmp_path: Path
    ) -> None:
        """Per-issue locking — two issues should be able to write in
        parallel without serializing on each other."""
        from concurrent.futures import ThreadPoolExecutor

        cache = _cache(tmp_path)

        def write(issue_id: int) -> int:
            return cache.record_plan_stored(issue_id, plan_text="x")

        with ThreadPoolExecutor(max_workers=4) as ex:
            results = list(ex.map(write, [1, 2, 3, 4]))

        # Each issue gets version 1 — independent counters.
        assert results == [1, 1, 1, 1]
        for issue_id in (1, 2, 3, 4):
            assert len(cache.read_history(issue_id)) == 1
