"""FakeReviewInsightStore — ReviewInsightStorePort impl backed by in-memory state.

Created to satisfy ADR-0047 (every Port needs a Fake). Identified as one of
five fakeless ports in the coverage audit (slice #5.2).

Design notes:

- All state is held in plain Python dicts/lists; there is no disk I/O.
- ``load_recent`` returns the last *n* records from the internal list in
  insertion order, mirroring the file-backed ``ReviewInsightStore`` behaviour.
- ``record_proposal`` captures ``pre_count`` and a fixed UTC timestamp so
  scenario tests can assert on the stored value without controlling a clock.
- ``update_proposal_verified`` is a no-op when the category has no prior
  metadata entry (mirrors the real store's silent guard in
  ``update_proposal_verified``).

The Fake is intentionally narrow — it does not replicate the file-path helpers
(``_proposal_meta_path``, ``save_proposal_metadata``) that are private
implementation details of the concrete adapter.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from review_insights import ProposalMetadata, ReviewRecord


class FakeReviewInsightStore:
    """In-memory ReviewInsightStorePort implementation for MockWorld scenarios.

    Satisfies the ``ReviewInsightStorePort`` protocol — every public method
    matches the port's signature so ``isinstance(fake, ReviewInsightStorePort)``
    returns True.
    """

    _is_fake_adapter = True

    def __init__(self) -> None:
        self._reviews: list[ReviewRecord] = []
        self._proposed_categories: set[str] = set()
        self._proposal_metadata: dict[str, ProposalMetadata] = {}

    # ------------------------------------------------------------------
    # ReviewInsightStorePort methods
    # ------------------------------------------------------------------

    def append_review(self, record: ReviewRecord) -> None:
        """Append *record* to the in-memory review list."""
        self._reviews.append(record)

    def load_recent(self, n: int = 10) -> list[ReviewRecord]:
        """Return the last *n* reviews in insertion order."""
        return self._reviews[-n:] if len(self._reviews) > n else list(self._reviews)

    def get_proposed_categories(self) -> set[str]:
        """Return the set of categories that already have filed proposals."""
        return set(self._proposed_categories)

    def mark_category_proposed(self, category: str) -> None:
        """Record that an improvement proposal has been filed for *category*."""
        self._proposed_categories.add(category)

    def record_proposal(self, category: str, pre_count: int) -> None:
        """Record a new improvement proposal with its baseline pattern count."""
        from review_insights import ProposalMetadata  # noqa: PLC0415

        self._proposal_metadata[category] = ProposalMetadata(
            pre_count=pre_count,
            proposed_at=datetime.now(UTC).isoformat(),
        )

    def load_proposal_metadata(self) -> dict[str, ProposalMetadata]:
        """Return a copy of the proposal metadata dict."""
        return dict(self._proposal_metadata)

    def update_proposal_verified(self, category: str, *, verified: bool) -> None:
        """Mark a proposal as verified (or stale). Silent no-op for unknown categories."""
        if category in self._proposal_metadata:
            self._proposal_metadata[category].verified = verified
