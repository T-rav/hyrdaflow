"""P9 — Persistence and data layout (ADR-0044 / ADR-0021)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from ..models import CheckContext, Finding, Status
from ..registry import register
from ._helpers import finding

_DATA_ROOT_FIELD_RE = re.compile(
    r"\bdata_root\s*:\s*(?:Path|str)\s*=\s*Field",
    re.MULTILINE,
)


@register("P9.1")
def _data_root_field(ctx: CheckContext) -> Finding:
    config = ctx.root / "src" / "config.py"
    if not config.exists():
        return finding("P9.1", Status.FAIL, "src/config.py missing")
    text = config.read_text(encoding="utf-8", errors="replace")
    if _DATA_ROOT_FIELD_RE.search(text):
        return finding("P9.1", Status.PASS)
    return finding(
        "P9.1",
        Status.FAIL,
        "src/config.py has no `data_root` field with a default",
    )


_ENV_OVERRIDE_RE = re.compile(r"\b[A-Z]+_DATA_ROOT\b|os\.environ\[.*DATA_ROOT")


@register("P9.2")
def _data_root_env_override(ctx: CheckContext) -> Finding:
    src = ctx.root / "src"
    if not src.is_dir():
        return finding("P9.2", Status.FAIL, "src/ missing")
    for py in src.rglob("*.py"):
        text = py.read_text(encoding="utf-8", errors="replace")
        if _ENV_OVERRIDE_RE.search(text):
            return finding("P9.2", Status.PASS, f"env override in {py.name}")
    return finding(
        "P9.2",
        Status.FAIL,
        "no *_DATA_ROOT env var override found in src/",
    )


_REPO_SLUG_SCOPE_RE = re.compile(
    r"repo_slug|repo-slug|data_root\s*/\s*\w+_slug",
)


@register("P9.3")
def _repo_slug_scoping(ctx: CheckContext) -> Finding:
    src = ctx.root / "src"
    if not src.is_dir():
        return finding("P9.3", Status.FAIL, "src/ missing")
    for py in src.rglob("*.py"):
        text = py.read_text(encoding="utf-8", errors="replace")
        if _REPO_SLUG_SCOPE_RE.search(text):
            return finding("P9.3", Status.PASS)
    return finding(
        "P9.3",
        Status.WARN,
        "no repo_slug-scoped paths found — multi-repo runs may collide",
    )


_CLASS_NAMES: dict[str, tuple[str, ...]] = {
    "P9.4": ("StateTracker", "StateManager", "StateStore"),
    "P9.5": ("DedupStore", "DedupTracker", "IdempotencyStore"),
}


def _find_class(root: Path, names: tuple[str, ...]) -> Path | None:
    src = root / "src"
    if not src.is_dir():
        return None
    pattern = re.compile(r"^class\s+(" + "|".join(names) + r")\b", re.MULTILINE)
    for py in src.rglob("*.py"):
        text = py.read_text(encoding="utf-8", errors="replace")
        if pattern.search(text):
            return py
    return None


@register("P9.4")
def _state_tracker(ctx: CheckContext) -> Finding:
    hit = _find_class(ctx.root, _CLASS_NAMES["P9.4"])
    if hit:
        return finding("P9.4", Status.PASS, f"state abstraction in {hit.name}")
    return finding(
        "P9.4",
        Status.FAIL,
        "no StateTracker/StateManager/StateStore class in src/ — state writes scatter",
    )


@register("P9.5")
def _dedup_store(ctx: CheckContext) -> Finding:
    hit = _find_class(ctx.root, _CLASS_NAMES["P9.5"])
    if hit:
        return finding("P9.5", Status.PASS, f"dedup abstraction in {hit.name}")
    return finding(
        "P9.5",
        Status.FAIL,
        "no DedupStore/IdempotencyStore class in src/ — restart-safe idempotency missing",
    )


_ATOMIC_WRITE_RE = re.compile(
    r"\bos\.replace\b|\batomic_write\b|\bNamedTemporaryFile\b"
)


@register("P9.6")
def _atomic_writes(ctx: CheckContext) -> Finding:
    src = ctx.root / "src"
    if not src.is_dir():
        return finding("P9.6", Status.FAIL, "src/ missing")
    for py in src.rglob("*.py"):
        text = py.read_text(encoding="utf-8", errors="replace")
        if _ATOMIC_WRITE_RE.search(text):
            return finding("P9.6", Status.PASS, f"atomic write in {py.name}")
    return finding(
        "P9.6",
        Status.FAIL,
        "no atomic write pattern (os.replace / atomic_write / NamedTemporaryFile) in src/",
    )


_DATA_ROOT_NAMES = (".hydraflow", ".data", "data", ".state")


@register("P9.7")
def _data_root_in_gitignore(ctx: CheckContext) -> Finding:
    gi = ctx.root / ".gitignore"
    if not gi.exists():
        return finding("P9.7", Status.FAIL, ".gitignore missing")
    text = gi.read_text(encoding="utf-8", errors="replace")
    for name in _DATA_ROOT_NAMES:
        if re.search(rf"^{re.escape(name)}/?\s*$", text, re.MULTILINE):
            return finding("P9.7", Status.PASS, f"`{name}/` in .gitignore")
    return finding(
        "P9.7",
        Status.WARN,
        f"no common data-root directory in .gitignore ({', '.join(_DATA_ROOT_NAMES)})",
    )


@register("P9.8")
def _no_writes_in_src(ctx: CheckContext) -> Finding:
    """Flag only string-literal write paths under src/.

    Variable paths are undecidable statically — they often derive from
    `data_root` or config. A string literal `open("foo.txt", "w")` is the
    unambiguous signal of a write outside the store abstractions.
    """
    src = ctx.root / "src"
    if not src.is_dir():
        return finding("P9.8", Status.NA, "no src/")
    offenders: list[str] = []
    for py in src.rglob("*.py"):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not _is_literal_write_open(node):
                continue
            offenders.append(f"{py.relative_to(ctx.root)}:{node.lineno}")
            if len(offenders) >= 5:
                break
        if len(offenders) >= 5:
            break
    if not offenders:
        return finding("P9.8", Status.PASS)
    return finding(
        "P9.8",
        Status.WARN,
        f"literal-path writes in src/: {'; '.join(offenders)}",
    )


def _is_literal_write_open(node: ast.Call) -> bool:
    """True for `open("literal", "w"|"a")` with a string-literal first arg."""
    func = node.func
    if not (isinstance(func, ast.Name) and func.id == "open"):
        return False
    if not node.args:
        return False
    first = node.args[0]
    if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
        return False
    mode = ""
    if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
        value = node.args[1].value
        if isinstance(value, str):
            mode = value
    for kw in node.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
            value = kw.value.value
            if isinstance(value, str):
                mode = value
    return any(flag in mode for flag in ("w", "a", "x"))
