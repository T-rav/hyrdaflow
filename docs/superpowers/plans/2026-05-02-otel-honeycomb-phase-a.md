# OTel Honeycomb Instrumentation — Phase A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire OpenTelemetry into HydraFlow such that every phase invocation, every background-loop tick, and every external-I/O port call emits a span to Honeycomb, with consistent `hf.*` business attributes and a `FakeHoneycomb` MockWorld fake that tests assert against.

**Architecture:** OTel is a passive layer — feature-gated decorators wrap existing methods, no signature changes, byte-identical when disabled. Three new files in a new `src/telemetry/` module (init, decorators+helpers, exception slugs, subprocess bridge); modifications to runners/loops/ports add a single decorator each. Tests use OTel's `InMemorySpanExporter` via a new `FakeHoneycomb` exposed on `MockWorld`. No real OTLP calls in tests.

**Tech Stack:** Python 3.11, OTel SDK (`opentelemetry-api`, `-sdk`, `-exporter-otlp-proto-http`), auto-instrumentation packages (`-instrumentation-fastapi`, `-httpx`, `-requests`, `-asyncio`, `-logging`), pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-05-02-otel-honeycomb-phase-a-design.md` (commit `d0dbba70` on `otel-honeycomb-phase-a-spec` branch).

**Worktree:** `/Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/otel-honeycomb-phase-a-spec` (branch: `otel-honeycomb-phase-a-spec`).

**Honeycomb env (for the human at verification time):**
- Set `HONEYCOMB_API_KEY` in `.env` (gitignored). Use the **Ingest** key (single token, not `KEY:SECRET`).
- Set `HYDRAFLOW_OTEL_ENABLED=true` to turn telemetry on.
- Default endpoint: `https://api.honeycomb.io` (US). EU users override `OTEL_EXPORTER_OTLP_ENDPOINT`.

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `pyproject.toml` | MOD | Add OTel SDK + auto-instrumentation deps |
| `src/telemetry/__init__.py` | NEW | Package marker; re-exports `init_otel`, `shutdown_otel` |
| `src/telemetry/otel.py` | NEW | `init_otel(config)` — feature-gated SDK bootstrap, registers auto-instrumentation, atexit shutdown hook |
| `src/telemetry/spans.py` | NEW | `runner_span`, `loop_span`, `port_span` decorators; `add_hf_context` helper; `validate_attr` cardinality guard; `_safe_*` exception-isolating helpers |
| `src/telemetry/slugs.py` | NEW | `EXCEPTION_SLUGS` mapping + `slug_for(exc)` lookup; unknown → `err-unclassified` |
| `src/telemetry/subprocess_bridge.py` | NEW | `bridge_event_to_span(span, event)` — adapts `trace_collector` parsed events to OTel span events |
| `src/config.py` | MOD | Add `otel_enabled`, `otel_endpoint`, `otel_service_name`, `otel_environment` fields + env overrides |
| `src/server.py` | MOD | Call `init_otel(config)` after `_init_sentry`; register `atexit(shutdown_otel)` |
| `src/base_runner.py` | MOD | Decorate `_execute` with `@runner_span()` |
| `src/base_background_loop.py` | MOD | Decorate `_do_work` with `@loop_span()` |
| `src/pr_manager.py` | MOD | Decorate `create_pr`, `merge_pr`, `create_issue`, `push_branch` with `@port_span(...)` |
| `src/workspace.py` | MOD | Decorate `run_git` with `@port_span("hf.port.workspace.git")` |
| `src/exception_classify.py` | MOD | `reraise_on_credit_or_bug` sets `error=true` + `exception.slug` on active span before re-raise |
| `src/events.py` | MOD | `EventBus.publish` calls `span.add_event("hf.event", ...)` on active span |
| `src/trace_collector.py` | MOD | After parsing each subprocess event, call `bridge_event_to_span(active_span, event)` |
| `tests/scenarios/fakes/fake_honeycomb.py` | NEW | `FakeHoneycomb` test fake — wraps `InMemorySpanExporter`, exposes assertion helpers |
| `tests/scenarios/fakes/mock_world.py` | MOD | Instantiate `FakeHoneycomb`; expose as `world.honeycomb`; `shutdown()` in teardown |
| `tests/test_telemetry_otel_init.py` | NEW | Unit tests for init/shutdown |
| `tests/test_telemetry_spans.py` | NEW | Unit tests for decorators + `add_hf_context` + `validate_attr` |
| `tests/test_telemetry_slugs.py` | NEW | Unit tests for slug catalog |
| `tests/test_telemetry_subprocess_bridge.py` | NEW | Unit tests for `bridge_event_to_span` |
| `tests/test_fake_honeycomb.py` | NEW | Unit tests for the fake itself |
| `tests/test_mockworld_honeycomb_wiring.py` | NEW | Smoke tests for MockWorld property + lifecycle |
| `tests/scenarios/test_telemetry_e2e.py` | NEW | End-to-end scenario: phase invocation produces correct trace shape |
| `tests/architecture/test_otel_invariants.py` | NEW | Architecture tests: decorators present, no bare `create_task` in instrumented files, `hf.*` only via helper |
| `tests/regressions/test_otel_disabled_is_noop.py` | NEW | Regression: disabled OTel is byte-identical to no decorators |

---

## Working Conventions

- **TDD strict**: every task is red → green → commit. No "implementation first, tests later."
- **Commit per task**: each task ends with a single commit. Subagents: leave un-pushed; the human pushes once at PR-open time.
- **Quality gate**: `make quality` must pass before final PR — but don't run it after every task (slow). Run it after Task 16 and after Task 21.
- **Decorator pattern** (used everywhere): wrapper calls a `_safe_*` helper for every span operation; business exceptions are re-raised; telemetry exceptions are logged and swallowed. Span cleanup via `with` block guarantees end-of-span on every path.
- **No real OTLP in tests**. `init_otel()` is never called in unit tests. `FakeHoneycomb` installs the in-memory exporter into the global `TracerProvider`; teardown restores the no-op tracer.

---

## Task 1: Add OTel dependencies

**Files:**
- Modify: `pyproject.toml` (the `[project.dependencies]` and a new `[project.optional-dependencies.otel]` group)

- [ ] **Step 1: Add deps to `pyproject.toml`**

Add to `[project.dependencies]` (always installed; the SDK itself is small and the `init_otel()` is feature-gated):

```toml
"opentelemetry-api>=1.30.0",
"opentelemetry-sdk>=1.30.0",
"opentelemetry-exporter-otlp-proto-http>=1.30.0",
"opentelemetry-instrumentation-fastapi>=0.51b0",
"opentelemetry-instrumentation-httpx>=0.51b0",
"opentelemetry-instrumentation-requests>=0.51b0",
"opentelemetry-instrumentation-asyncio>=0.51b0",
"opentelemetry-instrumentation-logging>=0.51b0",
```

- [ ] **Step 2: Install + sanity-check imports**

Run:
```bash
pip install -e . 2>&1 | tail -5
python -c "from opentelemetry import trace; from opentelemetry.sdk.trace import TracerProvider; from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter; print('ok')"
```
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "deps: add OpenTelemetry SDK + auto-instrumentation"
```

---

## Task 2: Exception slug catalog (`src/telemetry/slugs.py`)

**Files:**
- Create: `src/telemetry/__init__.py`
- Create: `src/telemetry/slugs.py`
- Test: `tests/test_telemetry_slugs.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_telemetry_slugs.py`:

```python
"""Unit tests for src/telemetry/slugs.py — exception → static slug mapping."""

from src.telemetry.slugs import slug_for


class _UnknownErr(Exception):
    pass


def test_credit_exhausted_known_slug():
    from src.exception_classify import CreditExhaustedError

    assert slug_for(CreditExhaustedError("oops")) == "err-credit-exhausted"


def test_subprocess_timeout_known_slug():
    err = TimeoutError("subprocess timed out")
    assert slug_for(err) == "err-subprocess-timeout"


def test_unknown_exception_falls_back():
    assert slug_for(_UnknownErr("boom")) == "err-unclassified"


def test_slug_for_handles_none():
    assert slug_for(None) == "err-unclassified"


def test_slug_is_low_cardinality_string():
    from src.exception_classify import CreditExhaustedError

    slug = slug_for(CreditExhaustedError("oops"))
    assert isinstance(slug, str)
    assert slug.startswith("err-")
    assert " " not in slug
```

- [ ] **Step 2: Run — expect FAIL**

```bash
pytest tests/test_telemetry_slugs.py -v
```
Expected: `ModuleNotFoundError: No module named 'src.telemetry'`

- [ ] **Step 3: Implement**

Create `src/telemetry/__init__.py`:

```python
"""HydraFlow telemetry module — OpenTelemetry instrumentation for Honeycomb.

Public surface kept intentionally small. Use `init_otel(config)` once at
process start and `shutdown_otel()` once at exit. Decorators in
`telemetry.spans` provide the per-method instrumentation.
"""

from src.telemetry.otel import init_otel, shutdown_otel
from src.telemetry.slugs import slug_for

__all__ = ["init_otel", "shutdown_otel", "slug_for"]
```

(`init_otel`/`shutdown_otel` will be defined in Task 4 — leave the import; failing imports come up there. For now, comment out the otel import:)

```python
# from src.telemetry.otel import init_otel, shutdown_otel  # Task 4
from src.telemetry.slugs import slug_for

__all__ = ["slug_for"]
```

Create `src/telemetry/slugs.py`:

```python
"""Maps exception classes to static `exception.slug` identifiers.

Slugs are low-cardinality, greppable, and stable across releases so that
Honeycomb queries / Phase B's anomaly loop can group by `exception.slug`
without depending on exception messages or stack traces.
"""

from __future__ import annotations

import asyncio
import subprocess
from typing import Any

from src.exception_classify import CreditExhaustedError

EXCEPTION_SLUGS: dict[type[BaseException], str] = {
    CreditExhaustedError: "err-credit-exhausted",
    TimeoutError: "err-subprocess-timeout",
    asyncio.TimeoutError: "err-subprocess-timeout",
    subprocess.TimeoutExpired: "err-subprocess-timeout",
    PermissionError: "err-permission-denied",
    FileNotFoundError: "err-file-not-found",
    ConnectionError: "err-connection",
}


def slug_for(exc: BaseException | None) -> str:
    """Return the static slug for `exc` or `err-unclassified` if unknown."""
    if exc is None:
        return "err-unclassified"
    for cls, slug in EXCEPTION_SLUGS.items():
        if isinstance(exc, cls):
            return slug
    return "err-unclassified"


def register_slug(exc_cls: type[BaseException], slug: str) -> None:
    """Add a class → slug mapping at startup. Caller is responsible for
    using a stable, low-cardinality slug. Phase B will grow this catalog
    from production data."""
    EXCEPTION_SLUGS[exc_cls] = slug
```

- [ ] **Step 4: Run — expect PASS**

```bash
pytest tests/test_telemetry_slugs.py -v
```
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/telemetry/__init__.py src/telemetry/slugs.py tests/test_telemetry_slugs.py
git commit -m "telemetry: exception slug catalog (slugs.py)"
```

---

## Task 3: Decorators + helpers (`src/telemetry/spans.py`)

This is the meatiest module — all decorators live here. Tests assert that decorators (a) start spans with the right name, (b) set `hf.*` attributes, (c) re-raise business exceptions, (d) swallow telemetry exceptions, (e) work as a no-op when no provider is configured.

**Files:**
- Create: `src/telemetry/spans.py`
- Test: `tests/test_telemetry_spans.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_telemetry_spans.py`:

```python
"""Unit tests for src/telemetry/spans.py — decorators + helpers."""

from __future__ import annotations

import asyncio

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
    from src.exception_classify import CreditExhaustedError

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

    # _safe_set_runner_attrs is internal-safe-by-design; if monkeypatched to
    # raise, the wrapper's outermost guard must still let business code run.
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
    for k in ("subprocess.exit_code", "git.subcommand", "gh.pr_number",
              "exception.slug", "claude.tool", "http.method", "error",
              "duration_ms", "deployment.environment", "service.name"):
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
```

- [ ] **Step 2: Run — expect FAIL**

```bash
pytest tests/test_telemetry_spans.py -v
```
Expected: `ModuleNotFoundError: No module named 'src.telemetry.spans'`

- [ ] **Step 3: Implement `src/telemetry/spans.py`**

```python
"""Decorators + helpers for HydraFlow OTel instrumentation.

Every span operation goes through a `_safe_*` helper so that telemetry
exceptions never alter business control flow. The wrapped business call's
exceptions are always re-raised; telemetry exceptions are logged and
swallowed. Wrappers are async-aware (decorators apply to coroutines on
runners/loops/ports).
"""

from __future__ import annotations

import functools
import logging
from typing import Any, Awaitable, Callable, TypeVar

from opentelemetry import trace
from opentelemetry.trace import Span, Status, StatusCode

from src.telemetry.slugs import slug_for

logger = logging.getLogger(__name__)

_F = TypeVar("_F", bound=Callable[..., Awaitable[Any]])

_RUNNER_TRACER = trace.get_tracer("hydraflow.runner")
_LOOP_TRACER = trace.get_tracer("hydraflow.loop")
_PORT_TRACER = trace.get_tracer("hydraflow.port")

# Allow-list of attribute prefixes / bare keys. Anything outside this set
# is rejected by validate_attr (cardinality guard).
_ALLOWED_PREFIXES = (
    "hf.",
    "subprocess.",
    "git.",
    "gh.",
    "exception.",
    "claude.",
    "http.",
    "db.",
    "service.",
    "deployment.",
    "process.",
    "code.",
    "net.",
)
_ALLOWED_BARE_KEYS = frozenset({"error", "duration_ms"})


def validate_attr(key: str) -> bool:
    """Return True if `key` is in our allow-list."""
    if key in _ALLOWED_BARE_KEYS:
        return True
    return any(key.startswith(p) for p in _ALLOWED_PREFIXES)


def _safe_set_attr(span: Span, key: str, value: Any) -> None:
    try:
        if not validate_attr(key):
            logger.warning("OTel attr rejected by validate_attr", extra={"key": key})
            return
        span.set_attribute(key, value)
    except Exception:
        logger.exception("OTel set_attribute failed", extra={"key": key})


def add_hf_context(
    span: Span,
    *,
    issue: int | None = None,
    phase: str | None = None,
    session_id: str | None = None,
    repo: str | None = None,
    runner: str | None = None,
    model: str | None = None,
    attempt: int | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Set the canonical hf.* attributes on `span`. The single source of
    truth for hf.* attribute names — never set hf.* directly elsewhere."""
    pairs = {
        "hf.issue": issue,
        "hf.phase": phase,
        "hf.session_id": session_id,
        "hf.repo": repo,
        "hf.runner": runner,
        "hf.model": model,
        "hf.attempt": attempt,
    }
    for k, v in pairs.items():
        if v is not None:
            _safe_set_attr(span, k, v)
    if extra:
        for k, v in extra.items():
            _safe_set_attr(span, k, v)


def _safe_set_runner_attrs(span: Span, runner_self: Any) -> None:
    """Pull standard hf.* attributes off a runner instance."""
    try:
        add_hf_context(
            span,
            issue=getattr(runner_self, "issue", None),
            phase=getattr(runner_self, "phase", None),
            session_id=getattr(runner_self, "session_id", None),
            repo=getattr(runner_self, "repo", None),
            runner=getattr(runner_self, "runner", None) or runner_self.__class__.__name__,
            model=getattr(runner_self, "model", None),
            attempt=getattr(runner_self, "attempt", None),
        )
    except Exception:
        logger.exception("OTel _safe_set_runner_attrs failed")


def _safe_set_loop_attrs(span: Span, loop_self: Any) -> None:
    try:
        _safe_set_attr(span, "hf.loop", getattr(loop_self, "name", "unknown"))
        tick = getattr(loop_self, "tick", None)
        if tick is not None:
            _safe_set_attr(span, "hf.tick", tick)
        interval = getattr(loop_self, "interval_s", None)
        if interval is not None:
            _safe_set_attr(span, "hf.interval_s", interval)
    except Exception:
        logger.exception("OTel _safe_set_loop_attrs failed")


def _safe_record_error(span: Span, exc: BaseException) -> None:
    try:
        slug = slug_for(exc)
        _safe_set_attr(span, "error", True)
        _safe_set_attr(span, "exception.slug", slug)
        span.set_status(Status(StatusCode.ERROR, description=str(exc)[:200]))
        span.record_exception(exc)
    except Exception:
        logger.exception("OTel _safe_record_error failed")


def runner_span() -> Callable[[_F], _F]:
    """Decorator for `BaseRunner._execute`. Span name is `hf.runner.{self.phase}`."""

    def decorator(fn: _F) -> _F:
        @functools.wraps(fn)
        async def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            phase = getattr(self, "phase", "unknown")
            with _RUNNER_TRACER.start_as_current_span(f"hf.runner.{phase}") as span:
                try:
                    _safe_set_runner_attrs(span, self)
                except Exception:
                    logger.exception("OTel runner attrs failed (continuing)")
                try:
                    result = await fn(self, *args, **kwargs)
                except Exception as exc:
                    _safe_record_error(span, exc)
                    raise
                _safe_set_attr(span, "hf.success", True)
                return result

        return wrapper  # type: ignore[return-value]

    return decorator


def loop_span() -> Callable[[_F], _F]:
    """Decorator for `BaseBackgroundLoop._do_work`. Span name is `hf.loop.{self.name}`."""

    def decorator(fn: _F) -> _F:
        @functools.wraps(fn)
        async def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            name = getattr(self, "name", "unknown")
            with _LOOP_TRACER.start_as_current_span(f"hf.loop.{name}") as span:
                try:
                    _safe_set_loop_attrs(span, self)
                except Exception:
                    logger.exception("OTel loop attrs failed (continuing)")
                try:
                    result = await fn(self, *args, **kwargs)
                except Exception as exc:
                    _safe_record_error(span, exc)
                    raise
                _safe_set_attr(span, "hf.success", True)
                return result

        return wrapper  # type: ignore[return-value]

    return decorator


def port_span(span_name: str) -> Callable[[_F], _F]:
    """Decorator for hexagonal-port methods. `span_name` is the literal span name."""

    def decorator(fn: _F) -> _F:
        @functools.wraps(fn)
        async def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            with _PORT_TRACER.start_as_current_span(span_name) as span:
                try:
                    result = await fn(self, *args, **kwargs)
                except Exception as exc:
                    _safe_record_error(span, exc)
                    raise
                return result

        return wrapper  # type: ignore[return-value]

    return decorator
```

- [ ] **Step 4: Run — expect PASS**

```bash
pytest tests/test_telemetry_spans.py -v
```
Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add src/telemetry/spans.py tests/test_telemetry_spans.py
git commit -m "telemetry: decorators + helpers (spans.py)"
```

---

## Task 4: SDK init/shutdown (`src/telemetry/otel.py`)

**Files:**
- Create: `src/telemetry/otel.py`
- Modify: `src/telemetry/__init__.py` (un-comment the otel import)
- Test: `tests/test_telemetry_otel_init.py`

- [ ] **Step 1: Write failing tests**

```python
"""Unit tests for src/telemetry/otel.py — feature-gated SDK bootstrap."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from src.telemetry import otel as otel_mod


def _config(**overrides):
    """Build a minimal config-like object with the otel_* fields."""
    base = {
        "otel_enabled": True,
        "otel_endpoint": "https://api.honeycomb.io",
        "otel_service_name": "hydraflow",
        "otel_environment": "test",
    }
    base.update(overrides)
    cfg = MagicMock()
    for k, v in base.items():
        setattr(cfg, k, v)
    return cfg


def test_init_otel_disabled_is_noop(caplog):
    cfg = _config(otel_enabled=False)
    with patch.object(otel_mod, "_install_provider") as install:
        otel_mod.init_otel(cfg)
    install.assert_not_called()


def test_init_otel_enabled_no_key_warns_and_returns(monkeypatch, caplog):
    monkeypatch.delenv("HONEYCOMB_API_KEY", raising=False)
    cfg = _config()
    with caplog.at_level(logging.WARNING), patch.object(
        otel_mod, "_install_provider"
    ) as install:
        otel_mod.init_otel(cfg)
    install.assert_not_called()
    assert any("HONEYCOMB_API_KEY" in r.message for r in caplog.records)


def test_init_otel_enabled_with_key_installs_provider(monkeypatch):
    monkeypatch.setenv("HONEYCOMB_API_KEY", "test-key")
    cfg = _config()
    with patch.object(otel_mod, "_install_provider") as install, patch.object(
        otel_mod, "_register_auto_instrumentation"
    ) as auto:
        otel_mod.init_otel(cfg)
    install.assert_called_once()
    auto.assert_called_once()


def test_init_otel_swallows_install_failure(monkeypatch, caplog):
    monkeypatch.setenv("HONEYCOMB_API_KEY", "test-key")
    cfg = _config()
    with patch.object(
        otel_mod, "_install_provider", side_effect=RuntimeError("boom")
    ), caplog.at_level(logging.ERROR):
        otel_mod.init_otel(cfg)  # must not raise
    assert any("init_otel failed" in r.message for r in caplog.records)


def test_shutdown_otel_is_idempotent_when_uninitialized():
    # Without ever calling init_otel, shutdown_otel must not raise.
    otel_mod.shutdown_otel()


def test_init_otel_redacts_api_key_from_logs(monkeypatch, caplog):
    monkeypatch.setenv("HONEYCOMB_API_KEY", "secret-not-to-log")
    cfg = _config()
    with caplog.at_level(logging.INFO), patch.object(
        otel_mod, "_install_provider"
    ), patch.object(otel_mod, "_register_auto_instrumentation"):
        otel_mod.init_otel(cfg)
    for record in caplog.records:
        assert "secret-not-to-log" not in record.getMessage()
```

- [ ] **Step 2: Run — expect FAIL**

```bash
pytest tests/test_telemetry_otel_init.py -v
```
Expected: `ModuleNotFoundError: No module named 'src.telemetry.otel'` (or similar).

- [ ] **Step 3: Implement `src/telemetry/otel.py`**

```python
"""Feature-gated OpenTelemetry SDK bootstrap.

`init_otel(config)` is called once from `server.py:main()` after Sentry
init. If `config.otel_enabled` is False, this is a no-op. If True but the
ingest key is missing, log once at WARN and continue with the no-op
tracer. Any exception during init is caught and logged to ERROR; the app
keeps running.

`shutdown_otel()` is registered via `atexit` and flushes pending spans
within ~5s. Idempotent.
"""

from __future__ import annotations

import atexit
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_PROVIDER: Any = None  # opentelemetry.sdk.trace.TracerProvider | None
_INITIALIZED = False


def init_otel(config: Any) -> None:
    """Wire OTel SDK to Honeycomb. Idempotent and exception-safe."""
    global _INITIALIZED
    if _INITIALIZED:
        return
    if not getattr(config, "otel_enabled", False):
        logger.debug("otel disabled — skipping init")
        return

    api_key = os.environ.get("HONEYCOMB_API_KEY")
    if not api_key:
        logger.warning(
            "otel_enabled=True but HONEYCOMB_API_KEY is unset; "
            "telemetry disabled (no-op tracer)"
        )
        return

    try:
        _install_provider(config, api_key)
        _register_auto_instrumentation()
        atexit.register(shutdown_otel)
        _INITIALIZED = True
        logger.info(
            "otel: exporter wired",
            extra={
                "endpoint": getattr(config, "otel_endpoint", "?"),
                "service_name": getattr(config, "otel_service_name", "?"),
                "environment": getattr(config, "otel_environment", "?"),
            },
        )
    except Exception:
        logger.exception("init_otel failed; running without telemetry")


def _install_provider(config: Any, api_key: str) -> None:
    """Install the global TracerProvider with OTLP/HTTP exporter."""
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
        OTLPSpanExporter,
    )
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    global _PROVIDER

    resource = Resource.create({
        "service.name": getattr(config, "otel_service_name", "hydraflow"),
        "deployment.environment": getattr(config, "otel_environment", "local"),
        "service.version": _read_version(),
        "process.pid": os.getpid(),
    })
    endpoint = getattr(config, "otel_endpoint", "https://api.honeycomb.io")
    exporter = OTLPSpanExporter(
        endpoint=endpoint.rstrip("/") + "/v1/traces",
        headers={"x-honeycomb-team": api_key},
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(
            exporter,
            max_queue_size=2048,
            schedule_delay_millis=5000,
            max_export_batch_size=512,
        )
    )
    trace.set_tracer_provider(provider)
    _PROVIDER = provider


def _register_auto_instrumentation() -> None:
    """Enable auto-instrumentation for HTTP/asyncio/logging/FastAPI.

    FastAPI is opt-in per app instance via FastAPIInstrumentor.instrument_app(app)
    in server.py, but the global instrumentors below cover everything else.
    """
    from opentelemetry.instrumentation.asyncio import AsyncioInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.logging import LoggingInstrumentor
    from opentelemetry.instrumentation.requests import RequestsInstrumentor

    AsyncioInstrumentor().instrument()
    HTTPXClientInstrumentor().instrument()
    RequestsInstrumentor().instrument()
    LoggingInstrumentor().instrument(set_logging_format=True)


def _read_version() -> str:
    try:
        from importlib.metadata import version

        return version("hydraflow")
    except Exception:
        return "unknown"


def shutdown_otel() -> None:
    """Flush + shutdown the provider. Idempotent."""
    global _PROVIDER, _INITIALIZED
    if _PROVIDER is None:
        return
    try:
        _PROVIDER.shutdown()
    except Exception:
        logger.exception("shutdown_otel failed")
    finally:
        _PROVIDER = None
        _INITIALIZED = False
```

- [ ] **Step 4: Re-enable the import in `src/telemetry/__init__.py`**

```python
"""HydraFlow telemetry module — OpenTelemetry instrumentation for Honeycomb."""

from src.telemetry.otel import init_otel, shutdown_otel
from src.telemetry.slugs import slug_for

__all__ = ["init_otel", "shutdown_otel", "slug_for"]
```

- [ ] **Step 5: Run — expect PASS**

```bash
pytest tests/test_telemetry_otel_init.py -v
```
Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add src/telemetry/otel.py src/telemetry/__init__.py tests/test_telemetry_otel_init.py
git commit -m "telemetry: SDK bootstrap (otel.py)"
```

---

## Task 5: Subprocess bridge (`src/telemetry/subprocess_bridge.py`)

Adapts `trace_collector` parsed events into OTel span events.

**Files:**
- Create: `src/telemetry/subprocess_bridge.py`
- Test: `tests/test_telemetry_subprocess_bridge.py`

- [ ] **Step 1: Write failing tests**

```python
"""Unit tests for src/telemetry/subprocess_bridge.py."""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
import pytest

from src.telemetry.subprocess_bridge import bridge_event_to_span


@pytest.fixture
def captured_spans():
    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": "test"}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    yield exporter
    trace._TRACER_PROVIDER = None  # noqa: SLF001


def test_bridges_tool_call_event(captured_spans):
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("hf.subprocess.claude") as span:
        bridge_event_to_span(span, {
            "type": "tool_use",
            "tool": "Edit",
            "duration_ms": 234,
            "name": "edit-1",
        })
    s = captured_spans.get_finished_spans()[0]
    assert len(s.events) == 1
    ev = s.events[0]
    assert ev.name == "claude.tool"
    assert ev.attributes["claude.tool"] == "Edit"
    assert ev.attributes["claude.duration_ms"] == 234


def test_skips_unknown_event_type(captured_spans):
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("hf.subprocess.claude") as span:
        bridge_event_to_span(span, {"type": "unknown_thing", "data": "x"})
    s = captured_spans.get_finished_spans()[0]
    assert s.events == ()


def test_handles_malformed_event_safely(captured_spans):
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("hf.subprocess.claude") as span:
        bridge_event_to_span(span, None)  # type: ignore[arg-type]
        bridge_event_to_span(span, {})
        bridge_event_to_span(span, {"type": "tool_use"})  # missing fields
    s = captured_spans.get_finished_spans()[0]
    # Best-effort: malformed events drop, never raise. Last call may add a
    # tool event with default attrs; that's acceptable as long as no exception.
    assert len(s.events) <= 1


def test_drops_disallowed_attribute_keys(captured_spans):
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("hf.subprocess.claude") as span:
        bridge_event_to_span(span, {
            "type": "tool_use",
            "tool": "Read",
            "duration_ms": 12,
            "user_email": "should-be-dropped@example.com",
        })
    s = captured_spans.get_finished_spans()[0]
    ev = s.events[0]
    assert "user_email" not in ev.attributes


def test_no_active_span_is_noop():
    # Calling with span=None must not raise.
    bridge_event_to_span(None, {"type": "tool_use", "tool": "Edit"})  # type: ignore[arg-type]
```

- [ ] **Step 2: Run — expect FAIL**

```bash
pytest tests/test_telemetry_subprocess_bridge.py -v
```
Expected: import error.

- [ ] **Step 3: Implement `src/telemetry/subprocess_bridge.py`**

```python
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
    attrs = {
        k: v
        for k, v in raw_attrs.items()
        if v is not None and validate_attr(k)
    }
    try:
        span.add_event("claude.tool", attributes=attrs)
    except Exception:
        logger.exception("bridge_event_to_span: add_event failed")
```

- [ ] **Step 4: Run — expect PASS**

```bash
pytest tests/test_telemetry_subprocess_bridge.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/telemetry/subprocess_bridge.py tests/test_telemetry_subprocess_bridge.py
git commit -m "telemetry: subprocess_bridge.py — trace_collector → span events"
```

---

## Task 6: Config fields (`src/config.py`)

Add four fields to `HydraFlowConfig` and wire them through env-override tables.

**Files:**
- Modify: `src/config.py`
- Test: extend `tests/test_telemetry_otel_init.py` (or use the existing config tests file — the engineer should grep for `HydraFlowConfig` test fixtures and add a new test in the same style as Sentry config tests)

- [ ] **Step 1: Find the existing Sentry config test** — model the new test after it.

```bash
grep -rn "sentry_poll_interval\|sentry_org" tests/ | head -5
```
Note the file path. Add new tests in the same file.

- [ ] **Step 2: Write failing tests** — add to the file you just identified (assume `tests/test_config.py`):

```python
def test_config_otel_defaults():
    from src.config import HydraFlowConfig

    cfg = HydraFlowConfig()
    assert cfg.otel_enabled is False
    assert cfg.otel_endpoint == "https://api.honeycomb.io"
    assert cfg.otel_service_name == "hydraflow"
    assert cfg.otel_environment == "local"


def test_config_otel_env_overrides(monkeypatch):
    monkeypatch.setenv("HYDRAFLOW_OTEL_ENABLED", "true")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://api.eu1.honeycomb.io")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "hydraflow-test")
    monkeypatch.setenv("HF_ENV", "staging")

    from src.config import HydraFlowConfig

    cfg = HydraFlowConfig()
    assert cfg.otel_enabled is True
    assert cfg.otel_endpoint == "https://api.eu1.honeycomb.io"
    assert cfg.otel_service_name == "hydraflow-test"
    assert cfg.otel_environment == "staging"
```

- [ ] **Step 3: Run — expect FAIL**

```bash
pytest tests/test_config.py -v -k otel
```
Expected: `AttributeError: 'HydraFlowConfig' object has no attribute 'otel_enabled'`.

- [ ] **Step 4: Add fields to `HydraFlowConfig`**

In `src/config.py`, find the `class HydraFlowConfig(BaseModel):` block. Add four new fields (place them near the existing `sentry_*` block to keep telemetry config clustered):

```python
    otel_enabled: bool = False
    otel_endpoint: str = "https://api.honeycomb.io"
    otel_service_name: str = "hydraflow"
    otel_environment: str = "local"
```

Then locate `_ENV_BOOL_OVERRIDES`, `_ENV_STR_OVERRIDES` (these are the env-mapping tables — grep for them). Add:

In `_ENV_BOOL_OVERRIDES`:
```python
    "HYDRAFLOW_OTEL_ENABLED": "otel_enabled",
```

In `_ENV_STR_OVERRIDES`:
```python
    "OTEL_EXPORTER_OTLP_ENDPOINT": "otel_endpoint",
    "OTEL_SERVICE_NAME": "otel_service_name",
    "HF_ENV": "otel_environment",
```

(Note: if `HF_ENV` is already mapped to a different field, route `otel_environment` to track it via a property or duplicate-map — match the existing pattern. Grep first: `grep -n "HF_ENV" src/config.py`. If already present, do not double-register.)

- [ ] **Step 5: Run — expect PASS**

```bash
pytest tests/test_config.py -v -k otel
```
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add src/config.py tests/test_config.py
git commit -m "config: add otel_enabled, otel_endpoint, otel_service_name, otel_environment"
```

---

## Task 7: Wire `init_otel` into `server.py`

**Files:**
- Modify: `src/server.py`
- Test: `tests/test_telemetry_otel_init.py` (add a smoke test that asserts wiring is invoked)

- [ ] **Step 1: Write failing test**

Add to `tests/test_telemetry_otel_init.py`:

```python
def test_main_calls_init_otel_after_sentry(monkeypatch):
    """server.main() must call init_otel after _init_sentry."""
    from src import server

    call_order: list[str] = []

    def _fake_sentry(cfg):
        call_order.append("sentry")

    def _fake_otel(cfg):
        call_order.append("otel")

    monkeypatch.setattr(server, "_init_sentry", _fake_sentry)
    monkeypatch.setattr("src.telemetry.otel.init_otel", _fake_otel)
    # Stub out uvicorn.run so the test doesn't actually start a server.
    monkeypatch.setattr("uvicorn.run", lambda *a, **kw: None)

    server.main()
    assert call_order == ["sentry", "otel"]
```

- [ ] **Step 2: Run — expect FAIL**

```bash
pytest tests/test_telemetry_otel_init.py::test_main_calls_init_otel_after_sentry -v
```

- [ ] **Step 3: Edit `src/server.py`**

Find the `def main():` function. After the `_init_sentry(config)` call, add:

```python
    from src.telemetry.otel import init_otel
    init_otel(config)
```

Use a deferred import (matching the existing Sentry pattern) so OTel deps don't load if `otel_enabled=False` and the SDK fails to import for any reason.

- [ ] **Step 4: Run — expect PASS**

```bash
pytest tests/test_telemetry_otel_init.py -v
```
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/server.py tests/test_telemetry_otel_init.py
git commit -m "server: call init_otel(config) after _init_sentry"
```

---

## Task 8: `FakeHoneycomb` test fake

**Files:**
- Create: `tests/scenarios/fakes/fake_honeycomb.py`
- Test: `tests/test_fake_honeycomb.py`

- [ ] **Step 1: Write failing tests**

```python
"""Unit tests for tests/scenarios/fakes/fake_honeycomb.py."""

from __future__ import annotations

import pytest
from opentelemetry import trace

from tests.scenarios.fakes.fake_honeycomb import FakeHoneycomb


@pytest.fixture
def fake():
    fh = FakeHoneycomb()
    yield fh
    fh.shutdown()


def test_captures_span(fake):
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("hf.runner.plan"):
        pass
    assert len(fake.captured_spans) == 1
    assert fake.captured_spans[0].name == "hf.runner.plan"


def test_find_spans_by_name(fake):
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("hf.runner.plan"):
        pass
    with tracer.start_as_current_span("hf.port.workspace.git"):
        pass
    matches = fake.find_spans(name="hf.runner.plan")
    assert len(matches) == 1


def test_find_spans_by_attrs(fake):
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("hf.runner.plan") as s:
        s.set_attribute("hf.issue", 1234)
    with tracer.start_as_current_span("hf.runner.plan") as s:
        s.set_attribute("hf.issue", 9999)
    matches = fake.find_spans(attrs={"hf.issue": 1234})
    assert len(matches) == 1


def test_trace_for_issue(fake):
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("hf.runner.plan") as s:
        s.set_attribute("hf.issue", 1234)
    with tracer.start_as_current_span("hf.runner.implement") as s:
        s.set_attribute("hf.issue", 1234)
    with tracer.start_as_current_span("hf.runner.plan") as s:
        s.set_attribute("hf.issue", 9999)
    spans = fake.trace_for_issue(1234)
    assert len(spans) == 2
    names = {s.name for s in spans}
    assert names == {"hf.runner.plan", "hf.runner.implement"}


def test_assert_attribute_present_passes(fake):
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("hf.runner.plan") as s:
        s.set_attribute("hf.issue", 1234)
    fake.assert_attribute_present("hf.runner.plan", "hf.issue")


def test_assert_attribute_present_fails(fake):
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("hf.runner.plan"):
        pass
    with pytest.raises(AssertionError, match="hf.issue"):
        fake.assert_attribute_present("hf.runner.plan", "hf.issue")


def test_reset_clears_captured_spans(fake):
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("hf.runner.plan"):
        pass
    fake.reset()
    assert fake.captured_spans == []


def test_shutdown_restores_noop_tracer(fake):
    fake.shutdown()
    # After shutdown, new spans don't get captured by this exporter.
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("post-shutdown"):
        pass
    assert fake.captured_spans == []
```

- [ ] **Step 2: Run — expect FAIL**

```bash
pytest tests/test_fake_honeycomb.py -v
```

- [ ] **Step 3: Implement `tests/scenarios/fakes/fake_honeycomb.py`**

```python
"""FakeHoneycomb — captures OTel spans during scenario tests.

Mirrors the existing fake-of-the-destination convention (FakeSentry,
FakeGitHub). Internally wraps OTel SDK's InMemorySpanExporter so we use
the upstream test machinery rather than rolling our own tracer.
"""

from __future__ import annotations

from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)


class FakeHoneycomb:
    """Captures OTel spans during scenario tests. Replaces the real OTLP
    exporter at the global TracerProvider. Use SimpleSpanProcessor (sync,
    not batched) so spans are visible immediately after their `with` block."""

    def __init__(self) -> None:
        self._exporter = InMemorySpanExporter()
        self._provider = TracerProvider(
            resource=Resource.create({"service.name": "hydraflow-test"})
        )
        self._provider.add_span_processor(SimpleSpanProcessor(self._exporter))
        trace.set_tracer_provider(self._provider)

    @property
    def captured_spans(self) -> list[ReadableSpan]:
        return list(self._exporter.get_finished_spans())

    def find_spans(
        self,
        *,
        name: str | None = None,
        attrs: dict[str, Any] | None = None,
    ) -> list[ReadableSpan]:
        out = []
        for s in self.captured_spans:
            if name is not None and s.name != name:
                continue
            if attrs is not None and not all(
                s.attributes.get(k) == v for k, v in attrs.items()
            ):
                continue
            out.append(s)
        return out

    def trace_for_issue(self, issue_num: int) -> list[ReadableSpan]:
        out = self.find_spans(attrs={"hf.issue": issue_num})
        return sorted(out, key=lambda s: s.start_time)

    def assert_trace_shape(
        self,
        issue_num: int,
        *,
        expected_root: str,
        expected_children: list[str],
    ) -> None:
        spans = self.trace_for_issue(issue_num)
        if not spans:
            raise AssertionError(
                f"No spans found with hf.issue={issue_num}"
            )
        roots = [s for s in spans if s.parent is None]
        if not any(r.name == expected_root for r in roots):
            raise AssertionError(
                f"Expected root span {expected_root!r} for issue {issue_num}, "
                f"got roots: {[r.name for r in roots]}"
            )
        child_names = {s.name for s in spans if s.parent is not None}
        missing = set(expected_children) - child_names
        if missing:
            raise AssertionError(
                f"Missing expected child spans for issue {issue_num}: {missing}; "
                f"actual children: {child_names}"
            )

    def assert_no_orphan_spans(self) -> None:
        """Every non-root span must have a parent in this batch."""
        ids = {s.context.span_id for s in self.captured_spans}
        for s in self.captured_spans:
            if s.parent is not None and s.parent.span_id not in ids:
                raise AssertionError(
                    f"Orphan span {s.name!r}: parent {s.parent.span_id} "
                    f"not in captured batch"
                )

    def assert_attribute_present(self, span_name: str, attr_key: str) -> None:
        matches = self.find_spans(name=span_name)
        if not matches:
            raise AssertionError(f"No span named {span_name!r} captured")
        for s in matches:
            if attr_key not in (s.attributes or {}):
                raise AssertionError(
                    f"Span {span_name!r} missing attribute {attr_key!r}; "
                    f"present attrs: {list((s.attributes or {}).keys())}"
                )

    def reset(self) -> None:
        self._exporter.clear()

    def shutdown(self) -> None:
        try:
            self._provider.shutdown()
        finally:
            trace._TRACER_PROVIDER = None  # noqa: SLF001 (test reset)
```

- [ ] **Step 4: Run — expect PASS**

```bash
pytest tests/test_fake_honeycomb.py -v
```
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/scenarios/fakes/fake_honeycomb.py tests/test_fake_honeycomb.py
git commit -m "test: FakeHoneycomb fake for scenario tests"
```

---

## Task 9: Wire `FakeHoneycomb` into `MockWorld`

**Files:**
- Modify: `tests/scenarios/fakes/mock_world.py`
- Test: `tests/test_mockworld_honeycomb_wiring.py`

- [ ] **Step 1: Write failing tests**

```python
"""Smoke tests for MockWorld → FakeHoneycomb wiring."""

from __future__ import annotations

import pytest
from opentelemetry import trace

from tests.scenarios.fakes.mock_world import MockWorld


def test_mockworld_exposes_honeycomb_property():
    world = MockWorld()
    try:
        assert hasattr(world, "honeycomb")
        from tests.scenarios.fakes.fake_honeycomb import FakeHoneycomb
        assert isinstance(world.honeycomb, FakeHoneycomb)
    finally:
        world.honeycomb.shutdown()


def test_mockworld_honeycomb_captures_spans():
    world = MockWorld()
    try:
        tracer = trace.get_tracer("test")
        with tracer.start_as_current_span("hf.runner.plan") as s:
            s.set_attribute("hf.issue", 1234)
        assert len(world.honeycomb.captured_spans) == 1
    finally:
        world.honeycomb.shutdown()


def test_mockworld_teardown_restores_noop_tracer():
    world = MockWorld()
    world.honeycomb.shutdown()
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("post-shutdown"):
        pass
    # Span should not be in this fake's exporter
    assert world.honeycomb.captured_spans == []
```

- [ ] **Step 2: Run — expect FAIL**

```bash
pytest tests/test_mockworld_honeycomb_wiring.py -v
```

- [ ] **Step 3: Edit `tests/scenarios/fakes/mock_world.py`**

Locate `class MockWorld:` and its `__init__`. Find where other fakes are instantiated (look for `self._sentry = FakeSentry(...)` or similar). Add:

```python
        from tests.scenarios.fakes.fake_honeycomb import FakeHoneycomb
        self._honeycomb = FakeHoneycomb()
```

Then locate the `@property` block around line 459 (`def sentry(self)`). Add a parallel property:

```python
    @property
    def honeycomb(self) -> Any:
        return self._honeycomb
```

(Use `Any` if there isn't already a typed return annotation pattern; otherwise import `FakeHoneycomb` and annotate.)

- [ ] **Step 4: Run — expect PASS**

```bash
pytest tests/test_mockworld_honeycomb_wiring.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/scenarios/fakes/mock_world.py tests/test_mockworld_honeycomb_wiring.py
git commit -m "test: wire FakeHoneycomb into MockWorld"
```

---

## Task 10: Decorate `BaseRunner._execute`

**Files:**
- Modify: `src/base_runner.py`
- Test: extend `tests/scenarios/test_telemetry_e2e.py` later (Task 17). For now, a focused unit test on `BaseRunner` itself, using a minimal subclass.

- [ ] **Step 1: Write failing test**

Add to a new file `tests/test_base_runner_telemetry.py`:

```python
"""Unit tests verifying BaseRunner._execute is wrapped by @runner_span."""

from __future__ import annotations

import pytest

from tests.scenarios.fakes.fake_honeycomb import FakeHoneycomb


@pytest.fixture
def fake():
    fh = FakeHoneycomb()
    yield fh
    fh.shutdown()


@pytest.mark.asyncio
async def test_base_runner_emits_runner_span(fake):
    """A real BaseRunner subclass executing a phase emits hf.runner.{phase}."""
    from src.base_runner import BaseRunner  # noqa: PLC0415 (lazy)

    class _MiniRunner(BaseRunner):
        phase = "implement"
        issue = 1234
        session_id = "sess-abc"
        repo = "org/repo"
        runner = "MiniRunner"
        model = "claude-opus-4-7"
        attempt = 1

        async def _execute(self):  # type: ignore[override]
            return "done"

    r = _MiniRunner.__new__(_MiniRunner)  # bypass real __init__
    result = await r._execute()
    assert result == "done"
    spans = fake.find_spans(name="hf.runner.implement")
    assert len(spans) == 1
    assert spans[0].attributes["hf.issue"] == 1234
    assert spans[0].attributes["hf.success"] is True
```

If `BaseRunner._execute` is abstract or has additional required init args, adapt the minimal subclass accordingly. Grep `class BaseRunner` first:
```bash
grep -n "class BaseRunner\|def _execute\|async def _execute" src/base_runner.py | head
```

- [ ] **Step 2: Run — expect FAIL**

```bash
pytest tests/test_base_runner_telemetry.py -v
```
Expected: span not captured (no decorator yet).

- [ ] **Step 3: Edit `src/base_runner.py`**

At the top of the file, add the import:

```python
from src.telemetry.spans import runner_span
```

Then locate `class BaseRunner:` and its `_execute` method. Add the decorator. Grep first to find the exact line:

```bash
grep -n "async def _execute\|def _execute" src/base_runner.py
```

If there's a single `async def _execute(self, ...):` line at the class level, decorate it directly:

```python
    @runner_span()
    async def _execute(self, ...):
        ...
```

If `_execute` is defined in subclasses rather than the base, instead decorate `BaseRunner.run()` (or whichever shared entry point all phase runners pass through). The spec says "trace root for issue work" — pick the single shared entry, not per-subclass overrides.

- [ ] **Step 4: Run — expect PASS**

```bash
pytest tests/test_base_runner_telemetry.py -v
```
Expected: passed.

- [ ] **Step 5: Commit**

```bash
git add src/base_runner.py tests/test_base_runner_telemetry.py
git commit -m "runner: decorate BaseRunner._execute with @runner_span"
```

---

## Task 11: Decorate `BaseBackgroundLoop._do_work`

**Files:**
- Modify: `src/base_background_loop.py`
- Test: `tests/test_base_background_loop_telemetry.py`

- [ ] **Step 1: Write failing test**

```python
"""Unit tests verifying BaseBackgroundLoop._do_work is wrapped by @loop_span."""

from __future__ import annotations

import pytest

from tests.scenarios.fakes.fake_honeycomb import FakeHoneycomb


@pytest.fixture
def fake():
    fh = FakeHoneycomb()
    yield fh
    fh.shutdown()


@pytest.mark.asyncio
async def test_loop_emits_loop_span(fake):
    from src.base_background_loop import BaseBackgroundLoop

    class _MiniLoop(BaseBackgroundLoop):
        name = "miniloop"
        interval_s = 60
        tick = 1

        async def _do_work(self):  # type: ignore[override]
            return None

    loop = _MiniLoop.__new__(_MiniLoop)  # bypass real __init__
    await loop._do_work()
    spans = fake.find_spans(name="hf.loop.miniloop")
    assert len(spans) == 1
    assert spans[0].attributes["hf.loop"] == "miniloop"
    assert spans[0].attributes["hf.tick"] == 1
    assert spans[0].attributes["hf.success"] is True
```

- [ ] **Step 2: Run — expect FAIL**

```bash
pytest tests/test_base_background_loop_telemetry.py -v
```

- [ ] **Step 3: Edit `src/base_background_loop.py`**

Add import:

```python
from src.telemetry.spans import loop_span
```

Locate `async def _do_work` on `BaseBackgroundLoop` and decorate:

```python
    @loop_span()
    async def _do_work(self, ...):
        ...
```

If `_do_work` is abstract on the base, the decorator should be applied at the call site (the base class's run/tick loop), or the base should provide a concrete `_do_work_traced` wrapper that subclasses extend. Grep first:
```bash
grep -n "_do_work\|def _do_work" src/base_background_loop.py
```
If `_do_work` is `abstractmethod`, add a concrete `_run_tick(self)` on the base that calls `self._do_work()` and decorate `_run_tick` instead. Update the test to call `_run_tick`. Update wiring (the loop's interval scheduler) to call `_run_tick` rather than `_do_work` directly.

- [ ] **Step 4: Run — expect PASS**

```bash
pytest tests/test_base_background_loop_telemetry.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/base_background_loop.py tests/test_base_background_loop_telemetry.py
git commit -m "loop: decorate BaseBackgroundLoop._do_work with @loop_span"
```

---

## Task 12: Decorate `PRManager` methods

**Files:**
- Modify: `src/pr_manager.py`
- Test: `tests/test_pr_manager_telemetry.py`

- [ ] **Step 1: Write failing tests**

```python
"""Unit tests verifying PRManager methods emit port spans."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from tests.scenarios.fakes.fake_honeycomb import FakeHoneycomb


@pytest.fixture
def fake():
    fh = FakeHoneycomb()
    yield fh
    fh.shutdown()


@pytest.mark.asyncio
async def test_create_pr_emits_port_span(fake):
    from src.pr_manager import PRManager

    pm = PRManager.__new__(PRManager)
    pm.dry_run = True

    with patch.object(PRManager, "_create_pr_impl", new=AsyncMock(return_value=42)):
        # Adjust the patch target if PRManager doesn't have a _create_pr_impl
        # — the goal is to skip subprocess calls, not to test PR logic here.
        pass  # placeholder; engineer fills in based on real PRManager.create_pr signature

    # Once decorator is in place, calling create_pr produces a span:
    # span = fake.find_spans(name="hf.port.pr.create_pr")
    # assert len(span) == 1
```

(Grep first: `grep -n "async def create_pr\|async def merge_pr\|async def create_issue\|async def push_branch" src/pr_manager.py`. Then write a test per method using the actual signatures, mocking subprocess/`gh` calls.)

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Edit `src/pr_manager.py`**

Add import:

```python
from src.telemetry.spans import port_span
```

Decorate each port method with the right name:

```python
    @port_span("hf.port.pr.create_pr")
    async def create_pr(self, ...):
        ...

    @port_span("hf.port.pr.merge_pr")
    async def merge_pr(self, ...):
        ...

    @port_span("hf.port.pr.create_issue")
    async def create_issue(self, ...):
        ...

    @port_span("hf.port.pr.push_branch")
    async def push_branch(self, ...):
        ...
```

After each decorated method, set per-call attributes inside the method body before returning:

```python
        from opentelemetry import trace
        span = trace.get_current_span()
        span.set_attribute("gh.repo", self.repo)
        span.set_attribute("gh.dry_run", bool(self.dry_run))
        # in create_pr after PR is created:
        span.set_attribute("gh.pr_number", pr_number)
```

(Note: setting attrs *inside* the method captures dynamic values like `pr_number` that aren't on `self` yet. The decorator only handles span lifecycle.)

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/pr_manager.py tests/test_pr_manager_telemetry.py
git commit -m "pr_manager: decorate port methods with @port_span"
```

---

## Task 13: Decorate `WorkspaceManager.run_git`

**Files:**
- Modify: `src/workspace.py`
- Test: `tests/test_workspace_telemetry.py`

- [ ] **Step 1: Write failing test**

```python
"""Unit tests verifying WorkspaceManager.run_git emits port spans."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from tests.scenarios.fakes.fake_honeycomb import FakeHoneycomb


@pytest.fixture
def fake():
    fh = FakeHoneycomb()
    yield fh
    fh.shutdown()


@pytest.mark.asyncio
async def test_run_git_emits_port_span(fake):
    from src.workspace import WorkspaceManager

    wm = WorkspaceManager.__new__(WorkspaceManager)
    # Adjust the mock target based on the real run_git internals — typically
    # an `asyncio.create_subprocess_exec` call. The point is to skip the
    # actual git invocation and confirm the span is emitted.
    with patch("src.workspace.asyncio.create_subprocess_exec") as mock_exec:
        mock_exec.return_value.communicate.return_value = (b"", b"")
        mock_exec.return_value.returncode = 0
        # call signature: await wm.run_git("status", repo_path="/tmp/x")
        # adapt as needed based on real signature
        # await wm.run_git(...)

    # spans = fake.find_spans(name="hf.port.workspace.git")
    # assert len(spans) == 1
    # assert spans[0].attributes["git.subcommand"] == "status"
```

(Grep `grep -n "async def run_git" src/workspace.py` and adapt to the real signature.)

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Edit `src/workspace.py`**

Add import:

```python
from src.telemetry.spans import port_span
```

Decorate:

```python
    @port_span("hf.port.workspace.git")
    async def run_git(self, subcommand: str, *args, ...):
        from opentelemetry import trace
        span = trace.get_current_span()
        span.set_attribute("git.subcommand", subcommand)
        # ... existing implementation ...
        # before returning:
        span.set_attribute("git.exit_code", exit_code)
        return result
```

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/workspace.py tests/test_workspace_telemetry.py
git commit -m "workspace: decorate run_git with @port_span"
```

---

## Task 14: `exception_classify` sets `exception.slug` on active span

**Files:**
- Modify: `src/exception_classify.py`
- Test: `tests/test_exception_classify_telemetry.py`

- [ ] **Step 1: Write failing test**

```python
"""Unit tests verifying reraise_on_credit_or_bug tags the active span."""

from __future__ import annotations

import pytest
from opentelemetry import trace

from tests.scenarios.fakes.fake_honeycomb import FakeHoneycomb


@pytest.fixture
def fake():
    fh = FakeHoneycomb()
    yield fh
    fh.shutdown()


def test_reraise_tags_active_span_with_slug(fake):
    from src.exception_classify import (
        CreditExhaustedError,
        reraise_on_credit_or_bug,
    )

    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("test-op"):
        with pytest.raises(CreditExhaustedError):
            try:
                raise CreditExhaustedError("boom")
            except CreditExhaustedError as exc:
                reraise_on_credit_or_bug(exc)

    span = fake.captured_spans[0]
    assert span.attributes["error"] is True
    assert span.attributes["exception.slug"] == "err-credit-exhausted"


def test_reraise_does_not_break_with_no_active_span():
    """Without an active span, classifier still re-raises correctly."""
    from src.exception_classify import (
        CreditExhaustedError,
        reraise_on_credit_or_bug,
    )

    with pytest.raises(CreditExhaustedError):
        try:
            raise CreditExhaustedError("boom")
        except CreditExhaustedError as exc:
            reraise_on_credit_or_bug(exc)
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Edit `src/exception_classify.py`**

Locate `reraise_on_credit_or_bug`. Before the `raise`, add:

```python
def reraise_on_credit_or_bug(exc: BaseException) -> None:
    # ... existing classification logic ...
    if isinstance(exc, (CreditExhaustedError, AuthenticationError)) or _is_likely_bug(exc):
        # New: tag active span before re-raising
        try:
            from opentelemetry import trace
            from src.telemetry.slugs import slug_for
            from src.telemetry.spans import _safe_set_attr

            span = trace.get_current_span()
            if span is not None and span.is_recording():
                _safe_set_attr(span, "error", True)
                _safe_set_attr(span, "exception.slug", slug_for(exc))
        except Exception:
            # Telemetry must never alter classify behavior
            pass
        raise exc
```

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/exception_classify.py tests/test_exception_classify_telemetry.py
git commit -m "exception_classify: tag active span with exception.slug before re-raise"
```

---

## Task 15: `EventBus.publish` adds span event

**Files:**
- Modify: `src/events.py`
- Test: `tests/test_events_telemetry.py`

- [ ] **Step 1: Write failing test**

```python
"""Unit tests verifying EventBus.publish records a span event on the active span."""

from __future__ import annotations

import pytest
from opentelemetry import trace

from tests.scenarios.fakes.fake_honeycomb import FakeHoneycomb


@pytest.fixture
def fake():
    fh = FakeHoneycomb()
    yield fh
    fh.shutdown()


def test_publish_adds_span_event(fake):
    from src.events import Event, EventBus, EventType

    bus = EventBus()  # adjust constructor as needed
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("hf.runner.plan"):
        bus.publish(Event(type=EventType.PHASE_CHANGE, payload={"phase": "plan"}))

    span = fake.captured_spans[0]
    assert len(span.events) >= 1
    ev_names = [e.name for e in span.events]
    assert "hf.event" in ev_names
```

(Adjust `Event`, `EventBus`, `EventType` import paths and constructor args based on `src/events.py`.)

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Edit `src/events.py`**

Inside `EventBus.publish`, after publishing to listeners but before/after JSONL persistence:

```python
def publish(self, event: Event) -> None:
    # ... existing publish logic ...
    try:
        from opentelemetry import trace
        span = trace.get_current_span()
        if span is not None and span.is_recording():
            span.add_event(
                "hf.event",
                attributes={
                    "hf.event.type": str(event.type),
                },
            )
    except Exception:
        # Telemetry must never break the event spine
        pass
```

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/events.py tests/test_events_telemetry.py
git commit -m "events: emit span events on publish"
```

---

## Task 16: Wire `trace_collector` to emit span events

**Files:**
- Modify: `src/trace_collector.py`
- Test: `tests/test_trace_collector_telemetry.py`

- [ ] **Step 1: Inspect current `trace_collector` parsing path**

```bash
grep -n "def parse\|def _parse\|json.loads\|parsed_event" src/trace_collector.py | head
```

Identify the function that yields/produces parsed event dicts (the same dicts going to JSONL).

- [ ] **Step 2: Write failing test**

```python
"""Verify trace_collector parsed events become OTel span events."""

from __future__ import annotations

import pytest
from opentelemetry import trace

from tests.scenarios.fakes.fake_honeycomb import FakeHoneycomb


@pytest.fixture
def fake():
    fh = FakeHoneycomb()
    yield fh
    fh.shutdown()


def test_trace_collector_emits_span_event(fake):
    from src.trace_collector import process_event  # or the actual fn name

    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("hf.subprocess.claude"):
        process_event({
            "type": "tool_use",
            "tool": "Edit",
            "duration_ms": 100,
        })

    span = fake.captured_spans[0]
    assert any(e.name == "claude.tool" for e in span.events)
```

(Replace `process_event` with the actual function. If `trace_collector` only writes to JSONL via class methods, instrument the writer and adjust the test accordingly.)

- [ ] **Step 3: Run — expect FAIL**

- [ ] **Step 4: Edit `src/trace_collector.py`**

In the function that handles each parsed event, add a parallel side-effect:

```python
from src.telemetry.subprocess_bridge import bridge_event_to_span
from opentelemetry import trace

def process_event(event_dict):
    # ... existing JSONL-write logic ...
    span = trace.get_current_span()
    if span is not None and span.is_recording():
        bridge_event_to_span(span, event_dict)
```

If `trace_collector` runs in a thread/coroutine that may not have the parent span in context, accept this limitation: the bridge is best-effort. The architecture invariant (Task 18) will catch missing context propagation.

- [ ] **Step 5: Run — expect PASS**

- [ ] **Step 6: Run quality gate**

```bash
make quality 2>&1 | tail -30
```
Fix any lint/type errors before continuing.

- [ ] **Step 7: Commit**

```bash
git add src/trace_collector.py tests/test_trace_collector_telemetry.py
git commit -m "trace_collector: bridge parsed events to OTel span events"
```

---

## Task 17: End-to-end scenario test

**Files:**
- Create: `tests/scenarios/test_telemetry_e2e.py`

- [ ] **Step 1: Write the scenario**

```python
"""End-to-end OTel scenario: a phase invocation produces the expected trace shape.

Uses MockWorld + FakeHoneycomb. No real OTLP traffic. No real Claude subprocess.
"""

from __future__ import annotations

import pytest

from tests.scenarios.fakes.mock_world import MockWorld


@pytest.mark.asyncio
async def test_plan_phase_produces_expected_trace(monkeypatch):
    world = (
        MockWorld()
        .add_repo("org/repo", "/tmp/repo")
        .add_issue(1234, title="test issue", labels=["hydraflow-ready"])
        .set_phase_result("plan", 1234, {"status": "complete"})
    )
    try:
        await world.harness.run_phase("plan", 1234)

        # Assert the trace shape: 1 root + at least 1 child.
        world.honeycomb.assert_trace_shape(
            issue_num=1234,
            expected_root="hf.runner.plan",
            expected_children=[],  # children depend on what the phase does;
                                    # at minimum the runner span exists
        )
        world.honeycomb.assert_attribute_present("hf.runner.plan", "hf.issue")
        world.honeycomb.assert_attribute_present("hf.runner.plan", "hf.session_id")
        world.honeycomb.assert_no_orphan_spans()
    finally:
        world.honeycomb.shutdown()


@pytest.mark.asyncio
async def test_phase_failure_records_error_with_slug(monkeypatch):
    from src.exception_classify import CreditExhaustedError

    def _explode(*a, **kw):
        raise CreditExhaustedError("out of budget")

    world = (
        MockWorld()
        .add_repo("org/repo", "/tmp/repo")
        .add_issue(9999, title="failing issue", labels=["hydraflow-ready"])
        .fail_service("planner")  # use the existing fail_service DSL
    )
    try:
        with pytest.raises(CreditExhaustedError):
            await world.harness.run_phase("plan", 9999)

        spans = world.honeycomb.find_spans(name="hf.runner.plan")
        assert len(spans) == 1
        assert spans[0].attributes["error"] is True
        assert spans[0].attributes["exception.slug"] == "err-credit-exhausted"
    finally:
        world.honeycomb.shutdown()
```

(Adjust `world.harness.run_phase`, `fail_service`, etc. to the real MockWorld API.)

- [ ] **Step 2: Run**

```bash
pytest tests/scenarios/test_telemetry_e2e.py -v
```

If MockWorld doesn't directly expose a way to drive a phase synchronously, look for an example in `tests/scenarios/test_principles_audit_scenario.py` and copy its harness-driving pattern.

- [ ] **Step 3: Commit**

```bash
git add tests/scenarios/test_telemetry_e2e.py
git commit -m "test: e2e telemetry scenario — phase produces expected trace shape"
```

---

## Task 18: Architecture invariant tests

**Files:**
- Create: `tests/architecture/test_otel_invariants.py`

- [ ] **Step 1: Write the invariant tests**

```python
"""Architecture tests enforcing OTel invariants across the codebase."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"


def _files_importing(module_name: str) -> list[Path]:
    out: list[Path] = []
    for f in SRC.rglob("*.py"):
        text = f.read_text()
        if module_name in text:
            out.append(f)
    return out


def test_base_runner_execute_is_decorated():
    """BaseRunner._execute must carry @runner_span."""
    f = SRC / "base_runner.py"
    tree = ast.parse(f.read_text())
    found = False
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == "_execute":
            decorator_names = [
                ast.unparse(d).split("(")[0] for d in node.decorator_list
            ]
            if any("runner_span" in d for d in decorator_names):
                found = True
                break
    assert found, "BaseRunner._execute must be decorated with @runner_span()"


def test_base_loop_do_work_is_decorated():
    f = SRC / "base_background_loop.py"
    tree = ast.parse(f.read_text())
    found = False
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name in (
            "_do_work",
            "_run_tick",
        ):
            decorator_names = [
                ast.unparse(d).split("(")[0] for d in node.decorator_list
            ]
            if any("loop_span" in d for d in decorator_names):
                found = True
                break
    assert found, "BaseBackgroundLoop._do_work (or _run_tick) must be decorated with @loop_span()"


def test_no_bare_create_task_in_instrumented_files():
    """Instrumented files must not call asyncio.create_task without storing the
    reference (otherwise span context propagation breaks). This is a
    pre-existing rule per gotchas.md; the OTel invariant codifies it for
    files we instrument."""
    instrumented = [
        SRC / "base_runner.py",
        SRC / "base_background_loop.py",
        SRC / "pr_manager.py",
        SRC / "workspace.py",
        SRC / "events.py",
    ]
    offenders: list[tuple[Path, int]] = []
    for f in instrumented:
        if not f.exists():
            continue
        text = f.read_text()
        for i, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if "asyncio.create_task(" in stripped and "=" not in stripped.split(
                "create_task("
            )[0]:
                offenders.append((f, i))
    assert not offenders, (
        "Bare asyncio.create_task() in instrumented files breaks OTel "
        f"context propagation. Store the task reference. Offenders: {offenders}"
    )


def test_hf_attrs_only_set_via_helper():
    """No file outside src/telemetry/ should call span.set_attribute('hf.*'...)
    directly — all hf.* attrs must go through add_hf_context."""
    offenders: list[tuple[Path, int, str]] = []
    for f in SRC.rglob("*.py"):
        if "telemetry" in f.parts:
            continue
        text = f.read_text()
        for i, line in enumerate(text.splitlines(), start=1):
            if "set_attribute" in line and '"hf.' in line:
                offenders.append((f, i, line.strip()))
    assert not offenders, (
        "hf.* attributes must be set via add_hf_context, not span.set_attribute. "
        f"Offenders: {offenders}"
    )


def test_new_fakes_have_unit_tests():
    """Any tests/scenarios/fakes/fake_*.py file must have a parallel
    tests/test_fake_*.py unit test file."""
    fakes_dir = REPO_ROOT / "tests" / "scenarios" / "fakes"
    tests_dir = REPO_ROOT / "tests"
    missing: list[str] = []
    for fake_file in fakes_dir.glob("fake_*.py"):
        unit_test = tests_dir / f"test_{fake_file.stem}.py"
        if not unit_test.exists():
            missing.append(fake_file.name)
    assert not missing, f"Fakes missing parallel unit test files: {missing}"
```

- [ ] **Step 2: Run — expect PASS** (assuming Tasks 10–15 all landed correctly)

```bash
pytest tests/architecture/test_otel_invariants.py -v
```

- [ ] **Step 3: Commit**

```bash
git add tests/architecture/test_otel_invariants.py
git commit -m "test: architecture invariants for OTel decorators + helpers"
```

---

## Task 19: Disabled-is-noop regression test

**Files:**
- Create: `tests/regressions/test_otel_disabled_is_noop.py`

- [ ] **Step 1: Write the regression test**

```python
"""Regression: with otel_enabled=false, decorator stack is byte-identical
to no decorators (return values, exception types, timing within tolerance).

Catches the case where someone accidentally couples telemetry into business
control flow."""

from __future__ import annotations

import pytest

from src.telemetry.spans import loop_span, port_span, runner_span


class _FakeRunner:
    phase = "implement"
    issue = 1


@pytest.mark.asyncio
async def test_runner_span_disabled_returns_same_value():
    """With no provider configured, decorator stack must return the same
    value as a bare async function."""

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
async def test_port_span_disabled_returns_same_value():
    @port_span("hf.port.test")
    async def decorated(self):
        return [1, 2, 3]

    class X: pass
    assert (await decorated(X())) == [1, 2, 3]
```

- [ ] **Step 2: Run — expect PASS**

```bash
pytest tests/regressions/test_otel_disabled_is_noop.py -v
```

- [ ] **Step 3: Commit**

```bash
git add tests/regressions/test_otel_disabled_is_noop.py
git commit -m "test: regression — otel_enabled=false is byte-identical to no decorators"
```

---

## Task 20: Quality gate + full suite

- [ ] **Step 1: Run `make quality`**

```bash
make quality 2>&1 | tail -50
```
Fix any lint, type, or format errors. **Do not push to a PR until this passes.**

- [ ] **Step 2: Run the full pytest suite**

```bash
pytest 2>&1 | tail -30
```
Expected: all green (or only pre-existing failures unrelated to OTel — confirm with `git stash` + diff).

- [ ] **Step 3: If any new failures, fix and commit per failure class**

```bash
git add ...
git commit -m "fix: <specific issue>"
```

---

## Task 21: Real-Honeycomb verification (manual + MCP)

This task is run **once** on the engineer's local machine before opening the PR. Output is captured in the PR description.

- [ ] **Step 1: Set up `.env`**

```bash
echo "HONEYCOMB_API_KEY=<the ingest key>" >> .env
echo "HYDRAFLOW_OTEL_ENABLED=true" >> .env
```
Confirm `.env` is gitignored.

- [ ] **Step 2: Boot HydraFlow locally**

```bash
hydraflow 2>&1 | tee /tmp/hydraflow-otel-boot.log
```
Look for `otel: exporter wired` in the log within ~5s.

- [ ] **Step 3: Trigger one phase invocation**

Use whatever existing local-test workflow you have for kicking a phase (UI button, `gh issue create` with the right label, or the existing `scripts/<x>` helper). Wait ~10s for `BatchSpanProcessor` to flush.

- [ ] **Step 4: Authenticate Honeycomb MCP (one-time)**

In a Claude Code session, run any `mcp__honeycomb__*` tool — a browser tab opens for OAuth consent. Click through.

- [ ] **Step 5: Verify via MCP queries**

```
get_workspace_context
```
Expected: `hydraflow` dataset listed.

```
find_columns dataset=hydraflow pattern=hf.*
```
Expected: `hf.issue`, `hf.phase`, `hf.session_id`, `hf.runner`, `hf.success` present.

```
run_query dataset=hydraflow time_range="last 1h"
  calculations: HEATMAP(duration_ms)
  filter: service.name=hydraflow
```
Expected: at least one trace root span visible.

```
run_query dataset=hydraflow time_range="last 1h"
  calculations: COUNT
  group_by: trace.id
  filter: hf.issue=<your test issue number>
```
Expected: 1 trace, with N spans (1 root + children depending on what the phase did).

- [ ] **Step 6: Capture queries + screenshots in PR description**

Open the PR with the four queries pasted into a "Verification" section, and one screenshot of the trace waterfall in Honeycomb's UI showing the root span + children.

- [ ] **Step 7: Open PR**

```bash
gh pr create --base main --head otel-honeycomb-phase-a-spec \
  --title "feat(telemetry): OTel Honeycomb instrumentation — Phase A" \
  --body-file /tmp/pr-body.md
```

PR body template:
```markdown
## Summary
Phase A of OTel Honeycomb instrumentation. Adds feature-gated OpenTelemetry
SDK bootstrap, custom spans on phase runners / background loops / PR & workspace
ports, subprocess-Claude milestones via trace_collector bridge, and a
FakeHoneycomb MockWorld fake. Sentry coexists unchanged.

Phase B (Honeycomb-Loop: trace anomaly → GitHub issue) is a separate spec,
deferred until ≥30 days of trace data inform thresholds.

## Spec & Plan
- Spec: `docs/superpowers/specs/2026-05-02-otel-honeycomb-phase-a-design.md`
- Plan: `docs/superpowers/plans/2026-05-02-otel-honeycomb-phase-a.md`

## Verification
[paste the four MCP queries + their results here]
[attach screenshot of Honeycomb trace waterfall]

## Test plan
- [x] make quality
- [x] pytest tests/test_telemetry_*
- [x] pytest tests/scenarios/test_telemetry_e2e.py
- [x] pytest tests/architecture/test_otel_invariants.py
- [x] pytest tests/regressions/test_otel_disabled_is_noop.py
- [x] Real Honeycomb ingest verified via MCP (queries above)
```

---

## Self-Review

### 1. Spec coverage

Walking each spec section against the plan:

- Spec §2 architectural rules → Tasks 3 (decorators are passive), 7 (boot-time gate), 3+10–13 (`add_hf_context` is the only `hf.*` setter, enforced by Task 18 invariant). ✅
- Spec §3 trace boundaries → Tasks 10 (runner root), 11 (loop root). ✅
- Spec §4.1 new module → Tasks 2, 3, 4, 5. ✅
- Spec §4.2 touched modules → Tasks 6 (config), 7 (server), 10 (runner), 11 (loop), 12 (pr), 13 (workspace), 14 (exception_classify), 15 (events), 16 (trace_collector). ✅
- Spec §4.3 auto-instrumentation → Task 4 (`_register_auto_instrumentation`). ✅
- Spec §4.4 cardinality budget → `validate_attr` in Task 3, enforced by tests. ✅
- Spec §5 data flow → Tasks 10–16 cumulatively produce the described shape; Task 17 verifies. ✅
- Spec §6 configuration → Task 6. ✅
- Spec §7 failure modes → Task 3 (decorator safety), Task 4 (init failure), Task 19 (disabled regression). ✅
- Spec §8 testing → Tasks 2–19 collectively cover all rows of the spec's testing table. ✅
- Spec §8.1 MockWorld extension → Tasks 8, 9. ✅
- Spec §10 verification bar → Task 21. ✅

No gaps.

### 2. Placeholder scan

Checked for "TBD", "TODO", "implement later", "fill in details" — none in plan steps. Two places where the engineer must adapt to real signatures (Tasks 12, 13, 16) — these are explicit "grep-first, then mirror" instructions, not placeholders. The replacement is shown in the same step.

### 3. Type / signature consistency

- `add_hf_context(span, *, issue, phase, session_id, repo, runner, model, attempt, extra)` — same kwargs in Task 3 implementation, Task 3 tests, and Task 14 reference. ✅
- `runner_span()`, `loop_span()`, `port_span(name)` — same signatures across Tasks 3, 10, 11, 12, 13. ✅
- `slug_for(exc)` — same signature in Tasks 2, 3, 14. ✅
- `bridge_event_to_span(span, event)` — same in Tasks 5, 16. ✅
- `FakeHoneycomb.find_spans(*, name=None, attrs=None)` — same in Tasks 8, 9, 10, 11, 12, 13, 14, 15, 17. ✅

### 4. Ambiguity / open questions

Three places where the engineer has a small judgment call (clearly flagged with "grep first" and a fallback strategy):
- Task 11: if `_do_work` is `abstractmethod`, decorate `_run_tick` instead.
- Task 12 / 13: real method signatures determine test mocks.
- Task 16: `trace_collector`'s actual function name for the per-event hook.

These are explicit and resolvable in <2 minutes each.

---

## Execution

**Plan complete and saved to `docs/superpowers/plans/2026-05-02-otel-honeycomb-phase-a.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration, your context stays clean.

**2. Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints for review.

**Which approach?**
