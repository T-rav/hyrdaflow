from __future__ import annotations

from pathlib import Path

import pytest

from arch.tree_sitter import tree_sitter_extractor

TS_FIXTURE = Path(__file__).parent / "fixtures" / "ts_repo"


def test_typescript_extractor_emits_file_edges() -> None:
    extract = tree_sitter_extractor("typescript")
    graph = extract(str(TS_FIXTURE))
    assert graph.module_unit == "file"
    assert ("src/a.ts", "src/b.ts") in graph.edges
    assert ("src/a.ts", "src/c.ts") in graph.edges


def test_unsupported_language_raises_clear_error() -> None:
    with pytest.raises(ValueError, match="unsupported language"):
        tree_sitter_extractor("klingon")
