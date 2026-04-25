"""Service registry and factory for the HydraFlow orchestrator."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from acceptance_criteria import AcceptanceCriteriaGenerator
from adr_reviewer import ADRCouncilReviewer
from adr_reviewer_loop import ADRReviewerLoop
from agent import AgentRunner
from base_background_loop import LoopDeps
from baseline_policy import BaselinePolicy
from beads_manager import BeadsManager
from bug_reproducer import BugReproducer
from caching_issue_store import CachingIssueStore
from ci_monitor_loop import CIMonitorLoop  # noqa: TCH001
from code_grooming_loop import CodeGroomingLoop  # noqa: TCH001
from config import Credentials, HydraFlowConfig
from contract_refresh_loop import ContractRefreshLoop
from corpus_learning_loop import CorpusLearningLoop
from crate_manager import CrateManager
from dependabot_merge_loop import DependabotMergeLoop
from diagnostic_loop import DiagnosticLoop  # noqa: TCH001
from diagnostic_runner import DiagnosticRunner
from discover_phase import DiscoverPhase  # noqa: TCH001
from discover_runner import DiscoverRunner
from docker_runner import get_docker_runner
from epic import EpicCompletionChecker, EpicManager
from epic_monitor_loop import EpicMonitorLoop
from epic_sweeper_loop import EpicSweeperLoop
from events import EventBus
from execution import SubprocessRunner
from fake_coverage_auditor_loop import FakeCoverageAuditorLoop
from flake_tracker_loop import FlakeTrackerLoop
from github_cache_loop import GitHubCacheLoop, GitHubDataCache
from harness_insights import HarnessInsightStore
from health_monitor_loop import HealthMonitorLoop
from hitl_phase import HITLPhase
from hitl_runner import HITLRunner
from implement_phase import ImplementPhase
from issue_cache import IssueCache
from issue_fetcher import GitHubTaskFetcher, IssueFetcher
from issue_store import IssueStore
from merge_conflict_resolver import MergeConflictResolver
from models import StatusCallback
from plan_phase import PlanPhase
from plan_reviewer import PlanReviewer
from planner import PlannerRunner
from ports import IssueStorePort
from post_merge_handler import PostMergeHandler
from pr_manager import PRManager
from pr_unsticker import PRUnsticker
from pr_unsticker_loop import PRUnstickerLoop
from precondition_gate import PreconditionGate
from principles_audit_loop import PrinciplesAuditLoop
from rc_budget_loop import RCBudgetLoop
from repo_wiki import RepoWikiStore
from repo_wiki_loop import RepoWikiLoop  # noqa: TCH001
from report_issue_loop import ReportIssueLoop
from research_runner import ResearchRunner
from retrospective import RetrospectiveCollector
from retrospective_loop import RetrospectiveLoop  # noqa: TCH001
from retrospective_queue import RetrospectiveQueue  # noqa: TCH001
from review_insights import ReviewInsightStore
from review_phase import ReviewPhase
from reviewer import ReviewRunner
from route_back import RouteBackCoordinator
from run_recorder import RunRecorder
from runs_gc_loop import RunsGCLoop
from security_patch_loop import SecurityPatchLoop  # noqa: TCH001
from sentry_loop import SentryLoop  # noqa: TCH001 — used in dataclass field
from shape_phase import ShapePhase  # noqa: TCH001
from shape_runner import ShapeRunner
from skill_prompt_eval_loop import SkillPromptEvalLoop
from staging_bisect_loop import StagingBisectLoop
from staging_promotion_loop import StagingPromotionLoop
from stale_issue_gc_loop import StaleIssueGCLoop  # noqa: TCH001
from stale_issue_loop import StaleIssueLoop
from state import StateTracker
from transcript_summarizer import TranscriptSummarizer
from triage import TriageRunner
from triage_phase import TriagePhase
from troubleshooting_store import TroubleshootingPatternStore
from trust_fleet_sanity_loop import TrustFleetSanityLoop
from verification_judge import VerificationJudge
from wiki_rot_detector_loop import WikiRotDetectorLoop
from workspace import WorkspaceManager
from workspace_gc_loop import WorkspaceGCLoop

if TYPE_CHECKING:
    from metrics_manager import MetricsManager

logger = logging.getLogger("hydraflow.service_registry")


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
    # Optional read-through cache decorator wrapping `store`. Phases
    # that want stale-bounded enrich_with_comments + fetch recording
    # consume this instead of `store` directly. Defaults to the same
    # object as `store` when caching_issue_store_enabled is False so
    # consumers can opt in without conditional wiring.
    phase_store: IssueStorePort
    crate_manager: CrateManager
    issue_cache: IssueCache

    # Phase coordinators
    triager: TriagePhase
    discover_phase: DiscoverPhase
    shape_phase: ShapePhase
    planner_phase: PlanPhase
    hitl_phase: HITLPhase
    implementer: ImplementPhase
    reviewer: ReviewPhase

    # Background workers and support
    run_recorder: RunRecorder
    metrics_manager: MetricsManager
    pr_unsticker: PRUnsticker
    retrospective: RetrospectiveCollector
    ac_generator: AcceptanceCriteriaGenerator
    verification_judge: VerificationJudge
    epic_checker: EpicCompletionChecker
    epic_manager: EpicManager

    # GitHub data cache
    github_cache: GitHubDataCache
    github_cache_loop: GitHubCacheLoop

    # Background loops
    pr_unsticker_loop: PRUnstickerLoop
    report_issue_loop: ReportIssueLoop
    epic_monitor_loop: EpicMonitorLoop
    epic_sweeper_loop: EpicSweeperLoop
    workspace_gc_loop: WorkspaceGCLoop
    runs_gc_loop: RunsGCLoop
    adr_reviewer_loop: ADRReviewerLoop
    health_monitor_loop: HealthMonitorLoop
    dependabot_merge_loop: DependabotMergeLoop
    staging_promotion_loop: StagingPromotionLoop
    staging_bisect_loop: StagingBisectLoop
    stale_issue_loop: StaleIssueLoop
    sentry_loop: SentryLoop
    stale_issue_gc_loop: StaleIssueGCLoop
    ci_monitor_loop: CIMonitorLoop
    security_patch_loop: SecurityPatchLoop
    code_grooming_loop: CodeGroomingLoop
    repo_wiki_store: RepoWikiStore
    repo_wiki_loop: RepoWikiLoop
    diagnostic_loop: DiagnosticLoop
    retrospective_loop: RetrospectiveLoop
    retrospective_queue: RetrospectiveQueue
    principles_audit_loop: PrinciplesAuditLoop
    flake_tracker_loop: FlakeTrackerLoop
    skill_prompt_eval_loop: SkillPromptEvalLoop
    fake_coverage_auditor_loop: FakeCoverageAuditorLoop
    rc_budget_loop: RCBudgetLoop
    wiki_rot_detector_loop: WikiRotDetectorLoop
    trust_fleet_sanity_loop: TrustFleetSanityLoop
    contract_refresh_loop: ContractRefreshLoop
    corpus_learning_loop: CorpusLearningLoop

    # Optional integrations


@dataclass(frozen=True)
class WorkerRegistryCallbacks:
    """Focused interface for background-worker management callbacks.

    Replaces the former ``OrchestratorCallbacks`` god-object with only the
    three callbacks that ``LoopDeps`` and status-reporting consumers need.
    """

    update_status: StatusCallback
    is_enabled: Callable[[str], bool]
    get_interval: Callable[[str], int]


def build_state_tracker(config: HydraFlowConfig) -> StateTracker:
    """Construct a ``StateTracker`` with the best available backend.

    Uses embedded Dolt when the ``dolt`` CLI is installed, otherwise
    falls back to JSON-file persistence.
    """
    from dolt_backend import DoltBackend

    dolt: DoltBackend | None = None
    try:
        dolt_dir = Path(str(config.state_file)).parent / "dolt"
        dolt = DoltBackend(dolt_dir)
        logger.info("Dolt state backend enabled at %s", dolt_dir)
    except FileNotFoundError:
        logger.info("dolt CLI not found — using file-based state")
    except Exception:
        logger.warning("Dolt init failed — using file-based state", exc_info=True)
    return StateTracker(config.state_file, dolt=dolt)


def build_services(
    config: HydraFlowConfig,
    event_bus: EventBus,
    state: StateTracker,
    stop_event: asyncio.Event,
    callbacks: WorkerRegistryCallbacks,
    active_issues_cb: Callable[[], None] | None = None,
    credentials: Credentials | None = None,
) -> ServiceRegistry:
    """Create all services wired together.

    This replaces the 170-line orchestrator constructor body.
    """
    # Build credentials from env if not supplied by caller.
    if credentials is None:
        from config import build_credentials

        credentials = build_credentials(config)

    # Configure global GitHub API concurrency limiter (startup config
    # belongs in the composition root, not the orchestrator).
    from subprocess_util import configure_gh_concurrency

    configure_gh_concurrency(config.gh_api_concurrency)

    # Hindsight semantic memory and MemoryJudge — REMOVED in Phase 3 cutover.
    # The wiki + tribal + ADR-draft pipeline is the new primary. Any
    # historical Hindsight content that needs to be preserved should have
    # been extracted via scripts/extract_hindsight_to_wiki.py before merge.

    # Dolt embedded state backend (preferred, graceful fallback)
    from dolt_backend import DoltBackend

    dolt_backend: DoltBackend | None = None
    try:
        dolt_dir = Path(str(config.state_file)).parent / "dolt"
        dolt_backend = DoltBackend(dolt_dir)
    except FileNotFoundError:
        logger.info("dolt CLI not found — stores will use file-based fallback")
    except Exception:
        logger.warning("Dolt init failed", exc_info=True)

    # Core runners
    workspaces = WorkspaceManager(config, credentials=credentials)  # noqa: F841
    subprocess_runner = get_docker_runner(config, credentials=credentials)
    # The self-repo's wiki lives at ``docs/wiki/`` so it is
    # git-tracked alongside the code it documents. Other managed repos'
    # wikis are runtime-cached under ``.hydraflow/repo_wiki/<owner>/<repo>/``.
    self_wiki_root = config.repo_root / "docs" / "wiki"
    if not self_wiki_root.exists():
        # Fallback for repos that haven't migrated yet: keep the legacy
        # runtime-only location so this PR's restructure stays backward
        # compatible with managed-repo deployments.
        self_wiki_root = config.data_path("repo_wiki")
    repo_wiki_store = RepoWikiStore(
        wiki_root=self_wiki_root,
        # Phase 3: per-entry tracked layout committed inside the target
        # repo. Prefer it over the legacy .hydraflow/repo_wiki/ when
        # present so agents read the same wiki that the factory writes.
        tracked_root=config.repo_root / config.repo_wiki_path,
        self_slug=config.repo,
    )
    from tribal_wiki import TribalWikiStore  # noqa: PLC0415
    from wiki_compiler import WikiCompiler  # noqa: PLC0415

    tribal_wiki_store = TribalWikiStore(config.data_path("tribal"))

    wiki_compiler = WikiCompiler(
        config=config,
        runner=subprocess_runner,
        credentials=credentials,
    )
    agents = AgentRunner(
        config,
        event_bus,
        runner=subprocess_runner,
        dolt=dolt_backend,
        credentials=credentials,
        wiki_store=repo_wiki_store,
        tribal_wiki_store=tribal_wiki_store,
    )
    planners = PlannerRunner(
        config,
        event_bus,
        runner=subprocess_runner,
        credentials=credentials,
        wiki_store=repo_wiki_store,
        tribal_wiki_store=tribal_wiki_store,
    )
    researcher = ResearchRunner(
        config,
        event_bus,
        runner=subprocess_runner,
        credentials=credentials,
        wiki_store=repo_wiki_store,
        tribal_wiki_store=tribal_wiki_store,
    )
    prs = PRManager(config, event_bus, credentials=credentials)
    reviewers = ReviewRunner(
        config,
        event_bus,
        runner=subprocess_runner,
        credentials=credentials,
        wiki_store=repo_wiki_store,
        tribal_wiki_store=tribal_wiki_store,
    )
    hitl_runner = HITLRunner(
        config,
        event_bus,
        runner=subprocess_runner,
        credentials=credentials,
        wiki_store=repo_wiki_store,
        tribal_wiki_store=tribal_wiki_store,
    )
    triage = TriageRunner(
        config,
        event_bus,
        runner=subprocess_runner,
        credentials=credentials,
        wiki_store=repo_wiki_store,
        tribal_wiki_store=tribal_wiki_store,
    )
    summarizer = TranscriptSummarizer(
        config, prs, event_bus, state, runner=subprocess_runner, credentials=credentials
    )

    # Data layer
    fetcher = IssueFetcher(config, credentials=credentials)
    gh_cache = GitHubDataCache(config, prs, fetcher)  # noqa: F841
    store = IssueStore(config, GitHubTaskFetcher(fetcher), event_bus)

    # Crate management
    crate_manager = CrateManager(config, state, prs, event_bus)
    store.set_crate_manager(crate_manager)

    # Local JSONL issue cache (append-only mirror; see src/issue_cache.py and #6422)
    issue_cache = IssueCache(
        config.data_path("cache"),
        enabled=config.issue_cache_enabled,
    )

    # Optional read-through cache decorator. Wraps `store` when both
    # the cache and the decorator flag are enabled, otherwise points
    # at the raw IssueStore. Phases consume `phase_store` (the
    # IssueStorePort interface) so the wiring is unchanged whether
    # caching is enabled or not.
    phase_store: IssueStorePort = (
        CachingIssueStore(
            store,
            cache=issue_cache,
            cache_ttl_seconds=config.issue_cache_enrich_ttl_seconds,
        )
        if config.issue_cache_enabled and config.caching_issue_store_enabled
        else store
    )

    # Harness insight store (shared across phases)
    harness_insights = HarnessInsightStore(
        config.data_path("memory"),
        dolt=dolt_backend,
        sensor_enrichment_enabled=config.sensor_enrichment_enabled,
    )

    # Troubleshooting pattern store (CI timeout feedback loop)
    troubleshooting_store = TroubleshootingPatternStore(
        config.data_path("memory"),
    )

    # Epic management
    epic_checker = EpicCompletionChecker(config, prs, fetcher, state=state)
    epic_manager = EpicManager(config, state, prs, fetcher, event_bus)

    # Beads manager (always active — fails hard if bd not installed)
    beads_mgr = BeadsManager()

    # Phase coordinators
    # Local JSONL issue cache — append-only mirror of GitHub issue state.
    # See src/issue_cache.py and issue #6422.
    issue_cache = IssueCache(
        config.data_path("cache"),
        enabled=config.issue_cache_enabled,
    )

    # Route-back coordinator + precondition gate (#6423). The coordinator
    # ties label swap + cache record + counter + escalation. The gate
    # is the consumer-side filter implement_phase / review_phase use to
    # drop issues that fail their stage preconditions.
    #
    # Escalation chain when route-backs are exhausted: diagnose first
    # (automated diagnostic agent gets one more autonomous shot at
    # triaging the failure), HITL as fallback. Matches the existing
    # PipelineEscalator pattern in src/phase_utils.py.
    route_back_coordinator = RouteBackCoordinator(
        cache=issue_cache,
        prs=prs,
        counter=state,  # StateTracker satisfies RouteBackCounterPort
        hitl_label=config.hitl_label[0],
        diagnose_label=config.diagnose_label[0],
        max_route_backs=2,
    )
    # The gate enforces stage preconditions only when BOTH the cache is
    # enabled (so records exist to check) AND the dedicated gate flag
    # is set. The gate flag defaults to False so that turning on the
    # cache doesn't automatically activate enforcement on a fresh
    # install with no historical records — operators flip the gate
    # flag separately after confirming cache coverage.
    precondition_gate = PreconditionGate(
        cache=issue_cache,
        coordinator=route_back_coordinator,
        enabled=(config.issue_cache_enabled and config.precondition_gate_enabled),
    )

    # Adversarial plan reviewer (#6421) and triage-time bug reproducer
    # (#6424). Both are read-only/scoped agent runners that produce the
    # cache records the precondition gate consumes. Subprocess wiring
    # is the next follow-up — until then, the runners' subprocess
    # shims raise NotImplementedError and the consuming phases catch
    # the failure as a best-effort skip.
    plan_reviewer = PlanReviewer(
        config=config,
        event_bus=event_bus,
        runner=subprocess_runner,
        credentials=credentials,
        wiki_store=repo_wiki_store,
    )
    bug_reproducer = BugReproducer(
        config=config,
        event_bus=event_bus,
        runner=subprocess_runner,
        credentials=credentials,
        wiki_store=repo_wiki_store,
    )

    triager = TriagePhase(
        config,
        state,
        store,
        triage,
        prs,
        event_bus,
        stop_event,
        epic_manager=epic_manager,
        issue_cache=issue_cache,
        bug_reproducer=bug_reproducer,
    )
    discover_runner = DiscoverRunner(config, event_bus)
    discover_phase = DiscoverPhase(  # noqa: F841
        config,
        state,
        store,
        prs,
        event_bus,
        stop_event,
        discover_runner=discover_runner,
    )
    shape_runner = ShapeRunner(config, event_bus)
    wa_bridge = None
    if config.whatsapp_enabled:
        from whatsapp_bridge import WhatsAppBridge  # noqa: PLC0415

        wa_bridge = WhatsAppBridge(
            phone_id=credentials.whatsapp_phone_id,
            token=credentials.whatsapp_token,
            recipient=credentials.whatsapp_recipient,
        )
    shape_phase = ShapePhase(  # noqa: F841
        config,
        state,
        store,
        prs,
        event_bus,
        stop_event,
        shape_runner=shape_runner,
        whatsapp_bridge=wa_bridge,
    )
    # Wire expert council for auto-decision on directions
    from expert_council import ExpertCouncil  # noqa: PLC0415

    shape_phase._council = ExpertCouncil(config, event_bus)
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
        wiki_store=repo_wiki_store,
        wiki_compiler=wiki_compiler,
        issue_cache=issue_cache,
        plan_reviewer=plan_reviewer,
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
        active_issues_cb=active_issues_cb,
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
        active_issues_cb=active_issues_cb,
        transcript_summarizer=summarizer,
        precondition_gate=precondition_gate,
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
        suggest_memory=MemorySuggester(config),
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
        credentials=credentials,
    )
    retrospective_queue = RetrospectiveQueue(
        config.data_path("memory", "retrospective_queue.jsonl"),
    )
    retrospective = RetrospectiveCollector(
        config,
        state,
        prs,
        dolt=dolt_backend,
        queue=retrospective_queue,
    )
    ac_generator = AcceptanceCriteriaGenerator(
        config, prs, event_bus, runner=subprocess_runner, credentials=credentials
    )
    verification_judge = VerificationJudge(
        config, event_bus, runner=subprocess_runner, credentials=credentials
    )
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
        update_bg_worker_status=callbacks.update_status,
        epic_manager=epic_manager,
        store=store,
        wiki_store=repo_wiki_store,
        wiki_compiler=wiki_compiler,
    )
    # ReviewInsightStore shared between AgentRunner and ReviewPhase
    review_insights = ReviewInsightStore(
        config.memory_dir,
        dolt=dolt_backend,
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
        update_bg_worker_status=callbacks.update_status,
        baseline_policy=baseline_policy,
        dolt=dolt_backend,
        active_issues_cb=active_issues_cb,
        transcript_summarizer=summarizer,
        wiki_store=repo_wiki_store,
        wiki_compiler=wiki_compiler,
        retrospective_queue=retrospective_queue,
        precondition_gate=precondition_gate,
        issue_cache=issue_cache,
    )

    # Background loops — shared deps bundled into a single LoopDeps object
    loop_deps = LoopDeps(
        event_bus=event_bus,
        stop_event=stop_event,
        status_cb=callbacks.update_status,
        enabled_cb=callbacks.is_enabled,
        interval_cb=callbacks.get_interval,
    )
    pr_unsticker_loop = PRUnstickerLoop(config, pr_unsticker, prs, deps=loop_deps)
    report_issue_loop = ReportIssueLoop(
        config=config,
        state=state,
        pr_manager=prs,
        deps=loop_deps,
        runner=subprocess_runner,
        credentials=credentials,
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
        credentials=credentials,
    )
    runs_gc_loop = RunsGCLoop(config=config, run_recorder=run_recorder, deps=loop_deps)
    adr_reviewer = ADRCouncilReviewer(
        config, event_bus, prs, subprocess_runner, credentials=credentials
    )
    adr_reviewer_loop = ADRReviewerLoop(
        config=config, adr_reviewer=adr_reviewer, deps=loop_deps
    )
    health_monitor_loop = HealthMonitorLoop(  # noqa: F841
        config=config,
        deps=loop_deps,
        prs=prs,
        retrospective_queue=retrospective_queue,
        state=state,
        # bg_workers is injected post-construction by the orchestrator
        # (chicken-and-egg with BGWorkerManager); see orchestrator.py.
    )
    dependabot_merge_loop = DependabotMergeLoop(  # noqa: F841
        config=config,
        cache=gh_cache,
        prs=prs,
        state=state,
        deps=loop_deps,
    )
    staging_promotion_loop = StagingPromotionLoop(  # noqa: F841
        config=config,
        prs=prs,
        deps=loop_deps,
        state=state,
    )
    staging_bisect_loop = StagingBisectLoop(  # noqa: F841
        config=config,
        prs=prs,
        deps=loop_deps,
        state=state,
    )
    stale_issue_loop = StaleIssueLoop(
        config=config,
        prs=prs,
        state=state,
        deps=loop_deps,
    )
    gh_cache_loop = GitHubCacheLoop(config, gh_cache, deps=loop_deps)  # noqa: F841
    from dedup_store import DedupStore  # noqa: PLC0415

    sentry_dedup = DedupStore(
        "sentry_filed_ids",
        config.data_root / "dedup" / "sentry_filed.json",
        dolt=dolt_backend,
    )
    sentry_loop = SentryLoop(
        config=config,
        prs=prs,
        deps=loop_deps,
        store=store,
        runner=subprocess_runner,
        credentials=credentials,
        dedup=sentry_dedup,
        state=state,
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
        credentials=credentials,
    )
    repo_wiki_loop = RepoWikiLoop(
        config=config,
        wiki_store=repo_wiki_store,
        deps=loop_deps,
        wiki_compiler=wiki_compiler,
        state=state,
        credentials=credentials,
        tribal_store=tribal_wiki_store,
    )
    diagnostic_runner = DiagnosticRunner(config=config, event_bus=event_bus)
    diagnostic_loop = DiagnosticLoop(
        config=config,
        runner=diagnostic_runner,
        prs=prs,
        state=state,
        deps=loop_deps,
        workspaces=workspaces,
    )
    retrospective_loop = RetrospectiveLoop(  # noqa: F841
        config=config,
        deps=loop_deps,
        retrospective=retrospective,
        insights=review_insights,
        queue=retrospective_queue,
        prs=prs,
    )
    principles_audit_loop = PrinciplesAuditLoop(
        config=config,
        state=state,
        pr_manager=prs,
        deps=loop_deps,
    )
    flake_tracker_dedup = DedupStore(
        "flake_tracker",
        config.data_root / "dedup" / "flake_tracker.json",
    )
    flake_tracker_loop = FlakeTrackerLoop(  # noqa: F841
        config=config,
        state=state,
        pr_manager=prs,
        dedup=flake_tracker_dedup,
        deps=loop_deps,
    )
    skill_prompt_eval_dedup = DedupStore(
        "skill_prompt_eval",
        config.data_root / "dedup" / "skill_prompt_eval.json",
    )
    skill_prompt_eval_loop = SkillPromptEvalLoop(  # noqa: F841
        config=config,
        state=state,
        pr_manager=prs,
        dedup=skill_prompt_eval_dedup,
        deps=loop_deps,
    )
    fake_coverage_auditor_dedup = DedupStore(
        "fake_coverage_auditor",
        config.data_root / "dedup" / "fake_coverage_auditor.json",
    )
    fake_coverage_auditor_loop = FakeCoverageAuditorLoop(  # noqa: F841
        config=config,
        state=state,
        pr_manager=prs,
        dedup=fake_coverage_auditor_dedup,
        deps=loop_deps,
    )

    rc_budget_dedup = DedupStore(
        "rc_budget",
        config.data_root / "dedup" / "rc_budget.json",
    )
    rc_budget_loop = RCBudgetLoop(  # noqa: F841
        config=config,
        state=state,
        pr_manager=prs,
        dedup=rc_budget_dedup,
        deps=loop_deps,
    )

    wiki_rot_dedup = DedupStore(
        "wiki_rot_detector",
        config.data_root / "dedup" / "wiki_rot_detector.json",
    )
    wiki_rot_detector_loop = WikiRotDetectorLoop(  # noqa: F841
        config=config,
        state=state,
        pr_manager=prs,
        dedup=wiki_rot_dedup,
        wiki_store=repo_wiki_store,
        deps=loop_deps,
    )

    trust_fleet_sanity_dedup = DedupStore(
        "trust_fleet_sanity",
        config.data_root / "dedup" / "trust_fleet_sanity.json",
    )
    trust_fleet_sanity_loop = TrustFleetSanityLoop(  # noqa: F841
        config=config,
        state=state,
        pr_manager=prs,
        dedup=trust_fleet_sanity_dedup,
        event_bus=event_bus,
        deps=loop_deps,
        # bg_workers is injected post-construction by the orchestrator
        # (BGWorkerManager takes the loop registry, so it must be built
        # after all loops).
    )

    contract_refresh_loop = ContractRefreshLoop(  # noqa: F841
        config=config,
        deps=loop_deps,
        prs=prs,
        state=state,
    )

    corpus_learning_dedup = DedupStore(
        "corpus_learning",
        config.data_root / "dedup" / "corpus_learning.json",
    )
    corpus_learning_loop = CorpusLearningLoop(  # noqa: F841
        config=config,
        prs=prs,
        dedup=corpus_learning_dedup,
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
        phase_store=phase_store,
        crate_manager=crate_manager,
        issue_cache=issue_cache,
        triager=triager,
        discover_phase=discover_phase,
        shape_phase=shape_phase,
        planner_phase=planner_phase,
        hitl_phase=hitl_phase,
        implementer=implementer,
        reviewer=reviewer,
        run_recorder=run_recorder,
        metrics_manager=metrics_manager,
        pr_unsticker=pr_unsticker,
        retrospective=retrospective,
        ac_generator=ac_generator,
        verification_judge=verification_judge,
        epic_checker=epic_checker,
        epic_manager=epic_manager,
        pr_unsticker_loop=pr_unsticker_loop,
        report_issue_loop=report_issue_loop,
        epic_monitor_loop=epic_monitor_loop,
        epic_sweeper_loop=epic_sweeper_loop,
        workspace_gc_loop=workspace_gc_loop,
        runs_gc_loop=runs_gc_loop,
        adr_reviewer_loop=adr_reviewer_loop,
        health_monitor_loop=health_monitor_loop,
        dependabot_merge_loop=dependabot_merge_loop,
        staging_promotion_loop=staging_promotion_loop,
        staging_bisect_loop=staging_bisect_loop,
        stale_issue_loop=stale_issue_loop,
        github_cache=gh_cache,
        github_cache_loop=gh_cache_loop,
        sentry_loop=sentry_loop,
        stale_issue_gc_loop=stale_issue_gc_loop,
        ci_monitor_loop=ci_monitor_loop,
        security_patch_loop=security_patch_loop,
        code_grooming_loop=code_grooming_loop,
        repo_wiki_store=repo_wiki_store,
        repo_wiki_loop=repo_wiki_loop,
        diagnostic_loop=diagnostic_loop,
        retrospective_loop=retrospective_loop,
        retrospective_queue=retrospective_queue,
        principles_audit_loop=principles_audit_loop,
        flake_tracker_loop=flake_tracker_loop,
        skill_prompt_eval_loop=skill_prompt_eval_loop,
        fake_coverage_auditor_loop=fake_coverage_auditor_loop,
        rc_budget_loop=rc_budget_loop,
        wiki_rot_detector_loop=wiki_rot_detector_loop,
        trust_fleet_sanity_loop=trust_fleet_sanity_loop,
        contract_refresh_loop=contract_refresh_loop,
        corpus_learning_loop=corpus_learning_loop,
    )
