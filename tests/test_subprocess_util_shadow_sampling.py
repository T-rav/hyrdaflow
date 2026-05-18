"""Tests for the shadow-sampling hook in subprocess_util (Phase 0.2 of #8786).

The hook is opt-in: when ``set_shadow_sampler(None)`` (the default), nothing
changes. When a sampler is installed, every ``gh``/``git``/``docker``/``claude``
call feeds it the (adapter, command, args, stdout, stderr, exit_code) tuple
after the subprocess returns — successes AND failures, because the failure
shape itself is part of the contract.

Critically: a sampler that raises must NEVER fail the subprocess call.
That's the whole point of "non-blocking observability".
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from execution import SimpleResult


class _StubRunner:
    """Minimal SubprocessRunner stub: returns a canned SimpleResult."""

    def __init__(
        self, *, stdout: str = "", stderr: str = "", returncode: int = 0
    ) -> None:
        self._stdout = stdout
        self._stderr = stderr
        self._returncode = returncode

    async def run_simple(
        self,
        cmd: Sequence[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout: float = 120.0,
        input: bytes | None = None,  # noqa: A002
    ) -> SimpleResult:
        del cmd, cwd, env, timeout, input
        return SimpleResult(
            stdout=self._stdout,
            stderr=self._stderr,
            returncode=self._returncode,
        )

    async def create_streaming_process(
        self, *_a: Any, **_k: Any
    ) -> Any:  # pragma: no cover
        raise NotImplementedError

    async def cleanup(self) -> None:  # pragma: no cover
        return None


@pytest.fixture(autouse=True)
def _reset_sampler() -> Any:
    """Ensure each test starts/ends with no sampler installed."""
    from subprocess_util import set_shadow_sampler

    set_shadow_sampler(None)
    yield
    set_shadow_sampler(None)


class _RecordingSampler:
    """Captures every sample call without persisting anything."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        *,
        adapter: str,
        command: str,
        args: list[str],
        stdout: str,
        stderr: str,
        exit_code: int,
    ) -> Path | None:
        self.calls.append(
            {
                "adapter": adapter,
                "command": command,
                "args": args,
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": exit_code,
            }
        )
        return None


@pytest.mark.asyncio
async def test_no_sampling_when_sampler_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default (no sampler installed) — run_subprocess is a no-op for shadow."""
    from subprocess_util import run_subprocess

    runner = _StubRunner(stdout="ok\n")
    result = await run_subprocess("gh", "pr", "view", "1", runner=runner)
    assert result == "ok\n"
    # The sampler is None; nothing to assert beyond "the call succeeded".


@pytest.mark.asyncio
async def test_sampler_called_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """When installed, the sampler sees the adapter, args, stdout, exit_code=0."""
    from subprocess_util import run_subprocess, set_shadow_sampler

    sampler = _RecordingSampler()
    set_shadow_sampler(sampler)
    runner = _StubRunner(stdout='{"state":"OPEN"}\n')

    await run_subprocess("gh", "pr", "view", "42", "--json", "state", runner=runner)

    assert len(sampler.calls) == 1
    call = sampler.calls[0]
    assert call["adapter"] == "github"
    assert call["command"] == "gh"
    assert call["args"] == ["pr", "view", "42", "--json", "state"]
    assert call["stdout"] == '{"state":"OPEN"}\n'
    assert call["exit_code"] == 0


@pytest.mark.asyncio
async def test_sampler_called_on_failure() -> None:
    """Failures are sampled too — the failure shape IS part of the contract.
    A loop that depends on a specific stderr for a 404 path needs that
    shape protected against drift just as much as the success path."""
    from subprocess_util import run_subprocess, set_shadow_sampler

    sampler = _RecordingSampler()
    set_shadow_sampler(sampler)
    runner = _StubRunner(stdout="", stderr="not found\n", returncode=1)

    with pytest.raises(RuntimeError):
        await run_subprocess("gh", "pr", "view", "99999", runner=runner)

    assert len(sampler.calls) == 1
    assert sampler.calls[0]["exit_code"] == 1
    assert sampler.calls[0]["stderr"] == "not found\n"


@pytest.mark.asyncio
async def test_sampler_failure_does_not_break_subprocess() -> None:
    """A sampler that raises must not propagate — observability never breaks
    the production call path."""
    from subprocess_util import run_subprocess, set_shadow_sampler

    def angry_sampler(**_kw: Any) -> Path | None:
        raise RuntimeError("disk full")

    set_shadow_sampler(angry_sampler)
    runner = _StubRunner(stdout="ok\n")
    # Must succeed despite the sampler raising.
    result = await run_subprocess("git", "status", runner=runner)
    assert result == "ok\n"


@pytest.mark.asyncio
async def test_unknown_command_not_sampled() -> None:
    """Only known adapters (gh/git/docker/claude) feed the corpus; other
    binaries (npm, ruff, …) are skipped — they're not contract surfaces."""
    from subprocess_util import run_subprocess, set_shadow_sampler

    sampler = _RecordingSampler()
    set_shadow_sampler(sampler)
    runner = _StubRunner(stdout="")

    await run_subprocess("npm", "install", runner=runner)
    await run_subprocess("ruff", "check", runner=runner)

    assert sampler.calls == [], "non-adapter commands must not feed the shadow corpus"


@pytest.mark.asyncio
async def test_adapter_inferred_per_command() -> None:
    """gh→github, git→git, docker→docker, claude→claude."""
    from subprocess_util import run_subprocess, set_shadow_sampler

    sampler = _RecordingSampler()
    set_shadow_sampler(sampler)
    runner = _StubRunner(stdout="")

    for cmd0, _expected in (
        ("gh", "github"),
        ("git", "git"),
        ("docker", "docker"),
        ("claude", "claude"),
    ):
        await run_subprocess(cmd0, "version", runner=runner)

    adapters = [c["adapter"] for c in sampler.calls]
    assert adapters == ["github", "git", "docker", "claude"]
