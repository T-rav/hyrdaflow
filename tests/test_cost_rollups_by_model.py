"""Tests for build_cost_by_model (cross-loop per-model aggregator)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dashboard_routes._cost_rollups import build_cost_by_model


def _write_inference(config, **fields) -> None:
    d = config.data_root / "metrics" / "prompt"
    d.mkdir(parents=True, exist_ok=True)
    with (d / "inferences.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(fields) + "\n")


@pytest.fixture
def config(tmp_path: Path) -> MagicMock:
    cfg = MagicMock()
    cfg.data_root = tmp_path
    cfg.data_path = tmp_path.joinpath
    return cfg


def test_build_cost_by_model_returns_one_row_per_model_sorted_descending(
    config,
) -> None:
    now = datetime(2026, 4, 22, 12, tzinfo=UTC)
    _write_inference(
        config,
        timestamp=(now - timedelta(hours=1)).isoformat(),
        source="implementer",
        model="claude-opus-4-7",
        input_tokens=100_000,
        output_tokens=20_000,
    )
    _write_inference(
        config,
        timestamp=(now - timedelta(hours=1)).isoformat(),
        source="implementer",
        model="claude-haiku-4-5-20251001",
        input_tokens=100_000,
        output_tokens=20_000,
    )
    _write_inference(
        config,
        timestamp=(now - timedelta(hours=1)).isoformat(),
        source="implementer",
        model="claude-sonnet-4-6",
        input_tokens=100_000,
        output_tokens=20_000,
    )

    rows = build_cost_by_model(config, since=now - timedelta(hours=24), until=now)

    assert [r["model"] for r in rows] == [
        "claude-opus-4-7",
        "claude-sonnet-4-6",
        "claude-haiku-4-5-20251001",
    ]
    for row in rows:
        assert row["calls"] == 1
        assert row["cost_usd"] > 0
        assert "input_tokens" in row
        assert "output_tokens" in row
        assert "cache_read_tokens" in row
        assert "cache_write_tokens" in row


def test_build_cost_by_model_returns_empty_list_for_no_data(config) -> None:
    now = datetime(2026, 4, 22, 12, tzinfo=UTC)
    rows = build_cost_by_model(config, since=now - timedelta(hours=24), until=now)
    assert rows == []


def test_build_cost_by_model_respects_window(config) -> None:
    now = datetime(2026, 4, 22, 12, tzinfo=UTC)
    _write_inference(
        config,
        timestamp=(now - timedelta(hours=1)).isoformat(),
        source="implementer",
        model="claude-opus-4-7",
        input_tokens=1_000,
        output_tokens=100,
    )
    _write_inference(
        config,
        timestamp=(now - timedelta(days=8)).isoformat(),
        source="implementer",
        model="claude-sonnet-4-6",
        input_tokens=1_000,
        output_tokens=100,
    )

    rows = build_cost_by_model(config, since=now - timedelta(days=7), until=now)

    assert [r["model"] for r in rows] == ["claude-opus-4-7"]


def test_build_cost_by_model_handles_unpriced_model(config) -> None:
    """Unknown model: cost is 0, tokens still summed."""
    now = datetime(2026, 4, 22, 12, tzinfo=UTC)
    _write_inference(
        config,
        timestamp=(now - timedelta(hours=1)).isoformat(),
        source="implementer",
        model="claude-future-99",
        input_tokens=5_000,
        output_tokens=500,
    )

    rows = build_cost_by_model(config, since=now - timedelta(hours=24), until=now)

    assert len(rows) == 1
    assert rows[0]["model"] == "claude-future-99"
    assert rows[0]["cost_usd"] == 0.0
    assert rows[0]["input_tokens"] == 5_000
    assert rows[0]["output_tokens"] == 500


def test_build_cost_by_model_buckets_missing_model_as_unknown(config) -> None:
    now = datetime(2026, 4, 22, 12, tzinfo=UTC)
    _write_inference(
        config,
        timestamp=(now - timedelta(hours=1)).isoformat(),
        source="implementer",
        model="",
        input_tokens=100,
        output_tokens=50,
    )

    rows = build_cost_by_model(config, since=now - timedelta(hours=24), until=now)

    assert [r["model"] for r in rows] == ["unknown"]
    assert rows[0]["calls"] == 1
