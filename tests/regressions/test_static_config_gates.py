"""Regression tests for static config gates on all 34 loops.

Dark-factory §2.1 #3: every loop must short-circuit with
``{"status": "config_disabled"}`` when its ``config.<loop>_enabled`` field
is ``False``, even when the ADR-0049 in-body kill-switch (``_enabled_cb``)
is live.

This test exercises each of the 34 loops that received static gates in this
PR. For each loop:

  1. Build a minimal loop instance with ``enabled=True`` (so ``_enabled_cb``
     does not short-circuit).
  2. Set the corresponding ``config.*_enabled`` field to ``False``.
  3. Call ``_do_work()`` and assert ``{"status": "config_disabled"}``.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# Ensure src/ is on the path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from tests.helpers import make_bg_loop_deps


# ---------------------------------------------------------------------------
# Helper: build a loop instance with the static gate disabled
# ---------------------------------------------------------------------------


def _deps(tmp_path: Path, disabled_field: str):
    """Return BgLoopDeps with enabled=True and the named field set to False.

    ``ConfigFactory.create()`` does not expose the 34 new ``*_enabled``
    params as kwargs (they ship with ``True`` defaults and don't need per-test
    overrides in the existing suite). We create a base config via
    ``make_bg_loop_deps`` and then produce an immutable copy with the one
    field flipped using Pydantic's ``model_copy(update=…)``.  The copy is
    slotted back onto the BgLoopDeps namedtuple by rebuilding it.
    """
    base = make_bg_loop_deps(tmp_path, enabled=True)
    patched_config = base.config.model_copy(update={disabled_field: False})
    # BgLoopDeps is a NamedTuple; rebuild with the patched config.
    from base_background_loop import LoopDeps
    from tests.helpers import BgLoopDeps

    patched_deps = LoopDeps(
        event_bus=base.loop_deps.event_bus,
        stop_event=base.loop_deps.stop_event,
        status_cb=base.loop_deps.status_cb,
        enabled_cb=base.loop_deps.enabled_cb,
        sleep_fn=base.loop_deps.sleep_fn,
    )
    return BgLoopDeps(
        config=patched_config,
        bus=base.bus,
        stop_event=base.stop_event,
        status_cb=base.status_cb,
        enabled_cb=base.enabled_cb,
        sleep_fn=base.sleep_fn,
        loop_deps=patched_deps,
    )


# ---------------------------------------------------------------------------
# Loop constructors
# All use MagicMock() for ports that would be unused because _do_work
# returns early at the config gate.
# ---------------------------------------------------------------------------


def _adr_reviewer_loop(tmp_path: Path):
    from adr_reviewer_loop import ADRReviewerLoop

    d = _deps(tmp_path, "adr_reviewer_loop_enabled")
    return ADRReviewerLoop(config=d.config, adr_reviewer=MagicMock(), deps=d.loop_deps)


def _adr_touchpoint_auditor_loop(tmp_path: Path):
    from adr_touchpoint_auditor_loop import AdrTouchpointAuditorLoop

    d = _deps(tmp_path, "adr_touchpoint_auditor_loop_enabled")
    return AdrTouchpointAuditorLoop(
        config=d.config,
        state=MagicMock(),
        pr_manager=MagicMock(),
        dedup=MagicMock(),
        adr_index=MagicMock(),
        deps=d.loop_deps,
    )


def _ci_monitor_loop(tmp_path: Path):
    from ci_monitor_loop import CIMonitorLoop

    d = _deps(tmp_path, "ci_monitor_loop_enabled")
    return CIMonitorLoop(config=d.config, pr_manager=MagicMock(), deps=d.loop_deps)


def _contract_refresh_loop(tmp_path: Path):
    from contract_refresh_loop import ContractRefreshLoop

    d = _deps(tmp_path, "contract_refresh_loop_enabled")
    return ContractRefreshLoop(
        config=d.config,
        deps=d.loop_deps,
        prs=MagicMock(),
        state=MagicMock(),
    )


def _corpus_learning_loop(tmp_path: Path):
    from corpus_learning_loop import CorpusLearningLoop

    d = _deps(tmp_path, "corpus_learning_loop_enabled")
    return CorpusLearningLoop(
        config=d.config,
        prs=MagicMock(),
        dedup=MagicMock(),
        deps=d.loop_deps,
        state=MagicMock(),
    )


def _cost_budget_watcher_loop(tmp_path: Path):
    from cost_budget_watcher_loop import CostBudgetWatcherLoop

    d = _deps(tmp_path, "cost_budget_watcher_loop_enabled")
    return CostBudgetWatcherLoop(
        config=d.config,
        pr_manager=MagicMock(),
        state=MagicMock(),
        deps=d.loop_deps,
    )


def _dependabot_merge_loop(tmp_path: Path):
    from dependabot_merge_loop import DependabotMergeLoop

    d = _deps(tmp_path, "dependabot_merge_loop_enabled")
    return DependabotMergeLoop(
        config=d.config,
        cache=MagicMock(),
        prs=MagicMock(),
        state=MagicMock(),
        deps=d.loop_deps,
    )


def _diagnostic_loop(tmp_path: Path):
    from diagnostic_loop import DiagnosticLoop

    d = _deps(tmp_path, "diagnostic_loop_enabled")
    return DiagnosticLoop(
        config=d.config,
        runner=MagicMock(),
        prs=MagicMock(),
        state=MagicMock(),
        deps=d.loop_deps,
    )


def _diagram_loop(tmp_path: Path):
    from diagram_loop import DiagramLoop

    d = _deps(tmp_path, "diagram_loop_enabled")
    return DiagramLoop(config=d.config, pr_manager=MagicMock(), deps=d.loop_deps)


def _epic_monitor_loop(tmp_path: Path):
    from epic_monitor_loop import EpicMonitorLoop

    d = _deps(tmp_path, "epic_monitor_loop_enabled")
    return EpicMonitorLoop(
        config=d.config, epic_manager=MagicMock(), deps=d.loop_deps
    )


def _epic_sweeper_loop(tmp_path: Path):
    from epic_sweeper_loop import EpicSweeperLoop

    d = _deps(tmp_path, "epic_sweeper_loop_enabled")
    return EpicSweeperLoop(
        config=d.config,
        fetcher=MagicMock(),
        prs=MagicMock(),
        state=MagicMock(),
        deps=d.loop_deps,
    )


def _fake_coverage_auditor_loop(tmp_path: Path):
    from fake_coverage_auditor_loop import FakeCoverageAuditorLoop

    d = _deps(tmp_path, "fake_coverage_auditor_loop_enabled")
    return FakeCoverageAuditorLoop(
        config=d.config,
        state=MagicMock(),
        pr_manager=MagicMock(),
        dedup=MagicMock(),
        deps=d.loop_deps,
    )


def _flake_tracker_loop(tmp_path: Path):
    from flake_tracker_loop import FlakeTrackerLoop

    d = _deps(tmp_path, "flake_tracker_loop_enabled")
    return FlakeTrackerLoop(
        config=d.config,
        state=MagicMock(),
        pr_manager=MagicMock(),
        dedup=MagicMock(),
        deps=d.loop_deps,
    )


def _github_cache_loop(tmp_path: Path):
    from github_cache_loop import GitHubCacheLoop

    d = _deps(tmp_path, "github_cache_loop_enabled")
    return GitHubCacheLoop(config=d.config, cache=MagicMock(), deps=d.loop_deps)


def _health_monitor_loop(tmp_path: Path):
    from health_monitor_loop import HealthMonitorLoop

    d = _deps(tmp_path, "health_monitor_loop_enabled")
    return HealthMonitorLoop(config=d.config, deps=d.loop_deps)


def _label_drift_watcher_loop(tmp_path: Path):
    from label_drift_watcher_loop import LabelDriftWatcherLoop

    d = _deps(tmp_path, "label_drift_watcher_loop_enabled")
    return LabelDriftWatcherLoop(
        config=d.config, pr_manager=MagicMock(), deps=d.loop_deps
    )


def _memory_backlog_loop(tmp_path: Path):
    from memory_backlog_loop import MemoryBacklogLoop

    d = _deps(tmp_path, "memory_backlog_loop_enabled")
    return MemoryBacklogLoop(
        config=d.config,
        state=MagicMock(),
        pr_manager=MagicMock(),
        dedup=MagicMock(),
        deps=d.loop_deps,
    )


def _merge_state_watcher_loop(tmp_path: Path):
    from merge_state_watcher_loop import MergeStateWatcherLoop

    d = _deps(tmp_path, "merge_state_watcher_loop_enabled")
    return MergeStateWatcherLoop(
        config=d.config, prs=MagicMock(), deps=d.loop_deps
    )


def _pr_unsticker_loop(tmp_path: Path):
    from pr_unsticker_loop import PRUnstickerLoop

    d = _deps(tmp_path, "pr_unsticker_loop_enabled")
    return PRUnstickerLoop(
        config=d.config,
        pr_unsticker=MagicMock(),
        prs=MagicMock(),
        deps=d.loop_deps,
    )


def _pricing_refresh_loop(tmp_path: Path):
    from pricing_refresh_loop import PricingRefreshLoop

    d = _deps(tmp_path, "pricing_refresh_loop_enabled")
    return PricingRefreshLoop(config=d.config, pr_manager=MagicMock(), deps=d.loop_deps)


def _principles_audit_loop(tmp_path: Path):
    from principles_audit_loop import PrinciplesAuditLoop

    d = _deps(tmp_path, "principles_audit_loop_enabled")
    return PrinciplesAuditLoop(
        config=d.config,
        state=MagicMock(),
        pr_manager=MagicMock(),
        deps=d.loop_deps,
    )


def _rc_budget_loop(tmp_path: Path):
    from rc_budget_loop import RCBudgetLoop

    d = _deps(tmp_path, "rc_budget_loop_enabled")
    return RCBudgetLoop(
        config=d.config,
        state=MagicMock(),
        pr_manager=MagicMock(),
        dedup=MagicMock(),
        deps=d.loop_deps,
    )


def _repo_wiki_loop(tmp_path: Path):
    from repo_wiki_loop import RepoWikiLoop

    d = _deps(tmp_path, "repo_wiki_loop_enabled")
    return RepoWikiLoop(
        config=d.config, wiki_store=MagicMock(), deps=d.loop_deps
    )


def _report_issue_loop(tmp_path: Path):
    from report_issue_loop import ReportIssueLoop

    d = _deps(tmp_path, "report_issue_loop_enabled")
    return ReportIssueLoop(
        config=d.config,
        state=MagicMock(),
        pr_manager=MagicMock(),
        deps=d.loop_deps,
    )


def _retrospective_loop(tmp_path: Path):
    from retrospective_loop import RetrospectiveLoop

    d = _deps(tmp_path, "retrospective_loop_enabled")
    return RetrospectiveLoop(
        config=d.config,
        deps=d.loop_deps,
        retrospective=MagicMock(),
        insights=MagicMock(),
        queue=MagicMock(),
    )


def _runs_gc_loop(tmp_path: Path):
    from runs_gc_loop import RunsGCLoop

    d = _deps(tmp_path, "runs_gc_loop_enabled")
    return RunsGCLoop(
        config=d.config, run_recorder=MagicMock(), deps=d.loop_deps
    )


def _security_patch_loop(tmp_path: Path):
    from security_patch_loop import SecurityPatchLoop

    d = _deps(tmp_path, "security_patch_loop_enabled")
    return SecurityPatchLoop(
        config=d.config, pr_manager=MagicMock(), deps=d.loop_deps
    )


def _sentry_loop(tmp_path: Path):
    from sentry_loop import SentryLoop

    d = _deps(tmp_path, "sentry_loop_enabled")
    return SentryLoop(
        config=d.config, prs=MagicMock(), deps=d.loop_deps
    )


def _skill_prompt_eval_loop(tmp_path: Path):
    from skill_prompt_eval_loop import SkillPromptEvalLoop

    d = _deps(tmp_path, "skill_prompt_eval_loop_enabled")
    return SkillPromptEvalLoop(
        config=d.config,
        state=MagicMock(),
        pr_manager=MagicMock(),
        dedup=MagicMock(),
        deps=d.loop_deps,
    )


def _stale_issue_gc_loop(tmp_path: Path):
    from stale_issue_gc_loop import StaleIssueGCLoop

    d = _deps(tmp_path, "stale_issue_gc_loop_enabled")
    return StaleIssueGCLoop(
        config=d.config, pr_manager=MagicMock(), deps=d.loop_deps
    )


def _stale_issue_loop(tmp_path: Path):
    from stale_issue_loop import StaleIssueLoop

    d = _deps(tmp_path, "stale_issue_loop_enabled")
    return StaleIssueLoop(
        config=d.config,
        prs=MagicMock(),
        state=MagicMock(),
        deps=d.loop_deps,
    )


def _trust_fleet_sanity_loop(tmp_path: Path):
    from trust_fleet_sanity_loop import TrustFleetSanityLoop

    d = _deps(tmp_path, "trust_fleet_sanity_loop_enabled")
    return TrustFleetSanityLoop(
        config=d.config,
        state=MagicMock(),
        pr_manager=MagicMock(),
        dedup=MagicMock(),
        event_bus=d.bus,
        deps=d.loop_deps,
    )


def _wiki_rot_detector_loop(tmp_path: Path):
    from wiki_rot_detector_loop import WikiRotDetectorLoop

    d = _deps(tmp_path, "wiki_rot_detector_loop_enabled")
    return WikiRotDetectorLoop(
        config=d.config,
        state=MagicMock(),
        pr_manager=MagicMock(),
        dedup=MagicMock(),
        wiki_store=MagicMock(),
        deps=d.loop_deps,
    )


def _workspace_gc_loop(tmp_path: Path):
    from workspace_gc_loop import WorkspaceGCLoop

    d = _deps(tmp_path, "workspace_gc_loop_enabled")
    return WorkspaceGCLoop(
        config=d.config,
        workspaces=MagicMock(),
        prs=MagicMock(),
        state=MagicMock(),
        deps=d.loop_deps,
    )


# ---------------------------------------------------------------------------
# Parameterized test
# ---------------------------------------------------------------------------


_LOOP_FACTORIES = [
    ("ADRReviewerLoop", _adr_reviewer_loop),
    ("AdrTouchpointAuditorLoop", _adr_touchpoint_auditor_loop),
    ("CIMonitorLoop", _ci_monitor_loop),
    ("ContractRefreshLoop", _contract_refresh_loop),
    ("CorpusLearningLoop", _corpus_learning_loop),
    ("CostBudgetWatcherLoop", _cost_budget_watcher_loop),
    ("DependabotMergeLoop", _dependabot_merge_loop),
    ("DiagnosticLoop", _diagnostic_loop),
    ("DiagramLoop", _diagram_loop),
    ("EpicMonitorLoop", _epic_monitor_loop),
    ("EpicSweeperLoop", _epic_sweeper_loop),
    ("FakeCoverageAuditorLoop", _fake_coverage_auditor_loop),
    ("FlakeTrackerLoop", _flake_tracker_loop),
    ("GitHubCacheLoop", _github_cache_loop),
    ("HealthMonitorLoop", _health_monitor_loop),
    ("LabelDriftWatcherLoop", _label_drift_watcher_loop),
    ("MemoryBacklogLoop", _memory_backlog_loop),
    ("MergeStateWatcherLoop", _merge_state_watcher_loop),
    ("PRUnstickerLoop", _pr_unsticker_loop),
    ("PricingRefreshLoop", _pricing_refresh_loop),
    ("PrinciplesAuditLoop", _principles_audit_loop),
    ("RCBudgetLoop", _rc_budget_loop),
    ("RepoWikiLoop", _repo_wiki_loop),
    ("ReportIssueLoop", _report_issue_loop),
    ("RetrospectiveLoop", _retrospective_loop),
    ("RunsGCLoop", _runs_gc_loop),
    ("SecurityPatchLoop", _security_patch_loop),
    ("SentryLoop", _sentry_loop),
    ("SkillPromptEvalLoop", _skill_prompt_eval_loop),
    ("StaleIssueGCLoop", _stale_issue_gc_loop),
    ("StaleIssueLoop", _stale_issue_loop),
    ("TrustFleetSanityLoop", _trust_fleet_sanity_loop),
    ("WikiRotDetectorLoop", _wiki_rot_detector_loop),
    ("WorkspaceGCLoop", _workspace_gc_loop),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "loop_name,factory",
    [(name, f) for name, f in _LOOP_FACTORIES],
    ids=[name for name, _ in _LOOP_FACTORIES],
)
async def test_config_disabled_short_circuits(
    loop_name: str,
    factory,
    tmp_path: Path,
) -> None:
    """When config.<loop>_enabled is False, _do_work must return config_disabled.

    The loop is constructed with enabled_cb returning True so the ADR-0049
    in-body kill-switch is live — this test validates the outermost
    deploy-time gate, not the dynamic one.
    """
    loop = factory(tmp_path)
    result = await loop._do_work()
    assert result == {"status": "config_disabled"}, (
        f"{loop_name}._do_work() returned {result!r} instead of "
        f'{{"status": "config_disabled"}} when config.{loop_name.lower()}_enabled=False'
    )
