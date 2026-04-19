"""Tests for the Phase 3 per-entry write API on ``RepoWikiStore``.

Covers ``write_entry``, ``append_log``, and ``commit_pending_entries`` —
the methods that make phase-ingest writes ride the issue's worktree PR.
See docs/git-backed-wiki-design.md Phase 3.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from repo_wiki import RepoWikiStore, WikiEntry

REPO = "acme/widget"


@pytest.fixture
def git_worktree(tmp_path: Path) -> Path:
    """An initialized git worktree with one initial commit.

    ``commit_pending_entries`` requires a real git repo because it stages
    + commits; matches the ``feedback_dolt_embedded`` guidance to prefer
    real git over mocks.
    """
    subprocess.run(["git", "init", str(tmp_path)], check=True)
    (tmp_path / "seed").write_text("seed\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
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
    return tmp_path


@pytest.fixture
def store(git_worktree: Path) -> RepoWikiStore:
    return RepoWikiStore(git_worktree / "repo_wiki")


def _entry(
    title: str, *, issue: int | None = 42, source_type: str = "plan"
) -> WikiEntry:
    return WikiEntry(
        title=title,
        content="body for " + title,
        source_type=source_type,
        source_issue=issue,
    )


class TestWriteEntry:
    def test_writes_per_entry_file_with_frontmatter(self, store: RepoWikiStore) -> None:
        path = store.write_entry(REPO, _entry("A pattern"), topic="patterns")

        assert path.parent.name == "patterns"
        assert path.name.endswith(".md")
        text = path.read_text()
        assert text.startswith("---\n")
        assert "topic: patterns" in text
        assert "source_issue: 42" in text
        assert "source_phase: plan" in text
        assert "status: active" in text
        assert "# A pattern" in text

    def test_filename_embeds_issue_number_and_slug(self, store: RepoWikiStore) -> None:
        path = store.write_entry(REPO, _entry("Circular imports!"), topic="patterns")

        assert "issue-42" in path.name
        assert "circular-imports" in path.name

    def test_unknown_issue_renders_as_unknown_in_filename(
        self, store: RepoWikiStore
    ) -> None:
        path = store.write_entry(REPO, _entry("Synth", issue=None), topic="patterns")
        assert "issue-unknown" in path.name

    def test_entry_id_is_monotonic_per_topic(self, store: RepoWikiStore) -> None:
        e1 = store.write_entry(REPO, _entry("First"), topic="patterns")
        e2 = store.write_entry(REPO, _entry("Second"), topic="patterns")

        assert e1.name.startswith("0001-")
        assert e2.name.startswith("0002-")

    def test_entry_id_is_scoped_per_topic(self, store: RepoWikiStore) -> None:
        """Each topic has its own id counter — both patterns/0001 and
        gotchas/0001 coexist."""
        e1 = store.write_entry(REPO, _entry("P1"), topic="patterns")
        e2 = store.write_entry(REPO, _entry("G1"), topic="gotchas")

        assert e1.parent.name == "patterns"
        assert e2.parent.name == "gotchas"
        assert e1.name.startswith("0001-")
        assert e2.name.startswith("0001-")

    def test_source_phase_synthesis_for_compiled_entries(
        self, store: RepoWikiStore
    ) -> None:
        path = store.write_entry(
            REPO,
            _entry("Compiled", issue=None, source_type="compiled"),
            topic="patterns",
        )
        assert "source_phase: synthesis" in path.read_text()


class TestAppendLog:
    def test_appends_per_issue_jsonl(self, store: RepoWikiStore) -> None:
        store.append_log(REPO, 100, {"phase": "plan", "action": "ingest"})
        store.append_log(REPO, 100, {"phase": "review", "action": "ingest"})
        store.append_log(REPO, 101, {"phase": "plan", "action": "ingest"})

        log_100 = (
            (store._wiki_root / REPO / "log" / "100.jsonl")
            .read_text()
            .strip()
            .splitlines()
        )
        log_101 = (
            (store._wiki_root / REPO / "log" / "101.jsonl")
            .read_text()
            .strip()
            .splitlines()
        )
        assert len(log_100) == 2
        assert len(log_101) == 1
        assert json.loads(log_100[0])["phase"] == "plan"
        assert json.loads(log_101[0])["action"] == "ingest"

    def test_record_includes_issue_number_automatically(
        self, store: RepoWikiStore
    ) -> None:
        """The method stamps issue_number into the record so downstream
        tooling (migration, per-issue views) can rely on it."""
        store.append_log(REPO, 42, {"phase": "plan"})

        log = (
            (store._wiki_root / REPO / "log" / "42.jsonl")
            .read_text()
            .strip()
            .splitlines()
        )
        rec = json.loads(log[0])
        assert rec["issue_number"] == 42
        assert rec["phase"] == "plan"


class TestCommitPendingEntries:
    def test_stages_and_commits_new_entries(
        self, store: RepoWikiStore, git_worktree: Path
    ) -> None:
        store.write_entry(REPO, _entry("X", issue=7), topic="patterns")
        store.append_log(REPO, 7, {"phase": "plan"})

        store.commit_pending_entries(
            worktree_path=git_worktree, phase="plan", issue_number=7
        )

        log = subprocess.run(
            ["git", "-C", str(git_worktree), "log", "--oneline"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert "wiki: ingest plan for #7" in log

        # The commit should carry the new repo_wiki files — staged by path.
        show = subprocess.run(
            ["git", "-C", str(git_worktree), "show", "--stat", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert "repo_wiki/" in show

    def test_no_op_when_nothing_pending(
        self, store: RepoWikiStore, git_worktree: Path
    ) -> None:
        """Called with nothing staged should not create an empty commit."""
        store.commit_pending_entries(
            worktree_path=git_worktree, phase="plan", issue_number=1
        )

        log = subprocess.run(
            ["git", "-C", str(git_worktree), "log", "--oneline"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        # Only the initial seed commit exists.
        assert log.strip().count("\n") == 0

    def test_does_not_sweep_unrelated_worktree_changes(
        self, store: RepoWikiStore, git_worktree: Path
    ) -> None:
        """Targeted ``git add repo_wiki/`` — never ``git add -A``.

        An unrelated modified file outside ``repo_wiki/`` must NOT land in
        the wiki commit.
        """
        store.write_entry(REPO, _entry("Y", issue=9), topic="patterns")

        unrelated = git_worktree / "unrelated.txt"
        unrelated.write_text("I should not be committed\n")

        store.commit_pending_entries(
            worktree_path=git_worktree, phase="plan", issue_number=9
        )

        show = subprocess.run(
            ["git", "-C", str(git_worktree), "show", "--name-only", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert "repo_wiki/" in show
        assert "unrelated.txt" not in show

        # And the unrelated file remains unstaged / untracked.
        status = subprocess.run(
            ["git", "-C", str(git_worktree), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert "unrelated.txt" in status


class TestWriteEntryCollisionAndSanitize:
    """Regressions for review findings L, M, O."""

    def test_write_entry_raises_on_filename_collision(
        self, store: RepoWikiStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Exclusive open prevents silent overwrite — surfaces the collision
        that a TOCTOU race between ``_next_entry_id`` and ``path.open('x')``
        could otherwise produce.
        """
        # Force _next_entry_id to return the same id twice — simulating the
        # race where two concurrent callers both scanned the directory
        # before either wrote.
        import repo_wiki as rw

        def stuck_next_id(topic_dir: Path) -> int:
            del topic_dir
            return 1

        monkeypatch.setattr(rw, "_next_entry_id", stuck_next_id)

        store.write_entry(REPO, _entry("First", issue=42), topic="patterns")
        with pytest.raises(FileExistsError):
            store.write_entry(REPO, _entry("First", issue=42), topic="patterns")

    def test_next_entry_id_skips_non_issue_numbered_files(
        self, store: RepoWikiStore
    ) -> None:
        """`_next_entry_id` must count any ``{digits}-...`` prefix, not only
        ``{digits}-issue-...``.  A synthesis or hand-edited file without
        ``issue-`` must not cause a duplicate id on the next write.
        """
        topic_dir = store._wiki_root / REPO / "patterns"
        topic_dir.mkdir(parents=True)
        (topic_dir / "0001-synthesis-foo.md").write_text("---\nid: 0001\n---\n")

        path = store.write_entry(REPO, _entry("Next"), topic="patterns")
        assert path.name.startswith("0002-")

    def test_sanitizes_leading_frontmatter_in_body(self, store: RepoWikiStore) -> None:
        """Content that starts with `---` must not be confused for a second
        YAML document by a multi-doc parser.

        Invariant: the first non-blank, non-title line of the body
        section must NOT itself be ``---``. Embedded ``---`` horizontal
        rules elsewhere in the body remain.
        """
        e = WikiEntry(
            title="Quote",
            content="---\nnested: true\n---\nactual body",
            source_type="plan",
            source_issue=7,
        )
        path = store.write_entry(REPO, e, topic="patterns")
        lines = path.read_text().splitlines()

        close_idx = next(
            i for i, ln in enumerate(lines) if i > 0 and ln.strip() == "---"
        )
        body_start = close_idx + 1
        while body_start < len(lines) and (
            lines[body_start].strip() == "" or lines[body_start].startswith("# ")
        ):
            body_start += 1

        assert body_start < len(lines), "body absent"
        assert lines[body_start].strip() != "---", (
            "first body line must not be `---` — would be read as a "
            f"second YAML document. Got: {lines[body_start]!r}"
        )

    def test_commit_pending_entries_respects_path_prefix(
        self, git_worktree: Path
    ) -> None:
        """When repo_wiki_path is overridden, the commit targets that path."""
        store = RepoWikiStore(git_worktree / "custom_wiki")
        store.write_entry(REPO, _entry("X", issue=3), topic="patterns")

        store.commit_pending_entries(
            worktree_path=git_worktree,
            phase="plan",
            issue_number=3,
            path_prefix="custom_wiki",
        )

        show = subprocess.run(
            ["git", "-C", str(git_worktree), "show", "--name-only", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert "custom_wiki/" in show
        assert "repo_wiki/" not in show
