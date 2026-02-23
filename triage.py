"""Triage agent — evaluates issue readiness before promoting to planning."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import TYPE_CHECKING

from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from execution import get_default_runner
from models import GitHubIssue, TriageResult, TriageStatus
from runner_utils import stream_claude_process, terminate_processes
from subprocess_util import CreditExhaustedError

if TYPE_CHECKING:
    from execution import SubprocessRunner

logger = logging.getLogger("hydraflow.triage")

# Minimum thresholds for issue readiness (fast pre-filter)
_MIN_TITLE_LENGTH = 10
_MIN_BODY_LENGTH = 50


def _coerce_reasons(raw: object) -> list[str]:
    """Normalise the ``reasons`` field from an LLM JSON response.

    - List → returned as-is (normal case).
    - Non-empty string → wrapped in a single-element list so the reason
      is preserved in HITL comments rather than silently dropped.
    - Anything else (None, int, empty string, …) → empty list.
    """
    if isinstance(raw, list):
        return list(raw)
    if isinstance(raw, str) and raw.strip():
        return [raw]
    return []


def _coerce_ready(raw: object) -> bool:
    """Normalise the ``ready`` field from an LLM JSON response.

    - bool → returned as-is (normal case).
    - String → ``False`` for ``"false"``/``"no"``/``"0"``/empty, else ``True``.
      Prevents ``bool("false") == True`` silently passing rejected issues.
    - Anything else → standard bool coercion.
    """
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.strip().lower() not in ("false", "no", "0", "")
    return bool(raw)


class TriageRunner:
    """Evaluates whether a GitHub issue has enough context for planning.

    Uses an LLM to assess issue clarity, specificity, actionability, and scope.
    Basic length checks remain as a fast pre-filter before the LLM call.

    Publishes ``TRIAGE_UPDATE`` events so the dashboard can show an
    active worker in the FIND column.
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        runner: SubprocessRunner | None = None,
    ) -> None:
        self._config = config
        self._bus = event_bus
        self._active_procs: set[asyncio.subprocess.Process] = set()
        self._runner = runner or get_default_runner()

    async def evaluate(
        self,
        issue: GitHubIssue,
        worker_id: int = 0,
    ) -> TriageResult:
        """Evaluate *issue* for readiness.

        Returns a :class:`TriageResult` indicating whether the issue
        has enough information to proceed to planning.
        """
        await self._emit_status(issue.number, worker_id, TriageStatus.EVALUATING)
        await self._emit_transcript(
            issue.number, f"Evaluating issue #{issue.number}: {issue.title}"
        )

        if self._config.dry_run:
            logger.info("[dry-run] Would evaluate issue #%d", issue.number)
            await self._emit_transcript(issue.number, "[dry-run] Skipping evaluation")
            await self._emit_status(issue.number, worker_id, TriageStatus.DONE)
            return TriageResult(issue_number=issue.number, ready=True)

        # --- Fast pre-filter: basic length checks ---
        reasons: list[str] = []
        title_len = len(issue.title.strip()) if issue.title else 0
        body_len = len(issue.body.strip()) if issue.body else 0
        await self._emit_transcript(
            issue.number,
            f"Title length: {title_len} chars (min {_MIN_TITLE_LENGTH}) | "
            f"Body length: {body_len} chars (min {_MIN_BODY_LENGTH})",
        )

        if not issue.title or title_len < _MIN_TITLE_LENGTH:
            reasons.append(
                f"Title is too short (minimum {_MIN_TITLE_LENGTH} characters)"
            )
        if not issue.body or body_len < _MIN_BODY_LENGTH:
            reasons.append(
                f"Body is too short or empty "
                f"(minimum {_MIN_BODY_LENGTH} characters of description)"
            )

        if reasons:
            result = TriageResult(
                issue_number=issue.number, ready=False, reasons=reasons
            )
            await self._emit_transcript(
                issue.number,
                "Issue needs more information:\n"
                + "\n".join(f"- {r}" for r in reasons),
            )
            await self._emit_status(issue.number, worker_id, TriageStatus.DONE)
            logger.info(
                "Issue #%d failed pre-filter: reasons=%s",
                issue.number,
                reasons,
            )
            return result

        # --- LLM evaluation ---
        await self._emit_transcript(
            issue.number,
            "Issue passes pre-filter, running LLM quality evaluation...",
        )

        try:
            result = await self._evaluate_with_llm(issue)
        except CreditExhaustedError:
            raise
        except Exception as exc:
            logger.warning(
                "LLM evaluation failed for issue #%d: %s",
                issue.number,
                exc,
            )
            result = TriageResult(
                issue_number=issue.number,
                ready=False,
                reasons=[f"LLM evaluation error: {exc}"],
            )

        if result.ready:
            await self._emit_transcript(
                issue.number, "Issue is ready — promoting to planning"
            )
        else:
            await self._emit_transcript(
                issue.number,
                "Issue needs more information:\n"
                + "\n".join(f"- {r}" for r in result.reasons),
            )

        await self._emit_status(issue.number, worker_id, TriageStatus.DONE)
        logger.info(
            "Issue #%d evaluated: ready=%s reasons=%s",
            issue.number,
            result.ready,
            result.reasons or "none",
        )
        return result

    def _build_command(self) -> list[str]:
        """Construct the ``claude`` CLI invocation for triage evaluation."""
        return [
            "claude",
            "-p",
            "--output-format",
            "stream-json",
            "--model",
            self._config.triage_model,
            "--verbose",
            "--permission-mode",
            "bypassPermissions",
            "--max-turns",
            "1",
        ]

    @staticmethod
    def _build_prompt(issue: GitHubIssue) -> str:
        """Build the triage evaluation prompt."""
        body = (issue.body or "")[:5000]
        return f"""You are a triage agent evaluating whether a GitHub issue has enough detail for an implementation planning agent to succeed.

## Issue #{issue.number}

**Title:** {issue.title}

**Body:**
{body}

## Evaluation Criteria

Evaluate the issue against these four criteria:

1. **Clarity**: Is the issue clearly written? Can an engineer understand what needs to happen?
2. **Specificity**: Does it describe a concrete problem or feature, not a vague wish?
3. **Actionability**: Is there enough context to start planning? (expected behavior, affected area, reproduction steps for bugs)
4. **Scope**: Is it a single, bounded unit of work? (not an unstructured epic or multiple unrelated requests)

## Instructions

- If ALL criteria are met, return `"ready": true`
- If ANY criterion fails, return `"ready": false` with specific, helpful feedback
- Be specific in your reasons (e.g., "Missing expected vs actual behavior" not just "lacks detail")
- Err on the side of passing well-written issues through — only reject clearly insufficient ones

Return ONLY a JSON object in this exact format, with no other text:

```json
{{"ready": true, "reasons": []}}
```

or

```json
{{"ready": false, "reasons": ["Specific reason 1", "Specific reason 2"]}}
```
"""

    async def _evaluate_with_llm(self, issue: GitHubIssue) -> TriageResult:
        """Run LLM evaluation and parse the verdict."""
        cmd = self._build_command()
        prompt = self._build_prompt(issue)

        transcript = await stream_claude_process(
            cmd=cmd,
            prompt=prompt,
            cwd=self._config.repo_root,
            active_procs=self._active_procs,
            event_bus=self._bus,
            event_data={"issue": issue.number, "source": "triage"},
            logger=logger,
            runner=self._runner,
        )

        result = self._parse_verdict(transcript, issue.number)
        if result is not None:
            return result

        # Fallback: could not parse LLM response
        return TriageResult(
            issue_number=issue.number,
            ready=False,
            reasons=["Could not parse LLM evaluation response"],
        )

    @staticmethod
    def _parse_verdict(transcript: str, issue_number: int) -> TriageResult | None:
        """Extract a JSON verdict from the LLM transcript.

        Tries multiple strategies:
        1. Direct ``json.loads`` on the full transcript
        2. Extract JSON from markdown code fences
        3. Regex to find a JSON object with ``"ready"`` key
        """
        # Strategy 1: direct parse
        try:
            data = json.loads(transcript.strip())
            if isinstance(data, dict) and "ready" in data:
                raw = data.get("reasons", [])
                return TriageResult(
                    issue_number=issue_number,
                    ready=_coerce_ready(data["ready"]),
                    reasons=_coerce_reasons(raw),
                )
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

        # Strategy 2: extract from markdown code fences
        fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", transcript, re.DOTALL)
        if fence_match:
            try:
                data = json.loads(fence_match.group(1).strip())
                if isinstance(data, dict) and "ready" in data:
                    raw = data.get("reasons", [])
                    return TriageResult(
                        issue_number=issue_number,
                        ready=_coerce_ready(data["ready"]),
                        reasons=_coerce_reasons(raw),
                    )
            except (json.JSONDecodeError, TypeError, ValueError):
                pass

        # Strategy 3: regex to find JSON object with "ready" key
        json_match = re.search(r"\{[^{}]*\"ready\"\s*:[^{}]*\}", transcript)
        if json_match:
            try:
                data = json.loads(json_match.group(0))
                if isinstance(data, dict) and "ready" in data:
                    raw = data.get("reasons", [])
                    return TriageResult(
                        issue_number=issue_number,
                        ready=_coerce_ready(data["ready"]),
                        reasons=_coerce_reasons(raw),
                    )
            except (json.JSONDecodeError, TypeError, ValueError):
                pass

        return None

    def terminate(self) -> None:
        """Kill all active triage subprocesses."""
        terminate_processes(self._active_procs)

    async def _emit_transcript(self, issue_number: int, line: str) -> None:
        """Publish a transcript line for the triage worker."""
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.TRANSCRIPT_LINE,
                data={
                    "issue": issue_number,
                    "line": line,
                    "source": "triage",
                },
            )
        )

    async def _emit_status(
        self, issue_number: int, worker_id: int, status: TriageStatus
    ) -> None:
        """Publish a triage status event."""
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.TRIAGE_UPDATE,
                data={
                    "issue": issue_number,
                    "worker": worker_id,
                    "status": status.value,
                    "role": "triage",
                },
            )
        )
