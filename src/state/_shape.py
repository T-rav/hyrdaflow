"""Shape conversation state: persistence for multi-turn design conversations."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import ShapeConversation, StateData


class ShapeStateMixin:
    """Methods for persisting shape conversation state."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    @staticmethod
    def _key(issue_id: int | str) -> str: ...  # provided by StateTracker

    def set_shape_conversation(
        self, issue_number: int, conversation: ShapeConversation
    ) -> None:
        """Save or update a shape conversation for *issue_number*."""
        self._data.shape_conversations[self._key(issue_number)] = conversation
        self.save()

    def get_shape_conversation(self, issue_number: int) -> ShapeConversation | None:
        """Return the shape conversation for *issue_number*, or *None*."""
        return self._data.shape_conversations.get(self._key(issue_number))

    def remove_shape_conversation(self, issue_number: int) -> None:
        """Clear the shape conversation for *issue_number*."""
        self._data.shape_conversations.pop(self._key(issue_number), None)
        self.save()
