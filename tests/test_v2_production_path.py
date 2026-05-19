"""Production-path integration test for #8786 v2 — boot the real
``ServiceRegistry``, exercise real ``run_subprocess`` calls through a stub
runner, and verify the shadow corpus captures + the replay loop processes
the resulting samples.

Why this layer exists:

- Unit tests prove each component works in isolation.
- The Pattern A MockWorld scenario (``test_v2_drift_chain_mockworld.py``)
  proves the loop wiring reaches a real ``FakeGitHub`` issue store WHEN
  given a pre-seeded corpus.
- This integration test fills the remaining gap: **does the real
  production-path actually feed the corpus when a real subprocess call
  happens?** That's the question MockWorld can't answer because in
  MockWorld no ``run_subprocess("gh", ...)`` ever executes — FakeGitHub
  short-circuits the subprocess.

The test builds the real ``ServiceRegistry`` (which installs the sampler
via the same code path production uses), invokes ``run_subprocess`` with
an injected ``runner=`` stub (the same dependency-injection seam sandbox
uses to stub the LLM), and verifies:

1. The sampler is installed by ``ServiceRegistry`` construction.
2. A real ``run_subprocess("gh", ...)`` call lands a sample on disk.
3. The real ``LiveCorpusReplayLoop`` from the registry can read + replay
   that sample without crashing.
4. A drifted sample fires a ``hydraflow-find`` issue through the real
   ``PRManager`` adapter.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

import subprocess_util
from config import HydraFlowConfig
from events import EventBus
from execution import SimpleResult
from service_registry import WorkerRegistryCallbacks, build_services
from state import StateTracker
from subprocess_util import run_subprocess
from tests.helpers import ConfigFactory


class _StubRunner:
    """SubprocessRunner stand-in — returns a canned SimpleResult.

    Same shape sandbox uses to stub the LLM at the runner seam.
    """

    def __init__(self, stdout: str, returncode: int = 0) -> None:
        self._stdout = stdout
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
        return SimpleResult(stdout=self._stdout, stderr="", returncode=self._returncode)

    async def create_streaming_process(
        self, *_a: Any, **_k: Any
    ) -> Any:  # pragma: no cover
        raise NotImplementedError

    async def cleanup(self) -> None:  # pragma: no cover
        return None


def _callbacks() -> WorkerRegistryCallbacks:
    return WorkerRegistryCallbacks(
        update_status=lambda *_a, **_k: None,
        is_enabled=lambda _name: True,
        get_interval=lambda _name: 900,
    )


@pytest.fixture(autouse=True)
def _reset_sampler():  # noqa: ANN201
    """Sampler is module-state — reset to avoid bleed between tests."""
    subprocess_util.set_shadow_sampler(None)
    yield
    subprocess_util.set_shadow_sampler(None)


@pytest.fixture
def _config(tmp_path: Path) -> HydraFlowConfig:
    return ConfigFactory.create(
        repo_root=tmp_path / "repo",
        workspace_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )


def _build_real_registry(config: HydraFlowConfig):  # noqa: ANN202
    """Spin up the real ServiceRegistry the same way the orchestrator does."""
    (config.repo_root).mkdir(parents=True, exist_ok=True)
    bus = EventBus()
    state = StateTracker(config.state_file)
    stop_event = asyncio.Event()
    return build_services(config, bus, state, stop_event, _callbacks())


# ---------------------------------------------------------------------------
# 1. ServiceRegistry construction installs the sampler — no flag, no opt-in
# ---------------------------------------------------------------------------


def test_service_registry_installs_shadow_sampler(_config: HydraFlowConfig) -> None:
    """Building the real registry installs the sampler. No config knob in
    play — the v2 pipeline is on for every orchestrator boot."""
    assert subprocess_util._shadow_sampler is None
    _build_real_registry(_config)
    assert subprocess_util._shadow_sampler is not None


# ---------------------------------------------------------------------------
# 2. A real run_subprocess call lands a sample on disk
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_subprocess_call_lands_in_corpus(
    _config: HydraFlowConfig,
) -> None:
    """The seam works end-to-end: build registry → call run_subprocess
    with the injected runner → corpus has a file with the captured shape."""
    _build_real_registry(_config)
    runner = _StubRunner(stdout='{"number":1,"state":"OPEN"}\n')

    stdout = await run_subprocess(
        "gh", "pr", "view", "1", "--json", "number,state", runner=runner
    )
    assert "OPEN" in stdout  # production-path return semantics preserved

    corpus_dir = _config.data_root / "contract_shadow" / "github"
    samples = list(corpus_dir.glob("*.yaml"))
    assert samples, "expected one sample under contract_shadow/github/"
    body = samples[0].read_text()
    assert "OPEN" in body and "pr" in body and "view" in body


# ---------------------------------------------------------------------------
# 3. LiveCorpusReplayLoop from the real registry processes the sample
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replay_loop_processes_real_captured_sample(
    _config: HydraFlowConfig,
) -> None:
    """Build real registry → capture via real run_subprocess → registry's
    LiveCorpusReplayLoop ticks against the real captured sample and
    completes without raising."""
    svc = _build_real_registry(_config)
    runner = _StubRunner(stdout='{"number":1,"state":"OPEN","mergeable":"MERGEABLE"}\n')

    await run_subprocess(
        "gh",
        "pr",
        "view",
        "1",
        "--json",
        "number,state,mergeable",
        runner=runner,
    )

    result = await svc.live_corpus_replay_loop._do_work()
    assert result is not None
    assert result["status"] == "ok"
    # The sample matches GhPRDetail → no drift.
    assert result["drifted"] == 0
    assert result["compared"] >= 1


# ---------------------------------------------------------------------------
# 4. A drifted sample drives the chain to PRManager.create_issue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drifted_call_files_hydraflow_find_via_real_chain(
    _config: HydraFlowConfig,
) -> None:
    """Inject a sample that fails Pydantic Literal validation, tick the
    loop, assert PRManager.create_issue is awaited with hydraflow-find
    + shadow-drift labels. End-to-end: real registry, real sampler, real
    corpus, real loop, real dispatcher, real PRManager → mocked
    create_issue (the only thing we mock is gh-API egress)."""
    svc = _build_real_registry(_config)
    # Mock only the outermost egress — PRManager.create_issue actually
    # shells out to ``gh issue create``; we don't want to do that, but
    # the END of the chain is what we're verifying lands here.
    create_issue_mock = AsyncMock(return_value=4242)
    svc.prs.create_issue = create_issue_mock  # type: ignore[method-assign]

    runner = _StubRunner(
        stdout='{"number":99,"state":"OPEN","mergeable":"WARP_DRIVE"}\n'
    )
    await run_subprocess(
        "gh",
        "pr",
        "view",
        "99",
        "--json",
        "number,state,mergeable",
        runner=runner,
    )

    result = await svc.live_corpus_replay_loop._do_work()

    assert result is not None
    assert result["drifted"] == 1
    create_issue_mock.assert_awaited_once()
    call = create_issue_mock.await_args
    assert call is not None
    labels: list[str]
    if "labels" in call.kwargs:
        labels = list(call.kwargs["labels"])
    elif len(call.args) >= 3:
        labels = list(call.args[2])
    else:
        labels = []
    assert labels, "expected non-empty labels list"
    assert "hydraflow-find" in labels
    assert "shadow-drift" in labels
    assert "hitl-escalation" not in labels


# ---------------------------------------------------------------------------
# 5. Non-adapter binaries are NOT sampled (production-path safety)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_adapter_binary_does_not_feed_corpus(
    _config: HydraFlowConfig,
) -> None:
    """A real ``npm install`` or ``ruff check`` must not generate corpus
    samples — only the four adapter binaries (gh/git/docker/claude) feed."""
    _build_real_registry(_config)
    runner = _StubRunner(stdout="installed 10 packages")

    await run_subprocess("npm", "install", runner=runner)
    await run_subprocess("ruff", "check", runner=runner)

    # No directory should have been created for npm/ruff.
    corpus_root = _config.data_root / "contract_shadow"
    if corpus_root.exists():
        for adapter_dir in corpus_root.iterdir():
            assert adapter_dir.name in {
                "github",
                "git",
                "docker",
                "claude",
            }, f"unexpected adapter directory: {adapter_dir.name}"
