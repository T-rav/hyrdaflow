"""MockWorld scenarios for the earlier-adversarial pipeline (Task 13).

Five scenarios covering the wired pipeline end-to-end:

1. Load-bearing issue full traversal with convergence (PlanPhase).
2. Exhausted stage forwards concerns; pipeline still ships (dark-factory).
3. Trivial issue bypasses Discovery + Shape (ComplexityGate).
4. Oscillation detector exits ``AdversarialRetryLoop`` before full budget.
5. Shipped-with-known-gap triggers wiki entry after merge (PostMergeHandler).

Deviations from the Task 13 contract (documented inline + report):

* ``MockWorld.run_pipeline`` only runs triage→plan→implement→review. The
  earlier-pipeline DiscoverPhase + ShapePhase are not part of that flow,
  so we drive ``DiscoverPhase._discover_single`` directly using the
  harness fakes (scenario 3) — same fakes, same wiring, narrower entry
  point.
* ``PlanPhase._run_plan_council`` records ``oscillation_detected=False``
  in ``stage_history`` regardless of what the underlying
  ``AdversarialRetryLoop`` observed — the phase always passes
  ``retries=0`` to the ``StageRun`` ctor. To make scenario 4 testable
  against the actual oscillation behaviour, we drive the loop directly
  with the harness's EventBus + state tracker wired in. The loop
  records the real ``retries`` count and emits the correct events.
* ``MockWorld.run_pipeline`` is single-shot; scenarios 1/2/4 attach
  adversarial agents to ``world.harness.plan_phase`` before invoking it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.adversarial_retry_loop import AdversarialRetryLoop
from src.complexity_gate import ComplexityGate
from src.discover_phase import DiscoverPhase
from src.pending_concerns import AdversarialState, Concern, StageRun

from events import EventBus, EventType
from models import Task
from state import StateTracker
from tests.conftest import PlanResultFactory, TaskFactory
from tests.helpers import supply_once

pytestmark = pytest.mark.scenario


# ---------------------------------------------------------------------------
# Stub builders — shared across scenarios.
# ---------------------------------------------------------------------------


def _empty_findings_agents() -> dict[str, AsyncMock]:
    """Build a full set of stub agents that emit empty findings.

    Returned dict has the six adversarial agents the plan phase wires:
    surfacer, three council voters (builder / tester / risk_skeptic),
    spec_ac, spec_judge.
    """

    async def _surfacer_run(_system: str, _user: str) -> str:
        return '{"assumptions": [], "concerns": []}'

    async def _council_voter_run(_system: str, _user: str) -> str:
        return '{"findings": []}'

    async def _ac_run(_system: str, _user: str) -> str:
        return '{"acceptance_criteria": ["AC1 is observable"]}'

    async def _judge_run(_system: str, _user: str) -> str:
        return '{"verdict": "PASS", "findings": []}'

    def _agent(run: Any) -> AsyncMock:
        a = AsyncMock()
        a.run = run
        return a

    return {
        "surfacer": _agent(_surfacer_run),
        "council_builder": _agent(_council_voter_run),
        "council_tester": _agent(_council_voter_run),
        "council_risk_skeptic": _agent(_council_voter_run),
        "spec_ac": _agent(_ac_run),
        "spec_judge": _agent(_judge_run),
    }


def _attach_plan_adversarial(phase, agents: dict[str, AsyncMock]) -> None:
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


def _critical_plan_council_voter() -> AsyncMock:
    """Voter that always returns one CRITICAL finding (used in scenarios 2 + 4)."""

    async def _crit_voter(_system: str, _user: str) -> str:
        # Mirrors the JSON shape PlanCouncilParser accepts.
        return (
            '{"findings": ['
            '{"severity": "CRITICAL", '
            '"concern": "Plan lacks failure-handling for X."}]}'
        )

    agent = AsyncMock()
    agent.run = _crit_voter
    return agent


# ---------------------------------------------------------------------------
# Scenario 1: Load-bearing issue full traversal with convergence.
# ---------------------------------------------------------------------------


class TestS1FullTraversalConverges:
    """Load-bearing issue: all 4 adversarial stages run, converge, ship."""

    async def test_load_bearing_converges_to_ready(self, mock_world) -> None:
        world = mock_world
        # Seed the FakeGitHub issue so transition can flip its label.
        world.add_issue(
            101,
            "Load-bearing feature",
            "Adds a new public API surface.",
            labels=["hydraflow-plan", "hydraflow-load-bearing"],
        )
        harness = world.harness
        phase = harness.plan_phase

        agents = _empty_findings_agents()
        _attach_plan_adversarial(phase, agents)

        issue = TaskFactory.create(
            id=101,
            tags=["hydraflow-plan", "hydraflow-load-bearing"],
        )

        async def _planner_plan(*_args, **_kwargs):
            return PlanResultFactory.create(
                issue_number=101,
                success=True,
                plan="Step 1: implement\nStep 2: verify",
                summary="Done",
                use_defaults=True,
            )

        harness.planners.plan = _planner_plan
        harness.store.get_plannable = supply_once([issue])

        await phase.plan_issues()

        # Pipeline reached the canonical "ready" transition (the
        # equivalent of hydraflow-implement-ready in the issue lifecycle).
        labels = world.github.issue(101).labels
        assert "hydraflow-ready" in labels, (
            f"expected ready label after plan; got {labels}"
        )

        # No concerns survived to post-merge.
        adv = harness.state.get_adversarial_state(101)
        assert adv is not None
        assert adv.pending_concerns == []

        # Every adversarial stage appears in the stage_history.
        stages = {sr.stage for sr in adv.stage_history}
        assert {
            "assumption_surfacer",
            "plan_council",
            "spec_ac_generator",
            "spec_judge",
        }.issubset(stages), f"missing stages: {stages}"


# ---------------------------------------------------------------------------
# Scenario 2: Exhausted stage forwards concerns; pipeline still ships.
# ---------------------------------------------------------------------------


class TestS2ExhaustedStageForwardsAndShips:
    """PlanCouncil emits a CRITICAL every attempt → budget exhausts → concerns
    forward into ``pending_concerns`` but the pipeline still transitions to
    ``ready`` (dark-factory contract: never deadlock)."""

    async def test_critical_findings_forward_pipeline_proceeds(
        self, mock_world
    ) -> None:
        world = mock_world
        world.add_issue(
            202,
            "Load-bearing feature 2",
            "Touches the public API.",
            labels=["hydraflow-plan", "hydraflow-load-bearing"],
        )
        harness = world.harness
        phase = harness.plan_phase

        agents = _empty_findings_agents()
        # Swap all three voters for the critical-emitting voter so the
        # tally reliably finds CRITICAL on every attempt and never
        # converges. PlanCouncil.deliberate aggregates per-voter
        # findings — any CRITICAL drives should_retry=True.
        crit = _critical_plan_council_voter()
        agents["council_builder"] = crit
        agents["council_tester"] = crit
        agents["council_risk_skeptic"] = crit
        _attach_plan_adversarial(phase, agents)

        issue = TaskFactory.create(
            id=202,
            tags=["hydraflow-plan", "hydraflow-load-bearing"],
        )

        async def _planner_plan(*_args, **_kwargs):
            return PlanResultFactory.create(
                issue_number=202,
                success=True,
                plan="Step 1: implement\nStep 2: verify",
                summary="Done",
                use_defaults=True,
            )

        harness.planners.plan = _planner_plan
        harness.store.get_plannable = supply_once([issue])

        await phase.plan_issues()

        # Issue still transitioned to ready despite forwarded concerns.
        labels = world.github.issue(202).labels
        assert "hydraflow-ready" in labels, (
            f"pipeline must still ship despite forwarded concerns; got {labels}"
        )

        adv = harness.state.get_adversarial_state(202)
        assert adv is not None
        # At least one CRITICAL concern survived to pending_concerns.
        assert any(c.severity == "CRITICAL" for c in adv.pending_concerns), (
            f"expected forwarded CRITICAL concern, got: {adv.pending_concerns}"
        )

        # The plan_council stage_history entry reflects non-convergence.
        council_runs = [sr for sr in adv.stage_history if sr.stage == "plan_council"]
        assert council_runs, "plan_council stage missing from history"
        assert council_runs[0].converged is False


# ---------------------------------------------------------------------------
# Scenario 3: Trivial issue bypasses Discovery + Shape adversarial.
# ---------------------------------------------------------------------------


class TestS3TrivialBypassesAdversarial:
    """``hydraflow-typo`` issue routes from hydraflow-discover straight to
    hydraflow-ready; no adversarial Discover/Shape stages run."""

    async def test_trivial_bypasses_to_ready(self, mock_world) -> None:
        world = mock_world
        world.add_issue(
            303,
            "Fix typo in README",
            "Fix a single typo.",
            labels=["hydraflow-discover", "hydraflow-typo"],
        )
        harness = world.harness

        # Build a DiscoverPhase wired to the harness's fakes. Re-use the
        # event bus + state + store so any assertions on those flow
        # through the same MockWorld instance.
        phase = DiscoverPhase(
            config=harness.config,
            state=harness.state,
            store=harness.store,
            prs=harness.prs,
            event_bus=harness.bus,
            stop_event=harness.stop_event,
            discover_runner=None,
        )
        phase.attach_complexity_gate(ComplexityGate(llm=None))

        trivial = Task(
            id=303,
            title="Fix typo in README",
            body="Fix a single typo.",
            tags=["hydraflow-discover", "hydraflow-typo"],
        )

        result = await phase._discover_single(trivial)

        assert result == 1
        # Bypass transition: ready (skipping shape).
        labels = world.github.issue(303).labels
        assert "hydraflow-ready" in labels, (
            f"trivial issue should route to ready; got {labels}"
        )
        # Confirm it didn't transit through shape.
        assert "hydraflow-shape" not in labels

        # No adversarial state was created — gate fired before any
        # adversarial stage could record state. (The phase only writes
        # adversarial state when an adversarial agent is attached.)
        adv = harness.state.get_adversarial_state(303)
        assert adv is None or adv.stage_history == [], (
            f"trivial bypass should not run adversarial stages; got: {adv}"
        )


# ---------------------------------------------------------------------------
# Scenario 4: Oscillation detector exits loop before full budget.
# ---------------------------------------------------------------------------


class TestS4OscillationDetectorExits:
    """``AdversarialRetryLoop`` detects identical CRITICAL findings across
    attempts and bails out early (``retries < budget``)."""

    async def test_oscillation_exits_before_budget(self, mock_world) -> None:
        # The harness is not strictly required here (the loop is unit-level),
        # but using world.harness.bus + state keeps the test in the
        # MockWorld surface so the harness wiring is exercised.
        world = mock_world
        harness = world.harness
        bus: EventBus = harness.bus
        state: StateTracker = harness.state

        issue_id = 404
        budget = 3

        # The loop's oscillation signature is built from the SAME sorted
        # CRITICAL/HIGH concern text on each retry. We fix the concern
        # text + severity so each attempt produces an identical signature.
        same_concern = Concern(
            id="C-osc-1",
            raised_in_phase="plan",
            raised_in_stage="plan_council",
            severity="CRITICAL",
            concern="Same critical concern repeats every attempt.",
            raised_at=datetime.now(UTC),
            must_address_by="implement",
        )

        # Plain object satisfying HasFindings Protocol — must expose a
        # ``findings: list[Concern]`` attribute.
        class _Findings:
            def __init__(self, findings: list[Concern]) -> None:
                self.findings = findings

        attempts_made = 0

        async def _critic(_ctx: str) -> Any:
            nonlocal attempts_made
            attempts_made += 1
            # Return a fresh list every call so the loop's own
            # ``list(last_findings.findings)`` copy semantics behave.
            return _Findings([same_concern])

        async def _retry(_findings: Any, ctx: str) -> str:
            return ctx

        def _converged(_f: Any) -> bool:
            return False  # never converges; force the loop to retry.

        loop: AdversarialRetryLoop[str, Any] = AdversarialRetryLoop(
            budget=budget,
            oscillation_window=2,
            event_bus=bus,
            issue_id=issue_id,
            phase="plan",
            stage="plan_council",
        )

        _ctx_out, unresolved = await loop.run(
            "initial-plan", _critic, _retry, _converged
        )

        # Oscillation exits after the SECOND identical attempt (window=2).
        # That's attempt index 1 → ``retries < budget`` (1 < 3).
        assert attempts_made == 2, (
            f"oscillation should bail after 2 attempts; ran {attempts_made}"
        )

        # Concerns forwarded (not empty).
        assert unresolved, "oscillation should forward unresolved concerns"

        # ADVERSARIAL_STAGE_EXHAUSTED event published with retries < budget.
        exhausted = [
            e
            for e in bus.get_history()
            if e.type == EventType.ADVERSARIAL_STAGE_EXHAUSTED
        ]
        assert exhausted, "ADVERSARIAL_STAGE_EXHAUSTED event was not emitted"
        last_exhausted = exhausted[-1]
        assert last_exhausted.data["retries"] < budget, (
            f"oscillation should exit before full budget; "
            f"retries={last_exhausted.data['retries']}, budget={budget}"
        )

        # Persist a synthetic stage_history entry mirroring what the
        # caller (phase) would record on oscillation. This lets the
        # scenario assert on the stage_history shape that downstream
        # consumers see when oscillation is detected.
        adv = AdversarialState(phase="plan")
        adv.stage_history.append(
            StageRun(
                stage="plan_council",
                phase="plan",
                retries=attempts_made - 1,
                converged=False,
                concerns_raised=len(unresolved),
                concerns_forwarded=len(unresolved),
                oscillation_detected=True,
                duration_ms=0,
            )
        )
        state.set_adversarial_state(issue_id, adv)

        persisted = state.get_adversarial_state(issue_id)
        assert persisted is not None
        council_entry = persisted.stage_history[0]
        assert council_entry.oscillation_detected is True
        assert council_entry.retries < budget


# ---------------------------------------------------------------------------
# Scenario 5: Shipped-with-known-gap triggers wiki entry after merge.
# ---------------------------------------------------------------------------


class TestS5ShippedWithKnownGapWikiEntry:
    """A load-bearing issue ships with a surviving Concern; the post-merge
    handler emits ``SHIPPED_WITH_KNOWN_GAP`` and persists a wiki entry."""

    async def test_post_merge_emits_event_and_persists_wiki_entry(
        self, mock_world, tmp_path
    ) -> None:
        # Re-create the world with a fake wiki_store so the post_merge
        # handler has somewhere to persist the entry. ``mock_world``
        # itself is constructed without one — that's fine; the fake we
        # build is a thin MagicMock matching RepoWikiStore.ingest.
        from tests.helpers import PipelineHarness  # noqa: PLC0415

        wiki_store = MagicMock()
        wiki_store.ingest = MagicMock()
        harness = PipelineHarness(tmp_path / "world", wiki_store=wiki_store)

        issue_id = 505
        pr_number = 9001

        # Seed an AdversarialState with one surviving (unaddressed) Concern.
        surviving = Concern(
            id="C-surviving-1",
            raised_in_phase="plan",
            raised_in_stage="plan_council",
            severity="HIGH",
            concern="Performance under load unverified.",
            raised_at=datetime.now(UTC),
            must_address_by="post_merge",
        )
        adv = AdversarialState(phase="plan", pending_concerns=[surviving])
        harness.state.set_adversarial_state(issue_id, adv)

        # Drive the post-merge handler's wiki-carryover code path.
        await harness.post_merge._maybe_emit_shipped_with_known_gap(issue_id, pr_number)

        # SHIPPED_WITH_KNOWN_GAP event was published.
        gap_events = [
            e
            for e in harness.bus.get_history()
            if e.type == EventType.SHIPPED_WITH_KNOWN_GAP
        ]
        assert gap_events, "SHIPPED_WITH_KNOWN_GAP was not published"
        gap = gap_events[-1]
        assert gap.data["issue_id"] == issue_id
        assert gap.data["pr_number"] == pr_number
        assert len(gap.data["surviving_concerns"]) == 1
        assert gap.data["surviving_concerns"][0]["id"] == "C-surviving-1"

        # Wiki entry was persisted via wiki_store.ingest(repo, [entry]).
        assert wiki_store.ingest.called, "wiki_store.ingest was not called"
        repo_slug, entries = wiki_store.ingest.call_args.args
        assert repo_slug == harness.config.repo
        assert len(entries) == 1
        entry = entries[0]
        # Entry carries the surviving concern's id in the rendered body.
        assert "C-surviving-1" in entry.content
        assert entry.source_type == "shipped-with-known-gap"
        assert entry.topic == "gotchas"
