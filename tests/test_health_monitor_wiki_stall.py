"""Test HealthMonitor dead-man-switch for RepoWikiLoop via log.jsonl mtime."""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from config import HydraFlowConfig
from health_monitor_loop import HealthMonitorLoop


@pytest.fixture
def hm_env(tmp_path: Path):
    from dedup_store import DedupStore

    repo_root = tmp_path / "repo"
    (repo_root / "docs" / "wiki").mkdir(parents=True)
    cfg = HydraFlowConfig(
        data_root=tmp_path,
        repo="hydra/hydraflow",
        repo_root=repo_root,
        wiki_freshness_stale_days=7,
    )
    prs = AsyncMock()
    prs.create_issue = AsyncMock(return_value=42)
    hm = HealthMonitorLoop.__new__(HealthMonitorLoop)
    hm._config = cfg
    hm._prs = prs
    hm._wiki_stall_dedup = DedupStore(
        "hm_wiki_stall_test",
        tmp_path / "dedup" / "hm_wiki_stall_test.json",
    )
    return hm, prs, repo_root


def _set_mtime(path: Path, age_days: float) -> None:
    epoch = time.time() - (age_days * 86400)
    os.utime(path, (epoch, epoch))


async def test_no_log_file_is_silent_noop(hm_env) -> None:
    hm, prs, _repo_root = hm_env
    await hm._check_wiki_freshness()
    prs.create_issue.assert_not_awaited()


async def test_recent_log_does_not_file_issue(hm_env) -> None:
    hm, prs, repo_root = hm_env
    log_path = repo_root / "docs" / "wiki" / "log.jsonl"
    log_path.write_text("{}\n")
    _set_mtime(log_path, age_days=1)
    await hm._check_wiki_freshness()
    prs.create_issue.assert_not_awaited()


async def test_stale_log_files_wiki_stale_issue(hm_env) -> None:
    hm, prs, repo_root = hm_env
    log_path = repo_root / "docs" / "wiki" / "log.jsonl"
    log_path.write_text("{}\n")
    _set_mtime(log_path, age_days=10)

    await hm._check_wiki_freshness()

    prs.create_issue.assert_awaited_once()
    title, _body, labels = prs.create_issue.await_args.args
    assert "wiki-stale" in title
    assert "10d" in title
    assert "hydraflow-find" in labels
    assert "wiki-stale" in labels


async def test_stale_log_dedups_within_same_stall(hm_env) -> None:
    hm, prs, repo_root = hm_env
    log_path = repo_root / "docs" / "wiki" / "log.jsonl"
    log_path.write_text("{}\n")
    _set_mtime(log_path, age_days=10)

    await hm._check_wiki_freshness()
    await hm._check_wiki_freshness()
    await hm._check_wiki_freshness()

    prs.create_issue.assert_awaited_once()


async def test_recovery_clears_dedup(hm_env) -> None:
    hm, prs, repo_root = hm_env
    log_path = repo_root / "docs" / "wiki" / "log.jsonl"
    log_path.write_text("{}\n")
    _set_mtime(log_path, age_days=10)
    await hm._check_wiki_freshness()
    assert prs.create_issue.await_count == 1

    _set_mtime(log_path, age_days=0)
    await hm._check_wiki_freshness()

    _set_mtime(log_path, age_days=10)
    await hm._check_wiki_freshness()

    assert prs.create_issue.await_count == 2


async def test_threshold_respects_config(hm_env) -> None:
    hm, prs, repo_root = hm_env
    hm._config = hm._config.model_copy(update={"wiki_freshness_stale_days": 30})
    log_path = repo_root / "docs" / "wiki" / "log.jsonl"
    log_path.write_text("{}\n")
    _set_mtime(log_path, age_days=10)
    await hm._check_wiki_freshness()
    prs.create_issue.assert_not_awaited()


async def test_no_prs_dependency_is_silent_noop(hm_env) -> None:
    hm, _prs, repo_root = hm_env
    hm._prs = None
    log_path = repo_root / "docs" / "wiki" / "log.jsonl"
    log_path.write_text("{}\n")
    _set_mtime(log_path, age_days=10)
    await hm._check_wiki_freshness()
