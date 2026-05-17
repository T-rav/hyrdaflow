"""Regression: ``AdversarialRetryLoop`` re-raises ``CreditExhaustedError``.

The dark-factory contract requires every subprocess-spawning runner to
propagate ``CreditExhaustedError`` so the active-issue loop can suspend
ticking instead of burning attempt budget against an exhausted billing
signal (see ``docs/wiki/dark-factory.md`` §2.2 and the related guard
``reraise_on_credit_or_bug``).

``AdversarialRetryLoop`` is a subprocess-spawning runner by transitivity
— its ``critic`` callable invokes LLM agents that run subprocesses. The
loop must therefore re-raise ``CreditExhaustedError`` rather than
swallow it into the broad ``except Exception`` crash counter.

Locking that behaviour with a regression test so a future refactor (e.g.
collapsing the two ``except`` clauses, swallowing crashes into a generic
forward) trips CI.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.adversarial_retry_loop import AdversarialRetryLoop
from src.pending_concerns import Concern
from src.subprocess_util import CreditExhaustedError


@dataclass
class _Ctx:
    text: str = "v0"


@dataclass
class _Findings:
    findings: list[Concern] = field(default_factory=list)


@pytest.mark.asyncio
async def test_credit_exhausted_propagates_on_first_attempt() -> None:
    """CreditExhaustedError on first critic call escapes the loop."""

    async def critic(ctx):
        raise CreditExhaustedError("anthropic billing")

    async def retry(findings, ctx):
        return ctx

    loop = AdversarialRetryLoop(budget=3)
    with pytest.raises(CreditExhaustedError, match="anthropic billing"):
        await loop.run(_Ctx(), critic, retry, is_converged=lambda f: False)


@pytest.mark.asyncio
async def test_credit_exhausted_propagates_via_run_with_metrics() -> None:
    """The richer metrics entry point also re-raises (no silent swallow)."""

    async def critic(ctx):
        raise CreditExhaustedError("credits gone")

    async def retry(findings, ctx):
        return ctx

    loop = AdversarialRetryLoop(budget=3)
    with pytest.raises(CreditExhaustedError, match="credits gone"):
        await loop.run_with_metrics(
            _Ctx(), critic, retry, is_converged=lambda f: False
        )


@pytest.mark.asyncio
async def test_credit_exhausted_not_counted_as_crash() -> None:
    """A single CreditExhaustedError must not roll into the 3-crash counter.

    If the broad ``except Exception`` swallowed it, three consecutive
    runs would hit the synthetic-crash-concern path. The contract is
    instead: raise on the first occurrence, let the active-issue loop
    handle suspension upstream.
    """
    attempts = {"n": 0}

    async def critic(ctx):
        attempts["n"] += 1
        raise CreditExhaustedError("billing")

    async def retry(findings, ctx):
        return ctx

    loop = AdversarialRetryLoop(budget=3)
    with pytest.raises(CreditExhaustedError):
        await loop.run(_Ctx(), critic, retry, is_converged=lambda f: False)
    # Critic invoked exactly once before the exception propagated.
    assert attempts["n"] == 1
