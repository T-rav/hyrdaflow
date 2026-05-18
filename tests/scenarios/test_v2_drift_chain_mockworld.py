"""MockWorld scenario for #8786 v2 drift detection — end-to-end through
the real ``FakeGitHub`` adapter (Pattern A per docs/standards/testing/README.md).

This is the scenario layer that's been missing from the v2 trail. Earlier
scenario tests used Pattern B (direct loop instantiation with MagicMock
collaborators), which proves the loop's reaction surface but does NOT prove
the chain reaches a real fake adapter's storage. Pattern A here drives:

1. A real ``MockWorld`` with a real ``FakeGitHub``.
2. A real ``ShadowCorpus`` (the bounded YAML store).
3. A real ``LiveCorpusReplayLoop`` registered with the real Phase 5
   ``gh_shape_validator`` dispatcher.
4. A drifted sample is captured (shape validation MUST fail).
5. The loop ticks and fires ``hydraflow-find`` + ``shadow-drift`` issue.
6. The issue lands in ``FakeGitHub``'s issue store — verifiable by the
   scenario, the same way a production drift would land on a real
   github repo.

This closes acceptance criterion #4 (drift signal reaches the autonomous
queue without human routing) at the SCENARIO layer, complementing the
unit-level proofs.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from contracts.shadow import ShadowCorpus
from contracts.shape_dispatchers import gh_shape_validator
from dedup_store import DedupStore
from events import EventBus
from live_corpus_replay_loop import LiveCorpusReplayLoop
from tests.scenarios.fakes.mock_world import MockWorld

pytestmark = pytest.mark.scenario_loops


def _build_loop(
    world: MockWorld, tmp_path: Path
) -> tuple[LiveCorpusReplayLoop, ShadowCorpus]:
    """Construct the v2 stack against MockWorld's real ``FakeGitHub``."""
    config = HydraFlowConfig(
        data_root=tmp_path / "data",
        repo_root=tmp_path / "repo",
        repo="hydra/hydraflow",
    )
    (tmp_path / "repo").mkdir(parents=True, exist_ok=True)
    corpus = ShadowCorpus(
        config.data_root / "contract_shadow",
        max_per_adapter=config.shadow_corpus_max_per_adapter,
    )
    dedup = DedupStore(
        "live_corpus_replay",
        config.data_root / "dedup" / "live_corpus_replay.json",
    )

    # MagicMock for the StateTracker — the loop only reads attempt
    # counters, not full state. A real StateTracker would also work but
    # adds boot/persist costs irrelevant to this scenario.
    state = MagicMock()
    state.inc_live_corpus_drift_attempts = MagicMock(return_value=1)
    state.clear_live_corpus_drift_attempts = MagicMock()

    stop = asyncio.Event()
    deps = LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=MagicMock(),
        enabled_cb=lambda _: True,
        sleep_fn=AsyncMock(),
    )

    # The critical line: pass the REAL FakeGitHub from MockWorld as the
    # pr_manager. The loop's ``create_issue`` call will land in
    # world.github._issues, observable by the scenario.
    loop = LiveCorpusReplayLoop(
        config=config,
        corpus=corpus,
        pr_manager=world.github,
        dedup=dedup,
        state=state,
        deps=deps,
    )
    loop.register("github", "gh", gh_shape_validator)
    return loop, corpus


class TestV2DriftChainMockWorld:
    async def test_drift_reaches_fake_github_issue_store(self, tmp_path: Path) -> None:
        """End-to-end scenario test:
        - Inject a sample with a drifted ``mergeable`` enum.
        - Tick the loop.
        - Verify a ``hydraflow-find`` + ``shadow-drift`` issue lands in
          MockWorld's FakeGitHub.
        """
        world = MockWorld(tmp_path)
        loop, corpus = _build_loop(world, tmp_path)

        # Inject a drifted sample. The shape dispatcher (GhPRDetail) pins
        # ``mergeable`` to a Literal; an unknown value MUST fire validation.
        corpus.record(
            adapter="github",
            command="gh",
            args=["pr", "view", "42", "--json", "number,mergeable"],
            stdout=json.dumps({"number": 42, "mergeable": "WARP_DRIVE"}) + "\n",
            stderr="",
            exit_code=0,
        )

        # Snapshot before — no issues yet.
        assert len(world.github._issues) == 0

        result = await loop._do_work()

        assert result is not None
        assert result["drifted"] == 1, (
            f"shape validator should have fired on bad enum; result={result}"
        )

        # An issue was created in the real FakeGitHub. The drift chain
        # reached the autonomous queue without any human routing.
        assert len(world.github._issues) == 1
        filed_issue_number = next(iter(world.github._issues))
        issue = world.github._issues[filed_issue_number]
        assert "hydraflow-find" in issue.labels
        assert "shadow-drift" in issue.labels
        # Critical: no HITL labels — autonomous-only routing.
        assert "hitl-escalation" not in issue.labels
        assert "human-required" not in issue.labels

    async def test_clean_tick_files_no_issue(self, tmp_path: Path) -> None:
        """Well-shaped samples leave the FakeGitHub issue store empty —
        no false positives."""
        world = MockWorld(tmp_path)
        loop, corpus = _build_loop(world, tmp_path)

        corpus.record(
            adapter="github",
            command="gh",
            args=["pr", "view", "1", "--json", "number,mergeable"],
            stdout=json.dumps({"number": 1, "mergeable": "MERGEABLE"}) + "\n",
            stderr="",
            exit_code=0,
        )

        result = await loop._do_work()
        assert result is not None
        assert result["drifted"] == 0
        assert len(world.github._issues) == 0
