"""ContractRefreshLoop — weekly cassette refresh for fake contract tests (§4.2).

Tick body (Tasks 15 + 16 + 20 wired; Tasks 17/18/19 still pending):

1. Record cassettes against live ``gh``/``git``/``docker``/``claude`` into a
   tmp directory (``contract_recording.record_*``).
2. Diff the fresh recordings against the committed cassettes
   (``contract_diff.detect_fleet_drift``). No drift → status dict with
   ``adapters_drifted=0``.
3. If drift is detected, hash the drift report and look the hash up in a
   per-loop :class:`DedupStore`. Hash hit → short-circuit so identical
   drift on back-to-back ticks does not refile the same PR.
4. Stage the drifted/new cassettes into the worktree (their committed
   paths under ``tests/trust/contracts/``) and open a refresh PR via
   :func:`auto_pr.open_automated_pr_async` — title ``contract-refresh:
   YYYY-MM-DD (<adapters>)``, body summarising per-adapter slugs, labels
   ``contract-refresh`` + ``auto-merge``, ``auto_merge=True``,
   ``raise_on_failure=False``.
5. Post-refresh replay gate (Task 16): invoke ``make trust-contracts``
   via :func:`subprocess.run`. Pass → clean exit. Fail → the fresh
   cassettes have outrun the fakes; file a ``hydraflow-find`` +
   ``fake-drift`` companion issue via ``PRManager.create_issue`` so the
   factory dispatches a fake-repair implementer. Success of the PR's
   auto-merge is not gated on replay; the replay gate only decides
   whether to file the companion issue. Dedup is recorded only once the
   PR has actually been opened so a transient failure does not silently
   block the next tick.

Task 20 wires per-loop telemetry: every recorder subprocess and the
replay gate emit one
:func:`trace_collector.emit_loop_subprocess_trace` entry under
``loop="contract_refresh"`` so deploy-time observability can flag a
silently-broken recorder (empty list + zero latency) or a slow replay
gate without cracking open the loop. The ``command`` field is the
symbolic recorder label (e.g. ``contract_recording.record_github``);
the real argv lives inside :mod:`contract_recording` and does not
round-trip here.

Kill-switch: :meth:`LoopDeps.enabled_cb` with
``worker_name="contract_refresh"``.

Spec: ``docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md``
§4.2 "ContractRefreshLoop — full caretaker (refresh + auto-repair)".
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import trace_collector
from auto_pr import open_automated_pr_async
from base_background_loop import BaseBackgroundLoop, LoopDeps  # noqa: TCH001
from contract_diff import (
    AdapterDriftReport,
    FleetDriftReport,
    detect_fleet_drift,
)
from contract_recording import (
    record_claude_stream,
    record_docker,
    record_git,
    record_github,
)
from dedup_store import DedupStore
from models import WorkCycleResult  # noqa: TCH001

if TYPE_CHECKING:
    from collections.abc import Callable

    from config import HydraFlowConfig
    from pr_manager import PRManager
    from state import StateTracker

logger = logging.getLogger("hydraflow.contract_refresh_loop")

# The committed sandbox repo the GitHub recorder targets. Centralised here
# so tests (and the eventual config field in Task 18+) can override in one
# place. Matches ``docs/superpowers/plans/2026-04-22-fake-contract-tests.md``
# Task 0.
_SANDBOX_GITHUB_REPO = "T-rav-Hydra-Ops/hydraflow-contracts-sandbox"

# Hard cap on the replay-gate subprocess — defends the async event loop
# when a recorder hangs on network I/O or a zombie subprocess.
_REPLAY_GATE_TIMEOUT_SECONDS = 300
# Fixture git sandbox seeded by Task 0 (relative to ``repo_root``).
_GIT_SANDBOX_RELPATH = "tests/trust/contracts/fixtures/git_sandbox"


@dataclass(frozen=True)
class AdapterPlan:
    """Per-adapter recording configuration.

    The ``name`` field identifies the adapter (``github``/``git``/``docker``/
    ``claude``); ``cassette_dir_relpath`` points at the committed cassette
    directory relative to the repo root. Tasks 13–18 consume these entries
    to drive per-adapter recording, diffing, and drift escalation.
    """

    name: str  # "github" | "git" | "docker" | "claude"
    cassette_dir_relpath: str  # under repo_root


ADAPTER_PLANS: tuple[AdapterPlan, ...] = (
    AdapterPlan(
        name="github", cassette_dir_relpath="tests/trust/contracts/cassettes/github"
    ),
    AdapterPlan(name="git", cassette_dir_relpath="tests/trust/contracts/cassettes/git"),
    AdapterPlan(
        name="docker", cassette_dir_relpath="tests/trust/contracts/cassettes/docker"
    ),
    AdapterPlan(
        name="claude", cassette_dir_relpath="tests/trust/contracts/claude_streams"
    ),
)


class ContractRefreshLoop(BaseBackgroundLoop):
    """Weekly refresh of fake-contract cassettes with autonomous repair dispatch.

    Tick body (Tasks 15 + 16 + 20) records, diffs, stages, PR-files,
    replay-gates, and emits per-subprocess telemetry. Tasks 17+ add:

    * Stream-protocol drift routing (`stream-protocol-drift` issues).
    * Per-adapter 3-attempt repair tracker; exhaustion →
      ``hitl-escalation`` + ``fake-repair-stuck`` / ``stream-parser-stuck``.
    """

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        deps: LoopDeps,
        prs: PRManager,
        state: StateTracker,
    ) -> None:
        super().__init__(
            worker_name="contract_refresh",
            config=config,
            deps=deps,
            run_on_startup=False,
        )
        self._prs = prs
        self._state = state
        self._dedup = DedupStore(
            "contract_refresh",
            config.data_root / "dedup" / "contract_refresh.json",
        )
        # Task 18 — separate dedup set keyed on adapter name so a stuck
        # adapter's hitl-escalation issue is filed at most once per stuck
        # streak. Cleared per-adapter on a clean tick so the next streak
        # can re-escalate.
        self._escalation_dedup = DedupStore(
            "contract_refresh_escalations",
            config.data_root / "dedup" / "contract_refresh_escalations.json",
        )

    def _get_default_interval(self) -> int:
        return self._config.contract_refresh_interval

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def _record_all(self, tmp_root: Path) -> dict[str, list[Path]]:
        """Run each adapter's recorder into a dedicated tmp subdirectory.

        Returns a ``{adapter_name: [recorded_paths]}`` mapping suitable
        for :func:`contract_diff.detect_fleet_drift`. An empty list for
        an adapter is the recorder's way of signalling "tool missing /
        sandbox offline" — the diff layer already treats that as
        no-signal (vs a catastrophic all-deleted sweep).

        Each recorder call is wrapped in a
        :func:`trace_collector.emit_loop_subprocess_trace` (Task 20) so
        deploy-time observability can flag a silently-broken recorder
        (empty list + zero latency) or a slow adapter without opening
        the loop. The synthetic ``command`` identifies the recorder
        symbolically; the real argv lives inside :mod:`contract_recording`
        and does not round-trip here.
        """
        sandbox_dir = self._config.repo_root / _GIT_SANDBOX_RELPATH

        recorded: dict[str, list[Path]] = {}
        recorded["github"] = self._record_with_trace(
            "contract_recording.record_github",
            record_github,
            _SANDBOX_GITHUB_REPO,
            tmp_root / "github",
        )
        recorded["git"] = self._record_with_trace(
            "contract_recording.record_git",
            record_git,
            sandbox_dir,
            tmp_root / "git",
        )
        recorded["docker"] = self._record_with_trace(
            "contract_recording.record_docker",
            record_docker,
            tmp_root / "docker",
        )
        recorded["claude"] = self._record_with_trace(
            "contract_recording.record_claude_stream",
            record_claude_stream,
            tmp_root / "claude",
        )
        return recorded

    def _record_with_trace(
        self,
        label: str,
        recorder: Callable[..., list[Path]],
        *args: Any,
    ) -> list[Path]:
        """Invoke *recorder* and emit one per-loop subprocess trace (Task 20).

        ``exit_code`` is synthesized from the recorder's observable
        outcome: ``0`` if the recorder returned at least one path, ``1``
        if it returned an empty list (the "binary missing / sandbox
        offline" signal documented in :mod:`contract_recording`). An
        unhandled exception is surfaced as ``exit_code=2`` + the
        exception message, then re-raised — we refuse to swallow
        recorder crashes but must ensure telemetry sees them first.
        """
        t0 = time.perf_counter()
        try:
            result = recorder(*args)
        except Exception as exc:
            duration_ms = int((time.perf_counter() - t0) * 1000)
            trace_collector.emit_loop_subprocess_trace(
                loop=self._worker_name,
                command=[label],
                exit_code=2,
                duration_ms=duration_ms,
                stderr_excerpt=str(exc),
            )
            raise
        duration_ms = int((time.perf_counter() - t0) * 1000)
        trace_collector.emit_loop_subprocess_trace(
            loop=self._worker_name,
            command=[label],
            exit_code=0 if result else 1,
            duration_ms=duration_ms,
            stderr_excerpt=None if result else "recorder returned no cassettes",
        )
        return result

    # ------------------------------------------------------------------
    # Drift → PR
    # ------------------------------------------------------------------

    def _dedup_key(self, fleet: FleetDriftReport) -> str:
        """Stable content hash keyed on the drifted/new/deleted slug sets.

        Volatile metadata inside each cassette is already stripped by
        :func:`contract_diff._canonical_payload`, so keying off filename
        sets is sufficient: two ticks that diff the same slugs the same
        way against the same committed tree will produce the same key.
        """
        payload = {
            "reports": [
                {
                    "adapter": r.adapter,
                    "drifted": sorted(p.name for p in r.drifted_cassettes),
                    "new": sorted(p.name for p in r.new_cassettes),
                    "deleted": sorted(p.name for p in r.deleted_cassettes),
                }
                for r in sorted(fleet.reports, key=lambda r: r.adapter)
            ]
        }
        blob = json.dumps(payload, sort_keys=True).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()

    def _stage_drifted_cassettes(self, reports: list[AdapterDriftReport]) -> list[Path]:
        """Copy each drifted/new cassette into its committed path under ``repo_root``.

        ``auto_pr.open_automated_pr_async`` reads the file bytes from the
        paths we return and stages them into the ephemeral worktree, so
        we *must* write to paths under ``repo_root``. Returns the list
        of committed paths that now hold the fresh bytes.
        """
        written: list[Path] = []
        plans_by_name = {p.name: p for p in ADAPTER_PLANS}
        for report in reports:
            plan = plans_by_name[report.adapter]
            committed_dir = self._config.repo_root / plan.cassette_dir_relpath
            committed_dir.mkdir(parents=True, exist_ok=True)
            for src in [*report.drifted_cassettes, *report.new_cassettes]:
                dst = committed_dir / src.name
                dst.write_bytes(src.read_bytes())
                written.append(dst)
        return written

    def _pr_title_and_body(
        self, fleet: FleetDriftReport, stamp: str
    ) -> tuple[str, str]:
        adapters_drifted = sorted({r.adapter for r in fleet.reports})
        adapters_joined = ", ".join(adapters_drifted)
        title = f"contract-refresh: {stamp} ({adapters_joined})"

        body_lines: list[str] = [
            "Automated cassette refresh by `ContractRefreshLoop`.",
            "",
            f"Adapters drifted: **{adapters_joined}**.",
            "",
            "Per-adapter slugs:",
        ]
        for report in sorted(fleet.reports, key=lambda r: r.adapter):
            drifted_names = sorted(p.name for p in report.drifted_cassettes)
            new_names = sorted(p.name for p in report.new_cassettes)
            deleted_names = sorted(p.name for p in report.deleted_cassettes)
            segments: list[str] = []
            if drifted_names:
                segments.append("drifted=" + ",".join(drifted_names))
            if new_names:
                segments.append("new=" + ",".join(new_names))
            if deleted_names:
                segments.append("deleted=" + ",".join(deleted_names))
            body_lines.append(f"- `{report.adapter}`: " + "; ".join(segments))
        body_lines.extend(
            [
                "",
                (
                    "Replay gate (`make trust-contracts`) runs after PR opens; on "
                    "failure a `fake-drift` companion issue routes repair through "
                    "the factory."
                ),
            ]
        )
        return title, "\n".join(body_lines)

    async def _open_refresh_pr(
        self, written: list[Path], fleet: FleetDriftReport
    ) -> str | None:
        stamp = datetime.now(UTC).strftime("%Y-%m-%d")
        branch = f"contract-refresh/{stamp}"
        title, body = self._pr_title_and_body(fleet, stamp)

        result = await open_automated_pr_async(
            repo_root=self._config.repo_root,
            branch=branch,
            files=written,
            pr_title=title,
            pr_body=body,
            commit_message=title,
            auto_merge=True,
            raise_on_failure=False,
            labels=["contract-refresh", "auto-merge"],
        )
        if result.status not in ("opened",):
            logger.warning(
                "contract_refresh: PR creation returned status=%s error=%s",
                result.status,
                getattr(result, "error", None),
            )
            return None
        return result.pr_url

    # ------------------------------------------------------------------
    # Replay gate (Task 16)
    # ------------------------------------------------------------------

    def _run_replay_gate(self) -> subprocess.CompletedProcess[str]:
        """Invoke ``make trust-contracts`` and capture its output.

        Synchronous on purpose: the refresh tick runs once a week and
        wrapping this in ``asyncio.create_subprocess_exec`` would add
        complexity for no real benefit.

        Task 20 wraps the call in
        :func:`trace_collector.emit_loop_subprocess_trace` so the replay
        gate's exit code + stderr tail land on the fleet-observability
        stream regardless of whether a companion issue fires.

        Hard timeout defends the orchestrator: a hung recording cassette
        (network call inside a recorder, zombie subprocess, etc.) must
        not stall the entire async event loop indefinitely. On
        ``TimeoutExpired`` we synthesize a non-zero CompletedProcess so
        the caller routes the timeout through the fake-drift companion
        path.
        """
        cmd = ["make", "trust-contracts"]
        t0 = time.perf_counter()
        try:
            proc = subprocess.run(  # noqa: S603
                cmd,
                cwd=str(self._config.repo_root),
                capture_output=True,
                text=True,
                check=False,
                timeout=_REPLAY_GATE_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            logger.warning(
                "Replay gate timed out after %ss; treating as failure",
                _REPLAY_GATE_TIMEOUT_SECONDS,
            )
            stdout_txt = (
                exc.stdout.decode()
                if isinstance(exc.stdout, bytes)
                else (exc.stdout or "")
            )
            stderr_txt = (
                exc.stderr.decode()
                if isinstance(exc.stderr, bytes)
                else (exc.stderr or "")
            )
            timeout_proc = subprocess.CompletedProcess(
                args=list(exc.cmd)
                if isinstance(exc.cmd, list | tuple)
                else [str(exc.cmd)],
                returncode=124,  # standard bash convention for timeouts
                stdout=stdout_txt,
                stderr=stderr_txt
                + f"\n[replay-gate-timeout {_REPLAY_GATE_TIMEOUT_SECONDS}s]",
            )
            duration_ms = int((time.perf_counter() - t0) * 1000)
            trace_collector.emit_loop_subprocess_trace(
                loop=self._worker_name,
                command=cmd,
                exit_code=124,
                duration_ms=duration_ms,
                stderr_excerpt=(timeout_proc.stderr or "").strip() or None,
            )
            return timeout_proc
        duration_ms = int((time.perf_counter() - t0) * 1000)
        trace_collector.emit_loop_subprocess_trace(
            loop=self._worker_name,
            command=cmd,
            exit_code=proc.returncode,
            duration_ms=duration_ms,
            stderr_excerpt=(proc.stderr or "").strip() or None,
        )
        return proc

    async def _file_fake_drift_issue(
        self,
        adapters: list[str],
        replay_proc: subprocess.CompletedProcess[str],
        pr_url: str | None,
    ) -> int:
        adapters_joined = ", ".join(adapters)
        labels = ["hydraflow-find", "fake-drift"]
        for adapter in adapters:
            labels.append(f"adapter-{adapter}")

        title = (
            f"Fake drift: replay gate failed after contract refresh ({adapters_joined})"
        )
        pr_line = f"Refresh PR: {pr_url}" if pr_url else "Refresh PR: (not opened)"
        # Clip replay output so the issue body stays reviewable.
        stdout_tail = (replay_proc.stdout or "").strip()[-2000:]
        stderr_tail = (replay_proc.stderr or "").strip()[-2000:]
        body = (
            "`ContractRefreshLoop` refreshed cassettes for "
            f"**{adapters_joined}** and the post-refresh replay gate "
            "(`make trust-contracts`) failed — one or more fakes have "
            "diverged from the committed cassette.\n\n"
            f"{pr_line}\n\n"
            "**Repair path.** Check out the refresh branch, run "
            "`PYTHONPATH=src uv run make trust-contracts` locally, inspect the "
            "diff, adjust the matching fake in `tests/scenarios/fakes/`, and "
            "land the fake-side fix PR.\n\n"
            "### replay gate stdout (tail)\n"
            f"```\n{stdout_tail}\n```\n\n"
            "### replay gate stderr (tail)\n"
            f"```\n{stderr_tail}\n```\n"
        )
        return await self._prs.create_issue(
            title=title,
            body=body,
            labels=labels,
        )

    # ------------------------------------------------------------------
    # Task 18 — per-adapter escalation tracker
    # ------------------------------------------------------------------

    def _update_attempt_counters(self, drifted_adapters: set[str]) -> None:
        """Bump drifted adapters; reset the rest (and clear their dedup).

        Called every tick, regardless of dedup — the counter tracks how
        many consecutive ticks an adapter has drifted, not how many
        refresh PRs have been opened. A stuck adapter whose drift is
        dedup-suppressed still counts toward escalation.

        A clean tick for an adapter clears both the attempts counter and
        the escalation dedup entry so the next streak can re-escalate.
        """
        current_escalation_dedup = self._escalation_dedup.get()
        new_escalation_dedup = set(current_escalation_dedup)
        dedup_dirty = False
        for plan in ADAPTER_PLANS:
            if plan.name in drifted_adapters:
                self._state.inc_contract_refresh_attempts(plan.name)
            else:
                if self._state.get_contract_refresh_attempts(plan.name):
                    self._state.clear_contract_refresh_attempts(plan.name)
                if plan.name in new_escalation_dedup:
                    new_escalation_dedup.discard(plan.name)
                    dedup_dirty = True
        if dedup_dirty:
            self._escalation_dedup.set_all(new_escalation_dedup)

    async def _file_escalation_issue(self, adapter: str, attempts: int) -> int:
        """File a ``hitl-escalation`` + ``fake-drift-stuck`` issue for *adapter*.

        Fires when an adapter's consecutive-drift counter reaches
        ``config.max_fake_repair_attempts``. The HITL operator uses the
        adapter name in the label + title to jump straight to the stuck
        fake.
        """
        labels = ["hitl-escalation", "fake-drift-stuck", f"adapter-{adapter}"]
        title = (
            f"Contract refresh stuck: {adapter} has drifted "
            f"{attempts} consecutive ticks"
        )
        body = (
            f"`ContractRefreshLoop` has detected drift on the **{adapter}** "
            f"adapter for {attempts} consecutive ticks without the drift "
            f"clearing. The auto-refresh PR + fake-repair dispatch path has "
            f"not converged.\n\n"
            f"**Repair path.** A human needs to inspect the committed "
            f"cassettes under `tests/trust/contracts/` for the `{adapter}` "
            f"adapter, review the last `contract-refresh/*` PR, and either "
            f"repair the fake in `tests/scenarios/fakes/` or adjust the "
            f"cassette normalizers.\n\n"
            f"This issue dedups on the adapter name — the next clean tick "
            f"for `{adapter}` will clear both the attempt counter and the "
            f"escalation dedup entry, so a future stuck streak can "
            f"re-escalate."
        )
        return await self._prs.create_issue(
            title=title,
            body=body,
            labels=labels,
        )

    async def _maybe_escalate(self, drifted_adapters: set[str]) -> dict[str, int]:
        """File escalation issues for adapters that hit the attempt threshold.

        Dedup via ``self._escalation_dedup`` keyed on adapter name so
        back-to-back stuck ticks file at most one escalation per streak.
        Returns ``{adapter: issue_number}`` for telemetry.
        """
        escalated: dict[str, int] = {}
        threshold = self._config.max_fake_repair_attempts
        dedup_set = self._escalation_dedup.get()
        for adapter in sorted(drifted_adapters):
            attempts = self._state.get_contract_refresh_attempts(adapter)
            if attempts < threshold:
                continue
            if adapter in dedup_set:
                logger.info(
                    "contract_refresh: escalation for %s already filed "
                    "(dedup hit); skipping",
                    adapter,
                )
                continue
            issue_num = await self._file_escalation_issue(adapter, attempts)
            self._escalation_dedup.add(adapter)
            escalated[adapter] = issue_num
            logger.warning(
                "contract_refresh: escalated %s to hitl-escalation "
                "(issue #%d, attempts=%d)",
                adapter,
                issue_num,
                attempts,
            )
        return escalated

    # ------------------------------------------------------------------
    # Tick
    # ------------------------------------------------------------------

    async def _do_work(self) -> WorkCycleResult:
        """Record → diff → (maybe) PR + replay gate + escalation.

        The kill-switch short-circuits with ``{"status": "disabled"}`` so
        the base-class status reporter still has something to publish.
        """
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}

        tmp_root = self._config.data_root / "contract_refresh" / "recordings"
        tmp_root.mkdir(parents=True, exist_ok=True)
        recordings = self._record_all(tmp_root)

        fleet: FleetDriftReport = detect_fleet_drift(recordings, self._config.repo_root)

        # Task 18 — update attempt counters on EVERY tick, before any
        # short-circuits, so dedup-suppressed drift still counts toward
        # escalation and clean ticks reset both the counter and the
        # per-adapter escalation dedup.
        drifted_adapters: set[str] = {r.adapter for r in fleet.reports}
        self._update_attempt_counters(drifted_adapters)

        if not fleet.has_drift:
            # Clean tick: a prior refresh PR has been applied (merged) and
            # the recordings now match committed cassettes. Clear the fleet
            # drift dedup so a *future* identical drift (e.g. a reverted PR
            # re-introduces the same diff) is re-filed rather than silently
            # swallowed. Keeps dedup bounded in size, too.
            if self._dedup.get():
                self._dedup.set_all(set())
            return {
                "status": "clean",
                "adapters_refreshed": 0,
                "adapters_drifted": 0,
            }

        # Task 18 — escalate any adapter that just hit the threshold.
        # Fire before the dedup short-circuit so a stuck adapter whose
        # refresh PR is dedup-suppressed still gets an escalation issue.
        escalated = await self._maybe_escalate(drifted_adapters)

        dedup_key = self._dedup_key(fleet)
        if dedup_key in self._dedup.get():
            logger.info(
                "contract_refresh: drift already dispatched (dedup hit %s)",
                dedup_key[:12],
            )
            return {
                "status": "dedup_hit",
                "adapters_refreshed": 0,
                "adapters_drifted": len(fleet.reports),
                "escalated_adapters": sorted(escalated),
            }

        written = self._stage_drifted_cassettes(fleet.reports)
        pr_url = await self._open_refresh_pr(written, fleet)
        # Only record the dedup key after a successful PR open. A
        # transient failure (branch conflict, ``gh`` auth, push rejection)
        # must not be hidden by dedup — the next tick retries. Without
        # this guard the primary checkout stays dirty with uncommitted
        # cassette writes while dedup blocks re-filing — silent stuck.
        if pr_url is not None:
            self._dedup.add(dedup_key)

        # Task 16 — replay gate. Only filed as fake-drift when the replay
        # suite fails after the refresh PR has been opened.
        replay_proc = self._run_replay_gate()
        fake_drift_issue: int | None = None
        if replay_proc.returncode != 0:
            adapters_drifted = sorted({r.adapter for r in fleet.reports})
            fake_drift_issue = await self._file_fake_drift_issue(
                adapters_drifted, replay_proc, pr_url
            )

        return {
            "status": "refreshed",
            "adapters_refreshed": len(written),
            "adapters_drifted": len(fleet.reports),
            "pr_url": pr_url,
            "replay_gate_passed": replay_proc.returncode == 0,
            "fake_drift_issue": fake_drift_issue,
            "escalated_adapters": sorted(escalated),
        }
