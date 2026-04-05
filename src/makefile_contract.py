"""Makefile contract validation and repair.

The Makefile is HydraFlow's language-agnostic quality port.  Every target
repo — regardless of language (Python, Node, C#, Java, Go, Rust, …) — must
expose the same canonical ``make`` targets so the pipeline can call them
without knowing the underlying toolchain.

This module provides:

* **REQUIRED_TARGETS** — the canonical contract.
* **validate()** — check whether a Makefile satisfies the contract.
* **validate_and_repair()** — validate, and scaffold missing targets when
  possible (delegates to ``makefile_scaffold.merge_makefile``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("hydraflow.makefile_contract")

# ── Contract definition ──────────────────────────────────────────────
#
# Every target repo must expose these ``make`` targets.  The pipeline
# calls them by name — the Makefile recipes are language-specific
# adapters behind a universal interface.
#
# Blocking targets fail the pipeline if they return non-zero.
# Advisory targets log warnings but do not block.

REQUIRED_TARGETS: tuple[str, ...] = (
    "lint",
    "lint-check",
    "test",
    "typecheck",
    "security",
    "quality-lite",
    "quality",
)

OPTIONAL_TARGETS: tuple[str, ...] = (
    "lint-fix",
    "help",
    "smoke",
    "coverage-check",
)


@dataclass
class ContractResult:
    """Outcome of a Makefile contract validation."""

    valid: bool
    """True when all required targets are present."""

    missing: list[str] = field(default_factory=list)
    """Required targets that are absent."""

    present: list[str] = field(default_factory=list)
    """Required targets that are present."""

    optional_missing: list[str] = field(default_factory=list)
    """Optional targets that are absent (informational)."""

    warnings: list[str] = field(default_factory=list)
    """Recipe-mismatch warnings from scaffold merge."""

    repaired: bool = False
    """True when missing targets were scaffolded in-place."""


def _parse_target_names(content: str) -> set[str]:
    """Extract target names from Makefile content (lightweight)."""
    import re  # noqa: PLC0415

    targets: set[str] = set()
    for match in re.finditer(
        r"^([a-zA-Z_][a-zA-Z0-9_-]*)\s*:(?![=:])", content, re.MULTILINE
    ):
        targets.add(match.group(1))
    return targets


def validate(worktree_path: Path) -> ContractResult:
    """Check whether the Makefile in *worktree_path* satisfies the contract.

    Does **not** modify any files — read-only validation.
    """
    makefile = worktree_path / "Makefile"
    if not makefile.is_file():
        return ContractResult(
            valid=False,
            missing=list(REQUIRED_TARGETS),
            optional_missing=list(OPTIONAL_TARGETS),
        )

    content = makefile.read_text(encoding="utf-8")
    targets = _parse_target_names(content)

    missing = [t for t in REQUIRED_TARGETS if t not in targets]
    present = [t for t in REQUIRED_TARGETS if t in targets]
    optional_missing = [t for t in OPTIONAL_TARGETS if t not in targets]

    return ContractResult(
        valid=len(missing) == 0,
        missing=missing,
        present=present,
        optional_missing=optional_missing,
    )


def validate_and_repair(
    worktree_path: Path,
    language: str | None = None,
) -> ContractResult:
    """Validate the contract and scaffold missing targets if possible.

    When *language* is ``None`` the stack is auto-detected via
    ``polyglot_prep.detect_prep_stack``.

    Returns a :class:`ContractResult` with ``repaired=True`` when
    targets were added.
    """
    result = validate(worktree_path)
    if result.valid:
        return result

    # Resolve language for scaffolding
    if language is None:
        from polyglot_prep import detect_prep_stack  # noqa: PLC0415

        language = detect_prep_stack(worktree_path)

    makefile = worktree_path / "Makefile"

    if makefile.is_file():
        from makefile_scaffold import merge_makefile  # noqa: PLC0415

        content = makefile.read_text(encoding="utf-8")
        new_content, warnings = merge_makefile(content, language)
        if new_content != content:
            makefile.write_text(new_content, encoding="utf-8")
            logger.info(
                "Repaired Makefile: added %d missing targets (%s)",
                len(result.missing),
                ", ".join(result.missing),
            )
        result.warnings = warnings
    else:
        from makefile_scaffold import generate_makefile  # noqa: PLC0415

        content = generate_makefile(language)
        if content:
            makefile.write_text(content, encoding="utf-8")
            logger.info("Generated Makefile for %s stack", language)
        else:
            logger.warning(
                "Cannot scaffold Makefile — unsupported language: %s", language
            )
            return result

    # Re-validate after repair
    post = validate(worktree_path)
    post.repaired = True
    post.warnings = result.warnings
    return post
