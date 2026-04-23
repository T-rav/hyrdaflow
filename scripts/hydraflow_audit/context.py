"""Detect the shape of the target repo so conditional checks return NA cleanly.

A non-orchestration repo does not have `src/orchestrator.py`; P6 and related
orchestration-only checks mark themselves NA when run against it. A repo
without a UI directory skips browser E2E checks. Detection is intentionally
simple — the audit is about conformance, not cleverness.
"""

from __future__ import annotations

from pathlib import Path

from .models import CheckContext


def build(root: Path) -> CheckContext:
    return CheckContext(
        root=root,
        is_orchestration_repo=_detect_orchestration(root),
        has_ui=_detect_ui(root),
    )


def _detect_orchestration(root: Path) -> bool:
    candidates = [
        root / "src" / "orchestrator.py",
        root / "src" / "base_background_loop.py",
    ]
    return any(p.exists() for p in candidates)


def _detect_ui(root: Path) -> bool:
    return (root / "ui").is_dir() or (root / "src" / "ui").is_dir()
