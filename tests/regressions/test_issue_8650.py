"""Regression test for issue #8650.

Bug: TrustFleetSanityLoop fires a staleness escalation for non-trust loops
(e.g. ``report_issue``) that appear in worker heartbeats. The ``report_issue``
loop polls every 30 s when idle but can legitimately take minutes when
processing a report via the Claude CLI. The 2 × 30 s = 60 s staleness
threshold fires as a false positive during normal LLM-driven report processing.

Expected behaviour after fix:
  - Staleness detection only runs for workers in ``TRUST_LOOP_WORKERS``.
  - A non-trust loop (e.g. ``report_issue``) with a stale heartbeat does NOT
    trigger a staleness escalation.
  - A trust-loop worker (e.g. ``rc_budget``) with a stale heartbeat still
    triggers a staleness escalation as before.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from base_background_loop import LoopDeps  # noqa: E402
from config import HydraFlowConfig  # noqa: E402
from events import EventBus  # noqa: E402
from trust_fleet_sanity_loop import TrustFleetSanityLoop  # noqa: E402


def _make_env(tmp_path: Path):
    cfg = HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow")
    state = MagicMock()
    state.get_trust_fleet_sanity_attempts.return_value = 0
    state.inc_trust_fleet_sanity_attempts.return_value = 1
    state.get_worker_heartbeats.return_value = {}
    bg_workers = MagicMock()
    bg_workers.worker_enabled = {}
    bg_workers.get_interval.return_value = 30
    pr_manager = AsyncMock()
    pr_manager.create_issue = AsyncMock(return_value=42)
    dedup = MagicMock()
    dedup.get.return_value = set()
    bus = EventBus()
    return cfg, state, bg_workers, pr_manager, dedup, bus


def _loop(env) -> TrustFleetSanityLoop:
    cfg, state, bg_workers, pr, dedup, bus = env
    deps = LoopDeps(
        event_bus=bus,
        stop_event=asyncio.Event(),
        status_cb=lambda name, status, details=None: None,  # type: ignore[arg-type]
        enabled_cb=lambda name: True,
    )
    loop = TrustFleetSanityLoop(
        config=cfg,
        state=state,
        bg_workers=bg_workers,
        pr_manager=pr,
        dedup=dedup,
        event_bus=bus,
        deps=deps,
    )
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    loop._load_cost_reader = MagicMock(return_value=None)
    return loop


async def _fake_load_empty(_since):  # noqa: ARG001
    return []


@pytest.mark.asyncio
async def test_non_trust_loop_stale_heartbeat_no_staleness_escalation(
    tmp_path: Path,
) -> None:
    """A stale ``report_issue`` heartbeat must NOT trigger a staleness escalation.

    Before the fix, TrustFleetSanityLoop would scan all heartbeat workers and
    fire staleness alerts for report_issue when it was processing a long-running
    report (legitimately taking > 2 × 30 s = 60 s). After the fix, staleness
    is only checked for TRUST_LOOP_WORKERS.
    """
    env = _make_env(tmp_path)
    _, state, bg_workers, pr, _, _ = env

    # report_issue heartbeat is very old — would breach 2 × 30 s threshold.
    old_iso = (datetime.now(UTC) - timedelta(seconds=99_999)).isoformat()
    state.get_worker_heartbeats.return_value = {
        "report_issue": {"status": "ok", "last_run": old_iso, "details": {}},
    }
    bg_workers.worker_enabled = {"report_issue": True}

    loop = _loop(env)
    loop._source_bus.load_events_since = _fake_load_empty  # type: ignore[method-assign]

    stats = await loop._do_work()
    assert stats is not None

    assert stats["anomalies"] == 0
    pr.create_issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_trust_loop_stale_heartbeat_still_escalates(tmp_path: Path) -> None:
    """A stale ``rc_budget`` (trust loop) heartbeat still triggers a staleness alert.

    Verify the fix did not accidentally disable staleness detection for real
    trust-loop workers.
    """
    env = _make_env(tmp_path)
    _, state, bg_workers, pr, _, _ = env

    old_iso = (datetime.now(UTC) - timedelta(seconds=99_999)).isoformat()
    state.get_worker_heartbeats.return_value = {
        "rc_budget": {"status": "ok", "last_run": old_iso, "details": {}},
    }
    bg_workers.worker_enabled = {"rc_budget": True}
    bg_workers.get_interval.return_value = 600

    loop = _loop(env)
    loop._source_bus.load_events_since = _fake_load_empty  # type: ignore[method-assign]

    stats = await loop._do_work()
    assert stats is not None

    assert stats["anomalies"] >= 1
    title = pr.create_issue.await_args.args[0]
    assert "rc_budget" in title
    assert "staleness" in title
