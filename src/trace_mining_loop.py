"""Background worker loop — in-process trace mining.

Walks the `<data_root>/traces/<issue>/<phase>/run-N/` layout produced
by `trace_rollup.write_phase_rollup`, aggregates each run's summary
into LifetimeStats, syncs insights to Hindsight, and finalizes any
orphan runs left behind by HydraFlow crashes.

This loop previously consumed Monocle-era files via `trace_parser`.
That stage has been removed — `write_phase_rollup` now writes
`summary.json` directly.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from models import TraceSummary

if TYPE_CHECKING:
    from hindsight import HindsightClient
    from state import StateTracker

logger = logging.getLogger("hydraflow.trace_mining_loop")

_KNOWN_PHASES = {"plan", "implement", "review", "triage", "hitl"}


class TraceMiningLoop(BaseBackgroundLoop):
    """Aggregate and sync in-process trace data in staged cycles."""

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
            return {"finalized": 0, "aggregated": 0, "synced": 0}

        finalized = self._stage_finalize_orphans(traces_root)
        aggregated = self._stage_aggregate(traces_root)
        synced = await self._stage_insights(traces_root)

        return {
            "finalized": finalized,
            "aggregated": aggregated,
            "synced": synced,
        }

    # ------------------------------------------------------------------
    # Stage 1: Finalize orphan runs (crashed before rollup)
    # ------------------------------------------------------------------

    def _stage_finalize_orphans(self, traces_root: Path) -> int:
        """Detect run-N/ directories with subprocess files but no summary.json
        AND no entry in state['trace_runs']['active']. Synthesize a
        crashed-marker summary and touch `.finalized_orphan`.

        First, purge any active entries whose ``started_at`` is older than
        ``2 * agent_timeout`` — these belong to runs killed by a crash and
        would otherwise hide their orphan directories from this stage
        forever.
        """
        try:
            stale_window = max(float(self._config.agent_timeout) * 2.0, 600.0)
            self._state.purge_stale_trace_runs(stale_window)
        except Exception:
            logger.warning("purge_stale_trace_runs failed", exc_info=True)

        try:
            active_keys = {
                (issue, phase, run_id)
                for issue, phase, run_id in self._state.list_active_trace_runs()
            }
        except Exception:
            logger.warning("list_active_trace_runs failed", exc_info=True)
            active_keys = set()

        count = 0
        for run_dir in self._iter_run_dirs(traces_root):
            if (run_dir / "summary.json").exists():
                continue
            if (run_dir / ".finalized_orphan").exists():
                continue
            issue_number, phase, run_id = self._parse_dir_parts(run_dir)
            if (issue_number, phase, run_id) in active_keys:
                # Still in flight — leave alone
                continue

            subprocess_files = list(run_dir.glob("subprocess-*.json"))
            if not subprocess_files:
                continue

            try:
                from trace_rollup import write_phase_rollup  # noqa: PLC0415

                summary = write_phase_rollup(
                    config=self._config,
                    issue_number=issue_number,
                    phase=phase,
                    run_id=run_id,
                )
                if summary is not None:
                    # Mark as crashed since the run never called end_trace_run
                    crashed_summary = summary.model_copy(update={"crashed": True})
                    summary_path = run_dir / "summary.json"
                    summary_path.write_text(
                        crashed_summary.model_dump_json(indent=2), encoding="utf-8"
                    )
            except Exception:
                logger.warning(
                    "Failed to finalize orphan run %s", run_dir, exc_info=True
                )
                continue

            (run_dir / ".finalized_orphan").touch()
            count += 1
            logger.info(
                "Finalized orphan run-%d for issue #%d (%s)",
                run_id,
                issue_number,
                phase,
            )
        return count

    # ------------------------------------------------------------------
    # Stage 2: Aggregate summaries into LifetimeStats
    # ------------------------------------------------------------------

    def _stage_aggregate(self, traces_root: Path) -> int:
        count = 0
        for run_dir in self._iter_run_dirs(traces_root):
            if (run_dir / ".aggregated").exists():
                continue

            summary_path = run_dir / "summary.json"
            if not summary_path.exists():
                continue

            try:
                summary = TraceSummary.model_validate_json(
                    summary_path.read_text(encoding="utf-8")
                )
            except Exception:
                logger.warning(
                    "Skipping malformed summary at %s", summary_path, exc_info=True
                )
                continue

            self._roll_into_stats(summary)
            (run_dir / ".aggregated").touch()
            count += 1
            issue_number, phase, run_id = self._parse_dir_parts(run_dir)
            logger.info(
                "Aggregated trace run-%d for issue #%d (%s)",
                run_id,
                issue_number,
                phase,
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
        for run_dir in self._iter_run_dirs(traces_root):
            if not (run_dir / ".aggregated").exists():
                continue
            if (run_dir / ".synced").exists():
                continue

            summary_path = run_dir / "summary.json"
            if not summary_path.exists():
                (run_dir / ".synced").touch()
                count += 1
                continue

            try:
                summary = TraceSummary.model_validate_json(
                    summary_path.read_text(encoding="utf-8")
                )
            except Exception:
                logger.warning(
                    "Skipping malformed summary at %s", summary_path, exc_info=True
                )
                (run_dir / ".synced").touch()
                continue

            if self._hindsight is not None:
                await self._retain_retrospective(summary)
                await self._retain_tracing_insights(summary)

            (run_dir / ".synced").touch()
            count += 1
            logger.info(
                "Synced trace insights for issue #%d (%s) run-%d",
                summary.issue_number,
                summary.phase,
                summary.run_id,
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
                "run_id": str(summary.run_id),
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
                "run_id": str(summary.run_id),
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
        crash_note = " [CRASHED]" if s.crashed else ""

        lines = [
            f"Issue #{s.issue_number} ({s.phase} phase run-{s.run_id}){crash_note}: "
            f"{s.spans.total_turns} turns, "
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
            f"Trace data for issue #{s.issue_number} ({s.phase} run-{s.run_id}): "
            f"{s.spans.total_spans} spans, "
            f"{s.tokens.prompt_tokens + s.tokens.completion_tokens} total tokens, "
            f"{s.tools.total_invocations} tool calls, "
            f"{s.skills.total_skills} skill invocations, "
            f"{s.skills.total_subagents} subagent spawns."
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _iter_run_dirs(self, traces_root: Path) -> list[Path]:
        """Return all <issue>/<phase>/run-N/ directories under traces_root."""
        dirs = []
        for issue_dir in sorted(traces_root.iterdir()):
            if not issue_dir.is_dir() or not issue_dir.name.isdigit():
                continue
            for phase_dir in sorted(issue_dir.iterdir()):
                if not phase_dir.is_dir():
                    continue
                if phase_dir.name not in _KNOWN_PHASES:
                    continue
                for run_dir in sorted(phase_dir.iterdir()):
                    if run_dir.is_dir() and run_dir.name.startswith("run-"):
                        dirs.append(run_dir)
        return dirs

    def _parse_dir_parts(self, run_dir: Path) -> tuple[int, str, int]:
        """Extract (issue_number, phase, run_id) from a run-N directory path."""
        run_id = int(run_dir.name.removeprefix("run-"))
        phase = run_dir.parent.name
        issue_number = int(run_dir.parent.parent.name)
        return issue_number, phase, run_id
