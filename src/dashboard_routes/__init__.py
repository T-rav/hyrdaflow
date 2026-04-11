"""Dashboard route handlers — package wrapper.

This package replaces the former ``dashboard_routes.py`` flat module.
Public symbols are re-exported here so that existing
``from dashboard_routes import X`` statements continue to work.

Private helpers (_-prefixed) should be imported from their submodules
directly: ``from dashboard_routes._common import _coerce_int``.
"""

from __future__ import annotations

from dashboard_routes._routes import (
    RouteContext,
    create_router,
)

__all__ = [
    "RouteContext",
    "create_router",
]
