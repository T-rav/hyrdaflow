"""Tests for the wiki-vs-code drift detector (P4 wiki-evolution audit).

First-cut detector is heuristic / deterministic: for each active
entry, extract ``src/...`` citations from its body, then verify each
cited file still exists under ``repo_root``.  Missing files = drift.
Symbol-level checks (grep for ``class Foo`` etc.) are a follow-up.

Output is a ``DriftResult`` the RepoWikiLoop can use to mark flagged
entries stale with a ``stale_reason: drift_detected <files>`` note.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from wiki_drift_detector import DriftFinding, detect_drift


def _write_entry(
    tracked_root: Path,
    repo_slug: str,
    topic: str,
    *,
    body: str,
    entry_id: str = "01JF000000000000000001",
    source_issue: int = 1,
    status: str = "active",
) -> Path:
    topic_dir = tracked_root / repo_slug / topic
    topic_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).isoformat()
    path = topic_dir / f"0001-issue-{source_issue}.md"
    path.write_text(
        "---\n"
        f"id: {entry_id}\n"
        f"topic: {topic}\n"
        f"source_issue: {source_issue}\n"
        "source_phase: implement\n"
        f"created_at: {now}\n"
        f"status: {status}\n"
        "---\n"
        f"{body}\n",
        encoding="utf-8",
    )
    return path


def test_detects_entry_citing_missing_file(tmp_path: Path) -> None:
    tracked_root = tmp_path / "repo_wiki"
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_entry(
        tracked_root,
        "o/r",
        "patterns",
        body="# title\n\nThe relevant code lives in `src/ghost.py:Ghost`.",
    )

    result = detect_drift(
        tracked_root=tracked_root,
        repo_root=repo_root,
        repo_slug="o/r",
    )

    assert len(result.findings) == 1
    finding = result.findings[0]
    assert isinstance(finding, DriftFinding)
    assert "src/ghost.py" in finding.missing_files


def test_passes_when_cited_file_exists(tmp_path: Path) -> None:
    tracked_root = tmp_path / "repo_wiki"
    repo_root = tmp_path / "repo"
    (repo_root / "src").mkdir(parents=True)
    (repo_root / "src" / "exists.py").write_text("class Exists: pass\n")

    _write_entry(
        tracked_root,
        "o/r",
        "patterns",
        body="# title\n\nImplemented in `src/exists.py:Exists`.",
    )

    result = detect_drift(
        tracked_root=tracked_root,
        repo_root=repo_root,
        repo_slug="o/r",
    )

    assert result.findings == []


def test_ignores_stale_and_superseded_entries(tmp_path: Path) -> None:
    tracked_root = tmp_path / "repo_wiki"
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_entry(
        tracked_root,
        "o/r",
        "patterns",
        body="Old body citing `src/ghost.py:Ghost`.",
        entry_id="01JF000000000000000002",
        source_issue=2,
        status="stale",
    )

    result = detect_drift(
        tracked_root=tracked_root,
        repo_root=repo_root,
        repo_slug="o/r",
    )

    assert result.findings == []


def test_entry_without_src_citations_is_skipped(tmp_path: Path) -> None:
    tracked_root = tmp_path / "repo_wiki"
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_entry(
        tracked_root,
        "o/r",
        "patterns",
        body="# title\n\nGeneral architectural note. No source pointers.",
    )

    result = detect_drift(
        tracked_root=tracked_root,
        repo_root=repo_root,
        repo_slug="o/r",
    )

    assert result.findings == []


def test_returns_empty_when_no_tracked_entries(tmp_path: Path) -> None:
    result = detect_drift(
        tracked_root=tmp_path / "missing",
        repo_root=tmp_path / "repo",
        repo_slug="o/r",
    )
    assert result.findings == []


def test_aggregates_findings_across_topics(tmp_path: Path) -> None:
    tracked_root = tmp_path / "repo_wiki"
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_entry(
        tracked_root,
        "o/r",
        "patterns",
        body="cites `src/one.py:A`",
        entry_id="01JF000000000000000001",
        source_issue=1,
    )
    _write_entry(
        tracked_root,
        "o/r",
        "testing",
        body="cites `src/two.py:B`",
        entry_id="01JF000000000000000002",
        source_issue=2,
    )

    result = detect_drift(
        tracked_root=tracked_root,
        repo_root=repo_root,
        repo_slug="o/r",
    )

    assert len(result.findings) == 2
    topics = {f.topic for f in result.findings}
    assert topics == {"patterns", "testing"}
