"""CLI entry point for `python -m scripts.hydraflow_audit`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import checks as _checks  # noqa: F401 — side effect: registers check functions
from . import context, observability
from .parser import parse_adr
from .report import format_terminal, write_json
from .runner import overall_exit_code, run_checks


def _resolve_adr_path(target_root: Path, explicit: Path | None) -> Path:
    """Find ADR-0044 — prefer the target repo's copy so projects own their rules."""
    if explicit is not None:
        return explicit
    local = target_root / "docs" / "adr" / "0044-hydraflow-principles.md"
    if local.exists():
        return local
    # Fall back to the hydraflow-checkout copy (this repo).
    here = Path(__file__).resolve().parents[2]
    return here / "docs" / "adr" / "0044-hydraflow-principles.md"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hydraflow_audit",
        description="Audit a repository against HydraFlow principles (ADR-0044).",
    )
    parser.add_argument(
        "target",
        nargs="?",
        default=".",
        help="Path to the target repository (default: current directory)",
    )
    parser.add_argument(
        "--adr",
        type=Path,
        default=None,
        help="Override the ADR-0044 location (default: target's docs/adr/, then this repo's)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Only write JSON output (no terminal summary)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="JSON output path (default: <target>/.hydraflow/audit-report.json)",
    )
    args = parser.parse_args(argv)

    observability.init()

    with observability.guard():
        target_root = Path(args.target).resolve()
        adr_path = _resolve_adr_path(target_root, args.adr)
        specs = parse_adr(adr_path)
        ctx = context.build(target_root)
        findings = run_checks(specs, ctx)

        out_path = args.out or (target_root / ".hydraflow" / "audit-report.json")
        write_json(findings, out_path)

        if not args.json:
            print(format_terminal(findings))
            print(f"\nJSON report: {out_path}")

        return overall_exit_code(findings)


if __name__ == "__main__":
    sys.exit(main())
