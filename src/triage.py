"""Triage agent — evaluates issue readiness before promoting to planning."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from agent_cli import build_agent_command
from base_runner import BaseRunner
from events import EventType, HydraFlowEvent
from exception_classify import reraise_on_credit_or_bug
from models import (
    EpicDecompResult,
    IssueType,
    NewIssueSpec,
    Task,
    TranscriptLinePayload,
    TriageResult,
    TriageStatus,
    TriageUpdatePayload,
)
from prompt_builder import PromptBuilder

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


class TriageRunner(BaseRunner):
    """Evaluates whether a GitHub issue has enough context for planning.

    Uses an LLM to assess issue clarity, specificity, actionability, and scope.
    Basic length checks remain as a fast pre-filter before the LLM call.

    Publishes ``TRIAGE_UPDATE`` events so the dashboard can show an
    active worker in the FIND column.
    """

    _log = logger

    async def evaluate(
        self,
        issue: Task,
        worker_id: int = 0,
    ) -> TriageResult:
        """Evaluate *issue* for readiness.

        Returns a :class:`TriageResult` indicating whether the issue
        has enough information to proceed to planning.
        """
        await self._emit_status(issue.id, worker_id, TriageStatus.EVALUATING)
        await self._emit_transcript(
            issue.id, f"Evaluating issue #{issue.id}: {issue.title}"
        )

        if self._config.dry_run:
            logger.info("[dry-run] Would evaluate issue #%d", issue.id)
            await self._emit_transcript(issue.id, "[dry-run] Skipping evaluation")
            await self._emit_status(issue.id, worker_id, TriageStatus.DONE)
            return TriageResult(issue_number=issue.id, ready=True)

        # --- Fast pre-filter: basic length checks ---
        reasons: list[str] = []
        title_len = len(issue.title.strip()) if issue.title else 0
        body_len = len(issue.body.strip()) if issue.body else 0
        await self._emit_transcript(
            issue.id,
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
            result = TriageResult(issue_number=issue.id, ready=False, reasons=reasons)
            await self._emit_transcript(
                issue.id,
                "Issue needs more information:\n"
                + "\n".join(f"- {r}" for r in reasons),
            )
            await self._emit_status(issue.id, worker_id, TriageStatus.DONE)
            logger.info(
                "Issue #%d failed pre-filter: reasons=%s",
                issue.id,
                reasons,
            )
            return result

        # --- LLM evaluation ---
        await self._emit_transcript(
            issue.id,
            "Issue passes pre-filter, running LLM quality evaluation...",
        )

        try:
            result = await self._evaluate_with_llm(issue)
        except RuntimeError:
            # Infrastructure errors (empty response, subprocess crash) should
            # propagate so the issue stays in the triage queue for retry
            # instead of being incorrectly escalated to HITL.
            raise
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning(
                "LLM evaluation failed for issue #%d: %s",
                issue.id,
                exc,
            )
            result = TriageResult(
                issue_number=issue.id,
                ready=False,
                reasons=[f"LLM evaluation error: {exc}"],
            )

        if result.ready:
            await self._emit_transcript(
                issue.id, "Issue is ready — promoting to planning"
            )
        else:
            await self._emit_transcript(
                issue.id,
                "Issue needs more information:\n"
                + "\n".join(f"- {r}" for r in result.reasons),
            )

        await self._emit_status(issue.id, worker_id, TriageStatus.DONE)
        logger.info(
            "Issue #%d evaluated: ready=%s reasons=%s",
            issue.id,
            result.ready,
            result.reasons or "none",
        )
        return result

    def _build_command(self, _worktree_path: Path | None = None) -> list[str]:
        """Construct the CLI invocation for triage evaluation.

        The *_worktree_path* parameter is accepted for API compatibility with
        ``BaseRunner._build_command`` but is unused — triage always runs
        against ``self._config.repo_root``.
        """
        return build_agent_command(
            tool=self._config.triage_tool,
            model=self._config.triage_model,
            max_turns=1,
        )

    @staticmethod
    def _build_prompt_with_stats(
        issue: Task, max_body: int = 5000
    ) -> tuple[str, dict[str, object]]:
        """Build the triage evaluation prompt and pruning stats."""
        builder = PromptBuilder()
        body = builder.add_context_section("Issue body", issue.body or "", max_body)
        prompt = f"""You are a triage agent evaluating a GitHub issue and enriching it if needed so a planning agent can succeed.

## Issue #{issue.id}

**Title:** {issue.title}

**Body:**
{body}

## Evaluation Criteria

Evaluate the issue against these four criteria:

1. **Clarity**: Is the issue clearly written? Can an engineer understand what needs to happen?
2. **Specificity**: Does it describe a concrete problem or feature, not a vague wish?
3. **Actionability**: Is there enough context to start planning? (expected behavior, affected area, reproduction steps for bugs)
4. **Scope**: Is it a single, bounded unit of work? (not an unstructured epic or multiple unrelated requests)

## Issue Type Classification

Also classify the issue as one of:
- **"feature"**: A new capability, enhancement, or improvement request
- **"bug"**: A defect report — something broken, incorrect, or failing
- **"epic"**: A large, multi-step initiative that should be decomposed into smaller issues

## Clarity Score

Rate the issue's specificity on a 0-10 scale:
- **8-10**: Clear, scoped, an engineer can start immediately (e.g. "add pagination to /api/users with limit/offset")
- **5-7**: Intent is clear but needs some enrichment (e.g. "improve the onboarding flow")
- **1-4**: Vague or broad — needs product research/discovery before planning (e.g. "build a better Calendly")

Issues scoring below 7 will be routed to a product discovery track
for competitive research and direction shaping before planning.

## Instructions

- **Default to passing issues through.** Most issues have enough intent to begin planning.
- Only return `"ready": false` if the issue is truly incomprehensible or has zero actionable content.
- If the issue is informal, vague, or missing detail but the *intent* is clear, return `"ready": true` and provide an `"enrichment"` string that fills in the gaps (expected behavior, affected areas, acceptance criteria, etc.). The enrichment will be posted as a comment to help the planning agent.
- If no enrichment is needed, set `"enrichment"` to an empty string.
- Set `"needs_discovery": true` if the issue is a broad product idea that needs market research, competitive analysis, or product direction exploration before engineering can begin.

Return ONLY a JSON object in this exact format, with no other text:

```json
{{"ready": true, "reasons": [], "issue_type": "feature", "clarity_score": 9, "needs_discovery": false, "enrichment": "## Triage Enrichment\\n\\n**Interpreted intent:** ...\\n**Affected area:** ...\\n**Acceptance criteria:**\\n- ..."}}
```

or for vague product ideas needing discovery:

```json
{{"ready": true, "reasons": [], "issue_type": "feature", "clarity_score": 3, "needs_discovery": true, "enrichment": ""}}
```

or for truly insufficient issues:

```json
{{"ready": false, "reasons": ["Specific reason why this cannot proceed"], "issue_type": "bug", "clarity_score": 0, "needs_discovery": false, "enrichment": ""}}
```
"""
        stats = builder.build_stats()
        return prompt, stats

    async def _evaluate_with_llm(self, issue: Task) -> TriageResult:
        """Run LLM evaluation and parse the verdict."""
        cmd = self._build_command()
        prompt, prompt_stats = self._build_prompt_with_stats(
            issue,
            max_body=max(1000, min(self._config.max_issue_body_chars, 3000)),
        )

        # Inject memory context if available
        memory_section = await self._inject_memory(
            query_context=f"{issue.title} {(issue.body or '')[:200]}"
        )
        if memory_section:
            prompt += memory_section

        transcript = await self._execute(
            cmd,
            prompt,
            self._config.repo_root,
            {"issue": issue.id, "source": "triage"},
            telemetry_stats=prompt_stats,
        )
        self._save_transcript("triage-issue", issue.id, transcript)

        if not transcript.strip():
            raise RuntimeError(
                "LLM returned empty response — subprocess produced no output"
            )

        result = self._parse_verdict(transcript, issue.id)
        if result is not None:
            try:
                import sentry_sdk as _sentry

                _sentry.add_breadcrumb(
                    category="triage.evaluated",
                    message=f"Triage evaluated issue #{issue.id}",
                    level="info",
                    data={"issue_id": issue.id, "ready": result.ready},
                )
            except ImportError:
                pass
            return result

        # Fallback: could not parse LLM response.  Rather than escalating
        # to HITL (which is for genuinely bad issues, not infra failures),
        # default to passing the issue through.  The triage prompt says
        # "default to passing issues through" — a parse failure is an
        # infrastructure problem, not an issue quality problem.
        logger.warning(
            "Issue #%d triage — could not parse LLM response, defaulting to "
            "ready=True. Transcript snippet: %.200s",
            issue.id,
            transcript.strip(),
        )
        try:
            import sentry_sdk as _sentry  # noqa: PLC0415

            _sentry.add_breadcrumb(
                category="triage.parse_failed",
                message=f"Triage parse failed for issue #{issue.id}",
                level="warning",
                data={"issue_id": issue.id},
            )
        except ImportError:
            pass
        return TriageResult(
            issue_number=issue.id,
            ready=True,
            reasons=["Triage parse failed — defaulting to ready"],
            enrichment=(
                "## Triage Note\n\n"
                "Triage evaluation could not parse the LLM response. "
                "This issue was passed through to planning by default. "
                "The planner should validate sufficient context."
            ),
        )

    @staticmethod
    def _result_from_dict(data: dict[str, object], issue_number: int) -> TriageResult:
        """Build a TriageResult from a parsed JSON dict."""
        raw = data.get("reasons", [])
        complexity = data.get("complexity_score", 0)
        score = int(complexity) if isinstance(complexity, int | float) else 0
        issue_type_raw = data.get("issue_type", IssueType.FEATURE)
        if isinstance(issue_type_raw, IssueType):
            issue_type = issue_type_raw
        elif isinstance(issue_type_raw, str):
            cleaned = issue_type_raw.strip().lower()
            issue_type = (
                IssueType(cleaned)
                if cleaned in IssueType._value2member_map_
                else IssueType.FEATURE
            )
        else:
            issue_type = IssueType.FEATURE
        enrichment_raw = data.get("enrichment", "")
        enrichment = str(enrichment_raw).strip() if enrichment_raw else ""
        clarity_raw = data.get("clarity_score", 10)
        clarity = int(clarity_raw) if isinstance(clarity_raw, int | float) else 10
        needs_discovery = bool(data.get("needs_discovery", False))
        return TriageResult(
            issue_number=issue_number,
            ready=_coerce_ready(data["ready"]),
            reasons=_coerce_reasons(raw),
            complexity_score=max(0, min(score, 10)),
            issue_type=issue_type,
            enrichment=enrichment,
            clarity_score=max(0, min(clarity, 10)),
            needs_discovery=needs_discovery,
        )

    @staticmethod
    def _strip_system_lines(transcript: str) -> str:
        """Remove Claude Code stream-json wrapper lines from the transcript.

        The subprocess transcript includes session initialization, tool use,
        and result wrapper lines like ``{"type":"system",...}``,
        ``{"type":"result",...}``, etc.  These confuse the JSON parsing
        strategies.  We strip all stream-json wrapper objects and also
        extract the ``result`` field from result objects (which contains
        the actual LLM response text).
        """
        _STREAM_TYPES = {"system", "result", "assistant", "tool_use", "tool_result"}
        filtered: list[str] = []
        for line in transcript.splitlines():
            stripped = line.strip()
            if not stripped:
                filtered.append(line)
                continue
            try:
                obj = json.loads(stripped)
                if isinstance(obj, dict) and obj.get("type") in _STREAM_TYPES:
                    # Extract the actual content from result objects
                    if obj.get("type") == "result" and isinstance(
                        obj.get("result"), str
                    ):
                        filtered.append(obj["result"])
                    continue
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
            filtered.append(line)
        return "\n".join(filtered)

    @staticmethod
    def _parse_verdict(transcript: str, issue_number: int) -> TriageResult | None:
        """Extract a JSON verdict from the LLM transcript.

        Tries multiple strategies:
        1. Direct ``json.loads`` on the full transcript
        2. Extract JSON from markdown code fences
        3. Regex to find a JSON object with ``"ready"`` key
        """
        # Pre-process: strip Claude Code system/init lines
        transcript = TriageRunner._strip_system_lines(transcript)

        # Strategy 1: direct parse
        try:
            data = json.loads(transcript.strip())
            if isinstance(data, dict) and "ready" in data:
                return TriageRunner._result_from_dict(data, issue_number)
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

        # Strategy 2: extract from markdown code fences
        fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", transcript, re.DOTALL)
        if fence_match:
            try:
                data = json.loads(fence_match.group(1).strip())
                if isinstance(data, dict) and "ready" in data:
                    return TriageRunner._result_from_dict(data, issue_number)
            except (json.JSONDecodeError, TypeError, ValueError):
                pass

        # Strategy 3: regex to find JSON object with "ready" key
        json_match = re.search(r"\{[^{}]*\"ready\"\s*:[^{}]*\}", transcript)
        if json_match:
            try:
                data = json.loads(json_match.group(0))
                if isinstance(data, dict) and "ready" in data:
                    return TriageRunner._result_from_dict(data, issue_number)
            except (json.JSONDecodeError, TypeError, ValueError):
                pass

        return None

    async def _emit_transcript(self, issue_number: int, line: str) -> None:
        """Publish a transcript line for the triage worker."""
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.TRANSCRIPT_LINE,
                data=TranscriptLinePayload(
                    issue=issue_number,
                    line=line,
                    source="triage",
                ),
            )
        )

    async def _emit_status(
        self, issue_number: int, worker_id: int, status: TriageStatus
    ) -> None:
        """Publish a triage status event."""
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.TRIAGE_UPDATE,
                data=TriageUpdatePayload(
                    issue=issue_number,
                    worker=worker_id,
                    status=status.value,
                    role="triage",
                ),
            )
        )

    # --- Auto-decomposition ---

    async def run_decomposition(self, task: Task) -> EpicDecompResult:
        """Determine if a high-complexity issue should be decomposed into an epic."""
        cmd = self._build_command()
        prompt = self._build_decomposition_prompt(task)

        try:
            transcript = await self._execute(
                cmd,
                prompt,
                self._config.repo_root,
                {"issue": task.id, "source": "decomposition"},
            )
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning(
                "Decomposition LLM call failed for issue #%d: %s",
                task.id,
                exc,
            )
            return EpicDecompResult()

        self._save_transcript("decomp-issue", task.id, transcript)
        return self._parse_decomposition(transcript)

    @staticmethod
    def _build_decomposition_prompt(task: Task) -> str:
        """Build the prompt asking the LLM to decompose a complex issue."""
        body = (task.body or "")[:5000]
        return f"""You are a decomposition agent. This issue has been identified as too complex for a single implementation pass.

## Issue #{task.id}

**Title:** {task.title}

**Body:**
{body}

## Instructions

Determine whether this issue should be broken into smaller, independently implementable child issues.

If YES, provide:
1. An epic title (concise summary)
2. An epic body with a checkbox list of child issues
3. 2-6 child issue specifications (title + body for each)

If NO, explain why decomposition is not appropriate.

Return ONLY a JSON object in this exact format:

```json
{{
  "should_decompose": true,
  "epic_title": "Epic: ...",
  "epic_body": "## Sub-issues\\n\\n- [ ] #1 — Child title 1\\n- [ ] #2 — Child title 2",
  "children": [
    {{"title": "Child issue title", "body": "Detailed description..."}},
    {{"title": "Another child", "body": "More details..."}}
  ],
  "reasoning": "Why this decomposition makes sense"
}}
```

or

```json
{{
  "should_decompose": false,
  "reasoning": "Why this issue should not be decomposed"
}}
```
"""

    @staticmethod
    def _parse_decomposition(transcript: str) -> EpicDecompResult:
        """Parse the decomposition LLM response."""
        data: dict[str, object] | None = None

        # Strategy 1: direct parse
        try:
            parsed = json.loads(transcript.strip())
            if isinstance(parsed, dict) and "should_decompose" in parsed:
                data = parsed
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

        # Strategy 2: code fence
        if data is None:
            fence_match = re.search(
                r"```(?:json)?\s*\n?(.*?)\n?```", transcript, re.DOTALL
            )
            if fence_match:
                try:
                    parsed = json.loads(fence_match.group(1).strip())
                    if isinstance(parsed, dict) and "should_decompose" in parsed:
                        data = parsed
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass

        if data is None:
            return EpicDecompResult()

        should = bool(data.get("should_decompose", False))
        if not should:
            return EpicDecompResult(
                should_decompose=False,
                reasoning=str(data.get("reasoning", "")),
            )

        children_raw = data.get("children", [])
        children: list[NewIssueSpec] = []
        if isinstance(children_raw, list):
            for item in children_raw:
                if isinstance(item, dict) and "title" in item:
                    children.append(
                        NewIssueSpec(
                            title=str(item["title"]),
                            body=str(item.get("body", "")),
                        )
                    )

        return EpicDecompResult(
            should_decompose=True,
            epic_title=str(data.get("epic_title", "")),
            epic_body=str(data.get("epic_body", "")),
            children=children,
            reasoning=str(data.get("reasoning", "")),
        )
