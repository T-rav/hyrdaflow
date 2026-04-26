"""Strict-build test: catches broken cross-links before Pages deploy."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_mkdocs_build_strict_succeeds(real_repo_root: Path):
    """Run `mkdocs build --strict` against the live docs tree.

    Fails on any warning. This is the gate that catches a generator
    emitting a relative link to a page that doesn't exist (e.g. an ADR
    file path that's been deleted).
    """
    if shutil.which("mkdocs") is None:
        pytest.skip("mkdocs not installed; run: pip install -e '.[docs]'")
    res = subprocess.run(
        ["mkdocs", "build", "--strict"],
        cwd=real_repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode != 0:
        pytest.fail(
            f"`mkdocs build --strict` failed:\n"
            f"--- stdout ---\n{res.stdout}\n"
            f"--- stderr ---\n{res.stderr}"
        )
