"""Tests that stream_claude_process feeds the optional TraceCollector."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest  # noqa: E402

from events import EventBus  # noqa: E402
from runner_utils import stream_claude_process  # noqa: E402
from trace_collector import TraceCollector  # noqa: E402


class _FakeStreamReader:
    def __init__(self, lines: list[bytes]):
        self._lines = list(lines)

    def __aiter__(self):
        return self

    async def __anext__(self) -> bytes:
        if not self._lines:
            raise StopAsyncIteration
        return self._lines.pop(0)


def _make_mock_proc(fake_lines: list[bytes]):
    proc = MagicMock()
    proc.stdout = _FakeStreamReader(fake_lines)
    proc.stderr.read = AsyncMock(return_value=b"")
    proc.stdin = MagicMock()
    proc.stdin.write = MagicMock()
    proc.stdin.drain = AsyncMock()
    proc.stdin.close = MagicMock()
    proc.wait = AsyncMock(return_value=None)
    proc.returncode = 0
    proc.pid = 12345
    return proc


@pytest.mark.asyncio
async def test_trace_collector_receives_each_line(tmp_path: Path):
    bus = EventBus()
    config = MagicMock()
    config.data_root = tmp_path

    collector = TraceCollector(
        issue_number=42,
        phase="implement",
        source="implementer",
        subprocess_idx=0,
        run_id=1,
        config=config,
        event_bus=None,
    )

    fake_lines = [
        json.dumps({"type": "system", "subtype": "init"}).encode() + b"\n",
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "id": "m1",
                    "content": [{"type": "text", "text": "hi"}],
                },
                "usage": {"input_tokens": 100, "output_tokens": 50},
            }
        ).encode()
        + b"\n",
    ]

    proc = _make_mock_proc(fake_lines)
    runner = MagicMock()
    runner.create_streaming_process = AsyncMock(return_value=proc)

    await stream_claude_process(
        cmd=["claude", "-p"],
        prompt="test",
        cwd=tmp_path,
        active_procs=set(),
        event_bus=bus,
        event_data={"issue": 42, "source": "implementer"},
        logger=logging.getLogger("test"),
        runner=runner,
        trace_collector=collector,
    )

    # Collector should have processed the assistant event
    assert collector.inference_count == 1
    assert collector.tokens.prompt_tokens == 100


@pytest.mark.asyncio
async def test_no_collector_does_not_break_existing_flow(tmp_path: Path):
    """Existing call sites that don't pass a collector still work."""
    bus = EventBus()

    fake_lines = [
        json.dumps({"type": "system", "subtype": "init"}).encode() + b"\n",
    ]

    proc = _make_mock_proc(fake_lines)
    runner = MagicMock()
    runner.create_streaming_process = AsyncMock(return_value=proc)

    # Should not raise — no trace_collector passed
    await stream_claude_process(
        cmd=["claude", "-p"],
        prompt="test",
        cwd=tmp_path,
        active_procs=set(),
        event_bus=bus,
        event_data={"issue": 42, "source": "implementer"},
        logger=logging.getLogger("test"),
        runner=runner,
    )
