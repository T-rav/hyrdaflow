"""PreflightDecision tests (spec §2.2, §2.3, §7)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from preflight.decision import PreflightResult, apply_decision


def _result(status: str, **kwargs) -> PreflightResult:
    return PreflightResult(
        status=status,
        pr_url=kwargs.get("pr_url"),
        diagnosis=kwargs.get("diagnosis", "diag"),
        cost_usd=kwargs.get("cost_usd", 1.0),
        wall_clock_s=kwargs.get("wall_clock_s", 60.0),
        tokens=kwargs.get("tokens", 1000),
    )


@pytest.mark.asyncio
async def test_resolved_removes_hitl_escalation() -> None:
    pr = AsyncMock()
    state = MagicMock()
    state.get_auto_agent_attempts = MagicMock(return_value=1)
    out = await apply_decision(
        issue_number=42,
        sub_label="flaky-test-stuck",
        result=_result("resolved", pr_url="https://x/pr/1"),
        pr_port=pr,
        state=state,
        max_attempts=3,
    )
    pr.remove_labels.assert_awaited_with(42, ["hitl-escalation"])
    pr.add_comment.assert_awaited()
    assert out["status"] == "resolved"


@pytest.mark.asyncio
async def test_needs_human_adds_label() -> None:
    pr = AsyncMock()
    state = MagicMock()
    state.get_auto_agent_attempts = MagicMock(return_value=1)
    await apply_decision(
        issue_number=42,
        sub_label="flaky-test-stuck",
        result=_result("needs_human"),
        pr_port=pr,
        state=state,
        max_attempts=3,
    )
    pr.add_labels.assert_awaited_with(42, ["human-required"])


@pytest.mark.asyncio
async def test_fatal_adds_paired_label() -> None:
    pr = AsyncMock()
    state = MagicMock()
    state.get_auto_agent_attempts = MagicMock(return_value=1)
    await apply_decision(
        issue_number=42,
        sub_label="x",
        result=_result("fatal"),
        pr_port=pr,
        state=state,
        max_attempts=3,
    )
    pr.add_labels.assert_awaited_with(42, ["human-required", "auto-agent-fatal"])


@pytest.mark.asyncio
async def test_exhaustion_appends_label() -> None:
    pr = AsyncMock()
    state = MagicMock()
    state.get_auto_agent_attempts = MagicMock(return_value=3)
    out = await apply_decision(
        issue_number=42,
        sub_label="x",
        result=_result("needs_human"),
        pr_port=pr,
        state=state,
        max_attempts=3,
    )
    assert "auto-agent-exhausted" in out["added"]
    pr.add_labels.assert_awaited_with(42, ["human-required", "auto-agent-exhausted"])


@pytest.mark.asyncio
async def test_resolved_at_cap_does_not_mark_exhausted() -> None:
    pr = AsyncMock()
    state = MagicMock()
    state.get_auto_agent_attempts = MagicMock(return_value=3)
    out = await apply_decision(
        issue_number=42,
        sub_label="x",
        result=_result("resolved"),
        pr_port=pr,
        state=state,
        max_attempts=3,
    )
    assert "auto-agent-exhausted" not in out["added"]


@pytest.mark.asyncio
async def test_cost_exceeded_pairs_correctly() -> None:
    pr = AsyncMock()
    state = MagicMock()
    state.get_auto_agent_attempts = MagicMock(return_value=1)
    await apply_decision(
        issue_number=42,
        sub_label="x",
        result=_result("cost_exceeded"),
        pr_port=pr,
        state=state,
        max_attempts=3,
    )
    pr.add_labels.assert_awaited_with(42, ["human-required", "cost-exceeded"])
