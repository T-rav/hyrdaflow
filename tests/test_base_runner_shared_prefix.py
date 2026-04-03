"""Tests for BaseRunner.hindsight property (#5938)."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from base_runner import BaseRunner  # noqa: E402


class _TestRunner(BaseRunner):
    """Minimal concrete subclass that satisfies the ClassVar requirement."""

    _log = logging.getLogger("hydraflow.test_runner_shared_prefix")


class TestBaseRunnerHindsightProperty:
    """Tests for the BaseRunner.hindsight read-only property."""

    def _make_runner(self, hindsight=None):
        """Construct a _TestRunner with minimal dependencies."""
        config = MagicMock()
        config.model = "claude-3-5-sonnet-latest"
        config.implementation_tool = "claude"
        event_bus = MagicMock()
        runner = MagicMock()
        return _TestRunner(config, event_bus, runner, hindsight=hindsight)

    def test_hindsight_property_returns_none_by_default(self) -> None:
        """hindsight defaults to None when not provided."""
        r = self._make_runner()
        assert r.hindsight is None

    def test_hindsight_property_returns_client_when_set(self) -> None:
        """hindsight returns the exact client object that was injected."""
        mock_client = MagicMock()
        r = self._make_runner(hindsight=mock_client)
        assert r.hindsight is mock_client

    def test_hindsight_property_is_read_only(self) -> None:
        """hindsight cannot be set — it is a read-only property."""
        r = self._make_runner()
        try:
            r.hindsight = MagicMock()  # type: ignore[misc]
            # If no exception, fall through and fail the test
            assert False, "Expected AttributeError when setting read-only property"
        except AttributeError:
            pass  # Expected — property has no setter

    def test_hindsight_is_same_object_as_internal_attribute(self) -> None:
        """hindsight property reflects _hindsight without copying."""
        mock_client = MagicMock()
        r = self._make_runner(hindsight=mock_client)
        assert r.hindsight is r._hindsight
