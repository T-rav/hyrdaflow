"""Scenario tests: per-sub-label playbook routing (ADR-0063 W1).

For each W1 specialist sub-label, an end-to-end `_do_work` tick must:
  1. select the matching playbook (asserted via the prompt that reaches spawn),
  2. substitute the playbook's specialist persona (not the deps default),
  3. render the playbook's prompt template (not _default.md).

These are MockWorld-style scenario tests — the spawn function is stubbed but
every other layer (loop, context-gather, decision, audit) runs for real.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from auto_agent_preflight_loop import AutoAgentPreflightLoop
from preflight.agent import PreflightSpawn
from preflight.playbooks import DEFAULT_PERSONA, get_playbook
from tests.helpers import make_bg_loop_deps


def _make_loop(tmp_path: Path, **overrides):
    deps = make_bg_loop_deps(tmp_path, **overrides)
    state = MagicMock()
    state.get_auto_agent_attempts = MagicMock(return_value=0)
    state.bump_auto_agent_attempts = MagicMock(return_value=1)
    state.clear_auto_agent_attempts = MagicMock()
    state.get_auto_agent_daily_spend = MagicMock(return_value=0.0)
    state.add_auto_agent_daily_spend = MagicMock(return_value=0.0)
    state.get_escalation_context = MagicMock(return_value=None)
    pr = AsyncMock()
    pr.list_closed_issues_by_label = AsyncMock(return_value=[])
    audit = MagicMock()
    audit.append = MagicMock()
    audit.entries_for_issue = MagicMock(return_value=[])
    loop = AutoAgentPreflightLoop(
        config=deps.config,
        state=state,
        pr_manager=pr,
        wiki_store=None,
        audit_store=audit,
        deps=deps.loop_deps,
    )
    return loop, state, pr, audit


def _capture_spawn(loop) -> list[str]:
    """Replace `_build_spawn_fn` so the rendered prompt is captured.

    Returns a list the test inspects after `_do_work` completes.
    """
    captured: list[str] = []

    async def _spawn(prompt: str, worktree_path: str) -> PreflightSpawn:
        captured.append(prompt)
        return PreflightSpawn(
            process=None,
            output_text="<status>needs_human</status><diagnosis>x</diagnosis>",
            cost_usd=0.0,
            tokens=0,
            crashed=False,
        )

    loop._build_spawn_fn = lambda issue: _spawn
    return captured


def _issue(sub_label: str, number: int = 1) -> dict:
    return {
        "number": number,
        "body": "x",
        "labels": [
            {"name": "hitl-escalation"},
            {"name": sub_label},
        ],
    }


# Each tuple: (sub_label, expected persona-marker substring, expected prompt-file
# header substring). The persona marker is a substring of the playbook persona
# that won't appear in the generic envelope/default copy; the header substring
# proves render_prompt picked the playbook's prompt_template.
_W1_ROUTING_CASES = [
    ("plan-stuck", "planning specialist", "plan-stuck Playbook"),
    ("implement-stuck", "implementation specialist", "implement-stuck Playbook"),
    ("review-stuck", "review-recovery specialist", "review-stuck Playbook"),
    ("triage-stuck", "triage specialist", "triage-stuck Playbook"),
    (
        "discover-stuck",
        "discovery / research specialist",
        "discover-stuck Playbook",
    ),
]


@pytest.mark.parametrize(
    ("sub_label", "persona_marker", "prompt_header"), _W1_ROUTING_CASES
)
@pytest.mark.asyncio
async def test_specialist_playbook_fires_for_sublabel(
    tmp_path: Path,
    sub_label: str,
    persona_marker: str,
    prompt_header: str,
) -> None:
    loop, _state, pr, _audit = _make_loop(tmp_path)
    pr.list_issues_by_label = AsyncMock(return_value=[_issue(sub_label)])
    prompts = _capture_spawn(loop)

    await loop._do_work()

    assert len(prompts) == 1, f"expected exactly one spawn for {sub_label}"
    prompt = prompts[0]
    assert persona_marker in prompt, (
        f"{sub_label}: specialist persona '{persona_marker}' missing from "
        f"rendered prompt — playbook routing did not fire"
    )
    assert prompt_header in prompt, (
        f"{sub_label}: prompt header '{prompt_header}' missing — "
        f"render_prompt picked the wrong template"
    )


@pytest.mark.asyncio
async def test_unspecialised_sublabel_uses_default_persona(tmp_path: Path) -> None:
    """A sub-label with no W1 specialist (e.g. `flaky-test-stuck`, which ships
    its own prompt file but no specialist persona) still uses the operator-
    configured `auto_agent_persona` from config — backwards-compat."""
    loop, _state, pr, _audit = _make_loop(
        tmp_path, auto_agent_persona="CUSTOM_OPERATOR_PERSONA"
    )
    pr.list_issues_by_label = AsyncMock(return_value=[_issue("flaky-test-stuck")])
    prompts = _capture_spawn(loop)

    await loop._do_work()

    assert len(prompts) == 1
    prompt = prompts[0]
    assert "CUSTOM_OPERATOR_PERSONA" in prompt
    # And the flaky-test-stuck prompt file is still rendered (not _default.md).
    assert "flaky-test-stuck Playbook" in prompt


@pytest.mark.asyncio
async def test_unknown_sublabel_falls_back_to_default_prompt(tmp_path: Path) -> None:
    """A completely unknown sub-label uses the operator persona AND the
    generic _default.md prompt (the runner's existing fallback path)."""
    loop, _state, pr, _audit = _make_loop(tmp_path, auto_agent_persona="OPERATOR_X")
    pr.list_issues_by_label = AsyncMock(return_value=[_issue("totally-novel-stuck")])
    prompts = _capture_spawn(loop)

    await loop._do_work()

    prompt = prompts[0]
    assert "OPERATOR_X" in prompt
    assert "Default Playbook" in prompt


def test_w1_routing_table_matches_registry() -> None:
    """Guard: the parametrised W1 routing table must cover every specialist
    in the registry (and no others). Catches drift between the registry
    and these scenario tests when W2-W5 add specialists without test
    updates."""
    from preflight.playbooks import iter_playbooks

    table_names = {sub for sub, _, _ in _W1_ROUTING_CASES}
    registry_names = {pb.name for pb in iter_playbooks()}
    assert table_names == registry_names, (
        f"W1 routing-table specialists {table_names} do not match registry "
        f"specialists {registry_names}. Update _W1_ROUTING_CASES (or the "
        f"registry) to match."
    )


def test_w1_persona_assertions_come_from_registry() -> None:
    """Guard: each row's `persona_marker` must be present in the playbook's
    actual persona string — protects against typos drifting between this
    parametrise table and the registry definitions."""
    for sub_label, persona_marker, _ in _W1_ROUTING_CASES:
        pb = get_playbook(sub_label)
        assert pb.persona != DEFAULT_PERSONA, (
            f"{sub_label} is not in the specialist registry"
        )
        assert persona_marker.lower() in pb.persona.lower(), (
            f"{sub_label} routing table expects persona marker "
            f"'{persona_marker}' which is missing from the playbook persona "
            f"in src/preflight/playbooks/__init__.py"
        )
