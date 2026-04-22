from __future__ import annotations

import ast
from pathlib import Path

from arch.models import ImportGraph

SKIP_DIRS = {".venv", "venv", "__pycache__", "node_modules", ".git", "dist", "build"}


def python_ast_extractor(repo_path: str) -> ImportGraph:
    root = Path(repo_path)
    graph = ImportGraph(module_unit="file")

    py_files: list[Path] = []
    for path in root.rglob("*.py"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        py_files.append(path)

    basename_to_rel: dict[str, str] = {}
    for f in py_files:
        rel = f.relative_to(root).as_posix()
        graph.nodes.add(rel)
        stem = f.stem
        basename_to_rel.setdefault(stem, rel)

    for f in py_files:
        rel = f.relative_to(root).as_posix()
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        except SyntaxError:
            continue
        # Only top-level imports are architectural dependencies worth checking.
        # Imports inside `if TYPE_CHECKING:`, function bodies, or try/except
        # are intentional deferrals (runtime optional, circular-break, etc.)
        # and are not evidence of a module-level coupling.
        for node in ast.iter_child_nodes(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names.extend(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module.split(".")[0])
            for name in names:
                target = basename_to_rel.get(name)
                if target and target != rel:
                    graph.add_edge(rel, target)

    return graph
