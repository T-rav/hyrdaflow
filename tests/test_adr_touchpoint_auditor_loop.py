"""Unit tests for AdrTouchpointAuditorLoop (ADR-0056)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from adr_touchpoint_auditor_loop import AdrTouchpointAuditorLoop
from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus


def _deps(stop: asyncio.Event) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: True,
    )


def _write_adr(adr_dir: Path, *, number: int, title: str, related: list[str]) -> None:
    related_block = ", ".join(f"`{f}`" for f in related)
    body = (
        f"# ADR-{number:04d}: {title}\n\n"
        f"- **Status:** Accepted\n"
        f"- **Date:** 2026-01-01\n"
        f"- **Related:** {related_block}\n\n"
        f"## Context\n\nFixture body.\n"
    )
    (adr_dir / f"{number:04d}-{title.lower()}.md").write_text(body)


@pytest.fixture
def loop_env(tmp_path: Path):
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    _write_adr(adr_dir, number=24, title="alpha", related=["src/agent.py"])
    _write_adr(adr_dir, number=27, title="beta", related=["src/runner.py"])

    cfg = HydraFlowConfig(
        data_root=tmp_path,
        repo="hydra/hydraflow",
        repo_root=tmp_path,
    )
    state = MagicMock()
    state.get_adr_audit_cursor.return_value = "2026-05-01T00:00:00+00:00"
    state.get_adr_audit_attempts.return_value = 0
    state.inc_adr_audit_attempts.return_value = 1
    pr = AsyncMock()
    pr.create_issue = AsyncMock(return_value=42)
    dedup = MagicMock()
    dedup.get.return_value = set()

    from adr_index import ADRIndex  # noqa: PLC0415

    return cfg, state, pr, dedup, ADRIndex(adr_dir)


def test_worker_name_and_interval(loop_env) -> None:
    cfg, state, pr, dedup, idx = loop_env
    stop = asyncio.Event()
    loop = AdrTouchpointAuditorLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        adr_index=idx,
        deps=_deps(stop),
    )
    assert loop._worker_name == "adr_touchpoint_auditor"
    assert loop._get_default_interval() == 14400


async def test_first_run_seeds_cursor_and_returns(loop_env) -> None:
    """Empty cursor → seed it to 'now' and bail; no scan, no issues."""
    cfg, state, pr, dedup, idx = loop_env
    state.get_adr_audit_cursor.return_value = ""

    stop = asyncio.Event()
    loop = AdrTouchpointAuditorLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        adr_index=idx,
        deps=_deps(stop),
    )
    result = await loop._do_work()
    assert result == {"status": "seeded", "filed": 0, "scanned": 0}
    state.set_adr_audit_cursor.assert_called_once()
    pr.create_issue.assert_not_awaited()


async def test_drift_files_one_issue_per_drifted_adr(loop_env, monkeypatch) -> None:
    """A merged PR touching an ADR-cited src/ file (without the ADR in the diff) → 1 issue."""
    cfg, state, pr, dedup, idx = loop_env
    stop = asyncio.Event()
    loop = AdrTouchpointAuditorLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        adr_index=idx,
        deps=_deps(stop),
    )

    async def fake_list(_cursor):
        return [
            {
                "number": 8473,
                "mergedAt": "2026-05-06T20:00:00Z",
                "title": "feat: tweak",
                "files": [
                    {"path": "src/agent.py"},
                    {"path": "tests/test_agent.py"},
                ],
            }
        ]

    async def fake_reconcile():
        return None

    monkeypatch.setattr(loop, "_list_recent_merged_prs", fake_list)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", fake_reconcile)

    stats = await loop._do_work()
    assert stats["scanned"] == 1
    assert stats["filed"] == 1
    assert stats["escalated"] == 0
    title = pr.create_issue.await_args.args[0]
    assert "ADR-0024" in title
    assert "PR #8473" in title


async def test_no_drift_when_adr_in_diff(loop_env, monkeypatch) -> None:
    """ADR file in same diff → no drift, no issue filed."""
    cfg, state, pr, dedup, idx = loop_env
    stop = asyncio.Event()
    loop = AdrTouchpointAuditorLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        adr_index=idx,
        deps=_deps(stop),
    )

    async def fake_list(_cursor):
        return [
            {
                "number": 8474,
                "mergedAt": "2026-05-06T21:00:00Z",
                "files": [
                    {"path": "src/agent.py"},
                    {"path": "docs/adr/0024-alpha.md"},
                ],
            }
        ]

    async def fake_reconcile():
        return None

    monkeypatch.setattr(loop, "_list_recent_merged_prs", fake_list)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", fake_reconcile)

    stats = await loop._do_work()
    assert stats["scanned"] == 1
    assert stats["filed"] == 0
    pr.create_issue.assert_not_awaited()


async def test_dedup_prevents_refile_within_same_tick(loop_env, monkeypatch) -> None:
    """A finding already in dedup is skipped."""
    cfg, state, pr, dedup, idx = loop_env
    dedup.get.return_value = {"adr_touchpoint_auditor:PR-8473:ADR-0024"}

    stop = asyncio.Event()
    loop = AdrTouchpointAuditorLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        adr_index=idx,
        deps=_deps(stop),
    )

    async def fake_list(_cursor):
        return [
            {
                "number": 8473,
                "mergedAt": "2026-05-06T20:00:00Z",
                "files": [{"path": "src/agent.py"}],
            }
        ]

    async def fake_reconcile():
        return None

    monkeypatch.setattr(loop, "_list_recent_merged_prs", fake_list)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", fake_reconcile)

    stats = await loop._do_work()
    assert stats["filed"] == 0
    pr.create_issue.assert_not_awaited()


async def test_escalation_after_three_attempts(loop_env, monkeypatch) -> None:
    cfg, state, pr, dedup, idx = loop_env
    state.inc_adr_audit_attempts.return_value = 3

    stop = asyncio.Event()
    loop = AdrTouchpointAuditorLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        adr_index=idx,
        deps=_deps(stop),
    )

    async def fake_list(_cursor):
        return [
            {
                "number": 8473,
                "mergedAt": "2026-05-06T20:00:00Z",
                "files": [{"path": "src/agent.py"}],
            }
        ]

    async def fake_reconcile():
        return None

    monkeypatch.setattr(loop, "_list_recent_merged_prs", fake_list)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", fake_reconcile)

    stats = await loop._do_work()
    assert stats["escalated"] == 1
    assert stats["filed"] == 0
    labels = pr.create_issue.await_args.args[2]
    assert "hydraflow-hitl-escalation" in labels
    assert "hydraflow-adr-drift-stuck" in labels


async def test_cursor_advances_to_most_recent_merged_at(loop_env, monkeypatch) -> None:
    cfg, state, pr, dedup, idx = loop_env

    stop = asyncio.Event()
    loop = AdrTouchpointAuditorLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        adr_index=idx,
        deps=_deps(stop),
    )

    async def fake_list(_cursor):
        return [
            {
                "number": 1,
                "mergedAt": "2026-05-06T20:00:00Z",
                "files": [{"path": "README.md"}],
            },
            {
                "number": 2,
                "mergedAt": "2026-05-06T22:00:00Z",
                "files": [{"path": "README.md"}],
            },
        ]

    async def fake_reconcile():
        return None

    monkeypatch.setattr(loop, "_list_recent_merged_prs", fake_list)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", fake_reconcile)

    await loop._do_work()
    state.set_adr_audit_cursor.assert_called_with("2026-05-06T22:00:00Z")


async def test_kill_switch_short_circuits(loop_env) -> None:
    cfg, state, pr, dedup, idx = loop_env
    stop = asyncio.Event()
    deps = LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda name: name != "adr_touchpoint_auditor",
    )
    loop = AdrTouchpointAuditorLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        adr_index=idx,
        deps=deps,
    )
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    stats = await loop._do_work()
    assert stats == {"status": "disabled"}
    loop._reconcile_closed_escalations.assert_not_awaited()
    pr.create_issue.assert_not_awaited()


async def test_close_reconcile_clears_dedup(loop_env, monkeypatch) -> None:
    """Closed adr-drift-stuck escalations clear their dedup key + attempt counter."""
    cfg, state, pr, dedup, idx = loop_env
    stuck_attempt_key = "PR-8473:ADR-0024"
    full_dedup_key = f"adr_touchpoint_auditor:{stuck_attempt_key}"
    current = {full_dedup_key, "adr_touchpoint_auditor:PR-9000:ADR-0042"}
    dedup.get.return_value = current

    stop = asyncio.Event()
    loop = AdrTouchpointAuditorLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        adr_index=idx,
        deps=_deps(stop),
    )

    closed_payload = json.dumps(
        [{"title": f"HITL: ADR drift {stuck_attempt_key} unresolved after 3"}]
    ).encode()

    class _FakeProc:
        returncode = 0

        async def communicate(self):
            return closed_payload, b""

    async def fake_exec(*_args, **_kwargs):
        return _FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    await loop._reconcile_closed_escalations()

    dedup.set_all.assert_called_once()
    remaining = dedup.set_all.call_args.args[0]
    assert full_dedup_key not in remaining
    assert "adr_touchpoint_auditor:PR-9000:ADR-0042" in remaining
    state.clear_adr_audit_attempts.assert_called_once_with(stuck_attempt_key)
