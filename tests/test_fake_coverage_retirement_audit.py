"""Phase 9 tests: FakeCoverageAuditorLoop's retirement audit path.

The audit runs each tick when ``cassette_retirement_audit_enabled=True``
AND a ``retirement_keys_cb`` has been installed. Each candidate batch
fires at most one issue (dedup'd on the candidate set) labeled
``hydraflow-find`` + ``cassette-retirement-ready``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from fake_coverage_auditor_loop import FakeCoverageAuditorLoop


def _deps(stop: asyncio.Event) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *_a, **_k: None,
        enabled_cb=lambda _name: True,
    )


def _write_baseline_cassette(
    cassette_root: Path, adapter: str, name: str, command: str
) -> Path:
    """Drop a baseline_only cassette under ``cassette_root/<adapter>/``."""
    adapter_dir = cassette_root / adapter
    adapter_dir.mkdir(parents=True, exist_ok=True)
    path = adapter_dir / f"{name}.yaml"
    payload = {
        "adapter": adapter,
        "interaction": name,
        "recorded_at": "2026-05-13T00:00:00Z",
        "recorder_sha": "00000000",
        "fixture_repo": "x/y",
        "input": {"command": command, "args": [], "stdin": None, "env": {}},
        "output": {"exit_code": 0, "stdout": "", "stderr": ""},
        "normalizers": [],
        "baseline_only": True,
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def _make_loop(tmp_path: Path, **config_overrides):  # noqa: ANN201
    cfg = HydraFlowConfig(
        data_root=tmp_path / "data",
        repo_root=tmp_path / "repo",
        repo="x/y",
        **config_overrides,
    )
    (tmp_path / "repo").mkdir(parents=True, exist_ok=True)
    state = MagicMock()
    state.get_fake_coverage_last_known.return_value = {}
    state.get_fake_coverage_attempts.return_value = 0
    state.inc_fake_coverage_attempts.return_value = 1
    pr = AsyncMock()
    pr.create_issue = AsyncMock(return_value=7777)
    dedup = MagicMock()
    dedup.get.return_value = set()
    stop = asyncio.Event()
    loop = FakeCoverageAuditorLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )
    return loop, pr, dedup


@pytest.mark.asyncio
async def test_audit_skipped_when_flag_off(tmp_path: Path) -> None:
    """Default config → audit doesn't run, no issue."""
    cassette_root = tmp_path / "repo" / "tests" / "trust" / "contracts" / "cassettes"
    _write_baseline_cassette(cassette_root, "github", "merge_pr", "gh")
    loop, pr, _ = _make_loop(tmp_path)
    # Flag is False; cb is None — both block.
    filed = await loop._audit_retirement(cassette_root)
    assert filed == 0
    pr.create_issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_audit_skipped_when_cb_missing(tmp_path: Path) -> None:
    cassette_root = tmp_path / "cassettes"
    _write_baseline_cassette(cassette_root, "github", "merge_pr", "gh")
    loop, pr, _ = _make_loop(tmp_path, cassette_retirement_audit_enabled=True)
    # Flag is True but no cb installed; audit no-ops.
    filed = await loop._audit_retirement(cassette_root)
    assert filed == 0
    pr.create_issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_audit_files_issue_when_candidates_exist(tmp_path: Path) -> None:
    """A baseline cassette covered by a live dispatcher → one issue filed."""
    cassette_root = tmp_path / "cassettes"
    _write_baseline_cassette(cassette_root, "github", "covered", "gh")
    loop, pr, _ = _make_loop(tmp_path, cassette_retirement_audit_enabled=True)
    loop.set_retirement_keys_cb(lambda: {("github", "gh")})

    filed = await loop._audit_retirement(cassette_root)

    assert filed == 1
    pr.create_issue.assert_awaited_once()
    call = pr.create_issue.await_args
    title, body, labels = call.args
    assert "retirement" in title.lower()
    assert "covered.yaml" in body
    assert "cassette-retirement-ready" in labels


class _DictDedup:
    """Tiny stand-in for DedupStore — preserves state across get/set_all
    without the self-clearing trap a side_effect MagicMock falls into."""

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def get(self) -> set[str]:
        return set(self._seen)

    def set_all(self, new: set[str]) -> None:
        self._seen = set(new)

    def add(self, key: str) -> None:
        self._seen.add(key)


@pytest.mark.asyncio
async def test_audit_dedups_across_ticks(tmp_path: Path) -> None:
    """Same candidate batch on consecutive ticks → at most one issue."""
    cassette_root = tmp_path / "cassettes"
    _write_baseline_cassette(cassette_root, "github", "covered", "gh")
    loop, pr, _dedup = _make_loop(tmp_path, cassette_retirement_audit_enabled=True)
    loop._dedup = _DictDedup()  # type: ignore[assignment]
    loop.set_retirement_keys_cb(lambda: {("github", "gh")})

    first = await loop._audit_retirement(cassette_root)
    second = await loop._audit_retirement(cassette_root)

    assert first == 1
    assert second == 0
    assert pr.create_issue.await_count == 1


@pytest.mark.asyncio
async def test_audit_catches_callback_exception(tmp_path: Path) -> None:
    """A broken keys callback must not crash the loop."""
    cassette_root = tmp_path / "cassettes"
    _write_baseline_cassette(cassette_root, "github", "covered", "gh")
    loop, pr, _ = _make_loop(tmp_path, cassette_retirement_audit_enabled=True)

    def angry_cb() -> set[tuple[str, str]]:
        raise RuntimeError("boom")

    loop.set_retirement_keys_cb(angry_cb)
    filed = await loop._audit_retirement(cassette_root)
    assert filed == 0
    pr.create_issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_setter_clears_previous_callback(tmp_path: Path) -> None:
    cassette_root = tmp_path / "cassettes"
    _write_baseline_cassette(cassette_root, "github", "covered", "gh")
    loop, pr, _ = _make_loop(tmp_path, cassette_retirement_audit_enabled=True)
    loop.set_retirement_keys_cb(lambda: {("github", "gh")})
    loop.set_retirement_keys_cb(None)  # cleared
    filed = await loop._audit_retirement(cassette_root)
    assert filed == 0
    pr.create_issue.assert_not_awaited()
