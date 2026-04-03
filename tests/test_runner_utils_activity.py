"""Integration test — AGENT_ACTIVITY events are emitted alongside TRANSCRIPT_LINE."""

from __future__ import annotations

import json

import pytest

from events import EventBus, EventType, HydraFlowEvent


@pytest.mark.asyncio
async def test_activity_event_emitted_for_tool_use(tmp_path):
    """stream_claude_process emits AGENT_ACTIVITY for Claude tool_use lines."""
    from unittest.mock import AsyncMock

    from runner_utils import stream_claude_process

    tool_use_line = json.dumps(
        {
            "type": "assistant",
            "message": {
                "id": "msg_1",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool_1",
                        "name": "Read",
                        "input": {"file_path": "src/config.py"},
                    },
                ],
            },
        }
    )

    async def fake_create_process(cmd, **_kwargs):
        proc = AsyncMock()
        proc.pid = 12345
        proc.returncode = 0

        async def _stdout():
            yield (tool_use_line + "\n").encode()

        proc.stdout = _stdout()
        proc.stderr = AsyncMock()
        proc.stderr.read = AsyncMock(return_value=b"")
        proc.stdin = None
        proc.wait = AsyncMock(return_value=0)
        proc.kill = AsyncMock()
        return proc

    bus = EventBus()
    collected: list[HydraFlowEvent] = []
    _original_publish = bus.publish

    async def _capture(event: HydraFlowEvent) -> None:
        collected.append(event)
        await _original_publish(event)

    bus.publish = _capture  # type: ignore[assignment]

    runner_mock = AsyncMock()
    runner_mock.create_streaming_process = fake_create_process

    await stream_claude_process(
        cmd=["claude", "-p", "--output-format", "stream-json"],
        prompt="test prompt",
        cwd=tmp_path,
        active_procs=set(),
        event_bus=bus,
        event_data={"issue": 42, "source": "implementer"},
        logger=__import__("logging").getLogger("test"),
        runner=runner_mock,
    )

    activity_events = [e for e in collected if e.type == EventType.AGENT_ACTIVITY]
    transcript_events = [e for e in collected if e.type == EventType.TRANSCRIPT_LINE]

    # Both event types should be emitted
    assert len(activity_events) >= 1, (
        f"Expected AGENT_ACTIVITY events, got {len(activity_events)}"
    )
    assert activity_events[0].data["activity_type"] == "tool_call"
    assert activity_events[0].data["tool_name"] == "Read"
    assert activity_events[0].data["issue"] == 42
    assert activity_events[0].data["source"] == "implementer"

    # Transcript line still emitted (unchanged behavior)
    assert len(transcript_events) >= 1, (
        f"Expected TRANSCRIPT_LINE events, got {len(transcript_events)}"
    )


@pytest.mark.asyncio
async def test_no_activity_event_for_session_lines(tmp_path):
    """Non-interesting lines (session, meta) should not emit AGENT_ACTIVITY."""
    from unittest.mock import AsyncMock

    from runner_utils import stream_claude_process

    session_line = json.dumps({"type": "session", "session_id": "abc-123"})

    async def fake_create_process(cmd, **_kwargs):
        proc = AsyncMock()
        proc.pid = 12345
        proc.returncode = 0

        async def _stdout():
            yield (session_line + "\n").encode()

        proc.stdout = _stdout()
        proc.stderr = AsyncMock()
        proc.stderr.read = AsyncMock(return_value=b"")
        proc.stdin = None
        proc.wait = AsyncMock(return_value=0)
        proc.kill = AsyncMock()
        return proc

    bus = EventBus()
    collected: list[HydraFlowEvent] = []
    _original_publish = bus.publish

    async def _capture(event: HydraFlowEvent) -> None:
        collected.append(event)
        await _original_publish(event)

    bus.publish = _capture  # type: ignore[assignment]

    runner_mock = AsyncMock()
    runner_mock.create_streaming_process = fake_create_process

    await stream_claude_process(
        cmd=["claude", "-p", "--output-format", "stream-json"],
        prompt="test prompt",
        cwd=tmp_path,
        active_procs=set(),
        event_bus=bus,
        event_data={"issue": 99, "source": "planner"},
        logger=__import__("logging").getLogger("test"),
        runner=runner_mock,
    )

    activity_events = [e for e in collected if e.type == EventType.AGENT_ACTIVITY]
    assert len(activity_events) == 0, (
        f"Expected no AGENT_ACTIVITY for session line, got {len(activity_events)}"
    )


# --- Bead ops-audit-fixes-efn: integration edge cases ---


def _make_bus_and_collector():
    """Create an EventBus with a capture wrapper for collecting published events."""
    bus = EventBus()
    collected: list[HydraFlowEvent] = []
    _original = bus.publish

    async def _capture(event: HydraFlowEvent) -> None:
        collected.append(event)
        await _original(event)

    bus.publish = _capture  # type: ignore[assignment]
    return bus, collected


def _make_runner_mock(line: str):
    """Create a mock SubprocessRunner that yields a single stdout line."""
    from unittest.mock import AsyncMock

    async def fake_create_process(cmd, **_kwargs):
        proc = AsyncMock()
        proc.pid = 12345
        proc.returncode = 0

        async def _stdout():
            yield (line + "\n").encode()

        proc.stdout = _stdout()
        proc.stderr = AsyncMock()
        proc.stderr.read = AsyncMock(return_value=b"")
        proc.stdin = None
        proc.wait = AsyncMock(return_value=0)
        proc.kill = AsyncMock()
        return proc

    runner = AsyncMock()
    runner.create_streaming_process = fake_create_process
    return runner


@pytest.mark.asyncio
async def test_codex_backend_detection(tmp_path):
    """cmd[0] == 'codex' should use CodexActivityParser."""
    from runner_utils import stream_claude_process

    codex_line = json.dumps(
        {
            "type": "item.completed",
            "item": {
                "id": "item_1",
                "type": "function_call",
                "name": "Read",
                "arguments": json.dumps({"file_path": "src/main.py"}),
            },
        }
    )

    bus, collected = _make_bus_and_collector()
    runner = _make_runner_mock(codex_line)

    await stream_claude_process(
        cmd=["codex", "exec", "--json"],
        prompt="test prompt",
        cwd=tmp_path,
        active_procs=set(),
        event_bus=bus,
        event_data={"issue": 10, "source": "implementer"},
        logger=__import__("logging").getLogger("test"),
        runner=runner,
    )

    activity_events = [e for e in collected if e.type == EventType.AGENT_ACTIVITY]
    assert len(activity_events) >= 1, "Codex tool_call should emit AGENT_ACTIVITY"
    assert activity_events[0].data["tool_name"] == "Read"


@pytest.mark.asyncio
async def test_activity_parser_exception_does_not_crash_stream(tmp_path):
    """If activity_parser.parse() raises, stream_claude_process should still complete."""
    from unittest.mock import patch

    from runner_utils import stream_claude_process

    # A valid Claude line that would normally produce an activity event
    tool_line = json.dumps(
        {
            "type": "assistant",
            "message": {
                "id": "msg_1",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "Read",
                        "input": {"file_path": "a.py"},
                    },
                ],
            },
        }
    )

    bus, collected = _make_bus_and_collector()
    runner = _make_runner_mock(tool_line)

    # Patch get_activity_parser to return a parser that raises
    class ExplodingParser:
        def parse(self, raw_line):
            raise RuntimeError("boom")

    with patch("runner_utils.get_activity_parser", return_value=ExplodingParser()):
        # This should NOT raise — the stream should complete
        result = await stream_claude_process(
            cmd=["claude", "-p", "--output-format", "stream-json"],
            prompt="test prompt",
            cwd=tmp_path,
            active_procs=set(),
            event_bus=bus,
            event_data={"issue": 1, "source": "implementer"},
            logger=__import__("logging").getLogger("test"),
            runner=runner,
        )

    # TRANSCRIPT_LINE should still be emitted even if activity parsing exploded
    transcript_events = [e for e in collected if e.type == EventType.TRANSCRIPT_LINE]
    assert len(transcript_events) >= 1, "TRANSCRIPT_LINE should still work"
    # Result should be returned (not crash)
    assert isinstance(result, str)
