"""Canonical type aliases for FastAPI route parameters and API DTOs.

Import shared parameter types from here — never duplicate ``Annotated[...]``
definitions in individual route modules.
"""

from __future__ import annotations

from typing import Annotated, TypeAlias

from fastapi import Query

from models import (
    ControlStatusConfig,
    ControlStatusResponse,
)

RepoSlugParam: TypeAlias = Annotated[
    str | None,
    Query(description="Repo slug to scope the request"),
]


__all__ = [
    "ControlStatusConfig",
    "ControlStatusResponse",
    "RepoSlugParam",
]
