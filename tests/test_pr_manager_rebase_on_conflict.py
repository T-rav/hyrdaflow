"""Tests for PRManager.update_pr_branch + auto_rebase merge path.

Covers the rebase-on-conflict pattern: when ``merge_pr`` or
``merge_promotion_pr`` fails, the caller can pass ``auto_rebase=True``
to trigger one rebase attempt via GitHub's update-branch API, re-poll CI,
and retry the merge.

Conflicts are handled by GitHub's API: 202 = clean rebase, 422 = real
conflict. Real conflicts surface to the caller as ``False`` so the
existing failure paths (find-issue, HITL release) still fire.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from tests.helpers import ConfigFactory, make_pr_manager


def _make_pr_manager() -> Any:
    """Minimal real PRManager for unit testing the rebase-on-conflict path."""
    config = ConfigFactory.create(repo="owner/repo")
    return make_pr_manager(config=config, event_bus=AsyncMock())


# --- update_pr_branch ---------------------------------------------------------


@pytest.mark.asyncio
async def test_update_pr_branch_calls_github_api_with_rebase_method(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """update_pr_branch(N) must PUT /pulls/N/update-branch with method=rebase."""
    pm = _make_pr_manager()
    captured: dict[str, Any] = {}

    async def _fake_run_gh(*cmd: str, cwd: Any = None) -> str:
        captured["cmd"] = cmd
        return ""

    monkeypatch.setattr(pm, "_run_gh", _fake_run_gh)

    ok = await pm.update_pr_branch(123, method="rebase")

    assert ok is True
    cmd = captured["cmd"]
    assert "api" in cmd
    assert "--method" in cmd
    assert "PUT" in cmd
    assert any("pulls/123/update-branch" in c for c in cmd)
    assert any("update_method=rebase" in c for c in cmd)


@pytest.mark.asyncio
async def test_update_pr_branch_returns_false_on_conflict_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When GitHub returns 422 (conflict / can't rebase), update_pr_branch returns False."""
    pm = _make_pr_manager()

    async def _raising_gh(*cmd: str, cwd: Any = None) -> str:
        raise RuntimeError(
            "HTTP 422: Validation Failed (https://api.github.com/repos/owner/repo/pulls/123/update-branch)"
        )

    monkeypatch.setattr(pm, "_run_gh", _raising_gh)

    ok = await pm.update_pr_branch(123)
    assert ok is False


@pytest.mark.asyncio
async def test_update_pr_branch_returns_false_on_other_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-422 failures also return False (don't crash the caller)."""
    pm = _make_pr_manager()

    async def _raising_gh(*cmd: str, cwd: Any = None) -> str:
        raise RuntimeError("network blip")

    monkeypatch.setattr(pm, "_run_gh", _raising_gh)
    assert await pm.update_pr_branch(123) is False


@pytest.mark.asyncio
async def test_update_pr_branch_dry_run_returns_true_without_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pm = _make_pr_manager()
    pm._config.dry_run = True
    called = False

    async def _fake_run_gh(*cmd: str, cwd: Any = None) -> str:
        nonlocal called
        called = True
        return ""

    monkeypatch.setattr(pm, "_run_gh", _fake_run_gh)
    assert await pm.update_pr_branch(99) is True
    assert called is False


# --- merge_pr with auto_rebase=True ------------------------------------------


@pytest.mark.asyncio
async def test_merge_pr_auto_rebase_off_does_not_invoke_rebase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Backward compat: default auto_rebase=False must not trigger rebase even on failure."""
    pm = _make_pr_manager()
    update_called = False

    async def _bad_merge(*a: Any, **kw: Any) -> Any:
        raise RuntimeError("merge conflict")

    async def _update(*a: Any, **kw: Any) -> bool:
        nonlocal update_called
        update_called = True
        return True

    monkeypatch.setattr("subprocess_util.run_subprocess", _bad_merge)
    monkeypatch.setattr(pm, "update_pr_branch", _update)
    monkeypatch.setattr(pm, "get_pr_title_and_body", AsyncMock(return_value=("", "")))

    ok = await pm.merge_pr(42)
    assert ok is False
    assert update_called is False


@pytest.mark.asyncio
async def test_merge_pr_auto_rebase_recovers_after_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First merge fails → update_pr_branch succeeds → wait_for_ci passes → second merge succeeds."""
    pm = _make_pr_manager()
    merge_calls = 0

    async def _flaky_subprocess(*cmd: str, **kw: Any) -> str:
        nonlocal merge_calls
        # Only the merge itself goes through run_subprocess; intercept by argv shape
        if "merge" in cmd:
            merge_calls += 1
            if merge_calls == 1:
                raise RuntimeError("Pull Request is not mergeable: conflict")
            return ""
        return ""

    async def _update_ok(*a: Any, **kw: Any) -> bool:
        return True

    async def _ci_passes(*a: Any, **kw: Any) -> tuple[bool, str]:
        return True, "CI passed after rebase"

    monkeypatch.setattr("pr_manager.run_subprocess", _flaky_subprocess)
    monkeypatch.setattr(pm, "update_pr_branch", _update_ok)
    monkeypatch.setattr(pm, "wait_for_ci", _ci_passes)
    monkeypatch.setattr(pm, "get_pr_title_and_body", AsyncMock(return_value=("", "")))

    ok = await pm.merge_pr(42, auto_rebase=True)
    assert ok is True
    assert merge_calls == 2  # first failed, second succeeded


@pytest.mark.asyncio
async def test_merge_pr_auto_rebase_gives_up_on_real_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When update_pr_branch returns False (real conflict), merge_pr gives up: returns False."""
    pm = _make_pr_manager()

    async def _failing_subprocess(*cmd: str, **kw: Any) -> str:
        if "merge" in cmd:
            raise RuntimeError("conflict")
        return ""

    async def _update_fails(*a: Any, **kw: Any) -> bool:
        return False

    monkeypatch.setattr("pr_manager.run_subprocess", _failing_subprocess)
    monkeypatch.setattr(pm, "update_pr_branch", _update_fails)
    monkeypatch.setattr(pm, "get_pr_title_and_body", AsyncMock(return_value=("", "")))

    ok = await pm.merge_pr(42, auto_rebase=True)
    assert ok is False


@pytest.mark.asyncio
async def test_merge_pr_auto_rebase_gives_up_when_ci_fails_after_rebase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rebase succeeded but post-rebase CI fails → don't retry merge, return False."""
    pm = _make_pr_manager()

    async def _failing_subprocess(*cmd: str, **kw: Any) -> str:
        if "merge" in cmd:
            raise RuntimeError("conflict")
        return ""

    async def _update_ok(*a: Any, **kw: Any) -> bool:
        return True

    async def _ci_fails(*a: Any, **kw: Any) -> tuple[bool, str]:
        return False, "regression test failed after rebase"

    monkeypatch.setattr("pr_manager.run_subprocess", _failing_subprocess)
    monkeypatch.setattr(pm, "update_pr_branch", _update_ok)
    monkeypatch.setattr(pm, "wait_for_ci", _ci_fails)
    monkeypatch.setattr(pm, "get_pr_title_and_body", AsyncMock(return_value=("", "")))

    ok = await pm.merge_pr(42, auto_rebase=True)
    assert ok is False


# --- merge_promotion_pr with auto_rebase=True --------------------------------


@pytest.mark.asyncio
async def test_merge_promotion_pr_auto_rebase_recovers_after_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same recovery semantics for RC PRs: rebase + re-CI + retry merge."""
    pm = _make_pr_manager()
    merge_calls = 0

    async def _flaky_subprocess(*cmd: str, **kw: Any) -> str:
        nonlocal merge_calls
        if "merge" in cmd:
            merge_calls += 1
            if merge_calls == 1:
                raise RuntimeError("not mergeable")
            return ""
        return ""

    async def _update_ok(*a: Any, **kw: Any) -> bool:
        return True

    async def _ci_passes(*a: Any, **kw: Any) -> tuple[bool, str]:
        return True, "CI passed"

    monkeypatch.setattr("pr_manager.run_subprocess", _flaky_subprocess)
    monkeypatch.setattr(pm, "update_pr_branch", _update_ok)
    monkeypatch.setattr(pm, "wait_for_ci", _ci_passes)

    ok = await pm.merge_promotion_pr(99, auto_rebase=True)
    assert ok is True
    assert merge_calls == 2


@pytest.mark.asyncio
async def test_merge_promotion_pr_auto_rebase_off_skips_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default auto_rebase=False: a single failed merge returns False, no retry."""
    pm = _make_pr_manager()

    async def _bad(*cmd: str, **kw: Any) -> str:
        raise RuntimeError("conflict")

    update_called = False

    async def _update(*a: Any, **kw: Any) -> bool:
        nonlocal update_called
        update_called = True
        return True

    monkeypatch.setattr("pr_manager.run_subprocess", _bad)
    monkeypatch.setattr(pm, "update_pr_branch", _update)

    ok = await pm.merge_promotion_pr(99)
    assert ok is False
    assert update_called is False
