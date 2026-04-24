"""Central registrations for the 6 phase-1 background loops.

Each block mirrors the instantiation logic from ``mock_world._make_loop``.
Phase 2 expands this to 20 loops. Phase 1 keeps behavior identical — only
the wiring mechanism changes.

Importing this module is a side effect: decorators run, registry fills.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from tests.scenarios.catalog import LoopCatalog, register_loop


def _build_ci_monitor(ports: dict[str, Any], config: Any, deps: Any) -> Any:
    from ci_monitor_loop import CIMonitorLoop  # noqa: PLC0415

    return CIMonitorLoop(config=config, pr_manager=ports["github"], deps=deps)


def _build_stale_issue_gc(ports: dict[str, Any], config: Any, deps: Any) -> Any:
    from stale_issue_gc_loop import StaleIssueGCLoop  # noqa: PLC0415

    return StaleIssueGCLoop(config=config, pr_manager=ports["github"], deps=deps)


def _build_dependabot_merge(ports: dict[str, Any], config: Any, deps: Any) -> Any:
    from dependabot_merge_loop import DependabotMergeLoop  # noqa: PLC0415
    from models import DependabotMergeSettings  # noqa: PLC0415

    cache = ports.get("dependabot_cache")
    state = ports.get("dependabot_state")
    if cache is None:
        cache = MagicMock()
        cache.get_open_prs.return_value = []
        ports["dependabot_cache"] = cache
    if state is None:
        state = MagicMock()
        state.get_dependabot_merge_settings.return_value = DependabotMergeSettings()
        state.get_dependabot_merge_processed.return_value = set()
        ports["dependabot_state"] = state
    return DependabotMergeLoop(
        config=config,
        cache=cache,
        prs=ports["github"],
        state=state,
        deps=deps,
    )


def _build_pr_unsticker(ports: dict[str, Any], config: Any, deps: Any) -> Any:
    from pr_unsticker_loop import PRUnstickerLoop  # noqa: PLC0415

    unsticker = MagicMock()
    unsticker.unstick = AsyncMock(
        side_effect=lambda items: {"resolved": 0, "skipped": len(items)}
    )
    return PRUnstickerLoop(
        config=config,
        pr_unsticker=unsticker,
        prs=ports["github"],
        deps=deps,
    )


def _build_health_monitor(ports: dict[str, Any], config: Any, deps: Any) -> Any:
    from health_monitor_loop import HealthMonitorLoop  # noqa: PLC0415

    return HealthMonitorLoop(config=config, deps=deps, prs=ports["github"])


def _build_workspace_gc(ports: dict[str, Any], config: Any, deps: Any) -> Any:
    from workspace_gc_loop import WorkspaceGCLoop  # noqa: PLC0415

    state = ports.get("workspace_gc_state")
    if state is None:
        state = MagicMock()
        state.get_active_workspaces.return_value = {}
        state.get_active_issue_numbers.return_value = set()
        state.get_active_branches.return_value = {}
        state.get_hitl_cause.return_value = None
        state.get_issue_attempts.return_value = 0
        ports["workspace_gc_state"] = state
    return WorkspaceGCLoop(
        config=config,
        workspaces=ports["workspace"],
        prs=ports["github"],
        state=state,
        deps=deps,
    )


def _build_runs_gc(ports: dict[str, Any], config: Any, deps: Any) -> Any:
    from runs_gc_loop import RunsGCLoop  # noqa: PLC0415

    run_recorder = ports.get("run_recorder") or MagicMock()
    ports.setdefault("run_recorder", run_recorder)
    return RunsGCLoop(config=config, run_recorder=run_recorder, deps=deps)


def _build_retrospective(ports: dict[str, Any], config: Any, deps: Any) -> Any:
    from retrospective_loop import RetrospectiveLoop  # noqa: PLC0415

    retrospective = ports.get("retrospective") or MagicMock()
    insights = ports.get("insights") or MagicMock()
    queue = ports.get("retrospective_queue") or MagicMock()
    ports.setdefault("retrospective", retrospective)
    ports.setdefault("insights", insights)
    ports.setdefault("retrospective_queue", queue)
    return RetrospectiveLoop(
        config=config,
        deps=deps,
        retrospective=retrospective,
        insights=insights,
        queue=queue,
        prs=ports["github"],
    )


def _build_adr_reviewer(ports: dict[str, Any], config: Any, deps: Any) -> Any:
    from adr_reviewer_loop import ADRReviewerLoop  # noqa: PLC0415

    adr_reviewer = ports.get("adr_reviewer") or MagicMock()
    ports.setdefault("adr_reviewer", adr_reviewer)
    return ADRReviewerLoop(config=config, adr_reviewer=adr_reviewer, deps=deps)


def _build_github_cache(ports: dict[str, Any], config: Any, deps: Any) -> Any:
    from github_cache_loop import GitHubCacheLoop  # noqa: PLC0415

    cache = ports.get("github_cache") or MagicMock()
    ports.setdefault("github_cache", cache)
    return GitHubCacheLoop(config=config, cache=cache, deps=deps)


def _build_repo_wiki(ports: dict[str, Any], config: Any, deps: Any) -> Any:
    from repo_wiki_loop import RepoWikiLoop  # noqa: PLC0415

    wiki_store = ports.get("wiki_store") or MagicMock()
    ports.setdefault("wiki_store", wiki_store)
    return RepoWikiLoop(config=config, wiki_store=wiki_store, deps=deps)


def _build_sentry(ports: dict[str, Any], config: Any, deps: Any) -> Any:
    from sentry_loop import SentryLoop  # noqa: PLC0415

    return SentryLoop(config=config, prs=ports["github"], deps=deps)


def _build_memory_sync(ports: dict[str, Any], config: Any, deps: Any) -> Any:
    from memory_sync_loop import MemorySyncLoop  # noqa: PLC0415

    memory_sync = ports.get("memory_sync") or MagicMock()
    ports.setdefault("memory_sync", memory_sync)
    return MemorySyncLoop(config=config, memory_sync=memory_sync, deps=deps)


def _build_diagnostic(ports: dict[str, Any], config: Any, deps: Any) -> Any:
    from diagnostic_loop import DiagnosticLoop  # noqa: PLC0415

    runner = ports.get("diagnostic_runner") or MagicMock()
    state = ports.get("diagnostic_state") or MagicMock()
    ports.setdefault("diagnostic_runner", runner)
    ports.setdefault("diagnostic_state", state)
    return DiagnosticLoop(
        config=config,
        runner=runner,
        prs=ports["github"],
        state=state,
        deps=deps,
    )


def _build_code_grooming(ports: dict[str, Any], config: Any, deps: Any) -> Any:
    from code_grooming_loop import CodeGroomingLoop  # noqa: PLC0415

    return CodeGroomingLoop(config=config, pr_manager=ports["github"], deps=deps)


def _build_report_issue(ports: dict[str, Any], config: Any, deps: Any) -> Any:
    from report_issue_loop import ReportIssueLoop  # noqa: PLC0415

    state = ports.get("report_issue_state") or MagicMock()
    ports.setdefault("report_issue_state", state)
    return ReportIssueLoop(
        config=config,
        state=state,
        pr_manager=ports["github"],
        deps=deps,
    )


def _build_epic_sweeper(ports: dict[str, Any], config: Any, deps: Any) -> Any:
    from epic_sweeper_loop import EpicSweeperLoop  # noqa: PLC0415

    fetcher = ports.get("issue_fetcher") or MagicMock()
    state = ports.get("epic_sweeper_state") or MagicMock()
    ports.setdefault("issue_fetcher", fetcher)
    ports.setdefault("epic_sweeper_state", state)
    return EpicSweeperLoop(
        config=config,
        fetcher=fetcher,
        prs=ports["github"],
        state=state,
        deps=deps,
    )


def _build_security_patch(ports: dict[str, Any], config: Any, deps: Any) -> Any:
    from security_patch_loop import SecurityPatchLoop  # noqa: PLC0415

    return SecurityPatchLoop(config=config, pr_manager=ports["github"], deps=deps)


def _build_stale_issue(ports: dict[str, Any], config: Any, deps: Any) -> Any:
    from stale_issue_loop import StaleIssueLoop  # noqa: PLC0415

    state = ports.get("stale_issue_state") or MagicMock()
    ports.setdefault("stale_issue_state", state)
    return StaleIssueLoop(config=config, prs=ports["github"], state=state, deps=deps)


def _build_epic_monitor(ports: dict[str, Any], config: Any, deps: Any) -> Any:
    from epic_monitor_loop import EpicMonitorLoop  # noqa: PLC0415

    epic_manager = ports.get("epic_manager") or MagicMock()
    ports.setdefault("epic_manager", epic_manager)
    return EpicMonitorLoop(config=config, epic_manager=epic_manager, deps=deps)


def _build_flake_tracker(ports: dict[str, Any], config: Any, deps: Any) -> Any:
    """Build FlakeTrackerLoop for scenarios (spec §4.5).

    External subprocess calls (``gh run list`` / ``gh run download``) and the
    closed-escalation reconciliation cannot run inside a scenario. Tests
    pre-seed three port keys which this builder monkey-patches onto the
    instance:

    * ``flake_fetch_runs`` → ``_fetch_recent_runs``
    * ``flake_download_junit`` → ``_download_junit``
    * ``flake_reconcile_closed`` → ``_reconcile_closed_escalations``

    ``state`` and ``dedup`` default to MagicMocks that behave like a clean
    slate (no prior flake counts, no prior dedup keys). Tests may override
    by seeding ``flake_state`` / ``flake_dedup`` explicitly.
    """
    from flake_tracker_loop import FlakeTrackerLoop  # noqa: PLC0415

    state = ports.get("flake_state")
    if state is None:
        state = MagicMock()
        state.get_flake_counts.return_value = {}
        state.get_flake_attempts.return_value = 0
        state.inc_flake_attempts.return_value = 1
        ports["flake_state"] = state

    dedup = ports.get("flake_dedup")
    if dedup is None:
        dedup = MagicMock()
        dedup.get.return_value = set()
        ports["flake_dedup"] = dedup

    pr_manager = ports.get("pr_manager") or ports["github"]

    loop = FlakeTrackerLoop(
        config=config,
        state=state,
        pr_manager=pr_manager,
        dedup=dedup,
        deps=deps,
    )

    # Rewire external I/O to seeded async callables (if provided).
    fetch = ports.get("flake_fetch_runs")
    if fetch is not None:
        loop._fetch_recent_runs = fetch  # type: ignore[method-assign]
    download = ports.get("flake_download_junit")
    if download is not None:
        # The real method takes one positional ``run`` arg; AsyncMock handles it.
        loop._download_junit = download  # type: ignore[method-assign]
    reconcile = ports.get("flake_reconcile_closed")
    if reconcile is not None:
        loop._reconcile_closed_escalations = reconcile  # type: ignore[method-assign]

    return loop


def _build_skill_prompt_eval(ports: dict[str, Any], config: Any, deps: Any) -> Any:
    """Build SkillPromptEvalLoop for scenarios (spec §4.6).

    The loop's external surface — ``_run_corpus`` (subprocess
    ``make trust-adversarial``) and ``_reconcile_closed_escalations``
    (``gh issue list``) — cannot run inside a scenario. Tests pre-seed
    two port keys which this builder monkey-patches onto the instance:

    * ``skill_corpus_runner`` → ``_run_corpus``
    * ``skill_reconcile_closed`` → ``_reconcile_closed_escalations``

    ``state`` and ``dedup`` default to MagicMocks that behave like a
    clean slate (empty last-green snapshot, zero attempts, no prior
    dedup keys). Tests may override by seeding ``skill_prompt_state`` /
    ``skill_prompt_dedup`` explicitly — mirrors the F7 FlakeTracker
    pattern.
    """
    from skill_prompt_eval_loop import SkillPromptEvalLoop  # noqa: PLC0415

    state = ports.get("skill_prompt_state")
    if state is None:
        state = MagicMock()
        state.get_skill_prompt_last_green.return_value = {}
        state.get_skill_prompt_attempts.return_value = 0
        state.inc_skill_prompt_attempts.return_value = 1
        ports["skill_prompt_state"] = state

    dedup = ports.get("skill_prompt_dedup")
    if dedup is None:
        dedup = MagicMock()
        dedup.get.return_value = set()
        ports["skill_prompt_dedup"] = dedup

    pr_manager = ports.get("pr_manager") or ports["github"]

    loop = SkillPromptEvalLoop(
        config=config,
        state=state,
        pr_manager=pr_manager,
        dedup=dedup,
        deps=deps,
    )

    # Rewire external I/O to seeded async callables (if provided).
    corpus = ports.get("skill_corpus_runner")
    if corpus is not None:
        loop._run_corpus = corpus  # type: ignore[method-assign]
    reconcile = ports.get("skill_reconcile_closed")
    if reconcile is not None:
        loop._reconcile_closed_escalations = reconcile  # type: ignore[method-assign]

    return loop


def _build_rc_budget(ports: dict[str, Any], config: Any, deps: Any) -> Any:
    """Build RCBudgetLoop for scenarios (spec §4.8).

    The loop's external surface (``_fetch_recent_runs`` / ``_fetch_job_breakdown``
    / ``_fetch_junit_tests`` / ``_reconcile_closed_escalations``) issues ``gh``
    subprocesses that cannot run inside a scenario. Tests may either:

    * Monkey-patch ``asyncio.create_subprocess_exec`` at the module level (the
      scenario pattern used by ``test_rc_budget_scenario.py``), **or**
    * Pre-seed port keys which this builder monkey-patches onto the instance:

      * ``rc_budget_fetch_runs`` → ``_fetch_recent_runs``
      * ``rc_budget_fetch_jobs`` → ``_fetch_job_breakdown``
      * ``rc_budget_fetch_junit`` → ``_fetch_junit_tests``
      * ``rc_budget_reconcile_closed`` → ``_reconcile_closed_escalations``

    ``state`` and ``dedup`` default to MagicMocks with clean-slate return
    values; tests may override by seeding ``rc_budget_state`` /
    ``rc_budget_dedup`` explicitly — mirrors the F7 FlakeTracker
    (``eac5fc72``), S6 SkillPromptEval (``93ebf387``), and C6
    FakeCoverageAuditor (``32b43ab0``) patterns.
    """
    from rc_budget_loop import RCBudgetLoop  # noqa: PLC0415

    state = ports.get("rc_budget_state")
    if state is None:
        state = MagicMock()
        state.get_rc_budget_duration_history.return_value = []
        state.get_rc_budget_attempts.return_value = 0
        state.inc_rc_budget_attempts.return_value = 1
        ports["rc_budget_state"] = state

    dedup = ports.get("rc_budget_dedup")
    if dedup is None:
        dedup = MagicMock()
        dedup.get.return_value = set()
        ports["rc_budget_dedup"] = dedup

    pr_manager = ports.get("pr_manager") or ports["github"]

    loop = RCBudgetLoop(
        config=config,
        state=state,
        pr_manager=pr_manager,
        dedup=dedup,
        deps=deps,
    )

    # Rewire external I/O to seeded async callables (if provided).
    fetch_runs = ports.get("rc_budget_fetch_runs")
    if fetch_runs is not None:
        loop._fetch_recent_runs = fetch_runs  # type: ignore[method-assign]
    fetch_jobs = ports.get("rc_budget_fetch_jobs")
    if fetch_jobs is not None:
        loop._fetch_job_breakdown = fetch_jobs  # type: ignore[method-assign]
    fetch_junit = ports.get("rc_budget_fetch_junit")
    if fetch_junit is not None:
        loop._fetch_junit_tests = fetch_junit  # type: ignore[method-assign]
    reconcile = ports.get("rc_budget_reconcile_closed")
    if reconcile is not None:
        loop._reconcile_closed_escalations = reconcile  # type: ignore[method-assign]

    return loop


def _build_wiki_rot_detector(ports: dict[str, Any], config: Any, deps: Any) -> Any:
    """Build WikiRotDetectorLoop for scenarios (spec §4.9).

    The loop's external surface — ``_gh_closed_escalations`` (``gh issue
    list`` subprocess) and the ``RepoWikiStore`` / ``StateTracker`` /
    ``DedupStore`` ports — cannot run live inside a scenario. Tests
    pre-seed three port keys which this builder reads and wires into the
    constructor:

    * ``wiki_rot_state`` → ``state``
    * ``wiki_rot_dedup`` → ``dedup``
    * ``wiki_store`` → ``wiki_store``

    All default to MagicMocks with clean-slate return values (zero
    attempts, no prior dedup keys, no seeded repos). Tests may override
    by seeding any of the port keys explicitly — mirrors the F7
    FlakeTracker (``eac5fc72``), S6 SkillPromptEval (``93ebf387``), C6
    FakeCoverageAuditor (``32b43ab0``), and rc-budget T9 (``20a4a177``)
    patterns.
    """
    from wiki_rot_detector_loop import WikiRotDetectorLoop  # noqa: PLC0415

    state = ports.get("wiki_rot_state")
    if state is None:
        state = MagicMock()
        state.get_wiki_rot_attempts.return_value = 0
        state.inc_wiki_rot_attempts.return_value = 1
        ports["wiki_rot_state"] = state

    dedup = ports.get("wiki_rot_dedup")
    if dedup is None:
        dedup = MagicMock()
        dedup.get.return_value = set()
        ports["wiki_rot_dedup"] = dedup

    wiki_store = ports.get("wiki_store")
    if wiki_store is None:
        wiki_store = MagicMock()
        wiki_store.list_repos.return_value = []
        ports["wiki_store"] = wiki_store

    pr_manager = ports.get("pr_manager") or ports["github"]

    return WikiRotDetectorLoop(
        config=config,
        state=state,
        pr_manager=pr_manager,
        dedup=dedup,
        wiki_store=wiki_store,
        deps=deps,
    )


def _build_fake_coverage_auditor(ports: dict[str, Any], config: Any, deps: Any) -> Any:
    """Build FakeCoverageAuditorLoop for scenarios (spec §4.7).

    The loop's external surface — ``_reconcile_closed_escalations``
    (``gh issue list``) and ``_grep_scenario_for_helper`` (``rg`` over
    ``tests/scenarios/``) — cannot run inside a scenario. Tests pre-seed
    two port keys which this builder monkey-patches onto the instance:

    * ``fake_coverage_reconcile_closed`` → ``_reconcile_closed_escalations``
    * ``fake_coverage_grep`` → ``_grep_scenario_for_helper``

    ``state`` and ``dedup`` default to MagicMocks that behave like a
    clean slate (empty last-known catalog, zero attempts, no prior
    dedup keys). Tests may override by seeding ``fake_coverage_state`` /
    ``fake_coverage_dedup`` explicitly — mirrors the F7 FlakeTracker
    (``eac5fc72``) and S6 SkillPromptEval (``93ebf387``) patterns.
    """
    from fake_coverage_auditor_loop import FakeCoverageAuditorLoop  # noqa: PLC0415

    state = ports.get("fake_coverage_state")
    if state is None:
        state = MagicMock()
        state.get_fake_coverage_last_known.return_value = {}
        state.get_fake_coverage_attempts.return_value = 0
        # Default < _MAX_ATTEMPTS=3 so gap-filing path is taken; escalation
        # tests override explicitly via ``fake_coverage_state``.
        state.inc_fake_coverage_attempts.return_value = 1
        ports["fake_coverage_state"] = state

    dedup = ports.get("fake_coverage_dedup")
    if dedup is None:
        dedup = MagicMock()
        dedup.get.return_value = set()
        ports["fake_coverage_dedup"] = dedup

    pr_manager = ports.get("pr_manager") or ports["github"]

    loop = FakeCoverageAuditorLoop(
        config=config,
        state=state,
        pr_manager=pr_manager,
        dedup=dedup,
        deps=deps,
    )

    # Rewire external I/O to seeded async callables (if provided).
    reconcile = ports.get("fake_coverage_reconcile_closed")
    if reconcile is not None:
        loop._reconcile_closed_escalations = reconcile  # type: ignore[method-assign]
    grep = ports.get("fake_coverage_grep")
    if grep is not None:
        loop._grep_scenario_for_helper = grep  # type: ignore[method-assign]

    return loop


def _build_staging_bisect(ports: dict[str, Any], config: Any, deps: Any) -> Any:
    """Build StagingBisectLoop for scenarios (spec §4.3).

    The loop shells out to ``git bisect`` / ``gh api`` / ``gh pr create`` /
    ``gh issue create`` which cannot run inside a scenario. Tests may
    monkey-patch ``asyncio.create_subprocess_exec`` at the module level
    (the pattern in ``test_staging_bisect_loop.py``) or pre-seed port keys
    which this builder monkey-patches onto the instance:

    * ``staging_bisect_state`` — pre-built StateTracker mock (defaults
      to a MagicMock with ``get_last_rc_red_sha`` returning ``""``)
    * ``staging_bisect_run_probe`` → ``_run_bisect_probe``
      (async callable ``(rc_sha) -> (passed, combined_output)``)
    * ``staging_bisect_run_pipeline`` → ``_run_full_bisect_pipeline``
      (async callable ``(red_sha, probe_output) -> dict``)
    """
    from staging_bisect_loop import StagingBisectLoop  # noqa: PLC0415

    state = ports.get("staging_bisect_state")
    if state is None:
        state = MagicMock()
        state.get_last_rc_red_sha.return_value = ""
        state.get_last_green_rc_sha.return_value = ""
        state.increment_flake_reruns_total.return_value = None
        ports["staging_bisect_state"] = state

    prs = ports.get("pr_manager") or ports["github"]

    # Scenario configs default ``staging_enabled=False``; unconditionally
    # enable it for scenario tests so the loop's ladder actually runs.
    # Tests that want the disabled-short-circuit path can assert on the
    # default HydraFlowConfig directly rather than via MockWorld.
    if not getattr(config, "staging_enabled", False):
        object.__setattr__(config, "staging_enabled", True)

    loop = StagingBisectLoop(config=config, prs=prs, state=state, deps=deps)

    run_probe = ports.get("staging_bisect_run_probe")
    if run_probe is not None:
        loop._run_bisect_probe = run_probe  # type: ignore[method-assign]
    run_pipeline = ports.get("staging_bisect_run_pipeline")
    if run_pipeline is not None:
        loop._run_full_bisect_pipeline = run_pipeline  # type: ignore[method-assign]

    return loop


def _build_corpus_learning(ports: dict[str, Any], config: Any, deps: Any) -> Any:
    """Build CorpusLearningLoop for scenarios (spec §4.1 v2).

    The loop's external surface — :meth:`PRManager.list_issues_by_label`
    (``gh issue list``) and :func:`auto_pr.open_automated_pr_async`
    (``git`` + ``gh pr create``) — cannot run live inside a scenario.
    Tests seed a FakeGitHub so ``list_issues_by_label`` returns seeded
    escape rows, and may pre-seed the ``corpus_learning_auto_pr`` port
    to stub the PR-opener so the loop's materialize-and-file ladder
    exercises real code without escaping the sandbox.

    ``dedup`` defaults to a real :class:`DedupStore` rooted under
    ``config.data_root / dedup / corpus_learning.json`` so the JSON
    round-trip runs (mirrors the unit/integration tests). Tests may
    override by seeding ``corpus_learning_dedup`` explicitly.
    """
    from corpus_learning_loop import CorpusLearningLoop  # noqa: PLC0415
    from dedup_store import DedupStore  # noqa: PLC0415

    dedup = ports.get("corpus_learning_dedup")
    if dedup is None:
        dedup = DedupStore(
            "corpus_learning",
            config.data_root / "dedup" / "corpus_learning.json",
        )
        ports["corpus_learning_dedup"] = dedup

    pr_manager = ports.get("pr_manager") or ports["github"]

    loop = CorpusLearningLoop(
        config=config,
        prs=pr_manager,
        dedup=dedup,
        deps=deps,
    )

    # Optional: replace the auto_pr seam on the loop's module with a
    # seeded async callable so tests can assert the opened PR without
    # shelling out to ``git``/``gh``.
    auto_pr_stub = ports.get("corpus_learning_auto_pr")
    if auto_pr_stub is not None:
        import corpus_learning_loop as _mod  # noqa: PLC0415

        _mod.open_automated_pr_async = auto_pr_stub  # type: ignore[assignment]

    return loop


def _build_trust_fleet_sanity(ports: dict[str, Any], config: Any, deps: Any) -> Any:
    """Build TrustFleetSanityLoop for scenarios (spec §12.1).

    The loop reads heartbeats/enabled state from ``StateTracker`` and
    ``BGWorkerManager``; tests may pre-seed mocks via ``trust_fleet_sanity_state``
    and ``trust_fleet_sanity_bg_workers`` ports. ``bg_workers`` is injected
    post-construction since the real orchestrator builds BGWorkerManager
    from the loop registry (chicken-and-egg).
    """
    from trust_fleet_sanity_loop import TrustFleetSanityLoop  # noqa: PLC0415

    state = ports.get("trust_fleet_sanity_state")
    if state is None:
        state = MagicMock()
        state.get_worker_heartbeats.return_value = {}
        state.get_trust_fleet_sanity_attempts.return_value = 0
        state.inc_trust_fleet_sanity_attempts.return_value = 1
        state.get_trust_fleet_sanity_last_seen_counts.return_value = {}
        ports["trust_fleet_sanity_state"] = state

    dedup = ports.get("trust_fleet_sanity_dedup")
    if dedup is None:
        dedup = MagicMock()
        dedup.get.return_value = set()
        ports["trust_fleet_sanity_dedup"] = dedup

    pr_manager = ports.get("pr_manager") or ports["github"]
    event_bus = ports.get("event_bus") or MagicMock()

    loop = TrustFleetSanityLoop(
        config=config,
        state=state,
        pr_manager=pr_manager,
        dedup=dedup,
        event_bus=event_bus,
        deps=deps,
    )

    bg_workers = ports.get("trust_fleet_sanity_bg_workers")
    if bg_workers is not None:
        loop.set_bg_workers(bg_workers)

    return loop


def _build_contract_refresh(ports: dict[str, Any], config: Any, deps: Any) -> Any:
    """Build ContractRefreshLoop for scenarios (spec §4.2).

    The loop's ``_do_work`` records cassettes against live ``gh``/``git``/
    ``docker``/``claude`` binaries, diffs them, opens refresh PRs, and runs
    ``make trust-contracts`` — none of which can run inside a scenario.
    Tests pre-seed port keys which this builder monkey-patches onto the
    module-level recorder / auto_pr seams the loop imports:

    * ``contract_refresh_record_github`` → ``record_github``
    * ``contract_refresh_record_git`` → ``record_git``
    * ``contract_refresh_record_docker`` → ``record_docker``
    * ``contract_refresh_record_claude`` → ``record_claude_stream``
    * ``contract_refresh_auto_pr`` → ``open_automated_pr_async``

    ``state`` defaults to a MagicMock wired with int-returning stubs for
    the Task 18 attempt counters (``get_contract_refresh_attempts`` →
    ``0``, ``inc_contract_refresh_attempts`` → ``1``) so the real
    ``_maybe_escalate`` ladder can run a full tick without crashing on
    a MagicMock arithmetic comparison. Tests may override by seeding
    ``contract_refresh_state`` explicitly. The loop builds its own
    ``DedupStore`` from ``config.data_root`` so no dedup port is exposed.
    """
    import contract_refresh_loop as _module  # noqa: PLC0415
    from contract_refresh_loop import ContractRefreshLoop  # noqa: PLC0415

    state = ports.get("contract_refresh_state")
    if state is None:
        state = MagicMock()
        # Task 18 — escalation ladder reads/increments these per adapter.
        # Without int defaults the ``attempts < threshold`` comparison
        # blows up with TypeError the moment the first drift tick runs.
        state.get_contract_refresh_attempts.return_value = 0
        state.inc_contract_refresh_attempts.return_value = 1
        state.clear_contract_refresh_attempts.return_value = None
        ports["contract_refresh_state"] = state

    pr_manager = ports.get("pr_manager") or ports["github"]

    # Monkey-patch the module-level recorder seams so the loop's
    # `_record_all` returns the test-supplied (or empty-list) mappings.
    # The loop imports these at module level, so we patch the module.
    default_empty = lambda *_a, **_k: []  # noqa: E731
    _module.record_github = ports.get("contract_refresh_record_github", default_empty)
    _module.record_git = ports.get("contract_refresh_record_git", default_empty)
    _module.record_docker = ports.get("contract_refresh_record_docker", default_empty)
    _module.record_claude_stream = ports.get(
        "contract_refresh_record_claude", default_empty
    )

    # Optional: replace the auto_pr seam on the loop's module with a
    # seeded async callable so tests can assert the opened PR shape
    # without shelling out to ``git`` / ``gh``. Mirrors the F1
    # corpus-learning pattern.
    auto_pr_stub = ports.get("contract_refresh_auto_pr")
    if auto_pr_stub is not None:
        _module.open_automated_pr_async = auto_pr_stub  # type: ignore[assignment]

    return ContractRefreshLoop(
        config=config,
        deps=deps,
        prs=pr_manager,
        state=state,
    )


_BUILDERS: dict[str, Any] = {
    # phase 1
    "ci_monitor": _build_ci_monitor,
    "stale_issue_gc": _build_stale_issue_gc,
    "dependabot_merge": _build_dependabot_merge,
    "pr_unsticker": _build_pr_unsticker,
    "health_monitor": _build_health_monitor,
    "workspace_gc": _build_workspace_gc,
    # phase 3b
    "runs_gc": _build_runs_gc,
    "retrospective": _build_retrospective,
    "adr_reviewer": _build_adr_reviewer,
    "github_cache": _build_github_cache,
    "repo_wiki": _build_repo_wiki,
    "sentry": _build_sentry,
    "memory_sync": _build_memory_sync,
    "diagnostic": _build_diagnostic,
    "code_grooming": _build_code_grooming,
    "report_issue": _build_report_issue,
    "epic_sweeper": _build_epic_sweeper,
    "security_patch": _build_security_patch,
    "stale_issue": _build_stale_issue,
    "epic_monitor": _build_epic_monitor,
    # trust fleet (spec §4.5 + §4.6 + §4.7)
    "flake_tracker": _build_flake_tracker,
    "skill_prompt_eval": _build_skill_prompt_eval,
    "fake_coverage_auditor": _build_fake_coverage_auditor,
    "rc_budget": _build_rc_budget,
    "wiki_rot_detector": _build_wiki_rot_detector,
    # trust fleet (spec §4.3 staging bisect + §12.1 sanity)
    "staging_bisect": _build_staging_bisect,
    "trust_fleet_sanity": _build_trust_fleet_sanity,
    # trust fleet (spec §4.2 contract refresh)
    "contract_refresh": _build_contract_refresh,
    # trust fleet (spec §4.1 v2 corpus learning)
    "corpus_learning": _build_corpus_learning,
}


def ensure_registered() -> None:
    """Idempotent: register any phase-1 loops that aren't already registered.

    Call this from any test that depends on the registry being populated,
    since ``LoopCatalog.reset()`` in unit tests wipes registrations.
    """
    for name, builder in _BUILDERS.items():
        if not LoopCatalog.is_registered(name):
            register_loop(name)(builder)


# Register on import (side effect).
ensure_registered()
