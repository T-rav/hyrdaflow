"""Daily-budget sweep runs inside ReportIssueLoop._do_work (spec §4.11 Task 9).

The sweep piggybacks on the existing report-issue loop cadence and only
runs when the report queue is empty. It calls
`cost_budget_alerts.check_daily_budget` with the current 24h rolling cost,
and swallows any exceptions so the loop tick is never aborted.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from report_issue_loop import ReportIssueLoop


@pytest.fixture
def report_cfg(tmp_path: Path) -> MagicMock:
    cfg = MagicMock()
    cfg.data_root = tmp_path
    cfg.data_path = tmp_path.joinpath
    cfg.dry_run = False
    cfg.report_issue_interval = 3600
    cfg.stale_report_threshold_hours = 24
    cfg.daily_cost_budget_usd = 1.0
    cfg.issue_cost_alert_usd = None
    cfg.find_label = ["hydraflow-find"]
    cfg.report_issue_tool = "claude"
    cfg.report_issue_model = "claude-sonnet-4-6"
    cfg.repo_root = tmp_path
    cfg.screenshot_redaction_enabled = False
    return cfg


def _make_loop(
    report_cfg: MagicMock,
    state_peek_value: object = None,
) -> ReportIssueLoop:
    state = MagicMock()
    state.peek_report.return_value = state_peek_value
    state.get_pending_reports.return_value = []
    state.get_filed_reports.return_value = []
    pr = MagicMock()
    pr.create_issue = AsyncMock(return_value=42)
    pr.get_issue_state = AsyncMock(return_value="open")
    deps = MagicMock()
    deps.event_bus = MagicMock()
    deps.event_bus.publish = AsyncMock()
    return ReportIssueLoop(config=report_cfg, state=state, pr_manager=pr, deps=deps)


async def test_daily_budget_sweep_invoked_when_queue_empty(
    report_cfg: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the report queue is empty the sweep fires exactly once."""
    calls: list[tuple[float, str]] = []

    async def _fake_check(
        cfg: MagicMock,
        *,
        pr_manager: object,
        dedup: object,
        event_bus: object,
        total_cost_24h: float,
        now: object = None,
    ) -> None:
        calls.append((total_cost_24h, "called"))

    def _fake_build(_cfg: MagicMock) -> dict[str, object]:
        return {"total": {"cost_usd": 12.34}}

    monkeypatch.setattr("report_issue_loop.check_daily_budget", _fake_check)
    monkeypatch.setattr("report_issue_loop.build_rolling_24h", _fake_build)

    loop = _make_loop(report_cfg, state_peek_value=None)
    result = await loop._do_work()

    assert result is None
    assert calls == [(12.34, "called")]


async def test_daily_budget_sweep_skipped_when_queue_nonempty(
    report_cfg: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the queue has work the sweep is deferred to a later tick."""
    calls: list[float] = []

    async def _fake_check(*_args: object, **kwargs: object) -> None:
        calls.append(kwargs["total_cost_24h"])  # pragma: no cover — should not run

    monkeypatch.setattr("report_issue_loop.check_daily_budget", _fake_check)

    # A non-None peek — the rest of _do_work tries to execute; we short-circuit
    # via dry_run=True so we only test the gate logic.
    report_cfg.dry_run = True
    loop = _make_loop(report_cfg, state_peek_value=MagicMock())
    await loop._do_work()
    assert calls == []


async def test_daily_budget_sweep_swallows_errors(
    report_cfg: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An exception inside the sweep must not bubble out of _do_work."""

    def _boom(_cfg: MagicMock) -> dict[str, object]:
        raise RuntimeError("aggregate read failed")

    monkeypatch.setattr("report_issue_loop.build_rolling_24h", _boom)

    loop = _make_loop(report_cfg, state_peek_value=None)
    # Must not raise.
    result = await loop._do_work()
    assert result is None
