"""Synthetic fixture — bare Mock assigned to Port-annotated target."""

from unittest.mock import AsyncMock

from src.ports import PRPort


def make() -> None:
    mock: PRPort = AsyncMock()  # FAIL — bare AsyncMock to Port-typed target
