"""Tests for TriageRetryLoop (ADR-0063 W2).

Coverage:

* Kill-switch + static config gate short-circuit before any work runs.
* Below-cap retry: counter bumps, comment posts, labels swap parked→find.
* At-cap escalation: hitl-escalation issue created with the
  ``triage-retry-exhausted`` sub-label.
* 24h floor: a recent ``last_attempt`` skips the issue.
* Reconciliation: closed parked issues have their counters cleared.

The loop talks only to ``PRPort`` + ``StateTracker``; tests use AsyncMock
for the PR surface and a MagicMock seeded with the ``TriageRetryStateMixin``
accessors. No subprocess, no network.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from triage_retry_loop import TriageRetryLoop


def _deps(stop: asyncio.Event, *, enabled: bool = True) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *_a, **_k: None,
        enabled_cb=lambda _name: enabled,
    )


@pytest.fixture
def env(tmp_path: Path):
    """Build a (config, state, pr) tuple for tests."""
    cfg = HydraFlowConfig(
        data_root=tmp_path / ".hydraflow",
        repo="hydra/hydraflow",
        repo_root=tmp_path,
    )
    state = MagicMock()
    state.get_triage_retry_attempts.return_value = 0
    state.inc_triage_retry_attempts.return_value = 1
    state.get_triage_retry_last_attempt.return_value = ""
    state.set_triage_retry_last_attempt.return_value = None
    state.clear_triage_retry_attempts.return_value = None
    # ``_reconcile_closed_parked`` reads ``state._data.triage_retry_attempts``
    # directly so it can iterate every tracked key (some of which may no
    # longer be in the open parked list).
    data = MagicMock()
    data.triage_retry_attempts = {}
    state._data = data

    pr = AsyncMock()
    pr.list_issues_by_label = AsyncMock(return_value=[])
    pr.swap_pipeline_labels = AsyncMock()
    pr.remove_label = AsyncMock()
    pr.post_comment = AsyncMock()
    pr.create_issue = AsyncMock(return_value=4242)
    pr.get_issue_state = AsyncMock(return_value="OPEN")
    return cfg, state, pr


def _make_loop(env, *, enabled: bool = True) -> TriageRetryLoop:
    cfg, state, pr = env
    return TriageRetryLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        deps=_deps(asyncio.Event(), enabled=enabled),
    )


@pytest.mark.asyncio
async def test_kill_switch_returns_disabled(env) -> None:
    """ADR-0049 in-body gate: when enabled_cb is False, do nothing."""
    loop = _make_loop(env, enabled=False)
    result = await loop._do_work()
    assert result == {"status": "disabled"}
    _, _, pr = env
    pr.list_issues_by_label.assert_not_called()


@pytest.mark.asyncio
async def test_static_config_gate_returns_config_disabled(env) -> None:
    """The static config flag short-circuits ahead of any GitHub calls."""
    cfg, _, pr = env
    object.__setattr__(cfg, "triage_retry_loop_enabled", False)
    loop = _make_loop(env)
    result = await loop._do_work()
    assert result == {"status": "config_disabled"}
    pr.list_issues_by_label.assert_not_called()


@pytest.mark.asyncio
async def test_retry_below_cap_bumps_counter_and_swaps_label(env) -> None:
    """First retry: counter goes 0→1, comment posts, parked→find swap."""
    cfg, state, pr = env
    state.get_triage_retry_attempts.return_value = 0
    state.inc_triage_retry_attempts.return_value = 1
    pr.list_issues_by_label.return_value = [
        {
            "number": 101,
            "title": "Vague bug report",
            "body": (
                "## Needs More Information\n\n"
                "**Missing:**\n"
                "- A reproduction\n"
                "- Expected behaviour\n"
            ),
            "updated_at": "2026-05-01T00:00:00Z",
        }
    ]
    loop = _make_loop(env)

    result = await loop._do_work()

    assert result["status"] == "ok"
    assert result["retried"] == 1
    assert result["escalated"] == 0
    state.inc_triage_retry_attempts.assert_called_once_with(101)
    pr.post_comment.assert_awaited_once()
    comment = pr.post_comment.await_args.args[1]
    assert "TriageRetryLoop" in comment
    assert "reproduction" in comment
    pr.swap_pipeline_labels.assert_awaited_once_with(101, cfg.find_label[0])
    pr.remove_label.assert_awaited_once_with(101, cfg.parked_label[0])
    state.set_triage_retry_last_attempt.assert_called_once()


@pytest.mark.asyncio
async def test_retry_at_cap_escalates_to_hitl(env) -> None:
    """At the third attempt the loop escalates instead of re-dispatching."""
    cfg, state, pr = env
    state.get_triage_retry_attempts.return_value = cfg.triage_retry_max_attempts
    pr.list_issues_by_label.return_value = [
        {
            "number": 202,
            "title": "Still vague after 3 retries",
            "body": ("Auto-Retry: Triage\n\n**Missing:**\n- Acceptance criteria\n"),
            "updated_at": "2026-05-01T00:00:00Z",
        }
    ]
    loop = _make_loop(env)

    result = await loop._do_work()

    assert result["status"] == "ok"
    assert result["escalated"] == 1
    assert result["retried"] == 0
    pr.create_issue.assert_awaited_once()
    title, body, labels = pr.create_issue.await_args.args
    assert "triage retry exhausted" in title.lower()
    assert "Acceptance criteria" in body
    assert cfg.hitl_escalation_label[0] in labels
    assert cfg.triage_retry_exhausted_label[0] in labels
    # parked label is not removed — the human now owns clarification
    pr.swap_pipeline_labels.assert_not_called()


@pytest.mark.asyncio
async def test_recent_attempt_skips_under_24h_floor(env) -> None:
    """Independent 24h floor — even a fast tick respects daily cadence."""
    _, state, pr = env
    pr.list_issues_by_label.return_value = [
        {
            "number": 303,
            "title": "Just retried",
            "body": "",
            "updated_at": "2026-05-01T00:00:00Z",
        }
    ]
    # Last attempt was an hour ago — well inside the 24h default floor.
    state.get_triage_retry_last_attempt.return_value = (
        datetime.now(UTC) - timedelta(hours=1)
    ).isoformat()
    loop = _make_loop(env)

    result = await loop._do_work()

    assert result["status"] == "ok"
    assert result["skipped_recent"] == 1
    assert result["retried"] == 0
    assert result["escalated"] == 0
    pr.post_comment.assert_not_called()
    pr.create_issue.assert_not_called()


@pytest.mark.asyncio
async def test_corrupt_last_attempt_timestamp_does_not_skip(env) -> None:
    """A garbled timestamp shouldn't lock the issue out of retry forever."""
    _, state, pr = env
    pr.list_issues_by_label.return_value = [
        {
            "number": 404,
            "title": "Garbled timestamp",
            "body": "",
            "updated_at": "2026-05-01T00:00:00Z",
        }
    ]
    state.get_triage_retry_last_attempt.return_value = "not-a-timestamp"
    state.get_triage_retry_attempts.return_value = 0
    loop = _make_loop(env)

    result = await loop._do_work()
    # No skip — the loop falls through to the retry branch.
    assert result["retried"] == 1
    assert result["skipped_recent"] == 0


@pytest.mark.asyncio
async def test_reconcile_clears_counter_for_closed_issue(env) -> None:
    """Closed issues drop out of the counter dict on the next tick."""
    _, state, pr = env
    # Pretend issue 555 was tracked but is now closed; issue 666 is open.
    state._data.triage_retry_attempts = {"555": 2, "666": 1}
    pr.get_issue_state = AsyncMock(side_effect=["CLOSED", "OPEN"])
    pr.list_issues_by_label.return_value = []
    loop = _make_loop(env)

    result = await loop._do_work()

    assert result["reconciled"] == 1
    state.clear_triage_retry_attempts.assert_called_once_with(555)


@pytest.mark.asyncio
async def test_list_failure_returns_partial_stats_without_raising(env) -> None:
    """A flaky ``gh issue list`` doesn't crash the loop — log and move on."""
    _, _, pr = env
    pr.list_issues_by_label = AsyncMock(side_effect=RuntimeError("gh blip"))
    loop = _make_loop(env)

    # Should not raise. ``reraise_on_credit_or_bug`` lets ordinary
    # RuntimeError through (it only re-raises credit/auth/bug classes).
    result = await loop._do_work()
    # Reconcile ran first (empty counters) and the list failure short-circuits.
    assert result["scanned"] == 0
    assert result["retried"] == 0
    assert result["escalated"] == 0


def test_extract_parking_reason_walks_to_newest_block(env) -> None:
    """When the body contains multiple Missing blocks, newest wins."""
    loop = _make_loop(env)
    body = (
        "## Needs More Information (first park)\n"
        "**Missing:**\n"
        "- The old reason\n\n"
        "## Auto-Retry: Triage\n"
        "**Missing:**\n"
        "- The new reason\n"
    )
    reason = loop._extract_parking_reason(body)
    assert "new reason" in reason
    assert "old reason" not in reason


def test_default_interval_matches_config(env) -> None:
    """The base interval defaults to ``triage_retry_interval`` from config."""
    cfg, _, _ = env
    loop = _make_loop(env)
    assert loop._get_default_interval() == cfg.triage_retry_interval
