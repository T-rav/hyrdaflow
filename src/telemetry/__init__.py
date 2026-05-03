"""HydraFlow telemetry module — OpenTelemetry instrumentation for Honeycomb."""

from src.telemetry.otel import init_otel, shutdown_otel
from src.telemetry.slugs import slug_for

__all__ = ["init_otel", "shutdown_otel", "slug_for"]
