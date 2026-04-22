"""Self-instrumentation for the audit tool (ADR-0044, P7.6 / P7.7).

The audit follows the principles it enforces: unhandled exceptions route
through a Sentry filter that drops transient errors and forwards real bugs.
If `sentry_sdk` is not installed, every function here is a no-op so the
tool stays runnable in minimal environments.

Future backends (OTLP, structured logs, a sidecar) plug in behind the same
`report_unhandled` entry point; they do not require a change at the call site.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager

_BUG_TYPES: tuple[type[BaseException], ...] = (
    TypeError,
    KeyError,
    AttributeError,
    ValueError,
    IndexError,
    NotImplementedError,
)

log = logging.getLogger("hydraflow_audit")


def init() -> None:
    """Initialise Sentry if available and a DSN is configured."""
    dsn = os.environ.get("HYDRAFLOW_AUDIT_SENTRY_DSN") or os.environ.get("SENTRY_DSN")
    if not dsn:
        return
    try:
        import sentry_sdk  # type: ignore[import-not-found]
    except ImportError:
        return

    def _before_send(event, hint):  # pragma: no cover — exercised only with a real DSN
        exc_info = hint.get("exc_info")
        if exc_info and not issubclass(exc_info[0], _BUG_TYPES):
            return None
        return event

    sentry_sdk.init(dsn=dsn, before_send=_before_send, traces_sample_rate=0.0)


def report_unhandled(exc: BaseException) -> None:
    """Forward real bugs to Sentry; log transient failures at warning."""
    if isinstance(exc, _BUG_TYPES):
        try:
            import sentry_sdk  # type: ignore[import-not-found]

            sentry_sdk.capture_exception(exc)
        except ImportError:
            log.exception("unhandled bug in audit tool (sentry unavailable)")
        else:
            log.exception("unhandled bug in audit tool")
    else:
        log.warning("transient failure in audit tool: %s", exc)


@contextmanager
def guard():
    """Wrap the CLI entry point so unhandled exceptions flow through the filter."""
    try:
        yield
    except Exception as exc:  # noqa: BLE001 — the point is to see everything
        report_unhandled(exc)
        raise
