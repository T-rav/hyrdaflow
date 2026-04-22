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
    return exists(ctx.root, "scripts/check_layer_imports.py", "P2.3")


@register("P2.4")
def _layer_check_exits_zero(ctx: CheckContext) -> Finding:
    script = ctx.root / "scripts" / "check_layer_imports.py"
    if not script.exists():
        return finding("P2.4", Status.FAIL, "scripts/check_layer_imports.py missing")
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
        return finding("P2.6", Status.FAIL, "scripts/check_layer_imports.py missing")
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
            "P2.7", Status.FAIL, "layer-check script missing — domain purity unverified"
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
    """Warn when domain model files contain only anaemic classes.

    Heuristic: for each candidate file (src/models.py, src/domain/*.py),
    count public classes and how many have at least one method beyond
    dunder methods. If ≥60% of classes are anaemic across the sample, warn.
    """
    candidates = _domain_files(ctx.root)
    if not candidates:
        return finding(
            "P2.8", Status.NA, "no src/models.py or src/domain/ — nothing to sample"
        )
    anaemic = 0
    total = 0
    for path in candidates:
        for cls in _public_classes(path):
            total += 1
            if not _has_real_method(cls):
                anaemic += 1
    if total == 0:
        return finding("P2.8", Status.NA, "no public classes in domain candidates")
    ratio = anaemic / total
    if ratio < 0.6:
        return finding(
            "P2.8",
            Status.PASS,
            f"{anaemic}/{total} domain classes anaemic ({ratio:.0%})",
        )
    return finding(
        "P2.8",
        Status.WARN,
        f"{anaemic}/{total} domain classes have no behaviour — logic may be leaking to application/infra",
    )


@register("P2.9")
def _ubiquitous_language(ctx: CheckContext) -> Finding:
    """Warn when architecture.md terms don't appear in CLAUDE.md."""
    arch = ctx.root / "docs" / "agents" / "architecture.md"
    claude = ctx.root / "CLAUDE.md"
    if not arch.exists() or not claude.exists():
        return finding(
            "P2.9",
            Status.NA,
            "architecture.md or CLAUDE.md missing — upstream P1 checks cover this",
        )
    arch_terms = _capitalised_terms(arch.read_text(encoding="utf-8", errors="replace"))
    claude_text = claude.read_text(encoding="utf-8", errors="replace")
    missing = [t for t in arch_terms if t not in claude_text]
    if len(arch_terms) < 3:
        return finding(
            "P2.9",
            Status.NA,
            f"only {len(arch_terms)} candidate terms in architecture.md — sample too small",
        )
    ratio_missing = len(missing) / len(arch_terms)
    if ratio_missing < 0.5:
        return finding(
            "P2.9",
            Status.PASS,
            f"{len(arch_terms) - len(missing)}/{len(arch_terms)} terms shared",
        )
    sample = ", ".join(missing[:5])
    return finding(
        "P2.9",
        Status.WARN,
        f"{len(missing)}/{len(arch_terms)} architecture.md terms absent from CLAUDE.md ({sample})",
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
