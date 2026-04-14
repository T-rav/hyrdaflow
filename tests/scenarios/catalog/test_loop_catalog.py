"""LoopCatalog registers loops via decorator and instantiates them on demand."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock

import pytest

from tests.scenarios.catalog.loop_catalog import LoopCatalog, register_loop


def _noop_builder(ports: dict[str, Any], config: Any, deps: Any) -> str:
    _ = (ports, config, deps)
    return "built"


@pytest.fixture(autouse=True)
def _reset_registry() -> Iterator[None]:
    LoopCatalog.reset()
    yield
    LoopCatalog.reset()


def test_register_loop_adds_to_catalog() -> None:
    register_loop("noop")(_noop_builder)

    assert LoopCatalog.is_registered("noop")
    assert (
        LoopCatalog.instantiate("noop", ports={}, config=MagicMock(), deps=MagicMock())
        == "built"
    )


def test_unknown_loop_raises() -> None:
    with pytest.raises(KeyError, match="nope"):
        LoopCatalog.instantiate("nope", ports={}, config=MagicMock(), deps=MagicMock())


def test_duplicate_name_raises() -> None:
    register_loop("dup")(_noop_builder)

    with pytest.raises(ValueError, match="already registered"):
        register_loop("dup")(_noop_builder)


def test_registered_names_lists_all() -> None:
    register_loop("one")(_noop_builder)
    register_loop("two")(_noop_builder)

    assert set(LoopCatalog.registered_names()) == {"one", "two"}
