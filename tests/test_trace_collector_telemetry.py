"""Verify trace_collector parsed events become OTel span events."""

from __future__ import annotations

from pathlib import Path


def test_trace_collector_imports_bridge():
    """Source-level check that trace_collector wires bridge_event_to_span."""
    src = Path(__file__).resolve().parents[1] / "src" / "trace_collector.py"
    text = src.read_text()
    assert "bridge_event_to_span" in text, (
        "trace_collector.py does not wire bridge_event_to_span"
    )
    assert (
        "from src.telemetry.subprocess_bridge" in text
        or "from telemetry.subprocess_bridge" in text
    ), "trace_collector.py does not import from telemetry.subprocess_bridge"
