"""FakeReviewInsightStore — conformance + behavioural tests.

Two layers:

1. Protocol conformance — ``isinstance(fake, ReviewInsightStorePort)`` must be
   True (runtime_checkable Protocol).

2. Behavioural — each Port method produces correct in-memory state, independent
   of any file I/O.
"""

from __future__ import annotations

from datetime import UTC, datetime

from mockworld.fakes.fake_review_insight_store import FakeReviewInsightStore
from models import ReviewVerdict
from ports import ReviewInsightStorePort
from review_insights import ReviewRecord

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _record(
    pr_number: int = 1,
    issue_number: int = 10,
    verdict: ReviewVerdict = ReviewVerdict.APPROVE,
    summary: str = "lgtm",
    categories: list[str] | None = None,
) -> ReviewRecord:
    return ReviewRecord(
        pr_number=pr_number,
        issue_number=issue_number,
        timestamp=datetime.now(UTC).isoformat(),
        verdict=verdict,
        summary=summary,
        fixes_made=False,
        categories=categories or [],
    )


# ---------------------------------------------------------------------------
# Conformance
# ---------------------------------------------------------------------------


def test_isinstance_review_insight_store_port() -> None:
    """FakeReviewInsightStore must satisfy ReviewInsightStorePort at runtime."""
    fake = FakeReviewInsightStore()
    assert isinstance(fake, ReviewInsightStorePort), (
        "FakeReviewInsightStore does not satisfy ReviewInsightStorePort — "
        "check that all Protocol methods are present and named correctly."
    )


def test_has_fake_adapter_marker() -> None:
    assert FakeReviewInsightStore._is_fake_adapter is True


# ---------------------------------------------------------------------------
# append_review / load_recent
# ---------------------------------------------------------------------------


def test_append_and_load_recent_returns_appended_records() -> None:
    fake = FakeReviewInsightStore()
    r1 = _record(pr_number=1)
    r2 = _record(pr_number=2)

    fake.append_review(r1)
    fake.append_review(r2)

    loaded = fake.load_recent(n=10)
    assert loaded == [r1, r2]


def test_load_recent_respects_n_limit() -> None:
    fake = FakeReviewInsightStore()
    for i in range(5):
        fake.append_review(_record(pr_number=i))

    loaded = fake.load_recent(n=3)
    assert len(loaded) == 3
    # Should be the last 3 in insertion order
    assert [r.pr_number for r in loaded] == [2, 3, 4]


def test_load_recent_empty_store_returns_empty_list() -> None:
    fake = FakeReviewInsightStore()
    assert fake.load_recent() == []


def test_load_recent_default_n_is_ten() -> None:
    """Default n=10 — store with 12 records returns only the last 10."""
    fake = FakeReviewInsightStore()
    for i in range(12):
        fake.append_review(_record(pr_number=i))

    loaded = fake.load_recent()
    assert len(loaded) == 10
    assert loaded[0].pr_number == 2  # first of last-10
    assert loaded[-1].pr_number == 11


# ---------------------------------------------------------------------------
# get_proposed_categories / mark_category_proposed
# ---------------------------------------------------------------------------


def test_get_proposed_categories_empty_initially() -> None:
    fake = FakeReviewInsightStore()
    assert fake.get_proposed_categories() == set()


def test_mark_category_proposed_adds_to_set() -> None:
    fake = FakeReviewInsightStore()
    fake.mark_category_proposed("missing_tests")
    assert "missing_tests" in fake.get_proposed_categories()


def test_mark_category_proposed_idempotent() -> None:
    fake = FakeReviewInsightStore()
    fake.mark_category_proposed("missing_tests")
    fake.mark_category_proposed("missing_tests")
    assert len(fake.get_proposed_categories()) == 1


def test_get_proposed_categories_returns_copy() -> None:
    """Mutating the returned set must not affect internal state."""
    fake = FakeReviewInsightStore()
    fake.mark_category_proposed("security")

    categories = fake.get_proposed_categories()
    categories.add("extra")

    assert "extra" not in fake.get_proposed_categories()


# ---------------------------------------------------------------------------
# record_proposal / load_proposal_metadata
# ---------------------------------------------------------------------------


def test_record_proposal_stores_pre_count() -> None:
    fake = FakeReviewInsightStore()
    fake.record_proposal("missing_tests", pre_count=5)

    meta = fake.load_proposal_metadata()
    assert "missing_tests" in meta
    assert meta["missing_tests"].pre_count == 5


def test_record_proposal_sets_proposed_at_timestamp() -> None:
    fake = FakeReviewInsightStore()
    before = datetime.now(UTC).isoformat()
    fake.record_proposal("error_handling", pre_count=3)
    after = datetime.now(UTC).isoformat()

    meta = fake.load_proposal_metadata()
    proposed_at = meta["error_handling"].proposed_at
    assert before <= proposed_at <= after


def test_record_proposal_verified_defaults_to_false() -> None:
    fake = FakeReviewInsightStore()
    fake.record_proposal("naming", pre_count=2)

    meta = fake.load_proposal_metadata()
    assert meta["naming"].verified is False


def test_load_proposal_metadata_empty_initially() -> None:
    fake = FakeReviewInsightStore()
    assert fake.load_proposal_metadata() == {}


def test_load_proposal_metadata_returns_copy() -> None:
    """Mutating the returned dict must not affect internal state."""
    fake = FakeReviewInsightStore()
    fake.record_proposal("security", pre_count=4)

    meta = fake.load_proposal_metadata()
    del meta["security"]

    assert "security" in fake.load_proposal_metadata()


# ---------------------------------------------------------------------------
# update_proposal_verified
# ---------------------------------------------------------------------------


def test_update_proposal_verified_sets_verified_true() -> None:
    fake = FakeReviewInsightStore()
    fake.record_proposal("type_annotations", pre_count=7)

    fake.update_proposal_verified("type_annotations", verified=True)

    meta = fake.load_proposal_metadata()
    assert meta["type_annotations"].verified is True


def test_update_proposal_verified_sets_verified_false() -> None:
    fake = FakeReviewInsightStore()
    fake.record_proposal("naming", pre_count=1)
    fake.update_proposal_verified("naming", verified=True)

    fake.update_proposal_verified("naming", verified=False)

    meta = fake.load_proposal_metadata()
    assert meta["naming"].verified is False


def test_update_proposal_verified_unknown_category_is_noop() -> None:
    """Must not raise when category has no prior metadata."""
    fake = FakeReviewInsightStore()
    # Should not raise
    fake.update_proposal_verified("nonexistent", verified=True)
    assert fake.load_proposal_metadata() == {}


# ---------------------------------------------------------------------------
# Isolation between instances
# ---------------------------------------------------------------------------


def test_two_instances_are_isolated() -> None:
    a = FakeReviewInsightStore()
    b = FakeReviewInsightStore()

    a.append_review(_record(pr_number=1))
    a.mark_category_proposed("security")
    a.record_proposal("missing_tests", pre_count=3)

    assert b.load_recent() == []
    assert b.get_proposed_categories() == set()
    assert b.load_proposal_metadata() == {}
