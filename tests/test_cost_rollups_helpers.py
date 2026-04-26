"""Tests for src/dashboard_routes/_cost_rollups.py."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dashboard_routes._cost_rollups import (
    _parse_range,
    build_by_loop,
    build_per_loop_cost,
    build_rolling_24h,
    build_top_issues,
    iter_loop_traces,
    iter_priced_inferences,
    iter_subprocess_traces,
)


@pytest.fixture
def config(tmp_path: Path) -> MagicMock:
    cfg = MagicMock()
    cfg.data_root = tmp_path
    cfg.data_path = lambda *parts: tmp_path.joinpath(*parts)  # noqa: PLW0108
    cfg.repo = "o/r"
    return cfg


def _write_inference(config: MagicMock, **fields) -> None:
    d = config.data_root / "metrics" / "prompt"
    d.mkdir(parents=True, exist_ok=True)
    with (d / "inferences.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(fields) + "\n")


def _write_loop_trace(config: MagicMock, loop: str, **fields) -> None:
    from trace_collector import _slug_for_loop  # noqa: PLC0415

    d = config.data_root / "traces" / "_loops" / _slug_for_loop(loop)
    d.mkdir(parents=True, exist_ok=True)
    payload = {"kind": "loop", "loop": loop, **fields}
    started = fields.get("started_at", "2026-04-22T10:00:00+00:00")
    name = started.replace(":", "")
    (d / f"run-{name}.json").write_text(json.dumps(payload), encoding="utf-8")


def _write_subprocess(
    config: MagicMock,
    issue: int,
    phase: str,
    run_id: int,
    idx: int,
    payload: dict,
) -> None:
    d = config.data_root / "traces" / str(issue) / phase / f"run-{run_id}"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"subprocess-{idx}.json").write_text(json.dumps(payload), encoding="utf-8")


# ---------------------------------------------------------------------------
# _parse_range
# ---------------------------------------------------------------------------


def test_parse_range_accepts_24h_7d_30d_90d() -> None:
    assert _parse_range("24h") == timedelta(hours=24)
    assert _parse_range("7d") == timedelta(days=7)
    assert _parse_range("30d") == timedelta(days=30)
    assert _parse_range("90d") == timedelta(days=90)


def test_parse_range_default_is_7d() -> None:
    assert _parse_range(None) == timedelta(days=7)
    assert _parse_range("") == timedelta(days=7)


def test_parse_range_rejects_unknown() -> None:
    with pytest.raises(ValueError):
        _parse_range("15m")
    with pytest.raises(ValueError):
        _parse_range("1y")


# ---------------------------------------------------------------------------
# iter_priced_inferences
# ---------------------------------------------------------------------------


def test_iter_priced_inferences_filters_by_window(config) -> None:
    _write_inference(
        config,
        timestamp="2026-04-21T10:00:00+00:00",
        source="implementer",
        tool="claude",
        model="claude-sonnet-4-6",
        issue_number=1,
        input_tokens=100,
        output_tokens=50,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        duration_seconds=1,
        status="success",
    )
    _write_inference(
        config,
        timestamp="2026-04-22T10:00:00+00:00",
        source="implementer",
        tool="claude",
        model="claude-sonnet-4-6",
        issue_number=2,
        input_tokens=200,
        output_tokens=100,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        duration_seconds=2,
        status="success",
    )
    pricing = MagicMock()
    pricing.estimate_cost.side_effect = [0.01, 0.02]
    since = datetime(2026, 4, 22, 0, 0, tzinfo=UTC)
    until = datetime(2026, 4, 23, 0, 0, tzinfo=UTC)
    rows = list(
        iter_priced_inferences(config, since=since, until=until, pricing=pricing)
    )
    # Only the 2026-04-22 row falls inside the window.
    assert len(rows) == 1
    assert rows[0]["issue_number"] == 2
    assert rows[0]["cost_usd"] == 0.01


def test_iter_priced_inferences_missing_file_returns_empty(config) -> None:
    pricing = MagicMock()
    rows = list(
        iter_priced_inferences(
            config,
            since=datetime(2026, 4, 1, tzinfo=UTC),
            until=datetime(2026, 5, 1, tzinfo=UTC),
            pricing=pricing,
        )
    )
    assert rows == []


def test_iter_priced_inferences_unknown_model_yields_zero_cost(config) -> None:
    _write_inference(
        config,
        timestamp="2026-04-22T10:00:00+00:00",
        source="implementer",
        tool="claude",
        model="made-up-xyz",
        issue_number=3,
        input_tokens=10,
        output_tokens=5,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        duration_seconds=1,
        status="success",
    )
    pricing = MagicMock()
    pricing.estimate_cost.return_value = None
    rows = list(
        iter_priced_inferences(
            config,
            since=datetime(2026, 4, 22, 0, 0, tzinfo=UTC),
            until=datetime(2026, 4, 23, 0, 0, tzinfo=UTC),
            pricing=pricing,
        )
    )
    assert len(rows) == 1
    assert rows[0]["cost_usd"] == 0.0


def test_iter_priced_inferences_phase_folded(config) -> None:
    _write_inference(
        config,
        timestamp="2026-04-22T10:00:00+00:00",
        source="hitl",
        tool="claude",
        model="claude-sonnet-4-6",
        issue_number=1,
        input_tokens=10,
        output_tokens=5,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        duration_seconds=1,
        status="success",
    )
    pricing = MagicMock()
    pricing.estimate_cost.return_value = 0.01
    rows = list(
        iter_priced_inferences(
            config,
            since=datetime(2026, 4, 22, 0, 0, tzinfo=UTC),
            until=datetime(2026, 4, 23, 0, 0, tzinfo=UTC),
            pricing=pricing,
        )
    )
    assert rows[0]["phase"] == "review"


# ---------------------------------------------------------------------------
# iter_loop_traces
# ---------------------------------------------------------------------------


def test_iter_loop_traces_window_and_slug(config) -> None:
    _write_loop_trace(
        config,
        loop="CorpusLearningLoop",
        command=["gh"],
        exit_code=0,
        duration_ms=100,
        started_at="2026-04-22T10:00:00+00:00",
    )
    _write_loop_trace(
        config,
        loop="RCBudgetLoop",
        command=["x"],
        exit_code=0,
        duration_ms=200,
        started_at="2026-04-21T10:00:00+00:00",
    )  # outside window
    since = datetime(2026, 4, 22, 0, 0, tzinfo=UTC)
    until = datetime(2026, 4, 23, 0, 0, tzinfo=UTC)
    rows = list(iter_loop_traces(config, since=since, until=until))
    assert len(rows) == 1
    assert rows[0]["loop"] == "CorpusLearningLoop"


def test_iter_loop_traces_missing_dir_returns_empty(config) -> None:
    rows = list(
        iter_loop_traces(
            config,
            since=datetime(2026, 4, 22, 0, 0, tzinfo=UTC),
            until=datetime(2026, 4, 23, 0, 0, tzinfo=UTC),
        )
    )
    assert rows == []


# ---------------------------------------------------------------------------
# iter_subprocess_traces
# ---------------------------------------------------------------------------


def test_iter_subprocess_traces_skips_loops_subtree(config) -> None:
    _write_subprocess(
        config,
        issue=42,
        phase="implement",
        run_id=1,
        idx=0,
        payload={
            "started_at": "2026-04-22T10:00:00+00:00",
            "tool_name": "Bash",
        },
    )
    # Write a loop trace under traces/_loops — must be skipped.
    _write_loop_trace(
        config,
        loop="RCBudgetLoop",
        command=["x"],
        exit_code=0,
        duration_ms=500,
        started_at="2026-04-22T10:00:00+00:00",
    )
    since = datetime(2026, 4, 22, 0, 0, tzinfo=UTC)
    until = datetime(2026, 4, 23, 0, 0, tzinfo=UTC)
    rows = list(iter_subprocess_traces(config, since=since, until=until))
    assert len(rows) == 1
    assert rows[0]["tool_name"] == "Bash"


# ---------------------------------------------------------------------------
# build_rolling_24h
# ---------------------------------------------------------------------------


def test_build_rolling_24h_total_and_by_phase(config, monkeypatch) -> None:
    now = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
    monkeypatch.setattr("dashboard_routes._cost_rollups._utcnow", lambda: now)
    _write_inference(
        config,
        timestamp="2026-04-22T11:00:00+00:00",
        source="implementer",
        tool="claude",
        model="claude-sonnet-4-6",
        issue_number=1,
        input_tokens=100,
        output_tokens=50,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        duration_seconds=1,
        status="success",
    )
    _write_inference(
        config,
        timestamp="2026-04-22T09:00:00+00:00",
        source="reviewer",
        tool="claude",
        model="claude-sonnet-4-6",
        issue_number=1,
        input_tokens=200,
        output_tokens=80,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        duration_seconds=1,
        status="success",
    )
    pricing = MagicMock()
    pricing.estimate_cost.side_effect = [0.05, 0.10]
    payload = build_rolling_24h(config, pricing=pricing)
    assert payload["total"]["cost_usd"] == pytest.approx(0.15)
    by_phase = {r["phase"]: r for r in payload["by_phase"]}
    assert by_phase["implement"]["cost_usd"] == pytest.approx(0.05)
    assert by_phase["review"]["cost_usd"] == pytest.approx(0.10)
    # by_loop should be empty (no loop traces in window)
    assert payload["by_loop"] == []


# ---------------------------------------------------------------------------
# build_top_issues
# ---------------------------------------------------------------------------


def test_build_top_issues_sorted_and_capped(config) -> None:
    for n in range(15):
        _write_inference(
            config,
            timestamp="2026-04-22T10:00:00+00:00",
            source="implementer",
            tool="claude",
            model="claude-sonnet-4-6",
            issue_number=n,
            input_tokens=n * 100,
            output_tokens=n * 50,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
            duration_seconds=float(n),
            status="success",
        )
    pricing = MagicMock()
    pricing.estimate_cost.side_effect = [n * 0.01 for n in range(15)]
    rows = build_top_issues(
        config,
        since=datetime(2026, 4, 20, tzinfo=UTC),
        until=datetime(2026, 4, 23, tzinfo=UTC),
        limit=10,
        pricing=pricing,
    )
    # Issue 0 costs 0.0 and is filtered out by the ``issue > 0`` guard,
    # so we have issues 1..14 → 14 rows, capped to 10.
    assert len(rows) == 10
    # Sorted descending by cost
    assert rows[0]["issue"] == 14
    for row in rows:
        assert "cost_usd" in row
        assert "wall_clock_seconds" in row


def test_build_top_issues_aggregates_multiple_rows_per_issue(config) -> None:
    for _ in range(3):
        _write_inference(
            config,
            timestamp="2026-04-22T10:00:00+00:00",
            source="implementer",
            tool="claude",
            model="claude-sonnet-4-6",
            issue_number=42,
            input_tokens=100,
            output_tokens=50,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
            duration_seconds=5.0,
            status="success",
        )
    pricing = MagicMock()
    pricing.estimate_cost.return_value = 0.02
    rows = build_top_issues(
        config,
        since=datetime(2026, 4, 22, 0, tzinfo=UTC),
        until=datetime(2026, 4, 23, 0, tzinfo=UTC),
        limit=10,
        pricing=pricing,
    )
    assert len(rows) == 1
    assert rows[0]["issue"] == 42
    assert rows[0]["cost_usd"] == pytest.approx(0.06)
    assert rows[0]["wall_clock_seconds"] == 15


# ---------------------------------------------------------------------------
# build_by_loop
# ---------------------------------------------------------------------------


def test_build_by_loop_shares_and_totals(config) -> None:
    _write_loop_trace(
        config,
        loop="RCBudgetLoop",
        command=["gh"],
        exit_code=0,
        duration_ms=1000,
        started_at="2026-04-22T10:00:00+00:00",
    )
    _write_loop_trace(
        config,
        loop="RCBudgetLoop",
        command=["gh"],
        exit_code=0,
        duration_ms=2000,
        started_at="2026-04-22T11:00:00+00:00",
    )
    _write_loop_trace(
        config,
        loop="CorpusLearningLoop",
        command=["x"],
        exit_code=0,
        duration_ms=500,
        started_at="2026-04-22T12:00:00+00:00",
    )
    rows = build_by_loop(
        config,
        since=datetime(2026, 4, 22, 0, tzinfo=UTC),
        until=datetime(2026, 4, 23, 0, tzinfo=UTC),
    )
    by_loop = {r["loop"]: r for r in rows}
    assert by_loop["RCBudgetLoop"]["ticks"] == 2
    assert by_loop["RCBudgetLoop"]["wall_clock_seconds"] == 3
    assert by_loop["CorpusLearningLoop"]["ticks"] == 1
    # Shares sum to 1.0.
    assert sum(r["share_of_ticks"] for r in rows) == pytest.approx(1.0)


def test_build_by_loop_empty_returns_empty(config) -> None:
    rows = build_by_loop(
        config,
        since=datetime(2026, 4, 22, 0, tzinfo=UTC),
        until=datetime(2026, 4, 23, 0, tzinfo=UTC),
    )
    assert rows == []


# ---------------------------------------------------------------------------
# build_per_loop_cost
# ---------------------------------------------------------------------------


def test_build_per_loop_cost_fields_match_spec(config) -> None:
    # In production, loop traces use the snake_case worker_name (e.g.
    # ``self._worker_name`` in rc_budget_loop.py), not the class name —
    # see rc_budget_loop.py:444. Mirror that pattern here so the event-bus
    # tally merges with the loop trace into a single row.
    _write_loop_trace(
        config,
        loop="rc_budget",
        command=["gh"],
        exit_code=0,
        duration_ms=1000,
        started_at="2026-04-22T10:00:00+00:00",
    )
    pricing = MagicMock()
    pricing.estimate_cost.return_value = 0.001
    # Event bus stub — BACKGROUND_WORKER_STATUS shape (see models.py:2266)
    ev = MagicMock()
    ev.type = "background_worker_status"
    ev.timestamp = "2026-04-22T10:00:00+00:00"
    ev.data = {
        "worker": "rc_budget",
        "status": "success",
        "last_run": "2026-04-22T10:00:00+00:00",
        "details": {"filed": 1, "repaired": 0, "failed": 0},
    }
    fake_events = [ev]
    bus = MagicMock()

    async def _load(since):
        return fake_events

    bus.load_events_since = _load
    rows = build_per_loop_cost(
        config,
        since=datetime(2026, 4, 22, 0, tzinfo=UTC),
        until=datetime(2026, 4, 23, 0, tzinfo=UTC),
        pricing=pricing,
        event_bus=bus,
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["loop"] == "rc_budget"
    for key in (
        "cost_usd",
        "tokens_in",
        "tokens_out",
        "llm_calls",
        "issues_filed",
        "issues_closed",
        "escalations",
        "ticks",
        "tick_cost_avg_usd",
        "wall_clock_seconds",
        "tick_cost_avg_usd_prev_period",
    ):
        assert key in row
    assert row["ticks"] == 1
    assert row["issues_filed"] == 1


def test_build_per_loop_cost_no_event_bus(config) -> None:
    _write_loop_trace(
        config,
        loop="rc_budget",
        command=["gh"],
        exit_code=0,
        duration_ms=1000,
        started_at="2026-04-22T10:00:00+00:00",
    )
    pricing = MagicMock()
    pricing.estimate_cost.return_value = 0.001
    rows = build_per_loop_cost(
        config,
        since=datetime(2026, 4, 22, 0, tzinfo=UTC),
        until=datetime(2026, 4, 23, 0, tzinfo=UTC),
        pricing=pricing,
        event_bus=None,
    )
    # Only trace-based rows present; worker stats are all 0.
    assert len(rows) == 1
    assert rows[0]["ticks"] == 1
    assert rows[0]["issues_filed"] == 0


def test_per_loop_cost_includes_model_breakdown_for_mixed_models(
    tmp_path,
) -> None:
    """build_per_loop_cost emits model_breakdown with one entry per model used."""
    from datetime import UTC, datetime, timedelta

    config = MagicMock()
    config.data_root = tmp_path
    config.data_path = lambda *parts: tmp_path.joinpath(*parts)  # noqa: PLW0108

    now = datetime(2026, 4, 22, 12, tzinfo=UTC)
    started = now - timedelta(minutes=5)
    _write_inference(
        config,
        timestamp=(started + timedelta(seconds=10)).isoformat(),
        source="implementer",
        model="claude-opus-4-7",
        input_tokens=10_000,
        output_tokens=2_000,
        cache_read_input_tokens=20_000,
        cache_creation_input_tokens=1_000,
    )
    _write_inference(
        config,
        timestamp=(started + timedelta(seconds=20)).isoformat(),
        source="implementer",
        model="claude-sonnet-4-6",
        input_tokens=5_000,
        output_tokens=500,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
    )
    _write_loop_trace(
        config,
        "implementer",
        started_at=started.isoformat(),
        duration_ms=60_000,
    )

    rows = build_per_loop_cost(config, since=now - timedelta(hours=1), until=now)

    assert len(rows) == 1
    row = rows[0]
    assert row["loop"] == "implementer"
    breakdown = row["model_breakdown"]
    assert set(breakdown.keys()) == {"claude-opus-4-7", "claude-sonnet-4-6"}
    opus = breakdown["claude-opus-4-7"]
    assert opus["calls"] == 1
    assert opus["input_tokens"] == 10_000
    assert opus["output_tokens"] == 2_000
    assert opus["cache_read_tokens"] == 20_000
    assert opus["cache_write_tokens"] == 1_000
    assert opus["cost_usd"] > 0
    sonnet = breakdown["claude-sonnet-4-6"]
    assert sonnet["calls"] == 1
    assert sonnet["input_tokens"] == 5_000


def test_per_loop_cost_buckets_missing_model_under_unknown(
    tmp_path,
) -> None:
    """Records with empty/missing model bucket under 'unknown'."""
    from datetime import UTC, datetime, timedelta

    config = MagicMock()
    config.data_root = tmp_path
    config.data_path = lambda *parts: tmp_path.joinpath(*parts)  # noqa: PLW0108

    now = datetime(2026, 4, 22, 12, tzinfo=UTC)
    started = now - timedelta(minutes=5)
    _write_inference(
        config,
        timestamp=(started + timedelta(seconds=10)).isoformat(),
        source="implementer",
        model="",
        input_tokens=100,
        output_tokens=50,
    )
    _write_loop_trace(
        config,
        "implementer",
        started_at=started.isoformat(),
        duration_ms=60_000,
    )

    rows = build_per_loop_cost(config, since=now - timedelta(hours=1), until=now)

    assert rows[0]["model_breakdown"].keys() == {"unknown"}
    assert rows[0]["model_breakdown"]["unknown"]["calls"] == 1


def test_per_loop_cost_existing_fields_unchanged(tmp_path) -> None:
    """Regression: adding model_breakdown does not change existing field values."""
    from datetime import UTC, datetime, timedelta

    config = MagicMock()
    config.data_root = tmp_path
    config.data_path = lambda *parts: tmp_path.joinpath(*parts)  # noqa: PLW0108

    now = datetime(2026, 4, 22, 12, tzinfo=UTC)
    started = now - timedelta(minutes=5)
    _write_inference(
        config,
        timestamp=(started + timedelta(seconds=10)).isoformat(),
        source="implementer",
        model="claude-opus-4-7",
        input_tokens=1_000,
        output_tokens=200,
    )
    _write_loop_trace(
        config,
        "implementer",
        started_at=started.isoformat(),
        duration_ms=60_000,
    )

    rows = build_per_loop_cost(config, since=now - timedelta(hours=1), until=now)

    row = rows[0]
    expected_keys = {
        "loop",
        "cost_usd",
        "tokens_in",
        "tokens_out",
        "llm_calls",
        "issues_filed",
        "issues_closed",
        "escalations",
        "ticks",
        "ticks_errored",
        "tick_cost_avg_usd",
        "wall_clock_seconds",
        "last_tick_at",
        "tick_cost_avg_usd_prev_period",
        "model_breakdown",
    }
    assert set(row.keys()) == expected_keys
    assert row["tokens_in"] == 1_000
    assert row["tokens_out"] == 200
    assert row["llm_calls"] == 1
