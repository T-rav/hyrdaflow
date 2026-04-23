"""Tests for PrinciplesAuditLoop."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps
from config import HydraFlowConfig, ManagedRepo
from events import EventBus
from principles_audit_loop import PrinciplesAuditLoop


def _deps(stop: asyncio.Event) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: True,
    )


@pytest.fixture
def loop_env(tmp_path: Path):
    cfg = HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow")
    cfg.managed_repos = []
    state = MagicMock()
    state.blocked_slugs.return_value = set()
    state.get_onboarding_status.return_value = None
    state.get_last_green_audit.return_value = {}
    state.get_drift_attempts.return_value = 0
    pr_manager = AsyncMock()
    pr_manager.create_issue = AsyncMock(return_value=42)
    return cfg, state, pr_manager


def test_skeleton_worker_name_and_interval(loop_env):
    cfg, state, pr = loop_env
    stop = asyncio.Event()
    loop = PrinciplesAuditLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        deps=_deps(stop),
    )
    assert loop._worker_name == "principles_audit"  # type: ignore[attr-defined]
    assert loop._get_default_interval() == 604800  # spec §4.4


async def test_audit_hydraflow_self_saves_snapshot(loop_env, tmp_path, monkeypatch):
    cfg, state, pr = loop_env
    stop = asyncio.Event()
    loop = PrinciplesAuditLoop(config=cfg, state=state, pr_manager=pr, deps=_deps(stop))

    fake_findings = [
        {
            "check_id": "P1.1",
            "status": "PASS",
            "severity": "STRUCTURAL",
            "principle": "P1",
            "source": "docs/adr",
            "what": "doc exists",
            "remediation": "write docs",
            "message": "",
        },
        {
            "check_id": "P2.4",
            "status": "PASS",
            "severity": "BEHAVIORAL",
            "principle": "P2",
            "source": "Makefile",
            "what": "target runs",
            "remediation": "fix target",
            "message": "",
        },
    ]

    async def fake_run_audit(slug, repo_root):
        return {"summary": {}, "findings": fake_findings}

    monkeypatch.setattr(loop, "_run_audit", fake_run_audit)

    snapshot = await loop._audit_hydraflow_self()
    assert snapshot == {"P1.1": "PASS", "P2.4": "PASS"}
    snap_dir = cfg.data_root / "hydraflow-self" / "audit"
    saved = list(snap_dir.glob("*.json"))
    assert len(saved) == 1


async def test_audit_managed_repo_clones_or_fetches(loop_env, tmp_path, monkeypatch):
    cfg, state, pr = loop_env
    stop = asyncio.Event()
    loop = PrinciplesAuditLoop(config=cfg, state=state, pr_manager=pr, deps=_deps(stop))
    mr = ManagedRepo(slug="acme/widget")
    commands: list[list[str]] = []

    async def fake_run_git(*args, cwd=None):
        commands.append(list(args))
        return 0, ""

    async def fake_run_audit(slug, repo_root):
        return {
            "findings": [
                {
                    "check_id": "P1.1",
                    "status": "PASS",
                    "severity": "STRUCTURAL",
                    "principle": "P1",
                    "source": "",
                    "what": "",
                    "remediation": "",
                    "message": "",
                }
            ]
        }

    monkeypatch.setattr(loop, "_run_git", fake_run_git)
    monkeypatch.setattr(loop, "_run_audit", fake_run_audit)
    snap = await loop._audit_managed_repo(mr)
    assert snap == {"P1.1": "PASS"}
    # first run → clone
    assert any("clone" in c for c in commands)

    # second call with dir present → fetch
    (cfg.data_root / "acme/widget" / "audit-checkout").mkdir(
        parents=True, exist_ok=True
    )
    commands.clear()
    await loop._audit_managed_repo(mr)
    assert any("fetch" in c for c in commands)
