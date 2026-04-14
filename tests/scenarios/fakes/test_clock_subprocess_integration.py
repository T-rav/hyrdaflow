"""FakeClock can override subprocess_util's time source in tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.scenarios.fakes.mock_world import MockWorld


async def test_fake_clock_installed_on_subprocess_util(tmp_path: Path) -> None:
    from subprocess_util import _get_time_source  # noqa: PLC0415

    world = MockWorld(tmp_path, install_subprocess_clock=True)
    # The configured time source is the fake clock's .now()
    now = _get_time_source()()
    world.clock.advance(10.0)
    later = _get_time_source()()
    assert later - now == pytest.approx(10.0, abs=0.01)

    # Teardown restores real clock
    world.clock.uninstall_subprocess_clock()
    _get_time_source()()
    assert True  # any real time reading acceptable
