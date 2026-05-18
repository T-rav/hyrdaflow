"""Regression: ContractRefreshLoop PRs must target the configured base branch.

Per CLAUDE.md (ADR-0042 two-tier branch model): "PRs target staging, not main.
Only RC promotion PRs use --base main." ``ContractRefreshLoop._open_refresh_pr``
defaulted to ``main`` (the ``open_automated_pr_async`` parameter default),
which meant every contract-refresh PR was opened against a protected branch
that requires an RC promotion to merge into. The "auto-merge" label and
``auto_merge=True`` flag both became no-ops because the merge gate at GitHub
was unreachable — the closed-loop "drift → PR → auto-merge → clean tick"
chain was broken at step 3.

The fix is the same pattern repo_wiki_loop already uses:
``base=self._config.base_branch()``. The helper returns ``staging_branch``
when ``staging_enabled`` is true (the dark-factory norm) and ``main_branch``
otherwise — so refresh PRs land where the auto-merge gate can actually fire.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import contract_refresh_loop as crl_module
from auto_pr import AutoPrResult
from base_background_loop import LoopDeps
from config import HydraFlowConfig
from contract_refresh_loop import ContractRefreshLoop
from events import EventBus


class _CaptureAutoPR:
    """Captures ``open_automated_pr_async`` kwargs for assertion."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> AutoPrResult:
        self.calls.append(kwargs)
        return AutoPrResult(
            status="opened",
            pr_url="https://github.com/x/y/pull/1",
            branch=kwargs.get("branch", ""),
        )


def _loop(tmp_path: Path, **config_overrides: Any) -> ContractRefreshLoop:
    cfg = HydraFlowConfig(
        data_root=tmp_path / "data",
        repo_root=tmp_path / "repo",
        repo="hydra/hydraflow",
        **config_overrides,
    )
    (tmp_path / "repo").mkdir(parents=True, exist_ok=True)
    stop = asyncio.Event()
    deps = LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=MagicMock(),
        enabled_cb=lambda _: True,
        sleep_fn=AsyncMock(),
    )
    return ContractRefreshLoop(
        config=cfg, prs=AsyncMock(), state=MagicMock(), deps=deps
    )


@pytest.mark.asyncio
async def test_refresh_pr_targets_staging_when_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With ``staging_enabled=True``, the refresh PR must target staging,
    not main — otherwise auto-merge can never fire against the protected
    main branch and the closed-loop chain is broken."""
    capture = _CaptureAutoPR()
    monkeypatch.setattr(crl_module, "open_automated_pr_async", capture)

    loop = _loop(tmp_path, staging_enabled=True)
    drifted = tmp_path / "drift.yaml"
    drifted.write_text("x")
    fleet = crl_module.FleetDriftReport(
        reports=[
            crl_module.AdapterDriftReport(
                adapter="git",
                drifted_cassettes=[drifted],
                new_cassettes=[],
                deleted_cassettes=[],
            )
        ],
        has_drift=True,
    )

    pr_url = await loop._open_refresh_pr([drifted], fleet)

    assert pr_url == "https://github.com/x/y/pull/1"
    assert len(capture.calls) == 1
    base = capture.calls[0].get("base")
    expected = loop._config.base_branch()
    assert base == expected, (
        f"refresh PR opened against {base!r}; expected {expected!r} (the "
        f"configured base_branch) — refresh PRs targeting main can't auto-merge "
        f"under ADR-0042 branch protection"
    )
    assert capture.calls[0].get("auto_merge") is True


@pytest.mark.asyncio
async def test_refresh_pr_targets_main_when_staging_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When staging is disabled, base_branch() returns main_branch — the
    fix must respect that, not hardcode staging."""
    capture = _CaptureAutoPR()
    monkeypatch.setattr(crl_module, "open_automated_pr_async", capture)

    loop = _loop(tmp_path, staging_enabled=False)
    drifted = tmp_path / "drift.yaml"
    drifted.write_text("x")
    fleet = crl_module.FleetDriftReport(
        reports=[
            crl_module.AdapterDriftReport(
                adapter="git",
                drifted_cassettes=[drifted],
                new_cassettes=[],
                deleted_cassettes=[],
            )
        ],
        has_drift=True,
    )

    await loop._open_refresh_pr([drifted], fleet)

    assert len(capture.calls) == 1
    assert capture.calls[0].get("base") == loop._config.main_branch
