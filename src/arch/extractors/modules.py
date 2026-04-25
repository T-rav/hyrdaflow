"""Build a package-level import graph for src/.

Each .py file's package is the dotted path of its parent directory under
src/ (e.g. src/foo/a.py belongs to package src.foo). Two files importing
two different things from the same package produce one edge with weight
2. External imports (stdlib, third-party) are filtered out — only
src.* → src.* edges are kept.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

from arch._models import ModuleEdge, ModuleGraph, ModuleNode


def _package_of(path: Path, src_root: Path) -> str:
    """Return the dotted package name for `path` relative to `src_root`'s parent.

    A file at src/foo/a.py belongs to package src.foo.
    A file at src/foo.py belongs to package src.
    """
    rel = path.relative_to(src_root.parent)
    parts = rel.with_suffix("").parts
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return ".".join(parts[:-1])


def _module_targets(node: ast.AST) -> list[str]:
    out: list[str] = []
    if isinstance(node, ast.Import):
        for alias in node.names:
            out.append(alias.name.split(".")[0])
    elif isinstance(node, ast.ImportFrom) and node.module:
        out.append(node.module.split(".")[0])
    return out


def extract_module_graph(src_dir: Path) -> ModuleGraph:
    src_dir = Path(src_dir).resolve()
    nodes: set[str] = set()
    raw_edges: Counter[tuple[str, str]] = Counter()

    # First pass: collect all package names that exist under src/.
    local_packages: set[str] = set()
    for py in src_dir.rglob("*.py"):
        local_packages.add(_package_of(py, src_dir))

    for py in sorted(src_dir.rglob("*.py")):
        try:
            tree = ast.parse(py.read_text())
        except SyntaxError:
            continue
        from_pkg = _package_of(py, src_dir)
        nodes.add(from_pkg)
        for stmt in ast.walk(tree):
            for tgt in _module_targets(stmt):
                # Resolve "bar" -> "src.bar" if src.bar exists locally.
                resolved = f"src.{tgt}" if f"src.{tgt}" in local_packages else tgt
                if resolved not in local_packages:
                    continue  # external dep, skip
                if resolved == from_pkg:
                    continue  # self-import
                raw_edges[(from_pkg, resolved)] += 1
                nodes.add(resolved)

    edges = [
        ModuleEdge(from_module=a, to_module=b, weight=w)
        for (a, b), w in sorted(raw_edges.items())
    ]
    return ModuleGraph(
        nodes=[ModuleNode(name=n) for n in sorted(nodes)],
        edges=edges,
    )
