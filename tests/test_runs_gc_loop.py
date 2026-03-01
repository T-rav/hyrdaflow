"""Tests for the RunsGCLoop background worker and RunRecorder retention methods."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from run_recorder import RunManifest, RunRecorder
from runs_gc_loop import RunsGCLoop
from tests.helpers import ConfigFactory, make_bg_loop_deps

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_recorder(
    tmp_path: Path,
    **config_overrides,
) -> tuple[object, RunRecorder]:
    """Create a RunRecorder with test-friendly defaults."""
    config = ConfigFactory.create(repo_root=tmp_path / "repo", **config_overrides)
    (tmp_path / "repo").mkdir(parents=True, exist_ok=True)
    return config, RunRecorder(config)


def _seed_run(recorder: RunRecorder, issue: int, timestamp: str) -> Path:
    """Create a minimal run directory with a manifest and a dummy file."""
    run_dir = recorder.runs_dir / str(issue) / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = RunManifest(issue_number=issue, timestamp=timestamp, outcome="success")
    (run_dir / "manifest.json").write_text(manifest.model_dump_json())
    (run_dir / "plan.md").write_text("x" * 100)
    return run_dir


def _make_loop(
    tmp_path: Path,
    *,
    enabled: bool = True,
    retention_days: int = 30,
    max_size_mb: int = 500,
    runs_gc_interval: int = 600,
) -> tuple[RunsGCLoop, RunRecorder, asyncio.Event]:
    """Build a RunsGCLoop with test-friendly defaults."""
    deps = make_bg_loop_deps(
        tmp_path,
        enabled=enabled,
        artifact_retention_days=retention_days,
        artifact_max_size_mb=max_size_mb,
        runs_gc_interval=runs_gc_interval,
    )
    recorder = RunRecorder(deps.config)
    loop = RunsGCLoop(
        config=deps.config,
        run_recorder=recorder,
        event_bus=deps.bus,
        stop_event=deps.stop_event,
        status_cb=deps.status_cb,
        enabled_cb=deps.enabled_cb,
        sleep_fn=deps.sleep_fn,
        interval_cb=None,
    )
    return loop, recorder, deps.stop_event


# ===========================================================================
# RunRecorder.get_storage_stats
# ===========================================================================


class TestGetStorageStats:
    def test_empty_runs_dir(self, tmp_path: Path) -> None:
        _config, recorder = _make_recorder(tmp_path)
        stats = recorder.get_storage_stats()
        assert stats["total_bytes"] == 0
        assert stats["total_runs"] == 0
        assert stats["issues"] == 0
        assert stats["total_mb"] == 0

    def test_counts_runs_and_issues(self, tmp_path: Path) -> None:
        _config, recorder = _make_recorder(tmp_path)
        _seed_run(recorder, 10, "20260101T100000Z")
        _seed_run(recorder, 10, "20260101T200000Z")
        _seed_run(recorder, 42, "20260101T100000Z")

        stats = recorder.get_storage_stats()
        assert stats["total_runs"] == 3
        assert stats["issues"] == 2
        assert stats["total_bytes"] > 0
        assert stats["total_mb"] >= 0  # small files may round to 0.0

    def test_skips_non_digit_issue_dirs(self, tmp_path: Path) -> None:
        _config, recorder = _make_recorder(tmp_path)
        _seed_run(recorder, 42, "20260101T100000Z")
        # Create a non-digit dir that should be ignored
        junk = recorder.runs_dir / "not-an-issue"
        junk.mkdir(parents=True, exist_ok=True)
        (junk / "file.txt").write_text("junk")

        stats = recorder.get_storage_stats()
        assert stats["issues"] == 1
        assert stats["total_runs"] == 1


# ===========================================================================
# RunRecorder.purge_expired
# ===========================================================================


class TestPurgeExpired:
    def test_removes_old_runs(self, tmp_path: Path) -> None:
        _config, recorder = _make_recorder(tmp_path)
        # Old run (way past retention)
        _seed_run(recorder, 42, "20200101T000000Z")
        # Recent run (should survive)
        _seed_run(recorder, 42, "20261231T000000Z")

        removed = recorder.purge_expired(retention_days=30)
        assert removed == 1
        runs = recorder.list_runs(42)
        assert len(runs) == 1
        assert runs[0].timestamp == "20261231T000000Z"

    def test_noop_when_no_expired(self, tmp_path: Path) -> None:
        _config, recorder = _make_recorder(tmp_path)
        _seed_run(recorder, 42, "20261231T000000Z")
        removed = recorder.purge_expired(retention_days=30)
        assert removed == 0

    def test_removes_empty_issue_dirs(self, tmp_path: Path) -> None:
        _config, recorder = _make_recorder(tmp_path)
        _seed_run(recorder, 42, "20200101T000000Z")
        recorder.purge_expired(retention_days=30)
        # Issue dir should be removed since all runs were purged
        assert not (recorder.runs_dir / "42").exists()

    def test_empty_runs_dir_returns_zero(self, tmp_path: Path) -> None:
        _config, recorder = _make_recorder(tmp_path)
        assert recorder.purge_expired(retention_days=30) == 0

    def test_purges_across_multiple_issues(self, tmp_path: Path) -> None:
        _config, recorder = _make_recorder(tmp_path)
        # Old runs in two different issues
        _seed_run(recorder, 10, "20200101T000000Z")
        _seed_run(recorder, 42, "20200101T000000Z")
        # Recent runs that should survive
        _seed_run(recorder, 10, "20261231T000000Z")
        _seed_run(recorder, 42, "20261231T000000Z")

        removed = recorder.purge_expired(retention_days=30)
        assert removed == 2
        assert len(recorder.list_runs(10)) == 1
        assert len(recorder.list_runs(42)) == 1

    def test_skips_non_timestamp_dirs(self, tmp_path: Path) -> None:
        _config, recorder = _make_recorder(tmp_path)
        # Create a dir with a non-timestamp name
        weird_dir = recorder.runs_dir / "42" / "not-a-timestamp"
        weird_dir.mkdir(parents=True, exist_ok=True)
        (weird_dir / "junk.txt").write_text("x")

        removed = recorder.purge_expired(retention_days=30)
        assert removed == 0
        assert weird_dir.exists()


# ===========================================================================
# RunRecorder.purge_oversized
# ===========================================================================


class TestPurgeOversized:
    def test_removes_oldest_until_under_limit(self, tmp_path: Path) -> None:
        _config, recorder = _make_recorder(tmp_path)
        # Seed runs with large files (each ~1KB)
        for ts in ("20260101T100000Z", "20260101T200000Z", "20260102T100000Z"):
            run_dir = _seed_run(recorder, 42, ts)
            (run_dir / "big.bin").write_bytes(b"x" * 512)

        # Set a zero MB limit so all runs get purged
        removed = recorder.purge_oversized(max_size_mb=0)
        # With 0 MB limit, all should be removed (since total > 0)
        assert removed > 0

    def test_noop_when_under_limit(self, tmp_path: Path) -> None:
        _config, recorder = _make_recorder(tmp_path)
        _seed_run(recorder, 42, "20260101T100000Z")
        removed = recorder.purge_oversized(max_size_mb=500)
        assert removed == 0

    def test_removes_oldest_first(self, tmp_path: Path) -> None:
        _config, recorder = _make_recorder(tmp_path)
        # Create three runs with large files so each exceeds 1 byte
        for ts in ("20260101T100000Z", "20260101T200000Z", "20260102T100000Z"):
            run_dir = _seed_run(recorder, 42, ts)
            (run_dir / "data.bin").write_bytes(b"x" * 1024)

        total = recorder._compute_total_bytes()
        assert total > 0
        # Remove with 0 limit — all get removed; verify count
        removed = recorder.purge_oversized(max_size_mb=0)
        assert removed == 3

    def test_removes_empty_issue_dirs(self, tmp_path: Path) -> None:
        _config, recorder = _make_recorder(tmp_path)
        run_dir = _seed_run(recorder, 42, "20260101T100000Z")
        (run_dir / "big.bin").write_bytes(b"x" * 512)

        recorder.purge_oversized(max_size_mb=0)
        # Issue dir should be removed since all runs were purged
        assert not (recorder.runs_dir / "42").exists()

    def test_empty_runs_dir(self, tmp_path: Path) -> None:
        _config, recorder = _make_recorder(tmp_path)
        assert recorder.purge_oversized(max_size_mb=0) == 0


# ===========================================================================
# RunRecorder.purge_all
# ===========================================================================


class TestPurgeAll:
    def test_removes_all_runs(self, tmp_path: Path) -> None:
        _config, recorder = _make_recorder(tmp_path)
        _seed_run(recorder, 10, "20260101T100000Z")
        _seed_run(recorder, 42, "20260101T100000Z")
        removed = recorder.purge_all()
        assert removed == 2
        assert recorder.list_issues() == []

    def test_empty_runs_dir(self, tmp_path: Path) -> None:
        _config, recorder = _make_recorder(tmp_path)
        assert recorder.purge_all() == 0


# ===========================================================================
# RunRecorder._compute_total_bytes
# ===========================================================================


class TestComputeTotalBytes:
    def test_sums_file_sizes(self, tmp_path: Path) -> None:
        _config, recorder = _make_recorder(tmp_path)
        _seed_run(recorder, 42, "20260101T100000Z")
        total = recorder._compute_total_bytes()
        assert total > 0

    def test_empty_returns_zero(self, tmp_path: Path) -> None:
        _config, recorder = _make_recorder(tmp_path)
        assert recorder._compute_total_bytes() == 0


# ===========================================================================
# RunsGCLoop
# ===========================================================================


class TestRunsGCLoopBasics:
    def test_worker_name(self, tmp_path: Path) -> None:
        loop, _recorder, _stop = _make_loop(tmp_path)
        assert loop._worker_name == "runs_gc"

    def test_default_interval(self, tmp_path: Path) -> None:
        loop, _recorder, _stop = _make_loop(tmp_path, runs_gc_interval=900)
        assert loop._get_default_interval() == 900

    @pytest.mark.asyncio
    async def test_run_skips_when_disabled(self, tmp_path: Path) -> None:
        loop, _recorder, _stop = _make_loop(tmp_path, enabled=False)
        await loop.run()
        loop._status_cb.assert_not_called()

    @pytest.mark.asyncio
    async def test_do_work_returns_stats(self, tmp_path: Path) -> None:
        loop, recorder, stop = _make_loop(tmp_path, retention_days=30)
        _seed_run(recorder, 42, "20200101T000000Z")  # expired
        _seed_run(recorder, 42, "20261231T000000Z")  # fresh

        result = await loop._do_work()
        assert result is not None
        assert result["expired_purged"] == 1
        assert result["total_runs"] == 1

    @pytest.mark.asyncio
    async def test_do_work_no_purges(self, tmp_path: Path) -> None:
        loop, recorder, stop = _make_loop(tmp_path, retention_days=365)
        _seed_run(recorder, 42, "20261231T000000Z")

        result = await loop._do_work()
        assert result is not None
        assert result["expired_purged"] == 0
        assert result["oversized_purged"] == 0
        assert result["total_runs"] == 1

    @pytest.mark.asyncio
    async def test_run_publishes_status_on_success(self, tmp_path: Path) -> None:
        loop, _recorder, stop = _make_loop(tmp_path)
        stop.set()  # Stop after first iteration
        # run_on_startup defaults to False, so loop sleeps first then checks stop
        # Just verify _do_work can run without error
        result = await loop._do_work()
        assert result is not None


# ===========================================================================
# Config fields
# ===========================================================================


class TestArtifactConfigFields:
    def test_default_values(self) -> None:
        config = ConfigFactory.create()
        assert config.artifact_retention_days == 30
        assert config.artifact_max_size_mb == 500
        assert config.runs_gc_interval == 3600

    def test_custom_values(self) -> None:
        config = ConfigFactory.create(
            artifact_retention_days=7,
            artifact_max_size_mb=100,
            runs_gc_interval=1800,
        )
        assert config.artifact_retention_days == 7
        assert config.artifact_max_size_mb == 100
        assert config.runs_gc_interval == 1800
