"""SandboxFailureFixerLoop unit tests.

Scaffold-generated smoke tests verify worker_name, default interval, and the
two ADR-0049 kill-switch gates. The behavioral tests below cover the body of
``_do_work``: polling labeled PRs, dispatching the auto-agent, attempt
counting in ``StateData.sandbox_failure_fixer_attempts``, the no-auto-fix
opt-out, and the cap-hit label-swap to ``sandbox-hitl``.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from sandbox_failure_fixer_loop import SandboxFailureFixerLoop
from tests.helpers import make_bg_loop_deps


def _make_loop(
    tmp_path: Path,
    *,
    enabled: bool = True,
    prs: object | None = None,
    runner: object | None = None,
    state: object | None = None,
    **config_overrides,
):
    # Default to static-config-enabled here so each behavioral test exercises
    # the body. The static-config-disable test overrides this kwarg.
    config_overrides.setdefault("sandbox_failure_fixer_enabled", True)
    deps = make_bg_loop_deps(tmp_path, enabled=enabled, **config_overrides)
    state = state if state is not None else MagicMock()
    loop = SandboxFailureFixerLoop(
        config=deps.config,
        state=state,
        prs=prs,
        runner=runner,
        deps=deps.loop_deps,
    )
    return loop, state


def _make_state_with_attempts(
    attempts: dict[str, int] | None = None,
) -> MagicMock:
    """Create a state mock that mirrors SandboxFailureFixerStateMixin.

    ``get_*`` returns the int, ``bump_*`` post-increments and returns the new
    value, and ``swap_*_label`` is a no-op. Tests then assert on call args.
    """
    state = MagicMock()
    counts = dict(attempts or {})

    def _get(pr_number: int) -> int:
        return int(counts.get(str(pr_number), 0))

    def _bump(pr_number: int) -> int:
        new = _get(pr_number) + 1
        counts[str(pr_number)] = new
        return new

    state.get_sandbox_failure_fixer_attempts.side_effect = _get
    state.bump_sandbox_failure_fixer_attempts.side_effect = _bump
    state._counts = counts  # exposed for assertions
    return state


def test_worker_name(tmp_path: Path) -> None:
    loop, _ = _make_loop(tmp_path)
    assert loop._worker_name == "sandbox_failure_fixer"


def test_default_interval_from_config(tmp_path: Path) -> None:
    loop, _ = _make_loop(tmp_path, sandbox_failure_fixer_interval=180)
    assert loop._get_default_interval() == 180


@pytest.mark.asyncio
async def test_kill_switch_short_circuits(tmp_path: Path) -> None:
    loop, _ = _make_loop(tmp_path, enabled=False)
    result = await loop._do_work()
    assert result == {"status": "disabled"}


@pytest.mark.asyncio
async def test_static_config_disable_short_circuits(tmp_path: Path) -> None:
    """Static-config gate (``HYDRAFLOW_SANDBOX_FAILURE_FIXER_ENABLED=false``)
    short-circuits before any port call. The loop ships kill-switched-off:
    operators flip the env var to True after observing a real fix-cycle.
    """
    loop, _ = _make_loop(tmp_path, enabled=True, sandbox_failure_fixer_enabled=False)
    result = await loop._do_work()
    assert result == {"status": "config_disabled"}


@pytest.mark.asyncio
async def test_do_work_skips_when_no_labeled_prs(tmp_path: Path) -> None:
    pr_port = MagicMock()
    pr_port.list_prs_by_label = AsyncMock(return_value=[])
    runner = MagicMock()
    runner.run = AsyncMock()
    state = _make_state_with_attempts()

    loop, _ = _make_loop(tmp_path, prs=pr_port, runner=runner, state=state)
    result = await loop._do_work()

    assert result["status"] == "ok"
    assert result["dispatched"] == 0
    assert result["escalated"] == 0
    runner.run.assert_not_called()


@pytest.mark.asyncio
async def test_do_work_dispatches_auto_agent_for_labeled_pr(
    tmp_path: Path,
) -> None:
    pr_port = MagicMock()
    pr_port.list_prs_by_label = AsyncMock(
        return_value=[
            SimpleNamespace(number=100, branch="rc/2026-04-26", labels=[]),
        ]
    )
    pr_port.add_pr_labels = AsyncMock()
    pr_port.remove_pr_label = AsyncMock()
    runner = MagicMock()
    runner.run = AsyncMock(
        return_value=SimpleNamespace(crashed=False, output_text="OK")
    )
    state = _make_state_with_attempts()

    loop, _ = _make_loop(tmp_path, prs=pr_port, runner=runner, state=state)
    result = await loop._do_work()

    runner.run.assert_called_once()
    assert state._counts == {"100": 1}
    assert result["dispatched"] == 1
    assert result["escalated"] == 0


@pytest.mark.asyncio
async def test_do_work_swaps_label_after_max_attempts(tmp_path: Path) -> None:
    pr_port = MagicMock()
    pr_port.list_prs_by_label = AsyncMock(
        return_value=[
            SimpleNamespace(number=100, branch="rc/2026-04-26", labels=[]),
        ]
    )
    pr_port.add_pr_labels = AsyncMock()
    pr_port.remove_pr_label = AsyncMock()
    runner = MagicMock()
    runner.run = AsyncMock()
    # already at the cap → loop should escalate, not dispatch
    state = _make_state_with_attempts({"100": 3})

    loop, _ = _make_loop(tmp_path, prs=pr_port, runner=runner, state=state)
    result = await loop._do_work()

    runner.run.assert_not_called()
    pr_port.remove_pr_label.assert_awaited_with(100, "sandbox-fail-auto-fix")
    pr_port.add_pr_labels.assert_awaited_with(100, ["sandbox-hitl"])
    assert result["escalated"] == 1
    assert result["dispatched"] == 0


@pytest.mark.asyncio
async def test_do_work_skips_no_auto_fix_label(tmp_path: Path) -> None:
    pr_port = MagicMock()
    pr_port.list_prs_by_label = AsyncMock(
        return_value=[
            SimpleNamespace(number=100, branch="rc/2026-04-26", labels=["no-auto-fix"]),
        ]
    )
    pr_port.add_pr_labels = AsyncMock()
    pr_port.remove_pr_label = AsyncMock()
    runner = MagicMock()
    runner.run = AsyncMock()
    state = _make_state_with_attempts()

    loop, _ = _make_loop(tmp_path, prs=pr_port, runner=runner, state=state)
    result = await loop._do_work()

    runner.run.assert_not_called()
    assert state._counts == {}
    assert result["skipped_opt_out"] == 1


@pytest.mark.asyncio
async def test_do_work_handles_crashed_runner(tmp_path: Path) -> None:
    """A crashed auto-agent run still bumps attempts (counts toward cap)."""
    pr_port = MagicMock()
    pr_port.list_prs_by_label = AsyncMock(
        return_value=[
            SimpleNamespace(number=200, branch="rc/2026-04-26", labels=[]),
        ]
    )
    pr_port.add_pr_labels = AsyncMock()
    pr_port.remove_pr_label = AsyncMock()
    runner = MagicMock()
    runner.run = AsyncMock(
        return_value=SimpleNamespace(crashed=True, output_text="boom")
    )
    state = _make_state_with_attempts()

    loop, _ = _make_loop(tmp_path, prs=pr_port, runner=runner, state=state)
    result = await loop._do_work()

    assert state._counts == {"200": 1}
    assert result["dispatched"] == 0
    assert result["crashed"] == 1


# ---------------------------------------------------------------------------
# ADR-0063 W3c — richer context injection tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_prompt_includes_ci_failure_log(tmp_path: Path) -> None:
    """The rendered prompt must contain the CI failure log from PRPort."""
    pr_port = MagicMock()
    pr_port.list_prs_by_label = AsyncMock(
        return_value=[
            SimpleNamespace(number=42, branch="rc/2026-05-01", labels=[]),
        ]
    )
    pr_port.add_pr_labels = AsyncMock()
    pr_port.remove_pr_label = AsyncMock()
    pr_port.fetch_ci_failure_logs = AsyncMock(
        return_value="FAILED: test_my_scenario :: AssertionError: expected True, got False"
    )
    pr_port.get_pr_recent_commit_diffs = AsyncMock(return_value="")
    runner = MagicMock()
    runner.run = AsyncMock(
        return_value=SimpleNamespace(crashed=False, output_text="ok")
    )
    state = _make_state_with_attempts()

    loop, _ = _make_loop(tmp_path, prs=pr_port, runner=runner, state=state)
    await loop._do_work()

    call_kwargs = runner.run.call_args
    prompt_used: str = (
        call_kwargs.kwargs.get("prompt") or call_kwargs.args[0]
        if call_kwargs.args
        else call_kwargs.kwargs["prompt"]
    )
    assert "AssertionError: expected True, got False" in prompt_used
    assert "{CI_FAILURE_LOG}" not in prompt_used


@pytest.mark.asyncio
async def test_build_prompt_includes_recent_commit_diffs(tmp_path: Path) -> None:
    """The rendered prompt must contain the recent commit diffs from PRPort."""
    pr_port = MagicMock()
    pr_port.list_prs_by_label = AsyncMock(
        return_value=[
            SimpleNamespace(number=42, branch="rc/2026-05-01", labels=[]),
        ]
    )
    pr_port.add_pr_labels = AsyncMock()
    pr_port.remove_pr_label = AsyncMock()
    pr_port.fetch_ci_failure_logs = AsyncMock(return_value="")
    pr_port.get_pr_recent_commit_diffs = AsyncMock(
        return_value=(
            "## aabbccdd add scenario seed\n"
            "diff --git a/tests/scenarios/test_x.py b/tests/scenarios/test_x.py\n"
            "+    assert result == 'ok'"
        )
    )
    runner = MagicMock()
    runner.run = AsyncMock(
        return_value=SimpleNamespace(crashed=False, output_text="ok")
    )
    state = _make_state_with_attempts()

    loop, _ = _make_loop(tmp_path, prs=pr_port, runner=runner, state=state)
    await loop._do_work()

    call_kwargs = runner.run.call_args
    prompt_used: str = (
        call_kwargs.kwargs.get("prompt") or call_kwargs.args[0]
        if call_kwargs.args
        else call_kwargs.kwargs["prompt"]
    )
    assert "aabbccdd add scenario seed" in prompt_used
    assert "{RECENT_COMMIT_DIFFS}" not in prompt_used


@pytest.mark.asyncio
async def test_build_prompt_degrades_gracefully_on_fetch_error(
    tmp_path: Path,
) -> None:
    """If either context fetch raises, the prompt still renders with placeholder text."""
    pr_port = MagicMock()
    pr_port.list_prs_by_label = AsyncMock(
        return_value=[
            SimpleNamespace(number=42, branch="rc/2026-05-01", labels=[]),
        ]
    )
    pr_port.add_pr_labels = AsyncMock()
    pr_port.remove_pr_label = AsyncMock()
    pr_port.fetch_ci_failure_logs = AsyncMock(side_effect=RuntimeError("network error"))
    pr_port.get_pr_recent_commit_diffs = AsyncMock(side_effect=RuntimeError("timeout"))
    runner = MagicMock()
    runner.run = AsyncMock(
        return_value=SimpleNamespace(crashed=False, output_text="ok")
    )
    state = _make_state_with_attempts()

    loop, _ = _make_loop(tmp_path, prs=pr_port, runner=runner, state=state)
    result = await loop._do_work()

    # Loop must still dispatch despite fetch failures.
    assert result["dispatched"] == 1

    call_kwargs = runner.run.call_args
    prompt_used: str = (
        call_kwargs.kwargs.get("prompt") or call_kwargs.args[0]
        if call_kwargs.args
        else call_kwargs.kwargs["prompt"]
    )
    assert "(no CI failure log available)" in prompt_used
    assert "(no recent commit diffs available)" in prompt_used
    # Template placeholders must not leak into the prompt.
    assert "{CI_FAILURE_LOG}" not in prompt_used
    assert "{RECENT_COMMIT_DIFFS}" not in prompt_used
