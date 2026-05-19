"""AST-walker that flags Mock-of-Port without spec= kwarg.

Two rules (see `docs/superpowers/specs/2026-05-07-tier2-enforcement-batch-design.md` §3):

1. Positional substitution: `AsyncMock(SomePort)` with no `spec=`.
2. Annotated target: `mock: SomePort = AsyncMock()` (no kwargs).

A name resolves to a "Port" when it ends in "Port" (case-sensitive). Imports
are tracked across the file (top-level and `TYPE_CHECKING` blocks). String-form
annotations are treated identically to live ones; if the name is unresolvable
the detector errs toward NOT flagging (false negative > false positive for a
ratchet).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

_MOCK_NAMES = frozenset({"AsyncMock", "MagicMock", "Mock"})


@dataclass(frozen=True)
class Violation:
    path: Path
    lineno: int
    reason: str


def detect_violations(path: Path) -> list[Violation]:
    """Return the list of Mock-spec discipline violations in `path`."""
    try:
        tree = ast.parse(path.read_text(), filename=str(path))
    except SyntaxError:
        return []
    port_names = _collect_port_names(tree)
    findings: list[Violation] = []
    for node in ast.walk(tree):
        finding = _check_node(node, port_names, path)
        if finding is not None:
            findings.append(finding)
    return sorted(findings, key=lambda v: v.lineno)


def _collect_port_names(tree: ast.AST) -> set[str]:
    """Names imported into the file that end in 'Port'."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom | ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name
                if local.endswith("Port"):
                    names.add(local)
    return names


def _check_node(node: ast.AST, port_names: set[str], path: Path) -> Violation | None:
    if isinstance(node, ast.Call):
        return _check_call(node, port_names, path)
    if isinstance(node, ast.AnnAssign):
        return _check_annotated_assign(node, port_names, path)
    return None


def _check_call(call: ast.Call, port_names: set[str], path: Path) -> Violation | None:
    """Rule 1: AsyncMock(SomePort) positional, no spec= kwarg."""
    func_name = _func_simple_name(call.func)
    if func_name not in _MOCK_NAMES:
        return None
    if any(kw.arg == "spec" for kw in call.keywords):
        return None
    if len(call.args) != 1:
        return None
    arg = call.args[0]
    if not isinstance(arg, ast.Name):
        return None
    if arg.id not in port_names:
        return None
    return Violation(
        path=path,
        lineno=call.lineno,
        reason=f"{func_name}({arg.id}) — pass spec={arg.id} instead",
    )


def _check_annotated_assign(
    node: ast.AnnAssign, port_names: set[str], path: Path
) -> Violation | None:
    """Rule 2: `mock: SomePort = AsyncMock()` with no kwargs."""
    ann_name = _annotation_name(node.annotation)
    if ann_name is None or ann_name not in port_names:
        return None
    if not isinstance(node.value, ast.Call):
        return None
    call = node.value
    func_name = _func_simple_name(call.func)
    if func_name not in _MOCK_NAMES:
        return None
    if any(kw.arg == "spec" for kw in call.keywords):
        return None
    if call.args:
        return None  # positional args trigger Rule 1 if any
    return Violation(
        path=path,
        lineno=call.lineno,
        reason=f"bare {func_name}() assigned to {ann_name}-typed target — pass spec={ann_name}",
    )


def _func_simple_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _annotation_name(ann: ast.expr) -> str | None:
    """Resolve a type annotation to a simple name (handles strings / Subscripts)."""
    if isinstance(ann, ast.Name):
        return ann.id
    if isinstance(ann, ast.Constant) and isinstance(ann.value, str):
        return ann.value.split("[", 1)[0].strip()
    if isinstance(ann, ast.Subscript):
        return _annotation_name(ann.value)
    if isinstance(ann, ast.Attribute):
        return ann.attr
    return None
