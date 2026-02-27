"""Automated transcript summarization for agent phases."""

from __future__ import annotations

import logging

from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from execution import SubprocessRunner, get_default_runner
from pr_manager import PRManager
from state import StateTracker
from subprocess_util import make_clean_env

logger = logging.getLogger("hydraflow.transcript_summarizer")

_MIN_TRANSCRIPT_LENGTH = 500


def build_transcript_summary_body(
    issue_number: int,
    phase: str,
    summary_content: str,
    issue_title: str = "",
    duration_seconds: float = 0.0,
) -> str:
    """Format a structured GitHub issue body for a transcript summary."""
    lines = ["## Transcript Summary\n"]
    if issue_title:
        lines.append(f"**Issue:** #{issue_number} — {issue_title}")
    else:
        lines.append(f"**Issue:** #{issue_number}")
    lines.append(f"**Phase:** {phase}")
    if duration_seconds > 0:
        lines.append(f"**Duration:** {duration_seconds:.0f}s")
    lines.append("")
    lines.append(summary_content)
    lines.append("")
    lines.append("---")
    lines.append(
        f"*Auto-generated from transcript of issue #{issue_number} ({phase} phase)*"
    )
    return "\n".join(lines)


def build_phase_summary_comment(
    phase: str,
    status: str,
    summary_content: str,
    *,
    duration_seconds: float = 0.0,
    log_file: str = "",
) -> str:
    """Format a phase summary comment for posting on the original issue."""
    lines: list[str] = []
    lines.append(f"## Phase Summary: {phase.capitalize()}\n")
    lines.append(f"**Status:** {status}")
    if duration_seconds > 0:
        lines.append(f"**Duration:** {duration_seconds:.0f}s")
    lines.append("")
    lines.append(summary_content)
    if log_file:
        lines.append("")
        lines.append("<details>")
        lines.append("<summary>Full transcript</summary>")
        lines.append("")
        lines.append(f"`{log_file}`")
        lines.append("")
        lines.append("</details>")
    lines.append("")
    lines.append("---")
    lines.append(f"*Auto-generated phase summary ({phase})*")
    return "\n".join(lines)


def _truncate_transcript(transcript: str, max_chars: int) -> str:
    """Cap transcript size, keeping the end (most useful decisions/errors)."""
    if len(transcript) <= max_chars:
        return transcript
    marker = "...(transcript truncated)...\n\n"
    return marker + transcript[-(max_chars - len(marker)) :]


_SUMMARIZATION_PROMPT = """\
You are analysing an agent transcript from a software engineering pipeline.
Extract a structured summary with ONLY the sections that have content.
Use these section headings (omit any section with nothing to report):

### Key Decisions
### Patterns Discovered
### Errors Encountered
### Workarounds Applied
### Codebase Insights

Each section should contain concise bullet points.
Do NOT include preamble or closing remarks — output ONLY the markdown sections.

--- TRANSCRIPT ---
{transcript}
"""

_HITL_CONTEXT_PROMPT = """\
You are assisting a human operator resolving a stuck software issue in a HITL queue.
Summarize the context into concise, actionable lines.

Rules:
- Output plain text only (no markdown, no bullets).
- Each line should be one sentence and include concrete details.
- Prefer what is blocked, why it is blocked, and what to do next.
- Keep to at most 8 lines total.

--- ISSUE CONTEXT ---
{context}
"""


class TranscriptSummarizer:
    """Summarizes agent transcripts and publishes them as GitHub issues or comments."""

    def __init__(
        self,
        config: HydraFlowConfig,
        pr_manager: PRManager,
        event_bus: EventBus,
        state: StateTracker,
        runner: SubprocessRunner | None = None,
    ) -> None:
        self._config = config
        self._prs = pr_manager
        self._bus = event_bus
        self._state = state
        self._runner = runner or get_default_runner()

    # --- Shared summary generation ---

    async def _generate_summary(self, transcript: str) -> str | None:
        """Generate a structured summary from a transcript.

        Returns the summary content string, or ``None`` if the transcript
        is too short, empty, disabled, or the model call fails.
        """
        if not self._config.transcript_summarization_enabled:
            return None

        if not transcript or not transcript.strip():
            return None

        if len(transcript.strip()) < _MIN_TRANSCRIPT_LENGTH:
            return None

        truncated = _truncate_transcript(
            transcript, self._config.max_transcript_summary_chars
        )
        prompt = _SUMMARIZATION_PROMPT.format(transcript=truncated)
        return await self._call_model(prompt)

    async def summarize_hitl_context(self, context: str) -> str | None:
        """Generate a compact operator summary for HITL context."""
        if not context.strip():
            return None
        truncated = _truncate_transcript(
            context, self._config.max_transcript_summary_chars
        )
        prompt = _HITL_CONTEXT_PROMPT.format(context=truncated)
        return await self._call_model(prompt)

    # --- Comment-based summaries (new default) ---

    async def summarize_and_comment(
        self,
        transcript: str,
        issue_number: int,
        phase: str,
        *,
        status: str = "success",
        issue_title: str = "",
        duration_seconds: float = 0.0,
        log_file: str = "",
    ) -> bool:
        """Summarize a transcript and post as a comment on the original issue.

        Returns ``True`` on success, ``False`` if skipped or failed.
        Never raises — all errors are logged and swallowed.
        """
        try:
            return await self._summarize_and_comment_inner(
                transcript,
                issue_number,
                phase,
                status=status,
                issue_title=issue_title,
                duration_seconds=duration_seconds,
                log_file=log_file,
            )
        except Exception:
            logger.exception(
                "Transcript summary comment failed for issue #%d (%s phase)",
                issue_number,
                phase,
            )
            return False

    async def _summarize_and_comment_inner(
        self,
        transcript: str,
        issue_number: int,
        phase: str,
        *,
        status: str,
        issue_title: str,
        duration_seconds: float,
        log_file: str,
    ) -> bool:
        """Inner implementation for comment-based summaries — may raise."""
        summary_content = await self._generate_summary(transcript)
        if not summary_content:
            return False

        body = build_phase_summary_comment(
            phase=phase,
            status=status,
            summary_content=summary_content,
            duration_seconds=duration_seconds,
            log_file=log_file,
        )

        await self._prs.post_comment(issue_number, body)

        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.TRANSCRIPT_SUMMARY,
                data={
                    "source_issue": issue_number,
                    "phase": phase,
                    "posted_as": "comment",
                },
            )
        )
        logger.info(
            "Posted transcript summary comment on issue #%d (%s phase)",
            issue_number,
            phase,
        )
        return True

    # --- Issue-based summaries (legacy, configurable) ---

    async def summarize_and_publish(
        self,
        transcript: str,
        issue_number: int,
        phase: str,
        issue_title: str = "",
        duration_seconds: float = 0.0,
    ) -> int | None:
        """Summarize a transcript and publish as a GitHub issue.

        Returns the created issue number, or ``None`` if skipped/failed.
        Only active when ``transcript_summary_as_issue`` is enabled.
        Never raises — all errors are logged and swallowed.
        """
        if not self._config.transcript_summary_as_issue:
            return None
        try:
            return await self._summarize_and_publish_inner(
                transcript, issue_number, phase, issue_title, duration_seconds
            )
        except Exception:
            logger.exception(
                "Transcript summarization failed for issue #%d (%s phase)",
                issue_number,
                phase,
            )
            return None

    async def _summarize_and_publish_inner(
        self,
        transcript: str,
        issue_number: int,
        phase: str,
        issue_title: str,
        duration_seconds: float,
    ) -> int | None:
        """Inner implementation — may raise."""
        summary_content = await self._generate_summary(transcript)
        if not summary_content:
            return None

        # Build issue body
        body = build_transcript_summary_body(
            issue_number=issue_number,
            phase=phase,
            summary_content=summary_content,
            issue_title=issue_title,
            duration_seconds=duration_seconds,
        )

        title = f"[Transcript Summary] Issue #{issue_number} — {phase} phase"
        labels = list(self._config.improve_label) + list(self._config.transcript_label)

        issue_num = await self._prs.create_issue(title, body, labels)
        if issue_num:
            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.TRANSCRIPT_SUMMARY,
                    data={
                        "source_issue": issue_number,
                        "phase": phase,
                        "summary_issue": issue_num,
                    },
                )
            )
            logger.info(
                "Filed transcript summary as issue #%d for issue #%d (%s phase)",
                issue_num,
                issue_number,
                phase,
            )
            return issue_num

        return None

    async def _call_model(self, prompt: str) -> str | None:
        """Call the configured CLI backend to summarize.

        Returns the model output, or ``None`` on failure.
        """
        tool = self._config.transcript_summary_tool
        model = self._config.transcript_summary_model
        if tool == "codex":
            cmd = [
                "codex",
                "exec",
                "--json",
                "--model",
                model,
                "--sandbox",
                "danger-full-access",
                "--dangerously-bypass-approvals-and-sandbox",
                "--skip-git-repo-check",
                prompt,
            ]
            cmd_input = None
        else:
            cmd = ["claude", "-p", "--model", model]
            cmd_input = prompt.encode()
        env = make_clean_env(self._config.gh_token)

        try:
            result = await self._runner.run_simple(
                cmd,
                env=env,
                input=cmd_input,
                timeout=self._config.transcript_summary_timeout,
            )
            if result.returncode != 0:
                logger.warning(
                    "Transcript summary model failed (rc=%d): %s",
                    result.returncode,
                    result.stderr[:200],
                )
                return None
            return result.stdout if result.stdout else None
        except TimeoutError:
            logger.warning("Transcript summary model timed out")
            return None
        except (OSError, FileNotFoundError, NotImplementedError) as exc:
            logger.warning("Transcript summary model unavailable: %s", exc)
            return None
