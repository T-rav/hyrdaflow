"""LoopCatalog registers loops via decorator and instantiates them on demand."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tests.scenarios.catalog.loop_catalog import LoopCatalog, register_loop


@pytest.fixture(autouse=True)
def _clear_registry() -> None:
    LoopCatalog.reset()


def test_register_loop_adds_to_catalog() -> None:
    @register_loop("noop")
    def _build(ports: dict, config: object, deps: object) -> object:
        _ = (ports, config, deps)
        return "built"

    assert LoopCatalog.is_registered("noop")
    assert (
        LoopCatalog.instantiate("noop", ports={}, config=MagicMock(), deps=MagicMock())
        == "built"
    )


def test_unknown_loop_raises() -> None:
    with pytest.raises(KeyError, match="nope"):
        LoopCatalog.instantiate("nope", ports={}, config=MagicMock(), deps=MagicMock())


def test_duplicate_name_raises() -> None:
    @register_loop("dup")
    def _a(ports: dict, config: object, deps: object) -> object:
        return "a"

    with pytest.raises(ValueError, match="already registered"):

        @register_loop("dup")
        def _b(ports: dict, config: object, deps: object) -> object:
            return "b"


def test_registered_names_lists_all() -> None:
    @register_loop("one")
    def _one(ports: dict, config: object, deps: object) -> object:
        return 1

    @register_loop("two")
    def _two(ports: dict, config: object, deps: object) -> object:
        return 2

    assert set(LoopCatalog.registered_names()) == {"one", "two"}
