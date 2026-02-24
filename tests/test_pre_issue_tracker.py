"""Tests for local .hydraflow/prep markdown issue tracking."""

from __future__ import annotations

from pre_issue_tracker import (
    ensure_pre_dirs,
    load_open_issues,
    mark_done,
    upsert_issue,
    write_run_log,
)


def test_ensure_pre_dirs_creates_dirs(tmp_path):
    pre_dir, runs_dir = ensure_pre_dirs(tmp_path)
    assert pre_dir.is_dir()
    assert runs_dir.is_dir()
    assert pre_dir == tmp_path / ".hydraflow" / "prep"
    assert runs_dir.parent == pre_dir / "runs"


def test_load_open_issues_skips_done(tmp_path):
    pre_dir, _ = ensure_pre_dirs(tmp_path)
    (pre_dir / "001-open.md").write_text("# Open\nbody\n")
    (pre_dir / "002-done.md").write_text("# Done\n<!-- status: done -->\n")

    issues = load_open_issues(tmp_path)

    assert len(issues) == 1
    assert issues[0].path.name == "001-open.md"
    assert issues[0].title == "Open"


def test_mark_done_appends_done_marker(tmp_path):
    pre_dir, _ = ensure_pre_dirs(tmp_path)
    p = pre_dir / "001-open.md"
    p.write_text("# Open\nbody\n")
    issue = load_open_issues(tmp_path)[0]

    mark_done(issue)

    body = p.read_text()
    assert "<!-- status: done -->" in body


def test_write_run_log_creates_log_file(tmp_path):
    path = write_run_log(tmp_path, title="Prep Run", lines=["- one", "- two"])
    assert path.is_file()
    text = path.read_text()
    assert "# Prep Run" in text
    assert "- one" in text


def test_upsert_issue_creates_or_updates_markdown(tmp_path):
    issue = upsert_issue(
        tmp_path,
        filename="auto-fix-quality.md",
        title="[prep] Resolve Quality failure",
        body_lines=["- one", "- two"],
    )
    assert issue.path.name == "auto-fix-quality.md"
    assert issue.path.exists()
    assert "[prep] Resolve Quality failure" in issue.path.read_text()
