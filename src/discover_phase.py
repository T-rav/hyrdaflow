"""Discover phase — product research for vague/broad issues."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from adversarial_agents import AgentLike
from adversarial_retry_loop import AdversarialRetryLoop
from assumption_surfacer import AssumptionSurfacer, SurfacerOutput
from complexity_gate import Complexity, ComplexityGate
from config import HydraFlowConfig
from dedup_store import DedupStore
from discover_runner import DiscoverRunner
from discovery_council import CouncilTally, DiscoveryCouncil
from events import EventBus, EventType, HydraFlowEvent
from models import DiscoverResult, Task
from pending_concerns import AdversarialState, StageRun
from phase_utils import (
    _sentry_transaction,
    run_refilling_pool,
    store_lifecycle,
)
from state import StateTracker
from task_source import TaskTransitioner

if TYPE_CHECKING:
    from ports import IssueStorePort, PRPort

logger = logging.getLogger("hydraflow.discover_phase")


class _TaskAsIssueLike:
    """Adapt ``Task.tags`` to ``IssueLike.labels`` for ComplexityGate.

    ``Task`` (the source-agnostic representation used inside phases) names
    the label list ``tags``; ``ComplexityGate.classify`` reads ``labels``
    per the ``IssueLike`` Protocol. This zero-cost wrapper bridges the
    two without forcing every Task carrier to also expose ``labels``.
    """

    __slots__ = ("body", "labels")

    def __init__(self, task: Task) -> None:
        self.body = task.body or ""
        self.labels = list(task.tags)


class DiscoverPhase:
    """Runs product discovery research on vague issues.

    Fetches issues from the discover queue, runs research (competitors,
    market gaps, user needs), posts a research brief as a comment, and
    transitions the issue to the shape stage.
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        state: StateTracker,
        store: IssueStorePort,
        prs: PRPort,
        event_bus: EventBus,
        stop_event: asyncio.Event,
        discover_runner: DiscoverRunner | None = None,
    ) -> None:
        self._config = config
        self._state = state
        self._store = store
        self._prs = prs
        self._transitioner: TaskTransitioner = prs
        self._bus = event_bus
        self._stop_event = stop_event
        self._runner = discover_runner
        if self._runner is not None:
            dedup = DedupStore(
                "hitl_escalations",
                config.data_root / "memory" / "hitl_escalations_dedup.json",
            )
            self._runner.bind_escalation_deps(self._prs, dedup)  # type: ignore[arg-type]
        # Earlier-adversarial pipeline agents (ADR-pending). Optional —
        # the factory wires them in when feature-enabled; legacy paths
        # leave them None and the adversarial stages are skipped. See
        # ``attach_adversarial_agents`` for the production entry point.
        self._surfacer_agent: AgentLike | None = None
        self._council_agents: dict[str, AgentLike] | None = None
        self._adversarial_budget: int = 3
        # ComplexityGate (Task 10). Optional — when attached, trivial
        # issues bypass Discovery + Shape entirely and transition to
        # ``hydraflow-ready``. Load-bearing issues proceed through the
        # canonical discovery flow. Legacy paths leave this None and
        # every discover-labeled issue runs full discovery.
        self._complexity_gate: ComplexityGate | None = None

    # ------------------------------------------------------------------
    # Earlier-adversarial pipeline wiring (ADR-pending)
    # ------------------------------------------------------------------

    def attach_adversarial_agents(
        self,
        *,
        surfacer_agent: AgentLike | None = None,
        council_agents: dict[str, AgentLike] | None = None,
        budget: int = 3,
    ) -> None:
        """Wire the two Discovery-phase adversarial agents onto this phase.

        Called by the factory once on construction (or by tests). Each
        agent is independently optional — when ``None``, that stage is
        skipped, the rest of the pipeline runs unchanged. Both together
        enable the full Surfacer → Council sequence around the existing
        DiscoverRunner.

        ``council_agents`` must contain keys ``problem_sharpener``,
        ``existing_solution_hunter``, ``cheapest_test_advocate`` (per
        ``DiscoveryCouncil``'s contract).
        """
        self._surfacer_agent = surfacer_agent
        self._council_agents = council_agents
        self._adversarial_budget = budget

    def attach_complexity_gate(self, gate: ComplexityGate) -> None:
        """Wire the ComplexityGate onto this phase.

        Called by the factory once on construction (or by tests). When
        attached, the gate runs at the top of each discover invocation:
        trivial issues bypass Discovery + Shape entirely and transition
        directly to ``hydraflow-ready``; load-bearing issues proceed
        through the canonical discovery flow.

        Backward-compat: when no gate is attached, every discover-labeled
        issue runs full discovery (no bypass).
        """
        self._complexity_gate = gate

    def _has_any_adversarial_agent(self) -> bool:
        return self._surfacer_agent is not None or self._council_agents is not None

    def _persist_adversarial_state(self, issue: Task, adv: AdversarialState) -> None:
        """Persist *adv* into state.json under the issue's key.

        Per contract: every adversarial stage persists before returning
        so the next stage (and shape_phase) can read the accumulated
        pending concerns.
        """
        self._state.set_adversarial_state(issue.id, adv)

    async def _run_assumption_surfacer(
        self, issue: Task, adv: AdversarialState, research_context: str
    ) -> None:
        """Surface assumptions + uncertainty concerns before the council.

        One-shot — the surfacer is a read-only critic. Concerns are
        appended to ``adv.pending_concerns`` and the state is persisted
        before returning.
        """
        if self._surfacer_agent is None:
            return
        surfacer = AssumptionSurfacer(agent=self._surfacer_agent, phase="discover")
        out: SurfacerOutput = await surfacer.run(
            issue_body=issue.body or "",
            research_context=research_context,
            carryover_concerns=list(adv.pending_concerns),
        )
        adv.pending_concerns.extend(out.concerns)
        adv.current_stage = "assumption_surfacer"
        adv.stage_history.append(
            StageRun(
                stage="assumption_surfacer",
                phase="discover",
                retries=0,
                converged=True,
                concerns_raised=len(out.concerns),
                concerns_forwarded=len(out.concerns),
                oscillation_detected=False,
                duration_ms=0,
            )
        )
        self._persist_adversarial_state(issue, adv)

    async def _run_discovery_council(
        self,
        issue: Task,
        adv: AdversarialState,
        discovery_text: str,
    ) -> None:
        """DiscoveryCouncil tight-loop around the (already-produced) brief.

        Wired via AdversarialRetryLoop with the configured budget.
        Because the DiscoverRunner has already produced its brief and we
        don't currently re-invoke it on Council retry, the loop runs the
        Council with a no-op ``retry`` step so unresolved concerns
        forward rather than block. Honors the dark-factory contract:
        never deadlock; surface, persist, forward.
        """
        if self._council_agents is None:
            return
        council = DiscoveryCouncil(agents=self._council_agents)

        async def _critic(_ctx: str) -> CouncilTally:
            return await council.deliberate(
                discovery_text=_ctx, pending_concerns=list(adv.pending_concerns)
            )

        async def _retry(_findings: CouncilTally, ctx: str) -> str:
            # The brief text is unchanged on retry — we do not currently
            # re-invoke the DiscoverRunner from inside the council loop.
            # In a future pass we may thread a runner-retry callback in
            # here. For now: forward findings (dark-factory contract)
            # once budget is exhausted.
            return ctx

        def _converged(t: CouncilTally) -> bool:
            return not t.should_retry

        loop: AdversarialRetryLoop[str, CouncilTally] = AdversarialRetryLoop(
            budget=self._adversarial_budget,
            event_bus=self._bus,
            issue_id=issue.id,
            phase="discover",
            stage="discovery_council",
        )
        _ctx_out, unresolved, metrics = await loop.run_with_metrics(
            discovery_text, _critic, _retry, _converged
        )
        adv.pending_concerns.extend(unresolved)
        adv.current_stage = "discovery_council"
        adv.stage_history.append(
            StageRun(
                stage="discovery_council",
                phase="discover",
                retries=metrics.retries,
                converged=not bool(unresolved),
                concerns_raised=metrics.total_concerns_raised,
                concerns_forwarded=len(unresolved),
                oscillation_detected=metrics.oscillation_detected,
                duration_ms=0,
            )
        )
        self._persist_adversarial_state(issue, adv)

    async def discover_issues(self) -> bool:
        """Process discover-labeled issues. Returns True if work was done."""

        async def _discover_one(_idx: int, issue: Task) -> int:
            if self._stop_event.is_set():
                return 0
            return await self._discover_single(issue)

        results = await run_refilling_pool(
            supply_fn=lambda: self._store.get_discoverable(1),
            worker_fn=_discover_one,
            max_concurrent=self._config.max_triagers,
            stop_event=self._stop_event,
        )
        return bool(sum(results))

    async def _discover_single(self, issue: Task) -> int:
        """Run product discovery for a single issue."""
        with _sentry_transaction("pipeline.discover", f"discover:#{issue.id}"):
            async with store_lifecycle(self._store, issue.id, "discover"):
                await self._bus.publish(
                    HydraFlowEvent(
                        type=EventType.DISCOVER_UPDATE,
                        data={"issue": issue.id, "action": "started"},
                    )
                )

                # ComplexityGate (Task 10). When attached, trivial issues
                # bypass Discovery + Shape entirely and transition straight
                # to hydraflow-ready. Load-bearing issues fall through to
                # the canonical discovery flow. The gate is opt-in — no
                # gate attached means no bypass (legacy behavior).
                #
                # ComplexityGate's IssueLike protocol expects ``.labels``;
                # ``Task`` exposes the same data as ``tags``. Wrap to bridge.
                if self._complexity_gate is not None:
                    complexity = await self._complexity_gate.classify(
                        _TaskAsIssueLike(issue)
                    )
                    if complexity == Complexity.TRIVIAL:
                        if not self._config.dry_run:
                            self._store.enqueue_transition(issue, "ready")
                            await self._transitioner.transition(issue.id, "ready")
                            self._state.increment_session_counter(
                                "complexity_gate_bypass"
                            )
                        await self._bus.publish(
                            HydraFlowEvent(
                                type=EventType.DISCOVER_UPDATE,
                                data={
                                    "issue": issue.id,
                                    "action": "bypassed",
                                    "complexity": "trivial",
                                },
                            )
                        )
                        logger.info(
                            "Issue #%d trivial — bypassing Discovery + Shape → %s",
                            issue.id,
                            self._config.ready_label[0],
                        )
                        return 1

                # Earlier-adversarial pipeline stage 1: surface assumptions
                # before the runner produces its brief. No-op when no agent
                # is attached. Reads carryover from any prior phase (none
                # currently feeds discover, but the carryover contract is
                # uniform across phases).
                adv: AdversarialState | None = None
                if self._has_any_adversarial_agent():
                    adv = self._state.get_adversarial_state(issue.id) or (
                        AdversarialState(phase="discover")
                    )
                    await self._run_assumption_surfacer(issue, adv, research_context="")

                if self._runner:
                    result = await self._runner.discover(issue)
                else:
                    result = DiscoverResult(
                        issue_number=issue.id,
                        research_brief=(
                            "Product discovery research requires a DiscoverRunner. "
                            "Configure the discover runner to enable real product research."
                        ),
                        opportunities=["Discovery runner not configured"],
                    )

                # Earlier-adversarial pipeline stage 2: DiscoveryCouncil
                # tight-loop around the produced brief. Concerns are
                # persisted and forward to ``shape`` per the dark-factory
                # contract.
                #
                # Gate on ``self._runner`` as well: when no runner is
                # attached, ``result.research_brief`` is the hardcoded
                # stub placeholder above, and running the council against
                # that text just generates noise concerns and forwards
                # them to shape. Skip the council in degraded mode.
                if adv is not None and self._runner is not None:
                    await self._run_discovery_council(
                        issue, adv, discovery_text=result.research_brief
                    )

                # Post research brief as structured comment
                comment = self._format_research_brief(issue, result)
                if not self._config.dry_run:
                    await self._transitioner.post_comment(issue.id, comment)
                    self._store.enqueue_transition(issue, "shape")
                    await self._transitioner.transition(issue.id, "shape")
                    self._state.increment_session_counter("discovered")

                await self._bus.publish(
                    HydraFlowEvent(
                        type=EventType.DISCOVER_UPDATE,
                        data={"issue": issue.id, "action": "completed"},
                    )
                )
                logger.info(
                    "Issue #%d discovery complete → %s",
                    issue.id,
                    self._config.shape_label[0],
                )
                return 1

    def _format_research_brief(self, issue: Task, result: DiscoverResult) -> str:
        """Format a research brief as a structured GitHub comment."""
        lines = [
            "## Product Discovery Brief",
            "",
            f"**Issue:** #{issue.id} — {issue.title}",
            "",
            "### Research Summary",
            "",
            result.research_brief,
            "",
        ]
        if result.competitors:
            lines.extend(["### Competitors Analyzed", ""])
            for comp in result.competitors:
                lines.append(f"- {comp}")
            lines.append("")
        if result.user_needs:
            lines.extend(["### User Needs Identified", ""])
            for need in result.user_needs:
                lines.append(f"- {need}")
            lines.append("")
        if result.opportunities:
            lines.extend(["### Opportunities", ""])
            for opp in result.opportunities:
                lines.append(f"- {opp}")
            lines.append("")
        lines.append("---")
        lines.append(
            "*This issue will proceed to product shaping for direction selection.*"
        )
        return "\n".join(lines)
