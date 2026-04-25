"""P2 — DDD, Ports & Adapters, Clean Architecture (ADR-0044)."""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

from ..models import CheckContext, Finding, Status
from ..registry import register
from ._helpers import exists, finding


@register("P2.1")
def _src_dir_exists(ctx: CheckContext) -> Finding:
    return exists(ctx.root, "src", "P2.1")


@register("P2.2")
def _ports_module_has_protocol(ctx: CheckContext) -> Finding:
    ports = ctx.root / "src" / "ports.py"
    if not ports.exists():
        return finding("P2.2", Status.FAIL, "src/ports.py missing")
    protocols = _count_protocol_classes(ports)
    if protocols >= 1:
        return finding("P2.2", Status.PASS, f"{protocols} Protocol(s) defined")
    return finding("P2.2", Status.FAIL, "src/ports.py defines no Protocol classes")


@register("P2.2a")
def _ports_cover_boundaries(ctx: CheckContext) -> Finding:
    """At least two Protocols = at least two boundaries modelled as ports.

    Only one Protocol is the strongest early signal that `AsyncMock` is
    being used instead of ports for other boundaries. A hard FAIL would be
    too aggressive for greenfield repos; emit a WARN so the gap is visible.
    """
    ports = ctx.root / "src" / "ports.py"
    if not ports.exists():
        return finding("P2.2a", Status.FAIL, "src/ports.py missing")
    protocols = _count_protocol_classes(ports)
    if protocols >= 2:
        return finding("P2.2a", Status.PASS, f"{protocols} Protocols cover boundaries")
    return finding(
        "P2.2a",
        Status.WARN,
        f"only {protocols} Protocol in ports.py — likely boundaries are AsyncMock-faked",
    )


@register("P2.3")
def _layer_check_script_exists(ctx: CheckContext) -> Finding:
    script = ctx.root / "scripts" / "check_layer_imports.py"
    if script.exists():
        return finding("P2.3", Status.PASS)
    return finding(
        "P2.3",
        Status.NA,
        "scripts/check_layer_imports.py not yet ported — layer-check pending",
    )


@register("P2.4")
def _layer_check_exits_zero(ctx: CheckContext) -> Finding:
    script = ctx.root / "scripts" / "check_layer_imports.py"
    if not script.exists():
        return finding("P2.4", Status.NA, "layer-check script not yet ported")
    try:
        result = subprocess.run(
            [sys.executable, str(script)],
            check=False,
            cwd=ctx.root,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return finding("P2.4", Status.FAIL, f"layer-check did not complete: {exc}")
    if result.returncode == 0:
        return finding("P2.4", Status.PASS)
    tail = (result.stdout + result.stderr).strip().splitlines()
    sample = "; ".join(tail[-3:]) if tail else "no output"
    return finding(
        "P2.4", Status.FAIL, f"layer-check failed (exit {result.returncode}): {sample}"
    )


@register("P2.5")
def _composition_root_exists(ctx: CheckContext) -> Finding:
    candidates = [
        ctx.root / "src" / "service_registry.py",
        ctx.root / "src" / "composition_root.py",
        ctx.root / "src" / "container.py",
    ]
    for path in candidates:
        if path.exists():
            return finding("P2.5", Status.PASS, f"composition root: {path.name}")
    return finding(
        "P2.5",
        Status.FAIL,
        "no composition root found (tried service_registry.py, composition_root.py, container.py)",
    )


_ALLOWLIST_RE = re.compile(r"\bALLOWLIST\b")


@register("P2.6")
def _layer_check_has_allowlist(ctx: CheckContext) -> Finding:
    script = ctx.root / "scripts" / "check_layer_imports.py"
    if not script.exists():
        return finding("P2.6", Status.NA, "layer-check script not yet ported")
    text = script.read_text(encoding="utf-8", errors="replace")
    if _ALLOWLIST_RE.search(text):
        return finding("P2.6", Status.PASS, "ALLOWLIST declared in layer-check")
    return finding(
        "P2.6",
        Status.WARN,
        "no ALLOWLIST in layer-check — composition-root exceptions are implicit",
    )


@register("P2.7")
def _domain_layer_purity(ctx: CheckContext) -> Finding:
    """Piggyback on the layer-check — if it's green, domain purity holds.

    A separate domain-only variant would re-implement the same traversal;
    this check succeeds when layer-check does, with a tighter failure
    message pointing at the principle.
    """
    script = ctx.root / "scripts" / "check_layer_imports.py"
    if not script.exists():
        return finding(
            "P2.7",
            Status.NA,
            "layer-check script not yet ported — domain purity unverified",
        )
    try:
        result = subprocess.run(
            [sys.executable, str(script)],
            check=False,
            cwd=ctx.root,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return finding("P2.7", Status.FAIL, f"layer-check did not complete: {exc}")
    if result.returncode == 0:
        return finding("P2.7", Status.PASS)
    return finding(
        "P2.7",
        Status.FAIL,
        "layer-check red → domain may be importing infrastructure",
    )


@register("P2.8")
def _domain_types_carry_behaviour(ctx: CheckContext) -> Finding:
    """Warn when domain classes that are NOT DTOs have no behaviour.

    ADR-0044 P2: "anaemic Pydantic models that only hold fields belong in
    DTOs, not the domain." So we explicitly exclude Pydantic BaseModel
    subclasses, TypedDicts, and `@dataclass(frozen=True)` value objects
    from the anaemic check — they are deliberately data-only. What we care
    about is domain entities that ought to model behaviour but don't.
    """
    candidates = _domain_files(ctx.root)
    if not candidates:
        return finding(
            "P2.8", Status.NA, "no src/models.py or src/domain/ — nothing to sample"
        )
    anaemic = 0
    entity_total = 0
    for path in candidates:
        for cls in _public_classes(path):
            if _looks_like_dto(cls):
                continue
            entity_total += 1
            if not _has_real_method(cls):
                anaemic += 1
    if entity_total == 0:
        return finding(
            "P2.8",
            Status.NA,
            "all sampled domain classes are DTOs (Pydantic / TypedDict / frozen dataclass) — nothing to evaluate",
        )
    ratio = anaemic / entity_total
    if ratio < 0.6:
        return finding(
            "P2.8",
            Status.PASS,
            f"{anaemic}/{entity_total} non-DTO domain classes anaemic ({ratio:.0%})",
        )
    return finding(
        "P2.8",
        Status.WARN,
        f"{anaemic}/{entity_total} non-DTO domain classes have no behaviour — logic may be leaking to application/infra",
    )


_DTO_BASE_NAMES = {
    "BaseModel",
    "TypedDict",
    "NamedTuple",
    "Protocol",
    "Enum",
    "IntEnum",
    "StrEnum",
    "Flag",
}


def _looks_like_dto(cls: ast.ClassDef) -> bool:
    """Classes that are *designed* to be data holders are exempt from P2.8.

    Matches:
      - Pydantic `BaseModel` (direct or via `pydantic.BaseModel`)
      - `TypedDict`, `NamedTuple`, `Protocol`, `Enum`, `IntEnum`, `StrEnum`, `Flag`
      - Any `@dataclass`-decorated class (frozen or not — plain dataclasses
        are idiomatic parameter-grouping DTOs in Python)
    """
    for base in cls.bases:
        name = ""
        if isinstance(base, ast.Name):
            name = base.id
        elif isinstance(base, ast.Attribute):
            name = base.attr
        if name in _DTO_BASE_NAMES or name.endswith("BaseModel"):
            return True
    return any(_is_dataclass(decorator) for decorator in cls.decorator_list)


def _is_dataclass(decorator: ast.expr) -> bool:
    """True for `@dataclass`, `@dataclass(...)`, or `dataclasses.dataclass` forms."""
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    if isinstance(target, ast.Name):
        return target.id == "dataclass"
    if isinstance(target, ast.Attribute):
        return target.attr == "dataclass"
    return False


@register("P2.9")
def _ubiquitous_language(ctx: CheckContext) -> Finding:
    """Warn when CLAUDE.md ubiquitous-language terms don't appear in the wiki.

    CLAUDE.md is a lean ToC; it lists a short ubiquitous-language vocabulary
    operators must use without paraphrasing. Those names must appear in the
    wiki's architecture topic so an agent looking up any of them lands on
    real context. The reverse direction (every wiki term must appear in
    CLAUDE.md) was load-bearing under the old layout where CLAUDE.md
    duplicated architecture content; the new layout intentionally moves
    architecture into the wiki, so the check now flows ToC → wiki.
    """
    arch = ctx.root / "docs" / "wiki" / "architecture.md"
    claude = ctx.root / "CLAUDE.md"
    if not arch.exists() or not claude.exists():
        return finding(
            "P2.9",
            Status.NA,
            "architecture.md or CLAUDE.md missing — upstream P1 checks cover this",
        )
    claude_terms = _capitalised_terms(
        claude.read_text(encoding="utf-8", errors="replace")
    )
    arch_text = arch.read_text(encoding="utf-8", errors="replace")
    if len(claude_terms) < 3:
        return finding(
            "P2.9",
            Status.NA,
            f"only {len(claude_terms)} candidate terms in CLAUDE.md — sample too small",
        )
    missing = [t for t in claude_terms if t not in arch_text]
    ratio_missing = len(missing) / len(claude_terms)
    if ratio_missing < 0.5:
        return finding(
            "P2.9",
            Status.PASS,
            f"{len(claude_terms) - len(missing)}/{len(claude_terms)} ToC terms covered by wiki",
        )
    sample = ", ".join(missing[:5])
    return finding(
        "P2.9",
        Status.WARN,
        f"{len(missing)}/{len(claude_terms)} CLAUDE.md terms absent from wiki ({sample})",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _count_protocol_classes(path: Path) -> int:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return 0
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and _inherits_protocol(node):
            count += 1
    return count


def _inherits_protocol(node: ast.ClassDef) -> bool:
    for base in node.bases:
        if isinstance(base, ast.Name) and base.id == "Protocol":
            return True
        if isinstance(base, ast.Attribute) and base.attr == "Protocol":
            return True
    return False


def _domain_files(root: Path) -> list[Path]:
    candidates: list[Path] = []
    models = root / "src" / "models.py"
    if models.exists():
        candidates.append(models)
    domain_dir = root / "src" / "domain"
    if domain_dir.is_dir():
        candidates.extend(sorted(domain_dir.glob("*.py")))
    return candidates


def _public_classes(path: Path) -> list[ast.ClassDef]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return []
    return [
        node
        for node in ast.iter_child_nodes(tree)
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_")
    ]


def _has_real_method(cls: ast.ClassDef) -> bool:
    for node in cls.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and not (
            node.name.startswith("__") and node.name.endswith("__")
        ):
            return True
    return False


_CAMEL_CASE = re.compile(r"\b([A-Z][a-z]+[A-Z][A-Za-z]+)\b")


def _capitalised_terms(text: str) -> list[str]:
    seen: set[str] = set()
    terms: list[str] = []
    for match in _CAMEL_CASE.finditer(text):
        term = match.group(1)
        if term not in seen:
            seen.add(term)
            terms.append(term)
    return terms
