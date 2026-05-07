"""Tests verifying .githooks/pre-push contains the arch-check gate."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
PRE_PUSH_HOOK = REPO_ROOT / ".githooks" / "pre-push"


def _hook_text() -> str:
    return PRE_PUSH_HOOK.read_text(encoding="utf-8")


def _line_number(text: str, needle: str) -> int:
    for i, line in enumerate(text.splitlines()):
        if needle in line:
            return i
    return -1


def test_pre_push_hook_exists() -> None:
    assert PRE_PUSH_HOOK.exists(), ".githooks/pre-push must exist"


def test_pre_push_hook_has_arch_check() -> None:
    assert "arch-check" in _hook_text(), (
        ".githooks/pre-push must invoke `make arch-check` to catch stale arch artifacts"
    )


def test_pre_push_hook_has_kill_switch() -> None:
    assert "HYDRAFLOW_DISABLE_PRE_PUSH_ARCH_CHECK" in _hook_text(), (
        ".githooks/pre-push must honor HYDRAFLOW_DISABLE_PRE_PUSH_ARCH_CHECK=1 kill-switch "
        "(per ADR-0049 kill-switch convention)"
    )


def test_pre_push_hook_arch_check_runs_before_quality_lite() -> None:
    text = _hook_text()
    arch_line = _line_number(text, "arch-check")
    quality_line = _line_number(text, "quality-lite")
    assert arch_line != -1, ".githooks/pre-push must reference arch-check"
    assert quality_line != -1, ".githooks/pre-push must reference quality-lite"
    assert arch_line < quality_line, (
        "arch-check must run before quality-lite (faster and more deterministic)"
    )
