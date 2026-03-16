"""Background worker loop — report issue processing.

Dequeues pending bug reports from state, saves screenshots to temp files,
and invokes the Claude CLI with ``/hf.issue`` so that the agent can see the
image, research the codebase, and file a well-structured GitHub issue.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from agent_cli import build_agent_command
from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from execution import SubprocessRunner
from models import PendingReport, TranscriptEventData
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
        deps: LoopDeps,
        runner: SubprocessRunner | None = None,
    ) -> None:
        super().__init__(
            worker_name="report_issue",
            config=config,
            deps=deps,
            run_on_startup=True,
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

        # Transition tracked report to "in-progress" so the UI reflects
        # that the report is actively being processed.
        self._state.update_tracked_report(
            report.id,
            status="in-progress",
            action_label="processing",
            detail="Agent started processing bug report",
        )

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

        # Upload screenshot to GitHub (via gist) so the issue body can
        # reference a real URL instead of a local temp path.
        screenshot_url: str = ""
        if screenshot_path:
            screenshot_url = await self._pr_manager.upload_screenshot(screenshot_path)
            if not screenshot_url:
                logger.warning(
                    "Screenshot upload failed for report %s; "
                    "issue will be created without inline image",
                    report.id,
                )

        # Build prompt — invoke /hf.issue so Claude gets the full skill
        # instructions (codebase research, duplicate check, structured body).
        description = report.description
        if screenshot_path:
            description += (
                f"\n\nA screenshot of the bug is saved at {screenshot_path} "
                f"— read it with the Read tool to see what the user saw."
            )
            if screenshot_url:
                description += (
                    f"\n\nThe screenshot has been uploaded to: {screenshot_url}"
                    f"\n\nInclude this markdown image in the GitHub issue body "
                    f"so the screenshot is visible inline:\n\n"
                    f"![Screenshot]({screenshot_url})"
                )
            else:
                description += (
                    "\n\nScreenshot upload failed — do NOT include a local "
                    "file path in the issue body as it will render as a "
                    "broken image."
                )

        # Use hydraflow-ready so bug reports skip triage/planning and go
        # straight to implementation.
        ready_label = (
            self._config.ready_label[0]
            if self._config.ready_label
            else "hydraflow-ready"
        )
        description += (
            f"\n\nIMPORTANT: Use the label `{ready_label}` instead of "
            f"`hydraflow-find` for this issue."
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
            # Verify the agent applied the correct label and screenshot
            await self._verify_issue(issue_number, ready_label, screenshot_url)

            issue_url = f"https://github.com/{self._config.repo}/issues/{issue_number}"

            # Set linked_issue_url before update_tracked_report so both
            # fields are persisted atomically in the same save() call.
            tracked = self._state.get_tracked_report(report.id)
            if tracked:
                tracked.linked_issue_url = issue_url

            # Success — mark tracked report and remove from queue
            self._state.update_tracked_report(
                report.id,
                status="fixed",
                action_label="fixed",
                detail=f"Created issue #{issue_number}",
            )
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
            self._state.update_tracked_report(
                report.id,
                status="closed",
                action_label="escalated",
                detail=f"Failed after {attempt_count} attempts — escalated to HITL",
            )

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

        # Revert tracked report to queued for retry
        self._state.update_tracked_report(
            report.id,
            status="queued",
            action_label="retry",
            detail=f"Attempt {attempt_count}/{_MAX_REPORT_ATTEMPTS} failed — will retry",
        )

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

    async def _verify_issue(
        self, issue_number: int, expected_label: str, screenshot_url: str
    ) -> None:
        """Verify the created issue has the correct label and screenshot.

        Fixes up the issue if the agent missed either requirement.
        """
        try:
            output = await self._pr_manager._run_gh(
                "gh",
                "issue",
                "view",
                str(issue_number),
                "--repo",
                self._pr_manager._repo,
                "--json",
                "labels,body",
            )
            import json as _json

            data = _json.loads(output)
            labels = [lb.get("name", "") for lb in data.get("labels", [])]
            body = data.get("body", "")

            # Fix missing label
            if expected_label not in labels:
                logger.warning(
                    "Issue #%d missing label %r — adding it",
                    issue_number,
                    expected_label,
                )
                await self._pr_manager.add_labels(issue_number, [expected_label])

            # Fix missing screenshot URL in body
            if screenshot_url and screenshot_url not in body:
                logger.warning(
                    "Issue #%d missing screenshot URL — appending it",
                    issue_number,
                )
                appendix = f"\n\n## Screenshot\n\n![Screenshot]({screenshot_url})\n"
                await self._pr_manager._run_gh(
                    "gh",
                    "issue",
                    "edit",
                    str(issue_number),
                    "--repo",
                    self._pr_manager._repo,
                    "--body",
                    body + appendix,
                )
        except Exception:
            logger.warning(
                "Post-creation verification failed for issue #%d — "
                "issue was created but may need manual label/screenshot fix",
                issue_number,
                exc_info=True,
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
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(raw)
        except Exception:
            # fd is closed by os.fdopen (even on write failure) so only
            # clean up the temp file to avoid accumulation.
            with contextlib.suppress(OSError):
                Path(path).unlink()
            raise
        return Path(path)

    @classmethod
    def _extract_issue_number_from_transcript(cls, transcript: str) -> int:
        """Return issue number parsed from transcript output, or 0 when absent.

        Only matches issue URLs that appear near creation context (e.g.,
        ``gh issue create`` output or "Created issue" text) to avoid
        false positives from URLs mentioned in agent reasoning.
        """
        if not transcript:
            return 0

        # Strategy 1: look for `gh issue create` output which prints the URL
        # on its own line (the most reliable signal)
        for line in reversed(transcript.splitlines()):
            stripped = line.strip()
            match = cls._ISSUE_URL_RE.fullmatch(stripped)
            if match:
                try:
                    return int(match.group(1))
                except ValueError:
                    continue

        # Strategy 2: look for "created" context near an issue URL
        created_re = re.compile(
            r"(?:creat|open|filed|submitt)\w*\s+.*?" + cls._ISSUE_URL_RE.pattern,
            re.IGNORECASE,
        )
        match = created_re.search(transcript)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                pass

        return 0
