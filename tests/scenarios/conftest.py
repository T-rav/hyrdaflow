"""Scenario test fixtures."""

from __future__ import annotations

import pytest

from tests.scenarios.catalog import (
    loop_registrations as _loop_registrations,  # noqa: F401
)


@pytest.fixture
async def mock_world(tmp_path):
    """Provide a fresh MockWorld for scenario tests."""
    from tests.scenarios.fakes import MockWorld

    world = MockWorld(tmp_path)
    yield world
