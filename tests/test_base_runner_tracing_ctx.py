"""Tests for BaseRunner tracing-context attribute."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from base_runner import BaseRunner  # noqa: E402
from tracing_context import TracingContext  # noqa: E402


def _make_runner() -> BaseRunner:
    config = MagicMock()
    event_bus = MagicMock()
    runner = MagicMock()
    br = BaseRunner.__new__(BaseRunner)
    br._config = config
    br._bus = event_bus
    br._active_procs = set()
    br._runner = runner
    br._prompt_telemetry = MagicMock()
    br._last_context_stats = {"cache_hits": 0, "cache_misses": 0}
    br._hindsight = None
    br._tracing_ctx = None
    return br


class TestBaseRunnerTracingContext:
    def test_default_is_none(self):
        runner = _make_runner()
        assert runner.tracing_context is None

    def test_set_and_get(self):
        runner = _make_runner()
        ctx = TracingContext(
            issue_number=42, phase="implement", source="implementer", run_id=1
        )
        runner.set_tracing_context(ctx)
        assert runner.tracing_context is ctx

    def test_clear(self):
        runner = _make_runner()
        ctx = TracingContext(
            issue_number=42, phase="implement", source="implementer", run_id=1
        )
        runner.set_tracing_context(ctx)
        runner.clear_tracing_context()
        assert runner.tracing_context is None
