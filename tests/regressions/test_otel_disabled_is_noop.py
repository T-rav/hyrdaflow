"""Regression: with no OTel provider registered, decorator stack is
byte-identical to no decorators (return values, exception types).

Catches accidental coupling between telemetry and business control flow.
"""

from __future__ import annotations

import pytest
from src.telemetry.spans import loop_span, port_span, runner_span


class _FakeRunner:
    phase = "implement"
    issue = 1


@pytest.mark.asyncio
async def test_runner_span_disabled_returns_same_value():
    """With no provider configured, decorated returns same value as bare."""

    @runner_span()
    async def decorated(self):
        return 42

    async def bare(self):
        return 42

    runner = _FakeRunner()
    assert (await decorated(runner)) == (await bare(runner)) == 42


@pytest.mark.asyncio
async def test_runner_span_disabled_reraises_same_exception():
    @runner_span()
    async def decorated(self):
        raise ValueError("x")

    runner = _FakeRunner()
    with pytest.raises(ValueError, match="x"):
        await decorated(runner)


@pytest.mark.asyncio
async def test_loop_span_disabled_returns_same_value():
    class _FakeLoop:
        name = "x"
        tick = 1
        interval_s = 60

    @loop_span()
    async def decorated(self):
        return "ok"

    assert (await decorated(_FakeLoop())) == "ok"


@pytest.mark.asyncio
async def test_loop_span_disabled_reraises_same_exception():
    class _FakeLoop:
        name = "x"
        tick = 1
        interval_s = 60

    @loop_span()
    async def decorated(self):
        raise RuntimeError("loop boom")

    with pytest.raises(RuntimeError, match="loop boom"):
        await decorated(_FakeLoop())


@pytest.mark.asyncio
async def test_port_span_disabled_returns_same_value():
    @port_span("hf.port.test")
    async def decorated(self):
        return [1, 2, 3]

    class X:
        pass

    assert (await decorated(X())) == [1, 2, 3]


@pytest.mark.asyncio
async def test_port_span_disabled_reraises_same_exception():
    @port_span("hf.port.test")
    async def decorated(self):
        raise KeyError("port-key")

    class X:
        pass

    with pytest.raises(KeyError):
        await decorated(X())
