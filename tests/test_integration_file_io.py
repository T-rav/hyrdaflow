"""Integration tests for file I/O operations.

Covers: file_util.py (atomic_write, append_jsonl, file_lock),
        state.py (save/load roundtrip, crash recovery, concurrent mutations),
        memory.py (digest persistence, load_memory_digest),
        manifest.py (detect_*, build_manifest_markdown, ProjectManifestManager).
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# file_util.py — atomic_write
# ---------------------------------------------------------------------------


class TestAtomicWrite:
    """Integration tests for file_util.atomic_write."""

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        from file_util import atomic_write

        target = tmp_path / "a" / "b" / "c" / "data.txt"
        atomic_write(target, "hello")
        assert target.read_text() == "hello"

    def test_atomic_replacement(self, tmp_path: Path) -> None:
        from file_util import atomic_write

        target = tmp_path / "data.txt"
        target.write_text("original")
        atomic_write(target, "replaced")
        assert target.read_text() == "replaced"

    def test_no_leftover_temp_files_on_success(self, tmp_path: Path) -> None:
        from file_util import atomic_write

        target = tmp_path / "data.txt"
        atomic_write(target, "content")
        temps = [f for f in tmp_path.iterdir() if f.suffix == ".tmp"]
        assert temps == []

    def test_no_leftover_temp_files_on_failure(self, tmp_path: Path) -> None:
        from file_util import atomic_write

        target = tmp_path / "data.txt"
        target.write_text("original")

        class BoomError(Exception):
            pass

        import os
        import unittest.mock

        def failing_fdopen(fd: int, mode: str) -> None:  # type: ignore[return]
            os.close(fd)
            raise BoomError("simulated write failure")

        with (
            unittest.mock.patch("file_util.os.fdopen", failing_fdopen),
            pytest.raises(BoomError),
        ):
            atomic_write(target, "new content")

        # Original content preserved
        assert target.read_text() == "original"
        # No leftover temp files
        temps = [f for f in tmp_path.iterdir() if f.suffix == ".tmp"]
        assert temps == []

    def test_overwrites_existing_content(self, tmp_path: Path) -> None:
        from file_util import atomic_write

        target = tmp_path / "data.txt"
        atomic_write(target, "first")
        atomic_write(target, "second")
        assert target.read_text() == "second"


# ---------------------------------------------------------------------------
# file_util.py — append_jsonl
# ---------------------------------------------------------------------------


class TestAppendJsonl:
    """Integration tests for file_util.append_jsonl."""

    def test_appends_multiple_lines(self, tmp_path: Path) -> None:
        from file_util import append_jsonl

        target = tmp_path / "events.jsonl"
        append_jsonl(target, '{"a": 1}')
        append_jsonl(target, '{"b": 2}')
        lines = target.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0]) == {"a": 1}
        assert json.loads(lines[1]) == {"b": 2}

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        from file_util import append_jsonl

        target = tmp_path / "sub" / "dir" / "log.jsonl"
        append_jsonl(target, '{"x": 1}')
        assert target.exists()


# ---------------------------------------------------------------------------
# file_util.py — file_lock
# ---------------------------------------------------------------------------


class TestFileLock:
    """Integration tests for file_util.file_lock."""

    def test_exclusive_access(self, tmp_path: Path) -> None:
        """Concurrent threads holding the lock never interleave critical sections.

        Each worker performs a non-atomic read-modify-write on a shared counter
        file with a deliberate yield point inside the critical section. Without
        proper mutual exclusion the threads would read the same stale value and
        the final count would be less than the expected total.

        A ``threading.Event`` (never set) with ``timeout=0`` is used instead of
        ``time.sleep(0.01)`` to remove the fixed wall-clock delay.  Note that
        ``Event.wait(timeout=0)`` completes in ~2–3 µs (well below the 5 ms GIL
        switch interval), so it does not guarantee a thread context switch; the
        test relies on natural OS-level thread interleaving via file-I/O GIL
        releases and the GIL preemption timer to expose any missing mutual
        exclusion.
        """
        from file_util import file_lock

        lock_path = tmp_path / "test.lock"
        counter_path = tmp_path / "counter.txt"
        counter_path.write_text("0")

        iterations = 10
        # An Event that is never set; .wait(timeout=0) avoids a fixed wall-clock
        # wait.  It completes in ~2-3 µs and does not guarantee a GIL switch,
        # so thread interleaving relies on natural OS scheduling and file-I/O.
        yield_point = threading.Event()

        def worker() -> None:
            for _ in range(iterations):
                with file_lock(lock_path):
                    # Non-atomic read-modify-write: without mutual exclusion
                    # another thread could read the same value before we write.
                    current = int(counter_path.read_text())
                    yield_point.wait(
                        timeout=0
                    )  # no wall-clock delay; no CPU yield guaranteed
                    counter_path.write_text(str(current + 1))

        threads = [threading.Thread(target=worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 3 threads × 10 iterations = 30.  Any interleaving that bypasses mutual
        # exclusion would produce a smaller count due to lost read-modify-write updates.
        assert int(counter_path.read_text()) == 3 * iterations

    def test_lock_creates_parent_dirs(self, tmp_path: Path) -> None:
        from file_util import file_lock

        lock_path = tmp_path / "nested" / "dir" / "lock"
        with file_lock(lock_path):
            assert lock_path.parent.exists()


# ---------------------------------------------------------------------------
# state.py — StateTracker persistence roundtrip
# ---------------------------------------------------------------------------


class TestStateTrackerPersistence:
    """Integration tests for StateTracker save/load with real disk I/O."""

    def test_save_load_roundtrip(self, tmp_path: Path) -> None:
        from state import StateTracker

        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker.mark_issue(42, "planned")
        tracker.set_worktree(42, "/tmp/wt/issue-42")
        tracker.set_branch(42, "agent/issue-42")
        tracker.mark_pr(101, "approved")
        tracker.set_hitl_origin(42, "hydraflow-review")
        tracker.set_hitl_cause(42, "CI failure")

        # Reload from the same file
        tracker2 = StateTracker(state_file)
        data = tracker2.to_dict()
        assert data["processed_issues"]["42"] == "planned"
        assert tracker2.get_active_worktrees() == {42: "/tmp/wt/issue-42"}
        assert tracker2.get_branch(42) == "agent/issue-42"
        assert data["reviewed_prs"]["101"] == "approved"
        assert tracker2.get_hitl_origin(42) == "hydraflow-review"
        assert tracker2.get_hitl_cause(42) == "CI failure"

    def test_corrupted_json_resets_gracefully(self, tmp_path: Path) -> None:
        from state import StateTracker

        state_file = tmp_path / "state.json"
        state_file.write_text("{invalid json!!")

        tracker = StateTracker(state_file)
        # Should have reset to defaults
        assert tracker.get_active_worktrees() == {}
        assert tracker.get_branch(1) is None

    def test_empty_file_resets(self, tmp_path: Path) -> None:
        from state import StateTracker

        state_file = tmp_path / "state.json"
        state_file.write_text("")

        tracker = StateTracker(state_file)
        assert tracker.get_active_worktrees() == {}

    def test_non_object_json_resets(self, tmp_path: Path) -> None:
        from state import StateTracker

        state_file = tmp_path / "state.json"
        state_file.write_text("[1, 2, 3]")

        tracker = StateTracker(state_file)
        assert tracker.get_active_worktrees() == {}

    def test_last_updated_set_on_save(self, tmp_path: Path) -> None:
        from state import StateTracker

        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker.mark_issue(1, "done")

        raw = json.loads(state_file.read_text())
        assert "last_updated" in raw
        assert raw["last_updated"] is not None

    def test_multiple_domains_persist_independently(self, tmp_path: Path) -> None:
        from state import StateTracker

        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)

        tracker.mark_issue(1, "planned")
        tracker.set_worktree(2, "/wt/2")
        tracker.set_branch(3, "branch-3")
        tracker.mark_pr(4, "reviewed")

        tracker2 = StateTracker(state_file)
        data = tracker2.to_dict()
        assert data["processed_issues"]["1"] == "planned"
        assert data["active_worktrees"]["2"] == "/wt/2"
        assert data["active_branches"]["3"] == "branch-3"
        assert data["reviewed_prs"]["4"] == "reviewed"


# ---------------------------------------------------------------------------
# memory.py — digest persistence
# ---------------------------------------------------------------------------


class TestMemoryDigestPersistence:
    """Integration tests for memory digest file operations."""

    def test_load_memory_digest_missing_file(self, tmp_path: Path) -> None:
        from memory import load_memory_digest
        from tests.helpers import ConfigFactory

        config = ConfigFactory.create(repo_root=tmp_path)
        assert load_memory_digest(config) == ""

    def test_load_memory_digest_roundtrip(self, tmp_path: Path) -> None:
        from file_util import atomic_write
        from memory import load_memory_digest
        from tests.helpers import ConfigFactory

        config = ConfigFactory.create(repo_root=tmp_path)
        digest_path = config.data_path("memory", "digest.md")
        digest_path.parent.mkdir(parents=True, exist_ok=True)
        content = "# Digest\n\n- Learning 1\n- Learning 2\n"
        atomic_write(digest_path, content)
        assert load_memory_digest(config) == content

    def test_load_memory_digest_truncates(self, tmp_path: Path) -> None:
        from file_util import atomic_write
        from memory import load_memory_digest
        from tests.helpers import ConfigFactory

        config = ConfigFactory.create(repo_root=tmp_path, max_memory_prompt_chars=500)
        digest_path = config.data_path("memory", "digest.md")
        digest_path.parent.mkdir(parents=True, exist_ok=True)
        long_content = "A" * 1000
        atomic_write(digest_path, long_content)
        result = load_memory_digest(config)
        assert len(result) < 1000
        assert result.endswith("…(truncated)")

    def test_load_memory_digest_empty_file(self, tmp_path: Path) -> None:
        from memory import load_memory_digest
        from tests.helpers import ConfigFactory

        config = ConfigFactory.create(repo_root=tmp_path)
        digest_path = config.data_path("memory", "digest.md")
        digest_path.parent.mkdir(parents=True, exist_ok=True)
        digest_path.write_text("   \n  ")
        assert load_memory_digest(config) == ""


# ---------------------------------------------------------------------------
# manifest.py — detection helpers
# ---------------------------------------------------------------------------


class TestManifestDetection:
    """Integration tests for manifest.py detection functions on real directories."""

    def test_detect_languages_python(self, tmp_path: Path) -> None:
        from manifest import detect_languages

        (tmp_path / "pyproject.toml").write_text("[project]\n")
        assert "python" in detect_languages(tmp_path)

    def test_detect_languages_javascript(self, tmp_path: Path) -> None:
        from manifest import detect_languages

        (tmp_path / "package.json").write_text("{}\n")
        assert "javascript" in detect_languages(tmp_path)

    def test_detect_languages_multiple(self, tmp_path: Path) -> None:
        from manifest import detect_languages

        (tmp_path / "pyproject.toml").write_text("[project]\n")
        (tmp_path / "Cargo.toml").write_text("[package]\n")
        langs = detect_languages(tmp_path)
        assert "python" in langs
        assert "rust" in langs

    def test_detect_languages_empty_repo(self, tmp_path: Path) -> None:
        from manifest import detect_languages

        assert detect_languages(tmp_path) == []

    def test_detect_language_mixed(self, tmp_path: Path) -> None:
        from manifest import detect_language

        (tmp_path / "pyproject.toml").write_text("[project]\n")
        (tmp_path / "package.json").write_text("{}\n")
        assert detect_language(tmp_path) == "mixed"

    def test_detect_language_unknown(self, tmp_path: Path) -> None:
        from manifest import detect_language

        assert detect_language(tmp_path) == "unknown"

    def test_detect_build_systems(self, tmp_path: Path) -> None:
        from manifest import detect_build_systems

        (tmp_path / "Makefile").write_text("all:\n")
        (tmp_path / "pyproject.toml").write_text("[project]\n")
        systems = detect_build_systems(tmp_path)
        assert "make" in systems
        assert "pip" in systems

    def test_detect_test_frameworks_pytest_from_pyproject(self, tmp_path: Path) -> None:
        from manifest import detect_test_frameworks

        (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
        assert "pytest" in detect_test_frameworks(tmp_path)

    def test_detect_test_frameworks_pytest_from_conftest(self, tmp_path: Path) -> None:
        from manifest import detect_test_frameworks

        (tmp_path / "conftest.py").write_text("")
        assert "pytest" in detect_test_frameworks(tmp_path)

    def test_detect_test_frameworks_go(self, tmp_path: Path) -> None:
        from manifest import detect_test_frameworks

        (tmp_path / "go.mod").write_text("module example\n")
        assert "go-test" in detect_test_frameworks(tmp_path)

    def test_detect_ci_systems(self, tmp_path: Path) -> None:
        from manifest import detect_ci_systems

        wf = tmp_path / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "ci.yml").write_text("name: CI\n")
        assert "github-actions" in detect_ci_systems(tmp_path)

    def test_detect_key_docs(self, tmp_path: Path) -> None:
        from manifest import detect_key_docs

        (tmp_path / "README.md").write_text("# Hello\n")
        (tmp_path / "LICENSE").write_text("MIT\n")
        docs = detect_key_docs(tmp_path)
        assert "README.md" in docs
        assert "LICENSE" in docs

    def test_detect_sub_projects_npm_workspaces(self, tmp_path: Path) -> None:
        from manifest import detect_sub_projects

        (tmp_path / "package.json").write_text(
            json.dumps({"workspaces": ["packages/a", "packages/b"]})
        )
        subs = detect_sub_projects(tmp_path)
        names = [s["name"] for s in subs]
        assert "packages/a" in names
        assert "packages/b" in names


# ---------------------------------------------------------------------------
# manifest.py — build_manifest_markdown
# ---------------------------------------------------------------------------


class TestBuildManifestMarkdown:
    """Integration tests for build_manifest_markdown with real FS scanning."""

    def test_produces_valid_markdown(self, tmp_path: Path) -> None:
        from manifest import build_manifest_markdown

        (tmp_path / "pyproject.toml").write_text("[project]\n")
        (tmp_path / "Makefile").write_text("all:\n")
        md = build_manifest_markdown(tmp_path)
        assert "## Project Manifest" in md
        assert "python" in md
        assert "make" in md

    def test_empty_repo_shows_unknown(self, tmp_path: Path) -> None:
        from manifest import build_manifest_markdown

        md = build_manifest_markdown(tmp_path)
        assert "unknown" in md


# ---------------------------------------------------------------------------
# manifest.py — ProjectManifestManager
# ---------------------------------------------------------------------------


class TestProjectManifestManager:
    """Integration tests for ProjectManifestManager with real disk I/O."""

    def _make_manager(self, tmp_path: Path):
        from manifest import ProjectManifestManager
        from manifest_curator import CuratedManifestStore
        from tests.helpers import ConfigFactory

        config = ConfigFactory.create(repo_root=tmp_path)
        curator = CuratedManifestStore(config)
        return ProjectManifestManager(config, curator)

    def test_scan_write_read_roundtrip(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\n")
        mgr = self._make_manager(tmp_path)

        content = mgr.scan()
        digest_hash = mgr.write(content)
        assert mgr.manifest_path.read_text() == content
        assert len(digest_hash) == 16

    def test_needs_refresh_when_missing(self, tmp_path: Path) -> None:
        mgr = self._make_manager(tmp_path)
        assert mgr.needs_refresh("any-hash") is True

    def test_needs_refresh_same_hash(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\n")
        mgr = self._make_manager(tmp_path)
        content = mgr.scan()
        digest_hash = mgr.write(content)
        assert mgr.needs_refresh(digest_hash) is False

    def test_needs_refresh_different_hash(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\n")
        mgr = self._make_manager(tmp_path)
        mgr.write(mgr.scan())
        assert mgr.needs_refresh("wrong-hash") is True

    def test_hash_stability(self, tmp_path: Path) -> None:
        """Same content produces the same hash."""
        (tmp_path / "pyproject.toml").write_text("[project]\n")
        mgr = self._make_manager(tmp_path)
        content = mgr.scan()
        h1 = mgr.write(content)
        h2 = mgr.write(content)
        assert h1 == h2

    def test_refresh_end_to_end(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\n")
        mgr = self._make_manager(tmp_path)
        result = mgr.refresh()
        assert "python" in result.content
        assert len(result.digest_hash) == 16
        assert mgr.manifest_path.read_text() == result.content
