"""MockWorld scenario for rebase-on-conflict (PR #8482).

Drives ``StagingPromotionLoop._handle_open_promotion`` against a REAL
``PRManager`` (not a port-level mock), with subprocess + ``_run_gh``
scripted at the boundary. Verifies the full recovery cycle wires
end-to-end:

  1. CI passes on the open RC PR
  2. First merge attempt fails (subprocess raises — simulates
     "PR head behind target")
  3. ``PRManager.update_pr_branch`` is called and succeeds
  4. CI re-polls and passes
  5. Second merge attempt succeeds
  6. Loop returns ``{"status": "promoted", "pr": ...}``

This catches integration bugs unit tests can't see — e.g. a typo in the
``auto_rebase=True`` kwarg path between loop and PR manager, or a state
leak between the first failed merge and the second successful one.

Per docs/standards/testing/README.md §"How to write each layer" Pattern B,
loop-level scenarios use direct instantiation. We construct a real
``PRManager`` so the recovery flow runs through actual code; only the
external I/O boundary (``run_subprocess``, ``_run_gh``) is monkeypatched.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.helpers import ConfigFactory, make_pr_manager

pytestmark = pytest.mark.scenario_loops


def _make_staging_loop(tmp_path: Any, config_overrides: dict[str, Any]) -> Any:
    """Build a real PRManager + a StagingPromotionLoop pointing at it."""
    from base_background_loop import LoopDeps
    from events import EventBus
    from staging_promotion_loop import StagingPromotionLoop

    base_config = ConfigFactory.create(repo_root=tmp_path / "repo")
    config = base_config.model_copy(
        update={"staging_enabled": True, **config_overrides}
    )

    bus = EventBus()
    prs = make_pr_manager(config=config, event_bus=AsyncMock())

    stop_event = asyncio.Event()
    stop_event.set()
    deps = LoopDeps(
        event_bus=bus,
        stop_event=stop_event,
        status_cb=MagicMock(),
        enabled_cb=lambda _: True,
        sleep_fn=AsyncMock(),
    )
    loop = StagingPromotionLoop(config=config, prs=prs, deps=deps)
    return loop, prs, config


@pytest.mark.asyncio
async def test_promotion_recovers_via_auto_rebase_end_to_end(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """First merge subprocess fails → update_pr_branch succeeds → second merge succeeds → loop reports promoted."""
    loop, prs, config = _make_staging_loop(tmp_path, {})

    # Existing open promotion PR — short-circuits the cadence path.
    prs.find_open_promotion_pr = AsyncMock(  # type: ignore[method-assign]
        return_value=MagicMock(number=42)
    )
    # CI passes both polls (initial + post-rebase).
    prs.wait_for_ci = AsyncMock(return_value=(True, "all green"))  # type: ignore[method-assign]

    # Script the gh subprocess: first merge raises (head behind),
    # update-branch succeeds, second merge succeeds.
    merge_attempts = 0

    async def _scripted_run_subprocess(*cmd: str, **_kw: Any) -> str:
        nonlocal merge_attempts
        if "merge" in cmd:
            merge_attempts += 1
            if merge_attempts == 1:
                raise RuntimeError("Pull Request is not mergeable: head is behind base")
            return ""
        return ""

    monkeypatch.setattr("pr_manager.run_subprocess", _scripted_run_subprocess)

    update_calls = 0

    async def _scripted_run_gh(*cmd: str, cwd: Any = None) -> str:
        nonlocal update_calls
        joined = " ".join(cmd)
        if "update-branch" in joined:
            update_calls += 1
            return ""
        return ""

    monkeypatch.setattr(prs, "_run_gh", _scripted_run_gh)

    # PRManager's get_pr_head_sha is exercised in the success path —
    # provide a stable SHA so the loop's last-green-rc-sha record path doesn't crash.
    prs.get_pr_head_sha = AsyncMock(return_value="abc123def456")  # type: ignore[method-assign]

    result = await loop._handle_open_promotion(42)

    assert result == {"status": "promoted", "pr": 42}
    assert merge_attempts == 2, (
        "first merge should have failed, second should have succeeded"
    )
    assert update_calls == 1, "update_pr_branch should have been invoked exactly once"


@pytest.mark.asyncio
async def test_promotion_real_conflict_falls_through_to_failure_path(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When update_pr_branch returns False (real conflict), loop's existing failure path fires."""
    loop, prs, config = _make_staging_loop(tmp_path, {})

    prs.find_open_promotion_pr = AsyncMock(  # type: ignore[method-assign]
        return_value=MagicMock(number=99)
    )
    prs.wait_for_ci = AsyncMock(return_value=(True, "all green"))  # type: ignore[method-assign]

    async def _failing_subprocess(*cmd: str, **_kw: Any) -> str:
        if "merge" in cmd:
            raise RuntimeError("Pull Request is not mergeable: conflict")
        return ""

    monkeypatch.setattr("pr_manager.run_subprocess", _failing_subprocess)

    async def _failing_run_gh(*cmd: str, cwd: Any = None) -> str:
        if "update-branch" in " ".join(cmd):
            # GitHub returns 422 — real conflict it can't auto-rebase.
            raise RuntimeError("HTTP 422: Validation Failed (update-branch)")
        return ""

    monkeypatch.setattr(prs, "_run_gh", _failing_run_gh)

    result = await loop._handle_open_promotion(99)

    # Loop returns "merge_failed" — the existing failure-handling code in
    # _handle_open_promotion now logs a warning. Importantly, the PR is
    # NOT auto-closed in this branch (only ci_failed closes the PR).
    assert result == {"status": "merge_failed", "pr": 99}


@pytest.mark.asyncio
async def test_promotion_first_attempt_succeeds_no_recovery_needed(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The happy path: first merge succeeds, update_pr_branch never called."""
    loop, prs, config = _make_staging_loop(tmp_path, {})

    prs.find_open_promotion_pr = AsyncMock(  # type: ignore[method-assign]
        return_value=MagicMock(number=7)
    )
    prs.wait_for_ci = AsyncMock(return_value=(True, "green"))  # type: ignore[method-assign]
    prs.get_pr_head_sha = AsyncMock(return_value="happysha")  # type: ignore[method-assign]

    update_calls = 0

    async def _scripted_run_gh(*cmd: str, cwd: Any = None) -> str:
        nonlocal update_calls
        if "update-branch" in " ".join(cmd):
            update_calls += 1
        return ""

    async def _ok_subprocess(*cmd: str, **_kw: Any) -> str:
        return ""

    monkeypatch.setattr("pr_manager.run_subprocess", _ok_subprocess)
    monkeypatch.setattr(prs, "_run_gh", _scripted_run_gh)

    result = await loop._handle_open_promotion(7)

    assert result == {"status": "promoted", "pr": 7}
    assert update_calls == 0, (
        "update_pr_branch should NOT fire when first merge succeeds"
    )
