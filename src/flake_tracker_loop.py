"""FlakeTrackerLoop — 4h detector for persistently flaky tests.

Spec: `docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md`
§4.5. Reads JUnit XML from the last 20 RC runs (uploaded by
`rc-promotion-scenario.yml`), counts mixed pass/fail occurrences per
test, and files a `hydraflow-find` + `flaky-test` issue when a test's
flake count crosses `flake_threshold` (default 3, comparison `>=`).

After 3 repair attempts for the same test_name the loop files a
second issue labeled `hitl-escalation` + `flaky-test-stuck`. The
dedup key clears when the escalation issue is closed (spec §3.2).
"""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from models import WorkCycleResult

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from dedup_store import DedupStore
    from pr_manager import PRManager
    from state import StateTracker

logger = logging.getLogger("hydraflow.flake_tracker_loop")

_MAX_ATTEMPTS = 3
_RUN_WINDOW = 20


def parse_junit_xml(xml_bytes: bytes) -> dict[str, str]:
    """Return ``{test_id: "pass"|"fail"}`` per test case in a JUnit XML doc.

    ``test_id`` is ``{classname}.{name}``. A testcase is ``fail`` if it
    has any ``<failure>`` or ``<error>`` child element; ``skip`` is
    treated as ``pass`` (skipped tests are not flakes).
    """
    results: dict[str, str] = {}
    root = ET.fromstring(xml_bytes)  # nosec B314 — JUnit XML from trusted CI artifacts
    for case in root.iter("testcase"):
        cls = case.get("classname") or ""
        name = case.get("name") or ""
        test_id = f"{cls}.{name}".lstrip(".")
        failed = any(c.tag in ("failure", "error") for c in case)
        results[test_id] = "fail" if failed else "pass"
    return results


class FlakeTrackerLoop(BaseBackgroundLoop):
    """Detects persistently flaky tests in the RC window (spec §4.5)."""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        state: StateTracker,
        pr_manager: PRManager,
        dedup: DedupStore,
        deps: LoopDeps,
    ) -> None:
        super().__init__(
            worker_name="flake_tracker",
            config=config,
            deps=deps,
            run_on_startup=False,
        )
        self._state = state
        self._pr = pr_manager
        self._dedup = dedup

    def _get_default_interval(self) -> int:
        return self._config.flake_tracker_interval

    async def _fetch_recent_runs(self) -> list[dict[str, Any]]:
        """Return metadata for the last 20 RC promotion workflow runs."""
        cmd = [
            "gh",
            "run",
            "list",
            "--repo",
            self._config.repo,
            "--workflow",
            "rc-promotion-scenario.yml",
            "--limit",
            str(_RUN_WINDOW),
            "--json",
            "databaseId,url,conclusion,createdAt",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.warning(
                "gh run list exit=%d: %s",
                proc.returncode,
                stderr.decode(errors="replace")[:400],
            )
            return []
        try:
            return json.loads(stdout.decode() or "[]")
        except json.JSONDecodeError:
            logger.warning("gh run list non-JSON response; returning empty")
            return []

    async def _download_junit(self, run: dict[str, Any]) -> dict[str, str]:
        """Download the ``junit-scenario`` artifact for a run; return per-test results."""
        run_id = str(run.get("databaseId", ""))
        if not run_id:
            return {}
        with tempfile.TemporaryDirectory() as td:
            cmd = [
                "gh",
                "run",
                "download",
                run_id,
                "--repo",
                self._config.repo,
                "--name",
                "junit-scenario",
                "--dir",
                td,
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.info(
                    "no junit-scenario artifact for run %s: %s",
                    run_id,
                    stderr.decode(errors="replace")[:200],
                )
                return {}
            combined: dict[str, str] = {}
            for xml_path in Path(td).rglob("*.xml"):
                try:
                    combined.update(parse_junit_xml(xml_path.read_bytes()))
                except ET.ParseError:
                    logger.debug("junit parse failed: %s", xml_path)
                    continue
            return combined

    def _tally_flakes(self, runs: list[dict[str, str]]) -> dict[str, int]:
        """Count fails per test across runs.

        Returns ``{test_id: fail_count}`` for every test that failed at
        least once. Threshold filtering happens in ``_do_work`` against
        ``config.flake_threshold``; a test that passes every run has a
        fail count of zero and is omitted here.
        """
        fail_counts: dict[str, int] = {}
        for run in runs:
            for test_id, result in run.items():
                if result == "fail":
                    fail_counts[test_id] = fail_counts.get(test_id, 0) + 1
        return fail_counts

    async def _file_flake_issue(
        self, test_id: str, flake_count: int, runs: list[dict[str, Any]]
    ) -> int:
        """File a ``hydraflow-find`` + ``flaky-test`` issue. Returns issue number."""
        title = f"Flaky test: {test_id} (flake rate: {flake_count}/{_RUN_WINDOW})"
        run_lines = "\n".join(
            f"- {r.get('url', '?')} ({r.get('createdAt', '?')})" for r in runs[:10]
        )
        body = (
            f"## Flake signal\n\n"
            f"Test `{test_id}` failed in {flake_count} of the last {_RUN_WINDOW} "
            f"RC promotion runs. This loop (`flake_tracker`, spec §4.5) filed "
            f"the issue so the standard implementer/reviewer pipeline can fix "
            f"the race, add a deterministic wait, or quarantine the test.\n\n"
            f"### Recent runs (up to 10)\n{run_lines}\n\n"
            f"_This issue was auto-filed by HydraFlow's `flake_tracker` loop._"
        )
        return await self._pr.create_issue(
            title, body, ["hydraflow-find", "flaky-test"]
        )

    async def _file_escalation(self, test_id: str, attempts: int) -> int:
        """File ``hitl-escalation`` + ``flaky-test-stuck`` after N failed repairs."""
        title = f"HITL: flaky test {test_id} unresolved after {attempts} attempts"
        body = (
            f"`flake_tracker` has filed `flaky-test` issues for `{test_id}` "
            f"{attempts} times without closure. Human review needed.\n\n"
            f"_Spec §3.2 escalation lifecycle: close this issue to clear the "
            f"dedup key and let the loop re-fire on the next drift._"
        )
        return await self._pr.create_issue(
            title, body, ["hitl-escalation", "flaky-test-stuck"]
        )

    async def _reconcile_closed_escalations(self) -> None:
        """Clear dedup keys whose escalation issue has been closed (spec §3.2)."""
        cmd = [
            "gh",
            "issue",
            "list",
            "--repo",
            self._config.repo,
            "--state",
            "closed",
            "--label",
            "hitl-escalation",
            "--label",
            "flaky-test-stuck",
            "--author",
            "@me",
            "--limit",
            "100",
            "--json",
            "title",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return
        try:
            closed = json.loads(stdout.decode() or "[]")
        except json.JSONDecodeError:
            return
        current = self._dedup.get()
        keep = set(current)
        for issue in closed:
            title = issue.get("title", "")
            # Title shape: "HITL: flaky test <id> unresolved after N attempts"
            for key in list(keep):
                if key.startswith("flake_tracker:") and key.split(":", 1)[1] in title:
                    keep.discard(key)
                    self._state.clear_flake_attempts(key.split(":", 1)[1])
        if keep != current:
            self._dedup.set_all(keep)

    async def _do_work(self) -> WorkCycleResult:
        """One flake-tracking cycle (spec §4.5)."""
        t0 = time.perf_counter()
        await self._reconcile_closed_escalations()

        runs = await self._fetch_recent_runs()
        if not runs:
            return {"status": "no_runs", "filed": 0}

        per_run_results: list[dict[str, str]] = []
        for run in runs:
            per_run_results.append(await self._download_junit(run))

        counts = self._tally_flakes(per_run_results)
        self._state.set_flake_counts(counts)

        threshold = self._config.flake_threshold
        filed = 0
        escalated = 0
        dedup = self._dedup.get()
        for test_id, count in counts.items():
            if count < threshold:
                continue
            key = f"flake_tracker:{test_id}"
            if key in dedup:
                continue
            attempts = self._state.inc_flake_attempts(test_id)
            if attempts >= _MAX_ATTEMPTS:
                await self._file_escalation(test_id, attempts)
                escalated += 1
            else:
                await self._file_flake_issue(test_id, count, runs)
                filed += 1
            dedup.add(key)
            self._dedup.set_all(dedup)

        self._emit_trace(t0, runs_seen=len(runs))
        return {
            "status": "ok",
            "filed": filed,
            "escalated": escalated,
            "tests_seen": len(counts),
        }

    def _emit_trace(self, t0: float, *, runs_seen: int) -> None:
        try:
            from trace_collector import (  # noqa: PLC0415
                emit_loop_subprocess_trace,
            )
        except ImportError:
            return
        duration_ms = int((time.perf_counter() - t0) * 1000)
        emit_loop_subprocess_trace(
            loop=self._worker_name,
            command=["gh", "run", "list", "rc-promotion-scenario.yml"],
            exit_code=0,
            duration_ms=duration_ms,
            stderr_excerpt=f"runs_seen={runs_seen}",
        )
