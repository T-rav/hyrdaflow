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


def _module_int_constants(tree: ast.Module) -> dict[str, int]:
    """Return module-level ``NAME = <int>`` assignments as a name→value dict.

    Used to resolve module-level constants referenced inside
    ``_get_default_interval``, e.g.::

        _DEFAULT_INTERVAL_SECONDS = 600  # module level
        def _get_default_interval(self) -> int:
            return _DEFAULT_INTERVAL_SECONDS
    """
    result: dict[str, int] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not (isinstance(node.value, ast.Constant) and isinstance(node.value.value, int)):
            continue
        for tgt in node.targets:
            if isinstance(tgt, ast.Name):
                result[tgt.id] = node.value.value
    return result


def _load_config_defaults(src_dir: Path) -> dict[str, int]:
    """Parse ``src/config.py`` and return a map of field_name → default int value.

    The map is used to resolve ``return self._config.<field>`` in
    ``_get_default_interval`` methods.  Only ``Field(default=<int>)`` entries
    are captured; computed defaults or non-integer defaults are ignored.
    """
    config_path = src_dir / "config.py"
    if not config_path.exists():
        return {}
    try:
        tree = ast.parse(config_path.read_text(), filename=str(config_path))
    except SyntaxError:
        return {}

    result: dict[str, int] = {}
    for node in ast.walk(tree):
        # AnnAssign: field_name: int = Field(default=<int>, ...)
        if not isinstance(node, ast.AnnAssign):
            continue
        if not isinstance(node.target, ast.Name):
            continue
        if not isinstance(node.value, ast.Call):
            continue
        for kw in node.value.keywords:
            if kw.arg == "default" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, int):
                result[node.target.id] = kw.value.value
                break
    return result


def _tick_interval(
    cls: ast.ClassDef,
    module_constants: dict[str, int],
    config_defaults: dict[str, int],
) -> int | None:
    """Resolve the default tick interval for a loop class.

    Resolution order (first match wins):

    1. Class-body attribute assignment ``tick_interval_seconds = <int>``
       (legacy/test fixture convention).
    2. ``_get_default_interval`` method that returns an int literal.
    3. ``_get_default_interval`` method that returns a module-level constant
       (e.g. ``return _DEFAULT_INTERVAL_SECONDS``).
    4. ``_get_default_interval`` method that returns ``self._config.<field>``
       where ``<field>`` has a known default in ``config_defaults``.
    """
    # (1) Legacy class attribute used in tests / older loops
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

    # (2–4) Look inside _get_default_interval
    for node in cls.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name != "_get_default_interval":
            continue
        for stmt in node.body:
            if not isinstance(stmt, ast.Return) or stmt.value is None:
                continue
            val = stmt.value
            # (2) Direct literal: return 14400
            if isinstance(val, ast.Constant) and isinstance(val.value, int):
                return val.value
            # (3) Module-level Name: return _DEFAULT_INTERVAL_SECONDS
            if isinstance(val, ast.Name) and val.id in module_constants:
                return module_constants[val.id]
            # (4) Config attribute: return self._config.field_name
            if (
                isinstance(val, ast.Attribute)
                and isinstance(val.value, ast.Attribute)
                and isinstance(val.value.value, ast.Name)
                and val.value.value.id == "self"
                and val.value.attr == "_config"
                and val.attr in config_defaults
            ):
                return config_defaults[val.attr]

    return None


def _kill_switch(cls: ast.ClassDef, module_src: str) -> str | None:
    """Find the HYDRAFLOW_DISABLE_… env-var name for this loop.

    The env-var string can appear in two places:

    * Inline in the class body (e.g. ``os.environ.get("HYDRAFLOW_DISABLE_FOO")``).
    * A module-level constant ``_KILL_SWITCH_ENV = "HYDRAFLOW_DISABLE_FOO"``
      that the class body references by name.

    Searching only the class body (``ast.unparse(cls)``) misses the second
    case.  We search the full module source text instead, which covers both.
    """
    m = _KILL_RE.search(module_src)
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
    config_defaults = _load_config_defaults(src_dir)
    out: list[LoopInfo] = []
    for py in sorted(src_dir.rglob("*.py")):
        if py.name.startswith("_"):
            continue
        try:
            source = py.read_text()
            tree = ast.parse(source, filename=str(py))
        except SyntaxError:
            continue
        module_constants = _module_int_constants(tree)
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
                    tick_interval_seconds=_tick_interval(node, module_constants, config_defaults),
                    event_subscriptions=_event_subs(node),
                    kill_switch_var=_kill_switch(node, source),
                    adr_refs=_adr_refs(node, tree),
                )
            )
    out.sort(key=lambda loop: loop.name)
    return out
