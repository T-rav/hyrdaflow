"""Shared PromptBuilder utility for runners.

Centralises the stats-gathering and section-formatting pattern that was
previously duplicated across ``agent.py``, ``hitl_runner.py``,
``planner.py``, ``reviewer.py``, and ``triage.py``.

Typical usage::

    builder = PromptBuilder()
    body = builder.add_context_section("Issue body", raw_body, max_chars=5000)
    cause = builder.add_history_section("Cause", raw_cause, max_chars=2000)
    stats = builder.build_stats()
    prompt = f"...{body}...{cause}..."
    return prompt, stats
"""

from __future__ import annotations

from prompt_stats import build_prompt_stats, truncate_with_notice


class PromptBuilder:
    """Accumulates prompt sections and tracks character-count statistics.

    Each section is optionally truncated via :func:`~prompt_stats.truncate_with_notice`.
    Characters are bucketed as *history* (dynamic content such as comments or
    error logs) or *context* (relatively static content such as issue bodies or
    diffs).  Call :meth:`build_stats` at the end to get the payload consumed by
    :class:`~prompt_telemetry.PromptTelemetry`.
    """

    def __init__(self) -> None:
        self._history_before: int = 0
        self._history_after: int = 0
        self._context_before: int = 0
        self._context_after: int = 0
        self._section_chars: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def add_history_section(self, label: str, content: str, max_chars: int) -> str:
        """Truncate *content* and record it as a *history* section.

        History sections contain dynamic information that changes frequently
        (comments, error logs, review feedback, etc.).

        Returns the (possibly truncated) text.
        """
        return self._add(label, content, max_chars, is_context=False)

    def add_context_section(self, label: str, content: str, max_chars: int) -> str:
        """Truncate *content* and record it as a *context* section.

        Context sections contain relatively static information (issue body,
        diff, manifest, etc.).

        Returns the (possibly truncated) text.
        """
        return self._add(label, content, max_chars, is_context=True)

    def build_stats(self) -> dict[str, object]:
        """Return the aggregated prompt-pruning statistics."""
        return build_prompt_stats(
            history_before=self._history_before,
            history_after=self._history_after,
            context_before=self._context_before,
            context_after=self._context_after,
            section_chars=self._section_chars,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _add(
        self, label: str, content: str, max_chars: int, *, is_context: bool
    ) -> str:
        truncated, before, after = truncate_with_notice(content, max_chars, label=label)
        if is_context:
            self._context_before += before
            self._context_after += after
        else:
            self._history_before += before
            self._history_after += after
        key = label.strip().lower().replace(" ", "_")
        self._section_chars[f"{key}_before"] = before
        self._section_chars[f"{key}_after"] = after
        return truncated
