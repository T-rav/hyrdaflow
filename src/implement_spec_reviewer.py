"""Spec-compliance review for ImplementPhase (ADR-0063 W5).

Runs after a failed implementation attempt to capture *why* the agent's
output diverged from the spec, so the next attempt can be fed concrete
gaps instead of just "your last try failed."

The pattern mirrors ``superpowers:subagent-driven-development``'s two-stage
review (spec-compliance first, code-quality second). The implementer subagent
is dispatched by ``ImplementPhase``; the spec-compliance reviewer is a
*separate* subagent that reads the spec + the actual diff and reports either
``COMPLIANT`` or a list of specific gaps. Gaps are then persisted via
``WorkerResultMeta.spec_review_gaps`` and prepended to the next attempt's
``prior_failure`` context.

Two failure modes this addresses (ADR-0063):

1. **Zero-diff branches.** Implementation produced no diff (or no commits).
   The reviewer reports "implementation produced no changes for the requested
   feature" as the gap, so the next attempt sees an explicit anchor — not
   just the prior error string ``"No commits found on branch"`` which is
   uninformative.

2. **Attempt-cap reaches.** Multiple attempts re-implement without learning
   from prior misses. With spec gaps in ``prior_failure``, the next attempt
   sees what the reviewer thought was missing, not just the agent's error log.

All subagent dispatches go through Claude Code's subagent dispatch interface
(see ``docs/wiki/dark-factory.md`` — no direct Anthropic SDK calls).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

logger = logging.getLogger("hydraflow.implement_spec_reviewer")


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_JSON_BLOCK_RE = re.compile(r"(\{.*\})", re.DOTALL)


def _extract_json_block(payload: str) -> str:
    """Extract the JSON object from an agent transcript.

    Subagent responses can contain prose, fenced code blocks, or stream
    events. Prefer fenced JSON, fall back to the greediest ``{...}`` block,
    and finally return the raw payload (which will fail to parse but at
    least surfaces what the agent actually said).
    """
    m = _JSON_FENCE_RE.search(payload)
    if m:
        return m.group(1)
    m = _JSON_BLOCK_RE.search(payload)
    if m:
        return m.group(1)
    return payload


@dataclass
class SpecReviewInput:
    """Inputs for one spec-compliance review call."""

    issue_number: int
    issue_title: str
    issue_body: str
    plan: str
    diff: str
    """Unified diff of ``branch`` against the configured base branch.

    May be empty — that itself is a finding (the reviewer should report a
    zero-diff gap rather than ``COMPLIANT``).
    """
    commits: int
    """Number of commits the implementation produced on the branch."""
    error: str
    """The implementation runner's error string (or empty on success-with-no-diff).
    Used as a hint for the reviewer but not authoritative — the diff is the truth."""


@dataclass
class SpecReviewResult:
    """Verdict from one spec-compliance review."""

    compliant: bool
    """True when the reviewer found no material gaps. False = at least one gap."""
    gaps: list[str] = field(default_factory=list)
    """Specific findings (missing requirements, wrong feature, zero diff, etc.).

    Each entry is human-readable; the next attempt sees these prepended to
    ``prior_failure`` so the agent has an explicit anchor.
    """
    reasoning: str = ""
    """Brief explanation from the reviewer, included in the comment posted to
    the issue when gaps exist."""
    degraded: bool = False
    """True when the reviewer subagent itself failed (runner error, parse
    error). In degraded mode ``compliant=True`` and ``gaps=[]`` so the
    fallback behavior matches the pre-W5 flow."""


class SpecComplianceReviewer(Protocol):
    """Callable interface ImplementPhase consumes.

    Production wiring (``service_registry.py``) provides a subagent-dispatch
    implementation. Tests substitute a synchronous stub that returns a fixed
    ``SpecReviewResult``.
    """

    async def review(self, inp: SpecReviewInput) -> SpecReviewResult: ...


class SubagentRunnerProtocol(Protocol):
    """The minimal subagent dispatch the default reviewer needs.

    Compatible with the reviewer-runner adapter used by ``review_advisor.py``.
    """

    async def run(
        self,
        *,
        model: str,
        subagent_type: str,
        prompt: str,
    ) -> str: ...


# Cap the diff fed to the reviewer. Bigger diffs are uncommon in failed
# attempts (failed attempts often produce small or zero diffs); keep the
# prompt focused and predictable.
_DEFAULT_MAX_DIFF_CHARS = 12_000


def _consume_mockworld_spec_review_script(
    reviewer, issue_number: int
) -> SpecReviewResult | None:
    """Return a scripted SpecReviewResult if MockWorld scripting is active.

    Returns ``None`` when the reviewer has no ``_mockworld_fake_llm``
    sentinel or no script is queued for *issue_number*. Used by
    :meth:`DefaultSpecComplianceReviewer.review` to skip the subagent
    dispatch when sandbox scenarios drive the ADR-0063 W5 two-stage
    review feedback path.
    """
    fake_llm = getattr(reviewer, "_mockworld_fake_llm", None)
    if fake_llm is None or not getattr(fake_llm, "_is_fake_adapter", False):
        return None
    if not hasattr(fake_llm, "pop_implement_spec_review_script"):
        return None
    scripted = fake_llm.pop_implement_spec_review_script(issue_number)
    if scripted is None:
        return None
    return SpecReviewResult(
        compliant=scripted.compliant,
        gaps=list(scripted.gaps),
        reasoning=scripted.reasoning,
        degraded=False,
    )


def build_spec_review_prompt(
    inp: SpecReviewInput, *, max_diff_chars: int = _DEFAULT_MAX_DIFF_CHARS
) -> str:
    """Compose the spec-compliance reviewer prompt.

    The structure mirrors ``superpowers:subagent-driven-development``'s
    ``spec-reviewer-prompt.md``: state what was requested, state what was
    produced, demand independent verification, ask for a JSON verdict.
    """
    diff_block = inp.diff[:max_diff_chars] if inp.diff else ""
    if not diff_block:
        diff_block = (
            "(no diff — branch produced zero changes from the base branch; "
            "this is itself a finding)"
        )
    plan_block = inp.plan.strip() if inp.plan else "(no plan was attached)"
    body_block = inp.issue_body.strip() if inp.issue_body else "(no body)"

    return f"""You are a spec-compliance reviewer for an autonomous coding agent.

Your job is to verify whether the implementation matches what was requested,
*by reading the diff*. Do not trust prose claims; the diff is the truth.

## Issue #{inp.issue_number}: {inp.issue_title}

{body_block}

## Implementation plan

{plan_block}

## Implementation result

- commits produced: {inp.commits}
- runner error: {inp.error or "(none)"}

## Diff (truncated to {max_diff_chars} chars)

```diff
{diff_block}
```

## Your job

Compare the diff to the requested work. Report gaps in three categories:

1. **Missing requirements** — things the spec asked for that the diff does
   not implement (or only stubs out).
2. **Wrong feature** — the diff implements something else, or interprets the
   spec wrongly.
3. **Zero/no-op work** — the diff is empty, only touches comments, or only
   moves text around without delivering the requested behavior.

If the diff genuinely covers the spec, report compliant.

## Response format — JSON only

Respond with a single JSON object matching this schema. No prose outside the JSON.

```json
{{
  "compliant": true | false,
  "gaps": ["short specific gap 1", "short specific gap 2"],
  "reasoning": "1-3 sentences explaining the verdict"
}}
```

If ``compliant`` is true, ``gaps`` MUST be an empty list. If ``compliant`` is
false, ``gaps`` MUST contain at least one entry.
"""


class DefaultSpecComplianceReviewer:
    """Default reviewer that dispatches a Claude Code subagent.

    Used in production. Failures (runner errors, parse errors) degrade to
    ``compliant=True, gaps=[], degraded=True`` so the pre-W5 flow continues
    unchanged — we never block on a flaky reviewer.
    """

    def __init__(
        self,
        runner: SubagentRunnerProtocol,
        *,
        model: str = "sonnet",
        subagent_type: str = "general-purpose",
        max_diff_chars: int = _DEFAULT_MAX_DIFF_CHARS,
    ) -> None:
        self._runner = runner
        self._model = model
        self._subagent_type = subagent_type
        self._max_diff_chars = max_diff_chars

    async def review(self, inp: SpecReviewInput) -> SpecReviewResult:
        scripted = _consume_mockworld_spec_review_script(self, inp.issue_number)
        if scripted is not None:
            return scripted

        prompt = build_spec_review_prompt(inp, max_diff_chars=self._max_diff_chars)
        try:
            payload = await self._runner.run(
                model=self._model,
                subagent_type=self._subagent_type,
                prompt=prompt,
            )
        except Exception as exc:
            # Auth/credit/likely-bug exceptions must propagate per
            # docs/wiki/dark-factory.md §2.2 — they signal infrastructure
            # state the orchestrator needs to see, not transient reviewer
            # failures.
            from exception_classify import (  # noqa: PLC0415
                reraise_on_credit_or_bug,
            )

            try:
                reraise_on_credit_or_bug(exc)
            except BaseException:
                raise
            logger.warning(
                "Spec-compliance reviewer subagent failed for issue #%d: %r",
                inp.issue_number,
                exc,
            )
            return SpecReviewResult(compliant=True, gaps=[], degraded=True)

        try:
            data = json.loads(_extract_json_block(payload))
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning(
                "Spec-compliance reviewer payload not JSON for issue #%d: %r",
                inp.issue_number,
                exc,
            )
            return SpecReviewResult(compliant=True, gaps=[], degraded=True)

        if not isinstance(data, dict):
            return SpecReviewResult(compliant=True, gaps=[], degraded=True)

        compliant = bool(data.get("compliant", True))
        gaps_raw = data.get("gaps", []) or []
        if not isinstance(gaps_raw, list):
            gaps_raw = []
        gaps: list[str] = [str(g) for g in gaps_raw if str(g).strip()]
        reasoning = str(data.get("reasoning", "") or "")

        # Schema integrity: if the reviewer says "compliant" but lists gaps,
        # trust the gaps (the JSON was generated by an LLM; gaps win).
        if gaps:
            compliant = False
        return SpecReviewResult(
            compliant=compliant, gaps=gaps, reasoning=reasoning, degraded=False
        )


def format_gaps_for_prior_failure(gaps: list[str], reasoning: str = "") -> str:
    """Render gaps + reasoning into a text block for ``prior_failure``.

    The next implementation attempt sees this text under the "Prior Attempt
    Failure" section of its prompt (see ``agent._build_prompt_with_stats``).
    Kept compact — the surrounding prompt machinery already truncates.
    """
    if not gaps:
        return ""
    lines = ["Spec-compliance gaps from prior attempt:"]
    for g in gaps:
        lines.append(f"- {g}")
    if reasoning.strip():
        lines.append("")
        lines.append(f"Reviewer reasoning: {reasoning.strip()}")
    return "\n".join(lines)


class AgentSubagentRunnerAdapter:
    """Adapts an ``AgentRunner`` into the ``SubagentRunnerProtocol``.

    Production wiring uses ``AgentRunner._execute`` so the reviewer's
    subagent share the same subprocess plumbing, tracing context, and
    auth-retry behavior as the implementer itself. The runner is invoked
    in read-only mode (``Write,Edit,NotebookEdit`` disallowed) — the
    reviewer must never modify the codebase.
    """

    def __init__(self, agents, config) -> None:  # noqa: ANN001 — duck-typed
        self._agents = agents
        self._config = config

    async def run(self, *, model: str, subagent_type: str, prompt: str) -> str:
        from agent_cli import build_agent_command  # noqa: PLC0415

        _ = subagent_type  # subagent_type isn't surfaced through _execute today
        cmd = build_agent_command(
            tool=self._config.review_tool,
            model=model,
            disallowed_tools="Write,Edit,NotebookEdit",
        )
        # Use the executor's public AgentPort entry point (forwards to
        # _execute under the hood). cwd is repo_root so the reviewer can
        # read source for cross-references.
        return await self._agents.execute(
            cmd,
            prompt,
            self._config.repo_root,
            {"source": "implement_spec_reviewer"},
        )


async def compute_branch_diff(
    workspace: Path,
    branch: str,
    base_branch: str,
    *,
    runner_run_simple,  # noqa: ANN001 — duck-typed run_simple callable
    timeout: int = 30,
) -> str:
    """Compute the unified diff of ``branch`` vs ``base_branch`` in a worktree.

    Uses ``git diff`` (not ``git log -p``) so the reviewer sees the *aggregate*
    change set, not per-commit history. Returns empty string on any error or
    when there is no diff — the reviewer treats empty diff as a finding.
    """
    try:
        result = await runner_run_simple(
            [
                "git",
                "diff",
                f"origin/{base_branch}...{branch}",
            ],
            cwd=str(workspace),
            timeout=timeout,
        )
    except (TimeoutError, FileNotFoundError, OSError):
        return ""
    return getattr(result, "stdout", "") or ""
