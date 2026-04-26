"""AutoAgentPreflightLoop scaffolding tests (spec §2.1, §5.1)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from auto_agent_preflight_loop import AutoAgentPreflightLoop
from tests.helpers import make_bg_loop_deps


def _make_loop(tmp_path: Path, *, enabled: bool = True, **config_overrides):
    deps = make_bg_loop_deps(tmp_path, enabled=enabled, **config_overrides)
    state = MagicMock()
    state.get_auto_agent_daily_spend = MagicMock(return_value=0.0)
    pr = AsyncMock()
    audit = MagicMock()
    loop = AutoAgentPreflightLoop(
        config=deps.config,
        state=state,
        pr_manager=pr,
        wiki_store=None,
        audit_store=audit,
        deps=deps.loop_deps,
    )
    return loop, state


def test_worker_name(tmp_path: Path) -> None:
    loop, _ = _make_loop(tmp_path)
    assert loop._worker_name == "auto_agent_preflight"


def test_default_interval_from_config(tmp_path: Path) -> None:
    loop, _ = _make_loop(tmp_path, auto_agent_preflight_interval=180)
    assert loop._get_default_interval() == 180


@pytest.mark.asyncio
async def test_kill_switch_short_circuits(tmp_path: Path) -> None:
    loop, _ = _make_loop(tmp_path, enabled=False)
    result = await loop._do_work()
    assert result == {"status": "disabled"}


@pytest.mark.asyncio
async def test_daily_budget_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # auto_agent_daily_budget_usd is an opt-float field driven by env var in
    # the model_validator; set the env var so ConfigFactory picks it up.
    monkeypatch.setenv("HYDRAFLOW_AUTO_AGENT_DAILY_BUDGET_USD", "50.0")
    loop, state = _make_loop(tmp_path)
    state.get_auto_agent_daily_spend = MagicMock(return_value=51.0)
    result = await loop._do_work()
    assert result["status"] == "budget_exceeded"
    assert result["cap_usd"] == 50.0


@pytest.mark.asyncio
async def test_no_cap_passes_gate(tmp_path: Path) -> None:
    loop, state = _make_loop(tmp_path)  # cap = None
    state.get_auto_agent_daily_spend = MagicMock(return_value=999.0)
    result = await loop._do_work()
    assert result["status"] == "ok"
