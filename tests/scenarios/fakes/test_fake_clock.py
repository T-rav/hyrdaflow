"""Tests for FakeClock.freeze() helper."""

from __future__ import annotations

from mockworld.fakes.fake_clock import FakeClock


def test_freeze_accepts_unix_float():
    clock = FakeClock()
    clock.freeze(1_718_467_200.0)  # 2024-06-15T16:00:00Z
    assert clock.now() == 1_718_467_200.0


def test_freeze_accepts_iso_string():
    clock = FakeClock()
    clock.freeze("2025-06-15T12:00:00Z")
    # ISO 2025-06-15T12:00:00Z -> unix 1_749_988_800
    assert clock.now() == 1_749_988_800.0


def test_freeze_rejects_naive_datetime_string():
    clock = FakeClock()
    import pytest

    with pytest.raises(ValueError, match="timezone"):
        clock.freeze("2025-06-15T12:00:00")  # no Z / offset
