"""Cross-cutting exception classification utilities.

This module lives at the Infrastructure/Cross-cutting boundary so that
both Application-layer code (``phase_utils``) and Infrastructure-layer
code (``merge_conflict_resolver``) can import it without creating upward
dependency violations.

Extracted from ``phase_utils`` as part of the architecture layering fix
(issue #5919).
"""

from __future__ import annotations

import logging

logger = logging.getLogger("exception_classify")

#: Exception types that almost certainly indicate a code bug rather than a
#: transient/environmental failure.  When one of these is caught in a
#: catch-all handler, it should be logged at a higher severity so operators
#: can distinguish "needs a code fix" from "will probably succeed on retry".
LIKELY_BUG_EXCEPTIONS: tuple[type[BaseException], ...] = (
    TypeError,
    KeyError,
    AttributeError,
    ValueError,
    IndexError,
    NotImplementedError,
)


def is_likely_bug(exc: BaseException) -> bool:
    """Return True if *exc* is likely a code bug rather than a transient failure."""
    return isinstance(exc, LIKELY_BUG_EXCEPTIONS)


def capture_if_bug(exc: Exception, **context: object) -> None:
    """Send to Sentry only if the exception looks like a real bug."""
    try:
        import sentry_sdk  # noqa: PLC0415

        if is_likely_bug(exc):
            sentry_sdk.capture_exception(exc)
        else:
            sentry_sdk.add_breadcrumb(
                category="transient_error",
                message=str(exc)[:500],
                level="warning",
                data=context,
            )
    except Exception:
        # Never let Sentry errors crash the application, but leave a debug
        # breadcrumb so operators can tell when Sentry itself is broken.
        logger.debug("sentry sdk failure suppressed in capture_if_bug", exc_info=True)


def reraise_on_credit_or_bug(exc: BaseException) -> None:
    """Re-raise *exc* if it is a fatal infrastructure error or a likely bug.

    Call this at the top of an ``except Exception`` handler to replace the
    duplicated pattern::

        except (AuthenticationError, CreditExhaustedError):
            raise
        except Exception as exc:
            if is_likely_bug(exc):
                raise

    with the shorter::

        except Exception as exc:
            reraise_on_credit_or_bug(exc)
    """
    from subprocess_util import AuthenticationError, CreditExhaustedError

    if isinstance(exc, AuthenticationError | CreditExhaustedError) or is_likely_bug(
        exc
    ):
        # Tag active span (best-effort; never block re-raise)
        try:
            from opentelemetry import trace  # noqa: PLC0415

            from src.telemetry.slugs import slug_for  # noqa: PLC0415

            span = trace.get_current_span()
            if span is not None and span.is_recording():
                span.set_attribute("error", True)
                span.set_attribute("exception.slug", slug_for(exc))
        except Exception:  # noqa: BLE001
            pass
        raise exc
