"""Extract LoopInfo records from src/*.py via AST static analysis.

Why AST and not class introspection: each loop module has deferred imports
with side effects (config wiring, network probes). Importing every module
to enumerate `BaseBackgroundLoop.__subclasses__()` would fire those side
effects and is not viable in a documentation pipeline. AST parses the
source text only; nothing executes.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from arch._models import LoopInfo

_ADR_RE = re.compile(r"ADR-(\d{4})")
_KILL_RE = re.compile(r"HYDRAFLOW_DISABLE_[A-Z0-9_]+")


def _module_for(path: Path, src_root: Path) -> str:
    rel = path.relative_to(src_root.parent)  # repo-root-relative
    return ".".join(rel.with_suffix("").parts)


def _is_basebackgroundloop_subclass(cls: ast.ClassDef) -> bool:
    for base in cls.bases:
        if isinstance(base, ast.Name) and base.id == "BaseBackgroundLoop":
            return True
        if isinstance(base, ast.Attribute) and base.attr == "BaseBackgroundLoop":
            return True
    return False


def _tick_interval(cls: ast.ClassDef) -> int | None:
    for node in cls.body:
        if not isinstance(node, ast.Assign):
            continue
        for tgt in node.targets:
            if (
                isinstance(tgt, ast.Name)
                and tgt.id == "tick_interval_seconds"
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, int)
            ):
                return node.value.value
    return None


def _kill_switch(cls: ast.ClassDef) -> str | None:
    src = ast.unparse(cls)
    m = _KILL_RE.search(src)
    return m.group(0) if m else None


def _adr_refs(cls: ast.ClassDef, module: ast.Module) -> list[str]:
    """ADR refs from the class docstring or — when the class has none — the
    module docstring. Loops conventionally cite their governing ADRs at the
    top of the file rather than on the class itself.
    """
    doc = ast.get_docstring(cls) or ast.get_docstring(module) or ""
    return sorted({f"ADR-{m}" for m in _ADR_RE.findall(doc)})


def _event_subs(cls: ast.ClassDef) -> list[str]:
    """Best-effort: pull EventType.X references from the class body."""
    src = ast.unparse(cls)
    return sorted(set(re.findall(r"EventType\.([A-Z_]+)", src)))


def extract_loops(src_dir: Path) -> list[LoopInfo]:
    """Walk *.py under src_dir and return one LoopInfo per BaseBackgroundLoop subclass.

    Result is sorted by class name for deterministic output. The
    `BaseBackgroundLoop` base class itself is skipped.
    """
    src_dir = Path(src_dir).resolve()
    out: list[LoopInfo] = []
    for py in sorted(src_dir.rglob("*.py")):
        if py.name.startswith("_"):
            continue
        try:
            tree = ast.parse(py.read_text(), filename=str(py))
        except SyntaxError:
            continue
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            if node.name == "BaseBackgroundLoop":
                continue
            if not _is_basebackgroundloop_subclass(node):
                continue
            out.append(
                LoopInfo(
                    name=node.name,
                    module=_module_for(py, src_dir),
                    source_path=str(py.relative_to(src_dir.parent)),
                    tick_interval_seconds=_tick_interval(node),
                    event_subscriptions=_event_subs(node),
                    kill_switch_var=_kill_switch(node),
                    adr_refs=_adr_refs(node, tree),
                )
            )
    out.sort(key=lambda loop: loop.name)
    return out
