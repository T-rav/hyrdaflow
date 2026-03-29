"""Service registry and factory for the HydraFlow orchestrator."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from acceptance_criteria import AcceptanceCriteriaGenerator
from adr_reviewer import ADRCouncilReviewer
from adr_reviewer_loop import ADRReviewerLoop
from agent import AgentRunner
from base_background_loop import LoopDeps
from baseline_policy import BaselinePolicy
from beads_manager import BeadsManager
from bot_pr_loop import BotPRLoop
from ci_monitor_loop import CIMonitorLoop  # noqa: TCH001
from code_grooming_loop import CodeGroomingLoop  # noqa: TCH001
from config import HydraFlowConfig
from crate_manager import CrateManager
from docker_runner import get_docker_runner
from epic import EpicCompletionChecker, EpicManager
from epic_monitor_loop import EpicMonitorLoop
from epic_sweeper_loop import EpicSweeperLoop
from events import EventBus
from execution import SubprocessRunner
from github_cache import GitHubCacheLoop, GitHubDataCache
from harness_insights import HarnessInsightStore
from health_monitor_loop import HealthMonitorLoop
from hitl_phase import HITLPhase
from hitl_runner import HITLRunner
from implement_phase import ImplementPhase
from issue_fetcher import GitHubTaskFetcher, IssueFetcher
from issue_store import IssueStore
from memory import MemorySyncWorker
from memory_sync_loop import MemorySyncLoop
from merge_conflict_resolver import MergeConflictResolver
from models import StatusCallback
from plan_phase import PlanPhase
from planner import PlannerRunner
from post_merge_handler import PostMergeHandler
from pr_manager import PRManager
from pr_unsticker import PRUnsticker
from pr_unsticker_loop import PRUnstickerLoop
from report_issue_loop import ReportIssueLoop
from research_runner import ResearchRunner
from retrospective import RetrospectiveCollector
from review_insights import ReviewInsightStore
from review_phase import ReviewPhase
from reviewer import ReviewRunner
from run_recorder import RunRecorder
from runs_gc_loop import RunsGCLoop
from security_patch_loop import SecurityPatchLoop  # noqa: TCH001
from sentry_loop import SentryLoop  # noqa: TCH001 — used in dataclass field
from stale_issue_gc_loop import StaleIssueGCLoop  # noqa: TCH001
from state import StateTracker
from transcript_summarizer import TranscriptSummarizer
from triage import TriageRunner
from triage_phase import TriagePhase
from troubleshooting_store import TroubleshootingPatternStore
from verification_judge import VerificationJudge
from workspace import WorkspaceManager
from workspace_gc_loop import WorkspaceGCLoop

if TYPE_CHECKING:
    from hindsight import HindsightClient
    from hindsight_wal import HindsightWAL
    from metrics_manager import MetricsManager


@dataclass
class ServiceRegistry:
    """Holds all service instances for the orchestrator."""

    # Core infrastructure
    workspaces: WorkspaceManager
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

    # GitHub data cache
    github_cache: GitHubDataCache
    github_cache_loop: GitHubCacheLoop

    # Background loops
    memory_sync_bg: MemorySyncLoop
    pr_unsticker_loop: PRUnstickerLoop
    report_issue_loop: ReportIssueLoop
    epic_monitor_loop: EpicMonitorLoop
    epic_sweeper_loop: EpicSweeperLoop
    workspace_gc_loop: WorkspaceGCLoop
    runs_gc_loop: RunsGCLoop
    adr_reviewer_loop: ADRReviewerLoop
    health_monitor_loop: HealthMonitorLoop
    bot_pr_loop: BotPRLoop
    sentry_loop: SentryLoop
    stale_issue_gc_loop: StaleIssueGCLoop
    ci_monitor_loop: CIMonitorLoop
    security_patch_loop: SecurityPatchLoop
    code_grooming_loop: CodeGroomingLoop

    # Optional integrations
    hindsight: HindsightClient | None = None
    hindsight_wal: HindsightWAL | None = None


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
    # Configure global GitHub API concurrency limiter (startup config
    # belongs in the composition root, not the orchestrator).
    from subprocess_util import configure_gh_concurrency

    configure_gh_concurrency(config.gh_api_concurrency)

    # Hindsight semantic memory (optional)
    hindsight_client = None
    hindsight_wal: HindsightWAL | None = None
    if config.hindsight_url:
        from hindsight import HindsightClient
        from hindsight_wal import HindsightWAL

        hindsight_client = HindsightClient(
            config.hindsight_url,
            api_key=config.hindsight_api_key,
            timeout=config.hindsight_timeout,
        )
        hindsight_wal = HindsightWAL(config.data_path("memory", "hindsight_wal.jsonl"))

    # Dolt embedded state backend (preferred, graceful fallback)
    from dolt_backend import DoltBackend

    dolt_backend: DoltBackend | None = None
    try:
        dolt_dir = Path(str(config.state_file)).parent / "dolt"
        dolt_backend = DoltBackend(dolt_dir)
    except FileNotFoundError:
        logging.getLogger("hydraflow.service_registry").info(
            "dolt CLI not found — stores will use file-based fallback",
        )
    except Exception:
        logging.getLogger("hydraflow.service_registry").warning(
            "Dolt init failed",
            exc_info=True,
        )

    # Core runners
    workspaces = WorkspaceManager(config)  # noqa: F841
    subprocess_runner = get_docker_runner(config)
    agents = AgentRunner(
        config,
        event_bus,
        runner=subprocess_runner,
        hindsight=hindsight_client,
        dolt=dolt_backend,
        wal=hindsight_wal,
    )
    planners = PlannerRunner(
        config, event_bus, runner=subprocess_runner, hindsight=hindsight_client
    )
    researcher = ResearchRunner(
        config, event_bus, runner=subprocess_runner, hindsight=hindsight_client
    )
    prs = PRManager(config, event_bus)
    reviewers = ReviewRunner(
        config, event_bus, runner=subprocess_runner, hindsight=hindsight_client
    )
    hitl_runner = HITLRunner(
        config, event_bus, runner=subprocess_runner, hindsight=hindsight_client
    )
    triage = TriageRunner(
        config, event_bus, runner=subprocess_runner, hindsight=hindsight_client
    )
    summarizer = TranscriptSummarizer(
        config, prs, event_bus, state, runner=subprocess_runner
    )

    # Data layer
    fetcher = IssueFetcher(config)
    gh_cache = GitHubDataCache(config, prs, fetcher)  # noqa: F841
    store = IssueStore(config, GitHubTaskFetcher(fetcher), event_bus)

    # Crate management
    crate_manager = CrateManager(config, state, prs, event_bus)
    store.set_crate_manager(crate_manager)

    # Harness insight store (shared across phases)
    harness_insights = HarnessInsightStore(
        config.data_path("memory"),
        hindsight=hindsight_client,
        dolt=dolt_backend,
        wal=hindsight_wal,
    )

    # Troubleshooting pattern store (CI timeout feedback loop)
    troubleshooting_store = TroubleshootingPatternStore(
        config.data_path("memory"), hindsight=hindsight_client, wal=hindsight_wal
    )

    # Epic management
    epic_checker = EpicCompletionChecker(config, prs, fetcher, state=state)
    epic_manager = EpicManager(config, state, prs, fetcher, event_bus)

    # Beads manager (always active — fails hard if bd not installed)
    beads_mgr = BeadsManager()

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
        research_runner=researcher,
        beads_manager=beads_mgr,
    )
    hitl_phase = HITLPhase(
        config,
        state,
        store,
        fetcher,
        workspaces,
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
        workspaces,
        agents,
        prs,
        store,
        stop_event,
        run_recorder=run_recorder,
        harness_insights=harness_insights,
        beads_manager=beads_mgr,
    )

    from metrics_manager import MetricsManager

    metrics_manager = MetricsManager(config, state, prs, event_bus)
    from phase_utils import MemorySuggester

    conflict_resolver = MergeConflictResolver(
        config=config,
        workspaces=workspaces,
        agents=agents,
        prs=prs,
        event_bus=event_bus,
        state=state,
        summarizer=summarizer,
        suggest_memory=MemorySuggester(config, prs, state),
    )
    pr_unsticker = PRUnsticker(
        config,
        state,
        event_bus,
        prs,
        agents,
        workspaces,
        fetcher,
        hitl_runner=hitl_runner,
        stop_event=stop_event,
        resolver=conflict_resolver,
        troubleshooting_store=troubleshooting_store,
        store=store,
    )
    memory_sync = MemorySyncWorker(
        config,
        state,
        event_bus,
        runner=subprocess_runner,
        prs=prs,
        hindsight=hindsight_client,
        dolt=dolt_backend,
        wal=hindsight_wal,
    )
    retrospective = RetrospectiveCollector(
        config,
        state,
        prs,
        hindsight=hindsight_client,
        dolt=dolt_backend,
        wal=hindsight_wal,
    )
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
        store=store,
    )
    # ReviewInsightStore shared between AgentRunner and ReviewPhase
    review_insights = ReviewInsightStore(
        config.memory_dir,
        hindsight=hindsight_client,
        dolt=dolt_backend,
        wal=hindsight_wal,
    )
    # Inject shared store into AgentRunner (replacing its self-constructed copy)
    agents._insights = review_insights

    reviewer = ReviewPhase(
        config,
        state,
        workspaces,
        reviewers,
        prs,
        stop_event,
        store,
        conflict_resolver,
        post_merge_handler,
        event_bus=event_bus,
        harness_insights=harness_insights,
        review_insights=review_insights,
        update_bg_worker_status=callbacks.update_bg_worker_status,
        baseline_policy=baseline_policy,
        hindsight=hindsight_client,
        dolt=dolt_backend,
        wal=hindsight_wal,
    )

    # Background loops — shared deps bundled into a single LoopDeps object
    loop_deps = LoopDeps(
        event_bus=event_bus,
        stop_event=stop_event,
        status_cb=callbacks.update_bg_worker_status,
        enabled_cb=callbacks.is_bg_worker_enabled,
        sleep_fn=callbacks.sleep_or_stop,
        interval_cb=callbacks.get_bg_worker_interval,
    )
    memory_sync_bg = MemorySyncLoop(config, memory_sync, deps=loop_deps)
    pr_unsticker_loop = PRUnstickerLoop(config, pr_unsticker, prs, deps=loop_deps)
    report_issue_loop = ReportIssueLoop(
        config=config,
        state=state,
        pr_manager=prs,
        deps=loop_deps,
        runner=subprocess_runner,
    )
    epic_monitor_loop = EpicMonitorLoop(
        config=config, epic_manager=epic_manager, deps=loop_deps
    )
    epic_sweeper_loop = EpicSweeperLoop(
        config=config,
        fetcher=fetcher,
        prs=prs,
        state=state,
        deps=loop_deps,
    )
    workspace_gc_loop = WorkspaceGCLoop(  # noqa: F841
        config=config,
        workspaces=workspaces,
        prs=prs,
        state=state,
        deps=loop_deps,
        is_in_pipeline_cb=store.is_in_pipeline,
    )
    runs_gc_loop = RunsGCLoop(config=config, run_recorder=run_recorder, deps=loop_deps)
    adr_reviewer = ADRCouncilReviewer(config, event_bus, prs, subprocess_runner)
    adr_reviewer_loop = ADRReviewerLoop(
        config=config, adr_reviewer=adr_reviewer, deps=loop_deps
    )
    health_monitor_loop = HealthMonitorLoop(  # noqa: F841
        config=config,
        deps=loop_deps,
        prs=prs,
    )
    bot_pr_loop = BotPRLoop(
        config=config,
        cache=gh_cache,
        prs=prs,
        state=state,
        deps=loop_deps,
    )
    gh_cache_loop = GitHubCacheLoop(config, gh_cache, deps=loop_deps)  # noqa: F841
    sentry_loop = SentryLoop(
        config=config,
        prs=prs,
        deps=loop_deps,
        store=store,
        runner=subprocess_runner,
    )
    stale_issue_gc_loop = StaleIssueGCLoop(  # noqa: F841
        config=config,
        pr_manager=prs,
        deps=loop_deps,
    )
    ci_monitor_loop = CIMonitorLoop(  # noqa: F841
        config=config,
        pr_manager=prs,
        deps=loop_deps,
    )
    security_patch_loop = SecurityPatchLoop(  # noqa: F841
        config=config,
        pr_manager=prs,
        deps=loop_deps,
    )
    code_grooming_loop = CodeGroomingLoop(  # noqa: F841
        config=config,
        pr_manager=prs,
        deps=loop_deps,
    )

    return ServiceRegistry(
        workspaces=workspaces,
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
        pr_unsticker_loop=pr_unsticker_loop,
        report_issue_loop=report_issue_loop,
        epic_monitor_loop=epic_monitor_loop,
        epic_sweeper_loop=epic_sweeper_loop,
        workspace_gc_loop=workspace_gc_loop,
        runs_gc_loop=runs_gc_loop,
        adr_reviewer_loop=adr_reviewer_loop,
        health_monitor_loop=health_monitor_loop,
        bot_pr_loop=bot_pr_loop,
        hindsight=hindsight_client,
        hindsight_wal=hindsight_wal,
        github_cache=gh_cache,
        github_cache_loop=gh_cache_loop,
        sentry_loop=sentry_loop,
        stale_issue_gc_loop=stale_issue_gc_loop,
        ci_monitor_loop=ci_monitor_loop,
        security_patch_loop=security_patch_loop,
        code_grooming_loop=code_grooming_loop,
    )
