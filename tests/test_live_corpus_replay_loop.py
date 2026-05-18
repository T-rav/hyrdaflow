"""Unit tests for LiveCorpusReplayLoop (Phase 2 of #8786).

Covers the loop's reaction surface (Pattern B per
``docs/standards/testing/README.md`` §How to write each layer):

- Empty corpus → status=ok, compared=0.
- Sample with no registered dispatcher → skipped, no issue filed.
- Sample matched by dispatcher with no drift → compared=1, no issue.
- Sample matched by dispatcher WITH drift → issue filed (hydraflow-find).
- Dedup: identical drift on consecutive ticks files at most one issue.
- Dispatcher raising is caught — loop continues, errors counted.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from contracts.shadow import ShadowCorpus
from dedup_store import DedupStore
from events import EventBus
from live_corpus_replay_loop import LiveCorpusReplayLoop


class _FakeState:
    """Minimal StateTracker stub for the per-signature attempt counters."""

    def __init__(self) -> None:
        self._attempts: dict[str, int] = {}

    def get_live_corpus_drift_attempts(self, sig: str) -> int:
        return self._attempts.get(sig, 0)

    def inc_live_corpus_drift_attempts(self, sig: str) -> int:
        self._attempts[sig] = self._attempts.get(sig, 0) + 1
        return self._attempts[sig]

    def clear_live_corpus_drift_attempts(self) -> None:
        self._attempts.clear()


def _build_loop(
    tmp_path: Path,
    *,
    pr_manager: Any | None = None,
    state: Any | None = None,
    max_drift_attempts: int = 3,
) -> tuple[LiveCorpusReplayLoop, ShadowCorpus, Any, Any]:
    config = HydraFlowConfig(
        data_root=tmp_path / "data",
        repo_root=tmp_path / "repo",
        repo="hydra/hydraflow",
        live_corpus_max_drift_attempts=max_drift_attempts,
    )
    (tmp_path / "repo").mkdir(parents=True, exist_ok=True)
    corpus = ShadowCorpus(config.data_root / "contract_shadow")
    pr = pr_manager
    if pr is None:
        pr = MagicMock()
        pr.create_issue = AsyncMock(return_value=4242)
    dedup = DedupStore(
        "live_corpus_replay",
        config.data_root / "dedup" / "live_corpus_replay.json",
    )
    state_obj = state if state is not None else _FakeState()
    stop = asyncio.Event()
    deps = LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=MagicMock(),
        enabled_cb=lambda _: True,
        sleep_fn=AsyncMock(),
    )
    loop = LiveCorpusReplayLoop(
        config=config,
        corpus=corpus,
        pr_manager=pr,
        dedup=dedup,
        deps=deps,
        state=state_obj,
    )
    return loop, corpus, pr, state_obj


@pytest.mark.asyncio
async def test_empty_corpus_returns_ok_with_zero_compared(tmp_path: Path) -> None:
    loop, _, pr, _state = _build_loop(tmp_path)
    result = await loop._do_work()
    assert result == {
        "status": "ok",
        "compared": 0,
        "skipped_no_dispatcher": 0,
        "drifted": 0,
        "errors": 0,
        "filed_issue": None,
        "escalated_issue": None,
        "escalated_signatures": 0,
    }
    pr.create_issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_sample_with_no_dispatcher_is_skipped(tmp_path: Path) -> None:
    loop, corpus, pr, _state = _build_loop(tmp_path)
    corpus.record(
        adapter="github",
        command="gh",
        args=["pr", "view", "42"],
        stdout='{"state":"OPEN"}\n',
        stderr="",
        exit_code=0,
    )
    result = await loop._do_work()
    assert result["compared"] == 0
    assert result["skipped_no_dispatcher"] == 1
    assert result["drifted"] == 0
    pr.create_issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatcher_match_no_drift(tmp_path: Path) -> None:
    """Fake output equal to sample → compared=1, no drift, no issue."""
    loop, corpus, pr, _state = _build_loop(tmp_path)
    payload = {"state": "OPEN", "mergeable": "MERGEABLE"}
    corpus.record(
        adapter="github",
        command="gh",
        args=["pr", "view", "42", "--json", "state,mergeable"],
        stdout=json.dumps(payload) + "\n",
        stderr="",
        exit_code=0,
    )

    async def gh_dispatcher(_sample):  # noqa: ANN001
        return payload

    loop.register("github", "gh", gh_dispatcher)
    result = await loop._do_work()
    assert result["compared"] == 1
    assert result["drifted"] == 0
    pr.create_issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatcher_match_with_drift_files_issue(tmp_path: Path) -> None:
    """Fake output diverges → single hydraflow-find issue filed."""
    loop, corpus, pr, _state = _build_loop(tmp_path)
    corpus.record(
        adapter="github",
        command="gh",
        args=["pr", "view", "42", "--json", "state"],
        stdout='{"state":"MERGED"}\n',
        stderr="",
        exit_code=0,
    )

    async def stale_fake(_sample):  # noqa: ANN001
        return {"state": "OPEN"}  # diverges from sampled "MERGED"

    loop.register("github", "gh", stale_fake)
    result = await loop._do_work()

    assert result["drifted"] == 1
    pr.create_issue.assert_awaited_once()
    call_args = pr.create_issue.await_args
    labels = call_args.kwargs.get("labels") or call_args.args[2]
    assert "hydraflow-find" in labels
    assert "shadow-drift" in labels


@pytest.mark.asyncio
async def test_identical_drift_dedups_across_ticks(tmp_path: Path) -> None:
    loop, corpus, pr, _state = _build_loop(tmp_path)
    corpus.record(
        adapter="github",
        command="gh",
        args=["pr", "view", "42"],
        stdout='{"state":"MERGED"}\n',
        stderr="",
        exit_code=0,
    )

    async def stale_fake(_sample):  # noqa: ANN001
        return {"state": "OPEN"}

    loop.register("github", "gh", stale_fake)
    first = await loop._do_work()
    second = await loop._do_work()

    assert first["drifted"] == 1
    assert first["filed_issue"] == 4242
    # Second tick still sees drift but dedup suppresses the issue.
    assert second["drifted"] == 1
    assert second["filed_issue"] is None
    pr.create_issue.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatcher_raising_is_caught(tmp_path: Path) -> None:
    loop, corpus, pr, _state = _build_loop(tmp_path)
    corpus.record(
        adapter="github",
        command="gh",
        args=["pr", "view", "1"],
        stdout="",
        stderr="",
        exit_code=0,
    )

    async def angry_dispatcher(_sample):  # noqa: ANN001
        raise RuntimeError("boom")

    loop.register("github", "gh", angry_dispatcher)
    result = await loop._do_work()
    assert result["errors"] == 1
    assert result["drifted"] == 0
    pr.create_issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_disabled_kill_switch_short_circuits(tmp_path: Path) -> None:
    loop, corpus, pr, _state = _build_loop(tmp_path)
    loop._enabled_cb = lambda _name: False
    corpus.record(
        adapter="github",
        command="gh",
        args=["pr", "view", "1"],
        stdout="",
        stderr="",
        exit_code=0,
    )
    result = await loop._do_work()
    assert result == {"status": "disabled"}
    pr.create_issue.assert_not_awaited()


# ---------------------------------------------------------------------------
# Phase 3: 3-attempt escalation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_escalation_fires_after_threshold_attempts(tmp_path: Path) -> None:
    """When the same drift signature survives ``live_corpus_max_drift_attempts``
    consecutive ticks, the loop files a ``hitl-escalation`` issue routed to
    the auto-agent preflight pipeline."""
    pr = MagicMock()
    # Two awaited calls in this test: one drift issue (tick 1), one
    # escalation issue (tick 3 hits the threshold). Ticks 2/3 dedup-skip
    # the drift issue.
    pr.create_issue = AsyncMock(side_effect=[4242, 5555])
    loop, corpus, _pr, _state = _build_loop(
        tmp_path, pr_manager=pr, max_drift_attempts=3
    )
    corpus.record(
        adapter="github",
        command="gh",
        args=["pr", "view", "42"],
        stdout='{"state":"MERGED"}\n',
        stderr="",
        exit_code=0,
    )

    async def stale_fake(_sample):  # noqa: ANN001
        return {"state": "OPEN"}

    loop.register("github", "gh", stale_fake)

    # Three ticks with identical drift. The third one hits the threshold.
    results = []
    for _ in range(3):
        results.append(await loop._do_work())

    assert results[0]["escalated_signatures"] == 0
    assert results[1]["escalated_signatures"] == 0
    assert results[2]["escalated_signatures"] == 1
    assert results[2]["escalated_issue"] == 5555

    # The escalation issue carries the hitl-escalation label so the
    # AutoAgentPreflightLoop picks it up.
    escalation_call = pr.create_issue.await_args_list[-1]
    labels = escalation_call.kwargs.get("labels") or escalation_call.args[2]
    assert "hitl-escalation" in labels
    assert "shadow-drift-stuck" in labels


@pytest.mark.asyncio
async def test_clean_tick_clears_attempt_counters(tmp_path: Path) -> None:
    """When drift resolves (clean tick), all attempt counters reset so a
    future re-occurrence of the same signature starts fresh."""
    loop, corpus, _pr, state = _build_loop(tmp_path, max_drift_attempts=3)
    sample_path = corpus.record(
        adapter="github",
        command="gh",
        args=["pr", "view", "1"],
        stdout='{"state":"MERGED"}\n',
        stderr="",
        exit_code=0,
    )
    assert sample_path is not None

    async def stale_fake(_sample):  # noqa: ANN001
        return {"state": "OPEN"}

    loop.register("github", "gh", stale_fake)
    await loop._do_work()
    await loop._do_work()
    # After two ticks of drift, the per-signature counter is 2.
    assert len(state._attempts) == 1
    counter = next(iter(state._attempts.values()))
    assert counter == 2

    # Now the fake catches up — clean tick.
    async def fixed_fake(_sample):  # noqa: ANN001
        return {"state": "MERGED"}

    loop.register("github", "gh", fixed_fake)
    clean = await loop._do_work()

    assert clean["drifted"] == 0
    assert state._attempts == {}, "clean tick must clear all counters"
