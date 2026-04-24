"""RCBudgetLoop — 4h RC CI wall-clock regression detector (spec §4.8).

Reads the last 30 days of ``rc-promotion-scenario.yml`` runs via ``gh
run list``, extracts per-run wall-clock duration, and emits a
``hydraflow-find`` + ``rc-duration-regression`` issue when the newest
run trips either:

- *Gradual bloat*: ``current_s >= rc_budget_threshold_ratio *
  rolling_median`` (default ratio ``1.5``).
- *Sudden spike*: ``current_s >= rc_budget_spike_ratio * max(recent-5,
  excluding current)`` (default ratio ``2.0``).

Signals are independent; both may fire on the same tick (two distinct
dedup keys). After 3 unresolved attempts per signal the loop files a
``hitl-escalation`` + ``rc-duration-stuck`` issue. Dedup keys clear on
escalation-close per spec §3.2.

Kill-switch: ``LoopDeps.enabled_cb("rc_budget")`` — **no
``rc_budget_enabled`` config field** (spec §12.2).
"""

from __future__ import annotations

import asyncio
import json
import logging
import statistics
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps  # noqa: TCH001
from models import WorkCycleResult  # noqa: TCH001

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from dedup_store import DedupStore
    from pr_manager import PRManager
    from state import StateTracker

logger = logging.getLogger("hydraflow.rc_budget_loop")

_MAX_ATTEMPTS = 3
_WINDOW_DAYS = 30
_HISTORY_CAP = 60
_RECENT_N = 5
_MIN_HISTORY = 5
_WORKFLOW = "rc-promotion-scenario.yml"


def _parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp (allowing trailing ``Z``); return None on err."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class RCBudgetLoop(BaseBackgroundLoop):
    """Detects RC wall-clock bloat via median + spike signals (spec §4.8)."""

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
            worker_name="rc_budget",
            config=config,
            deps=deps,
            run_on_startup=False,
        )
        self._state = state
        self._pr = pr_manager
        self._dedup = dedup

    def _get_default_interval(self) -> int:
        return self._config.rc_budget_interval

    async def _do_work(self) -> WorkCycleResult:
        """Run one tick: reconcile closures, fetch runs, detect, file/escalate."""
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}

        t0 = time.perf_counter()
        await self._reconcile_closed_escalations()
        runs = await self._fetch_recent_runs()
        if len(runs) < _MIN_HISTORY:
            return {"status": "warmup", "runs_seen": len(runs)}

        self._state.set_rc_budget_duration_history(
            [
                {
                    "run_id": int(r.get("databaseId", 0)),
                    "created_at": str(r.get("createdAt", "")),
                    "duration_s": int(r["duration_s"]),
                    "conclusion": str(r.get("conclusion", "")),
                }
                for r in runs
            ]
        )

        current, baselines = self._compute_baselines(runs)
        signals = self._check_signals(current, baselines)

        filed = 0
        escalated = 0
        dedup = set(self._dedup.get())
        previous_5 = [r for r in runs if r is not current][:5]
        jobs: list[dict[str, Any]] = []
        junit_tests: list[tuple[str, float]] = []
        if signals:
            jobs = await self._fetch_job_breakdown(current)
            junit_tests = await self._fetch_junit_tests(current)

        for kind, baseline_s in signals:
            key = f"rc_budget:{kind}"
            if key in dedup:
                continue
            attempts = self._state.inc_rc_budget_attempts(kind)
            if attempts >= _MAX_ATTEMPTS:
                await self._file_escalation(kind, attempts)
                escalated += 1
            else:
                await self._file_regression_issue(
                    kind=kind,
                    current=current,
                    baseline_s=baseline_s,
                    baselines=baselines,
                    previous_5=previous_5,
                    jobs=jobs,
                    junit_tests=junit_tests,
                )
                filed += 1
            dedup.add(key)
            self._dedup.set_all(dedup)

        self._emit_trace(t0, runs_seen=len(runs), signals=len(signals))
        return {
            "status": "ok",
            "runs_seen": len(runs),
            "filed": filed,
            "escalated": escalated,
            "current_duration_s": int(current["duration_s"]),
            "rolling_median_s": baselines["rolling_median"],
            "recent_max_s": baselines["recent_max"],
        }

    async def _fetch_recent_runs(self) -> list[dict[str, Any]]:
        """Fetch last 30 days of completed RC runs with per-run wall-clock."""
        cmd = [
            "gh",
            "run",
            "list",
            "--repo",
            self._config.repo,
            "--workflow",
            _WORKFLOW,
            "--limit",
            "100",
            "--status",
            "completed",
            "--json",
            "databaseId,url,conclusion,createdAt,updatedAt,startedAt",
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
            raw = json.loads(stdout.decode() or "[]")
        except json.JSONDecodeError:
            return []
        cutoff = datetime.now(UTC) - timedelta(days=_WINDOW_DAYS)
        out: list[dict[str, Any]] = []
        for run in raw:
            created = _parse_iso(run.get("createdAt"))
            started = _parse_iso(run.get("startedAt") or run.get("createdAt"))
            updated = _parse_iso(run.get("updatedAt"))
            if not created or not started or not updated or created < cutoff:
                continue
            out.append(
                {
                    **run,
                    "duration_s": max(0, int((updated - started).total_seconds())),
                }
            )
        out.sort(key=lambda r: r.get("createdAt", ""), reverse=True)
        return out[:_HISTORY_CAP]

    def _compute_baselines(
        self, runs: list[dict[str, Any]]
    ) -> tuple[dict[str, Any], dict[str, int]]:
        """Return ``(current, {rolling_median, recent_max})`` excluding current."""
        current = max(runs, key=lambda r: r.get("createdAt", ""))
        others = [r for r in runs if r.get("databaseId") != current.get("databaseId")]
        others.sort(key=lambda r: r.get("createdAt", ""), reverse=True)
        durations = [int(r["duration_s"]) for r in others]
        recent = durations[:_RECENT_N]
        return current, {
            "rolling_median": (int(statistics.median(durations)) if durations else 0),
            "recent_max": max(recent) if recent else 0,
        }

    def _check_signals(
        self, current: dict[str, Any], baselines: dict[str, int]
    ) -> list[tuple[str, int]]:
        """Return ``[(kind, baseline_s), ...]`` where kind in {median, spike}.

        Spec §4.8 + sibling plan: ``>=`` comparison.
        """
        cfg = self._config
        cur = int(current["duration_s"])
        hits: list[tuple[str, int]] = []
        m, r = baselines["rolling_median"], baselines["recent_max"]
        if m > 0 and cur >= cfg.rc_budget_threshold_ratio * m:
            hits.append(("median", m))
        if r > 0 and cur >= cfg.rc_budget_spike_ratio * r:
            hits.append(("spike", r))
        return hits

    async def _fetch_job_breakdown(self, run: dict[str, Any]) -> list[dict[str, Any]]:
        """Return up to 10 slowest jobs for *run* via ``gh run view --json jobs``."""
        run_id = str(run.get("databaseId", ""))
        if not run_id:
            return []
        cmd = [
            "gh",
            "run",
            "view",
            run_id,
            "--repo",
            self._config.repo,
            "--json",
            "jobs",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return []
        try:
            payload = json.loads(stdout.decode() or "{}")
        except json.JSONDecodeError:
            return []
        out: list[dict[str, Any]] = []
        for job in payload.get("jobs") or []:
            s = _parse_iso(job.get("startedAt"))
            c = _parse_iso(job.get("completedAt"))
            if not s or not c:
                continue
            out.append(
                {
                    "name": job.get("name", "?"),
                    "duration_s": max(0, int((c - s).total_seconds())),
                }
            )
        out.sort(key=lambda j: j["duration_s"], reverse=True)
        return out[:10]

    async def _fetch_junit_tests(self, run: dict[str, Any]) -> list[tuple[str, float]]:
        """Return top-10 slowest tests from the ``junit-scenario`` artifact."""
        run_id = str(run.get("databaseId", ""))
        if not run_id:
            return []
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
            await proc.communicate()
            if proc.returncode != 0:
                return []
            results: list[tuple[str, float]] = []
            for xml_path in Path(td).rglob("*.xml"):
                try:
                    root = ET.fromstring(  # nosec B314 — JUnit XML from trusted CI artifacts
                        xml_path.read_bytes()
                    )
                except ET.ParseError:
                    continue
                for case in root.iter("testcase"):
                    cls = case.get("classname") or ""
                    name = case.get("name") or ""
                    test_id = f"{cls}.{name}".lstrip(".")
                    try:
                        dur = float(case.get("time") or 0.0)
                    except ValueError:
                        dur = 0.0
                    results.append((test_id, dur))
        results.sort(key=lambda t: t[1], reverse=True)
        return results[:10]

    async def _file_regression_issue(
        self,
        *,
        kind: str,
        current: dict[str, Any],
        baseline_s: int,
        baselines: dict[str, int],
        previous_5: list[dict[str, Any]],
        jobs: list[dict[str, Any]],
        junit_tests: list[tuple[str, float]],
    ) -> int:
        """File a ``hydraflow-find`` + ``rc-duration-regression`` issue."""
        cfg = self._config
        cur = int(current["duration_s"])
        title = (
            f"RC gate duration regression: {cur}s vs {baseline_s}s "
            f"({'spike' if kind == 'spike' else 'median'})"
        )
        job_lines = (
            "\n".join(f"- `{j['name']}` — {j['duration_s']}s" for j in jobs)
            or "_(job breakdown unavailable)_"
        )
        test_lines = (
            "\n".join(f"- `{t}` — {d:.2f}s" for t, d in junit_tests)
            or "_(junit-scenario artifact absent — top-10 tests elided)_"
        )
        prev_lines = "\n".join(
            f"- run {r.get('databaseId', '?')} "
            f"({r.get('createdAt', '?')}) — {int(r['duration_s'])}s"
            for r in previous_5
        )
        body = (
            f"## RC wall-clock regression (signal: `{kind}`)\n\n"
            f"Run [{current.get('databaseId', '?')}]({current.get('url', '')}) "
            f"took **{cur}s**. Trips `{kind}`:\n\n"
            f"- Current: **{cur}s**\n"
            f"- Rolling 30d median: **{baselines['rolling_median']}s** "
            f"(threshold_ratio `{cfg.rc_budget_threshold_ratio}` → fires at "
            f"`{int(cfg.rc_budget_threshold_ratio * baselines['rolling_median'])}s`)\n"
            f"- Max of recent 5 (excl. current): **{baselines['recent_max']}s** "
            f"(spike_ratio `{cfg.rc_budget_spike_ratio}` → fires at "
            f"`{int(cfg.rc_budget_spike_ratio * baselines['recent_max'])}s`)\n\n"
            f"### Previous 5 runs\n{prev_lines}\n\n"
            f"### Per-job breakdown (top 10)\n{job_lines}\n\n"
            f"### Top-10 slowest tests\n{test_lines}\n\n"
            f"_Auto-filed by HydraFlow `rc_budget` (spec §4.8). "
            f"Escalates after 3 unresolved attempts._"
        )
        return await self._pr.create_issue(
            title, body, ["hydraflow-find", "rc-duration-regression"]
        )

    async def _file_escalation(self, kind: str, attempts: int) -> int:
        """File a ``hitl-escalation`` + ``rc-duration-stuck`` issue."""
        title = (
            f"HITL: RC gate duration regression ({kind}) unresolved after "
            f"{attempts} attempts"
        )
        body = (
            f"`rc_budget` filed `rc-duration-regression` for `{kind}` "
            f"{attempts} times without closure. Close this to clear the "
            f"`rc_budget:{kind}` dedup key (spec §3.2)."
        )
        return await self._pr.create_issue(
            title, body, ["hitl-escalation", "rc-duration-stuck"]
        )

    async def _reconcile_closed_escalations(self) -> None:
        """Clear dedup keys + attempt counters for closed HITL issues (§3.2)."""
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
            "rc-duration-stuck",
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
            for kind in ("median", "spike"):
                key = f"rc_budget:{kind}"
                if key in keep and f"({kind})" in title:
                    keep.discard(key)
                    self._state.clear_rc_budget_attempts(kind)
        if keep != current:
            self._dedup.set_all(keep)

    def _emit_trace(self, t0: float, *, runs_seen: int, signals: int) -> None:
        """Best-effort subprocess trace via lazy-imported ``trace_collector``."""
        try:
            from trace_collector import emit_loop_subprocess_trace  # noqa: PLC0415
        except ImportError:
            return
        duration_ms = int((time.perf_counter() - t0) * 1000)
        emit_loop_subprocess_trace(
            loop=self._worker_name,
            command=["gh", "run", "list", _WORKFLOW],
            exit_code=0,
            duration_ms=duration_ms,
            stderr_excerpt=f"runs_seen={runs_seen} signals={signals}",
        )
