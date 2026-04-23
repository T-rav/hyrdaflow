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
    # trust fleet (spec §4.5 + §4.6)
    "flake_tracker": _build_flake_tracker,
    "skill_prompt_eval": _build_skill_prompt_eval,
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
