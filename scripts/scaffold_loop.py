#!/usr/bin/env python3
"""Scaffold a new caretaker loop with all conventions correct.

Usage::

    python scripts/scaffold_loop.py NAME [LABEL] [DESCRIPTION] [--interval N]
                                          [--type caretaker|subprocess]
                                          [--dry-run]
                                          [--apply]

Existing CLI signature preserved for backward-compat with PR #5911.

NAME: snake_case loop name (e.g., "blarg_monitor"). Generated class name
will be PascalCase ("BlargMonitorLoop").

Default behavior: dry-run. Prints unified summary of all planned edits and
asks `Apply? [y/N]`. Use `--apply` to skip the prompt (for CI).

The script (when fully implemented across T3.2 + T3.3 + T3.4):
1. Refuses to run on a dirty working tree.
2. Renders three new files from scripts/scaffold_templates/.
3. Patches the five-checkpoint files (models.py, state/__init__.py,
   config.py, service_registry.py, orchestrator.py, ui constants,
   _common.py, scenario catalog, functional_areas.yml).
4. File-level tempdir transaction: writes everything to a tmpdir,
   validates the result imports, bulk-copies to working tree on success.
5. Runs `make arch-regen` after apply.

Spec: docs/superpowers/specs/2026-04-26-dark-factory-infrastructure-hardening-design.md §3.2.
"""

from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import sys
from pathlib import Path

import jinja2

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = Path(__file__).resolve().parent / "scaffold_templates"


def _run(
    cmd: list[str], *, cwd: Path | None = None, check: bool = True
) -> subprocess.CompletedProcess:
    """Thin subprocess.run wrapper with sane defaults."""
    return subprocess.run(
        cmd, cwd=cwd or REPO_ROOT, capture_output=True, text=True, check=check
    )


def _ensure_clean_tree() -> None:
    """Refuse to run on a dirty working tree — apply must be atomic."""
    out = _run(["git", "status", "--porcelain"]).stdout.strip()
    if out:
        sys.stderr.write(
            "scaffold_loop: working tree is dirty. Stash or commit before running.\n"
            f"Dirty:\n{out}\n"
        )
        sys.exit(2)


def _names(snake: str) -> dict[str, str]:
    """Compute the case variants the templates need."""
    parts = snake.split("_")
    pascal = "".join(p.title() for p in parts)
    return {
        "snake": snake,
        "pascal": pascal,
        "name_title": " ".join(p.title() for p in parts),
        "upper": snake.upper(),
        "today": dt.date.today().isoformat(),
    }


def _render_templates(names: dict[str, str], description: str) -> dict[Path, str]:
    """Return {target_path: rendered_content} for all template-emitted files."""
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(TEMPLATES_DIR),
        keep_trailing_newline=True,
    )
    ctx = {**names, "description": description}
    return {
        REPO_ROOT / f"src/{names['snake']}_loop.py": env.get_template(
            "loop.py.j2"
        ).render(ctx),
        REPO_ROOT / f"src/state/_{names['snake']}.py": env.get_template(
            "state_mixin.py.j2"
        ).render(ctx),
        REPO_ROOT / f"tests/test_{names['snake']}_loop.py": env.get_template(
            "test_loop.py.j2"
        ).render(ctx),
    }


def _compute_patches(names: dict[str, str], description: str) -> list[tuple[Path, str]]:
    """Compute (target_path, new_content) for each five-checkpoint file.

    STUB — full implementation lands in T3.3.
    """
    return []


def _print_planned_edits(
    rendered: dict[Path, str], patches: list[tuple[Path, str]]
) -> None:
    """Print a human-readable summary of all planned edits (the dry-run output)."""
    print("\n=== New files ===")
    for path, content in rendered.items():
        rel = path.relative_to(REPO_ROOT)
        print(f"  CREATE {rel} ({len(content)} chars)")
    print("\n=== Five-checkpoint patches ===")
    if not patches:
        print("  (T3.3 patcher not yet implemented)")
    for path, _ in patches:
        rel = path.relative_to(REPO_ROOT)
        print(f"  PATCH  {rel}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name", help="snake_case loop name")
    parser.add_argument(
        "label", nargs="?", default=None, help="Human-readable label (optional)"
    )
    parser.add_argument("description", nargs="?", default="No description provided.")
    parser.add_argument(
        "--interval", type=int, default=3600, help="Default interval seconds"
    )
    parser.add_argument(
        "--type", choices=["caretaker", "subprocess"], default="caretaker"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="default; print diff and exit"
    )
    parser.add_argument("--apply", action="store_true", help="skip the y/N prompt")
    args = parser.parse_args()

    if args.type == "subprocess":
        sys.stderr.write(
            "scaffold_loop: --type=subprocess not yet implemented; falling "
            "back to caretaker template.\n"
        )

    _ensure_clean_tree()

    names = _names(args.name)
    rendered = _render_templates(names, args.description)
    patches = _compute_patches(names, args.description)

    _print_planned_edits(rendered, patches)

    # Default is dry-run: if --apply was not explicitly given, just show the
    # plan and exit 0.  Use --apply to write files (skips the prompt, safe for CI).
    if not args.apply:
        print("\nDry-run mode (default). Use --apply to write the files.")
        return 0

    # T3.4 wires the file-level tempdir transaction here.
    raise NotImplementedError("T3.4 wires the apply transaction.")


if __name__ == "__main__":
    sys.exit(main())
