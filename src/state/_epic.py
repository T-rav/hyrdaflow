"""Epic state and release tracking."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from models import EpicState, Release

if TYPE_CHECKING:
    from models import StateData


class EpicStateMixin:
    """Methods for epic lifecycle and release tracking."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    @staticmethod
    def _key(issue_id: int | str) -> str: ...  # provided by StateTracker

    # --- epic state tracking ---

    def get_epic_state(self, epic_number: int) -> EpicState | None:
        """Return the persisted state for *epic_number*, or ``None``."""
        es = self._data.epic_states.get(self._key(epic_number))
        return es.model_copy(deep=True) if es else None

    def upsert_epic_state(self, state: EpicState) -> None:
        """Create or update the persisted state for an epic."""
        self._data.epic_states[self._key(state.epic_number)] = state.model_copy(
            deep=True
        )
        self.save()

    def mark_epic_child_complete(self, epic_number: int, child_number: int) -> None:
        """Move *child_number* to completed_children for *epic_number*."""
        epic = self._data.epic_states.get(self._key(epic_number))
        if epic is None:
            return
        if child_number not in epic.completed_children:
            epic.completed_children.append(child_number)
        if child_number in epic.failed_children:
            epic.failed_children.remove(child_number)
        epic.last_activity = datetime.now(UTC).isoformat()
        self.save()

    def mark_epic_child_failed(self, epic_number: int, child_number: int) -> None:
        """Move *child_number* to failed_children for *epic_number*."""
        epic = self._data.epic_states.get(self._key(epic_number))
        if epic is None:
            return
        if child_number not in epic.failed_children:
            epic.failed_children.append(child_number)
        epic.last_activity = datetime.now(UTC).isoformat()
        self.save()

    def mark_epic_child_approved(self, epic_number: int, child_number: int) -> None:
        """Add *child_number* to approved_children for *epic_number*."""
        epic = self._data.epic_states.get(self._key(epic_number))
        if epic is None:
            return
        if child_number not in epic.approved_children:
            epic.approved_children.append(child_number)
        epic.last_activity = datetime.now(UTC).isoformat()
        self.save()

    def get_epic_progress(self, epic_number: int) -> dict[str, object]:
        """Return epic progress summary for *epic_number*.

        Returns a dict with keys: total, merged, in_progress, pending,
        approved, ready_to_merge, merge_strategy.
        """
        epic = self._data.epic_states.get(self._key(epic_number))
        if epic is None:
            return {}
        total = len(epic.child_issues)
        merged = len(epic.completed_children)
        failed = len(epic.failed_children)
        approved = len(epic.approved_children)
        in_progress = total - merged - failed
        pending = total - merged - failed - approved
        # Ready to merge: all children approved or merged, none failed, non-independent
        ready = (
            total > 0
            and failed == 0
            and epic.merge_strategy != "independent"
            and all(
                c in epic.approved_children or c in epic.completed_children
                for c in epic.child_issues
            )
        )
        return {
            "total": total,
            "merged": merged,
            "in_progress": max(in_progress, 0),
            "pending": max(pending, 0),
            "approved": approved,
            "ready_to_merge": ready,
            "merge_strategy": epic.merge_strategy,
        }

    def get_all_epic_states(self) -> dict[str, EpicState]:
        """Return all persisted epic states (deep copy)."""
        return {k: v.model_copy(deep=True) for k, v in self._data.epic_states.items()}

    def close_epic(self, epic_number: int) -> None:
        """Mark an epic as closed."""
        epic = self._data.epic_states.get(self._key(epic_number))
        if epic is None:
            return
        epic.closed = True
        epic.last_activity = datetime.now(UTC).isoformat()
        self.save()

    # --- release tracking ---

    def upsert_release(self, release: Release) -> None:
        """Create or update a release record, keyed by epic number."""
        self._data.releases[self._key(release.epic_number)] = release.model_copy(
            deep=True
        )
        self.save()

    def get_release(self, epic_number: int) -> Release | None:
        """Return the release for *epic_number*, or ``None``."""
        rel = self._data.releases.get(self._key(epic_number))
        return rel.model_copy(deep=True) if rel else None

    def get_all_releases(self) -> dict[str, Release]:
        """Return all persisted releases (deep copy)."""
        return {k: v.model_copy(deep=True) for k, v in self._data.releases.items()}
