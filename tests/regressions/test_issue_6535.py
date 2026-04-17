"""Regression test for issue #6535.

Bug: ``CrateManager._next_crate_title()`` catches ``RuntimeError`` on the
``list_milestones`` call.  Because ``AuthenticationError`` is a subclass of
``RuntimeError``, it is silently swallowed — the method falls back to
``max_iter=0`` and returns ``YYYY-MM-DD.1`` even when higher-numbered
milestones already exist, causing milestone name collisions.

Expected behaviour after fix:
  - ``AuthenticationError`` propagates out of ``_next_crate_title`` instead
    of being caught.
  - A plain (non-auth) ``RuntimeError`` is still caught and the method
    falls back gracefully to ``.1``.

These tests assert the *correct* behaviour, so they are RED against the
current buggy code.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from crate_manager import CrateManager  # noqa: E402
from subprocess_util import AuthenticationError  # noqa: E402
from tests.helpers import ConfigFactory  # noqa: E402


def _make_manager() -> tuple[CrateManager, AsyncMock]:
    """Create a CrateManager with mocked dependencies."""
    config = ConfigFactory.create()
    state = MagicMock()
    state.get_active_crate_number.return_value = None
    state.set_active_crate_number = MagicMock()
    pr_manager = AsyncMock()
    from events import EventBus  # noqa: E402

    bus = EventBus()
    cm = CrateManager(config, state, pr_manager, bus)
    return cm, pr_manager


class TestAuthenticationErrorPropagates:
    """Issue #6535 — AuthenticationError must not be silently swallowed
    by the ``except RuntimeError`` clause in ``_next_crate_title``.
    """

    @pytest.mark.asyncio
    async def test_authentication_error_escapes_next_crate_title(self) -> None:
        """When ``list_milestones`` raises ``AuthenticationError``,
        ``_next_crate_title`` must let it propagate rather than catching
        it and falling back to ``.1``.

        Currently FAILS (RED) because ``AuthenticationError`` is a
        ``RuntimeError`` subclass and the bare ``except RuntimeError``
        catches it silently.
        """
        # Arrange
        cm, pr_mock = _make_manager()
        pr_mock.list_milestones.side_effect = AuthenticationError("Bad credentials")

        # Act & Assert — the error must escape
        with pytest.raises(AuthenticationError):
            await cm._next_crate_title()

    @pytest.mark.asyncio
    async def test_plain_runtime_error_still_caught_gracefully(self) -> None:
        """A non-auth ``RuntimeError`` (transient GitHub API error) should
        still be caught and the method should fall back to ``.1``.

        This test is GREEN on the current code and should remain GREEN
        after the fix — it documents the graceful fallback.
        """
        # Arrange
        cm, pr_mock = _make_manager()
        pr_mock.list_milestones.side_effect = RuntimeError("API timeout")

        # Act — should not raise
        title = await cm._next_crate_title()

        # Assert — falls back to .1
        assert title.endswith(".1")
