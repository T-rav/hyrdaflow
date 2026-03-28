"""Per-issue reflections — append-only learning file for cross-cycle context.

Each issue gets a `reflections.txt` that accumulates learnings across
implementation, review, and retry cycles. The planner and implement
phases read it before starting work so each cycle benefits from
previous discoveries.

Inspired by the Ralph pattern (snarktank/ralph).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from config import HydraFlowConfig

logger = logging.getLogger("hydraflow.reflections")


def _reflections_path(config: HydraFlowConfig, issue_number: int) -> Path:
    """Return the reflections file path for an issue."""
    return config.data_root / "reflections" / f"issue-{issue_number}.txt"


def read_reflections(config: HydraFlowConfig, issue_number: int) -> str:
    """Read the reflections file for an issue. Returns empty string if none."""
    path = _reflections_path(config, issue_number)
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        logger.debug("Could not read reflections for issue #%d", issue_number)
        return ""


def append_reflection(
    config: HydraFlowConfig,
    issue_number: int,
    phase: str,
    content: str,
) -> None:
    """Append a learning entry to the issue's reflections file."""
    path = _reflections_path(config, issue_number)
    path.parent.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    entry = f"\n--- {phase} | {timestamp} ---\n{content.strip()}\n"

    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(entry)
        logger.debug(
            "Appended %s reflection for issue #%d (%d chars)",
            phase,
            issue_number,
            len(content),
        )
    except OSError:
        logger.warning(
            "Could not write reflection for issue #%d", issue_number, exc_info=True
        )


def clear_reflections(config: HydraFlowConfig, issue_number: int) -> None:
    """Remove the reflections file for an issue (e.g., after merge)."""
    path = _reflections_path(config, issue_number)
    path.unlink(missing_ok=True)
