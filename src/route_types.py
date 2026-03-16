"""Canonical type aliases for FastAPI route parameters.

Import shared parameter types from here — never duplicate ``Annotated[...]``
definitions in individual route modules.
"""

from __future__ import annotations

from typing import Annotated, TypeAlias

from fastapi import Query

RepoSlugParam: TypeAlias = Annotated[
    str | None,
    Query(description="Repo slug to scope the request"),
]
