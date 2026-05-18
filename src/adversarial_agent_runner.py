"""Subprocess-CLI adapter that satisfies the AgentLike Protocol.

The earlier-adversarial pipeline (AssumptionSurfacer, PlanCouncil,
DiscoveryCouncil, ShapeChallenger, ShapeExpertCouncil, SpecACGenerator,
SpecJudge) each take an agent satisfying the two-string-in,
JSON-string-out contract in :mod:`src.adversarial_agents`. This adapter
wraps the existing one-shot CLI invocation path
(:func:`agent_cli.build_lightweight_command` + ``SubprocessRunner``) so
the adversarial pipeline can drive real ``claude -p`` (or
``codex``/``gemini``/``pi``) subprocesses in production.

Design notes
------------

* The Claude/Codex/Gemini/Pi CLIs invoked through
  ``build_lightweight_command`` accept a single prompt argument; there
  is no separate ``system`` slot in the lightweight (non-streaming)
  path. We therefore concatenate ``system_prompt`` + ``user_message``
  with explicit section headers. The adversarial-stage system prompts
  already include the JSON output contract verbatim, so this preserves
  the contract end-to-end.

* The adapter returns raw stdout. Callers (AssumptionSurfacer, etc.)
  are responsible for JSON-parsing and turning malformed replies into
  soft outputs per the adversarial-pipeline contract.

* Dark-factory contract: ``CreditExhaustedError`` is reraised so the
  outer loop pauses on billing signal rather than burning attempt
  budget. ``reraise_on_credit_or_bug`` catches likely-bug exceptions
  (TypeError, KeyError, etc.) so they surface in logs instead of
  silently becoming an empty findings list.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agent_cli import AgentTool, build_lightweight_command
from exception_classify import reraise_on_credit_or_bug
from subprocess_util import (
    CreditExhaustedError,
    is_credit_exhaustion,
    make_clean_env,
    parse_credit_resume_time,
)

if TYPE_CHECKING:
    from config import Credentials
    from execution import SubprocessRunner

logger = logging.getLogger("hydraflow.adversarial_agent_runner")


@dataclass
class SubprocessAgentRunner:
    """Subprocess-CLI adapter satisfying the AgentLike Protocol.

    Spawns a one-shot CLI process per ``run`` call. Stateless — a
    single instance is safe to share across all adversarial-stage
    agents (the per-call ``system_prompt`` is what differentiates a
    surfacer from a council voter).

    Attributes
    ----------
    runner:
        The :class:`execution.SubprocessRunner` used to invoke the CLI.
        Production paths inject the Docker runner; tests inject fakes.
    tool:
        Which agent CLI to invoke. Defaults to ``"claude"``.
    model:
        Model identifier passed to the CLI. Defaults to Claude Haiku —
        the adversarial stages are critic-style and benefit from a
        fast, low-cost model.
    timeout:
        Per-call subprocess timeout in seconds. The adversarial stages
        are one-shot critics, not multi-turn agents, so the default is
        deliberately shorter than the planner/implement timeout.
    credentials:
        Optional :class:`config.Credentials`; when provided, the
        ``gh_token`` is injected into the subprocess env via
        :func:`make_clean_env`.
    """

    runner: SubprocessRunner
    tool: AgentTool = "claude"
    model: str = "claude-haiku-4-5-20251001"
    timeout: float = 180.0
    credentials: Credentials | None = None

    async def run(self, system_prompt: str, user_message: str) -> str:
        """Send the prompts to the CLI and return raw stdout.

        Concatenates ``system_prompt`` + ``user_message`` into a single
        prompt with explicit section headers (the lightweight CLI path
        has no separate system slot). The downstream caller JSON-parses
        the result.

        Raises
        ------
        CreditExhaustedError:
            When the CLI output indicates API credit exhaustion, so the
            outer loop can pause on the billing signal rather than burn
            attempt budget.
        Exception:
            Any other ``except Exception`` is filtered through
            :func:`reraise_on_credit_or_bug` so likely bugs (TypeError,
            KeyError, etc.) surface in logs instead of becoming a soft
            empty reply.
        """
        prompt = self._compose_prompt(system_prompt, user_message)
        cmd, cmd_input = build_lightweight_command(
            tool=self.tool, model=self.model, prompt=prompt
        )
        gh_token = self.credentials.gh_token if self.credentials is not None else ""
        env = make_clean_env(gh_token)

        try:
            result = await self.runner.run_simple(
                cmd,
                env=env,
                input=cmd_input,
                timeout=self.timeout,
            )
        except Exception as exc:
            # Dark-factory contract: bug + credit exceptions must
            # propagate so the outer loop can react. Everything else
            # (TimeoutError, OSError, transient network blips) becomes
            # a soft empty reply so the adversarial stage doesn't crash
            # the host pipeline.
            reraise_on_credit_or_bug(exc)
            logger.warning(
                "SubprocessAgentRunner(%s) subprocess failed: %s", self.tool, exc
            )
            return ""

        stdout = result.stdout or ""
        stderr = result.stderr or ""

        # Credit-exhaustion detection: the lightweight CLI path can
        # surface "usage limit reached" in stdout or stderr without
        # raising. Convert to CreditExhaustedError so the outer loop
        # can pause on the billing signal.
        for blob in (stdout, stderr):
            if blob and is_credit_exhaustion(blob):
                resume_at = parse_credit_resume_time(blob)
                raise CreditExhaustedError(
                    f"{self.tool} CLI signaled credit exhaustion",
                    resume_at=resume_at,
                )

        if result.returncode != 0:
            # The CLI exited nonzero but it wasn't a credit-exhaustion
            # signal. Log + soft-fail: the AgentLike contract returns a
            # string and the caller will treat empty/non-JSON as an
            # empty findings list. This prevents one flaky voter from
            # crashing the whole adversarial stage.
            logger.warning(
                "SubprocessAgentRunner(%s) returned rc=%d: %s",
                self.tool,
                result.returncode,
                stderr[:200],
            )
            return ""

        return stdout

    @staticmethod
    def _compose_prompt(system_prompt: str, user_message: str) -> str:
        """Concatenate system + user into a single CLI prompt.

        Section headers are explicit so the model treats the system
        block as standing instructions and the user block as the
        message to evaluate. Matches the lightweight CLI's
        single-prompt convention used elsewhere
        (``term_proposer_runtime.ClaudeCLIClient``,
        ``adr_reviewer``, ``transcript_summarizer``).
        """
        return (
            "# System instructions\n"
            f"{system_prompt}\n\n"
            "# User message\n"
            f"{user_message}\n"
        )
