"""Tests for route_types module — canonical type aliases and duplicate guard."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Annotated, get_args, get_origin

from route_types import RepoSlugParam

SRC_DIR = Path(__file__).resolve().parent.parent / "src"


class TestRepoSlugParam:
    """RepoSlugParam is importable and has expected metadata."""

    def test_is_annotated(self) -> None:
        assert get_origin(RepoSlugParam) is Annotated

    def test_base_type_is_optional_str(self) -> None:
        args = get_args(RepoSlugParam)
        # First arg is the base type (str | None)
        base = args[0]
        assert base == str | None

    def test_query_metadata_description(self) -> None:
        args = get_args(RepoSlugParam)
        query_info = args[1]
        assert hasattr(query_info, "description")
        assert query_info.description == "Repo slug to scope the request"  # type: ignore[union-attr]


class TestNoDuplicateAnnotatedAliases:
    """Guard: RepoSlugParam must be defined in exactly one src file."""

    def _find_definitions(self, name: str, scan_dir: Path | None = None) -> list[Path]:
        """Scan src/ (or *scan_dir*) for files that define ``name = Annotated[...]``."""
        hits: list[Path] = []
        for py_file in (scan_dir or SRC_DIR).rglob("*.py"):
            try:
                tree = ast.parse(py_file.read_text(), filename=str(py_file))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Assign)
                    and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id == name
                    and isinstance(node.value, ast.Subscript)
                    and isinstance(node.value.value, ast.Name)
                    and node.value.value.id == "Annotated"
                ):
                    hits.append(py_file)
        return hits

    def test_repo_slug_param_defined_once(self) -> None:
        hits = self._find_definitions("RepoSlugParam")
        assert len(hits) == 1, (
            f"RepoSlugParam defined in {len(hits)} files; expected exactly 1 "
            f"(route_types.py). Found in: {[str(h.relative_to(SRC_DIR)) for h in hits]}"
        )
        assert hits[0].name == "route_types.py"

    def test_detects_duplicate(self, tmp_path: Path) -> None:
        """Verify _find_definitions catches a duplicate definition in an isolated dir."""
        # Create a fake source tree with two files defining RepoSlugParam
        fake_src = tmp_path / "src"
        fake_src.mkdir()
        alias_def = (
            "from typing import Annotated\n"
            "from fastapi import Query\n"
            "RepoSlugParam = Annotated[str | None, Query(description='dup')]\n"
        )
        (fake_src / "routes_a.py").write_text(alias_def)
        (fake_src / "routes_b.py").write_text(alias_def)

        hits = self._find_definitions("RepoSlugParam", scan_dir=fake_src)
        assert len(hits) == 2, (
            f"Scanner should find 2 definitions, found {len(hits)}: {hits}"
        )
