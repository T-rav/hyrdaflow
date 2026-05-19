"""PreflightAgent tests (spec §3.3, §5.1)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from preflight.agent import (
    PreflightAgentDeps,
    PreflightSpawn,
    hash_prompt,
    run_preflight,
)
from preflight.context import PreflightContext


def _ctx(sub_label: str = "flaky-test-stuck") -> PreflightContext:
    return PreflightContext(
        issue_number=42,
        issue_body="body",
        issue_comments=[],
        sub_label=sub_label,
        escalation_context=None,
        wiki_excerpts="",
        sentry_events=[],
        recent_commits=[],
    )


@pytest.mark.asyncio
async def test_resolved_response_parsed() -> None:
    spawn_fn = AsyncMock(
        return_value=PreflightSpawn(
            process=None,
            output_text="<status>resolved</status>\n<pr_url>https://x/pr/1</pr_url>\n<diagnosis>fixed it</diagnosis>",
            cost_usd=1.0,
            tokens=1000,
            crashed=False,
        )
    )
    deps = PreflightAgentDeps(
        persona="x",
        cost_cap_usd=None,
        wall_clock_cap_s=None,
        spawn_fn=spawn_fn,
    )
    out = await run_preflight(
        context=_ctx(), repo_slug="x/y", worktree_path="/tmp", deps=deps
    )
    assert out.status == "resolved"
    assert out.pr_url == "https://x/pr/1"
    assert out.diagnosis == "fixed it"


@pytest.mark.asyncio
async def test_subprocess_crash_returns_fatal() -> None:
    spawn_fn = AsyncMock(
        return_value=PreflightSpawn(
            process=None,
            output_text="partial output",
            cost_usd=0.5,
            tokens=500,
            crashed=True,
        )
    )
    deps = PreflightAgentDeps(
        persona="x",
        cost_cap_usd=None,
        wall_clock_cap_s=None,
        spawn_fn=spawn_fn,
    )
    out = await run_preflight(
        context=_ctx(), repo_slug="x/y", worktree_path="/tmp", deps=deps
    )
    assert out.status == "fatal"
    assert "Subprocess crashed" in out.diagnosis


@pytest.mark.asyncio
async def test_spawn_exception_returns_fatal() -> None:
    spawn_fn = AsyncMock(side_effect=RuntimeError("oom"))
    deps = PreflightAgentDeps(
        persona="x",
        cost_cap_usd=None,
        wall_clock_cap_s=None,
        spawn_fn=spawn_fn,
    )
    out = await run_preflight(
        context=_ctx(), repo_slug="x/y", worktree_path="/tmp", deps=deps
    )
    assert out.status == "fatal"
    assert "spawn failed" in out.diagnosis


@pytest.mark.asyncio
async def test_cost_cap_returns_cost_exceeded() -> None:
    spawn_fn = AsyncMock(
        return_value=PreflightSpawn(
            process=None,
            output_text="<status>resolved</status><diagnosis>x</diagnosis>",
            cost_usd=10.0,
            tokens=10000,
            crashed=False,
        )
    )
    deps = PreflightAgentDeps(
        persona="x",
        cost_cap_usd=5.0,
        wall_clock_cap_s=None,
        spawn_fn=spawn_fn,
    )
    out = await run_preflight(
        context=_ctx(), repo_slug="x/y", worktree_path="/tmp", deps=deps
    )
    assert out.status == "cost_exceeded"


@pytest.mark.asyncio
async def test_wall_clock_cap_returns_timeout() -> None:
    """Spec §5.1: wall-clock cap fires when subprocess wall time exceeds the cap."""
    import asyncio

    async def slow_spawn(*, prompt: str, worktree_path: str) -> PreflightSpawn:
        await asyncio.sleep(0.05)  # exceed the 0.01s cap below
        return PreflightSpawn(
            process=None,
            output_text="<status>resolved</status><diagnosis>x</diagnosis>",
            cost_usd=1.0,
            tokens=1000,
            crashed=False,
        )

    deps = PreflightAgentDeps(
        persona="x",
        cost_cap_usd=None,
        wall_clock_cap_s=0,  # any nonzero wall time exceeds 0
        spawn_fn=slow_spawn,
    )
    out = await run_preflight(
        context=_ctx(),
        repo_slug="x/y",
        worktree_path="/tmp",
        deps=deps,
    )
    assert out.status == "timeout"
    assert "Wall-clock cap" in out.diagnosis


def test_hash_prompt_stable() -> None:
    assert hash_prompt("abc") == hash_prompt("abc")
    assert hash_prompt("abc") != hash_prompt("def")
    assert hash_prompt("abc").startswith("sha256:")


@pytest.mark.asyncio
async def test_playbook_persona_overrides_deps_persona() -> None:
    """ADR-0063 W1: when the sub-label resolves to a specialist playbook,
    the playbook's persona is substituted into the prompt — not the generic
    ``deps.persona``. The deps persona remains the default for unspecialised
    sub-labels (backwards-compat)."""
    captured_prompts: list[str] = []

    async def _spawn(*, prompt: str, worktree_path: str) -> PreflightSpawn:
        captured_prompts.append(prompt)
        return PreflightSpawn(
            process=None,
            output_text="<status>needs_human</status><diagnosis>x</diagnosis>",
            cost_usd=0.0,
            tokens=0,
            crashed=False,
        )

    deps = PreflightAgentDeps(
        persona="GENERIC_DEFAULT",
        cost_cap_usd=None,
        wall_clock_cap_s=None,
        spawn_fn=_spawn,
    )
    # plan-stuck is a specialist sub-label in the W1 registry.
    await run_preflight(
        context=_ctx(sub_label="plan-stuck"),
        repo_slug="x/y",
        worktree_path="/tmp",
        deps=deps,
    )
    assert len(captured_prompts) == 1
    prompt = captured_prompts[0]
    # The specialist persona for plan-stuck mentions "planning specialist"
    # and uses the plan-stuck prompt file.
    assert "planning specialist" in prompt
    assert "GENERIC_DEFAULT" not in prompt
    assert "plan-stuck Playbook" in prompt


@pytest.mark.asyncio
async def test_unspecialised_sublabel_uses_deps_persona() -> None:
    """Backwards-compat: a sub-label not in the W1 registry still receives the
    operator-configured ``deps.persona`` (generic lead-engineer)."""
    captured_prompts: list[str] = []

    async def _spawn(*, prompt: str, worktree_path: str) -> PreflightSpawn:
        captured_prompts.append(prompt)
        return PreflightSpawn(
            process=None,
            output_text="<status>needs_human</status><diagnosis>x</diagnosis>",
            cost_usd=0.0,
            tokens=0,
            crashed=False,
        )

    deps = PreflightAgentDeps(
        persona="OPERATOR_CONFIGURED",
        cost_cap_usd=None,
        wall_clock_cap_s=None,
        spawn_fn=_spawn,
    )
    # flaky-test-stuck has a prompt file but no specialist persona — should
    # still use the deps.persona verbatim.
    await run_preflight(
        context=_ctx(sub_label="flaky-test-stuck"),
        repo_slug="x/y",
        worktree_path="/tmp",
        deps=deps,
    )
    prompt = captured_prompts[0]
    assert "OPERATOR_CONFIGURED" in prompt


@pytest.mark.asyncio
async def test_unparseable_response_falls_back_to_needs_human() -> None:
    spawn_fn = AsyncMock(
        return_value=PreflightSpawn(
            process=None,
            output_text="garbage no tags",
            cost_usd=1.0,
            tokens=100,
            crashed=False,
        )
    )
    deps = PreflightAgentDeps(
        persona="x",
        cost_cap_usd=None,
        wall_clock_cap_s=None,
        spawn_fn=spawn_fn,
    )
    out = await run_preflight(
        context=_ctx(), repo_slug="x/y", worktree_path="/tmp", deps=deps
    )
    assert out.status == "needs_human"
