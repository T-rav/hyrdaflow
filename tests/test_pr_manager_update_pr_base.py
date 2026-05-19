"""Unit tests for PRManager.update_pr_base — retargeting a PR's base branch."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from tests.helpers import ConfigFactory, make_pr_manager


def _make_pr_manager() -> Any:
    config = ConfigFactory.create(repo="owner/repo")
    return make_pr_manager(config=config, event_bus=AsyncMock())


@pytest.mark.asyncio
async def test_update_pr_base_calls_gh_pr_edit(monkeypatch: pytest.MonkeyPatch) -> None:
    pm = _make_pr_manager()
    captured: dict[str, Any] = {}

    async def _fake_run_subprocess(*cmd: str, **_kw: Any) -> str:
        captured["cmd"] = cmd
        return ""

    monkeypatch.setattr("pr_manager.run_subprocess", _fake_run_subprocess)

    ok = await pm.update_pr_base(123, base="staging")

    assert ok is True
    cmd = captured["cmd"]
    assert "pr" in cmd
    assert "edit" in cmd
    assert "123" in cmd
    assert "--base" in cmd
    assert "staging" in cmd


@pytest.mark.asyncio
async def test_update_pr_base_returns_false_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pm = _make_pr_manager()

    async def _failing_subprocess(*_cmd: str, **_kw: Any) -> str:
        raise RuntimeError("gh pr edit failed: not found")

    monkeypatch.setattr("pr_manager.run_subprocess", _failing_subprocess)

    ok = await pm.update_pr_base(123, base="staging")
    assert ok is False


@pytest.mark.asyncio
async def test_update_pr_base_dry_run_returns_true_without_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pm = _make_pr_manager()
    pm._config.dry_run = True
    called = False

    async def _fake_run_subprocess(*_cmd: str, **_kw: Any) -> str:
        nonlocal called
        called = True
        return ""

    monkeypatch.setattr("pr_manager.run_subprocess", _fake_run_subprocess)

    ok = await pm.update_pr_base(99, base="staging")
    assert ok is True
    assert called is False
