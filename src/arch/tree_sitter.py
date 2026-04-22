from __future__ import annotations

import ctypes
import pathlib
import warnings
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import tree_sitter as _ts  # type: ignore[import-untyped]
import tree_sitter_languages  # type: ignore[import-untyped]

from arch.models import ImportGraph, ModuleUnit

# tree_sitter ships runtime classes but no py.typed marker; on some pyright
# configurations Language/Parser/Query/QueryCursor resolve as modules rather
# than classes. Aliasing through Any erases the bogus type so annotations and
# call sites don't trip pyright, while preserving runtime behaviour.
Language: Any = _ts.Language
Parser: Any = _ts.Parser
Query: Any = _ts.Query
QueryCursor: Any = _ts.QueryCursor

# tree_sitter_languages 1.10.2 ships a bundled .so; load it directly so we can
# call the C-level tree_sitter_<lang>() functions.  This avoids the broken
# tree_sitter_languages.get_language() / get_parser() shim which was compiled
# for tree-sitter <0.22 and fails with tree-sitter 0.25's new Language.__init__.
_TSL_SO = next(pathlib.Path(next(iter(tree_sitter_languages.__path__))).glob("*.so"))
_TSL_LIB = ctypes.cdll.LoadLibrary(str(_TSL_SO))


def _load_language(name: str) -> Any:
    """Return a tree_sitter.Language for *name* using the bundled .so."""
    fn = getattr(_TSL_LIB, f"tree_sitter_{name}", None)
    if fn is None:
        raise ValueError(f"unsupported language {name!r}: symbol not found in .so")
    fn.restype = ctypes.c_void_p
    ptr = fn()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return Language(ptr)


SUPPORTED: dict[str, dict[str, Any]] = {
    "python": {
        "ext": (".py",),
        "unit": "file",
        "query": "(import_statement) @i (import_from_statement) @i",
        "capture": None,  # whole-node capture; extract module string in Python
    },
    "typescript": {
        "ext": (".ts", ".tsx"),
        "unit": "file",
        "query": "(import_statement source: (string) @src)",
        "capture": "src",
    },
    "javascript": {
        "ext": (".js", ".jsx", ".mjs"),
        "unit": "file",
        "query": "(import_statement source: (string) @src)",
        "capture": "src",
    },
    "go": {
        "ext": (".go",),
        "unit": "directory",
        "query": "(import_declaration (import_spec path: (interpreted_string_literal) @src))",
        "capture": "src",
    },
    "java": {
        "ext": (".java",),
        "unit": "file",
        "query": "(import_declaration (scoped_identifier) @src)",
        "capture": "src",
    },
    "rust": {
        "ext": (".rs",),
        "unit": "file",
        "query": "(use_declaration) @i",
        "capture": None,
    },
    "ruby": {
        "ext": (".rb",),
        "unit": "file",
        "query": '(call method: (identifier) @m (#match? @m "require|require_relative") arguments: (argument_list (string) @src))',
        "capture": "src",
    },
}

SKIP_DIRS = {
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    ".git",
    "dist",
    "build",
    "vendor",
    "target",
}


def tree_sitter_extractor(language: str) -> Callable[[str], ImportGraph]:
    if language not in SUPPORTED:
        raise ValueError(
            f"unsupported language {language!r}; available: {sorted(SUPPORTED)}"
        )

    cfg = SUPPORTED[language]
    lang = _load_language(language)
    parser = Parser(lang)
    query = Query(lang, cfg["query"])
    cap_name: str | None = cfg["capture"]
    exts: tuple[str, ...] = cfg["ext"]
    unit: ModuleUnit = cast(ModuleUnit, cfg["unit"])

    def extract(repo_path: str) -> ImportGraph:
        root = Path(repo_path)
        graph = ImportGraph(module_unit=unit)

        files: list[Path] = []
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if path.suffix in exts:
                files.append(path)

        stems: dict[str, str] = {}
        for f in files:
            rel = f.relative_to(root).as_posix()
            graph.nodes.add(
                rel if unit == "file" else f.parent.relative_to(root).as_posix()
            )
            stems.setdefault(f.stem, rel)

        for f in files:
            src_bytes = f.read_bytes()
            tree = parser.parse(src_bytes)
            rel_src = f.relative_to(root).as_posix()
            source_node = (
                rel_src if unit == "file" else f.parent.relative_to(root).as_posix()
            )
            cursor = QueryCursor(query)
            for _, captures in cursor.matches(tree.root_node):
                key = cap_name if cap_name is not None else next(iter(captures), None)
                if key is None:
                    continue
                nodes = captures.get(key, [])
                for node in nodes:
                    text = src_bytes[node.start_byte : node.end_byte].decode(
                        "utf-8", errors="ignore"
                    )
                    spec = _strip_quotes(text)
                    target = _resolve_relative(f.parent, spec, exts, root) or stems.get(
                        spec.split("/")[-1].split(".")[0]
                    )
                    if target is None:
                        continue
                    resolved = target if unit == "file" else str(Path(target).parent)
                    if resolved != source_node:
                        graph.add_edge(source_node, resolved)
        return graph

    return extract


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] in "\"'" and s[-1] in "\"'":
        return s[1:-1]
    return s


def _resolve_relative(
    base: Path, spec: str, exts: tuple[str, ...], root: Path
) -> str | None:
    if not spec.startswith("."):
        return None
    candidate = (base / spec).resolve()
    for ext in exts:
        p = candidate.with_suffix(ext)
        if p.is_file():
            try:
                return p.relative_to(root).as_posix()
            except ValueError:
                return None
    for ext in exts:
        p = candidate / f"index{ext}"
        if p.is_file():
            try:
                return p.relative_to(root).as_posix()
            except ValueError:
                return None
    return None
