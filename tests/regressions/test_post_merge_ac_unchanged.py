"""Regression: post-merge AC + verification_judge stay isolated from the adversarial branch.

Spec contract for the earlier-adversarial pipeline: the new pre-impl
SpecACGenerator + SpecJudge are *siblings* of the existing post-merge
``acceptance_criteria`` + ``verification_judge`` pipeline, not a
replacement. This regression locks that contract:

  * Post-merge modules must not depend on the new adversarial agents.
  * Their public surface (the classes/functions the rest of the
    codebase imports) must stay intact.

A future refactor that conflates pre-impl Judge work with post-merge
verification will trip these checks.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

_ADVERSARIAL_MODULES = {
    "src.spec_ac_generator",
    "src.spec_judge",
    "src.plan_council",
    "src.discovery_council",
    "src.shape_council",
    "src.assumption_surfacer",
    "src.adversarial_retry_loop",
    "src.complexity_gate",
}


def _module_imports(path: Path) -> set[str]:
    """Return all ``import X`` / ``from X import Y`` module targets in *path*."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                targets.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            targets.add(node.module)
    return targets


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def test_acceptance_criteria_does_not_import_adversarial() -> None:
    path = _repo_root() / "src" / "acceptance_criteria.py"
    imports = _module_imports(path)
    leaked = imports & _ADVERSARIAL_MODULES
    assert not leaked, (
        f"src/acceptance_criteria.py leaked adversarial-pipeline imports: "
        f"{sorted(leaked)}. Post-merge AC must stay independent of the "
        f"pre-impl SpecJudge pipeline (spec contract)."
    )


def test_verification_judge_does_not_import_adversarial() -> None:
    path = _repo_root() / "src" / "verification_judge.py"
    imports = _module_imports(path)
    leaked = imports & _ADVERSARIAL_MODULES
    assert not leaked, (
        f"src/verification_judge.py leaked adversarial-pipeline imports: "
        f"{sorted(leaked)}. Post-merge verification must stay independent "
        f"of the pre-impl SpecJudge pipeline (spec contract)."
    )


def test_acceptance_criteria_public_surface_intact() -> None:
    """Imports of the legacy public surface still resolve from the module."""
    import acceptance_criteria  # noqa: PLC0415

    # The post-merge AC pipeline's public entry point. Tracked here so
    # that an unintended rename (e.g. conflating with SpecACGenerator)
    # trips this regression before the rest of the codebase blows up.
    assert hasattr(acceptance_criteria, "AcceptanceCriteriaGenerator")


def test_verification_judge_public_surface_intact() -> None:
    import verification_judge  # noqa: PLC0415

    assert hasattr(verification_judge, "VerificationJudge")
