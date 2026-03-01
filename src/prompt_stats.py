"""Reusable prompt-pruning helpers for inference telemetry."""

from __future__ import annotations

from collections.abc import Mapping


def truncate_with_notice(
    text: str, max_chars: int, label: str = "Text"
) -> tuple[str, int, int]:
    """Truncate *text* to *max_chars* and append a short notice when trimmed."""
    raw = text or ""
    before = len(raw)
    if max_chars <= 0:
        return "", before, 0
    if before <= max_chars:
        return raw, before, before
    truncated = raw[:max_chars] + f"\n\n[{label} truncated at {max_chars:,} chars]"
    return truncated, before, len(truncated)


def build_prompt_stats(
    *,
    history_before: int = 0,
    history_after: int = 0,
    context_before: int = 0,
    context_after: int = 0,
    section_chars: Mapping[str, int] | None = None,
) -> dict[str, object]:
    """Build a normalized stats payload consumed by PromptTelemetry."""
    hb = max(0, int(history_before))
    ha = max(0, int(history_after))
    cb = max(0, int(context_before))
    ca = max(0, int(context_after))
    stats: dict[str, object] = {
        "history_chars_before": hb,
        "history_chars_after": ha,
        "context_chars_before": cb,
        "context_chars_after": ca,
        "pruned_chars_total": max(0, hb - ha) + max(0, cb - ca),
    }
    if section_chars:
        clean_sections: dict[str, int] = {}
        for key, value in section_chars.items():
            name = str(key).strip()
            if not name:
                continue
            clean_sections[name] = max(0, int(value))
        if clean_sections:
            stats["section_chars"] = clean_sections
    return stats
