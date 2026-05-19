"""Synthetic fixture — all Mock-of-Port usages have spec=."""

from unittest.mock import AsyncMock, MagicMock

from src.ports import PRPort


def via_kwarg() -> PRPort:
    return AsyncMock(spec=PRPort)  # PASS


def via_assignment() -> PRPort:
    mock: PRPort = AsyncMock(spec=PRPort)  # PASS
    return mock


def non_port_unrestricted() -> object:
    return AsyncMock()  # PASS — not a Port; rule does not apply


def via_magicmock_kwarg() -> object:
    return MagicMock(spec=PRPort)  # PASS — MagicMock equally subject to the rule
