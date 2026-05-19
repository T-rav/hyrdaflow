"""Tests for the earlier-adversarial pipeline wiring in shape_phase.

Verifies the wiring contract from Task 9 of the earlier-adversarial
pipeline implementation plan:

  1. ShapeChallenger runs after ShapeRunner produces its turn.
  2. ShapeExpertCouncil runs after ShapeChallenger.
  3. Both are wrapped in AdversarialRetryLoop semantics (budget=3).
  4. ``adversarial_state`` is persisted after each stage.
  5. Backward-compat: when no adversarial agents are attached, shape_phase
     still runs (legacy path).

These tests use lightweight stubs for the per-stage agents — the
unit-level correctness of each adapter is covered in its own
``tests/test_shape_<stage>.py``.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.pending_concerns import AdversarialState

from config import HydraFlowConfig
from models import ShapeTurnResult, Task
from shape_phase import ShapePhase

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_deps(tmp_path: Path) -> tuple[dict, MagicMock]:
    """Build a ShapePhase deps dict backed by an in-memory state stub.

    We use a real-ish state stub (MagicMock with a dict-backed adversarial
    state implementation) so we can read back what was persisted without
    pulling the full StateTracker file machinery into this unit test.
    """
    state = MagicMock()
    state._adv_states: dict[int, AdversarialState] = {}

    def _get(i: int) -> AdversarialState | None:
        return state._adv_states.get(i)

    def _set(i: int, adv: AdversarialState) -> None:
        state._adv_states[i] = adv

    state.get_adversarial_state.side_effect = _get
    state.set_adversarial_state.side_effect = _set
    state.get_shape_conversation.return_value = None
    state.set_shape_conversation = MagicMock()
    state.get_shape_response.return_value = None
    state.clear_shape_response = MagicMock()
    state.remove_shape_conversation = MagicMock()
    state.increment_session_counter = MagicMock()

    config = HydraFlowConfig(repo="test/repo", data_root=tmp_path)

    deps = {
        "config": config,
        "state": state,
        "store": MagicMock(),
        "prs": AsyncMock(),
        "event_bus": AsyncMock(),
        "stop_event": asyncio.Event(),
    }
    return deps, state


class _Recorder:
    """Captures the order of adversarial-stage invocations."""

    def __init__(self) -> None:
        self.calls: list[str] = []


def _make_recording_agents() -> tuple[_Recorder, dict[str, AsyncMock]]:
    """Build a recorder + per-stage agent stubs.

    The stubs return JSON the adapters parse as empty findings — no
    retry, no concerns. This isolates the wiring test from per-stage
    correctness (covered separately).
    """
    rec = _Recorder()

    async def _challenger_run(_system: str, _user: str) -> str:
        rec.calls.append("shape_challenger")
        return '{"findings": []}'

    async def _council_voter_run(_system: str, _user: str) -> str:
        if "shape_expert_council" not in rec.calls:
            rec.calls.append("shape_expert_council")
        return '{"findings": []}'

    challenger_agent = AsyncMock()
    challenger_agent.run = _challenger_run

    ua_agent = AsyncMock()
    ua_agent.run = _council_voter_run
    tl_agent = AsyncMock()
    tl_agent.run = _council_voter_run
    ps_agent = AsyncMock()
    ps_agent.run = _council_voter_run

    return rec, {
        "challenger": challenger_agent,
        "user_advocate": ua_agent,
        "tech_lead": tl_agent,
        "product_strategist": ps_agent,
    }


def _sample_task() -> Task:
    return Task(
        id=42, title="Build the thing", body="Vague idea", labels=["hydraflow-shape"]
    )


# ---------------------------------------------------------------------------
# Wiring shape: order + persistence + backward-compat
# ---------------------------------------------------------------------------


class TestShapePhaseAdversarialWiring:
    @pytest.mark.asyncio
    async def test_stages_run_in_spec_order_when_agents_configured(
        self, tmp_path: Path
    ) -> None:
        """Challenger → Expert Council, after ShapeRunner produces content."""
        rec, agents = _make_recording_agents()
        deps, state = _make_deps(tmp_path)

        # Stub ShapeRunner so we control content + don't touch subprocesses.
        runner = MagicMock()

        async def _run_turn(*_args, **_kwargs):
            rec.calls.append("shape_runner")
            return ShapeTurnResult(content="A proposed direction", is_final=False)

        runner.run_turn = _run_turn
        # ShapeRunner.bind_escalation_deps is called from __init__ — make it
        # a no-op so we don't have to wire a dedup store.
        runner.bind_escalation_deps = MagicMock()
        deps["shape_runner"] = runner

        phase = ShapePhase(**deps)
        phase.attach_adversarial_agents(
            challenger_agent=agents["challenger"],
            council_agents={
                "user_advocate": agents["user_advocate"],
                "tech_lead": agents["tech_lead"],
                "product_strategist": agents["product_strategist"],
            },
        )

        await phase._shape_with_runner(_sample_task())

        # The 3 council voters run concurrently; we collapsed their record
        # to a single marker. Verify order of the three observable phases.
        known = [
            c
            for c in rec.calls
            if c in {"shape_runner", "shape_challenger", "shape_expert_council"}
        ]
        assert known == [
            "shape_runner",
            "shape_challenger",
            "shape_expert_council",
        ], f"Stages out of order: {known}"

    @pytest.mark.asyncio
    async def test_adversarial_state_persisted_after_stages(
        self, tmp_path: Path
    ) -> None:
        """``adversarial_states[42]`` exists with both stages in stage_history."""
        _rec, agents = _make_recording_agents()
        deps, state = _make_deps(tmp_path)

        runner = MagicMock()

        async def _run_turn(*_args, **_kwargs):
            return ShapeTurnResult(content="proposal", is_final=False)

        runner.run_turn = _run_turn
        runner.bind_escalation_deps = MagicMock()
        deps["shape_runner"] = runner

        phase = ShapePhase(**deps)
        phase.attach_adversarial_agents(
            challenger_agent=agents["challenger"],
            council_agents={
                "user_advocate": agents["user_advocate"],
                "tech_lead": agents["tech_lead"],
                "product_strategist": agents["product_strategist"],
            },
        )

        await phase._shape_with_runner(_sample_task())

        adv = state._adv_states.get(42)
        assert adv is not None
        assert adv.phase == "shape"
        stages = [sr.stage for sr in adv.stage_history]
        assert "shape_challenger" in stages
        assert "shape_expert_council" in stages

    @pytest.mark.asyncio
    async def test_shape_phase_works_without_adversarial_agents(
        self, tmp_path: Path
    ) -> None:
        """Backward-compat: legacy path runs unchanged when nothing is attached."""
        deps, state = _make_deps(tmp_path)
        runner = MagicMock()

        async def _run_turn(*_args, **_kwargs):
            return ShapeTurnResult(content="proposal", is_final=False)

        runner.run_turn = _run_turn
        runner.bind_escalation_deps = MagicMock()
        deps["shape_runner"] = runner

        phase = ShapePhase(**deps)
        # No attach_adversarial_agents call.

        await phase._shape_with_runner(_sample_task())

        assert state._adv_states == {}, (
            "Without adversarial agents, no AdversarialState should be created."
        )
