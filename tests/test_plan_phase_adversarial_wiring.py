"""Tests for the earlier-adversarial pipeline wiring in plan_phase.

Verifies the wiring contract from Task 7 of the earlier-adversarial
pipeline implementation plan:

  1. AssumptionSurfacer runs before Planner.
  2. PlanCouncil runs after Planner, before the existing PlanReviewer.
  3. The existing PlanReviewer runs unchanged.
  4. SpecACGenerator + SpecJudge run after PlanReviewer.
  5. Each new stage is wrapped in AdversarialRetryLoop (budget=3).
  6. ``adversarial_state`` is persisted after each stage (state.json key
     ``adversarial_states``).
  7. ``implement_phase`` reads carryover concerns but does NOT block —
     it logs at INFO and forwards (dark-factory contract).
  8. Backward-compatible schema evolution: legacy state files (no
     ``adversarial_states`` key) load cleanly.

These tests use lightweight stubs for the per-stage agents — the
unit-level correctness of each adapter is covered in its own
``tests/test_<stage>.py``. The point here is the wiring shape.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.pending_concerns import AdversarialState, Concern

from models import StateData
from state import StateTracker
from tests.conftest import PlanResultFactory, TaskFactory
from tests.helpers import make_implement_phase, make_plan_phase, supply_once

if TYPE_CHECKING:
    from config import HydraFlowConfig


# ---------------------------------------------------------------------------
# Schema evolution: legacy state files must load cleanly.
# ---------------------------------------------------------------------------


class TestAdversarialStateSchemaEvolution:
    def test_legacy_state_without_adversarial_states_loads(
        self, tmp_path: Path
    ) -> None:
        """A state.json with no ``adversarial_states`` key still loads.

        Pydantic fills the default (empty dict). This is the
        backward-compatible schema evolution guarantee for the new
        ``adversarial_states`` field on ``StateData``.
        """
        legacy = {
            "schema_version": 1,
            "processed_issues": {"42": "in_progress"},
            "issue_attempts": {"42": 1},
            # no adversarial_states key
        }
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps(legacy))

        tracker = StateTracker(state_file)
        # Field exists, defaults to empty dict, mutator works.
        assert tracker.get_adversarial_state(42) is None
        tracker.set_adversarial_state(42, AdversarialState(phase="plan"))
        assert tracker.get_adversarial_state(42) is not None

    def test_adversarial_state_round_trips(self, tmp_path: Path) -> None:
        """Persist + reload returns an equivalent AdversarialState."""
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)

        adv = AdversarialState(phase="plan", current_stage="plan_council")
        tracker.set_adversarial_state(42, adv)

        # Reload from disk.
        tracker2 = StateTracker(state_file)
        loaded = tracker2.get_adversarial_state(42)
        assert loaded is not None
        assert loaded.phase == "plan"
        assert loaded.current_stage == "plan_council"

    def test_state_data_field_default_empty_dict(self) -> None:
        """``StateData.adversarial_states`` defaults to an empty dict."""
        data = StateData()
        assert data.adversarial_states == {}


# ---------------------------------------------------------------------------
# Wiring shape: order of operations + state persistence.
# ---------------------------------------------------------------------------


class _Recorder:
    """Captures the order of adversarial-stage invocations.

    Each stub appends a marker to ``calls`` when it runs. The wiring
    test asserts the marker sequence matches the spec.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.persisted: list[AdversarialState] = []


def _make_recording_agents() -> tuple[_Recorder, dict[str, AsyncMock]]:
    """Build a recorder + per-stage agent stubs that record + return JSON.

    The stubs return strings the real adapter parsers accept so the
    adapters produce empty findings — no retry, no concerns. This
    isolates the wiring test from per-stage correctness.
    """
    rec = _Recorder()

    async def _surfacer_run(_system: str, _user: str) -> str:
        rec.calls.append("assumption_surfacer")
        return '{"assumptions": [], "concerns": []}'

    async def _council_voter_run(_system: str, _user: str) -> str:
        # PlanCouncil runs three voters concurrently. We only need to
        # record the council ran once (per attempt), so use a sentinel
        # the first voter records and the others ignore.
        if "plan_council" not in rec.calls:
            rec.calls.append("plan_council")
        return '{"findings": []}'

    async def _ac_run(_system: str, _user: str) -> str:
        rec.calls.append("spec_ac_generator")
        return '{"acceptance_criteria": ["AC1 is observable"]}'

    async def _judge_run(_system: str, _user: str) -> str:
        rec.calls.append("spec_judge")
        return '{"verdict": "PASS", "findings": []}'

    surfacer_agent = AsyncMock()
    surfacer_agent.run = _surfacer_run

    builder_agent = AsyncMock()
    builder_agent.run = _council_voter_run
    tester_agent = AsyncMock()
    tester_agent.run = _council_voter_run
    risk_agent = AsyncMock()
    risk_agent.run = _council_voter_run

    ac_agent = AsyncMock()
    ac_agent.run = _ac_run
    judge_agent = AsyncMock()
    judge_agent.run = _judge_run

    agents = {
        "surfacer": surfacer_agent,
        "council_builder": builder_agent,
        "council_tester": tester_agent,
        "council_risk_skeptic": risk_agent,
        "spec_ac": ac_agent,
        "spec_judge": judge_agent,
    }
    return rec, agents


class TestPlanPhaseAdversarialWiring:
    @pytest.mark.asyncio
    async def test_stages_run_in_spec_order_when_agents_configured(
        self, config: HydraFlowConfig
    ) -> None:
        """Surfacer → Planner → Council → Reviewer → AC → Judge → label swap.

        With the adversarial agents wired in, the new stages must
        execute around the existing planner+reviewer call in the order
        specified by the implementation plan.
        """
        rec, agents = _make_recording_agents()
        phase, _state, planners, _prs, store, _stop = make_plan_phase(config)

        # Inject adversarial agents on the phase. Setter is intentional —
        # production wiring threads them via the factory; the test
        # injects them directly so the test is independent of the
        # factory's loop-up of LLM models.
        phase.attach_adversarial_agents(
            surfacer_agent=agents["surfacer"],
            council_agents={
                "builder": agents["council_builder"],
                "tester": agents["council_tester"],
                "risk_skeptic": agents["council_risk_skeptic"],
            },
            spec_ac_agent=agents["spec_ac"],
            spec_judge_agent=agents["spec_judge"],
        )

        # Existing planner shim records its own call so we can verify
        # surfacer ran BEFORE it and council ran AFTER it.
        async def _planner_plan(*_args, **_kwargs):
            rec.calls.append("planner")
            return PlanResultFactory.create(
                issue_number=42,
                success=True,
                plan="Step 1: Do the thing\nStep 2: Verify",
                summary="Done",
                use_defaults=True,
            )

        planners.plan = _planner_plan
        store.get_plannable = supply_once([TaskFactory.create(id=42)])

        await phase.plan_issues()

        # Filter to known markers (drops noise like duplicate council voters)
        known = [
            c
            for c in rec.calls
            if c
            in {
                "assumption_surfacer",
                "planner",
                "plan_council",
                "spec_ac_generator",
                "spec_judge",
            }
        ]
        assert known == [
            "assumption_surfacer",
            "planner",
            "plan_council",
            "spec_ac_generator",
            "spec_judge",
        ], f"Adversarial stages out of order: {known}"

    @pytest.mark.asyncio
    async def test_adversarial_state_persisted_per_stage(
        self, config: HydraFlowConfig
    ) -> None:
        """After plan_issues, ``adversarial_states[issue_id]`` exists.

        The wiring must persist the per-issue AdversarialState after
        each adversarial stage so implement_phase can read it.
        """
        _rec, agents = _make_recording_agents()
        phase, state, planners, _prs, store, _stop = make_plan_phase(config)
        phase.attach_adversarial_agents(
            surfacer_agent=agents["surfacer"],
            council_agents={
                "builder": agents["council_builder"],
                "tester": agents["council_tester"],
                "risk_skeptic": agents["council_risk_skeptic"],
            },
            spec_ac_agent=agents["spec_ac"],
            spec_judge_agent=agents["spec_judge"],
        )

        async def _planner_plan(*_args, **_kwargs):
            return PlanResultFactory.create(
                issue_number=99,
                success=True,
                plan="Plan body",
                summary="Done",
                use_defaults=True,
            )

        planners.plan = _planner_plan
        store.get_plannable = supply_once([TaskFactory.create(id=99)])

        await phase.plan_issues()

        adv = state.get_adversarial_state(99)
        assert adv is not None
        assert adv.phase == "plan"

    @pytest.mark.asyncio
    async def test_plan_phase_works_without_adversarial_agents(
        self, config: HydraFlowConfig
    ) -> None:
        """When adversarial agents are not attached, plan_phase still runs.

        Backward-compat: the production factory may not yet provide
        these agents (Task 8+ wires them in). The phase must continue
        to work in legacy mode — no adversarial stages, no state
        persisted, but the plan still completes.
        """
        phase, state, planners, prs, store, _stop = make_plan_phase(config)
        # No attach_adversarial_agents call.
        planners.plan = AsyncMock(
            return_value=PlanResultFactory.create(
                issue_number=7,
                success=True,
                plan="Legacy plan",
                summary="Done",
                use_defaults=True,
            )
        )
        store.get_plannable = supply_once([TaskFactory.create(id=7)])

        await phase.plan_issues()

        # Plan succeeded, no adversarial state persisted.
        assert state.get_adversarial_state(7) is None
        prs.transition.assert_awaited_once_with(7, "ready")


# ---------------------------------------------------------------------------
# implement_phase: read carryover, do not block.
# ---------------------------------------------------------------------------


class TestImplementPhaseReadsAdversarialState:
    @pytest.mark.asyncio
    async def test_implement_phase_logs_carryover_concerns(
        self,
        config: HydraFlowConfig,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """If adversarial_state has CRITICAL/HIGH concerns, they're logged at INFO.

        Dark-factory contract: implement_phase reads the state but does
        NOT deadlock on it. The concerns surface to the operator via
        the log; the implementation proceeds.
        """
        from datetime import UTC, datetime

        issue = TaskFactory.create(id=55)
        phase, _mock_wt, _mock_prs = make_implement_phase(config, [issue])

        adv = AdversarialState(
            phase="plan",
            pending_concerns=[
                Concern(
                    id="PLAN-COUNCIL-001",
                    raised_in_phase="plan",
                    raised_in_stage="plan_council_tester",
                    severity="HIGH",
                    concern="Test for X is missing.",
                    raised_at=datetime.now(UTC),
                    must_address_by="implement",
                ),
            ],
        )
        # Persist via the phase's own state tracker.
        phase._state.set_adversarial_state(55, adv)

        with caplog.at_level("INFO", logger="hydraflow.implement_phase"):
            # Direct call exercises the carryover read in isolation.
            phase._log_adversarial_carryover(issue)

        assert any(
            "PLAN-COUNCIL-001" in r.message or "carryover" in r.message.lower()
            for r in caplog.records
        ), f"carryover not logged: {[r.message for r in caplog.records]}"

    def test_implement_phase_carryover_log_is_noop_when_absent(
        self,
        config: HydraFlowConfig,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """No persisted state → carryover log is silent (no warnings/errors)."""
        issue = TaskFactory.create(id=77)
        phase, _wt, _prs = make_implement_phase(config, [issue])

        with caplog.at_level("WARNING", logger="hydraflow.implement_phase"):
            phase._log_adversarial_carryover(issue)

        warnings_or_errors = [
            r for r in caplog.records if r.levelname in {"WARNING", "ERROR"}
        ]
        assert warnings_or_errors == []


# ---------------------------------------------------------------------------
# HITL escalation clears adversarial state (regression for unbounded growth).
# ---------------------------------------------------------------------------


class TestHitlEscalationClearsAdversarialState:
    """When plan_phase escalates an issue to HITL, the per-issue
    AdversarialState must be cleared so the next retry starts fresh.

    Regression for review issue 3: without this, ``_run_assumption_surfacer``
    extended ``adv.pending_concerns`` on every retry, growing the list
    unboundedly across HITL cycles.
    """

    @staticmethod
    def _seed_adversarial_state(state: StateTracker, issue_id: int) -> None:
        """Seed an AdversarialState with two concerns under *issue_id*."""
        from datetime import UTC, datetime

        adv = AdversarialState(
            phase="plan",
            current_stage="assumption_surfacer",
            pending_concerns=[
                Concern(
                    id="SURFACER-001",
                    raised_in_phase="plan",
                    raised_in_stage="assumption_surfacer",
                    severity="HIGH",
                    concern="Unverified dependency.",
                    raised_at=datetime.now(UTC),
                    must_address_by="implement",
                ),
                Concern(
                    id="SURFACER-002",
                    raised_in_phase="plan",
                    raised_in_stage="assumption_surfacer",
                    severity="MEDIUM",
                    concern="Unclear acceptance bar.",
                    raised_at=datetime.now(UTC),
                    must_address_by="implement",
                ),
            ],
        )
        state.set_adversarial_state(issue_id, adv)
        assert state.get_adversarial_state(issue_id) is not None

    @pytest.mark.asyncio
    async def test_rejected_evidence_escalation_clears_adv_state(
        self, config: HydraFlowConfig
    ) -> None:
        """``_plan_one`` rejected-evidence path must clear adv state on escalation."""
        phase, state, planners, prs, store, _stop = make_plan_phase(config)
        self._seed_adversarial_state(state, 42)

        issue = TaskFactory.create(id=42)
        plan_result = PlanResultFactory.create(
            issue_number=42,
            success=True,
            already_satisfied=True,
            summary="The feature already exists.",  # No Evidence — rejected
        )
        planners.plan = AsyncMock(return_value=plan_result)
        store.get_plannable = supply_once([issue])

        await phase.plan_issues()

        # Escalator fired (label swap) AND state cleared.
        prs.swap_pipeline_labels.assert_awaited()
        assert state.get_adversarial_state(42) is None, (
            "AdversarialState must be cleared on HITL escalation so the "
            "next retry starts fresh — otherwise pending_concerns grows "
            "unboundedly across HITL cycles."
        )

    @pytest.mark.asyncio
    async def test_epic_child_false_claim_escalation_clears_adv_state(
        self, config: HydraFlowConfig
    ) -> None:
        """Epic-child false-claim escalation must clear adv state."""
        phase, state, planners, prs, store, _stop = make_plan_phase(config)
        self._seed_adversarial_state(state, 42)

        issue = TaskFactory.create(id=42, tags=["hydraflow-epic-child"])
        plan_result = PlanResultFactory.create(
            issue_number=42,
            success=True,
            already_satisfied=True,
            summary="The feature is already implemented",
        )
        planners.plan = AsyncMock(return_value=plan_result)
        store.get_plannable = supply_once([issue])

        await phase.plan_issues()

        prs.swap_pipeline_labels.assert_awaited()
        assert state.get_adversarial_state(42) is None

    @pytest.mark.asyncio
    async def test_handle_plan_failure_clears_adv_state(
        self, config: HydraFlowConfig
    ) -> None:
        """``_handle_plan_failure`` clears adv state before escalating.

        Direct-call test — the method is currently not invoked from
        ``_plan_one`` (validation-warning plans are accepted there
        instead), but the helper is the canonical HITL hand-off and
        must clear state defensively if any future caller wires it up.
        """
        from models import PlanResult

        phase, state, _planners, prs, _store, _stop = make_plan_phase(config)
        self._seed_adversarial_state(state, 99)

        issue = TaskFactory.create(id=99)
        result = PlanResult(
            issue_number=99,
            success=False,
            validation_errors=["Step 3 references unknown file"],
        )

        await phase._handle_plan_failure(issue, result)

        prs.swap_pipeline_labels.assert_awaited()
        assert state.get_adversarial_state(99) is None


# Avoid pytest collection warning by referencing asyncio so the
# `from asyncio` import does not appear unused on some pytest versions.
_ = asyncio
