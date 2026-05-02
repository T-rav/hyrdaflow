"""Maps exception classes to static `exception.slug` identifiers.

Slugs are low-cardinality, greppable, and stable across releases so that
Honeycomb queries / Phase B's anomaly loop can group by `exception.slug`
without depending on exception messages or stack traces.
"""

from __future__ import annotations

import asyncio
import subprocess

from src.subprocess_util import CreditExhaustedError

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
