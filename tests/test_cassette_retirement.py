"""Unit tests for the cassette retirement audit (Phase 6 of #8786)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from contracts.retirement import (
    RetirementCandidate,
    find_retirement_candidates,
    format_candidates_for_issue,
)


def _write_cassette(
    path: Path,
    *,
    adapter: str,
    command: str,
    interaction: str = "anything",
    baseline_only: bool = False,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "adapter": adapter,
        "interaction": interaction,
        "recorded_at": "2026-05-13T00:00:00Z",
        "recorder_sha": "00000000",
        "fixture_repo": "x/y",
        "input": {"command": command, "args": [], "stdin": None, "env": {}},
        "output": {"exit_code": 0, "stdout": "", "stderr": ""},
        "normalizers": [],
        "baseline_only": baseline_only,
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def test_no_candidates_when_no_dispatchers(tmp_path: Path) -> None:
    """Empty dispatcher set → no candidates ever."""
    _write_cassette(
        tmp_path / "github" / "merge_pr.yaml",
        adapter="github",
        command="merge_pr",
        baseline_only=True,
    )
    candidates = find_retirement_candidates(tmp_path, dispatcher_keys=set())
    assert candidates == []


def test_dispatcher_covers_baseline_cassette(tmp_path: Path) -> None:
    """When a dispatcher key matches the cassette's (adapter, command) and
    baseline_only=true, the cassette is a retirement candidate."""
    _write_cassette(
        tmp_path / "github" / "x.yaml",
        adapter="github",
        command="gh",
        interaction="pr_view",
        baseline_only=True,
    )
    candidates = find_retirement_candidates(
        tmp_path, dispatcher_keys={("github", "gh")}
    )
    assert len(candidates) == 1
    assert candidates[0].adapter == "github"
    assert candidates[0].interaction == "pr_view"
    assert candidates[0].dispatcher_key == ("github", "gh")
    assert candidates[0].reason == "dispatcher_covers_shape"


def test_non_baseline_cassettes_ignored(tmp_path: Path) -> None:
    """Live-recorded cassettes (baseline_only=false or missing) are NEVER
    candidates — those represent the live-recording corpus, not legacy
    baselines."""
    _write_cassette(
        tmp_path / "git" / "commit.yaml",
        adapter="git",
        command="commit",
        baseline_only=False,
    )
    candidates = find_retirement_candidates(
        tmp_path, dispatcher_keys={("git", "commit")}
    )
    assert candidates == []


def test_missing_dispatcher_for_command_no_candidate(tmp_path: Path) -> None:
    """A baseline cassette whose command isn't dispatcher-covered stays."""
    _write_cassette(
        tmp_path / "github" / "merge_pr.yaml",
        adapter="github",
        command="merge_pr",
        baseline_only=True,
    )
    # Dispatcher registered for "gh" but cassette command is "merge_pr".
    candidates = find_retirement_candidates(
        tmp_path, dispatcher_keys={("github", "gh")}
    )
    assert candidates == []


def test_malformed_cassette_skipped(tmp_path: Path) -> None:
    """A YAML parse error must not crash the audit — log + skip."""
    (tmp_path / "github").mkdir()
    (tmp_path / "github" / "broken.yaml").write_text(
        "this is: not: valid: yaml: at all: [", encoding="utf-8"
    )
    # Also write a good baseline to prove the audit continued past the bad one.
    _write_cassette(
        tmp_path / "github" / "good.yaml",
        adapter="github",
        command="gh",
        baseline_only=True,
    )
    candidates = find_retirement_candidates(
        tmp_path, dispatcher_keys={("github", "gh")}
    )
    assert len(candidates) == 1
    assert candidates[0].path.name == "good.yaml"


def test_nonexistent_root_returns_empty(tmp_path: Path) -> None:
    candidates = find_retirement_candidates(
        tmp_path / "does-not-exist", dispatcher_keys={("github", "gh")}
    )
    assert candidates == []


def test_format_empty(tmp_path: Path) -> None:
    assert format_candidates_for_issue([]) == "No retirement candidates."


def test_format_renders_table(tmp_path: Path) -> None:
    candidates = [
        RetirementCandidate(
            path=tmp_path / "github" / "merge_pr.yaml",
            adapter="github",
            interaction="merge_pr",
            dispatcher_key=("github", "gh"),
            reason="dispatcher_covers_shape",
        )
    ]
    body = format_candidates_for_issue(candidates)
    assert "merge_pr.yaml" in body
    assert "github" in body
    assert "| Cassette |" in body


@pytest.mark.asyncio
async def test_live_loop_exposes_registered_shapes() -> None:
    """LiveCorpusReplayLoop.registered_shapes() returns the (adapter, command)
    set the retirement audit consumes."""
    import asyncio
    import tempfile
    from unittest.mock import AsyncMock, MagicMock

    from base_background_loop import LoopDeps
    from config import HydraFlowConfig
    from contracts.shadow import ShadowCorpus
    from dedup_store import DedupStore
    from events import EventBus
    from live_corpus_replay_loop import LiveCorpusReplayLoop

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        config = HydraFlowConfig(
            data_root=root / "data", repo_root=root / "repo", repo="x/y"
        )
        (root / "repo").mkdir()
        corpus = ShadowCorpus(config.data_root / "contract_shadow")
        dedup = DedupStore("x", config.data_root / "dedup" / "x.json")
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
            pr_manager=AsyncMock(),
            dedup=dedup,
            deps=deps,
        )

        async def _stub(_sample):  # noqa: ANN001
            return None

        loop.register("github", "gh", _stub)
        loop.register("git", "git", _stub)
        assert loop.registered_shapes() == {("github", "gh"), ("git", "git")}
