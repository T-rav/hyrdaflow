from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Generic, Protocol, TypeVar

from src.pending_concerns import Concern
from src.subprocess_util import CreditExhaustedError

logger = logging.getLogger(__name__)

Ctx = TypeVar("Ctx")


class HasFindings(Protocol):
    findings: list[Concern]


F = TypeVar("F", bound=HasFindings)


class AdversarialRetryLoop(Generic[Ctx, F]):
    """Tight-loop retry with oscillation detection and forwarding fallback.

    On budget exhaustion, returns unresolved concerns rather than blocking.
    Per dark-factory contract: never deadlock.
    """

    def __init__(self, budget: int = 3, oscillation_window: int = 2):
        self.budget = budget
        self.oscillation_window = oscillation_window

    async def run(
        self,
        initial_ctx: Ctx,
        critic: Callable[[Ctx], Awaitable[F]],
        retry: Callable[[F, Ctx], Awaitable[Ctx]],
        is_converged: Callable[[F], bool],
    ) -> tuple[Ctx, list[Concern]]:
        ctx = initial_ctx
        recent_signatures: list[str] = []
        consecutive_crashes = 0
        last_findings: F | None = None

        for attempt in range(self.budget + 1):
            try:
                findings = await critic(ctx)
                consecutive_crashes = 0
            except CreditExhaustedError:
                raise
            except Exception as exc:
                logger.warning("critic crashed on attempt %s: %s", attempt, exc)
                consecutive_crashes += 1
                if consecutive_crashes >= 3:
                    return ctx, [_synthetic_crash_concern(exc)]
                continue

            last_findings = findings

            if is_converged(findings):
                return ctx, []

            signature = _signature_for(findings)
            recent_signatures.append(signature)
            if (
                len(recent_signatures) >= self.oscillation_window
                and len(set(recent_signatures[-self.oscillation_window :])) == 1
            ):
                logger.info("oscillation detected after %s attempts", attempt + 1)
                return ctx, list(findings.findings)

            if attempt == self.budget:
                break

            ctx = await retry(findings, ctx)

        return ctx, list(last_findings.findings) if last_findings else []


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
