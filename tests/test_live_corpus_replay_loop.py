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


def _build_loop(
    tmp_path: Path,
    *,
    pr_manager: Any | None = None,
) -> tuple[LiveCorpusReplayLoop, ShadowCorpus, Any]:
    config = HydraFlowConfig(
        data_root=tmp_path / "data",
        repo_root=tmp_path / "repo",
        repo="hydra/hydraflow",
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
    )
    return loop, corpus, pr


@pytest.mark.asyncio
async def test_empty_corpus_returns_ok_with_zero_compared(tmp_path: Path) -> None:
    loop, _, pr = _build_loop(tmp_path)
    result = await loop._do_work()
    assert result == {
        "status": "ok",
        "compared": 0,
        "skipped_no_dispatcher": 0,
        "drifted": 0,
        "errors": 0,
        "filed_issue": None,
    }
    pr.create_issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_sample_with_no_dispatcher_is_skipped(tmp_path: Path) -> None:
    loop, corpus, pr = _build_loop(tmp_path)
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
    loop, corpus, pr = _build_loop(tmp_path)
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
    loop, corpus, pr = _build_loop(tmp_path)
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
    loop, corpus, pr = _build_loop(tmp_path)
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
    loop, corpus, pr = _build_loop(tmp_path)
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
    loop, corpus, pr = _build_loop(tmp_path)
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
