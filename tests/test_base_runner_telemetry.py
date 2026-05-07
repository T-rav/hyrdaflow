"""Unit tests verifying BaseRunner emits hf.runner.{phase} on its trace-root method."""

from __future__ import annotations

import pytest

from mockworld.fakes.fake_honeycomb import FakeHoneycomb


@pytest.fixture
def fake():
    fh = FakeHoneycomb()
    yield fh
    fh.shutdown()


def test_base_runner_execute_is_decorated():
    """BaseRunner._execute must be wrapped by @runner_span (structural check)."""
    from src.base_runner import BaseRunner  # noqa: PLC0415

    assert hasattr(BaseRunner._execute, "__wrapped__"), (
        "BaseRunner._execute is not decorated with @runner_span(); "
        "__wrapped__ attribute is absent"
    )


@pytest.mark.asyncio
async def test_base_runner_emits_runner_span(fake):
    """Invoking BaseRunner._execute emits hf.runner.{phase} even when the body raises."""
    from src.base_runner import BaseRunner  # noqa: PLC0415

    class _MiniRunner(BaseRunner):
        _phase_name = "implement"
        issue = 1234
        session_id = "sess-abc"
        repo = "org/repo"
        runner = "MiniRunner"
        model = "claude-opus-4-7"
        attempt = 1

    r = _MiniRunner.__new__(_MiniRunner)  # bypass real __init__

    # _execute calls stream_claude_process which will fail without real args;
    # the span is emitted regardless (decorator wraps the exception path too).
    with pytest.raises(Exception):  # noqa: B017
        await r._execute([], "", None, {})  # type: ignore[arg-type]

    spans = fake.find_spans(name="hf.runner.implement")
    assert len(spans) == 1, (
        f"Expected 1 span, got: {[s.name for s in fake.captured_spans]}"
    )
    assert spans[0].attributes.get("hf.issue") == 1234
