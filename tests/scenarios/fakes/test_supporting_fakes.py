"""Tests for FakeHindsight, FakeWorkspace, FakeSentry, FakeClock."""

from __future__ import annotations

import pytest

from tests.scenarios.fakes.fake_clock import FakeClock
from tests.scenarios.fakes.fake_hindsight import FakeHindsight
from tests.scenarios.fakes.fake_sentry import FakeSentry
from tests.scenarios.fakes.fake_workspace import FakeWorkspace

pytestmark = pytest.mark.scenario


class TestFakeHindsight:
    async def test_retain_and_recall(self):
        hs = FakeHindsight()
        await hs.retain("learnings", "key1", "test memory")
        results = await hs.recall("learnings", "test")
        assert len(results) == 1
        assert results[0]["content"] == "test memory"

    async def test_recall_empty_bank(self):
        hs = FakeHindsight()
        results = await hs.recall("learnings", "nothing")
        assert results == []

    async def test_fail_mode(self):
        hs = FakeHindsight()
        hs.set_failing(True)
        with pytest.raises(ConnectionError):
            await hs.retain("learnings", "k", "v")

    async def test_heal_after_fail(self):
        hs = FakeHindsight()
        hs.set_failing(True)
        hs.set_failing(False)
        await hs.retain("learnings", "k", "v")
        results = await hs.recall("learnings", "")
        assert len(results) == 1


class TestFakeWorkspace:
    async def test_create_tracks_issue(self, tmp_path):
        ws = FakeWorkspace(tmp_path)
        path = await ws.create(42, "agent/issue-42")
        assert 42 in ws.created
        assert path.exists()

    async def test_destroy_tracks_cleanup(self, tmp_path):
        ws = FakeWorkspace(tmp_path)
        await ws.create(42, "agent/issue-42")
        await ws.destroy(42)
        assert 42 in ws.destroyed


class TestFakeSentry:
    def test_capture_breadcrumb(self):
        sentry = FakeSentry()
        sentry.add_breadcrumb(category="test", message="hello")
        assert len(sentry.breadcrumbs) == 1
        assert sentry.breadcrumbs[0]["message"] == "hello"

    def test_capture_exception(self):
        sentry = FakeSentry()
        sentry.capture_exception(ValueError("boom"))
        assert len(sentry.events) == 1


class TestFakeClock:
    def test_advance_time(self):
        clock = FakeClock(start=1000.0)
        assert clock.now() == 1000.0
        clock.advance(60.0)
        assert clock.now() == 1060.0

    async def test_sleep_advances_clock(self):
        clock = FakeClock(start=1000.0)
        await clock.sleep(30.0)
        assert clock.now() == 1030.0
