"""Tests for FakeWorkspace, FakeSentry, FakeClock."""

from __future__ import annotations

import pytest

from mockworld.fakes.fake_clock import FakeClock
from mockworld.fakes.fake_sentry import FakeSentry
from mockworld.fakes.fake_workspace import FakeWorkspace

pytestmark = pytest.mark.scenario


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


class TestFakeWorkspaceFaults:
    async def test_fail_next_create_permission(self, tmp_path) -> None:
        ws = FakeWorkspace(tmp_path)
        ws.fail_next_create(kind="permission")
        with pytest.raises(PermissionError):
            await ws.create(1, "agent/issue-1")

    async def test_fail_next_create_disk_full(self, tmp_path) -> None:
        ws = FakeWorkspace(tmp_path)
        ws.fail_next_create(kind="disk_full")
        with pytest.raises(OSError) as exc_info:
            await ws.create(1, "agent/issue-1")
        assert exc_info.value.errno == 28

    async def test_fail_next_create_branch_conflict(self, tmp_path) -> None:
        ws = FakeWorkspace(tmp_path)
        ws.fail_next_create(kind="branch_conflict")
        with pytest.raises(RuntimeError, match="already exists"):
            await ws.create(1, "agent/issue-1")

    async def test_fail_next_create_is_single_shot(self, tmp_path) -> None:
        ws = FakeWorkspace(tmp_path)
        ws.fail_next_create(kind="permission")
        with pytest.raises(PermissionError):
            await ws.create(1, "agent/issue-1")
        # Second call succeeds
        path = await ws.create(2, "agent/issue-2")
        assert path is not None
