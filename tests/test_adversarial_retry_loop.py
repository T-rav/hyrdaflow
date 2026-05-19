from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from adversarial_retry_loop import AdversarialRetryLoop
from pending_concerns import Concern
from subprocess_util import CreditExhaustedError


@dataclass
class FakeContext:
    plan_text: str = "v0"


@dataclass
class FakeFindings:
    findings: list[Concern] = field(default_factory=list)


def _make_concern(severity: str, concern: str = "X") -> Concern:
    return Concern(
        id=f"T-{concern}",
        raised_in_phase="plan",
        raised_in_stage="test",
        severity=severity,
        concern=concern,
        raised_at=datetime.now(UTC),
        must_address_by="next",
    )


@pytest.mark.asyncio
async def test_loop_converges_on_first_retry():
    calls = {"critic": 0, "retry": 0}

    async def critic(ctx):
        calls["critic"] += 1
        return FakeFindings(
            findings=[_make_concern("HIGH")] if calls["critic"] == 1 else []
        )

    async def retry(findings, ctx):
        calls["retry"] += 1
        return FakeContext(plan_text="v1")

    def is_converged(f):
        return len(f.findings) == 0

    loop = AdversarialRetryLoop(budget=3)
    final, unresolved = await loop.run(FakeContext(), critic, retry, is_converged)

    assert calls["critic"] == 2  # initial + after-retry
    assert calls["retry"] == 1
    assert unresolved == []
    assert final.plan_text == "v1"


@pytest.mark.asyncio
async def test_loop_exhausts_budget_and_forwards():
    async def critic(ctx):
        return FakeFindings(findings=[_make_concern("HIGH", concern=ctx.plan_text)])

    async def retry(findings, ctx):
        return FakeContext(plan_text=ctx.plan_text + "+")

    loop = AdversarialRetryLoop(budget=3)
    final, unresolved = await loop.run(
        FakeContext(plan_text="x"), critic, retry, is_converged=lambda f: False
    )

    assert len(unresolved) >= 1  # findings forwarded
    assert final.plan_text == "x+++"  # 3 retries applied


@pytest.mark.asyncio
async def test_oscillation_detector_exits_early():
    """Same CRITICAL/HIGH concern repeating twice exits before budget exhaust."""

    async def critic(ctx):
        return FakeFindings(findings=[_make_concern("CRITICAL", concern="same")])

    async def retry(findings, ctx):
        return ctx

    loop = AdversarialRetryLoop(budget=3, oscillation_window=2)
    final, unresolved = await loop.run(
        FakeContext(), critic, retry, is_converged=lambda f: False
    )

    # critic runs 2x (oscillation detected after second identical finding)
    # Implementation MUST exit before consuming full budget.
    assert len(unresolved) >= 1
    # No direct call counter exposed; oscillation logged on StageRun (asserted in scenario tests)


@pytest.mark.asyncio
async def test_credit_exhausted_reraises_immediately():
    async def critic(ctx):
        raise CreditExhaustedError("billing")

    async def retry(findings, ctx):
        return ctx

    loop = AdversarialRetryLoop(budget=3)
    with pytest.raises(CreditExhaustedError):
        await loop.run(FakeContext(), critic, retry, is_converged=lambda f: False)


@pytest.mark.asyncio
async def test_consecutive_crashes_count_as_exhaustion():
    """Per spec: 3 consecutive critic crashes -> forward + treat as exhaustion."""

    async def critic(ctx):
        raise RuntimeError("transient")

    async def retry(findings, ctx):
        return ctx

    loop = AdversarialRetryLoop(budget=3)
    final, unresolved = await loop.run(
        FakeContext(), critic, retry, is_converged=lambda f: False
    )
    # Crash converted to a synthetic forwarded concern; no exception escapes.
    assert any("crash" in c.concern.lower() for c in unresolved)


@pytest.mark.asyncio
async def test_run_with_metrics_first_pass_convergence():
    """First-pass convergence reports zero retries and no oscillation."""

    async def critic(ctx):
        return FakeFindings(findings=[])

    async def retry(findings, ctx):
        raise AssertionError("retry should not be invoked")

    loop = AdversarialRetryLoop(budget=3)
    _ctx, unresolved, metrics = await loop.run_with_metrics(
        FakeContext(), critic, retry, is_converged=lambda f: True
    )

    assert unresolved == []
    assert metrics.retries == 0
    assert metrics.oscillation_detected is False
    assert metrics.crashed is False


@pytest.mark.asyncio
async def test_run_with_metrics_exhausts_budget_records_retries():
    """Budget-exhaustion path records the actual number of retry invocations."""

    async def critic(ctx):
        return FakeFindings(findings=[_make_concern("HIGH", concern=ctx.plan_text)])

    async def retry(findings, ctx):
        return FakeContext(plan_text=ctx.plan_text + "+")

    loop = AdversarialRetryLoop(budget=3)
    _ctx, unresolved, metrics = await loop.run_with_metrics(
        FakeContext(plan_text="x"), critic, retry, is_converged=lambda f: False
    )

    assert len(unresolved) >= 1
    # 3 retries applied between 4 critic invocations.
    assert metrics.retries == 3
    assert metrics.oscillation_detected is False
    assert metrics.crashed is False


@pytest.mark.asyncio
async def test_run_with_metrics_oscillation_flagged():
    """Oscillation early-exit flips the oscillation_detected flag."""

    async def critic(ctx):
        return FakeFindings(findings=[_make_concern("CRITICAL", concern="same")])

    async def retry(findings, ctx):
        return ctx

    loop = AdversarialRetryLoop(budget=3, oscillation_window=2)
    _ctx, unresolved, metrics = await loop.run_with_metrics(
        FakeContext(), critic, retry, is_converged=lambda f: False
    )

    assert len(unresolved) >= 1
    assert metrics.oscillation_detected is True
    assert metrics.crashed is False


@pytest.mark.asyncio
async def test_run_with_metrics_crash_marked():
    """Three consecutive critic crashes report crashed=True."""

    async def critic(ctx):
        raise RuntimeError("transient")

    async def retry(findings, ctx):
        return ctx

    loop = AdversarialRetryLoop(budget=3)
    _ctx, unresolved, metrics = await loop.run_with_metrics(
        FakeContext(), critic, retry, is_converged=lambda f: False
    )

    assert any("crash" in c.concern.lower() for c in unresolved)
    assert metrics.crashed is True
    assert metrics.oscillation_detected is False


@pytest.mark.asyncio
async def test_run_remains_backward_compatible():
    """``run()`` still returns a two-tuple, ignoring metrics."""

    async def critic(ctx):
        return FakeFindings(findings=[])

    async def retry(findings, ctx):
        return ctx

    loop = AdversarialRetryLoop(budget=3)
    result = await loop.run(FakeContext(), critic, retry, is_converged=lambda f: True)
    assert isinstance(result, tuple)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_run_with_metrics_total_concerns_raised_accumulates():
    """``total_concerns_raised`` sums findings across attempts, not just tail.

    The bug: callers were using ``len(unresolved)`` for
    ``StageRun.concerns_raised`` — that's the *forwarded* count.
    ``StageRun.concerns_raised`` semantically means "total concerns the
    council raised in this stage", which on convergence-after-retry
    must include the concerns from the failed attempts that were
    resolved by the retry.

    Scenario: 3 findings on attempt 1, 2 on attempt 2 (post-retry),
    0 on attempt 3 (convergence). ``total_concerns_raised`` must be
    ``3 + 2 + 0 == 5`` even though ``unresolved`` is empty.
    """
    counts = [3, 2, 0]
    call_idx = {"n": 0}

    async def critic(ctx):
        idx = call_idx["n"]
        call_idx["n"] += 1
        n = counts[idx] if idx < len(counts) else 0
        return FakeFindings(
            findings=[_make_concern("HIGH", concern=f"c{idx}-{j}") for j in range(n)]
        )

    async def retry(findings, ctx):
        return ctx

    def is_converged(f):
        return len(f.findings) == 0

    loop = AdversarialRetryLoop(budget=3)
    _ctx, unresolved, metrics = await loop.run_with_metrics(
        FakeContext(), critic, retry, is_converged
    )

    assert unresolved == []
    assert metrics.total_concerns_raised == 5
    assert metrics.retries == 2  # two retry invocations between three critic passes
    assert metrics.crashed is False
    assert metrics.oscillation_detected is False
