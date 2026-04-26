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

    Each patch is a string substitution against a stable marker.
    Markers identified by reading existing wired loops (auto_agent_preflight
    and diagram_loop are the latest reference loops with all 9 sites wired).
    """
    snake = names["snake"]
    pascal = names["pascal"]
    upper = names["upper"]
    name_title = names["name_title"]
    patches: list[tuple[Path, str]] = []

    # 1. src/models.py — append two StateData fields before the trust-fleet block.
    models_path = REPO_ROOT / "src/models.py"
    models_text = models_path.read_text()
    new_fields = (
        f"    # {pascal}Loop state\n"
        f"    {snake}_attempts: dict[str, int] = Field(default_factory=dict)\n"
    )
    marker = "    flake_attempts: dict[str, int]"
    if marker in models_text:
        new_models = models_text.replace(marker, new_fields + marker)
        patches.append((models_path, new_models))

    # 2. src/state/__init__.py — import + MRO append.
    state_init_path = REPO_ROOT / "src/state/__init__.py"
    state_text = state_init_path.read_text()
    import_line = f"from ._{snake} import {pascal}StateMixin\n"
    if "from ._auto_agent import AutoAgentStateMixin\n" in state_text:
        state_text = state_text.replace(
            "from ._auto_agent import AutoAgentStateMixin\n",
            f"from ._auto_agent import AutoAgentStateMixin\n{import_line}",
        )
    if "    AutoAgentStateMixin," in state_text:
        state_text = state_text.replace(
            "    AutoAgentStateMixin,",
            f"    AutoAgentStateMixin,\n    {pascal}StateMixin,",
        )
    patches.append((state_init_path, state_text))

    # 3. src/config.py — env override + HydraFlowConfig fields.
    config_path = REPO_ROOT / "src/config.py"
    config_text = config_path.read_text()
    env_row = f'    ("{snake}_interval", "HYDRAFLOW_{upper}_INTERVAL", 3600),\n'
    if '    ("auto_agent_preflight_interval",' in config_text:
        config_text = config_text.replace(
            '    ("auto_agent_preflight_interval",',
            env_row + '    ("auto_agent_preflight_interval",',
        )
    fields_block = f"""    {snake}_enabled: bool = Field(
        default=True,
        description="UI kill-switch for {pascal}Loop (ADR-0049).",
    )
    {snake}_interval: int = Field(
        default=3600,
        ge=60,
        le=86400,
        description="Seconds between {pascal}Loop cycles (default 1h).",
    )
"""
    if "    auto_agent_preflight_enabled: bool = Field(" in config_text:
        config_text = config_text.replace(
            "    auto_agent_preflight_enabled: bool = Field(",
            fields_block + "    auto_agent_preflight_enabled: bool = Field(",
        )
    patches.append((config_path, config_text))

    # 4. src/service_registry.py — import + dataclass field + construction + kwarg.
    sr_path = REPO_ROOT / "src/service_registry.py"
    sr_text = sr_path.read_text()
    if "from auto_agent_preflight_loop import AutoAgentPreflightLoop\n" in sr_text:
        sr_text = sr_text.replace(
            "from auto_agent_preflight_loop import AutoAgentPreflightLoop\n",
            f"from auto_agent_preflight_loop import AutoAgentPreflightLoop\n"
            f"from {snake}_loop import {pascal}Loop\n",
        )
    if "    auto_agent_preflight_loop: AutoAgentPreflightLoop\n" in sr_text:
        sr_text = sr_text.replace(
            "    auto_agent_preflight_loop: AutoAgentPreflightLoop\n",
            f"    auto_agent_preflight_loop: AutoAgentPreflightLoop\n"
            f"    {snake}_loop: {pascal}Loop\n",
        )
    construction = (
        f"    {snake}_loop = {pascal}Loop(  # noqa: F841\n"
        f"        config=config,\n"
        f"        state=state,\n"
        f"        deps=loop_deps,\n"
        f"    )\n\n"
    )
    if "    auto_agent_audit_store = PreflightAuditStore" in sr_text:
        sr_text = sr_text.replace(
            "    auto_agent_audit_store = PreflightAuditStore",
            construction + "    auto_agent_audit_store = PreflightAuditStore",
        )
    if "        auto_agent_preflight_loop=auto_agent_preflight_loop,\n" in sr_text:
        sr_text = sr_text.replace(
            "        auto_agent_preflight_loop=auto_agent_preflight_loop,\n",
            f"        auto_agent_preflight_loop=auto_agent_preflight_loop,\n"
            f"        {snake}_loop={snake}_loop,\n",
        )
    patches.append((sr_path, sr_text))

    # 5. src/orchestrator.py — bg_loop_registry + loop_factories.
    orch_path = REPO_ROOT / "src/orchestrator.py"
    orch_text = orch_path.read_text()
    if (
        '            "auto_agent_preflight": svc.auto_agent_preflight_loop,'
        in orch_text
    ):
        orch_text = orch_text.replace(
            '            "auto_agent_preflight": svc.auto_agent_preflight_loop,',
            f'            "auto_agent_preflight": svc.auto_agent_preflight_loop,\n'
            f'            "{snake}": svc.{snake}_loop,',
        )
    if (
        '            ("auto_agent_preflight", self._svc.auto_agent_preflight_loop.run),'
        in orch_text
    ):
        orch_text = orch_text.replace(
            '            ("auto_agent_preflight", self._svc.auto_agent_preflight_loop.run),',
            f'            ("auto_agent_preflight", self._svc.auto_agent_preflight_loop.run),\n'
            f'            ("{snake}", self._svc.{snake}_loop.run),',
        )
    patches.append((orch_path, orch_text))

    # 6. src/ui/src/constants.js — three sites.
    # NOTE: diagram_loop is the last entry in all three constants.js sites.
    consts_path = REPO_ROOT / "src/ui/src/constants.js"
    consts_text = consts_path.read_text()
    # 6a. EDITABLE_INTERVAL_WORKERS Set — append before closing bracket.
    if "'diagram_loop'])" in consts_text:
        consts_text = consts_text.replace(
            "'diagram_loop'])",
            f"'diagram_loop', '{snake}'])",
        )
    # 6b. SYSTEM_WORKER_INTERVALS map — diagram_loop is the last entry.
    if "  diagram_loop: 14400,\n}" in consts_text:
        consts_text = consts_text.replace(
            "  diagram_loop: 14400,\n}",
            f"  diagram_loop: 14400,\n  {snake}: 3600,\n}}",
        )
    # 6c. BACKGROUND_WORKERS metadata array — append after diagram_loop entry.
    if "  { key: 'diagram_loop'," in consts_text:
        new_bw_entry = (
            f"  {{ key: '{snake}', label: '{name_title}', description: "
            f"'{description}', color: theme.purple, group: 'autonomy', "
            f"tags: ['scaffold'] }},\n"
        )
        consts_text = consts_text.replace(
            "  { key: 'diagram_loop',",
            new_bw_entry + "  { key: 'diagram_loop',",
        )
    patches.append((consts_path, consts_text))

    # 7. src/dashboard_routes/_common.py — _INTERVAL_BOUNDS.
    common_path = REPO_ROOT / "src/dashboard_routes/_common.py"
    common_text = common_path.read_text()
    if '"auto_agent_preflight": (60, 600),' in common_text:
        common_text = common_text.replace(
            '"auto_agent_preflight": (60, 600),',
            f'"auto_agent_preflight": (60, 600),\n    "{snake}": (60, 86400),',
        )
    patches.append((common_path, common_text))

    # 8. tests/scenarios/catalog/loop_registrations.py — _build_NAME + _BUILDERS.
    cat_path = REPO_ROOT / "tests/scenarios/catalog/loop_registrations.py"
    cat_text = cat_path.read_text()
    builder = (
        f"def _build_{snake}(ports: dict[str, Any], config: Any, deps: Any) -> Any:\n"
        f'    """Build {pascal}Loop for scenarios."""\n'
        f"    from {snake}_loop import {pascal}Loop  # noqa: PLC0415\n"
        f'    state = ports.get("{snake}_state") or MagicMock()\n'
        f'    ports.setdefault("{snake}_state", state)\n'
        f"    return {pascal}Loop(config=config, state=state, deps=deps)\n"
        f"\n\n"
    )
    if "def _build_auto_agent_preflight(" in cat_text:
        cat_text = cat_text.replace(
            "def _build_auto_agent_preflight(",
            builder + "def _build_auto_agent_preflight(",
        )
    if '    "auto_agent_preflight": _build_auto_agent_preflight,' in cat_text:
        cat_text = cat_text.replace(
            '    "auto_agent_preflight": _build_auto_agent_preflight,',
            f'    "auto_agent_preflight": _build_auto_agent_preflight,\n'
            f'    "{snake}": _build_{snake},',
        )
    patches.append((cat_path, cat_text))

    # 9. docs/arch/functional_areas.yml — append to the autonomy area's loops list.
    fa_path = REPO_ROOT / "docs/arch/functional_areas.yml"
    fa_text = fa_path.read_text()
    if "      - AutoAgentPreflightLoop\n" in fa_text:
        fa_text = fa_text.replace(
            "      - AutoAgentPreflightLoop\n",
            f"      - AutoAgentPreflightLoop\n      - {pascal}Loop\n",
        )
    patches.append((fa_path, fa_text))

    # 10. tests/helpers.py — ConfigFactory.create() signature + call-site passthrough.
    # Required so generated test files can pass interval/enabled overrides through
    # make_bg_loop_deps(..., {snake}_interval=N, {snake}_enabled=False).
    helpers_path = REPO_ROOT / "tests/helpers.py"
    helpers_text = helpers_path.read_text()
    sig_param = (
        f"        {snake}_interval: int = 3600,\n"
        f"        {snake}_enabled: bool = True,\n"
    )
    call_kwarg = (
        f"                {snake}_interval={snake}_interval,\n"
        f"                {snake}_enabled={snake}_enabled,\n"
    )
    # Append just before the auto_agent_preflight params (last two before the
    # closing paren) in both the signature and the HydraFlowConfig(...) call.
    if "        auto_agent_preflight_interval: int = 120," in helpers_text:
        helpers_text = helpers_text.replace(
            "        auto_agent_preflight_interval: int = 120,",
            sig_param + "        auto_agent_preflight_interval: int = 120,",
        )
    if (
        "                auto_agent_preflight_interval=auto_agent_preflight_interval,"
        in helpers_text
    ):
        helpers_text = helpers_text.replace(
            "                auto_agent_preflight_interval=auto_agent_preflight_interval,",
            call_kwarg
            + "                auto_agent_preflight_interval=auto_agent_preflight_interval,",
        )
    patches.append((helpers_path, helpers_text))

    return patches


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


def _apply_atomic(rendered: dict[Path, str], patches: list[tuple[Path, str]]) -> None:
    """File-level tempdir transaction: write all changes to a tempdir
    mirror, validate the result, bulk-copy on success.

    Tempdir mirror approach: copy the entire repo into the tempdir,
    apply all changes there, validate via `python -c "import ..."`,
    then bulk-copy back. If validation fails, the tempdir is discarded
    and the working tree is untouched.
    """
    import shutil
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        # Copy everything, but skip .git, venv, node_modules, .claude.
        shutil.copytree(
            REPO_ROOT,
            tmp_root / "repo",
            ignore=shutil.ignore_patterns(
                ".git",
                "node_modules",
                ".venv",
                "__pycache__",
                ".claude",
                "*.pyc",
            ),
            symlinks=True,
        )
        tmp_repo = tmp_root / "repo"

        # Apply new files.
        for target, content in rendered.items():
            tmp_target = tmp_repo / target.relative_to(REPO_ROOT)
            tmp_target.parent.mkdir(parents=True, exist_ok=True)
            tmp_target.write_text(content)

        # Apply patches.
        for target, content in patches:
            tmp_target = tmp_repo / target.relative_to(REPO_ROOT)
            tmp_target.write_text(content)

        # Validate: the new loop module must import cleanly. Use the snake
        # name from the first rendered file (e.g., src/blarg_monitor_loop.py
        # → blarg_monitor_loop).
        first = next(iter(rendered))
        loop_module = first.stem  # e.g., "blarg_monitor_loop"
        validate = subprocess.run(
            [
                "uv",
                "run",
                "python",
                "-c",
                f"import sys; sys.path.insert(0, 'src'); import {loop_module}",
            ],
            check=False,
            cwd=tmp_repo,
            capture_output=True,
            text=True,
        )
        if validate.returncode != 0:
            sys.stderr.write(
                "scaffold_loop: validation failed in tempdir.\n"
                f"stderr:\n{validate.stderr}\n"
                f"stdout:\n{validate.stdout}\n"
                "Working tree NOT modified.\n"
            )
            sys.exit(3)

        # Bulk-copy back. New files + patches.
        for target in {**rendered, **dict(patches)}:
            tmp_source = tmp_repo / target.relative_to(REPO_ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(tmp_source, target)

    print("scaffold_loop: apply complete. Running make arch-regen...")
    _run(["make", "arch-regen"])
    print("scaffold_loop: done. Next: implement _do_work body, run tests, commit.")


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

    _apply_atomic(rendered, patches)
    return 0


if __name__ == "__main__":
    sys.exit(main())
