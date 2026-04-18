"""Tests for the Phase 3.5 wiki-ingest wiring in plan_phase / review_phase.

Exercises the ``_wiki_tracked_store`` decision helper on both phases —
verifying it respects ``config.repo_wiki_git_backed`` and the existence
of the issue worktree — and the ``_wiki_commit_compiler_entries`` rollback
path.  Avoids reconstructing the full phase object; instead builds a
minimal stub that exposes just the attributes the helper reads.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from config import HydraFlowConfig
from plan_phase import PlanPhase
from repo_wiki import RepoWikiStore, WikiEntry
from review_phase import ReviewPhase


@pytest.fixture
def git_worktree(tmp_path: Path) -> Path:
    # Path must match HydraFlowConfig.workspace_path_for_issue:
    # workspace_base / repo_slug / issue-{n} where repo_slug replaces `/`→`-`.
    wt = tmp_path / "workspaces" / "acme-widget" / "issue-42"
    wt.mkdir(parents=True)
    subprocess.run(["git", "init", str(wt)], check=True)
    (wt / "seed").write_text("seed\n")
    subprocess.run(["git", "-C", str(wt), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(wt),
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-m",
            "init",
        ],
        check=True,
    )
    return wt


def _make_config(tmp_path: Path, *, git_backed: bool) -> HydraFlowConfig:
    """Minimal config — only the fields the wiki wiring reads."""
    return HydraFlowConfig(
        repo="acme/widget",
        workspace_base=tmp_path / "workspaces",
        repo_wiki_git_backed=git_backed,
        repo_wiki_path="repo_wiki",
    )


def _stub_phase(
    cls: type[PlanPhase] | type[ReviewPhase],
    config: HydraFlowConfig,
    wiki_store: RepoWikiStore,
) -> PlanPhase | ReviewPhase:
    """Construct a phase instance bypassing full __init__ — sets just
    the attributes the wiki helpers read.
    """
    obj = cls.__new__(cls)  # type: ignore[call-overload]
    obj._config = config
    obj._wiki_store = wiki_store
    obj._wiki_compiler = None
    return obj


@pytest.mark.parametrize("phase_cls", [PlanPhase, ReviewPhase])
class TestWikiTrackedStore:
    def test_returns_none_when_git_backed_disabled(
        self, phase_cls: type, tmp_path: Path, git_worktree: Path
    ) -> None:
        del git_worktree  # created but the helper skips on the config flag
        config = _make_config(tmp_path, git_backed=False)
        store = RepoWikiStore(tmp_path / "legacy")

        phase = _stub_phase(phase_cls, config, store)
        tracked, path = phase._wiki_tracked_store(42)

        assert tracked is None
        assert path is None

    def test_returns_none_when_worktree_missing(
        self, phase_cls: type, tmp_path: Path
    ) -> None:
        config = _make_config(tmp_path, git_backed=True)
        store = RepoWikiStore(tmp_path / "legacy")

        phase = _stub_phase(phase_cls, config, store)
        tracked, path = phase._wiki_tracked_store(999)  # no worktree for 999

        assert tracked is None
        assert path is None

    def test_returns_tracked_store_when_worktree_exists(
        self, phase_cls: type, tmp_path: Path, git_worktree: Path
    ) -> None:
        config = _make_config(tmp_path, git_backed=True)
        store = RepoWikiStore(tmp_path / "legacy")

        phase = _stub_phase(phase_cls, config, store)
        tracked, path = phase._wiki_tracked_store(42)

        assert tracked is not None
        assert path == git_worktree
        # Tracked store's root points at worktree/repo_wiki/.
        assert tracked._wiki_root == git_worktree / "repo_wiki"


@pytest.mark.parametrize("phase_cls", [PlanPhase, ReviewPhase])
class TestWikiCommitCompilerEntries:
    def test_writes_commits_and_respects_path_prefix(
        self, phase_cls: type, tmp_path: Path, git_worktree: Path
    ) -> None:
        config = _make_config(tmp_path, git_backed=True)
        legacy_store = RepoWikiStore(tmp_path / "legacy")
        tracked_store = RepoWikiStore(git_worktree / "repo_wiki")

        phase = _stub_phase(phase_cls, config, legacy_store)
        entries = [
            WikiEntry(
                title="Architecture of the queue",
                content="service A talks to service B via a queue" * 3,
                source_type="plan",
                source_issue=42,
            ),
            WikiEntry(
                title="Test strategy for the queue",
                content="run unit tests before integration tests" * 3,
                source_type="plan",
                source_issue=42,
            ),
        ]

        phase._wiki_commit_compiler_entries(
            tracked_store=tracked_store,
            worktree_path=git_worktree,
            repo="acme/widget",
            issue_number=42,
            phase="plan",
            entries=entries,
        )

        log = subprocess.run(
            ["git", "-C", str(git_worktree), "log", "--oneline"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert "wiki: ingest plan for #42" in log

        show = subprocess.run(
            ["git", "-C", str(git_worktree), "show", "--name-only", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert "repo_wiki/" in show
        # Two per-entry markdown files (one per topic via classify_topic) + a log jsonl.
        assert show.count(".md") == 2
        assert "log/42.jsonl" in show

    def test_rollback_on_partial_failure(
        self,
        phase_cls: type,
        tmp_path: Path,
        git_worktree: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When one write_entry raises, every prior write is removed."""
        config = _make_config(tmp_path, git_backed=True)
        legacy_store = RepoWikiStore(tmp_path / "legacy")
        tracked_store = RepoWikiStore(git_worktree / "repo_wiki")

        phase = _stub_phase(phase_cls, config, legacy_store)

        call_count = {"n": 0}
        original = tracked_store.write_entry

        def flaky_write_entry(repo_slug: str, entry: WikiEntry, *, topic: str) -> Path:
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise OSError("simulated disk full")
            return original(repo_slug, entry, topic=topic)

        monkeypatch.setattr(tracked_store, "write_entry", flaky_write_entry)

        entries = [
            WikiEntry(
                title=f"Entry {i}",
                content=f"content {i}" * 10,
                source_type="plan",
                source_issue=42,
            )
            for i in range(3)
        ]

        with pytest.raises(OSError, match="simulated disk full"):
            phase._wiki_commit_compiler_entries(
                tracked_store=tracked_store,
                worktree_path=git_worktree,
                repo="acme/widget",
                issue_number=42,
                phase="plan",
                entries=entries,
            )

        # No wiki files remain — the first successful write was rolled back.
        remaining = list((git_worktree / "repo_wiki").rglob("*.md"))
        assert remaining == [], f"orphaned after rollback: {remaining}"

        # No commit landed.
        log = (
            subprocess.run(
                ["git", "-C", str(git_worktree), "log", "--oneline"],
                capture_output=True,
                text=True,
                check=True,
            )
            .stdout.strip()
            .splitlines()
        )
        assert len(log) == 1  # only the initial seed commit
