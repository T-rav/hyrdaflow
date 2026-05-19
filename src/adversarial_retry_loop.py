from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Generic, Protocol, TypeVar

from pending_concerns import Concern
from subprocess_util import CreditExhaustedError

if TYPE_CHECKING:
    from events import EventBus

logger = logging.getLogger(__name__)

Ctx = TypeVar("Ctx")


class HasFindings(Protocol):
    findings: list[Concern]


F = TypeVar("F", bound=HasFindings)


@dataclass(frozen=True)
class RunMetrics:
    """Observability metrics for one ``AdversarialRetryLoop.run`` invocation.

    Returned alongside the final context + unresolved concerns by
    :py:meth:`AdversarialRetryLoop.run_with_metrics`. Callers plumb
    these into ``StageRun(retries=..., oscillation_detected=...,
    concerns_raised=...)`` so dashboards can distinguish "converged
    first try" from "oscillated twice and exhausted" — the original
    ``run()`` shape hardcoded ``retries=0`` at every callsite, hiding
    that signal.

    ``total_concerns_raised`` is the cumulative count of ``findings``
    emitted by the critic across all attempts inside the loop —
    *every* concern the stage saw, not just the unresolved tail that
    forwarded. This is the semantic ``StageRun.concerns_raised``
    expects per :class:`src.pending_concerns.StageRun`; the
    forwarded-tail count belongs on ``concerns_forwarded`` instead.
    On a stage that converges on the first attempt with zero findings
    this is ``0``; on a stage that raises 3 then 0 (converges after
    one retry) it is ``3``.
    """

    retries: int
    oscillation_detected: bool
    crashed: bool
    total_concerns_raised: int = 0


class AdversarialRetryLoop(Generic[Ctx, F]):
    """Tight-loop retry with oscillation detection and forwarding fallback.

    On budget exhaustion, returns unresolved concerns rather than blocking.
    Per dark-factory contract: never deadlock.

    Optional EventBus wiring
    ------------------------
    When constructed with ``event_bus``, ``issue_id``, ``phase`` and
    ``stage`` the loop emits adversarial-stage observability events:

    * ``ADVERSARIAL_STAGE_STARTED`` at the top of each attempt
    * ``ADVERSARIAL_STAGE_CONVERGED`` on convergence
    * ``ADVERSARIAL_STAGE_EXHAUSTED`` on budget exhaustion / oscillation /
      crash bail-out
    * ``CONCERN_FORWARDED`` for each unresolved concern when forwarding

    All four kwargs are optional and default to ``None`` so the existing
    public API (and existing call sites) keep working unchanged. If
    ``event_bus`` is set but identity fields are missing, emission is
    silently skipped — wiring is opt-in, not load-bearing.
    """

    def __init__(
        self,
        budget: int = 3,
        oscillation_window: int = 2,
        *,
        event_bus: EventBus | None = None,
        issue_id: int | None = None,
        phase: str | None = None,
        stage: str | None = None,
    ):
        self.budget = budget
        self.oscillation_window = oscillation_window
        self._event_bus = event_bus
        self._issue_id = issue_id
        self._phase = phase
        self._stage = stage

    async def run(
        self,
        initial_ctx: Ctx,
        critic: Callable[[Ctx], Awaitable[F]],
        retry: Callable[[F, Ctx], Awaitable[Ctx]],
        is_converged: Callable[[F], bool],
    ) -> tuple[Ctx, list[Concern]]:
        """Backward-compatible entry point — discards :class:`RunMetrics`.

        Existing callers (and tests) keep their two-tuple return shape.
        New callers that need ``retries`` / ``oscillation_detected``
        for ``StageRun`` propagation should call :py:meth:`run_with_metrics`.
        """
        ctx, unresolved, _metrics = await self.run_with_metrics(
            initial_ctx, critic, retry, is_converged
        )
        return ctx, unresolved

    async def run_with_metrics(
        self,
        initial_ctx: Ctx,
        critic: Callable[[Ctx], Awaitable[F]],
        retry: Callable[[F, Ctx], Awaitable[Ctx]],
        is_converged: Callable[[F], bool],
    ) -> tuple[Ctx, list[Concern], RunMetrics]:
        """Run the loop and return ``(ctx, unresolved, RunMetrics)``.

        The third tuple element exposes the actual ``retries`` consumed
        and whether oscillation was detected, so callers can plumb the
        real values into ``StageRun(retries=..., oscillation_detected=...)``
        instead of hardcoding ``0`` / ``False``.

        ``retries`` is the number of completed retry steps — i.e. how
        many times the ``retry`` callable was invoked, which for
        convergence-on-first-pass is ``0``.  ``crashed`` is True if the
        loop returned because of three consecutive critic crashes (the
        synthetic-crash-concern path).
        """
        ctx = initial_ctx
        recent_signatures: list[str] = []
        consecutive_crashes = 0
        last_findings: F | None = None
        total_concerns_raised = 0
        retries_completed = 0

        for attempt in range(self.budget + 1):
            await self._emit_stage_started(retry_count=attempt)
            try:
                findings = await critic(ctx)
                consecutive_crashes = 0
            except CreditExhaustedError:
                raise
            except Exception as exc:
                logger.warning("critic crashed on attempt %s: %s", attempt, exc)
                consecutive_crashes += 1
                if consecutive_crashes >= 3:
                    crash_concerns = [_synthetic_crash_concern(exc)]
                    await self._emit_concerns_forwarded(crash_concerns)
                    await self._emit_stage_exhausted(
                        retries=attempt,
                        concerns_forwarded=len(crash_concerns),
                    )
                    return (
                        ctx,
                        crash_concerns,
                        RunMetrics(
                            retries=retries_completed,
                            oscillation_detected=False,
                            crashed=True,
                            total_concerns_raised=total_concerns_raised,
                        ),
                    )
                continue

            last_findings = findings
            total_concerns_raised += len(findings.findings)

            if is_converged(findings):
                await self._emit_stage_converged(
                    retries=attempt,
                    concerns_raised=total_concerns_raised,
                    concerns_forwarded=0,
                )
                return (
                    ctx,
                    [],
                    RunMetrics(
                        retries=retries_completed,
                        oscillation_detected=False,
                        crashed=False,
                        total_concerns_raised=total_concerns_raised,
                    ),
                )

            signature = _signature_for(findings)
            recent_signatures.append(signature)
            if (
                len(recent_signatures) >= self.oscillation_window
                and len(set(recent_signatures[-self.oscillation_window :])) == 1
            ):
                logger.info("oscillation detected after %s attempts", attempt + 1)
                unresolved = list(findings.findings)
                await self._emit_concerns_forwarded(unresolved)
                await self._emit_stage_exhausted(
                    retries=attempt,
                    concerns_forwarded=len(unresolved),
                )
                return (
                    ctx,
                    unresolved,
                    RunMetrics(
                        retries=retries_completed,
                        oscillation_detected=True,
                        crashed=False,
                        total_concerns_raised=total_concerns_raised,
                    ),
                )

            if attempt == self.budget:
                break

            ctx = await retry(findings, ctx)
            retries_completed += 1

        unresolved = list(last_findings.findings) if last_findings else []
        await self._emit_concerns_forwarded(unresolved)
        await self._emit_stage_exhausted(
            retries=self.budget,
            concerns_forwarded=len(unresolved),
        )
        return (
            ctx,
            unresolved,
            RunMetrics(
                retries=retries_completed,
                oscillation_detected=False,
                crashed=False,
                total_concerns_raised=total_concerns_raised,
            ),
        )

    # -- EventBus emission helpers (all no-op when wiring is incomplete) --

    def _emission_ready(self) -> bool:
        return (
            self._event_bus is not None
            and self._issue_id is not None
            and self._phase is not None
            and self._stage is not None
        )

    async def _emit_stage_started(self, *, retry_count: int) -> None:
        if not self._emission_ready():
            return
        # Deferred import — avoids a hard dependency cycle for callers
        # that import the loop without an EventBus.
        from events import EventType, HydraFlowEvent  # noqa: PLC0415

        assert self._event_bus is not None  # for type-checker  # noqa: S101
        await self._event_bus.publish(
            HydraFlowEvent(
                type=EventType.ADVERSARIAL_STAGE_STARTED,
                data={
                    "issue_id": self._issue_id,
                    "phase": self._phase,
                    "stage": self._stage,
                    "retry_count": retry_count,
                },
            )
        )

    async def _emit_stage_converged(
        self,
        *,
        retries: int,
        concerns_raised: int,
        concerns_forwarded: int,
    ) -> None:
        if not self._emission_ready():
            return
        from events import EventType, HydraFlowEvent  # noqa: PLC0415

        assert self._event_bus is not None  # noqa: S101
        await self._event_bus.publish(
            HydraFlowEvent(
                type=EventType.ADVERSARIAL_STAGE_CONVERGED,
                data={
                    "issue_id": self._issue_id,
                    "phase": self._phase,
                    "stage": self._stage,
                    "retries": retries,
                    "concerns_raised": concerns_raised,
                    "concerns_forwarded": concerns_forwarded,
                },
            )
        )

    async def _emit_stage_exhausted(
        self,
        *,
        retries: int,
        concerns_forwarded: int,
    ) -> None:
        if not self._emission_ready():
            return
        from events import EventType, HydraFlowEvent  # noqa: PLC0415

        assert self._event_bus is not None  # noqa: S101
        await self._event_bus.publish(
            HydraFlowEvent(
                type=EventType.ADVERSARIAL_STAGE_EXHAUSTED,
                data={
                    "issue_id": self._issue_id,
                    "phase": self._phase,
                    "stage": self._stage,
                    "retries": retries,
                    "concerns_forwarded": concerns_forwarded,
                },
            )
        )

    async def _emit_concerns_forwarded(self, concerns: list[Concern]) -> None:
        if not self._emission_ready() or not concerns:
            return
        from events import EventType, HydraFlowEvent  # noqa: PLC0415

        assert self._event_bus is not None  # noqa: S101
        for concern in concerns:
            await self._event_bus.publish(
                HydraFlowEvent(
                    type=EventType.CONCERN_FORWARDED,
                    data={
                        "issue_id": self._issue_id,
                        "concern_id": concern.id,
                        "from_stage": self._stage,
                        # Downstream destination is whoever picks the
                        # concern up — encode the contract from the
                        # concern itself rather than guessing.
                        "to_stage": concern.must_address_by,
                        "severity": concern.severity,
                    },
                )
            )


def _signature_for(findings: HasFindings) -> str:
    """Stable signature of CRITICAL/HIGH concerns for oscillation detection."""
    items = sorted(
        f.concern for f in findings.findings if f.severity in {"CRITICAL", "HIGH"}
    )
    return "|".join(items)


def _synthetic_crash_concern(exc: Exception) -> Concern:
    return Concern(
        id=f"CRASH-{datetime.now(UTC).isoformat()}",
        raised_in_phase="plan",
        raised_in_stage="adversarial_retry_loop",
        severity="HIGH",
        concern=f"critic crashed 3x consecutively: {type(exc).__name__}: {exc}",
        raised_at=datetime.now(UTC),
        must_address_by="next",
    )
