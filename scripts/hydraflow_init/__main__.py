"""CLI for `python -m scripts.hydraflow_init`."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from scripts.hydraflow_audit import observability  # self-instrumentation per P7.6

from .modes import decide
from .prompt import render


def _audit_report_path(target: Path, override: Path | None) -> Path:
    if override is not None:
        return override
    return target / ".hydraflow" / "audit-report.json"


def _ensure_report(target: Path, report_path: Path) -> None:
    """Run `make audit` (via module invocation) if the report is missing."""
    if report_path.exists():
        return
    subprocess.run(
        [sys.executable, "-m", "scripts.hydraflow_audit", str(target), "--json"],
        check=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hydraflow_init",
        description="Emit a superpowers-chained adoption plan from an audit report.",
    )
    parser.add_argument("target", nargs="?", default=".")
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--principle", default=None, help="Scope to a single principle (e.g. P3)"
    )
    parser.add_argument(
        "--skip-brainstorm",
        action="store_true",
        help="Skip the brainstorming step even in greenfield mode",
    )
    args = parser.parse_args(argv)

    observability.init()

    with observability.guard():
        target_root = Path(args.target).resolve()
        report_path = _audit_report_path(target_root, args.report)
        _ensure_report(target_root, report_path)
        data = json.loads(report_path.read_text(encoding="utf-8"))
        findings = data.get("findings", [])
        summary = data.get("summary", {})
        mode = decide(findings)
        output = render(
            target=str(target_root),
            findings=findings,
            summary=summary,
            mode=mode,
            principle_filter=args.principle,
            skip_brainstorm=args.skip_brainstorm,
        )

        if args.out is not None:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(output, encoding="utf-8")
            print(f"Adoption plan written to {args.out}")
        else:
            sys.stdout.write(output)

        return 0


if __name__ == "__main__":
    sys.exit(main())
