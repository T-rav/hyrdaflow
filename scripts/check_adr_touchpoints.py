"""ADR touchpoint gate — P2 of the wiki-evolution audit.

Given a git diff (``--base`` vs ``--head``), reports Accepted ADRs
whose ``src/...`` citations intersect the changed files. The PR is
expected to either:

1. Include ADR updates in the diff (``docs/adr/*.md`` files touched).
2. Carry a ``Skip-ADR: <reason>`` marker in the PR body (checked by
   CI, not this script).

Without one of the escape hatches, the script exits non-zero so the
CI gate can fail the PR and surface which ADRs need attention.

Usage (CI):

    python scripts/check_adr_touchpoints.py \\
        --base origin/main --head HEAD

Usage (local):

    python scripts/check_adr_touchpoints.py --base main --head HEAD
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from adr_index import ADR, ADRIndex  # noqa: E402


def _changed_files(base: str, head: str) -> list[str]:
    """Return the list of files changed between *base* and *head*."""
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...{head}"],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO_ROOT,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _pr_touches_any_adr(changed: list[str]) -> bool:
    """Return True if any ADR markdown file is included in the diff."""
    return any(p.startswith("docs/adr/") and p.endswith(".md") for p in changed)


def _format_report(hits: dict[str, list[ADR]]) -> str:
    lines = ["Accepted ADRs cite files touched in this PR:", ""]
    for path in sorted(hits):
        adrs = sorted(hits[path], key=lambda a: a.number)
        summaries = ", ".join(f"ADR-{a.number:04d} ({a.title})" for a in adrs)
        lines.append(f"  {path}")
        lines.append(f"    → {summaries}")
    lines.extend(
        [
            "",
            "Next steps:",
            "  - Update the relevant ADR(s) in the same PR, OR",
            "  - Add `Skip-ADR: <reason>` to the PR body (enforced by the",
            "    CI workflow — this script only reports touchpoints).",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="Git base ref (e.g. origin/main)")
    parser.add_argument("--head", default="HEAD", help="Git head ref (default HEAD)")
    parser.add_argument(
        "--adr-dir",
        default=str(REPO_ROOT / "docs" / "adr"),
        help="ADR directory (default docs/adr)",
    )
    args = parser.parse_args()

    changed = _changed_files(args.base, args.head)
    if not changed:
        return 0

    idx = ADRIndex(Path(args.adr_dir))
    hits = idx.adrs_touching(changed)
    if not hits:
        return 0

    if _pr_touches_any_adr(changed):
        # PR already updates at least one ADR; assume the author is aware.
        print("ADR file(s) modified in this PR — touchpoint gate passes.")
        return 0

    print(_format_report(hits), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
