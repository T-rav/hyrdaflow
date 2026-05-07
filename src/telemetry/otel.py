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
    global _INITIALIZED  # noqa: PLW0603
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

    global _PROVIDER  # noqa: PLW0603

    resource = Resource.create(
        {
            "service.name": getattr(config, "otel_service_name", "hydraflow"),
            "deployment.environment": getattr(config, "otel_environment", "local"),
            "service.version": _read_version(),
            "process.pid": os.getpid(),
        }
    )
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
    """Enable auto-instrumentation for HTTP/asyncio/logging.

    FastAPI is opt-in per app instance via FastAPIInstrumentor.instrument_app(app)
    in server.py, but the global instrumentors below cover everything else.

    Note: opentelemetry-instrumentation-requests was intentionally not
    installed — codebase uses httpx, not requests.
    """
    from opentelemetry.instrumentation.asyncio import AsyncioInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.logging import LoggingInstrumentor

    AsyncioInstrumentor().instrument()
    HTTPXClientInstrumentor().instrument()
    LoggingInstrumentor().instrument(set_logging_format=True)


def _read_version() -> str:
    try:
        from importlib.metadata import version

        return version("hydraflow")
    except Exception:
        return "unknown"


def shutdown_otel() -> None:
    """Flush + shutdown the provider. Idempotent."""
    global _PROVIDER, _INITIALIZED  # noqa: PLW0603
    if _PROVIDER is None:
        return
    try:
        _PROVIDER.shutdown()
    except Exception:
        logger.exception("shutdown_otel failed")
    finally:
        _PROVIDER = None
        _INITIALIZED = False
