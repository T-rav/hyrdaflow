"""HydraFlow telemetry module — OpenTelemetry instrumentation for Honeycomb.

Uses relative imports so the package works under both pytest (which puts the
project root on PYTHONPATH and resolves ``src.telemetry``) and standalone
Python (which only has ``src/`` on the path via pyproject's
``package-dir = {"" = "src"}`` and resolves ``telemetry`` directly).
Relative imports avoid the dual-module identity problem entirely.
"""

from .otel import init_otel, shutdown_otel
from .slugs import slug_for

__all__ = ["init_otel", "shutdown_otel", "slug_for"]
