"""AutoAgentRunner — Claude Code subprocess spawn for AutoAgentPreflightLoop.

Spec §3.1 / ADR-0050. Inherits BaseSubprocessRunner[PreflightSpawn] for
the load-bearing conventions (auth-retry, reraise_on_credit_or_bug,
telemetry, never-raises). Auto-agent-specific concerns:

- tool restrictions (`--disallowedTools=WebFetch` per spec §5.2)
- backend-mismatch warning when implementation_tool != "claude"
- wall-clock cap override (auto_agent_wall_clock_cap_s)
- result shape: PreflightSpawn (with output_text + tokens fields)
"""

from __future__ import annotations

import logging
from pathlib import Path

from agent_cli import build_agent_command
from preflight.agent import PreflightSpawn
from runners.base_subprocess_runner import (
    BaseSubprocessRunner,
    SpawnOutcome,
    _coerce_int,
)

logger = logging.getLogger("hydraflow.preflight.auto_agent_runner")


# Spec §5.2 — tools the auto-agent must NOT use.
#
# `WebFetch` is disabled because the auto-agent should reason from the
# context the loop gathered (wiki + sentry + recent commits + escalation
# context), not chase arbitrary external URLs that could leak issue
# content or pull in malicious instructions.
_AUTO_AGENT_DISALLOWED_TOOLS = "WebFetch"


class AutoAgentRunner(BaseSubprocessRunner[PreflightSpawn]):
    """Spawns a Claude Code subprocess for one auto-agent attempt.

    One instance per attempt; lifetime is bounded by `run()`.
    """

    def _telemetry_source(self) -> str:
        return "auto_agent_preflight"

    def _build_command(self, prompt: str, worktree: Path) -> list[str]:
        return build_agent_command(
            tool=self._config.implementation_tool,
            model=self._config.model,
            disallowed_tools=_AUTO_AGENT_DISALLOWED_TOOLS,
        )

    def _default_timeout_s(self) -> int:
        return int(
            self._config.auto_agent_wall_clock_cap_s or self._config.agent_timeout
        )

    def _pre_spawn_hook(self, prompt: str) -> None:
        # `--disallowedTools=WebFetch` is silently dropped by build_agent_command
        # for codex/gemini backends. Warn so the operator knows the CLI-level
        # guard isn't active for that backend — the path-level honor-system
        # in the prompt envelope is the only remaining restriction layer.
        if self._config.implementation_tool != "claude":
            logger.warning(
                "auto-agent: --disallowedTools is only enforced for the claude "
                "backend; current implementation_tool=%s — WebFetch restriction "
                "is honor-system + post-hoc CI for this run",
                self._config.implementation_tool,
            )

    def _make_result(self, outcome: SpawnOutcome) -> PreflightSpawn:
        return PreflightSpawn(
            process=None,
            output_text=outcome.transcript,
            cost_usd=outcome.cost_usd,
            tokens=_coerce_int(outcome.usage_stats.get("total_tokens")),
            crashed=outcome.crashed,
            prompt_hash=outcome.prompt_hash,
        )
