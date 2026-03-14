"""Shared PromptBuilder utility for runners.

Centralises the stats-gathering and section-formatting pattern that was
previously duplicated across ``agent.py``, ``hitl_runner.py``,
``planner.py``, ``reviewer.py``, and ``triage.py``.

Typical usage (with built-in truncation)::

    builder = PromptBuilder()
    body = builder.add_context_section("Issue body", raw_body, max_chars=5000)
    cause = builder.add_history_section("Cause", raw_cause, max_chars=2000)
    stats = builder.build_stats()
    prompt = f"...{body}...{cause}..."
    return prompt, stats

For runners that apply custom truncation externally, use the record helpers::

    builder = PromptBuilder()
    processed_body = my_custom_truncate(raw_body)
    builder.record_context("Issue body", raw_body, processed_body)
    stats = builder.build_stats()
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

    Runners that apply their own truncation logic (e.g. line-boundary or
    semantic summarisation) should use :meth:`record_context` /
    :meth:`record_history` instead of :meth:`add_context_section` /
    :meth:`add_history_section`.
    """

    def __init__(self) -> None:
        self._history_before: int = 0
        self._history_after: int = 0
        self._context_before: int = 0
        self._context_after: int = 0
        self._section_chars: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Public helpers — built-in truncation
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

    # ------------------------------------------------------------------
    # Public helpers — external truncation (record-only)
    # ------------------------------------------------------------------

    def record_context(self, label: str, raw: str, processed: str) -> None:
        """Record stats for a context section already processed externally.

        Use this when the runner applies its own truncation strategy (e.g.
        line-boundary truncation or semantic summarisation) and only needs
        PromptBuilder to accumulate the statistics.
        """
        self._record(label, raw, processed, is_context=True)

    def record_history(self, label: str, raw: str, processed: str) -> None:
        """Record stats for a history section already processed externally.

        Use this when the runner applies its own truncation strategy and only
        needs PromptBuilder to accumulate the statistics.
        """
        self._record(label, raw, processed, is_context=False)

    # ------------------------------------------------------------------
    # Stats aggregation
    # ------------------------------------------------------------------

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
        self._accumulate(label, before, after, is_context=is_context)
        return truncated

    def _record(
        self, label: str, raw: str, processed: str, *, is_context: bool
    ) -> None:
        before = len(raw or "")
        after = len(processed or "")
        self._accumulate(label, before, after, is_context=is_context)

    def _accumulate(
        self, label: str, before: int, after: int, *, is_context: bool
    ) -> None:
        if is_context:
            self._context_before += before
            self._context_after += after
        else:
            self._history_before += before
            self._history_after += after
        key = label.strip().lower().replace(" ", "_")
        self._section_chars[f"{key}_before"] = before
        self._section_chars[f"{key}_after"] = after
