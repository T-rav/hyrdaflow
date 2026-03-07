"""Integration tests for file I/O operations.

Tests real disk I/O for:
- file_util.py atomic writes and file locking
- state.py crash recovery persistence
- memory.py digest file management
- manifest.py project manifest detection and persistence
- update_check.py cache file management
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from file_util import append_jsonl, atomic_write, file_lock
from state import StateTracker
from tests.helpers import ConfigFactory

# ---------------------------------------------------------------------------
# file_util: atomic_write integration
# ---------------------------------------------------------------------------


class TestAtomicWriteIntegration:
    """Integration tests verifying real atomic write behaviour on disk."""

    def test_concurrent_writes_produce_consistent_file(self, tmp_path: Path) -> None:
        """Multiple threads writing to the same file should each produce valid content."""
        target = tmp_path / "shared.json"
        results: list[bool] = []
        barrier = threading.Barrier(4)

        def writer(value: int) -> None:
            barrier.wait()
            data = json.dumps({"writer": value, "payload": "x" * 100})
            atomic_write(target, data)
            results.append(True)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert all(results)
        # File must contain valid JSON from one of the writers
        content = json.loads(target.read_text())
        assert "writer" in content
        assert content["writer"] in range(4)

    def test_atomic_write_survives_rapid_overwrites(self, tmp_path: Path) -> None:
        """Rapid sequential writes should never leave a corrupt file."""
        target = tmp_path / "rapid.json"
        for i in range(50):
            atomic_write(target, json.dumps({"iteration": i}))

        content = json.loads(target.read_text())
        assert content["iteration"] == 49

    def test_no_temp_files_left_after_concurrent_writes(self, tmp_path: Path) -> None:
        """Temp files should be cleaned up even under concurrent writes."""
        target = tmp_path / "clean.txt"
        barrier = threading.Barrier(4)

        def writer(value: int) -> None:
            barrier.wait()
            atomic_write(target, f"writer-{value}")

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        temps = list(tmp_path.glob(".clean-*.tmp"))
        assert temps == []

    def test_atomic_write_with_large_data(self, tmp_path: Path) -> None:
        """Atomic write handles large payloads correctly."""
        target = tmp_path / "large.json"
        large_data = json.dumps({"data": "x" * 1_000_000})
        atomic_write(target, large_data)
        assert target.read_text() == large_data


# ---------------------------------------------------------------------------
# file_util: append_jsonl integration
# ---------------------------------------------------------------------------


class TestAppendJsonlIntegration:
    """Integration tests for JSONL append operations."""

    def test_multiple_appends_produce_valid_jsonl(self, tmp_path: Path) -> None:
        """Each append should produce a complete, parseable line."""
        target = tmp_path / "events.jsonl"
        records = [{"event": i, "ts": time.time()} for i in range(20)]
        for record in records:
            append_jsonl(target, json.dumps(record))

        lines = target.read_text().strip().splitlines()
        assert len(lines) == 20
        for i, line in enumerate(lines):
            parsed = json.loads(line)
            assert parsed["event"] == i

    def test_append_to_nonexistent_nested_path(self, tmp_path: Path) -> None:
        """Appending to a deeply nested non-existent path creates all parents."""
        target = tmp_path / "a" / "b" / "c" / "d" / "log.jsonl"
        append_jsonl(target, '{"deep": true}')
        assert json.loads(target.read_text().strip()) == {"deep": True}


# ---------------------------------------------------------------------------
# file_util: file_lock integration
# ---------------------------------------------------------------------------


class TestFileLockIntegration:
    """Integration tests for advisory file locking."""

    def test_lock_serializes_access(self, tmp_path: Path) -> None:
        """Two threads using the same lock should not overlap."""
        lock_path = tmp_path / "test.lock"
        counter_file = tmp_path / "counter.txt"
        counter_file.write_text("0")

        def increment() -> None:
            with file_lock(lock_path):
                val = int(counter_file.read_text())
                time.sleep(0.01)  # small delay to expose races
                counter_file.write_text(str(val + 1))

        threads = [threading.Thread(target=increment) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert int(counter_file.read_text()) == 10


# ---------------------------------------------------------------------------
# state.py: StateTracker persistence
# ---------------------------------------------------------------------------


class TestStateTrackerIntegration:
    """Integration tests for StateTracker file I/O."""

    def test_save_and_reload_round_trip(self, tmp_path: Path) -> None:
        """Mutations should survive save/reload cycle."""
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker.mark_issue(42, "success")
        tracker.set_worktree(42, "/tmp/wt-42")
        tracker.set_branch(42, "issue-42")
        tracker.mark_pr(100, "approved")
        tracker.save()

        # Reload from disk
        tracker2 = StateTracker(state_file)
        data = tracker2.to_dict()
        assert data["processed_issues"]["42"] == "success"
        assert data["active_worktrees"]["42"] == "/tmp/wt-42"
        assert data["active_branches"]["42"] == "issue-42"
        assert data["reviewed_prs"]["100"] == "approved"

    def test_state_file_is_valid_json(self, tmp_path: Path) -> None:
        """The state file should always be valid JSON."""
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker.mark_issue(1, "pending")
        tracker.save()

        content = state_file.read_text()
        parsed = json.loads(content)
        assert isinstance(parsed, dict)

    def test_corrupt_state_file_recovery(self, tmp_path: Path) -> None:
        """A corrupt state file should be handled gracefully on load."""
        state_file = tmp_path / "state.json"
        state_file.write_text("{invalid json content!!!")

        # Should not raise — resets to defaults
        tracker = StateTracker(state_file)
        assert tracker.get_active_worktrees() == {}

    def test_missing_state_file_initializes_fresh(self, tmp_path: Path) -> None:
        """A missing state file should initialize with default state."""
        state_file = tmp_path / "nonexistent" / "state.json"
        tracker = StateTracker(state_file)
        tracker.mark_issue(1, "test")
        tracker.save()

        assert state_file.exists()
        assert json.loads(state_file.read_text())

    def test_rapid_save_cycles(self, tmp_path: Path) -> None:
        """Rapid save cycles should produce consistent state."""
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        for i in range(100):
            tracker.mark_issue(i, f"status-{i}")
            tracker.save()

        # Reload and verify all 100 issues persisted
        tracker2 = StateTracker(state_file)
        data = tracker2.to_dict()
        assert len(data["processed_issues"]) == 100
        assert data["processed_issues"]["99"] == "status-99"

    def test_hitl_state_persistence(self, tmp_path: Path) -> None:
        """HITL-related state should persist across reloads."""
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker.set_hitl_origin(42, "hydraflow-review")
        tracker.set_hitl_cause(42, "CI failure")
        tracker.set_hitl_summary(42, "Build timed out")
        tracker.save()

        tracker2 = StateTracker(state_file)
        data = tracker2.to_dict()
        assert data["hitl_origins"]["42"] == "hydraflow-review"
        assert data["hitl_causes"]["42"] == "CI failure"
        assert data["hitl_summaries"]["42"]["summary"] == "Build timed out"


# ---------------------------------------------------------------------------
# manifest.py: project manifest detection and persistence
# ---------------------------------------------------------------------------


class TestManifestIntegration:
    """Integration tests for manifest detection with real file structures."""

    def test_detect_python_project(self, tmp_path: Path) -> None:
        """Detect Python markers from real file structure."""
        from manifest import detect_languages, detect_test_frameworks

        (tmp_path / "pyproject.toml").write_text(
            "[project]\nname = 'myapp'\n\n[tool.pytest.ini_options]\n"
        )
        (tmp_path / "conftest.py").touch()
        (tmp_path / "tests").mkdir()

        langs = detect_languages(tmp_path)
        assert "python" in langs

        frameworks = detect_test_frameworks(tmp_path)
        assert "pytest" in frameworks

    def test_detect_mixed_project(self, tmp_path: Path) -> None:
        """Detect both Python and JS markers."""
        from manifest import detect_language, detect_languages

        (tmp_path / "pyproject.toml").touch()
        (tmp_path / "package.json").write_text("{}")

        langs = detect_languages(tmp_path)
        assert "python" in langs
        assert "javascript" in langs
        assert detect_language(tmp_path) == "mixed"

    def test_detect_build_systems(self, tmp_path: Path) -> None:
        """Detect build systems from marker files."""
        from manifest import detect_build_systems

        (tmp_path / "Makefile").touch()
        (tmp_path / "pyproject.toml").touch()

        systems = detect_build_systems(tmp_path)
        assert "make" in systems
        assert "pip" in systems

    def test_detect_ci_systems(self, tmp_path: Path) -> None:
        """Detect CI from directory structure."""
        from manifest import detect_ci_systems

        (tmp_path / ".github" / "workflows").mkdir(parents=True)

        systems = detect_ci_systems(tmp_path)
        assert "github-actions" in systems

    def test_detect_npm_workspaces(self, tmp_path: Path) -> None:
        """Detect npm workspaces from package.json."""
        from manifest import detect_sub_projects

        (tmp_path / "package.json").write_text(
            json.dumps({"workspaces": ["packages/*", "apps/*"]})
        )

        subs = detect_sub_projects(tmp_path)
        names = [s["name"] for s in subs]
        assert "packages/*" in names
        assert "apps/*" in names

    def test_detect_key_docs(self, tmp_path: Path) -> None:
        """Detect common documentation files."""
        from manifest import detect_key_docs

        (tmp_path / "README.md").touch()
        (tmp_path / "LICENSE").touch()
        (tmp_path / "CLAUDE.md").touch()

        docs = detect_key_docs(tmp_path)
        assert "README.md" in docs
        assert "LICENSE" in docs
        assert "CLAUDE.md" in docs

    def test_build_manifest_markdown(self, tmp_path: Path) -> None:
        """Build full manifest from a real directory structure."""
        from manifest import build_manifest_markdown

        (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
        (tmp_path / "Makefile").touch()
        (tmp_path / ".github" / "workflows").mkdir(parents=True)
        (tmp_path / "README.md").touch()

        md = build_manifest_markdown(tmp_path)
        assert "## Project Manifest" in md
        assert "python" in md
        assert "make" in md
        assert "pytest" in md
        assert "github-actions" in md
        assert "README.md" in md

    def test_manifest_manager_write_and_read(self, tmp_path: Path) -> None:
        """ProjectManifestManager.write() persists and returns a hash."""
        from manifest import ProjectManifestManager

        config = ConfigFactory.create(repo_root=tmp_path)
        manager = ProjectManifestManager(config)

        content = "## Project Manifest\n**Languages:** python\n"
        digest_hash = manager.write(content)

        assert manager.manifest_path.read_text() == content
        assert len(digest_hash) == 16
        assert not manager.needs_refresh(digest_hash)

    def test_manifest_manager_refresh(self, tmp_path: Path) -> None:
        """ProjectManifestManager.refresh() scans and persists the manifest."""
        from manifest import ProjectManifestManager

        (tmp_path / "pyproject.toml").touch()
        config = ConfigFactory.create(repo_root=tmp_path)
        manager = ProjectManifestManager(config)

        result = manager.refresh()
        assert "python" in result.content
        assert manager.manifest_path.exists()
        assert len(result.digest_hash) == 16

    def test_load_project_manifest(self, tmp_path: Path) -> None:
        """load_project_manifest reads persisted manifest from disk."""
        from manifest import load_project_manifest

        config = ConfigFactory.create(repo_root=tmp_path)
        manifest_path = config.data_path("manifest", "manifest.md")
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text("## Project Manifest\n**Languages:** python\n")

        content = load_project_manifest(config)
        assert "python" in content

    def test_load_project_manifest_truncation(self, tmp_path: Path) -> None:
        """load_project_manifest truncates content exceeding max_chars."""
        from manifest import load_project_manifest

        config = ConfigFactory.create(repo_root=tmp_path, max_manifest_prompt_chars=200)
        manifest_path = config.data_path("manifest", "manifest.md")
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text("x" * 500)

        content = load_project_manifest(config)
        assert len(content) < 500
        assert "truncated" in content

    def test_legacy_manifest_migration(self, tmp_path: Path) -> None:
        """Legacy manifest in memory/ should be migrated to manifest/."""
        from manifest import load_project_manifest

        config = ConfigFactory.create(repo_root=tmp_path)
        legacy_path = config.data_path("memory", "manifest.md")
        legacy_path.parent.mkdir(parents=True, exist_ok=True)
        legacy_path.write_text("## Old Manifest\n")

        content = load_project_manifest(config)
        assert "Old Manifest" in content
        # New location should exist
        assert config.data_path("manifest", "manifest.md").exists()


# ---------------------------------------------------------------------------
# memory.py: digest file management
# ---------------------------------------------------------------------------


class TestMemoryDigestIntegration:
    """Integration tests for memory digest I/O."""

    def test_load_memory_digest_from_disk(self, tmp_path: Path) -> None:
        """load_memory_digest reads a real digest file."""
        from memory import load_memory_digest

        config = ConfigFactory.create(repo_root=tmp_path)
        digest_path = config.data_path("memory", "digest.md")
        digest_path.parent.mkdir(parents=True, exist_ok=True)
        digest_path.write_text("## Accumulated Learnings\nsome content\n")

        content = load_memory_digest(config)
        assert "Accumulated Learnings" in content

    def test_load_memory_digest_missing_file(self, tmp_path: Path) -> None:
        """load_memory_digest returns empty string for missing file."""
        from memory import load_memory_digest

        config = ConfigFactory.create(repo_root=tmp_path)
        assert load_memory_digest(config) == ""

    def test_load_memory_digest_truncation(self, tmp_path: Path) -> None:
        """load_memory_digest caps content at max_memory_prompt_chars."""
        from memory import load_memory_digest

        config = ConfigFactory.create(repo_root=tmp_path, max_memory_prompt_chars=500)
        digest_path = config.data_path("memory", "digest.md")
        digest_path.parent.mkdir(parents=True, exist_ok=True)
        digest_path.write_text("x" * 2000)

        content = load_memory_digest(config)
        assert len(content) < 2000
        assert "truncated" in content

    def test_memory_item_file_write_and_prune(self, tmp_path: Path) -> None:
        """MemorySyncWorker writes item files and prunes stale ones."""
        from memory import MemorySyncWorker

        config = ConfigFactory.create(repo_root=tmp_path)
        state = StateTracker(tmp_path / "state.json")
        from events import EventBus

        bus = EventBus()

        worker = MemorySyncWorker(config, state, bus)

        # Write items manually (simulating what sync does)
        items_dir = config.data_path("memory", "items")
        items_dir.mkdir(parents=True, exist_ok=True)
        (items_dir / "10.md").write_text("learning for issue 10")
        (items_dir / "20.md").write_text("learning for issue 20")
        (items_dir / "30.md").write_text("learning for issue 30")

        # Prune: only issues 10 and 30 are active
        pruned = worker._prune_stale_items([10, 30])
        assert pruned == 1
        assert (items_dir / "10.md").exists()
        assert not (items_dir / "20.md").exists()
        assert (items_dir / "30.md").exists()

    def test_adr_source_ids_persistence(self, tmp_path: Path) -> None:
        """ADR source IDs should round-trip through save/load."""
        from memory import MemorySyncWorker

        config = ConfigFactory.create(repo_root=tmp_path)
        state = StateTracker(tmp_path / "state.json")
        from events import EventBus

        bus = EventBus()

        worker = MemorySyncWorker(config, state, bus)

        # Save some source IDs
        worker._save_adr_source_ids({100, 200, 300})

        # Load and verify
        loaded = worker._load_adr_source_ids()
        assert loaded == {100, 200, 300}

    def test_adr_source_ids_missing_file(self, tmp_path: Path) -> None:
        """Loading ADR source IDs from nonexistent file returns empty set."""
        from memory import MemorySyncWorker

        config = ConfigFactory.create(repo_root=tmp_path)
        state = StateTracker(tmp_path / "state.json")
        from events import EventBus

        bus = EventBus()

        worker = MemorySyncWorker(config, state, bus)
        assert worker._load_adr_source_ids() == set()

    def test_write_digest_creates_file(self, tmp_path: Path) -> None:
        """_write_digest creates the digest file atomically."""
        from memory import MemorySyncWorker

        config = ConfigFactory.create(repo_root=tmp_path)
        state = StateTracker(tmp_path / "state.json")
        from events import EventBus

        bus = EventBus()

        worker = MemorySyncWorker(config, state, bus)
        worker._write_digest("## Test Digest\ncontent here\n")

        digest_path = config.data_path("memory", "digest.md")
        assert digest_path.exists()
        assert "Test Digest" in digest_path.read_text()


# ---------------------------------------------------------------------------
# update_check.py: cache file I/O
# ---------------------------------------------------------------------------


class TestUpdateCheckCacheIntegration:
    """Integration tests for update_check cache file operations."""

    def test_write_and_read_cache_round_trip(self, tmp_path: Path) -> None:
        """Cache data should survive write/read round-trip."""
        from hf_cli.update_check import _read_cache, _write_cache

        cache_path = tmp_path / "cache.json"
        payload = {
            "checked_at": 1700000000,
            "current_version": "1.0.0",
            "latest_version": "2.0.0",
        }
        _write_cache(payload, cache_path)
        loaded = _read_cache(cache_path)
        assert loaded == payload

    def test_cache_creates_parent_directories(self, tmp_path: Path) -> None:
        """Writing cache should create parent dirs."""
        from hf_cli.update_check import _write_cache

        cache_path = tmp_path / "nested" / "deep" / "cache.json"
        _write_cache({"version": "1.0.0"}, cache_path)
        assert cache_path.exists()

    def test_load_cached_result_with_real_file(self, tmp_path: Path) -> None:
        """load_cached_update_result works with a real cache file."""
        from hf_cli.update_check import _write_cache, load_cached_update_result

        cache_path = tmp_path / "cache.json"
        _write_cache(
            {"current_version": "1.0.0", "latest_version": "2.0.0"},
            cache_path,
        )

        result = load_cached_update_result(current_version="1.0.0", path=cache_path)
        assert result is not None
        assert result.update_available is True
        assert result.latest_version == "2.0.0"

    def test_cache_handles_corrupt_file(self, tmp_path: Path) -> None:
        """Corrupt cache file should return None gracefully."""
        from hf_cli.update_check import _read_cache

        cache_path = tmp_path / "cache.json"
        cache_path.write_text("not valid json{{{")
        assert _read_cache(cache_path) is None

    def test_cache_handles_non_dict_json(self, tmp_path: Path) -> None:
        """Cache with non-dict JSON should return None."""
        from hf_cli.update_check import _read_cache

        cache_path = tmp_path / "cache.json"
        cache_path.write_text("[1, 2, 3]")
        assert _read_cache(cache_path) is None
