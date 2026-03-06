"""Background worker loop — report issue processing.

Dequeues pending bug reports from state, saves screenshots to temp files,
and invokes the Claude CLI with ``/hf.issue`` so that the agent can see the
image, research the codebase, and file a well-structured GitHub issue.
"""

from __future__ import annotations

import asyncio
import base64
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
from models import StatusCallback, TranscriptEventData
from pr_manager import PRManager
from runner_utils import stream_claude_process
from screenshot_scanner import scan_base64_for_secrets
from state import StateTracker

logger = logging.getLogger("hydraflow.report_issue_loop")


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

        report = self._state.dequeue_report()
        if report is None:
            return None

        # Save screenshot to a temp PNG so the agent can *see* it via Read.
        screenshot_path: Path | None = None
        has_secrets = False
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
                has_secrets = True
            else:
                screenshot_path = self._save_screenshot(report.screenshot_base64)

        # Build prompt — invoke /hf.issue so Claude gets the full skill
        # instructions (codebase research, duplicate check, structured body).
        description = report.description
        if screenshot_path:
            description += (
                f"\n\nA screenshot of the bug is saved at {screenshot_path} "
                f"— read it with the Read tool to see what the user saw."
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

        labels_list = list(self._config.planner_label)
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

        # Reliability guard: if the agent didn't create the issue, fall back
        # to a basic gh issue create via PRManager.
        fallback_title = f"[Bug Report] {report.description[:100]}"
        if issue_number <= 0:
            fallback_body = f"## Bug Report\n\n{report.description}"
            if report.screenshot_base64 and not has_secrets:
                gist_url = await self._pr_manager.upload_screenshot_gist(
                    report.screenshot_base64
                )
                if gist_url:
                    fallback_body += f"\n\n![Screenshot]({gist_url})"
            issue_number = await self._pr_manager.create_issue(
                fallback_title, fallback_body, labels_list
            )
        if issue_number <= 0:
            logger.error(
                "Report %s failed: issue was not created via agent or fallback",
                report.id,
            )
            return {"processed": 0, "report_id": report.id, "error": True}

        logger.info(
            "Processed report %s as issue #%d: %s",
            report.id,
            issue_number,
            fallback_title,
        )
        return {"processed": 1, "report_id": report.id, "issue_number": issue_number}

    @staticmethod
    def _save_screenshot(b64_data: str) -> Path:
        """Decode base64 screenshot and write to a temp PNG file."""
        raw = base64.b64decode(b64_data)
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
