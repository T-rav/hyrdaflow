"""Shared fixtures for architecture tests.

The `fixture_src_tree` factory writes a tiny synthetic source tree to
tmp_path so extractor tests run in isolation from the live repo. The
`real_repo_root` fixture points at the actual repo (for tests that
intentionally exercise the live tree, like the drift test).
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest


@pytest.fixture
def fixture_src_tree(tmp_path: Path):
    """Returns a callable: write_files(spec: dict[str, str]) -> Path.

    Usage:
        root = fixture_src_tree({
            "src/foo.py": "class Foo: ...",
            "src/bar.py": "from foo import Foo",
        })
    """

    def _write(spec: dict[str, str]) -> Path:
        for rel, body in spec.items():
            p = tmp_path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(dedent(body).lstrip("\n"))
        return tmp_path

    return _write


@pytest.fixture
def real_repo_root() -> Path:
    """Path to the repo root (parents[2] from this conftest)."""
    return Path(__file__).resolve().parents[2]
