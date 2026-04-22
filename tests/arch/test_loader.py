from __future__ import annotations

from pathlib import Path

import pytest

from arch.loader import LoaderError, load_rule_module

FIXTURES = Path(__file__).parent / "fixtures" / "rule_modules"


def test_load_valid_module_returns_rule_module() -> None:
    rm = load_rule_module(FIXTURES / "valid.py")
    assert callable(rm.extractor)
    assert "src/a/**" in rm.layers.mapping
    assert len(rm.fitness) == 1


def test_missing_extractor_field_raises() -> None:
    with pytest.raises(LoaderError, match="EXTRACTOR"):
        load_rule_module(FIXTURES / "missing_extractor.py")


def test_syntax_error_raises() -> None:
    with pytest.raises(LoaderError, match="SyntaxError|invalid syntax"):
        load_rule_module(FIXTURES / "bad_syntax.py")


def test_missing_file_raises() -> None:
    with pytest.raises(LoaderError, match="not found"):
        load_rule_module(FIXTURES / "nonexistent.py")
