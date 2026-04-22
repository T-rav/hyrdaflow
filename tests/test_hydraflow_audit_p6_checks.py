"""Tests for P6 (Agents / loops / labels) check functions."""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.hydraflow_audit import registry  # noqa: F401
from scripts.hydraflow_audit.checks import p6_agents  # noqa: F401
from scripts.hydraflow_audit.models import CheckContext, Status


def _ctx(root: Path, *, orchestration: bool = True) -> CheckContext:
    return CheckContext(root=root, is_orchestration_repo=orchestration)


def _run(check_id: str, ctx: CheckContext):
    fn = registry.get(check_id)
    assert fn is not None
    return fn(ctx)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.mark.parametrize("check_id", ["P6.1", "P6.2", "P6.3", "P6.4", "P6.5"])
def test_all_na_for_non_orchestration_repo(check_id: str, tmp_path: Path) -> None:
    assert _run(check_id, _ctx(tmp_path, orchestration=False)).status is Status.NA


def test_orchestrator_with_concurrent_loops_passes(tmp_path: Path) -> None:
    _write(
        tmp_path / "src" / "orchestrator.py",
        "import asyncio\n\nasync def main():\n    await asyncio.gather(a(), b())\n",
    )
    assert _run("P6.1", _ctx(tmp_path)).status is Status.PASS


def test_orchestrator_without_gather_fails(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "orchestrator.py", "async def main(): pass\n")
    assert _run("P6.1", _ctx(tmp_path)).status is Status.FAIL


def test_labels_centralised_passes(tmp_path: Path) -> None:
    body = "\n".join(
        f"    {name}_label: list[str] = Field(default=['{name}'])"
        for name in ["find", "plan", "ready", "review"]
    )
    _write(tmp_path / "src" / "config.py", f"class C:\n{body}\n")
    assert _run("P6.2", _ctx(tmp_path)).status is Status.PASS


def test_labels_scattered_fails(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "config.py", "FIND = 'find'\n")
    assert _run("P6.2", _ctx(tmp_path)).status is Status.FAIL


def test_base_background_loop_class_detected(tmp_path: Path) -> None:
    _write(
        tmp_path / "src" / "base_background_loop.py",
        "class BaseBackgroundLoop:\n    async def run(self): ...\n",
    )
    assert _run("P6.3", _ctx(tmp_path)).status is Status.PASS


def test_base_background_loop_missing_fails(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    assert _run("P6.3", _ctx(tmp_path)).status is Status.FAIL


def test_wiring_test_covers_five_checkpoints(tmp_path: Path) -> None:
    _write(
        tmp_path / "tests" / "test_loop_wiring_completeness.py",
        (
            "# covers service_registry, orchestrator, constants.js, _common.py, _interval\n"
            "def test_wiring(): pass\n"
        ),
    )
    assert _run("P6.4", _ctx(tmp_path)).status is Status.PASS


def test_wiring_test_missing_fails(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    assert _run("P6.4", _ctx(tmp_path)).status is Status.FAIL


def test_atomic_swap_helper_detected(tmp_path: Path) -> None:
    _write(
        tmp_path / "src" / "pr_manager.py",
        "async def swap_pipeline_labels(issue, to): ...\n",
    )
    assert _run("P6.5", _ctx(tmp_path)).status is Status.PASS


def test_atomic_swap_helper_missing_fails(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "pr_manager.py", "def add_label(x): ...\n")
    assert _run("P6.5", _ctx(tmp_path)).status is Status.FAIL
