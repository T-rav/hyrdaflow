"""Unit tests verifying BaseBackgroundLoop emits hf.loop.{name} on _execute_cycle."""

from __future__ import annotations

import pytest

from mockworld.fakes.fake_honeycomb import FakeHoneycomb


class _FakeBus:
    """Minimal EventBus stub that swallows publish calls."""

    async def publish(self, event: object) -> None:
        return None


@pytest.fixture
def fake():
    fh = FakeHoneycomb()
    yield fh
    fh.shutdown()


def test_base_background_loop_execute_cycle_is_decorated():
    """BaseBackgroundLoop._execute_cycle must be wrapped by @loop_span (structural check)."""
    from src.base_background_loop import BaseBackgroundLoop  # noqa: PLC0415

    assert hasattr(BaseBackgroundLoop._execute_cycle, "__wrapped__"), (
        "BaseBackgroundLoop._execute_cycle is not decorated with @loop_span(); "
        "__wrapped__ attribute is absent"
    )


@pytest.mark.asyncio
async def test_loop_emits_loop_span(fake):
    """Invoking _execute_cycle on a stub loop emits hf.loop.{name} span with loop attrs."""
    from src.base_background_loop import BaseBackgroundLoop  # noqa: PLC0415

    class _MiniLoop(BaseBackgroundLoop):
        tick = 1
        interval_s = 60

        def _get_default_interval(self) -> int:
            return 60

        async def _do_work(self):  # type: ignore[override]
            return None

    loop = _MiniLoop.__new__(_MiniLoop)
    loop._worker_name = "miniloop"
    loop._status_cb = lambda *_: None  # type: ignore[method-assign,assignment]
    loop._bus = _FakeBus()  # type: ignore[assignment]

    await loop._execute_cycle()

    spans = fake.find_spans(name="hf.loop.miniloop")
    assert len(spans) == 1, (
        f"Expected 1 span named 'hf.loop.miniloop', got: {[s.name for s in fake.captured_spans]}"
    )
    assert spans[0].attributes["hf.loop"] == "miniloop"
    assert spans[0].attributes["hf.tick"] == 1
    assert spans[0].attributes["hf.interval_s"] == 60
    assert spans[0].attributes["hf.success"] is True
