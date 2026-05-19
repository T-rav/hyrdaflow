"""Contract tests: FakeHoneycomb span schema fidelity (ADR-0047 + ADR-0055).

Why no cassettes
----------------
The cassette/replay pattern (ADR-0047 §Part 1) targets CLI-based adapters
(github, git, docker) whose real-service output can be snapshot as YAML.
FakeHoneycomb wraps OTel's ``InMemorySpanExporter`` — there is no CLI, no
subprocess, and no external service whose output drifts. Adding "honeycomb"
to ``KNOWN_ADAPTERS`` would be wrong. The contract here is span *schema
fidelity*: does FakeHoneycomb faithfully reproduce the attribute shapes
declared in ``src/telemetry/spans.py`` (the ADR-0055 authority)?

What this file asserts
----------------------
1. Every ``hf.runner.{phase}`` span carries the 7 required ``hf.*`` attributes
   (``hf.issue``, ``hf.phase``, ``hf.session_id``, ``hf.repo``, ``hf.runner``,
   ``hf.model``, ``hf.attempt``) on a clean return, plus ``hf.success=True``.
2. Every ``hf.loop.{name}`` span carries the 4 required loop attributes
   (``hf.loop``, ``hf.tick``, ``hf.interval_s``, ``hf.success``) on a clean return.
3. ``assert_no_orphan_spans()`` passes after a multi-span scenario.
4. Parent-child issue-context: child port spans share the same trace context
   (same ``trace_id``) as their parent runner span.
5. FakeHoneycomb helper methods (``find_spans``, ``trace_for_issue``,
   ``assert_trace_shape``, ``assert_attribute_present``) behave correctly.
6. Error path: ``hf.success`` absent, ``error=True``, ``exception.slug`` present
   on a runner span when the decorated body raises.

Approach: instantiate FakeHoneycomb directly (no MockWorld), invoke the
``runner_span()`` / ``loop_span()`` / ``port_span()`` decorators from
``src/telemetry/spans.py`` on thin stubs, then assert against captured spans.
This is the same layer ADR-0055 §"Enforced by" refers to for ``test_otel_invariants.py``.
"""

from __future__ import annotations

import pytest

from mockworld.fakes.fake_honeycomb import FakeHoneycomb
from telemetry.spans import (
    _get_tracer,
    add_hf_context,
    loop_span,
    port_span,
    runner_span,
)

# ---- helpers -----------------------------------------------------------------

_RUNNER_REQUIRED_ATTRS = (
    "hf.issue",
    "hf.phase",
    "hf.session_id",
    "hf.repo",
    "hf.runner",
    "hf.model",
    "hf.attempt",
)

_LOOP_REQUIRED_ATTRS = (
    "hf.loop",
    "hf.tick",
    "hf.interval_s",
    "hf.success",
)


def _make_honeycomb() -> FakeHoneycomb:
    """Create a fresh FakeHoneycomb and clear the tracer cache."""
    hc = FakeHoneycomb()
    _get_tracer.cache_clear()
    return hc


# ---- fixtures for lightweight stubs -----------------------------------------


class _StubRunner:
    """Minimal runner stub — carries all hf.* fields; no real __init__ needed."""

    _phase_name = "plan"
    issue = 42
    phase = "plan"
    session_id = "sess-contract-test"
    repo = "org/contract-repo"
    runner = "StubPlanRunner"
    model = "claude-sonnet-4-6"
    attempt = 1


class _StubLoop:
    """Minimal loop stub — carries name, tick, interval_s."""

    name = "contract_loop"
    tick = 7
    interval_s = 60


class _RaisesRunner:
    """Runner stub whose _execute body always raises."""

    _phase_name = "implement"
    issue = 99
    phase = "implement"
    session_id = "sess-err"
    repo = "org/repo"
    runner = "RaisesRunner"
    model = "claude-sonnet-4-6"
    attempt = 2


# ---- test 1: runner span carries all 7 required hf.* attrs on clean return ---


@pytest.mark.asyncio
async def test_runner_span_schema_on_success() -> None:
    """hf.runner.{phase} span must carry all 7 required hf.* attributes on success."""
    hc = _make_honeycomb()
    try:

        @runner_span()
        async def _execute(self, *args, **kwargs):  # noqa: ANN001,ANN002,ANN003
            return "ok"

        stub = _StubRunner.__new__(_StubRunner)
        await _execute(stub)

        spans = hc.find_spans(name="hf.runner.plan")
        assert len(spans) == 1, (
            f"Expected exactly 1 hf.runner.plan span; got {[s.name for s in hc.captured_spans]}"
        )
        span = spans[0]
        attrs = span.attributes or {}

        for key in _RUNNER_REQUIRED_ATTRS:
            assert key in attrs, (
                f"Runner span missing required attribute {key!r}; present: {sorted(attrs)}"
            )

        # Spot-check concrete values so the test is tied to the stub's fields.
        assert attrs["hf.issue"] == 42
        assert attrs["hf.phase"] == "plan"
        assert attrs["hf.session_id"] == "sess-contract-test"
        assert attrs["hf.repo"] == "org/contract-repo"
        assert attrs["hf.runner"] == "StubPlanRunner"
        assert attrs["hf.model"] == "claude-sonnet-4-6"
        assert attrs["hf.attempt"] == 1

        # Success path: hf.success must be True.
        assert attrs.get("hf.success") is True, (
            f"Runner span missing hf.success=True on clean return; attrs: {dict(attrs)}"
        )

        hc.assert_no_orphan_spans()
    finally:
        hc.shutdown()


# ---- test 2: loop span carries all 4 required attributes on clean return -----


@pytest.mark.asyncio
async def test_loop_span_schema_on_success() -> None:
    """hf.loop.{name} span must carry hf.loop, hf.tick, hf.interval_s, hf.success."""
    hc = _make_honeycomb()
    try:

        @loop_span()
        async def _execute_cycle(self, *args, **kwargs):  # noqa: ANN001,ANN002,ANN003
            return None

        stub = _StubLoop()
        await _execute_cycle(stub)

        spans = hc.find_spans(name="hf.loop.contract_loop")
        assert len(spans) == 1, (
            f"Expected exactly 1 hf.loop.contract_loop span; got "
            f"{[s.name for s in hc.captured_spans]}"
        )
        span = spans[0]
        attrs = span.attributes or {}

        for key in _LOOP_REQUIRED_ATTRS:
            assert key in attrs, (
                f"Loop span missing required attribute {key!r}; present: {sorted(attrs)}"
            )

        assert attrs["hf.loop"] == "contract_loop"
        assert attrs["hf.tick"] == 7
        assert attrs["hf.interval_s"] == 60
        assert attrs["hf.success"] is True

        hc.assert_no_orphan_spans()
    finally:
        hc.shutdown()


# ---- test 3: assert_no_orphan_spans after multi-span scenario ----------------


@pytest.mark.asyncio
async def test_no_orphan_spans_after_runner_with_port_child() -> None:
    """After a runner span that emits a child port span, no orphan spans exist."""
    hc = _make_honeycomb()
    try:

        @port_span("hf.port.create_pr")
        async def _create_pr(self):  # noqa: ANN001
            return None

        @runner_span()
        async def _execute(self, *args, **kwargs):  # noqa: ANN001,ANN002,ANN003
            # Call a port-decorated method from inside the runner span
            # so it becomes a child span in the same trace.
            await _create_pr(self)
            return "ok"

        stub = _StubRunner.__new__(_StubRunner)
        await _execute(stub)

        runner_spans = hc.find_spans(name="hf.runner.plan")
        port_spans = hc.find_spans(name="hf.port.create_pr")

        assert len(runner_spans) == 1, "Expected 1 runner span"
        assert len(port_spans) == 1, "Expected 1 port span"

        hc.assert_no_orphan_spans()
    finally:
        hc.shutdown()


# ---- test 4: parent-child issue context (same trace_id) ----------------------


@pytest.mark.asyncio
async def test_parent_child_share_trace_id() -> None:
    """Child port span shares trace_id with its parent runner span."""
    hc = _make_honeycomb()
    try:

        @port_span("hf.port.push_branch")
        async def _push_branch(self):  # noqa: ANN001
            return None

        @runner_span()
        async def _execute(self, *args, **kwargs):  # noqa: ANN001,ANN002,ANN003
            await _push_branch(self)
            return "ok"

        stub = _StubRunner.__new__(_StubRunner)
        await _execute(stub)

        runner_spans = hc.find_spans(name="hf.runner.plan")
        port_spans = hc.find_spans(name="hf.port.push_branch")

        assert runner_spans and port_spans

        runner_trace_id = runner_spans[0].context.trace_id
        port_trace_id = port_spans[0].context.trace_id

        assert runner_trace_id == port_trace_id, (
            f"Parent and child span have different trace_ids: "
            f"runner={runner_trace_id} port={port_trace_id}"
        )

        # The port span's parent span_id must match the runner span's span_id.
        runner_span_id = runner_spans[0].context.span_id
        port_parent_span_id = port_spans[0].parent.span_id  # type: ignore[union-attr]

        assert runner_span_id == port_parent_span_id, (
            f"Port span's parent_span_id {port_parent_span_id} does not match "
            f"runner span_id {runner_span_id}"
        )
    finally:
        hc.shutdown()


# ---- test 5: error path — hf.success absent, error attrs present ------------


@pytest.mark.asyncio
async def test_runner_span_error_path_attributes() -> None:
    """On failure, runner span must have error=True + exception.slug; hf.success absent."""
    hc = _make_honeycomb()
    try:

        @runner_span()
        async def _execute(self, *args, **kwargs):  # noqa: ANN001,ANN002,ANN003
            raise RuntimeError("intentional contract test failure")

        stub = _RaisesRunner.__new__(_RaisesRunner)
        with pytest.raises(RuntimeError, match="intentional contract test failure"):
            await _execute(stub)

        spans = hc.find_spans(name="hf.runner.implement")
        assert len(spans) == 1, (
            f"Expected 1 hf.runner.implement span; got {[s.name for s in hc.captured_spans]}"
        )
        span = spans[0]
        attrs = span.attributes or {}

        # Error path: hf.success must NOT be set.
        assert "hf.success" not in attrs, (
            f"hf.success must not be set on the error path; attrs: {dict(attrs)}"
        )

        # error=True and exception.slug set by _safe_record_error.
        assert attrs.get("error") is True, (
            f"error=True missing on error-path runner span; attrs: {dict(attrs)}"
        )
        assert "exception.slug" in attrs, (
            f"exception.slug missing on error-path runner span; attrs: {dict(attrs)}"
        )

        hc.assert_no_orphan_spans()
    finally:
        hc.shutdown()


# ---- test 6: FakeHoneycomb helper method contracts ---------------------------


@pytest.mark.asyncio
async def test_find_spans_by_name_and_attrs() -> None:
    """find_spans filters by name and attribute dict correctly."""
    hc = _make_honeycomb()
    try:

        @runner_span()
        async def _execute(self, *args, **kwargs):  # noqa: ANN001,ANN002,ANN003
            return "ok"

        stub = _StubRunner.__new__(_StubRunner)
        await _execute(stub)

        # By name only.
        by_name = hc.find_spans(name="hf.runner.plan")
        assert len(by_name) == 1

        # By attribute only.
        by_attr = hc.find_spans(attrs={"hf.issue": 42})
        assert len(by_attr) == 1

        # By name + attribute.
        by_both = hc.find_spans(name="hf.runner.plan", attrs={"hf.issue": 42})
        assert len(by_both) == 1

        # Non-matching name returns empty.
        miss = hc.find_spans(name="hf.runner.does_not_exist")
        assert miss == []

        # Non-matching attribute returns empty.
        miss_attr = hc.find_spans(attrs={"hf.issue": 9999})
        assert miss_attr == []
    finally:
        hc.shutdown()


@pytest.mark.asyncio
async def test_trace_for_issue_returns_sorted_spans() -> None:
    """trace_for_issue returns all spans with matching hf.issue, sorted by start_time."""
    hc = _make_honeycomb()
    try:

        @port_span("hf.port.create_pr")
        async def _create_pr(self):  # noqa: ANN001
            return None

        @runner_span()
        async def _execute(self, *args, **kwargs):  # noqa: ANN001,ANN002,ANN003
            await _create_pr(self)
            return "ok"

        stub = _StubRunner.__new__(_StubRunner)
        await _execute(stub)

        # Only runner span carries hf.issue (port span does not); verify
        # trace_for_issue finds at minimum the runner span.
        issue_spans = hc.trace_for_issue(42)
        assert len(issue_spans) >= 1

        # Returned list is ordered ascending by start_time.
        times = [s.start_time for s in issue_spans if s.start_time is not None]
        assert times == sorted(times), "trace_for_issue spans not sorted by start_time"
    finally:
        hc.shutdown()


@pytest.mark.asyncio
async def test_assert_trace_shape_passes_on_correct_shape() -> None:
    """assert_trace_shape does not raise when root matches expectations.

    Note: ``assert_trace_shape`` builds its span list via ``trace_for_issue``,
    which filters by ``hf.issue`` attribute. Only spans that carry ``hf.issue``
    are visible to it — port spans do not carry ``hf.issue`` by default
    (ADR-0055 §Trace boundaries). The child-list check therefore applies to
    explicitly-tagged nested runner spans, not to port spans.

    Here we verify the no-children case (root-only trace) passes cleanly, and
    that passing an impossible child name raises AssertionError as expected.
    """
    hc = _make_honeycomb()
    try:

        @runner_span()
        async def _execute(self, *args, **kwargs):  # noqa: ANN001,ANN002,ANN003
            return "ok"

        stub = _StubRunner.__new__(_StubRunner)
        await _execute(stub)

        # Root-only trace: no children expected — must not raise.
        hc.assert_trace_shape(
            42,
            expected_root="hf.runner.plan",
            expected_children=[],
        )

        # Requesting a child span that does not exist must raise.
        with pytest.raises(AssertionError, match="Missing expected child spans"):
            hc.assert_trace_shape(
                42,
                expected_root="hf.runner.plan",
                expected_children=["hf.runner.nonexistent"],
            )
    finally:
        hc.shutdown()


@pytest.mark.asyncio
async def test_assert_attribute_present_raises_on_missing_attr() -> None:
    """assert_attribute_present raises AssertionError for a genuinely absent attribute."""
    hc = _make_honeycomb()
    try:

        @runner_span()
        async def _execute(self, *args, **kwargs):  # noqa: ANN001,ANN002,ANN003
            return "ok"

        stub = _StubRunner.__new__(_StubRunner)
        await _execute(stub)

        with pytest.raises(AssertionError, match="missing attribute"):
            hc.assert_attribute_present("hf.runner.plan", "hf.nonexistent_attr")
    finally:
        hc.shutdown()


# ---- test 7: reset() clears captured spans -----------------------------------


@pytest.mark.asyncio
async def test_reset_clears_spans() -> None:
    """reset() empties captured spans so test isolation works within a single FakeHoneycomb."""
    hc = _make_honeycomb()
    try:

        @runner_span()
        async def _execute(self, *args, **kwargs):  # noqa: ANN001,ANN002,ANN003
            return "ok"

        stub = _StubRunner.__new__(_StubRunner)
        await _execute(stub)

        assert len(hc.captured_spans) > 0, "Expected spans before reset"
        hc.reset()
        assert hc.captured_spans == [], "Expected empty captured_spans after reset"
    finally:
        hc.shutdown()


# ---- test 8: add_hf_context skips None values --------------------------------


def test_add_hf_context_skips_none_values() -> None:
    """add_hf_context must not set attributes for None values."""
    hc = _make_honeycomb()
    try:
        from opentelemetry import trace as _trace

        tracer = _trace.get_tracer("contract-test")
        with tracer.start_as_current_span("test.add_hf_context") as span:
            add_hf_context(
                span,
                issue=5,
                phase="triage",
                session_id=None,
                repo=None,
                runner=None,
                model=None,
                attempt=None,
            )

        spans = hc.find_spans(name="test.add_hf_context")
        assert len(spans) == 1
        attrs = spans[0].attributes or {}

        assert "hf.issue" in attrs
        assert "hf.phase" in attrs
        assert "hf.session_id" not in attrs, (
            "None values must not be written as attributes"
        )
        assert "hf.repo" not in attrs
    finally:
        hc.shutdown()
