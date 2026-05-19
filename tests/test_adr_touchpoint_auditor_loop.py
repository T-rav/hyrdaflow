"""Unit tests for AdrTouchpointAuditorLoop (ADR-0056 + #8987 rollup).

Per-ADR rollup behavior (#8987): one issue per ADR listing all PRs that
drifted it. Subsequent ticks update the body. Dedup key is
``adr_touchpoint_auditor:ADR-NNNN`` (no PR component).
"""

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


def _state_mock() -> MagicMock:
    """Build a MagicMock state with rollup-aware defaults."""
    state = MagicMock()
    state.get_adr_audit_cursor.return_value = "2026-05-01T00:00:00+00:00"
    state.get_adr_audit_attempts.return_value = 0
    state.inc_adr_audit_attempts.return_value = 1
    state.get_adr_rollup.return_value = None
    return state


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
    state = _state_mock()
    pr = AsyncMock()
    pr.create_issue = AsyncMock(return_value=42)
    pr.update_issue_body = AsyncMock(return_value=None)
    pr.close_issue = AsyncMock(return_value=None)
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


async def test_drift_files_one_rollup_per_adr(loop_env, monkeypatch) -> None:
    """A merged PR touching an ADR-cited src/ file → 1 rollup issue."""
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
    assert stats["updated"] == 0
    assert stats["escalated"] == 0
    title = pr.create_issue.await_args.args[0]
    body = pr.create_issue.await_args.args[1]
    assert "ADR-0024" in title
    assert "1 PR" in title  # rollup count
    assert "PR #8473" in title or "#8473" in body
    # Rollup state was recorded so the next tick can update in-place.
    state.set_adr_rollup.assert_called_once()
    call_kwargs = state.set_adr_rollup.call_args.kwargs
    assert call_kwargs["pr_numbers"] == [8473]
    assert call_kwargs["issue_number"] == 42


async def test_one_pr_drifting_8_adrs_files_8_issues(loop_env, monkeypatch) -> None:
    """A single PR drifting 8 ADRs files 8 issues (one per ADR)."""
    cfg, state, pr, dedup, idx = loop_env
    # Add 8 ADRs each citing a distinct file the PR will touch.
    adr_dir = cfg.repo_root / "docs" / "adr"
    for i in range(8):
        _write_adr(
            adr_dir,
            number=100 + i,
            title=f"big{i}",
            related=[f"src/big{i}.py"],
        )
    from adr_index import ADRIndex  # noqa: PLC0415

    idx = ADRIndex(adr_dir)

    pr.create_issue = AsyncMock(side_effect=list(range(200, 208)))

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
                "number": 8500,
                "mergedAt": "2026-05-07T20:00:00Z",
                "files": [{"path": f"src/big{i}.py"} for i in range(8)],
            }
        ]

    monkeypatch.setattr(loop, "_list_recent_merged_prs", fake_list)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", AsyncMock())

    stats = await loop._do_work()
    assert stats["filed"] == 8
    assert pr.create_issue.await_count == 8


async def test_three_prs_drifting_same_adr_file_one_rollup(
    loop_env, monkeypatch
) -> None:
    """3 PRs drifting the same ADR file ONE issue with all 3 PRs in body."""
    cfg, state, pr, dedup, idx = loop_env
    pr.create_issue = AsyncMock(return_value=555)

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
                "number": 8501,
                "mergedAt": "2026-05-07T10:00:00Z",
                "files": [{"path": "src/agent.py"}],
            },
            {
                "number": 8502,
                "mergedAt": "2026-05-07T11:00:00Z",
                "files": [{"path": "src/agent.py"}],
            },
            {
                "number": 8503,
                "mergedAt": "2026-05-07T12:00:00Z",
                "files": [{"path": "src/agent.py"}],
            },
        ]

    monkeypatch.setattr(loop, "_list_recent_merged_prs", fake_list)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", AsyncMock())

    stats = await loop._do_work()
    assert stats["filed"] == 1
    assert pr.create_issue.await_count == 1
    body = pr.create_issue.await_args.args[1]
    assert "#8501" in body
    assert "#8502" in body
    assert "#8503" in body
    # Rollup pr_numbers persisted to state.
    pr_numbers = state.set_adr_rollup.call_args.kwargs["pr_numbers"]
    assert sorted(pr_numbers) == [8501, 8502, 8503]


async def test_subsequent_tick_updates_body_with_new_prs(loop_env, monkeypatch) -> None:
    """Tick N+1 with a new PR drifting same ADR → update_issue_body, no new issue."""
    cfg, state, pr, dedup, idx = loop_env
    # Existing rollup state from a previous tick.
    state.get_adr_rollup.return_value = {
        "issue_number": 999,
        "pr_numbers": [8501],
    }

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
                "number": 8502,
                "mergedAt": "2026-05-07T22:00:00Z",
                "files": [{"path": "src/agent.py"}],
            }
        ]

    monkeypatch.setattr(loop, "_list_recent_merged_prs", fake_list)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", AsyncMock())

    stats = await loop._do_work()
    assert stats["filed"] == 0
    assert stats["updated"] == 1
    pr.create_issue.assert_not_awaited()
    pr.update_issue_body.assert_awaited_once()
    issue_number_arg, body_arg = pr.update_issue_body.await_args.args
    assert issue_number_arg == 999
    assert "#8501" in body_arg
    assert "#8502" in body_arg
    # State persists the merged PR set.
    merged = state.set_adr_rollup.call_args.kwargs["pr_numbers"]
    assert merged == [8501, 8502]


async def test_pr_gaining_adr_coverage_removed_from_rollup(
    loop_env, monkeypatch
) -> None:
    """A PR added in tick N, then ADR file updated in tick N+1 → rollup closed."""
    cfg, state, pr, dedup, idx = loop_env
    state.get_adr_rollup.return_value = {
        "issue_number": 999,
        "pr_numbers": [8501],
    }
    dedup.get.return_value = {"adr_touchpoint_auditor:ADR-0024"}

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
                "number": 8502,
                "mergedAt": "2026-05-07T22:00:00Z",
                "files": [
                    {"path": "src/agent.py"},
                    {"path": "docs/adr/0024-alpha.md"},
                ],
            }
        ]

    monkeypatch.setattr(loop, "_list_recent_merged_prs", fake_list)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", AsyncMock())

    stats = await loop._do_work()
    assert stats["closed"] == 1
    assert stats["filed"] == 0
    pr.close_issue.assert_awaited_once_with(999)
    state.clear_adr_rollup.assert_called_with("ADR-0024")
    state.clear_adr_audit_attempts.assert_called_with("ADR-0024")
    # Dedup key cleaned up.
    dedup.set_all.assert_called()
    last_set = dedup.set_all.call_args.args[0]
    assert "adr_touchpoint_auditor:ADR-0024" not in last_set


async def test_adr_file_in_diff_closes_rollup_no_new_issue(
    loop_env, monkeypatch
) -> None:
    """ADR's own file in diff and no open rollup → no issue filed, no close."""
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

    monkeypatch.setattr(loop, "_list_recent_merged_prs", fake_list)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", AsyncMock())

    stats = await loop._do_work()
    assert stats["filed"] == 0
    pr.create_issue.assert_not_awaited()
    pr.close_issue.assert_not_awaited()


async def test_escalation_after_three_attempts(loop_env, monkeypatch) -> None:
    """3-strikes escalation triggers per-ADR rollup."""
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

    monkeypatch.setattr(loop, "_list_recent_merged_prs", fake_list)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", AsyncMock())

    stats = await loop._do_work()
    assert stats["escalated"] == 1
    assert stats["filed"] == 0
    labels = pr.create_issue.await_args.args[2]
    assert "hydraflow-hitl-escalation" in labels
    assert "hydraflow-adr-drift-stuck" in labels
    # The 3-strike attempt counter key is per ADR, not per (PR, ADR).
    state.inc_adr_audit_attempts.assert_called_with("ADR-0024")


async def test_escalation_does_not_storm_after_threshold(loop_env, monkeypatch) -> None:
    """Regression for the #8993 review finding: escalation fires exactly
    once when the per-ADR attempt counter crosses ``_MAX_ATTEMPTS`` (==3),
    not on every subsequent tick.

    Setup: an existing rollup (issue #4242) is open for ADR-0024, the
    attempt counter is now 4 (one tick after threshold). The loop should
    update the body and persist the new PR set, but it should NOT file a
    fresh HITL escalation issue.
    """
    cfg, state, pr, dedup, idx = loop_env
    # Tracked rollup exists with one prior PR; counter is past the threshold.
    state.get_adr_rollup.return_value = {
        "issue_number": 4242,
        "pr_numbers": [8473],
    }
    state.inc_adr_audit_attempts.return_value = 4

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

    monkeypatch.setattr(loop, "_list_recent_merged_prs", fake_list)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", AsyncMock())

    stats = await loop._do_work()

    # Existing rollup body was refreshed.
    assert pr.update_issue_body.await_count >= 1
    # And NO new escalation issue was filed — ``==`` not ``>=`` is the
    # whole point of this regression test.
    assert pr.create_issue.await_count == 0
    assert stats["escalated"] == 0


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

    monkeypatch.setattr(loop, "_list_recent_merged_prs", fake_list)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", AsyncMock())

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
    stuck_attempt_key = "ADR-0024"
    full_dedup_key = f"adr_touchpoint_auditor:{stuck_attempt_key}"
    current = {full_dedup_key, "adr_touchpoint_auditor:ADR-0042"}
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
    assert "adr_touchpoint_auditor:ADR-0042" in remaining
    state.clear_adr_audit_attempts.assert_called_with(stuck_attempt_key)
    state.clear_adr_rollup.assert_called_with(stuck_attempt_key)
