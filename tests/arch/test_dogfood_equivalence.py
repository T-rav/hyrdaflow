"""Dogfood gate: new scripts/check_arch.py must report no violations on HydraFlow's
own codebase, matching the existing scripts/check_layer_imports.py behaviour.

If this test starts failing, the new checker has found a real violation OR the
rule module has fallen out of sync with the hardcoded map. Read the diff, fix
either the rules or the code.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_old_checker_reports_zero_violations() -> None:
    """Sanity: old checker is zero on main. If it's not, the equivalence gate
    is pointless; update both old and new together."""
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "check_layer_imports.py")],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO,
    )
    assert proc.returncode == 0, (
        f"old checker reports violations:\n{proc.stdout}\n---\n{proc.stderr}"
    )


def test_new_checker_matches_old_on_main() -> None:
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "check_arch.py"), str(REPO)],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO,
    )
    assert proc.returncode == 0, (
        f"new checker reports violations:\n"
        f"STDOUT:\n{proc.stdout}\n"
        f"STDERR:\n{proc.stderr}"
    )
