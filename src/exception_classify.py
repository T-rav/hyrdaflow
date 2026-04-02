"""Cross-cutting exception classification utilities.

This module lives at the Infrastructure/Cross-cutting boundary so that
both Application-layer code (``phase_utils``) and Infrastructure-layer
code (``merge_conflict_resolver``) can import it without creating upward
dependency violations.

Extracted from ``phase_utils`` as part of the architecture layering fix
(issue #5919).
"""

from __future__ import annotations

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
