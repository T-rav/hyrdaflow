"""Sentry-backed implementation of ObservabilityPort.

This adapter wraps ``sentry_sdk`` and is the sole place in production code
that imports it directly (aside from the SDK initialisation in ``server.py``).
All domain code routes observability calls through the injected
``ObservabilityPort`` so a different backend (OTLP, structured-log, no-op)
can be substituted without touching call sites.

The adapter is a **no-op** when ``sentry_sdk`` is not installed — every public
method silently returns so callers never need a try/except around port calls.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("hydraflow.observability.sentry_adapter")


class SentryObservabilityAdapter:
    """ObservabilityPort implementation backed by sentry_sdk.

    Constructed once at service-registry time and injected wherever the port
    is consumed.  When ``sentry_sdk`` is not installed or fails, every method
    degrades to a no-op so the application continues running without Sentry.
    """

    # Sentinel used by tests to distinguish the real adapter from FakeSentry.
    _is_fake_adapter: bool = False

    def capture_exception(self, exc: BaseException) -> None:
        """Forward *exc* to ``sentry_sdk.capture_exception``."""
        try:
            import sentry_sdk  # noqa: PLC0415

            sentry_sdk.capture_exception(exc)
        except ImportError:
            pass
        except Exception:  # noqa: BLE001
            logger.debug("sentry capture_exception failed", exc_info=True)

    def capture_message(self, message: str, *, level: str = "info") -> None:
        """Forward *message* to ``sentry_sdk.capture_message``."""
        try:
            import sentry_sdk  # noqa: PLC0415

            sentry_sdk.capture_message(message, level=level)
        except ImportError:
            pass
        except Exception:  # noqa: BLE001
            logger.debug("sentry capture_message failed", exc_info=True)

    def breadcrumb(self, category: str, message: str, **data: object) -> None:
        """Forward a breadcrumb to ``sentry_sdk.add_breadcrumb``.

        The ``level`` key in *data* is promoted to a top-level kwarg so Sentry
        displays it correctly.  All remaining keys land in ``data``.
        """
        try:
            import sentry_sdk  # noqa: PLC0415

            level = str(data.pop("level", "info"))
            sentry_sdk.add_breadcrumb(
                category=category,
                message=message,
                level=level,
                data=data if data else None,
            )
        except ImportError:
            pass
        except Exception:  # noqa: BLE001
            logger.debug("sentry breadcrumb failed", exc_info=True)

    def set_measurement(self, name: str, value: float, unit: str = "") -> None:
        """Forward a measurement to ``sentry_sdk.set_measurement``."""
        try:
            import sentry_sdk  # noqa: PLC0415

            if unit:
                sentry_sdk.set_measurement(name, value, unit)
            else:
                sentry_sdk.set_measurement(name, value)
        except ImportError:
            pass
        except Exception:  # noqa: BLE001
            logger.debug("sentry set_measurement failed", exc_info=True)

    def flush(self, timeout_ms: int = 2000) -> bool:
        """Flush buffered Sentry events. Returns True on success."""
        try:
            import sentry_sdk  # noqa: PLC0415

            client = sentry_sdk.get_client()
            if client.options:
                result = client.flush(timeout=timeout_ms / 1000)
                return bool(result) if result is not None else True
            return True
        except (ImportError, AttributeError):
            return True
        except Exception:  # noqa: BLE001
            logger.debug("sentry flush failed", exc_info=True)
            return True
