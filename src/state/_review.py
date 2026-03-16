"""Review attempt, feedback, and last-reviewed-SHA state."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import StateData


class ReviewStateMixin:
    """Methods for review attempts, feedback, and last-reviewed SHA."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    @staticmethod
    def _key(issue_id: int | str) -> str: ...  # provided by StateTracker

    # --- review attempt tracking ---

    def get_review_attempts(self, issue_number: int) -> int:
        """Return the current review attempt count for *issue_number* (default 0)."""
        return self._data.review_attempts.get(self._key(issue_number), 0)

    def increment_review_attempts(self, issue_number: int) -> int:
        """Increment and return the new review attempt count for *issue_number*."""
        key = self._key(issue_number)
        current = self._data.review_attempts.get(key, 0)
        self._data.review_attempts[key] = current + 1
        self.save()
        return current + 1

    def reset_review_attempts(self, issue_number: int) -> None:
        """Clear the review attempt counter for *issue_number*."""
        self._data.review_attempts.pop(self._key(issue_number), None)
        self.save()

    # --- review feedback storage ---

    def set_review_feedback(self, issue_number: int, feedback: str) -> None:
        """Store review feedback for *issue_number*."""
        self._data.review_feedback[self._key(issue_number)] = feedback
        self.save()

    def get_review_feedback(self, issue_number: int) -> str | None:
        """Return stored review feedback for *issue_number*, or *None*."""
        return self._data.review_feedback.get(self._key(issue_number))

    def clear_review_feedback(self, issue_number: int) -> None:
        """Clear stored review feedback for *issue_number*."""
        self._data.review_feedback.pop(self._key(issue_number), None)
        self.save()

    # --- last reviewed SHA tracking ---

    def set_last_reviewed_sha(self, issue_number: int, sha: str) -> None:
        """Record the last-reviewed commit SHA for *issue_number*."""
        self._data.last_reviewed_shas[self._key(issue_number)] = sha
        self.save()

    def get_last_reviewed_sha(self, issue_number: int) -> str | None:
        """Return the last-reviewed commit SHA for *issue_number*, or *None*."""
        return self._data.last_reviewed_shas.get(self._key(issue_number))

    def clear_last_reviewed_sha(self, issue_number: int) -> None:
        """Clear the last-reviewed commit SHA for *issue_number*."""
        self._data.last_reviewed_shas.pop(self._key(issue_number), None)
        self.save()
