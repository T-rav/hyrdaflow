"""Background worker loop — Monocle trace mining."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from models import TraceSummary
from trace_parser import parse_traces

if TYPE_CHECKING:
    from hindsight import HindsightClient
    from state import StateTracker

logger = logging.getLogger("hydraflow.trace_mining_loop")


class TraceMiningLoop(BaseBackgroundLoop):
    """Parse, aggregate, and sync Monocle trace data in staged cycles."""

    def __init__(
        self,
        config: HydraFlowConfig,
        state: StateTracker,
        hindsight: HindsightClient | None,
        deps: LoopDeps,
    ) -> None:
        super().__init__(worker_name="trace_mining", config=config, deps=deps)
        self._state = state
        self._hindsight = hindsight

    def _get_default_interval(self) -> int:
        return self._config.trace_mining_interval

    async def _do_work(self) -> dict[str, Any] | None:
        traces_root = self._config.data_root / "traces"
        if not traces_root.is_dir():
            return {"parsed": 0, "aggregated": 0, "synced": 0}

        parsed = self._stage_parse(traces_root)
        aggregated = self._stage_aggregate(traces_root)
        synced = await self._stage_insights(traces_root)

        return {"parsed": parsed, "aggregated": aggregated, "synced": synced}

    # ------------------------------------------------------------------
    # Stage 1: Parse raw traces into summaries
    # ------------------------------------------------------------------

    def _stage_parse(self, traces_root: Path) -> int:
        count = 0
        for phase_dir in self._iter_phase_dirs(traces_root):
            if (phase_dir / ".parsed").exists():
                continue
            raw_dir = phase_dir / "raw"
            if not raw_dir.is_dir():
                continue

            issue_number, phase = self._parse_dir_parts(phase_dir)
            summary = parse_traces(phase_dir, issue_number=issue_number, phase=phase)
            (phase_dir / "summary.json").write_text(summary.model_dump_json(indent=2))
            (phase_dir / ".parsed").touch()
            count += 1
            logger.info("Parsed traces for issue #%d (%s)", issue_number, phase)

        return count

    # ------------------------------------------------------------------
    # Stage 2: Aggregate summaries into LifetimeStats
    # ------------------------------------------------------------------

    def _stage_aggregate(self, traces_root: Path) -> int:
        count = 0
        for phase_dir in self._iter_phase_dirs(traces_root):
            if not (phase_dir / ".parsed").exists():
                continue
            if (phase_dir / ".aggregated").exists():
                continue

            summary_path = phase_dir / "summary.json"
            if not summary_path.exists():
                continue

            summary = TraceSummary.model_validate_json(summary_path.read_text())
            self._roll_into_stats(summary)
            (phase_dir / ".aggregated").touch()
            count += 1
            logger.info(
                "Aggregated traces for issue #%d (%s)",
                summary.issue_number,
                summary.phase,
            )

        return count

    def _roll_into_stats(self, summary: TraceSummary) -> None:
        stats = self._state.get_lifetime_stats()

        stats.total_prompt_tokens += summary.tokens.prompt_tokens
        stats.total_completion_tokens += summary.tokens.completion_tokens
        stats.total_cache_read_tokens += summary.tokens.cache_read_tokens
        stats.total_cache_creation_tokens += summary.tokens.cache_creation_tokens

        for tool, cnt in summary.tools.tool_counts.items():
            stats.tool_invocation_counts[tool] = (
                stats.tool_invocation_counts.get(tool, 0) + cnt
            )
        for tool, cnt in summary.tools.tool_errors.items():
            stats.tool_error_counts[tool] = stats.tool_error_counts.get(tool, 0) + cnt

        for skill, cnt in summary.skills.skill_counts.items():
            stats.skill_invocation_counts[skill] = (
                stats.skill_invocation_counts.get(skill, 0) + cnt
            )
        for agent, cnt in summary.skills.subagent_counts.items():
            stats.subagent_invocation_counts[agent] = (
                stats.subagent_invocation_counts.get(agent, 0) + cnt
            )

        stats.total_traces_harvested += 1
        stats.total_spans_processed += summary.spans.total_spans
        stats.total_inference_calls += summary.spans.total_inference_calls
        stats.total_agent_turns += summary.spans.total_turns

        self._state.update_lifetime_stats(stats)

    # ------------------------------------------------------------------
    # Stage 3: Push insights to Hindsight
    # ------------------------------------------------------------------

    async def _stage_insights(self, traces_root: Path) -> int:
        count = 0
        for phase_dir in self._iter_phase_dirs(traces_root):
            if not (phase_dir / ".aggregated").exists():
                continue
            if (phase_dir / ".synced").exists():
                continue

            summary_path = phase_dir / "summary.json"
            if not summary_path.exists():
                (phase_dir / ".synced").touch()
                count += 1
                continue

            summary = TraceSummary.model_validate_json(summary_path.read_text())

            if self._hindsight is not None:
                await self._retain_retrospective(summary)
                await self._retain_tracing_insights(summary)

            (phase_dir / ".synced").touch()
            count += 1
            logger.info(
                "Synced trace insights for issue #%d (%s)",
                summary.issue_number,
                summary.phase,
            )

        return count

    async def _retain_retrospective(self, summary: TraceSummary) -> None:
        from hindsight import Bank

        text = self._format_retro_summary(summary)
        await self._hindsight.retain_safe(  # type: ignore[union-attr]
            bank=Bank.RETROSPECTIVES,
            content=text,
            tags={
                "issue": str(summary.issue_number),
                "phase": summary.phase,
                "source": "trace_mining",
            },
        )

    async def _retain_tracing_insights(self, summary: TraceSummary) -> None:
        from hindsight import Bank

        text = self._format_tracing_insight(summary)
        await self._hindsight.retain_safe(  # type: ignore[union-attr]
            bank=Bank.TRACING_INSIGHTS,
            content=text,
            tags={
                "issue": str(summary.issue_number),
                "phase": summary.phase,
                "source": "trace_mining",
            },
        )

    def _format_retro_summary(self, s: TraceSummary) -> str:
        top_tools = sorted(
            s.tools.tool_counts.items(), key=lambda x: x[1], reverse=True
        )[:5]
        tools_str = ", ".join(f"{name}({cnt})" for name, cnt in top_tools)
        skills_str = ", ".join(
            f"{name}({cnt})" for name, cnt in s.skills.skill_counts.items()
        )
        agents_str = ", ".join(
            f"{name}({cnt})" for name, cnt in s.skills.subagent_counts.items()
        )
        mins = s.spans.duration_seconds / 60

        lines = [
            f"Issue #{s.issue_number} ({s.phase} phase): {s.spans.total_turns} turns, "
            f"{s.spans.total_inference_calls} inference calls,",
            f"{s.tokens.prompt_tokens:,} prompt tokens, {s.tokens.completion_tokens:,} completion tokens "
            f"({s.tokens.cache_hit_rate:.0%} cache hit rate).",
            f"Top tools: {tools_str}.",
        ]
        if skills_str:
            lines.append(f"Skills: {skills_str}.")
        if agents_str:
            lines.append(f"Subagents: {agents_str}.")
        lines.append(f"Duration: {mins:.1f}m.")
        return " ".join(lines)

    def _format_tracing_insight(self, s: TraceSummary) -> str:
        return (
            f"Trace data for issue #{s.issue_number} ({s.phase}): "
            f"{s.spans.total_spans} spans, "
            f"{s.tokens.prompt_tokens + s.tokens.completion_tokens} total tokens, "
            f"{s.tools.total_invocations} tool calls, "
            f"{s.skills.total_skills} skill invocations, "
            f"{s.skills.total_subagents} subagent spawns."
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _iter_phase_dirs(self, traces_root: Path) -> list[Path]:
        """Return all issue/phase directories under traces_root."""
        dirs = []
        for issue_dir in sorted(traces_root.iterdir()):
            if not issue_dir.is_dir() or not issue_dir.name.isdigit():
                continue
            for phase_dir in sorted(issue_dir.iterdir()):
                if phase_dir.is_dir() and phase_dir.name in (
                    "plan",
                    "implement",
                    "review",
                ):
                    dirs.append(phase_dir)
        return dirs

    def _parse_dir_parts(self, phase_dir: Path) -> tuple[int, str]:
        """Extract (issue_number, phase) from a phase directory path."""
        phase = phase_dir.name
        issue_number = int(phase_dir.parent.name)
        return issue_number, phase
