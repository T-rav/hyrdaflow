"""Utilities for reading and preparing log context for agent injection."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import HydraFlowConfig

_TRUNCATION_MARKER = "[Log truncated — showing last {n} chars]\n\n"


def truncate_log(log_text: str, max_chars: int) -> str:
    """Keep the tail of *log_text*, prepending a truncation marker if needed.

    Returns *log_text* unchanged when it fits within *max_chars*.
    """
    if len(log_text) <= max_chars:
        return log_text

    marker = _TRUNCATION_MARKER.format(n=max_chars)
    available = max_chars - len(marker)
    if available <= 0:
        return marker[:max_chars]
    return marker + log_text[-available:]


def load_runtime_logs(config: HydraFlowConfig) -> str:
    """Read the HydraFlow application log tail for agent context injection.

    Returns an empty string when the feature is disabled, the log file is
    missing, or it is empty.  Output is capped at ``config.max_runtime_log_chars``.
    """
    if not config.inject_runtime_logs:
        return ""

    log_path = config.data_path("logs", "hydraflow.log")
    if not log_path.is_file():
        return ""

    try:
        content = log_path.read_text()
    except OSError:
        return ""

    if not content.strip():
        return ""

    return truncate_log(content, config.max_runtime_log_chars)
