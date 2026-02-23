"""Makefile scaffolding for target repos.

Generates or merges Makefile targets (lint, lint-check, typecheck, test, quality)
based on detected repo language (Python or JS/TS).
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

from manifest import detect_language

_PYTHON_TARGETS: dict[str, str] = {
    "lint": "\truff check . --fix && ruff format .\n",
    "lint-check": "\truff check . && ruff format . --check\n",
    "typecheck": "\tpyright\n",
    "test": "\tpytest tests/ -x -q\n",
}

_JS_TARGETS: dict[str, str] = {
    "lint": "\tnpx eslint . --fix\n",
    "lint-check": "\tnpx eslint .\n",
    "typecheck": "\tnpx tsc --noEmit\n",
    "test": "\tnpx vitest run\n",
}

# quality is always a prerequisite-only target
_QUALITY_LINE = "quality: lint-check typecheck test\n"

_ALL_TARGET_NAMES = ["lint", "lint-check", "typecheck", "test", "quality"]

_MAKEFILE_NAMES = ("GNUmakefile", "makefile", "Makefile")


@dataclasses.dataclass
class ScaffoldResult:
    """Result of a Makefile scaffolding operation."""

    created: bool = False
    targets_added: list[str] = dataclasses.field(default_factory=list)
    warnings: list[str] = dataclasses.field(default_factory=list)
    skipped: list[str] = dataclasses.field(default_factory=list)
    language: str = "unknown"


def parse_makefile(content: str) -> dict[str, str]:
    """Extract target-name -> recipe-text mappings from Makefile content.

    Ignores comments, variable assignments, and .PHONY declarations.
    """
    targets: dict[str, str] = {}
    current_target: str | None = None
    recipe_lines: list[str] = []

    for line in content.split("\n"):
        # Skip .PHONY declarations
        if line.startswith(".PHONY"):
            continue

        # Check for target definition: "name:" or "name: deps"
        # Exclude variable assignments like CC := gcc or CC ::= gcc
        target_match = re.match(r"^([a-zA-Z_][a-zA-Z0-9_-]*)\s*:(?![=:])(.*)$", line)
        if target_match:
            # Save previous target
            if current_target is not None:
                targets[current_target] = "\n".join(recipe_lines)
            current_target = target_match.group(1)
            recipe_lines = []
            continue

        # Recipe line (tab-indented)
        if line.startswith("\t") and current_target is not None:
            recipe_lines.append(line.lstrip("\t"))
            continue

        # Blank or non-recipe line ends current target
        if current_target is not None and not line.startswith("\t"):
            targets[current_target] = "\n".join(recipe_lines)
            current_target = None
            recipe_lines = []

    # Save last target
    if current_target is not None:
        targets[current_target] = "\n".join(recipe_lines)

    return targets


def _targets_for_language(language: str) -> dict[str, str]:
    """Return the target templates for a given language."""
    if language in ("python", "mixed"):
        return _PYTHON_TARGETS
    if language == "javascript":
        return _JS_TARGETS
    return {}


def generate_makefile(language: str) -> str:
    """Build a complete Makefile string from the template for the given language."""
    targets = _targets_for_language(language)
    if not targets:
        return ""

    lines: list[str] = []
    lines.append(f".PHONY: {' '.join(_ALL_TARGET_NAMES)}")
    lines.append("")

    for name, recipe in targets.items():
        lines.append(f"{name}:")
        lines.append(recipe)

    lines.append(_QUALITY_LINE)

    return "\n".join(lines)


def merge_makefile(existing_content: str, language: str) -> tuple[str, list[str]]:
    """Merge missing targets into an existing Makefile.

    Returns (new_content, warnings). Existing targets are never overwritten.
    Warnings are emitted when an existing target has a different recipe.
    """
    template_targets = _targets_for_language(language)
    if not template_targets:
        return existing_content, []

    # Include quality in the full set to check
    all_template: dict[str, str | None] = dict(template_targets)
    all_template["quality"] = None  # prerequisite-only, no recipe body

    existing_targets = parse_makefile(existing_content)

    warnings: list[str] = []
    targets_to_add: list[str] = []

    for name, template_recipe in all_template.items():
        if name in existing_targets:
            # Compare recipes (only for targets with recipe bodies)
            if template_recipe is not None:
                existing_recipe = existing_targets[name]
                expected_recipe = template_recipe.strip("\n").lstrip("\t")
                if existing_recipe.strip() != expected_recipe.strip():
                    warnings.append(
                        f"Target '{name}' exists with different recipe: "
                        f"found '{existing_recipe.strip()}', "
                        f"expected '{expected_recipe.strip()}'"
                    )
        else:
            targets_to_add.append(name)

    # Warn if existing quality: has different prerequisites (no recipe to compare)
    if "quality" in existing_targets:
        quality_match = re.search(
            r"^quality\s*:(?![=:])\s*(.*)",
            existing_content,
            re.MULTILINE,
        )
        if quality_match:
            existing_deps = quality_match.group(1).strip()
            expected_deps = "lint-check typecheck test"
            if existing_deps != expected_deps:
                warnings.append(
                    f"Target 'quality' exists with different prerequisites: "
                    f"found '{existing_deps}', expected '{expected_deps}'"
                )

    if not targets_to_add:
        return existing_content, warnings

    # Build the new content by appending missing targets
    new_lines = existing_content.rstrip("\n")

    # Add a blank line separator
    new_lines += "\n"

    for name in targets_to_add:
        if name == "quality":
            continue  # Add quality last
        new_lines += f"\n{name}:\n{template_targets[name]}"

    if "quality" in targets_to_add:
        new_lines += f"\n{_QUALITY_LINE}"

    # Ensure .PHONY includes all targets — preserve existing .PHONY entries
    # that may not have target definitions in this file (e.g., from includes).
    existing_phony: set[str] = set()
    for _line in existing_content.split("\n"):
        if _line.startswith(".PHONY"):
            _rest = _line.split(":", 1)
            if len(_rest) > 1:
                existing_phony.update(_rest[1].split())
    all_target_names = (
        existing_phony | set(existing_targets.keys()) | set(targets_to_add)
    )
    phony_names = " ".join(sorted(all_target_names))

    if ".PHONY" in existing_content:
        # Replace existing .PHONY line(s)
        new_lines = re.sub(
            r"\.PHONY:.*",
            f".PHONY: {phony_names}",
            new_lines,
            count=1,
        )
    else:
        # Prepend .PHONY
        new_lines = f".PHONY: {phony_names}\n\n{new_lines}"

    # Ensure trailing newline
    if not new_lines.endswith("\n"):
        new_lines += "\n"

    return new_lines, warnings


def _find_existing_makefile(repo_root: Path) -> Path | None:
    """Find an existing Makefile, checking GNUmakefile, makefile, Makefile."""
    for name in _MAKEFILE_NAMES:
        path = repo_root / name
        if path.exists():
            return path
    return None


def scaffold_makefile(repo_root: Path, dry_run: bool = False) -> ScaffoldResult:
    """Scaffold or merge Makefile targets for a repo.

    Detects language, checks for existing Makefile, generates or merges
    targets, and writes the result (unless dry_run is True).
    """
    language = detect_language(repo_root)
    result = ScaffoldResult(language=language)

    if language == "unknown":
        return result

    existing_path = _find_existing_makefile(repo_root)

    if existing_path is not None:
        existing_content = existing_path.read_text()

        # Treat empty/whitespace-only Makefiles as "no Makefile"
        if not existing_content.strip():
            content = generate_makefile(language)
            result.created = True
            result.targets_added = list(_ALL_TARGET_NAMES)
            if not dry_run:
                existing_path.write_text(content)
            return result

        existing_targets = parse_makefile(existing_content)
        new_content, warnings = merge_makefile(existing_content, language)
        result.warnings = warnings

        # Determine which targets were added
        template_targets = _targets_for_language(language)
        all_names = list(template_targets.keys()) + ["quality"]
        result.targets_added = [n for n in all_names if n not in existing_targets]
        result.skipped = [n for n in all_names if n in existing_targets]

        if result.targets_added and not dry_run:
            existing_path.write_text(new_content)
    else:
        content = generate_makefile(language)
        result.created = True
        result.targets_added = list(_ALL_TARGET_NAMES)
        if not dry_run:
            makefile_path = repo_root / "Makefile"
            makefile_path.write_text(content)

    return result
