"""PreflightAgent — spawns AutoAgentRunner + caps + cost telemetry.

Spec §3.3, §5.1.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Any

from preflight.context import PreflightContext
from preflight.decision import PreflightResult
from preflight.runner import parse_agent_response, render_blocks, render_prompt

logger = logging.getLogger("hydraflow.preflight.agent")


@dataclass
class PreflightAgentDeps:
    persona: str
    cost_cap_usd: float | None
    wall_clock_cap_s: int | None
    spawn_fn: (
        Any  # callable(prompt, worktree_path) -> PreflightSpawn (see test for shape)
    )


@dataclass(frozen=True)
class PreflightSpawn:
    """Returned by spawn_fn — represents the running subprocess + cost meter."""

    process: Any  # subprocess.Process or asyncio task
    output_text: str  # populated after wait()
    cost_usd: float
    tokens: int
    crashed: bool
    prompt_hash: str = ""  # hex prefix; populated by spawn_fn for audit traceability


async def run_preflight(
    *,
    context: PreflightContext,
    repo_slug: str,
    worktree_path: str,
    deps: PreflightAgentDeps,
) -> PreflightResult:
    """Run one auto-agent attempt; return the result."""
    blocks = render_blocks(
        issue_comments=context.issue_comments,
        escalation_context=context.escalation_context,
        wiki_excerpts=context.wiki_excerpts,
        sentry_events=context.sentry_events,
        recent_commits=context.recent_commits,
        prior_attempts=context.prior_attempts,
    )
    prompt = render_prompt(
        sub_label=context.sub_label,
        persona=deps.persona,
        issue_number=context.issue_number,
        repo_slug=repo_slug,
        worktree_path=worktree_path,
        issue_body=context.issue_body,
        **blocks,
    )

    prompt_hash = hash_prompt(prompt)
    start = time.monotonic()
    try:
        spawn = await deps.spawn_fn(prompt=prompt, worktree_path=worktree_path)
    except Exception as exc:
        logger.exception("PreflightAgent spawn failed: %s", exc)
        return PreflightResult(
            status="fatal",
            pr_url=None,
            diagnosis=f"Subprocess spawn failed: {exc}",
            cost_usd=0.0,
            wall_clock_s=time.monotonic() - start,
            tokens=0,
            prompt_hash=prompt_hash,
        )

    wall_s = time.monotonic() - start
    # Prefer the hash recorded by spawn_fn when present (some spawn impls hash
    # the post-redaction prompt the subprocess actually saw); fall back to our
    # locally-computed hash so the audit always carries a value.
    spawn_hash = spawn.prompt_hash or prompt_hash

    if spawn.crashed:
        return PreflightResult(
            status="fatal",
            pr_url=None,
            diagnosis=f"Subprocess crashed. Partial output: {spawn.output_text[-1000:]}",
            cost_usd=spawn.cost_usd,
            wall_clock_s=wall_s,
            tokens=spawn.tokens,
            prompt_hash=spawn_hash,
        )

    # Cap checks (post-hoc — caps were enforced inside spawn_fn or by watchers)
    if deps.cost_cap_usd is not None and spawn.cost_usd > deps.cost_cap_usd:
        return PreflightResult(
            status="cost_exceeded",
            pr_url=None,
            diagnosis=(
                f"Cost cap (${deps.cost_cap_usd:.2f}) hit. "
                f"Partial output: {spawn.output_text[-1000:]}"
            ),
            cost_usd=spawn.cost_usd,
            wall_clock_s=wall_s,
            tokens=spawn.tokens,
            prompt_hash=spawn_hash,
        )
    if deps.wall_clock_cap_s is not None and wall_s > deps.wall_clock_cap_s:
        return PreflightResult(
            status="timeout",
            pr_url=None,
            diagnosis=(
                f"Wall-clock cap ({deps.wall_clock_cap_s}s) hit. "
                f"Partial output: {spawn.output_text[-1000:]}"
            ),
            cost_usd=spawn.cost_usd,
            wall_clock_s=wall_s,
            tokens=spawn.tokens,
            prompt_hash=spawn_hash,
        )

    parsed = parse_agent_response(spawn.output_text)
    raw_status: str = parsed["status"] or "needs_human"
    status = raw_status if raw_status in {"resolved", "needs_human"} else "needs_human"
    pr_url = parsed["pr_url"]
    # Agent claimed "resolved" but produced no PR — that's a PR-creation failure
    # (spec §2.2: pr_failed status). Demote so the loop applies the right label
    # set instead of treating the missing PR as a successful resolve.
    if status == "resolved" and not pr_url:
        status = "pr_failed"
    return PreflightResult(
        status=status,
        pr_url=pr_url,
        diagnosis=parsed["diagnosis"] or "",
        cost_usd=spawn.cost_usd,
        wall_clock_s=wall_s,
        tokens=spawn.tokens,
        prompt_hash=spawn_hash,
    )


def hash_prompt(prompt: str) -> str:
    return "sha256:" + hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
