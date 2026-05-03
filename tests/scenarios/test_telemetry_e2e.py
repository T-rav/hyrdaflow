"""End-to-end OTel scenario: phase/loop invocations produce the expected trace shape.

Uses MockWorld + FakeHoneycomb. No real OTLP traffic. No real Claude subprocess.

Coverage:
- Loop path: a ``BaseBackgroundLoop._execute_cycle`` call (decorated with
  ``@loop_span()``) produces a ``hf.loop.<name>`` root span captured by
  FakeHoneycomb, with the canonical hf.* attributes set and no orphan spans.

- Runner path: a ``BaseRunner._execute`` call (decorated with
  ``@runner_span()``) produces a ``hf.runner.<phase>`` root span even
  when the body raises (the decorator wraps both success and failure paths).

Design note: MockWorld.run_with_loops() calls ``loop._do_work()`` directly,
bypassing ``_execute_cycle``. To exercise the @loop_span() decorator we call
``_execute_cycle()`` directly on a loop instance built by the catalog — this is
the same code path the real orchestrator uses (``BaseBackgroundLoop.run()``
calls ``_execute_cycle()`` in its event loop). MockWorld's FakeHoneycomb is
already installed as the global TracerProvider when the world is constructed,
so spans emitted inside ``_execute_cycle`` land in world.honeycomb automatically.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.scenarios.fakes.mock_world import MockWorld


@pytest.mark.asyncio
async def test_loop_execute_cycle_produces_loop_span(tmp_path: Path) -> None:
    """_execute_cycle on a catalog loop emits hf.loop.<name> captured by FakeHoneycomb."""
    from tests.helpers import make_bg_loop_deps  # noqa: PLC0415
    from tests.scenarios.catalog import LoopCatalog  # noqa: PLC0415
    from tests.scenarios.catalog import (  # noqa: PLC0415  # side-effect: register all loops
        loop_registrations as _loop_registrations,
    )

    _ = _loop_registrations  # import for registration side-effect

    world = MockWorld(tmp_path)
    try:
        bg = make_bg_loop_deps(tmp_path)

        from base_background_loop import LoopDeps  # noqa: PLC0415

        loop_deps = LoopDeps(
            event_bus=bg.bus,
            stop_event=bg.stop_event,
            status_cb=bg.status_cb,
            enabled_cb=bg.enabled_cb,
            sleep_fn=bg.sleep_fn,
        )

        loop = LoopCatalog.instantiate(
            "stale_issue_gc",
            ports={"github": world.github},
            config=bg.config,
            deps=loop_deps,
        )

        # Call _execute_cycle directly — this is the decorator-wrapped method
        # that the real run loop calls. _do_work for stale_issue_gc talks to
        # the FakeGitHub, which returns an empty list: a clean no-op tick.
        await loop._execute_cycle()

        spans = world.honeycomb.find_spans(name="hf.loop.stale_issue_gc")
        assert len(spans) >= 1, (
            f"Expected >=1 hf.loop.stale_issue_gc span; captured: "
            f"{[s.name for s in world.honeycomb.captured_spans]}"
        )

        span = spans[0]
        # hf.loop attribute set by _safe_set_loop_attrs inside the decorator
        assert span.attributes.get("hf.loop") == "stale_issue_gc", span.attributes
        # hf.success set on the clean-return path
        assert span.attributes.get("hf.success") is True, span.attributes

        world.honeycomb.assert_no_orphan_spans()
    finally:
        world.honeycomb.shutdown()


@pytest.mark.asyncio
async def test_runner_execute_produces_runner_span(tmp_path: Path) -> None:
    """BaseRunner._execute emits hf.runner.<phase> captured by FakeHoneycomb.

    The body always raises (no real subprocess), but the @runner_span()
    decorator emits the span on both success and failure paths. We assert the
    span was captured with the canonical hf.* attributes.
    """
    world = MockWorld(tmp_path)
    try:
        from src.base_runner import BaseRunner  # noqa: PLC0415

        class _StubPlanRunner(BaseRunner):
            """Minimal runner stub — bypasses real __init__ to avoid dep setup."""

            _phase_name = "plan"
            issue = 9001
            session_id = "sess-e2e-test"
            repo = "org/e2e-repo"
            runner = "StubPlanRunner"
            model = "claude-sonnet-4-6"
            attempt = 1

        r = _StubPlanRunner.__new__(_StubPlanRunner)

        # _execute will fail (no real subprocess deps), but the span must be
        # emitted before the exception propagates (decorator catches + re-raises).
        with pytest.raises(Exception):  # noqa: B017
            await r._execute([], "", None, {})  # type: ignore[arg-type]

        spans = world.honeycomb.find_spans(name="hf.runner.plan")
        assert len(spans) >= 1, (
            f"Expected >=1 hf.runner.plan span; captured: "
            f"{[s.name for s in world.honeycomb.captured_spans]}"
        )

        span = spans[0]
        # hf.issue set by _safe_set_runner_attrs via add_hf_context
        assert span.attributes.get("hf.issue") == 9001, span.attributes
        # error path: hf.success must NOT be set (only set on clean return)
        assert "hf.success" not in (span.attributes or {}), span.attributes
        # error path: error=True and exception.slug set by _safe_record_error
        assert span.attributes.get("error") is True, span.attributes

        world.honeycomb.assert_no_orphan_spans()
    finally:
        world.honeycomb.shutdown()


@pytest.mark.asyncio
async def test_loop_span_carries_tick_and_interval(tmp_path: Path) -> None:
    """Loop span includes hf.tick and hf.interval_s from the loop instance."""
    from tests.helpers import make_bg_loop_deps  # noqa: PLC0415
    from tests.scenarios.catalog import LoopCatalog  # noqa: PLC0415
    from tests.scenarios.catalog import (  # noqa: PLC0415
        loop_registrations as _lr,
    )

    _ = _lr  # ensure registration

    world = MockWorld(tmp_path)
    try:
        bg = make_bg_loop_deps(tmp_path)

        from base_background_loop import LoopDeps  # noqa: PLC0415

        loop_deps = LoopDeps(
            event_bus=bg.bus,
            stop_event=bg.stop_event,
            status_cb=bg.status_cb,
            enabled_cb=bg.enabled_cb,
            sleep_fn=bg.sleep_fn,
        )

        loop = LoopCatalog.instantiate(
            "stale_issue_gc",
            ports={"github": world.github},
            config=bg.config,
            deps=loop_deps,
        )

        # Manually inject tick and interval_s so the span carries them.
        # _safe_set_loop_attrs reads these via getattr; they are not present
        # on StaleIssueGCLoop by default (it uses _get_default_interval instead).
        loop.tick = 3  # type: ignore[attr-defined]
        loop.interval_s = 120  # type: ignore[attr-defined]
        await loop._execute_cycle()

        spans = world.honeycomb.find_spans(name="hf.loop.stale_issue_gc")
        assert len(spans) >= 1
        span = spans[0]
        # Both attributes are emitted when present on the loop instance.
        assert span.attributes.get("hf.tick") == 3, span.attributes
        assert span.attributes.get("hf.interval_s") == 120, span.attributes
    finally:
        world.honeycomb.shutdown()
