"""Regression tests for issue #8481.

Bare-label callsites in 12 caretaker/escalation loop files used hardcoded
strings (e.g. "hitl-escalation", "wiki-rot-stuck") directly in create_issue /
PRManager calls. Those labels were never registered in HYDRAFLOW_LABELS, so
`make ensure-labels` never provisioned them and every `gh issue create` silently
failed with rc=1.

These tests verify the post-fix contract:
1. HydraFlowConfig exposes `hitl_escalation_label` and all per-loop stuck-label
   fields with `hydraflow-` prefixed defaults.
2. HYDRAFLOW_LABELS registers every new config field so `make ensure-labels`
   provisions them on the repo.
3. Key loop escalation methods pass config-driven labels to create_issue, not
   bare strings.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from config import HydraFlowConfig  # noqa: E402
from prep import HYDRAFLOW_LABELS  # noqa: E402
from tests.helpers import ConfigFactory, make_bg_loop_deps  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_HYDRAFLOW_LABELS_FIELD_NAMES: set[str] = {
    cfg_field for cfg_field, _color, _desc in HYDRAFLOW_LABELS
}


def _config(**overrides: object) -> HydraFlowConfig:
    """Build a minimal HydraFlowConfig with optional field overrides."""
    return ConfigFactory.create(**overrides)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 1. Config — hitl_escalation_label exists and is hydraflow-prefixed
# ---------------------------------------------------------------------------


class TestHitlEscalationLabelConfig:
    """HydraFlowConfig must expose `hitl_escalation_label` with hydraflow- prefix."""

    def test_field_exists_with_hydraflow_prefix(self) -> None:
        cfg = HydraFlowConfig()
        assert hasattr(cfg, "hitl_escalation_label"), (
            "HydraFlowConfig is missing `hitl_escalation_label` field — "
            "added in issue #8481 to replace bare 'hitl-escalation' literals."
        )
        assert len(cfg.hitl_escalation_label) >= 1
        assert cfg.hitl_escalation_label[0].startswith("hydraflow-"), (
            f"hitl_escalation_label default must start with 'hydraflow-', "
            f"got {cfg.hitl_escalation_label[0]!r}"
        )

    def test_field_is_registered_in_hydraflow_labels(self) -> None:
        assert "hitl_escalation_label" in _HYDRAFLOW_LABELS_FIELD_NAMES, (
            "hitl_escalation_label is not in prep.HYDRAFLOW_LABELS — "
            "`make ensure-labels` will never provision it, causing rc=1 on "
            "every escalation issue creation."
        )


# ---------------------------------------------------------------------------
# 2. Config — per-loop stuck-label fields exist with hydraflow- prefixes
# ---------------------------------------------------------------------------

_PER_LOOP_STUCK_FIELDS: list[tuple[str, str]] = [
    # (config_field_name, description_hint)
    ("fake_coverage_stuck_label", "fake_coverage_auditor_loop escalation"),
    ("discover_stuck_label", "discover_runner escalation"),
    ("shape_stuck_label", "shape_runner escalation"),
    ("corpus_learning_stuck_label", "corpus_learning_loop escalation"),
    ("trust_loop_anomaly_label", "trust_fleet_sanity_loop escalation"),
    ("rc_duration_stuck_label", "rc_budget_loop escalation"),
    ("wiki_rot_stuck_label", "wiki_rot_detector_loop escalation"),
    ("skill_prompt_stuck_label", "skill_prompt_eval_loop escalation"),
    ("flaky_test_stuck_label", "flake_tracker_loop escalation"),
    ("principles_stuck_label", "principles_audit_loop escalation"),
    ("fake_repair_stuck_label", "contract_refresh_loop hitl escalation"),
    ("bisect_harness_failure_label", "staging_bisect_loop harness failure"),
    ("revert_conflict_label", "staging_bisect_loop revert conflict"),
    ("rc_red_bisect_exhausted_label", "staging_bisect_loop bisect exhausted"),
    ("retry_lineage_exhausted_label", "staging_bisect_loop lineage exhausted"),
    ("rc_red_post_revert_red_label", "staging_bisect_loop post-revert red"),
    ("rc_red_verify_timeout_label", "staging_bisect_loop verify timeout"),
]


class TestPerLoopStuckLabelConfigs:
    """Each per-loop stuck label must be a config field with hydraflow- prefix."""

    @pytest.mark.parametrize("field_name,hint", _PER_LOOP_STUCK_FIELDS)
    def test_field_exists_with_hydraflow_prefix(
        self, field_name: str, hint: str
    ) -> None:
        cfg = HydraFlowConfig()
        assert hasattr(cfg, field_name), (
            f"HydraFlowConfig is missing `{field_name}` (used in {hint}). "
            f"Without it, the loop emits a bare label and `make ensure-labels` "
            f"never provisions it."
        )
        value: list[str] = getattr(cfg, field_name)
        assert len(value) >= 1
        assert value[0].startswith("hydraflow-"), (
            f"`{field_name}` default must start with 'hydraflow-', got {value[0]!r}"
        )

    @pytest.mark.parametrize("field_name,hint", _PER_LOOP_STUCK_FIELDS)
    def test_field_registered_in_hydraflow_labels(
        self, field_name: str, hint: str
    ) -> None:
        assert field_name in _HYDRAFLOW_LABELS_FIELD_NAMES, (
            f"`{field_name}` ({hint}) is not in prep.HYDRAFLOW_LABELS — "
            f"`make ensure-labels` will not provision it, causing rc=1 when "
            f"the loop files its escalation issue."
        )


# ---------------------------------------------------------------------------
# 3. Behavioral — FakeCoverageAuditorLoop._file_escalation uses config labels
# ---------------------------------------------------------------------------


class TestFakeCoverageAuditorEscalationUsesConfig:
    """_file_escalation must pass config-driven labels, not bare strings."""

    @pytest.mark.asyncio
    async def test_file_escalation_uses_config_hitl_escalation_label(
        self, tmp_path: Path
    ) -> None:
        """When the loop escalates, create_issue receives the config
        `hitl_escalation_label` value, not the bare string 'hitl-escalation'."""
        from dedup_store import DedupStore
        from fake_coverage_auditor_loop import FakeCoverageAuditorLoop
        from state import StateTracker

        custom_label = "custom-hitl-escalation-test"
        custom_stuck = "custom-fake-coverage-stuck-test"
        deps = make_bg_loop_deps(tmp_path, enabled=True)

        cfg = ConfigFactory.create(
            hitl_escalation_label=[custom_label],
            fake_coverage_stuck_label=[custom_stuck],
        )
        state = StateTracker(cfg.state_file)
        pr = MagicMock()
        pr.create_issue = AsyncMock(return_value=42)
        dedup = DedupStore("fake_coverage_escalations", tmp_path / "dedup.json")

        loop = FakeCoverageAuditorLoop(
            config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=deps.loop_deps
        )
        await loop._file_escalation("some-key", 3)

        pr.create_issue.assert_awaited_once()
        _title, _body, labels = pr.create_issue.await_args.args
        assert custom_label in labels, (
            f"_file_escalation passed bare 'hitl-escalation' instead of "
            f"config.hitl_escalation_label ({custom_label!r}). Labels: {labels}"
        )
        assert custom_stuck in labels, (
            f"_file_escalation passed bare 'fake-coverage-stuck' instead of "
            f"config.fake_coverage_stuck_label ({custom_stuck!r}). Labels: {labels}"
        )


# ---------------------------------------------------------------------------
# 4. Behavioral — WikiRotDetectorLoop uses config labels (module-level const)
# ---------------------------------------------------------------------------


class TestWikiRotDetectorEscalationUsesConfig:
    """WikiRotDetectorLoop._file_escalation must use config labels."""

    @pytest.mark.asyncio
    async def test_escalation_uses_config_labels(self, tmp_path: Path) -> None:
        from dedup_store import DedupStore
        from repo_wiki import RepoWikiStore
        from state import StateTracker
        from wiki_rot_citations import Cite
        from wiki_rot_detector_loop import WikiRotDetectorLoop

        custom_hitl = "custom-hitl-escalation-wiki"
        custom_stuck = "custom-wiki-rot-stuck-test"
        deps = make_bg_loop_deps(tmp_path, enabled=True)

        cfg = ConfigFactory.create(
            hitl_escalation_label=[custom_hitl],
            wiki_rot_stuck_label=[custom_stuck],
        )
        state = StateTracker(cfg.state_file)
        pr = MagicMock()
        pr.create_issue = AsyncMock(return_value=99)
        dedup = DedupStore("wiki_rot_escalations", tmp_path / "wiki_dedup.json")
        wiki_store = MagicMock(spec=RepoWikiStore)

        loop = WikiRotDetectorLoop(
            config=cfg,
            state=state,
            pr_manager=pr,
            dedup=dedup,
            wiki_store=wiki_store,
            deps=deps.loop_deps,
        )

        cite = Cite(
            module="src/nonexistent.py",
            symbol="",
            style="colon",
            raw="src/nonexistent.py:42",
        )
        await loop._file_escalation(slug="test-slug", cite=cite, attempts=3)

        pr.create_issue.assert_awaited_once()
        _title, _body, labels = pr.create_issue.await_args.args
        assert custom_hitl in labels, (
            f"WikiRotDetectorLoop passed bare 'hitl-escalation' instead of "
            f"config.hitl_escalation_label ({custom_hitl!r}). Labels: {labels}"
        )
        assert custom_stuck in labels, (
            f"WikiRotDetectorLoop passed bare 'wiki-rot-stuck' instead of "
            f"config.wiki_rot_stuck_label ({custom_stuck!r}). Labels: {labels}"
        )


# ---------------------------------------------------------------------------
# 5. Behavioral — DiscoverRunner._escalate_stuck uses config labels
# ---------------------------------------------------------------------------


class TestDiscoverRunnerEscalationUsesConfig:
    """DiscoverRunner._escalate_stuck must use config labels, not the module
    constant _ESCALATION_LABEL_HITL = 'hitl-escalation'."""

    @pytest.mark.asyncio
    async def test_escalate_stuck_uses_config_hitl_label(self, tmp_path: Path) -> None:
        from dedup_store import DedupStore
        from discover_runner import DiscoverRunner
        from events import EventBus
        from models import Task

        custom_hitl = "custom-hitl-escalation-discover"
        custom_stuck = "custom-discover-stuck-test"
        cfg = ConfigFactory.create(
            hitl_escalation_label=[custom_hitl],
            discover_stuck_label=[custom_stuck],
        )
        bus = MagicMock(spec=EventBus)
        bus.emit = AsyncMock()
        runner = DiscoverRunner(config=cfg, event_bus=bus)
        pr = MagicMock()
        pr.create_issue = AsyncMock(return_value=77)
        dedup = DedupStore("discover_escalations", tmp_path / "discover_dedup.json")
        runner.bind_escalation_deps(pr, dedup)

        task = Task(id=123, title="Test task", body="Test body")
        await runner._escalate_stuck(task, "summary text", [], 3)

        pr.create_issue.assert_awaited_once()
        call_kwargs = pr.create_issue.await_args
        labels = call_kwargs.kwargs.get("labels") or call_kwargs.args[2]
        assert custom_hitl in labels, (
            f"DiscoverRunner._escalate_stuck used bare 'hitl-escalation' instead "
            f"of config.hitl_escalation_label ({custom_hitl!r}). Labels: {labels}"
        )
        assert custom_stuck in labels, (
            f"DiscoverRunner._escalate_stuck used bare 'discover-stuck' instead "
            f"of config.discover_stuck_label ({custom_stuck!r}). Labels: {labels}"
        )


# ---------------------------------------------------------------------------
# 6. Behavioral — StagingBisectLoop._escalate_harness_failure uses config labels
# ---------------------------------------------------------------------------


class TestStagingBisectLoopEscalationUsesConfig:
    """StagingBisectLoop must use config.hitl_escalation_label, not bare string."""

    @pytest.mark.asyncio
    async def test_escalate_harness_failure_uses_config_hitl_label(
        self, tmp_path: Path
    ) -> None:
        from staging_bisect_loop import StagingBisectLoop
        from state import StateTracker

        custom_hitl = "custom-hitl-escalation-bisect"
        custom_harness = "custom-bisect-harness-failure-test"
        deps = make_bg_loop_deps(tmp_path, enabled=True)
        cfg = ConfigFactory.create(
            hitl_escalation_label=[custom_hitl],
            bisect_harness_failure_label=[custom_harness],
        )
        state = StateTracker(cfg.state_file)
        pr = MagicMock()
        pr.create_issue = AsyncMock(return_value=55)

        loop = StagingBisectLoop(
            config=cfg,
            state=state,
            prs=pr,
            deps=deps.loop_deps,
        )
        await loop._escalate_harness_failure(
            red_sha="abc123def456",
            green_sha="000111222333",
            label=custom_harness,
            detail="test failure detail",
        )

        pr.create_issue.assert_awaited_once()
        _title, _body, labels = pr.create_issue.await_args.args
        assert custom_hitl in labels, (
            f"StagingBisectLoop._escalate_harness_failure used bare "
            f"'hitl-escalation' instead of config.hitl_escalation_label "
            f"({custom_hitl!r}). Labels: {labels}"
        )


# ---------------------------------------------------------------------------
# 7. Config — cultural_check_label exists and is hydraflow-prefixed
# ---------------------------------------------------------------------------


class TestCulturalCheckLabelConfig:
    """HydraFlowConfig must expose `cultural_check_label` with hydraflow- prefix."""

    def test_field_exists_with_hydraflow_prefix(self) -> None:
        cfg = HydraFlowConfig()
        assert hasattr(cfg, "cultural_check_label"), (
            "HydraFlowConfig is missing `cultural_check_label` — "
            "PrinciplesAuditLoop appends bare 'cultural-check' to escalation "
            "issues; must route through config so make ensure-labels provisions it."
        )
        assert len(cfg.cultural_check_label) >= 1
        assert cfg.cultural_check_label[0].startswith("hydraflow-"), (
            f"cultural_check_label default must start with 'hydraflow-', "
            f"got {cfg.cultural_check_label[0]!r}"
        )

    def test_field_is_registered_in_hydraflow_labels(self) -> None:
        assert "cultural_check_label" in _HYDRAFLOW_LABELS_FIELD_NAMES, (
            "cultural_check_label is not in prep.HYDRAFLOW_LABELS — "
            "make ensure-labels will never provision it, causing rc=1 on every "
            "CULTURAL-severity principles escalation."
        )


# ---------------------------------------------------------------------------
# 8. Config — auto_agent_skip_sublabels default uses hydraflow-prefixed labels
# ---------------------------------------------------------------------------


class TestAutoAgentSkipSublabelsMatchMigratedLabels:
    """auto_agent_skip_sublabels default must reference hydraflow-prefixed labels.

    After the #8481 migration, principles_stuck_label defaults to
    'hydraflow-principles-stuck' and cultural_check_label defaults to
    'hydraflow-cultural-check'. The skip-sublabels deny-list must use those
    same values, otherwise AutoAgentPreflightLoop silently processes issues
    it should skip.
    """

    def test_skip_sublabels_does_not_contain_bare_principles_stuck(self) -> None:
        cfg = HydraFlowConfig()
        assert "principles-stuck" not in cfg.auto_agent_skip_sublabels, (
            "auto_agent_skip_sublabels still contains bare 'principles-stuck'. "
            "After migration the label is 'hydraflow-principles-stuck'; the "
            "skip filter would never match, causing auto-agent to process "
            "principles-escalation issues it should skip."
        )

    def test_skip_sublabels_does_not_contain_bare_cultural_check(self) -> None:
        cfg = HydraFlowConfig()
        assert "cultural-check" not in cfg.auto_agent_skip_sublabels, (
            "auto_agent_skip_sublabels still contains bare 'cultural-check'. "
            "After migration the label is 'hydraflow-cultural-check'; the "
            "skip filter would never match."
        )

    def test_skip_sublabels_contains_hydraflow_principles_stuck(self) -> None:
        cfg = HydraFlowConfig()
        assert cfg.principles_stuck_label[0] in cfg.auto_agent_skip_sublabels, (
            f"auto_agent_skip_sublabels must include {cfg.principles_stuck_label[0]!r} "
            f"(the default principles_stuck_label) so principles-stuck escalations "
            f"are correctly skipped by AutoAgentPreflightLoop."
        )

    def test_skip_sublabels_contains_hydraflow_cultural_check(self) -> None:
        cfg = HydraFlowConfig()
        assert cfg.cultural_check_label[0] in cfg.auto_agent_skip_sublabels, (
            f"auto_agent_skip_sublabels must include {cfg.cultural_check_label[0]!r} "
            f"(the default cultural_check_label) so cultural-severity escalations "
            f"are correctly skipped by AutoAgentPreflightLoop."
        )


# ---------------------------------------------------------------------------
# 9. Behavioral — PrinciplesAuditLoop._maybe_escalate uses config cultural label
# ---------------------------------------------------------------------------


class TestPrinciplesAuditLoopCulturalEscalationUsesConfig:
    """_maybe_escalate for CULTURAL severity must use config.cultural_check_label."""

    @pytest.mark.asyncio
    async def test_cultural_escalation_uses_config_label(self, tmp_path: Path) -> None:
        from principles_audit_loop import PrinciplesAuditLoop
        from state import StateTracker

        custom_hitl = "custom-hitl-escalation-principles"
        custom_stuck = "custom-principles-stuck-test"
        custom_cultural = "custom-cultural-check-test"
        deps = make_bg_loop_deps(tmp_path, enabled=True)
        cfg = ConfigFactory.create(
            hitl_escalation_label=[custom_hitl],
            principles_stuck_label=[custom_stuck],
            cultural_check_label=[custom_cultural],
            state_file=tmp_path / "state.json",
        )
        state = StateTracker(cfg.state_file)
        pr = MagicMock()
        pr.create_issue = AsyncMock(return_value=88)

        loop = PrinciplesAuditLoop(
            config=cfg,
            state=state,
            pr_manager=pr,
            deps=deps.loop_deps,
        )
        # CULTURAL threshold (_CULTURAL_ATTEMPTS) is 1 — first increment fires.
        await loop._maybe_escalate("some-slug", "check-99", "CULTURAL")

        pr.create_issue.assert_awaited_once()
        _title, _body, labels = pr.create_issue.await_args.args
        assert custom_cultural in labels, (
            f"_maybe_escalate (CULTURAL) passed bare 'cultural-check' instead of "
            f"config.cultural_check_label ({custom_cultural!r}). Labels: {labels}"
        )
        assert custom_hitl in labels, (
            f"_maybe_escalate (CULTURAL) did not include config.hitl_escalation_label "
            f"({custom_hitl!r}). Labels: {labels}"
        )
        assert custom_stuck in labels, (
            f"_maybe_escalate (CULTURAL) did not include config.principles_stuck_label "
            f"({custom_stuck!r}). Labels: {labels}"
        )
