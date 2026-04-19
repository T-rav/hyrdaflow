"""MockWorld — composable test world for scenario testing.

Wraps PipelineHarness with stateful fakes so scenarios can seed a world,
run the pipeline, and assert on the world's final state.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tests.conftest import TaskFactory
from tests.helpers import PipelineHarness, PipelineRunResult
from tests.scenarios.catalog import LoopCatalog
from tests.scenarios.catalog import (
    loop_registrations as _loop_registrations,  # noqa: F401
)
from tests.scenarios.fakes.fake_clock import FakeClock
from tests.scenarios.fakes.fake_docker import FakeDocker
from tests.scenarios.fakes.fake_fs import FakeFS
from tests.scenarios.fakes.fake_git import FakeGit
from tests.scenarios.fakes.fake_github import FakeGitHub
from tests.scenarios.fakes.fake_hindsight import FakeHindsight
from tests.scenarios.fakes.fake_http import FakeHTTP
from tests.scenarios.fakes.fake_llm import FakeLLM
from tests.scenarios.fakes.fake_sentry import FakeSentry
from tests.scenarios.fakes.fake_workspace import FakeWorkspace
from tests.scenarios.fakes.scenario_result import IssueOutcome, ScenarioResult


class MockWorld:
    """Composable test world for scenario testing."""

    def __init__(
        self,
        tmp_path: Path,
        *,
        config: Any = None,
        install_subprocess_clock: bool = False,
        use_real_agent_runner: bool = False,
        clock_start: float | str | None = None,
    ) -> None:
        self._tmp_path = tmp_path
        self._use_real_agent = use_real_agent_runner
        self._harness = PipelineHarness(tmp_path, config=config)
        self._llm = FakeLLM()
        self._github = FakeGitHub()
        self._hindsight = FakeHindsight()
        self._sentry = FakeSentry()
        self._workspace = FakeWorkspace(tmp_path / "worktrees")
        self._clock = FakeClock(start=time.time())
        if clock_start is not None:
            self._clock.freeze(clock_start)
        self._docker = FakeDocker()
        self._git = FakeGit()
        self._fs = FakeFS()
        self._http = FakeHTTP()
        self._issues: dict[int, dict[str, Any]] = {}
        self._phase_hooks: list[tuple[str, Callable[[], None]]] = []
        self._ran = False
        self._dashboard: Any = None
        self._dashboard_url: str | None = None

        self._wire_targets(self._harness)

        if self._use_real_agent:
            from tests.scenarios.helpers.agent_runner_factory import (  # noqa: PLC0415
                build_real_agent_runner,
            )

            self._harness.set_agents(
                build_real_agent_runner(
                    docker=self._docker,
                    hindsight=self._hindsight,
                    event_bus=self._harness.bus,
                    tmp_path=self._tmp_path,
                )
            )

        if install_subprocess_clock:
            self._clock.install_subprocess_clock()

    def _wire_targets(self, target: Any) -> None:
        """Patch runner/PR/workspace attributes on ``target`` to this world's fakes.

        ``target`` must expose ``.prs``, ``.triage_runner``, ``.planners``,
        ``.agents``, ``.reviewers``, and ``.workspaces`` objects whose methods
        are replaceable. Works for both ``PipelineHarness`` and a small
        duck-typed wrapper around the service registry on a real
        ``HydraFlowOrchestrator`` (used in Task 9).
        """
        # Runners
        target.triage_runner.evaluate = self._llm.triage_runner.evaluate
        target.triage_runner.run_decomposition = (
            self._llm.triage_runner.run_decomposition
        )
        target.planners.plan = self._llm.planners.plan
        target.planners.run_gap_review = self._llm.planners.run_gap_review
        target.agents.run = self._llm.agents.run
        target.reviewers.review = self._llm.reviewers.review
        target.reviewers.fix_ci = self._llm.reviewers.fix_ci

        # PRs
        prs = target.prs
        gh = self._github
        for method in (
            "transition",
            "swap_pipeline_labels",
            "add_labels",
            "remove_label",
            "post_comment",
            "post_pr_comment",
            "submit_review",
            "create_task",
            "close_task",
            "close_issue",
            "find_existing_issue",
            "push_branch",
            "create_pr",
            "find_open_pr_for_branch",
            "branch_has_diff_from_main",
            "add_pr_labels",
            "get_pr_diff",
            "get_pr_head_sha",
            "get_pr_diff_names",
            "get_pr_approvers",
            "fetch_code_scanning_alerts",
            "wait_for_ci",
            "fetch_ci_failure_logs",
            "merge_pr",
        ):
            setattr(prs, method, getattr(gh, method))

        # Workspaces
        target.workspaces.create = self._workspace.create
        target.workspaces.destroy = self._workspace.destroy

    def _wire_runners(self) -> None:
        """Backward-compatible wrapper — delegates to _wire_targets."""
        self._wire_targets(self._harness)

    def _wire_prs(self) -> None:
        """Backward-compatible wrapper — delegates to _wire_targets."""
        self._wire_targets(self._harness)

    def _wire_workspaces(self) -> None:
        """Backward-compatible wrapper — delegates to _wire_targets."""
        self._wire_targets(self._harness)

    # --- Seed API (fluent, returns self) ---

    def add_issue(
        self,
        number: int,
        title: str,
        body: str,
        labels: list[str] | None = None,
    ) -> MockWorld:
        self._issues[number] = {
            "number": number,
            "title": title,
            "body": body,
            "labels": labels or ["hydraflow-find"],
        }
        self._github.add_issue(number, title, body, labels=labels)
        return self

    def add_repo(self, slug: str, path: str) -> MockWorld:
        """Seed an entry into the RepoRegistryStore rooted at tmp_path.

        Scenarios that exercise multi-repo controls (register / remove)
        start with this rather than driving the UI's 'Add repo' button.
        """
        from repo_store import RepoRecord, RepoRegistryStore  # noqa: PLC0415

        store = RepoRegistryStore(self._tmp_path)
        store.upsert(RepoRecord(slug=slug, repo=slug, path=path))
        return self

    def set_phase_result(self, phase: str, issue: int, result: Any) -> MockWorld:
        return self.set_phase_results(phase, issue, [result])

    def set_phase_results(
        self, phase: str, issue: int, results: list[Any]
    ) -> MockWorld:
        phase_map = {
            "triage": self._llm.script_triage,
            "plan": self._llm.script_plan,
            "implement": self._llm.script_implement,
            "review": self._llm.script_review,
        }
        script_fn = phase_map.get(phase)
        if script_fn is None:
            msg = f"Unknown phase: {phase}; valid: {list(phase_map)}"
            raise ValueError(msg)
        script_fn(issue, results)
        return self

    def on_phase(self, phase: str, callback: Callable[[], None]) -> MockWorld:
        self._phase_hooks.append((phase, callback))
        return self

    def fail_service(
        self, name: str, _error: type[Exception] = ConnectionError
    ) -> MockWorld:
        if name == "hindsight":
            self._hindsight.set_failing(True)
        elif name == "docker":
            self._docker.fail_next(kind="exit_nonzero")
        elif name == "github":
            self._github.set_rate_limit_mode(remaining=0)
        else:
            msg = f"unknown service: {name}"
            raise ValueError(msg)
        return self

    def heal_service(self, name: str) -> MockWorld:
        if name == "hindsight":
            self._hindsight.set_failing(False)
        elif name == "github":
            self._github.clear_rate_limit()
        elif name == "docker":
            self._docker.clear_fault()
        else:
            msg = f"unknown service: {name}"
            raise ValueError(msg)
        return self

    # --- Inspect world state ---

    @property
    def github(self) -> FakeGitHub:
        return self._github

    @property
    def hindsight(self) -> FakeHindsight:
        return self._hindsight

    @property
    def sentry(self) -> FakeSentry:
        return self._sentry

    @property
    def clock(self) -> FakeClock:
        return self._clock

    @property
    def harness(self) -> PipelineHarness:
        return self._harness

    @property
    def docker(self) -> FakeDocker:
        return self._docker

    @property
    def git(self) -> FakeGit:
        return self._git

    @property
    def fs(self) -> FakeFS:
        return self._fs

    @property
    def http(self) -> FakeHTTP:
        return self._http

    # --- Run ---

    def _fire_hooks(self, phase: str) -> None:
        for hook_phase, callback in self._phase_hooks:
            if hook_phase == phase:
                callback()

    async def run_pipeline(self) -> ScenarioResult:
        """Run all seeded issues through the full pipeline."""
        if self._ran:
            msg = (
                "MockWorld.run_pipeline is single-shot; create a new MockWorld "
                "to run again. Re-use would re-seed issues against stale fake state."
            )
            raise RuntimeError(msg)
        self._ran = True
        h = self._harness
        start = time.monotonic()

        for info in self._issues.values():
            tags = info.get("labels", ["hydraflow-find"])
            task = TaskFactory.create(
                id=info["number"],
                title=info["title"],
                body=info["body"],
                tags=tags,
            )
            h.seed_issue(task, stage="find")

        snapshots: dict[str, Any] = {}

        def _capture(label: str) -> None:
            snapshots[label] = h.store.get_queue_stats().model_copy(deep=True)

        # Triage
        self._fire_hooks("triage")
        triaged = await h.triage_phase.triage_issues()
        _capture("after_triage")

        # Plan
        self._fire_hooks("plan")
        plan_results = await h.plan_phase.plan_issues()
        _capture("after_plan")

        # Implement
        self._fire_hooks("implement")
        worker_results, _ = await h.implement_phase.run_batch()
        _capture("after_implement")

        # Review
        self._fire_hooks("review")
        review_results: list[Any] = []
        if worker_results:
            prs_to_review = [wr.pr_info for wr in worker_results if wr.pr_info]
            if prs_to_review:
                candidates = h.store.get_reviewable(h.config.batch_size)
                review_results = await h.review_phase.review_prs(
                    prs_to_review, candidates
                )
        _capture("after_review")

        await asyncio.sleep(0)
        events = h.bus.get_history()

        # Build per-issue outcomes
        outcomes: dict[int, IssueOutcome] = {}
        for info in self._issues.values():
            num = info["number"]
            pr_record = self._github.pr_for_issue(num)
            merged = pr_record.merged if pr_record else False

            wr = next((w for w in worker_results if w.issue_number == num), None)
            rr = next((r for r in review_results if r.issue_number == num), None)
            pr_result = next((p for p in plan_results if p.issue_number == num), None)

            if rr and getattr(rr, "merged", False):
                final_stage = "done"
            elif rr:
                final_stage = "review"
            elif wr:
                final_stage = "implement"
            elif pr_result:
                final_stage = "plan"
            else:
                final_stage = "triage"

            labels = (
                self._github.issue(num).labels if num in self._github._issues else []
            )
            outcomes[num] = IssueOutcome(
                number=num,
                final_stage=final_stage,
                plan_result=pr_result,
                worker_result=wr,
                review_result=rr,
                labels=labels,
                merged=merged,
            )

        pipeline_result = PipelineRunResult(
            task=TaskFactory.create(id=0),
            triaged_count=triaged,
            plan_results=plan_results,
            worker_results=worker_results,
            review_results=review_results,
            snapshots=snapshots,
            events=events,
        )

        duration = time.monotonic() - start
        result = ScenarioResult(
            pipeline_results=[pipeline_result],
            duration_seconds=duration,
        )
        result._outcomes = outcomes
        return result

    # --- Loop execution ---

    @property
    def _dependabot_cache(self) -> Any:
        """Expose the dependabot cache mock created by loop_registrations."""
        return self._loop_ports.get("dependabot_cache")

    @property
    def _workspace_gc_state(self) -> Any:
        """Expose the workspace GC state mock created by loop_registrations."""
        return self._loop_ports.get("workspace_gc_state")

    async def run_with_loops(
        self,
        loops: list[str],
        *,
        cycles: int = 1,
    ) -> dict[str, dict[str, Any] | None]:
        """Instantiate and run real BaseBackgroundLoop subclasses via LoopCatalog.

        Invokes ``loop._do_work()`` directly, ``cycles`` times per loop. This
        skips ``loop.run()`` so the sleep/stop_event lifecycle machinery is
        not exercised — scenarios that need graceful-shutdown semantics should
        drive ``loop.run()`` directly rather than use this helper. FakeGitHub
        is wired as the PRPort so loops interact with seeded world state.

        Returns a dict mapping loop name → last ``_do_work()`` stats.
        """
        from tests.helpers import make_bg_loop_deps  # noqa: PLC0415

        bg = make_bg_loop_deps(self._tmp_path)
        call_count = 0
        stop_event = bg.stop_event

        async def _counting_sleep(_seconds: int | float) -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= cycles:
                stop_event.set()
            await asyncio.sleep(0)

        from base_background_loop import LoopDeps  # noqa: PLC0415

        loop_deps = LoopDeps(
            event_bus=bg.bus,
            stop_event=stop_event,
            status_cb=bg.status_cb,
            enabled_cb=bg.enabled_cb,
            sleep_fn=_counting_sleep,
        )
        config = bg.config

        # Persistent ports dict so catalog-allocated mocks survive across calls
        if not hasattr(self, "_loop_ports"):
            self._loop_ports: dict[str, Any] = {
                "github": self._github,
                "workspace": self._workspace,
                "hindsight": self._hindsight,
                "sentry": self._sentry,
                "clock": self._clock,
            }
        else:
            # Keep fakes up-to-date (cheap; they're the same objects)
            self._loop_ports["github"] = self._github
            self._loop_ports["workspace"] = self._workspace

        loop_instances = []
        for name in loops:
            instance = LoopCatalog.instantiate(
                name, ports=self._loop_ports, config=config, deps=loop_deps
            )
            loop_instances.append((name, instance))

        results: dict[str, dict[str, Any] | None] = {}
        for name, loop in loop_instances:
            for _ in range(cycles):
                stats = await loop._do_work()
                results[name] = stats

        return results

    # --- Dashboard lifecycle ---

    @property
    def dashboard_url(self) -> str | None:
        return self._dashboard_url

    async def start_dashboard(self, *, with_orchestrator: bool = False) -> str:
        """Boot HydraFlowDashboard in-process against this world's fakes.

        Returns the base URL (e.g. 'http://127.0.0.1:54321'). Idempotent —
        subsequent calls return the existing URL.

        When ``with_orchestrator`` is True, MockWorld constructs a real
        HydraFlowOrchestrator wired against the fakes (Task 9). Otherwise
        the dashboard serves UI only (this task).
        """
        if self._dashboard_url is not None:
            return self._dashboard_url

        from dashboard import HydraFlowDashboard  # noqa: PLC0415
        from events import EventBus, EventLog  # noqa: PLC0415
        from service_registry import build_state_tracker  # noqa: PLC0415

        config = self._harness.config
        # Force ephemeral port; override static defaults from HydraFlowConfig.
        config.dashboard_host = "127.0.0.1"
        config.dashboard_port = 0

        bus = EventBus(event_log=EventLog(self._tmp_path / "events.jsonl"))
        state = build_state_tracker(config)

        orchestrator = None
        if with_orchestrator:
            orchestrator = await self._build_wired_orchestrator(config, bus, state)

        dashboard = HydraFlowDashboard(
            config=config,
            event_bus=bus,
            state=state,
            orchestrator=orchestrator,
            hindsight_client=self._hindsight,
        )
        await dashboard.start()

        port = await self._await_dashboard_port(dashboard)
        self._dashboard = dashboard
        self._dashboard_url = f"http://127.0.0.1:{port}"
        return self._dashboard_url

    async def stop_dashboard(self) -> None:
        """Shut down uvicorn task, stop orchestrator if present."""
        if self._dashboard is None:
            return
        try:
            if self._dashboard._orchestrator and self._dashboard._orchestrator.running:
                await self._dashboard._orchestrator.stop()

            uv_server = getattr(self._dashboard, "_uvicorn_server", None)
            if uv_server is not None:
                uv_server.should_exit = True
                # Close bound listener sockets synchronously so the port is
                # released before we return. Uvicorn's graceful shutdown can
                # take seconds; explicit close avoids flake.
                for s in uv_server.servers:
                    s.close()
                    await s.wait_closed()

            await asyncio.wait_for(self._dashboard.stop(), timeout=5)
        finally:
            self._dashboard = None
            self._dashboard_url = None

    async def _await_dashboard_port(self, dashboard: Any, timeout: float = 5.0) -> int:
        """Poll ``dashboard._uvicorn_server`` for the bound port up to ``timeout`` seconds."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            uv_server = getattr(dashboard, "_uvicorn_server", None)
            if uv_server and uv_server.started and uv_server.servers:
                sock = uv_server.servers[0].sockets[0]
                return int(sock.getsockname()[1])
            await asyncio.sleep(0.05)
        raise TimeoutError("dashboard did not bind a port within 5s")

    async def _build_wired_orchestrator(self, config: Any, bus: Any, state: Any) -> Any:
        """Stub — implemented in Task 9."""
        raise NotImplementedError("with_orchestrator=True is implemented in Task 9")
