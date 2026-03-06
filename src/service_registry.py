"""Service registry and factory for the HydraFlow orchestrator."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from acceptance_criteria import AcceptanceCriteriaGenerator
from adr_reviewer import ADRCouncilReviewer
from adr_reviewer_loop import ADRReviewerLoop
from agent import AgentRunner
from baseline_policy import BaselinePolicy
from config import HydraFlowConfig
from crate_manager import CrateManager
from docker_runner import get_docker_runner
from epic import EpicCompletionChecker, EpicManager
from epic_monitor_loop import EpicMonitorLoop
from events import EventBus
from execution import SubprocessRunner
from harness_insights import HarnessInsightStore
from hitl_phase import HITLPhase
from hitl_runner import HITLRunner
from implement_phase import ImplementPhase
from issue_fetcher import GitHubTaskFetcher, IssueFetcher
from issue_store import IssueStore
from manifest import ProjectManifestManager
from manifest_issue_syncer import ManifestIssueSyncer
from manifest_refresh_loop import ManifestRefreshLoop
from memory import MemorySyncWorker
from memory_sync_loop import MemorySyncLoop
from merge_conflict_resolver import MergeConflictResolver
from metrics_sync_loop import MetricsSyncLoop
from models import StatusCallback
from plan_phase import PlanPhase
from planner import PlannerRunner
from post_merge_handler import PostMergeHandler
from pr_manager import PRManager
from pr_unsticker import PRUnsticker
from pr_unsticker_loop import PRUnstickerLoop
from report_issue_loop import ReportIssueLoop
from retrospective import RetrospectiveCollector
from review_phase import ReviewPhase
from reviewer import ReviewRunner
from run_recorder import RunRecorder
from runs_gc_loop import RunsGCLoop
from state import StateTracker
from transcript_summarizer import TranscriptSummarizer
from triage import TriageRunner
from triage_phase import TriagePhase
from troubleshooting_store import TroubleshootingPatternStore
from verification_judge import VerificationJudge
from worktree import WorktreeManager
from worktree_gc_loop import WorktreeGCLoop

if TYPE_CHECKING:
    from metrics_manager import MetricsManager


@dataclass
class ServiceRegistry:
    """Holds all service instances for the orchestrator."""

    # Core infrastructure
    worktrees: WorktreeManager
    subprocess_runner: SubprocessRunner
    agents: AgentRunner
    planners: PlannerRunner
    prs: PRManager
    reviewers: ReviewRunner
    hitl_runner: HITLRunner
    triage: TriageRunner
    summarizer: TranscriptSummarizer

    # Data layer
    fetcher: IssueFetcher
    store: IssueStore
    crate_manager: CrateManager

    # Phase coordinators
    triager: TriagePhase
    planner_phase: PlanPhase
    hitl_phase: HITLPhase
    implementer: ImplementPhase
    reviewer: ReviewPhase

    # Background workers and support
    run_recorder: RunRecorder
    metrics_manager: MetricsManager
    pr_unsticker: PRUnsticker
    memory_sync: MemorySyncWorker
    retrospective: RetrospectiveCollector
    ac_generator: AcceptanceCriteriaGenerator
    verification_judge: VerificationJudge
    epic_checker: EpicCompletionChecker
    epic_manager: EpicManager

    # Background loops
    memory_sync_bg: MemorySyncLoop
    metrics_sync_bg: MetricsSyncLoop
    pr_unsticker_loop: PRUnstickerLoop
    manifest_refresh_loop: ManifestRefreshLoop
    report_issue_loop: ReportIssueLoop
    epic_monitor_loop: EpicMonitorLoop
    worktree_gc_loop: WorktreeGCLoop
    runs_gc_loop: RunsGCLoop
    adr_reviewer_loop: ADRReviewerLoop


@dataclass
class OrchestratorCallbacks:
    """Callbacks from the orchestrator needed during service construction."""

    sync_active_issue_numbers: Callable[[], None]
    update_bg_worker_status: StatusCallback
    is_bg_worker_enabled: Callable[[str], bool]
    sleep_or_stop: Callable[[int | float], Coroutine[Any, Any, None]]
    get_bg_worker_interval: Callable[[str], int]


def build_services(
    config: HydraFlowConfig,
    event_bus: EventBus,
    state: StateTracker,
    stop_event: asyncio.Event,
    callbacks: OrchestratorCallbacks,
) -> ServiceRegistry:
    """Create all services wired together.

    This replaces the 170-line orchestrator constructor body.
    """
    # Core runners
    worktrees = WorktreeManager(config)
    subprocess_runner = get_docker_runner(config)
    agents = AgentRunner(config, event_bus, runner=subprocess_runner)
    planners = PlannerRunner(config, event_bus, runner=subprocess_runner)
    prs = PRManager(config, event_bus)
    manifest_syncer = ManifestIssueSyncer(config, state, prs)
    reviewers = ReviewRunner(config, event_bus, runner=subprocess_runner)
    hitl_runner = HITLRunner(config, event_bus, runner=subprocess_runner)
    triage = TriageRunner(config, event_bus, runner=subprocess_runner)
    summarizer = TranscriptSummarizer(
        config, prs, event_bus, state, runner=subprocess_runner
    )

    # Data layer
    fetcher = IssueFetcher(config)
    store = IssueStore(config, GitHubTaskFetcher(fetcher), event_bus)

    # Crate management
    crate_manager = CrateManager(config, state, prs, event_bus)
    store.set_crate_manager(crate_manager)

    # Harness insight store (shared across phases)
    harness_insights = HarnessInsightStore(config.data_path("memory"))

    # Troubleshooting pattern store (CI timeout feedback loop)
    troubleshooting_store = TroubleshootingPatternStore(config.data_path("memory"))

    # Epic management
    epic_checker = EpicCompletionChecker(config, prs, fetcher, state=state)
    epic_manager = EpicManager(config, state, prs, fetcher, event_bus)

    # Phase coordinators
    triager = TriagePhase(
        config,
        state,
        store,
        triage,
        prs,
        event_bus,
        stop_event,
        epic_manager=epic_manager,
    )
    planner_phase = PlanPhase(
        config,
        state,
        store,
        planners,
        prs,
        event_bus,
        stop_event,
        transcript_summarizer=summarizer,
        harness_insights=harness_insights,
        epic_manager=epic_manager,
    )
    hitl_phase = HITLPhase(
        config,
        state,
        store,
        fetcher,
        worktrees,
        hitl_runner,
        prs,
        event_bus,
        stop_event,
        active_issues_cb=callbacks.sync_active_issue_numbers,
    )
    run_recorder = RunRecorder(config)
    implementer = ImplementPhase(
        config,
        state,
        worktrees,
        agents,
        prs,
        store,
        stop_event,
        run_recorder=run_recorder,
        harness_insights=harness_insights,
    )

    from metrics_manager import MetricsManager

    metrics_manager = MetricsManager(config, state, prs, event_bus)
    conflict_resolver = MergeConflictResolver(
        config=config,
        worktrees=worktrees,
        agents=agents,
        prs=prs,
        event_bus=event_bus,
        state=state,
        summarizer=summarizer,
    )
    pr_unsticker = PRUnsticker(
        config,
        state,
        event_bus,
        prs,
        agents,
        worktrees,
        fetcher,
        hitl_runner=hitl_runner,
        stop_event=stop_event,
        resolver=conflict_resolver,
        troubleshooting_store=troubleshooting_store,
    )
    memory_sync = MemorySyncWorker(
        config,
        state,
        event_bus,
        runner=subprocess_runner,
        prs=prs,
        manifest_syncer=manifest_syncer,
    )
    retrospective = RetrospectiveCollector(config, state, prs)
    ac_generator = AcceptanceCriteriaGenerator(
        config, prs, event_bus, runner=subprocess_runner
    )
    verification_judge = VerificationJudge(config, event_bus, runner=subprocess_runner)
    baseline_policy = BaselinePolicy(
        config=config,
        state=state,
        event_bus=event_bus,
    )
    post_merge_handler = PostMergeHandler(
        config=config,
        state=state,
        prs=prs,
        event_bus=event_bus,
        ac_generator=ac_generator,
        retrospective=retrospective,
        verification_judge=verification_judge,
        epic_checker=epic_checker,
        update_bg_worker_status=callbacks.update_bg_worker_status,
        epic_manager=epic_manager,
    )
    reviewer = ReviewPhase(
        config,
        state,
        worktrees,
        reviewers,
        prs,
        stop_event,
        store,
        event_bus=event_bus,
        harness_insights=harness_insights,
        conflict_resolver=conflict_resolver,
        post_merge=post_merge_handler,
        update_bg_worker_status=callbacks.update_bg_worker_status,
        baseline_policy=baseline_policy,
    )

    # Background loops
    memory_sync_bg = MemorySyncLoop(
        config,
        fetcher,
        memory_sync,
        event_bus,
        stop_event,
        status_cb=callbacks.update_bg_worker_status,
        enabled_cb=callbacks.is_bg_worker_enabled,
        sleep_fn=callbacks.sleep_or_stop,
        interval_cb=callbacks.get_bg_worker_interval,
    )
    metrics_sync_bg = MetricsSyncLoop(
        config,
        store,
        metrics_manager,
        event_bus,
        stop_event,
        status_cb=callbacks.update_bg_worker_status,
        enabled_cb=callbacks.is_bg_worker_enabled,
        sleep_fn=callbacks.sleep_or_stop,
        interval_cb=callbacks.get_bg_worker_interval,
    )
    pr_unsticker_loop = PRUnstickerLoop(
        config,
        pr_unsticker,
        prs,
        event_bus,
        stop_event,
        status_cb=callbacks.update_bg_worker_status,
        enabled_cb=callbacks.is_bg_worker_enabled,
        sleep_fn=callbacks.sleep_or_stop,
    )
    manifest_manager = ProjectManifestManager(config)
    manifest_refresh_loop = ManifestRefreshLoop(
        config,
        manifest_manager,
        state,
        event_bus,
        stop_event,
        status_cb=callbacks.update_bg_worker_status,
        enabled_cb=callbacks.is_bg_worker_enabled,
        sleep_fn=callbacks.sleep_or_stop,
        interval_cb=callbacks.get_bg_worker_interval,
        manifest_syncer=manifest_syncer,
    )

    report_issue_loop = ReportIssueLoop(
        config=config,
        state=state,
        pr_manager=prs,
        event_bus=event_bus,
        stop_event=stop_event,
        status_cb=callbacks.update_bg_worker_status,
        enabled_cb=callbacks.is_bg_worker_enabled,
        sleep_fn=callbacks.sleep_or_stop,
        interval_cb=callbacks.get_bg_worker_interval,
        runner=subprocess_runner,
    )

    epic_monitor_loop = EpicMonitorLoop(
        config=config,
        epic_manager=epic_manager,
        event_bus=event_bus,
        stop_event=stop_event,
        status_cb=callbacks.update_bg_worker_status,
        enabled_cb=callbacks.is_bg_worker_enabled,
        sleep_fn=callbacks.sleep_or_stop,
        interval_cb=callbacks.get_bg_worker_interval,
    )

    worktree_gc_loop = WorktreeGCLoop(
        config=config,
        worktrees=worktrees,
        prs=prs,
        state=state,
        event_bus=event_bus,
        stop_event=stop_event,
        status_cb=callbacks.update_bg_worker_status,
        enabled_cb=callbacks.is_bg_worker_enabled,
        sleep_fn=callbacks.sleep_or_stop,
        interval_cb=callbacks.get_bg_worker_interval,
        is_in_pipeline_cb=store.is_in_pipeline,
    )

    runs_gc_loop = RunsGCLoop(
        config=config,
        run_recorder=run_recorder,
        event_bus=event_bus,
        stop_event=stop_event,
        status_cb=callbacks.update_bg_worker_status,
        enabled_cb=callbacks.is_bg_worker_enabled,
        sleep_fn=callbacks.sleep_or_stop,
        interval_cb=callbacks.get_bg_worker_interval,
    )

    adr_reviewer = ADRCouncilReviewer(config, event_bus, prs, subprocess_runner)
    adr_reviewer_loop = ADRReviewerLoop(
        config=config,
        adr_reviewer=adr_reviewer,
        event_bus=event_bus,
        stop_event=stop_event,
        status_cb=callbacks.update_bg_worker_status,
        enabled_cb=callbacks.is_bg_worker_enabled,
        sleep_fn=callbacks.sleep_or_stop,
        interval_cb=callbacks.get_bg_worker_interval,
    )

    return ServiceRegistry(
        worktrees=worktrees,
        subprocess_runner=subprocess_runner,
        agents=agents,
        planners=planners,
        prs=prs,
        reviewers=reviewers,
        hitl_runner=hitl_runner,
        triage=triage,
        summarizer=summarizer,
        fetcher=fetcher,
        store=store,
        crate_manager=crate_manager,
        triager=triager,
        planner_phase=planner_phase,
        hitl_phase=hitl_phase,
        implementer=implementer,
        reviewer=reviewer,
        run_recorder=run_recorder,
        metrics_manager=metrics_manager,
        pr_unsticker=pr_unsticker,
        memory_sync=memory_sync,
        retrospective=retrospective,
        ac_generator=ac_generator,
        verification_judge=verification_judge,
        epic_checker=epic_checker,
        epic_manager=epic_manager,
        memory_sync_bg=memory_sync_bg,
        metrics_sync_bg=metrics_sync_bg,
        pr_unsticker_loop=pr_unsticker_loop,
        manifest_refresh_loop=manifest_refresh_loop,
        report_issue_loop=report_issue_loop,
        epic_monitor_loop=epic_monitor_loop,
        worktree_gc_loop=worktree_gc_loop,
        runs_gc_loop=runs_gc_loop,
        adr_reviewer_loop=adr_reviewer_loop,
    )
