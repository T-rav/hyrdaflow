"""Background worker loop — report issue processing.

Dequeues pending bug reports from state, saves screenshots to temp files,
and invokes the Claude CLI with ``/hf.issue`` so that the agent can see the
image, research the codebase, and file a well-structured GitHub issue.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import re
import tempfile
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

from agent_cli import build_agent_command
from base_background_loop import BaseBackgroundLoop
from config import HydraFlowConfig
from events import EventBus
from execution import SubprocessRunner
from models import PendingReport, StatusCallback, TranscriptEventData
from pr_manager import PRManager
from runner_utils import stream_claude_process
from screenshot_scanner import scan_base64_for_secrets
from state import StateTracker

logger = logging.getLogger("hydraflow.report_issue_loop")

_MAX_REPORT_ATTEMPTS = 5


class ReportIssueLoop(BaseBackgroundLoop):
    """Processes queued bug reports into GitHub issues via the configured agent."""

    _ISSUE_URL_RE = re.compile(r"https://github\.com/[^/\s]+/[^/\s]+/issues/(\d+)")

    def __init__(
        self,
        config: HydraFlowConfig,
        state: StateTracker,
        pr_manager: PRManager,
        event_bus: EventBus,
        stop_event: asyncio.Event,
        status_cb: StatusCallback,
        enabled_cb: Callable[[str], bool],
        sleep_fn: Callable[[int | float], Coroutine[Any, Any, None]],
        interval_cb: Callable[[str], int] | None = None,
        runner: SubprocessRunner | None = None,
    ) -> None:
        super().__init__(
            worker_name="report_issue",
            config=config,
            bus=event_bus,
            stop_event=stop_event,
            status_cb=status_cb,
            enabled_cb=enabled_cb,
            sleep_fn=sleep_fn,
            interval_cb=interval_cb,
        )
        self._state = state
        self._pr_manager = pr_manager
        self._runner = runner
        self._active_procs: set[asyncio.subprocess.Process] = set()

    def _get_default_interval(self) -> int:
        return self._config.report_issue_interval

    async def _do_work(self) -> dict[str, Any] | None:
        if self._config.dry_run:
            return None

        report = self._state.peek_report()
        if report is None:
            return None

        # Save screenshot to a temp PNG so the agent can *see* it via Read
        # and reference it as a markdown image in the issue body.  The `gh
        # issue create` CLI auto-uploads local image paths used in markdown.
        screenshot_path: Path | None = None
        if report.screenshot_base64:
            secret_hits = (
                scan_base64_for_secrets(report.screenshot_base64)
                if self._config.screenshot_redaction_enabled
                else []
            )
            if secret_hits:
                logger.warning(
                    "Screenshot for report %s contains potential secrets (%s); "
                    "stripping screenshot from report",
                    report.id,
                    ", ".join(secret_hits),
                )
            else:
                try:
                    screenshot_path = self._save_screenshot(report.screenshot_base64)
                except (ValueError, binascii.Error):
                    logger.warning(
                        "Screenshot for report %s was not valid base64; "
                        "continuing without screenshot attachment",
                        report.id,
                    )

        # Build prompt — invoke /hf.issue so Claude gets the full skill
        # instructions (codebase research, duplicate check, structured body).
        description = report.description
        if screenshot_path:
            description += (
                f"\n\nA screenshot of the bug is saved at {screenshot_path} "
                f"— read it with the Read tool to see what the user saw."
                f"\n\nInclude this markdown image in the GitHub issue body so "
                f"the screenshot is visible inline (gh issue create will "
                f"auto-upload the local file):\n\n"
                f"![Screenshot]({screenshot_path})"
            )

        prompt = f"/hf.issue {description}"

        cmd = build_agent_command(
            tool=self._config.report_issue_tool,
            model=self._config.report_issue_model,
            max_turns=10,
        )

        event_data: TranscriptEventData = {
            "source": "report_issue",
        }

        issue_number = 0
        try:
            transcript = await stream_claude_process(
                cmd=cmd,
                prompt=prompt,
                cwd=self._config.repo_root,
                active_procs=self._active_procs,
                event_bus=self._bus,
                event_data=event_data,
                logger=logger,
                runner=self._runner,
                gh_token=self._config.gh_token,
            )
            issue_number = self._extract_issue_number_from_transcript(transcript)
        except Exception:
            logger.exception("Report issue agent failed for report %s", report.id)
        finally:
            if screenshot_path:
                screenshot_path.unlink(missing_ok=True)

        if issue_number > 0:
            # Success — remove from queue
            self._state.remove_report(report.id)
            logger.info(
                "Processed report %s as issue #%d: %s",
                report.id,
                issue_number,
                f"[Bug Report] {report.description[:100]}",
            )
            return {
                "processed": 1,
                "report_id": report.id,
                "issue_number": issue_number,
            }

        # Failed — increment attempts and check cap
        attempt_count = self._state.fail_report(report.id)
        if attempt_count >= _MAX_REPORT_ATTEMPTS:
            self._state.remove_report(report.id)
            await self._escalate_failed_report(report)
            logger.error(
                "Report %s failed %d times — escalated to HITL",
                report.id,
                attempt_count,
            )
            return {
                "processed": 0,
                "report_id": report.id,
                "error": True,
                "escalated": True,
            }

        logger.warning(
            "Report %s failed (attempt %d/%d) — will retry next cycle",
            report.id,
            attempt_count,
            _MAX_REPORT_ATTEMPTS,
        )
        return {"processed": 0, "report_id": report.id, "error": True}

    async def _escalate_failed_report(self, report: PendingReport) -> None:
        """Create a HITL issue with the raw report content for manual review."""
        body = (
            "## Bug Report — Processing Failed\n\n"
            "This bug report could not be processed automatically after "
            f"{_MAX_REPORT_ATTEMPTS} attempts. The raw input is preserved "
            "below for manual review.\n\n"
            f"**Report ID:** {report.id}\n"
            f"**Created:** {report.created_at}\n\n"
            "### Description\n\n"
            f"{report.description}\n\n"
        )
        if report.environment:
            body += "### Environment\n\n"
            for key, value in report.environment.items():
                body += f"- **{key}:** {value}\n"
            body += "\n"
        if report.screenshot_base64:
            # Include a truncated indicator — the full base64 is too large for an issue
            body += (
                "### Screenshot\n\n"
                f"Base64 screenshot attached ({len(report.screenshot_base64)} chars). "
                "Too large to include in this issue.\n"
            )

        labels = list(self._config.hitl_label)
        await self._pr_manager.create_issue(
            f"[Bug Report] Failed to process: {report.description[:80]}",
            body,
            labels,
        )

    @staticmethod
    def _save_screenshot(b64_data: str) -> Path:
        """Decode base64 screenshot and write to a temp PNG file."""
        payload = b64_data
        if payload.startswith("data:"):
            _, _, payload = payload.partition(",")
        # Strip whitespace that may be introduced during transport
        payload = payload.translate({ord(c): None for c in " \t\n\r"})
        raw = base64.b64decode(payload, validate=True)
        fd, path = tempfile.mkstemp(suffix=".png", prefix="hydraflow-report-")
        Path(path).write_bytes(raw)
        # Close the fd opened by mkstemp (write_bytes uses its own handle).
        import os

        os.close(fd)
        return Path(path)

    @classmethod
    def _extract_issue_number_from_transcript(cls, transcript: str) -> int:
        """Return issue number parsed from transcript output, or 0 when absent."""
        match = cls._ISSUE_URL_RE.search(transcript or "")
        if not match:
            return 0
        try:
            return int(match.group(1))
        except ValueError:
            return 0
