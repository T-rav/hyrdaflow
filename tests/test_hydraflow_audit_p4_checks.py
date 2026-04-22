"""Tests for P4 (Quality Gates) check functions."""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.hydraflow_audit import registry  # noqa: F401
from scripts.hydraflow_audit.checks import p4_quality  # noqa: F401
from scripts.hydraflow_audit.models import CheckContext, Status


def _ctx(root: Path) -> CheckContext:
    return CheckContext(root=root)


def _run(check_id: str, ctx: CheckContext):
    fn = registry.get(check_id)
    assert fn is not None
    return fn(ctx)


@pytest.mark.parametrize(
    ("check_id", "target"),
    [
        ("P4.1", "lint-check"),
        ("P4.2", "typecheck"),
        ("P4.3", "security"),
        ("P4.4", "test"),
        ("P4.5", "quality-lite"),
        ("P4.6", "quality"),
    ],
)
def test_make_target_presence(check_id: str, target: str, tmp_path: Path) -> None:
    (tmp_path / "Makefile").write_text(f"{target}:\n\techo go\n", encoding="utf-8")
    assert _run(check_id, _ctx(tmp_path)).status is Status.PASS


def test_make_target_absent_fails(tmp_path: Path) -> None:
    (tmp_path / "Makefile").write_text("other:\n\techo\n", encoding="utf-8")
    assert _run("P4.4", _ctx(tmp_path)).status is Status.FAIL


def test_tool_configs_all_present_passes(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.ruff]\n[tool.pyright]\n[tool.bandit]\n[tool.pytest.ini_options]\n",
        encoding="utf-8",
    )
    assert _run("P4.7", _ctx(tmp_path)).status is Status.PASS


def test_tool_configs_missing_sections_fails(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\n", encoding="utf-8")
    result = _run("P4.7", _ctx(tmp_path))
    assert result.status is Status.FAIL
    assert "pyright" in result.message


def test_tool_configs_missing_pyproject_fails(tmp_path: Path) -> None:
    assert _run("P4.7", _ctx(tmp_path)).status is Status.FAIL
