"""Tests for StagingBisectLoop (spec §4.3)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from state import StateTracker


def _make_cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> HydraFlowConfig:
    monkeypatch.setenv("HYDRAFLOW_STAGING_ENABLED", "true")
    monkeypatch.setenv("HYDRAFLOW_STAGING_BISECT_INTERVAL", "600")
    return HydraFlowConfig(
        repo_root=tmp_path,
        workspace_base=tmp_path / "wt",
        state_file=tmp_path / "s.json",
        data_root=tmp_path / "data",
    )


def _make_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[object, MagicMock, StateTracker]:
    from staging_bisect_loop import StagingBisectLoop

    cfg = _make_cfg(tmp_path, monkeypatch)
    stop_event = asyncio.Event()

    async def _sleep(_s: float) -> None:
        return None

    loop_deps = LoopDeps(
        event_bus=EventBus(),
        stop_event=stop_event,
        status_cb=MagicMock(),
        enabled_cb=lambda _n: True,
        sleep_fn=_sleep,
    )
    prs = MagicMock()
    state = StateTracker(state_file=tmp_path / "s.json")
    loop = StagingBisectLoop(config=cfg, prs=prs, deps=loop_deps, state=state)
    return loop, prs, state


class TestSkeleton:
    @pytest.mark.asyncio
    async def test_do_work_returns_noop_when_no_red_sha(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _prs, state = _make_loop(tmp_path, monkeypatch)
        assert state.get_last_rc_red_sha() == ""
        result = await loop._do_work()  # type: ignore[attr-defined]
        assert result == {"status": "no_red"}

    @pytest.mark.asyncio
    async def test_do_work_idempotent_on_already_processed_sha(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _prs, state = _make_loop(tmp_path, monkeypatch)
        state.set_last_rc_red_sha_and_bump_cycle("abc")
        loop._last_processed_rc_red_sha = "abc"  # type: ignore[attr-defined]
        result = await loop._do_work()  # type: ignore[attr-defined]
        assert result == {"status": "already_processed", "sha": "abc"}

    @pytest.mark.asyncio
    async def test_do_work_noop_when_staging_disabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _prs, _state = _make_loop(tmp_path, monkeypatch)
        # _make_cfg sets STAGING_ENABLED=true; override on the constructed
        # config for this scenario (env is read at config-construct time).
        loop._config.staging_enabled = False  # type: ignore[attr-defined]
        result = await loop._do_work()  # type: ignore[attr-defined]
        assert result == {"status": "staging_disabled"}

    def test_interval_uses_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _prs, _state = _make_loop(tmp_path, monkeypatch)
        assert loop._get_default_interval() == 600  # type: ignore[attr-defined]
