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
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from opentelemetry import trace
from opentelemetry.trace import Span, Status, StatusCode, Tracer

from .slugs import slug_for

logger = logging.getLogger(__name__)

_F = TypeVar("_F", bound=Callable[..., Awaitable[Any]])

_RUNNER_TRACER_NAME = "hydraflow.runner"
_LOOP_TRACER_NAME = "hydraflow.loop"
_PORT_TRACER_NAME = "hydraflow.port"


@functools.lru_cache(maxsize=8)
def _get_tracer(name: str) -> Tracer:
    """Cache one Tracer per scope name. The OTel SDK's `get_tracer` allocates
    a fresh Tracer object on every call (no internal cache); at HydraFlow's
    span rates we want to allocate once per scope and reuse. Tests should
    call `_get_tracer.cache_clear()` between provider swaps."""
    return trace.get_tracer(name)


# Allow-list of attribute prefixes / bare keys.
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
            runner=getattr(runner_self, "runner", None)
            or runner_self.__class__.__name__,
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
            tracer = _get_tracer(_RUNNER_TRACER_NAME)
            with tracer.start_as_current_span(f"hf.runner.{phase}") as span:
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
            tracer = _get_tracer(_LOOP_TRACER_NAME)
            with tracer.start_as_current_span(f"hf.loop.{name}") as span:
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
            tracer = _get_tracer(_PORT_TRACER_NAME)
            with tracer.start_as_current_span(span_name) as span:
                try:
                    result = await fn(self, *args, **kwargs)
                except Exception as exc:
                    _safe_record_error(span, exc)
                    raise
                return result

        return wrapper  # type: ignore[return-value]

    return decorator
