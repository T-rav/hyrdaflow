"""Background worker loop — report issue processing.

Dequeues pending bug reports from state, uploads screenshots, and
invokes the configured CLI agent to create GitHub issues.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
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

        # Upload screenshot gist if present (skip if secrets detected)
        screenshot_url = ""
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
                screenshot_url = await self._pr_manager.upload_screenshot_gist(
                    report.screenshot_base64
                )

        # Build the agent prompt
        title = f"[Bug Report] {report.description[:100]}"
        body_parts = ["## Bug Report", "", "### Description", report.description]

        if screenshot_url:
            body_parts += [
                "",
                "### Dashboard Screenshot",
                f"![Screenshot]({screenshot_url})",
            ]

        env = report.environment
        if env:
            source = env.get("source", "dashboard")
            version = env.get("app_version", "unknown")
            status = env.get("orchestrator_status", "unknown")
            queue_depths = env.get("queue_depths", {})
            queue_line = ", ".join(
                f"{k}={queue_depths.get(k, 0)}"
                for k in ("triage", "plan", "implement", "review")
            )
            body_parts += [
                "",
                "### Environment",
                f"- **HydraFlow version**: {version}",
                f"- **Status**: {status}",
                f"- **Queue depths**: {queue_line}",
                f"- **Source**: {source}",
            ]

        body = "\n".join(body_parts)
        repo = self._config.repo
        labels = ",".join(self._config.planner_label)

        prompt = (
            f"Create a GitHub issue in the repo {repo} with the following details.\n\n"
            f"Title: {title}\n\n"
            f"Body:\n{body}\n\n"
            f"Labels: {labels}\n\n"
            f"Use `gh issue create --repo {repo} "
            f'--title "{title}" --label "{labels}" --body \'...\'` '
            f"to create the issue. Output only the gh command and its result."
        )

        cmd = build_agent_command(
            tool=self._config.report_issue_tool,
            model=self._config.report_issue_model,
            max_turns=3,
        )

        event_data: TranscriptEventData = {
            "source": "report_issue",
        }

        try:
            await stream_claude_process(
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
        except Exception:
            logger.exception("Report issue agent failed for report %s", report.id)
            return {"processed": 0, "report_id": report.id, "error": True}

        logger.info("Processed report %s: %s", report.id, title)
        return {"processed": 1, "report_id": report.id}
