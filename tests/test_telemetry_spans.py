"""Unit tests for src/telemetry/spans.py — decorators + helpers."""

from __future__ import annotations

import pytest
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from src.telemetry.spans import (
    add_hf_context,
    loop_span,
    port_span,
    runner_span,
    validate_attr,
)


@pytest.fixture
def captured_spans():
    """Install in-memory exporter; yield the exporter; restore default tracer."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": "test"}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    yield exporter
    # Restore default no-op-ish tracer
    trace._TRACER_PROVIDER = None  # noqa: SLF001 (test reset)


class _FakeRunner:
    phase = "implement"
    issue = 1234
    session_id = "sess-abc"
    repo = "org/repo"
    runner = "AgentRunner"
    model = "claude-opus-4-7"
    attempt = 1


@pytest.mark.asyncio
async def test_runner_span_creates_root_with_correct_name(captured_spans):
    runner = _FakeRunner()

    @runner_span()
    async def _execute(self):
        return "ok"

    result = await _execute(runner)
    assert result == "ok"
    spans = captured_spans.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "hf.runner.implement"


@pytest.mark.asyncio
async def test_runner_span_sets_hf_attributes(captured_spans):
    runner = _FakeRunner()

    @runner_span()
    async def _execute(self):
        return None

    await _execute(runner)
    span = captured_spans.get_finished_spans()[0]
    assert span.attributes["hf.issue"] == 1234
    assert span.attributes["hf.phase"] == "implement"
    assert span.attributes["hf.session_id"] == "sess-abc"
    assert span.attributes["hf.repo"] == "org/repo"
    assert span.attributes["hf.runner"] == "AgentRunner"
    assert span.attributes["hf.model"] == "claude-opus-4-7"
    assert span.attributes["hf.attempt"] == 1
    assert span.attributes["hf.success"] is True


@pytest.mark.asyncio
async def test_runner_span_reraises_business_exception(captured_spans):
    runner = _FakeRunner()

    @runner_span()
    async def _execute(self):
        raise ValueError("business problem")

    with pytest.raises(ValueError, match="business problem"):
        await _execute(runner)
    span = captured_spans.get_finished_spans()[0]
    assert span.attributes["error"] is True
    assert span.attributes["exception.slug"] == "err-unclassified"


@pytest.mark.asyncio
async def test_runner_span_credit_exhausted_gets_known_slug(captured_spans):
    from src.subprocess_util import CreditExhaustedError

    runner = _FakeRunner()

    @runner_span()
    async def _execute(self):
        raise CreditExhaustedError("out of credit")

    with pytest.raises(CreditExhaustedError):
        await _execute(runner)
    span = captured_spans.get_finished_spans()[0]
    assert span.attributes["exception.slug"] == "err-credit-exhausted"


@pytest.mark.asyncio
async def test_runner_span_swallows_telemetry_exception(captured_spans, monkeypatch):
    """A bug in our telemetry helpers must not break the wrapped call."""
    runner = _FakeRunner()

    def _broken(*a, **kw):
        raise RuntimeError("telemetry bug")

    monkeypatch.setattr("src.telemetry.spans._safe_set_runner_attrs", _broken)

    @runner_span()
    async def _execute(self):
        return "still works"

    result = await _execute(runner)
    assert result == "still works"


@pytest.mark.asyncio
async def test_loop_span_uses_loop_name(captured_spans):
    class _FakeLoop:
        name = "sentry"
        interval_s = 600
        tick = 42

    loop = _FakeLoop()

    @loop_span()
    async def _do_work(self):
        return None

    await _do_work(loop)
    spans = captured_spans.get_finished_spans()
    assert spans[0].name == "hf.loop.sentry"
    assert spans[0].attributes["hf.loop"] == "sentry"
    assert spans[0].attributes["hf.tick"] == 42
    assert spans[0].attributes["hf.interval_s"] == 600


@pytest.mark.asyncio
async def test_port_span_with_explicit_name(captured_spans):
    @port_span("hf.port.workspace.git")
    async def run_git(self, subcommand, *args):
        return 0

    class _FakePort:
        repo = "org/repo"

    await run_git(_FakePort(), "checkout", "main")
    spans = captured_spans.get_finished_spans()
    assert spans[0].name == "hf.port.workspace.git"


def test_validate_attr_allows_hf_prefix():
    assert validate_attr("hf.issue") is True
    assert validate_attr("hf.session_id") is True


def test_validate_attr_allows_known_namespaces():
    for k in (
        "subprocess.exit_code",
        "git.subcommand",
        "gh.pr_number",
        "exception.slug",
        "claude.tool",
        "http.method",
        "error",
        "duration_ms",
        "deployment.environment",
        "service.name",
    ):
        assert validate_attr(k) is True


def test_validate_attr_rejects_unknown_namespace():
    assert validate_attr("user.email") is False
    assert validate_attr("payload") is False
    assert validate_attr("some_random_key") is False


def test_add_hf_context_only_sets_known_attrs(captured_spans):
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("test") as span:
        add_hf_context(
            span,
            issue=1234,
            phase="plan",
            session_id="sess-abc",
            repo="org/repo",
            extra={"user.email": "should-be-rejected", "hf.attempt": 2},
        )
    span = captured_spans.get_finished_spans()[0]
    assert span.attributes["hf.issue"] == 1234
    assert span.attributes["hf.phase"] == "plan"
    assert span.attributes["hf.attempt"] == 2
    assert "user.email" not in span.attributes
