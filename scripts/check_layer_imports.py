#!/usr/bin/env python3
"""Static import-direction checker for HydraFlow's layered architecture.

Validates that imports flow inward only: a module at layer N may import from
layers 1..N but NEVER from layer N+1 or above. Cross-cutting modules may
import from Layer 1 only. service_registry.py is the sole exception.

Exit codes:
  0 — no violations found
  1 — one or more violations found
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import NamedTuple

# ---------------------------------------------------------------------------
# Layer assignments
# ---------------------------------------------------------------------------

# Explicit file-to-layer mappings (basename without .py)
LAYER_MAP: dict[str, int] = {
    # Layer 1 — Domain
    "models": 1,
    "config": 1,
    "config_io": 1,
    # Layer 2 — Application (phase coordination, workflow orchestration)
    "orchestrator": 2,
    "plan_phase": 2,
    "implement_phase": 2,
    "review_phase": 2,
    "triage_phase": 2,
    "hitl_phase": 2,
    "discover_phase": 2,
    "shape_phase": 2,
    "phase_utils": 2,
    "pr_unsticker": 2,
    "base_background_loop": 2,
    "bg_worker_manager": 2,
    # Layer 3 — Runners (subprocess orchestration, agent invocation)
    "base_runner": 3,
    "agent": 3,
    "planner": 3,
    "reviewer": 3,
    "hitl_runner": 3,
    "triage_runner": 3,
    "triage": 3,
    "runner_utils": 3,
    "runner_constants": 3,
    "diagnostic_runner": 3,
    "discover_runner": 3,
    "research_runner": 3,
    "shape_runner": 3,
    "docker_runner": 3,
    # Layer 4 — Infrastructure/Adapters (I/O, external systems)
    "pr_manager": 4,
    "worktree": 4,
    "workspace": 4,
    "merge_conflict_resolver": 4,
    "post_merge_handler": 4,
    "dashboard": 4,
    "dashboard_routes": 4,
    "server": 4,
    "prep": 4,
    "ci_scaffold": 4,
    "lint_scaffold": 4,
    "test_scaffold": 4,
    "makefile_scaffold": 4,
    "polyglot_prep": 4,
    "prep_hooks": 4,
    "prep_ignore": 4,
}

# Cross-cutting modules (available to all, imports only from Layer 1)
CROSS_CUTTING: set[str] = {
    "events",
    "state",
    "service_registry",
    "ports",
}

# Modules exempt from all checks (composition roots that wire everything)
ALLOWLIST: set[str] = {
    "service_registry",
}

# Per-file import allowlist: {source_module: {allowed_target_module, ...}}
# These are known architectural exceptions documented for tracking.
# L2 phases currently import L3 runners directly (e.g. plan_phase → planner)
# and some also reach L4 infrastructure (e.g. discover_phase → pr_manager).
# Port-based decoupling for L2→L3 violations is tracked in issue #6049;
# L2→L4 violations (discover_phase, shape_phase, review_phase) need their
# own tracking issues.
FILE_ALLOWLIST: dict[str, set[str]] = {
    "implement_phase": {"agent"},
    "plan_phase": {"planner", "research_runner"},
    "review_phase": {"reviewer", "merge_conflict_resolver", "post_merge_handler"},
    "hitl_phase": {"hitl_runner"},
    "triage_phase": {"triage"},
    "discover_phase": {"discover_runner", "pr_manager"},
    "shape_phase": {"shape_runner", "pr_manager"},
    "base_background_loop": {"runner_utils"},
    "code_grooming_loop": {"runner_utils"},
    "report_issue_loop": {"runner_utils"},
}

# Pattern-based layer inference (checked in order; first match wins)
LAYER_PATTERNS: list[tuple[str, int]] = [
    ("_loop", 2),  # *_loop.py → Layer 2 (background loops)
    ("_phase", 2),  # *_phase.py → Layer 2
    ("_runner", 3),  # *_runner.py → Layer 3
    ("_scaffold", 4),  # *_scaffold.py → Layer 4
]

# Directory-based layer inference
DIR_LAYER_MAP: dict[str, int | str] = {
    "state": "cross-cutting",
    "dashboard_routes": 4,
}

LAYER_NAMES: dict[int | str, str] = {
    1: "L1-Domain",
    2: "L2-Application",
    3: "L3-Runners",
    4: "L4-Infrastructure",
    "cross-cutting": "Cross-cutting",
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


class Violation(NamedTuple):
    file: str
    line: int
    import_name: str
    source_layer: int | str
    target_layer: int | str
    kind: str  # "upward" or "cross-cutting-pollution"


# ---------------------------------------------------------------------------
# Layer resolution
# ---------------------------------------------------------------------------


def resolve_layer(module_name: str) -> int | str | None:
    """Return the layer number for a module, or None if unknown."""
    # Check explicit map first
    if module_name in LAYER_MAP:
        return LAYER_MAP[module_name]

    # Check cross-cutting
    if module_name in CROSS_CUTTING:
        return "cross-cutting"

    # Check directory-based mapping
    if module_name in DIR_LAYER_MAP:
        return DIR_LAYER_MAP[module_name]

    # Pattern-based inference
    for suffix, layer in LAYER_PATTERNS:
        if module_name.endswith(suffix):
            return layer

    return None


# ---------------------------------------------------------------------------
# Import extraction
# ---------------------------------------------------------------------------


class ImportInfo(NamedTuple):
    module: str
    line: int
    raw: str


def extract_imports(source: str) -> list[ImportInfo]:
    """Extract intra-project top-level imports from Python source.

    Only module-level (top-level) import statements are checked. Imports inside
    ``if TYPE_CHECKING:`` blocks are naturally excluded because
    ``ast.iter_child_nodes(Module)`` yields only direct Module children — the
    ``If`` node itself, not its body. Imports inside functions or methods are
    also excluded; deferred imports used intentionally to break circular
    dependencies are therefore not flagged.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    imports: list[ImportInfo] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            top_module = node.module.split(".")[0]
            names = ", ".join(a.name for a in node.names)
            raw = f"from {node.module} import {names}"
            imports.append(ImportInfo(module=top_module, line=node.lineno, raw=raw))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                top_module = alias.name.split(".")[0]
                imports.append(
                    ImportInfo(
                        module=top_module,
                        line=node.lineno,
                        raw=f"import {alias.name}",
                    )
                )
    return imports


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def check_violations(
    source_file: str,
    source_layer: int | str,
    imports: list[ImportInfo],
    allowed_targets: set[str] | None = None,
) -> list[Violation]:
    """Check a single module's imports for layer violations."""
    violations: list[Violation] = []
    allowed = allowed_targets or set()

    for imp in imports:
        # Skip allowlisted target modules
        if imp.module in allowed:
            continue

        target_layer = resolve_layer(imp.module)
        if target_layer is None:
            continue  # unknown module — skip

        # Cross-cutting modules may only import from Layer 1 or other cross-cutting
        if source_layer == "cross-cutting":
            if target_layer not in {1, "cross-cutting"}:
                violations.append(
                    Violation(
                        file=source_file,
                        line=imp.line,
                        import_name=imp.raw,
                        source_layer=source_layer,
                        target_layer=target_layer,
                        kind="cross-cutting-pollution",
                    )
                )
            continue

        # Skip if target is cross-cutting (always allowed)
        if target_layer == "cross-cutting":
            continue

        # Upward violation: source layer < target layer
        if (
            isinstance(source_layer, int)
            and isinstance(target_layer, int)
            and target_layer > source_layer
        ):
            violations.append(
                Violation(
                    file=source_file,
                    line=imp.line,
                    import_name=imp.raw,
                    source_layer=source_layer,
                    target_layer=target_layer,
                    kind="upward",
                )
            )

    return violations


# ---------------------------------------------------------------------------
# File discovery and main
# ---------------------------------------------------------------------------


def discover_source_files(src_dir: Path) -> list[Path]:
    """Find all Python source files in src/, excluding tests and venv."""
    excludes = {"__pycache__", ".venv", "venv", "node_modules", "ui", "assets"}
    results: list[Path] = []
    for path in sorted(src_dir.rglob("*.py")):
        parts = set(path.relative_to(src_dir).parts)
        if parts & excludes:
            continue
        results.append(path)
    return results


def module_name_from_path(path: Path, src_dir: Path) -> str:
    """Derive module name from file path relative to src_dir."""
    rel = path.relative_to(src_dir)
    parts = list(rel.parts)
    # __init__.py → use the directory name
    if parts[-1] == "__init__.py":
        return parts[-2] if len(parts) >= 2 else ""
    # Strip .py extension
    parts[-1] = parts[-1].removesuffix(".py")
    # For files inside a sub-package, use the top-level directory name
    if len(parts) > 1:
        return parts[0]
    return parts[0]


def run_check(src_dir: Path) -> list[Violation]:
    """Run the full layer import check on a source directory."""
    all_violations: list[Violation] = []

    for path in discover_source_files(src_dir):
        mod_name = module_name_from_path(path, src_dir)
        if not mod_name:
            continue

        # Skip allowlisted modules
        if mod_name in ALLOWLIST:
            continue

        source_layer = resolve_layer(mod_name)
        if source_layer is None:
            continue  # unclassified — skip

        source = path.read_text(encoding="utf-8", errors="replace")
        imports = extract_imports(source)
        rel_path = str(path.relative_to(src_dir))
        allowed = FILE_ALLOWLIST.get(mod_name, set())
        violations = check_violations(rel_path, source_layer, imports, allowed)
        all_violations.extend(violations)

    return all_violations


def format_violations(violations: list[Violation]) -> str:
    """Format violations for human-readable output."""
    lines: list[str] = []
    for v in violations:
        src_label = LAYER_NAMES.get(v.source_layer, str(v.source_layer))
        tgt_label = LAYER_NAMES.get(v.target_layer, str(v.target_layer))
        if v.kind == "upward":
            desc = f"imports upward: {src_label} -> {tgt_label}"
        else:
            desc = f"cross-cutting imports from {tgt_label} (only L1-Domain allowed)"
        lines.append(f"  {v.file}:{v.line}: {v.import_name}")
        lines.append(f"    {desc}")
    return "\n".join(lines)


def main(src_dir: Path | None = None) -> int:
    """Entry point. Returns 0 on success, 1 on violations."""
    if src_dir is None:
        # Default: resolve relative to this script's location
        src_dir = Path(__file__).resolve().parent.parent / "src"

    if not src_dir.is_dir():
        print(f"Error: source directory not found: {src_dir}", file=sys.stderr)
        return 1

    violations = run_check(src_dir)

    if violations:
        print(f"Layer import violations ({len(violations)}):\n")
        print(format_violations(violations))
        print(f"\n{len(violations)} violation(s) found.")
        return 1

    print("No layer import violations found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
