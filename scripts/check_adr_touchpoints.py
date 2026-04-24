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
import re
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


_ADR_FILENAME_RE = re.compile(r"docs/adr/(\d{4})-[^/]+\.md$")


def _touched_adr_numbers(changed: list[str]) -> set[int]:
    """Return the numeric IDs of ADR markdown files present in the diff."""
    numbers: set[int] = set()
    for path in changed:
        m = _ADR_FILENAME_RE.search(path)
        if m:
            numbers.add(int(m.group(1)))
    return numbers


def evaluate_gate(
    changed: list[str],
    hits: dict[str, list[ADR]],
) -> tuple[bool, dict[str, list[ADR]]]:
    """Pure decision function: does the diff clear the ADR gate?

    Returns ``(passed, unresolved_hits)``. A hit is **resolved** when at
    least one of the ADRs citing that file is also updated in the diff.
    The gate passes only when *every* hit is resolved — touching an
    unrelated ADR no longer clears a gate fired by a different ADR.
    """
    if not hits:
        return True, {}
    touched_adrs = _touched_adr_numbers(changed)
    unresolved: dict[str, list[ADR]] = {}
    for path, adrs in hits.items():
        if not any(a.number in touched_adrs for a in adrs):
            unresolved[path] = adrs
    return (not unresolved), unresolved


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

    passed, unresolved = evaluate_gate(changed, hits)
    if passed:
        print("Every touchpoint has a corresponding ADR update in this PR.")
        return 0

    print(_format_report(unresolved), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
