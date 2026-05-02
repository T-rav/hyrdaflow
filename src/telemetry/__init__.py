"""HydraFlow telemetry module — OpenTelemetry instrumentation for Honeycomb.

Public surface kept intentionally small. Use `init_otel(config)` once at
process start and `shutdown_otel()` once at exit. Decorators in
`telemetry.spans` provide the per-method instrumentation.
"""

# from src.telemetry.otel import init_otel, shutdown_otel  # Task 4
from src.telemetry.slugs import slug_for

__all__ = ["slug_for"]
