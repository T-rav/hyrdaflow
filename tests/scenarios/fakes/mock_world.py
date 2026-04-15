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
from tests.scenarios.fakes.fake_clock import FakeClock
from tests.scenarios.fakes.fake_github import FakeGitHub
from tests.scenarios.fakes.fake_hindsight import FakeHindsight
from tests.scenarios.fakes.fake_llm import FakeLLM
from tests.scenarios.fakes.fake_sentry import FakeSentry
from tests.scenarios.fakes.fake_workspace import FakeWorkspace
from tests.scenarios.fakes.scenario_result import IssueOutcome, ScenarioResult


class MockWorld:
    """Composable test world for scenario testing."""

    def __init__(self, tmp_path: Path, *, config: Any = None) -> None:
        self._tmp_path = tmp_path
        self._harness = PipelineHarness(tmp_path, config=config)
        self._llm = FakeLLM()
        self._github = FakeGitHub()
        self._hindsight = FakeHindsight()
        self._sentry = FakeSentry()
        self._workspace = FakeWorkspace(tmp_path / "worktrees")
        self._clock = FakeClock(start=time.time())
        self._issues: dict[int, dict[str, Any]] = {}
        self._phase_hooks: list[tuple[str, Callable[[], None]]] = []

        self._wire_runners()
        self._wire_prs()
        self._wire_workspaces()

    def _wire_runners(self) -> None:
        """Replace harness AsyncMock runners with FakeLLM runners."""
        h = self._harness
        h.triage_runner.evaluate = self._llm.triage_runner.evaluate
        h.triage_runner.run_decomposition = self._llm.triage_runner.run_decomposition
        h.planners.plan = self._llm.planners.plan
        h.planners.run_gap_review = self._llm.planners.run_gap_review
        h.agents.run = self._llm.agents.run
        h.reviewers.review = self._llm.reviewers.review
        h.reviewers.fix_ci = self._llm.reviewers.fix_ci

    def _wire_prs(self) -> None:
        """Replace harness PR manager mocks with FakeGitHub methods."""
        h = self._harness
        gh = self._github
        h.prs.transition = gh.transition
        h.prs.swap_pipeline_labels = gh.swap_pipeline_labels
        h.prs.add_labels = gh.add_labels
        h.prs.remove_label = gh.remove_label
        h.prs.post_comment = gh.post_comment
        h.prs.post_pr_comment = gh.post_pr_comment
        h.prs.submit_review = gh.submit_review
        h.prs.create_task = gh.create_task
        h.prs.close_task = gh.close_task
        h.prs.close_issue = gh.close_issue
        h.prs.find_existing_issue = gh.find_existing_issue
        h.prs.push_branch = gh.push_branch
        h.prs.create_pr = gh.create_pr
        h.prs.find_open_pr_for_branch = gh.find_open_pr_for_branch
        h.prs.branch_has_diff_from_main = gh.branch_has_diff_from_main
        h.prs.add_pr_labels = gh.add_pr_labels
        h.prs.get_pr_diff = gh.get_pr_diff
        h.prs.get_pr_head_sha = gh.get_pr_head_sha
        h.prs.get_pr_diff_names = gh.get_pr_diff_names
        h.prs.get_pr_approvers = gh.get_pr_approvers
        h.prs.fetch_code_scanning_alerts = gh.fetch_code_scanning_alerts
        h.prs.wait_for_ci = gh.wait_for_ci
        h.prs.fetch_ci_failure_logs = gh.fetch_ci_failure_logs
        h.prs.merge_pr = gh.merge_pr

    def _wire_workspaces(self) -> None:
        """Replace harness workspace mocks with FakeWorkspace."""
        h = self._harness
        h.workspaces.create = self._workspace.create
        h.workspaces.destroy = self._workspace.destroy

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
        return self

    def heal_service(self, name: str) -> MockWorld:
        if name == "hindsight":
            self._hindsight.set_failing(False)
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

    # --- Run ---

    def _fire_hooks(self, phase: str) -> None:
        for hook_phase, callback in self._phase_hooks:
            if hook_phase == phase:
                callback()

    async def run_pipeline(self) -> ScenarioResult:
        """Run all seeded issues through the full pipeline."""
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

    async def run_with_loops(
        self,
        loops: list[str],
        *,
        cycles: int = 1,
    ) -> dict[str, dict[str, Any] | None]:
        """Instantiate and run real BaseBackgroundLoop subclasses.

        Each loop runs for *cycles* iterations using the counting-sleep
        pattern (``instant_sleep_factory``), then stops.  FakeGitHub is
        wired as the PRPort so loops interact with seeded world state.

        Returns a dict mapping loop name → last ``_do_work()`` stats.
        """

        from tests.helpers import make_bg_loop_deps  # noqa: PLC0415

        bg = make_bg_loop_deps(self._tmp_path)
        # Override stop-after-2 default: build a sleep that stops after `cycles`
        call_count = 0
        stop_event = bg.stop_event

        async def _counting_sleep(_seconds: int | float) -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= cycles:
                stop_event.set()
            await asyncio.sleep(0)

        from base_background_loop import LoopDeps

        loop_deps = LoopDeps(
            event_bus=bg.bus,
            stop_event=stop_event,
            status_cb=bg.status_cb,
            enabled_cb=bg.enabled_cb,
            sleep_fn=_counting_sleep,
        )
        config = bg.config

        loop_instances = []
        for name in loops:
            instance = self._make_loop(name, config, loop_deps)
            loop_instances.append((name, instance))

        # Run _do_work directly (not .run()) to get stats without the
        # full run-loop machinery that sleeps/triggers.
        results: dict[str, dict[str, Any] | None] = {}
        for name, loop in loop_instances:
            for _ in range(cycles):
                stats = await loop._do_work()
                results[name] = stats

        return results

    def _make_loop(self, name: str, config: Any, loop_deps: Any) -> Any:
        """Instantiate a named loop with FakeGitHub wired as its PRPort."""
        from unittest.mock import MagicMock  # noqa: PLC0415

        gh = self._github

        if name == "ci_monitor":
            from ci_monitor_loop import CIMonitorLoop

            return CIMonitorLoop(
                config=config,
                pr_manager=gh,
                deps=loop_deps,
            )

        if name == "stale_issue_gc":
            from stale_issue_gc_loop import StaleIssueGCLoop

            return StaleIssueGCLoop(
                config=config,
                pr_manager=gh,
                deps=loop_deps,
            )

        if name == "dependabot_merge":
            from dependabot_merge_loop import DependabotMergeLoop

            # Reuse existing mocks if already initialized (multi-cycle tests)
            if not hasattr(self, "_dependabot_cache"):
                cache = MagicMock()
                cache.get_open_prs.return_value = []
                state = MagicMock()
                from models import DependabotMergeSettings

                state.get_dependabot_merge_settings.return_value = (
                    DependabotMergeSettings()
                )
                state.get_dependabot_merge_processed.return_value = set()
                self._dependabot_cache = cache
                self._dependabot_state = state
            cache = self._dependabot_cache
            state = self._dependabot_state
            return DependabotMergeLoop(
                config=config,
                cache=cache,
                prs=gh,
                state=state,
                deps=loop_deps,
            )

        if name == "pr_unsticker":
            from unittest.mock import AsyncMock  # noqa: PLC0415

            from pr_unsticker_loop import PRUnstickerLoop

            unsticker = MagicMock()
            unsticker.unstick = AsyncMock(
                side_effect=lambda items: {"resolved": 0, "skipped": len(items)}
            )
            return PRUnstickerLoop(
                config=config,
                pr_unsticker=unsticker,
                prs=gh,
                deps=loop_deps,
            )

        if name == "health_monitor":
            from health_monitor_loop import HealthMonitorLoop

            return HealthMonitorLoop(
                config=config,
                deps=loop_deps,
                prs=gh,
            )

        if name == "workspace_gc":
            from workspace_gc_loop import WorkspaceGCLoop

            state = MagicMock()
            state.get_active_workspaces.return_value = {}
            state.get_active_issue_numbers.return_value = set()
            state.get_active_branches.return_value = {}
            state.get_hitl_cause.return_value = None
            state.get_issue_attempts.return_value = 0
            self._workspace_gc_state = state
            return WorkspaceGCLoop(
                config=config,
                workspaces=self._workspace,
                prs=gh,
                state=state,
                deps=loop_deps,
            )

        msg = f"Unknown loop: {name}"
        raise ValueError(msg)
