"""Tests for create_issue dedup guard in PRManager."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.helpers import ConfigFactory, make_pr_manager


class TestCreateIssueDedup:
    """Verify that create_issue checks for existing issues before filing."""

    @pytest.fixture
    def config(self, tmp_path: Path):
        return ConfigFactory.create(
            repo_root=tmp_path,
            repo="owner/repo",
        )

    @pytest.fixture
    def event_bus(self):
        from events import EventBus

        return EventBus()

    @pytest.fixture
    def mgr(self, config, event_bus):
        return make_pr_manager(config, event_bus)

    @pytest.mark.asyncio
    async def test_returns_existing_when_duplicate_found(
        self, mgr, monkeypatch
    ) -> None:
        """When an open issue with the same title exists, return its number."""
        search_result = json.dumps([{"number": 42, "title": "Fix the widget"}])

        async def fake_run_gh(*args, **kwargs):
            joined = " ".join(str(a) for a in args)
            if "search" in joined and "issues" in joined:
                return search_result
            raise AssertionError("create should not be called for duplicates")

        monkeypatch.setattr(mgr, "_run_gh", fake_run_gh)
        result = await mgr.create_issue("Fix the widget", "body", labels=["bug"])
        assert result == 42

    @pytest.mark.asyncio
    async def test_creates_when_no_duplicate(self, mgr, monkeypatch) -> None:
        """When no open issue matches, proceed with normal creation."""
        created = False

        async def fake_run_gh(*args, **kwargs):
            nonlocal created
            joined = " ".join(str(a) for a in args)
            if "search" in joined and "issues" in joined:
                return "[]"
            return ""

        async def fake_run_with_body(*args, **kwargs):
            nonlocal created
            created = True
            return "https://github.com/owner/repo/issues/99\n"

        monkeypatch.setattr(mgr, "_run_gh", fake_run_gh)
        monkeypatch.setattr(mgr, "_run_with_body_file", fake_run_with_body)
        result = await mgr.create_issue("Brand new issue", "body")
        assert result == 99
        assert created

    @pytest.mark.asyncio
    async def test_skips_dedup_on_dry_run(self, config, event_bus) -> None:
        """Dry run should return 0 without searching."""
        dry_config = ConfigFactory.create(
            repo_root=config.repo_root,
            repo="owner/repo",
            dry_run=True,
        )
        mgr = make_pr_manager(dry_config, event_bus)
        result = await mgr.create_issue("Any title", "body")
        assert result == 0

    @pytest.mark.asyncio
    async def test_find_existing_issue_ignores_partial_title_match(
        self, mgr, monkeypatch
    ) -> None:
        """find_existing_issue should only match exact titles."""
        search_result = json.dumps(
            [
                {"number": 10, "title": "Fix the widget v2"},
            ]
        )

        async def fake_run_gh(*args, **kwargs):
            return search_result

        monkeypatch.setattr(mgr, "_run_gh", fake_run_gh)
        result = await mgr.find_existing_issue("Fix the widget")
        assert result == 0

    @pytest.mark.asyncio
    async def test_find_existing_issue_returns_zero_on_error(
        self, mgr, monkeypatch
    ) -> None:
        """Search errors should fall through to allow creation."""

        async def failing_run_gh(*args, **kwargs):
            raise RuntimeError("gh CLI failed")

        monkeypatch.setattr(mgr, "_run_gh", failing_run_gh)
        result = await mgr.find_existing_issue("Some title")
        assert result == 0
