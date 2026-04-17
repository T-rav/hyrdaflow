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
import json
import logging
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent_cli import build_agent_command
from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import Credentials, HydraFlowConfig
from exception_classify import reraise_on_credit_or_bug
from execution import SubprocessRunner
from models import PendingReport, TranscriptEventData
from runner_utils import AuthenticationRetryError, StreamConfig, stream_claude_process
from screenshot_scanner import scan_base64_for_secrets
from state import StateTracker

if TYPE_CHECKING:
    from pr_manager import PRManager

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
        credentials: Credentials | None = None,
    ) -> None:
        super().__init__(
            worker_name="report_issue",
            config=config,
            deps=deps,
            run_on_startup=False,
        )
        self._state = state
        self._pr_manager = pr_manager
        self._runner = runner
        self._credentials = credentials or Credentials()
        self._active_procs: set[asyncio.subprocess.Process] = set()

    async def _emit_report_event(
        self, report_id: str, status: str, **extra: object
    ) -> None:
        """Publish a REPORT_UPDATE event so listeners (WebSocket, metrics) react."""
        from events import EventType, HydraFlowEvent

        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.REPORT_UPDATE,
                data={"report_id": report_id, "status": status, **extra},
            )
        )

    async def run(self) -> None:
        """Drain all queued reports on startup, then enter the normal loop.

        The base polling loop processes one report per cycle.  This override
        keeps executing cycles until the queue is empty (or stop is requested),
        ensuring reports queued before the processor started are all handled
        before entering steady-state polling.
        """
        while not self._stop_event.is_set() and self._state.peek_report() is not None:
            try:
                await self._execute_cycle()
            except AuthenticationRetryError:
                logger.warning(
                    "Auth error during report drain — deferring to polling loop"
                )
                break

        await super().run()

    def _get_default_interval(self) -> int:
        return self._config.report_issue_interval

    async def _sweep_stale_reports(self) -> int:
        """Auto-close reports stuck at 'queued' longer than the configured threshold.

        Returns the number of reports closed.
        """
        threshold_hours = self._config.stale_report_threshold_hours
        now = datetime.now(UTC)
        closed = 0
        for report in self._state.get_pending_reports():
            try:
                created = datetime.fromisoformat(report.created_at)
                age_hours = (now - created).total_seconds() / 3600
            except (ValueError, TypeError):
                logger.warning(
                    "Skipping stale-sweep for report %s: unparseable created_at %r",
                    report.id,
                    report.created_at,
                )
                continue
            if age_hours >= threshold_hours:
                self._state.remove_report(report.id)
                updated = self._state.update_tracked_report(
                    report.id,
                    status="closed",
                    action_label="stale",
                    detail=f"Auto-closed after {age_hours:.1f}h (threshold: {threshold_hours}h)",
                )
                await self._emit_report_event(
                    report.id,
                    "closed",
                    detail="stale",
                )
                if updated is None:
                    logger.warning(
                        "Stale report %s removed from queue but has no TrackedReport — "
                        "no audit trail recorded",
                        report.id,
                    )
                logger.info(
                    "Auto-closed stale report %s (age %.1fh, threshold %dh)",
                    report.id,
                    age_hours,
                    threshold_hours,
                )
                closed += 1
        return closed

    async def _sync_filed_reports(self) -> int:
        """Check linked GitHub issues for filed reports and auto-transition.

        Returns the number of reports transitioned.
        """
        transitioned = 0
        for report in self._state.get_filed_reports():
            issue_number = self._extract_issue_number_from_url(report.linked_issue_url)
            if issue_number <= 0:
                continue
            try:
                issue_state = await self._pr_manager.get_issue_state(issue_number)
            except Exception as exc:
                reraise_on_credit_or_bug(exc)
                logger.debug(
                    "Failed to check issue state for report %s (issue #%d)",
                    report.id,
                    issue_number,
                    exc_info=True,
                )
                continue
            if issue_state == "COMPLETED":
                self._state.update_tracked_report(
                    report.id,
                    status="fixed",
                    action_label="fixed",
                    detail=f"Issue #{issue_number} resolved",
                )
                await self._emit_report_event(report.id, "fixed")
                transitioned += 1
                logger.info(
                    "Report %s auto-transitioned to fixed (issue #%d resolved)",
                    report.id,
                    issue_number,
                )
            elif issue_state == "NOT_PLANNED":
                self._state.update_tracked_report(
                    report.id,
                    status="closed",
                    action_label="closed",
                    detail=f"Issue #{issue_number} closed as won't fix",
                )
                await self._emit_report_event(report.id, "closed", detail="won't fix")
                transitioned += 1
                logger.info(
                    "Report %s auto-transitioned to closed (issue #%d won't fix)",
                    report.id,
                    issue_number,
                )
        return transitioned

    @classmethod
    def _extract_issue_number_from_url(cls, url: str) -> int:
        """Extract the issue number from a GitHub issue URL, or return 0."""
        m = cls._ISSUE_URL_RE.search(url)
        return int(m.group(1)) if m else 0

    async def _do_work(self) -> dict[str, Any] | None:
        if self._config.dry_run:
            return None

        await self._sweep_stale_reports()
        await self._sync_filed_reports()

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
        await self._emit_report_event(report.id, "in-progress", detail="processing")

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

        # Everything from here on must clean up the screenshot temp file.
        issue_number = 0
        screenshot_url: str = ""
        plan_label = (
            self._config.planner_label[0]
            if self._config.planner_label
            else "hydraflow-plan"
        )
        try:
            # Upload screenshot to GitHub (via gist) so the issue body can
            # reference a real URL instead of a local temp path.
            if screenshot_path:
                screenshot_url = await self._pr_manager.upload_screenshot(
                    screenshot_path
                )
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

            # Use hydraflow-plan so bug reports go through the planning phase
            # (lite plan auto-detected) before implementation. This ensures every
            # issue has a plan comment that the implement agent can reference.
            description += (
                f"\n\nIMPORTANT: Use the label `{plan_label}` instead of "
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

            transcript = await stream_claude_process(
                cmd=cmd,
                prompt=prompt,
                cwd=self._config.repo_root,
                active_procs=self._active_procs,
                event_bus=self._bus,
                event_data=event_data,
                logger=logger,
                config=StreamConfig(
                    runner=self._runner,
                    gh_token=self._credentials.gh_token,
                ),
            )
            issue_number = self._extract_issue_number_from_transcript(transcript)
        except AuthenticationRetryError:
            logger.warning(
                "Report %s hit authentication error — deferring to next cycle",
                report.id,
            )
            raise
        except Exception:
            logger.exception("Report issue agent failed for report %s", report.id)
        finally:
            if screenshot_path:
                screenshot_path.unlink(missing_ok=True)

        if issue_number > 0:
            # Verify the agent applied the correct label and screenshot
            await self._verify_issue(issue_number, plan_label, screenshot_url)

            issue_url = f"https://github.com/{self._config.repo}/issues/{issue_number}"

            # Set linked_issue_url before update_tracked_report so both
            # fields are persisted atomically in the same save() call.
            tracked = self._state.get_tracked_report(report.id)
            if tracked:
                tracked.linked_issue_url = issue_url

            # Success — mark as "filed" (issue created, not yet resolved).
            # The report only becomes "fixed" when the linked issue is
            # confirmed closed/merged via the status-refresh endpoint.
            self._state.update_tracked_report(
                report.id,
                status="filed",
                action_label="filed",
                detail=f"Created issue #{issue_number}",
            )
            await self._emit_report_event(
                report.id,
                "filed",
                issue_number=issue_number,
                issue_url=issue_url,
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
            await self._emit_report_event(
                report.id,
                "closed",
                detail=f"Escalated after {attempt_count} failed attempts",
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
        await self._emit_report_event(
            report.id,
            "queued",
            detail=f"Retry attempt {attempt_count}/{_MAX_REPORT_ATTEMPTS}",
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
            data = json.loads(output)
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
