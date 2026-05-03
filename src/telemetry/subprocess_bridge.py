"""Bridge `trace_collector` parsed events into OTel span events.

`trace_collector.py` already parses subprocess stdout into structured event
dicts. Phase A adds a parallel side-effect: each parsed event becomes a
`span.add_event("claude.tool", {...})` on the active subprocess span. The
existing JSONL output is preserved untouched (different concern: subprocess
transcript persistence).
"""

from __future__ import annotations

import logging
from typing import Any

from opentelemetry.trace import Span

from src.telemetry.spans import validate_attr

logger = logging.getLogger(__name__)


def bridge_event_to_span(span: Span | None, event: Any) -> None:
    """Adapt a trace_collector event dict to an OTel span event. Best-effort:
    malformed events are dropped without raising."""
    if span is None:
        return
    if not isinstance(event, dict):
        return

    event_type = event.get("type")
    if event_type != "tool_use":
        return

    raw_attrs = {
        "claude.tool": event.get("tool"),
        "claude.duration_ms": event.get("duration_ms"),
        "claude.name": event.get("name"),
    }
    attrs = {k: v for k, v in raw_attrs.items() if v is not None and validate_attr(k)}
    try:
        span.add_event("claude.tool", attributes=attrs)
    except Exception:
        logger.exception("bridge_event_to_span: add_event failed")
