"""B2 — auto-stale-mark drift findings (extension of P4).

``detect_drift`` flags entries citing missing files. A companion
helper flips those entries' ``status: active`` → ``stale`` with a
``stale_reason: drift_detected: <files>`` annotation so they drop
out of ``query()``'s prompt-injection results immediately.

Safe by construction: P4's detector is deterministic — a missing
file is binary, no LLM guesswork.  Auto-marking is therefore low
risk for false positives.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from wiki_drift_detector import DriftFinding, apply_drift_markers, detect_drift


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


def test_apply_markers_flips_active_to_stale(tmp_path: Path) -> None:
    tracked_root = tmp_path / "repo_wiki"
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    entry_path = _write_entry(
        tracked_root,
        "o/r",
        "patterns",
        body="# title\n\nCited in `src/ghost.py:Ghost`.",
    )

    result = detect_drift(
        tracked_root=tracked_root, repo_root=repo_root, repo_slug="o/r"
    )
    marked = apply_drift_markers(result.findings)

    assert marked == 1
    updated_text = entry_path.read_text()
    assert "status: stale" in updated_text
    assert "stale_reason: drift_detected" in updated_text
    assert "src/ghost.py" in updated_text


def test_apply_markers_preserves_body(tmp_path: Path) -> None:
    tracked_root = tmp_path / "repo_wiki"
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    body_text = "# title\n\nThe important insight here.\n\nCited `src/ghost.py:Ghost`."
    entry_path = _write_entry(tracked_root, "o/r", "patterns", body=body_text)

    result = detect_drift(
        tracked_root=tracked_root, repo_root=repo_root, repo_slug="o/r"
    )
    apply_drift_markers(result.findings)

    text = entry_path.read_text()
    # Body survives
    assert "The important insight here." in text
    # Still one frontmatter block
    assert text.count("---\n") == 2


def test_apply_markers_returns_zero_for_empty_findings() -> None:
    assert apply_drift_markers([]) == 0


def test_apply_markers_skips_unreadable_files(tmp_path: Path) -> None:
    # Finding pointing at a path that doesn't exist: apply_drift_markers
    # must not raise; it should skip and report 0.
    finding = DriftFinding(
        entry_path=tmp_path / "missing.md",
        entry_id="x",
        topic="patterns",
        missing_files=frozenset({"src/ghost.py"}),
    )
    assert apply_drift_markers([finding]) == 0
