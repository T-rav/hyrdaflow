"""Verify every catalog builder registers successfully via the catalog.

The loop list is derived from ``_BUILDERS`` so it stays in sync automatically
when new builders are added. The CI completeness guard lives in
``test_catalog_completeness.py``; this file only checks that each registered
builder is retrievable from ``LoopCatalog`` after ``ensure_registered()``.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests.scenarios.catalog import LoopCatalog
from tests.scenarios.catalog.loop_registrations import _BUILDERS, ensure_registered


@pytest.fixture(autouse=True)
def _ensure_registered() -> Iterator[None]:
    ensure_registered()
    yield


@pytest.mark.parametrize("name", sorted(_BUILDERS.keys()))
def test_loop_registered(name: str) -> None:
    assert LoopCatalog.is_registered(name), f"{name!r} not registered"
