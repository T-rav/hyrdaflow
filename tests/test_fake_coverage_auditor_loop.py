"""Tests for FakeCoverageAuditorLoop (spec §4.7)."""

from __future__ import annotations

import asyncio
import json  # noqa: F401 — used by appended tick-behavior tests below
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml  # noqa: F401 — used by appended tick-behavior tests below

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from fake_coverage_auditor_loop import (
    FakeCoverageAuditorLoop,
    catalog_cassette_methods,
    catalog_fake_methods,
)


def _deps(stop: asyncio.Event) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: True,
    )


@pytest.fixture
def loop_env(tmp_path: Path):
    cfg = HydraFlowConfig(
        data_root=tmp_path, repo="hydra/hydraflow", repo_root=tmp_path
    )
    state = MagicMock()
    state.get_fake_coverage_last_known.return_value = {}
    state.get_fake_coverage_attempts.return_value = 0
    # Default: returns 1 (< _MAX_ATTEMPTS=3) so gap filing path is taken.
    # Escalation tests override this explicitly.
    state.inc_fake_coverage_attempts.return_value = 1
    pr = AsyncMock()
    pr.create_issue = AsyncMock(return_value=42)
    dedup = MagicMock()
    dedup.get.return_value = set()
    return cfg, state, pr, dedup


def test_skeleton_worker_name_and_interval(loop_env) -> None:
    cfg, state, pr, dedup = loop_env
    stop = asyncio.Event()
    loop = FakeCoverageAuditorLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )
    assert loop._worker_name == "fake_coverage_auditor"
    assert loop._get_default_interval() == 604800


def test_catalog_fake_methods_splits_surface_vs_helper(tmp_path: Path) -> None:
    fake_dir = tmp_path / "fakes"
    fake_dir.mkdir()
    (fake_dir / "fake_github.py").write_text(
        "from dataclasses import dataclass\n\n"
        "class FakeGitHub:\n"
        "    async def create_issue(self, title, body, labels): ...\n"
        "    async def close_issue(self, num): ...\n"
        "    def script_ci(self, events): ...\n"
        "    def fail_service(self, reason): ...\n"
        "    def _private(self): ...\n"
    )

    cat = catalog_fake_methods(fake_dir)
    assert "FakeGitHub" in cat
    surface = set(cat["FakeGitHub"]["adapter-surface"])
    helpers = set(cat["FakeGitHub"]["test-helper"])
    assert surface == {"create_issue", "close_issue"}
    assert helpers == {"script_ci", "fail_service"}


def test_catalog_cassette_methods_reads_input_command(tmp_path: Path) -> None:
    import yaml

    cassettes = tmp_path / "cassettes" / "github"
    cassettes.mkdir(parents=True)
    (cassettes / "create_issue.yaml").write_text(
        yaml.safe_dump({"input": {"command": "create_issue"}, "output": {}})
    )
    (cassettes / "close_issue.yaml").write_text(
        yaml.safe_dump({"input": {"command": "close_issue"}, "output": {}})
    )
    methods = catalog_cassette_methods(cassettes)
    assert methods == {"create_issue", "close_issue"}


async def test_do_work_files_surface_gap(loop_env, monkeypatch, tmp_path) -> None:
    """Un-cassetted public method → one ``adapter-surface`` issue."""
    cfg, state, pr, dedup = loop_env
    fake_dir = tmp_path / "src" / "mockworld" / "fakes"
    fake_dir.mkdir(parents=True)
    (fake_dir / "fake_github.py").write_text(
        "class FakeGitHub:\n"
        "    async def create_issue(self, title): ...\n"
        "    async def close_issue(self, n): ...\n"
    )
    cassettes = tmp_path / "tests" / "trust" / "contracts" / "cassettes" / "github"
    cassettes.mkdir(parents=True)
    # Note: plan draft used .json; real catalog_cassette_methods scans *.yaml
    # per §4.2 cassette schema. See plan deviation note (C4).
    (cassettes / "create_issue.yaml").write_text(
        yaml.safe_dump({"input": {"command": "create_issue"}, "output": {}})
    )
    # close_issue uncassetted → expect one adapter-surface gap.

    stop = asyncio.Event()
    loop = FakeCoverageAuditorLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    async def fake_reconcile():
        return None

    monkeypatch.setattr(loop, "_reconcile_closed_escalations", fake_reconcile)

    stats = await loop._do_work()
    assert stats["filed"] == 1
    labels = pr.create_issue.await_args.args[2]
    assert "adapter-surface" in labels
    assert "fake-coverage-gap" in labels


async def test_do_work_files_helper_gap(loop_env, monkeypatch, tmp_path) -> None:
    """Un-exercised ``script_*`` helper → one ``test-helper`` issue."""
    cfg, state, pr, dedup = loop_env
    fake_dir = tmp_path / "src" / "mockworld" / "fakes"
    fake_dir.mkdir(parents=True)
    (fake_dir / "fake_docker.py").write_text(
        "class FakeDocker:\n    def script_run(self, events): ...\n"
    )
    cassettes = tmp_path / "tests" / "trust" / "contracts" / "cassettes" / "docker"
    cassettes.mkdir(parents=True)

    stop = asyncio.Event()
    loop = FakeCoverageAuditorLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    async def fake_reconcile():
        return None

    async def fake_grep(helper):
        return False  # no scenario calls the helper

    monkeypatch.setattr(loop, "_reconcile_closed_escalations", fake_reconcile)
    monkeypatch.setattr(loop, "_grep_scenario_for_helper", fake_grep)

    stats = await loop._do_work()
    assert stats["filed"] == 1
    labels = pr.create_issue.await_args.args[2]
    assert "test-helper" in labels
    title = pr.create_issue.await_args.args[0]
    assert "script_run" in title


async def test_escalation_fires_after_three_attempts(
    loop_env, monkeypatch, tmp_path
) -> None:
    """3rd re-file of a stuck gap → ``hitl-escalation`` issue, not another gap."""
    cfg, state, pr, dedup = loop_env
    state.inc_fake_coverage_attempts.return_value = 3
    fake_dir = tmp_path / "src" / "mockworld" / "fakes"
    fake_dir.mkdir(parents=True)
    (fake_dir / "fake_github.py").write_text(
        "class FakeGitHub:\n    async def missing(self): ...\n"
    )
    (tmp_path / "tests" / "trust" / "contracts" / "cassettes" / "github").mkdir(
        parents=True
    )

    stop = asyncio.Event()
    loop = FakeCoverageAuditorLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    async def fake_reconcile():
        return None

    monkeypatch.setattr(loop, "_reconcile_closed_escalations", fake_reconcile)

    stats = await loop._do_work()
    assert stats["escalated"] == 1
    labels = pr.create_issue.await_args.args[2]
    assert "hitl-escalation" in labels
    assert "fake-coverage-stuck" in labels


async def test_close_reconcile_clears_dedup_on_closed_escalation(
    loop_env, monkeypatch, tmp_path
) -> None:
    """Closed ``fake-coverage-stuck`` issues clear their dedup key + attempts."""
    cfg, state, pr, dedup = loop_env
    stuck_key = "fake_coverage_auditor:FakeGitHub.missing:adapter-surface"
    current = {stuck_key, "fake_coverage_auditor:FakeGitHub.other:adapter-surface"}
    dedup.get.return_value = current

    stop = asyncio.Event()
    loop = FakeCoverageAuditorLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    closed_payload = json.dumps(
        [{"title": "HITL: fake coverage gap FakeGitHub.missing:adapter-surface ..."}]
    ).encode()

    class _FakeProc:
        returncode = 0

        async def communicate(self):
            return closed_payload, b""

    async def fake_exec(*_args, **_kwargs):
        return _FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    await loop._reconcile_closed_escalations()

    # Only the closed key was cleared; the other key remains.
    dedup.set_all.assert_called_once()
    remaining = dedup.set_all.call_args.args[0]
    assert stuck_key not in remaining
    assert "fake_coverage_auditor:FakeGitHub.other:adapter-surface" in remaining
    state.clear_fake_coverage_attempts.assert_called_once_with(
        "FakeGitHub.missing:adapter-surface"
    )


@pytest.mark.asyncio
async def test_kill_switch_short_circuits_do_work(loop_env) -> None:
    """Disabled kill-switch → _do_work returns `disabled` and skips reconcile (ADR-0049)."""
    cfg, state, pr, dedup = loop_env
    stop = asyncio.Event()
    deps = LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda name: name != "fake_coverage_auditor",
    )
    loop = FakeCoverageAuditorLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=deps
    )
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    stats = await loop._do_work()
    assert stats == {"status": "disabled"}
    loop._reconcile_closed_escalations.assert_not_awaited()
    pr.create_issue.assert_not_awaited()
