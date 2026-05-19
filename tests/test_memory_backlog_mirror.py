"""Pure-function tests for `src/memory_backlog_mirror.py`."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from memory_backlog_mirror import (  # noqa: E402
    dedup_key_for,
    load_mirror_entry,
    pending_entries,
    render_issue_body,
    update_status,
)


def _write(
    path: Path, front: dict, body: str = "rule body\n\n**Why:** because\n"
) -> None:
    front_yaml = yaml.safe_dump(front, sort_keys=False).rstrip()
    path.write_text(f"---\n{front_yaml}\n---\n\n{body}")


def test_load_entry(tmp_path: Path) -> None:
    p = tmp_path / "x.md"
    _write(
        p,
        {
            "source": "feedback_x.md",
            "name": "X rule",
            "description": "desc",
            "status": "pending",
            "issue": None,
            "promoted_in": None,
            "wontfix_reason": None,
            "created": "2026-05-07",
        },
    )
    entry = load_mirror_entry(p)
    assert entry.slug == "x"
    assert entry.name == "X rule"
    assert entry.status == "pending"
    assert entry.issue is None


def test_pending_entries_filters_status(tmp_path: Path) -> None:
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    c = tmp_path / "c.md"
    _write(
        a,
        {
            "source": "fa.md",
            "name": "A",
            "status": "pending",
            "issue": None,
            "promoted_in": None,
        },
    )
    _write(
        b,
        {
            "source": "fb.md",
            "name": "B",
            "status": "issue-open",
            "issue": 42,
            "promoted_in": None,
        },
    )
    _write(
        c,
        {
            "source": "fc.md",
            "name": "C",
            "status": "promoted",
            "issue": 9,
            "promoted_in": "abc1234",
        },
    )
    entries = pending_entries(tmp_path)
    assert [e.slug for e in entries] == ["a"]


def test_pending_entries_skips_readme(tmp_path: Path) -> None:
    """README.md in the mirror dir is documentation, not an entry."""
    readme = tmp_path / "README.md"
    readme.write_text("# Memory feedback\n")
    p = tmp_path / "real.md"
    _write(
        p,
        {
            "source": "f.md",
            "name": "R",
            "status": "pending",
            "issue": None,
            "promoted_in": None,
        },
    )
    entries = pending_entries(tmp_path)
    assert [e.slug for e in entries] == ["real"]


def test_dedup_key_is_stable() -> None:
    assert (
        dedup_key_for("feedback-subagent-batch-size")
        == "memory_backlog:feedback-subagent-batch-size"
    )


def test_render_issue_body_includes_source_link(tmp_path: Path) -> None:
    p = tmp_path / "x.md"
    _write(
        p,
        {
            "source": "feedback_x.md",
            "name": "X rule",
            "description": "short desc",
            "status": "pending",
            "issue": None,
            "promoted_in": None,
        },
    )
    entry = load_mirror_entry(p)
    body = render_issue_body(entry, repo_relative_path="docs/wiki/memory-feedback/x.md")
    assert "X rule" in body
    assert "short desc" in body
    assert "docs/wiki/memory-feedback/x.md" in body
    assert "rule body" in body


def test_update_status_writes_back_frontmatter(tmp_path: Path) -> None:
    p = tmp_path / "x.md"
    _write(
        p,
        {
            "source": "feedback_x.md",
            "name": "X",
            "status": "pending",
            "issue": None,
            "promoted_in": None,
        },
    )
    update_status(p, status="issue-open", issue=123)
    entry = load_mirror_entry(p)
    assert entry.status == "issue-open"
    assert entry.issue == 123
    # Body preserved verbatim.
    assert "rule body" in p.read_text()


def test_load_entry_rejects_unknown_status(tmp_path: Path) -> None:
    p = tmp_path / "x.md"
    _write(
        p,
        {
            "source": "feedback_x.md",
            "name": "X",
            "status": "garbage",
            "issue": None,
            "promoted_in": None,
        },
    )
    with pytest.raises(ValueError, match="invalid status"):
        load_mirror_entry(p)


def test_load_entry_handles_missing_optional_fields(tmp_path: Path) -> None:
    """Old mirrors might not have all optional fields; loader must tolerate."""
    p = tmp_path / "x.md"
    _write(p, {"source": "f.md", "name": "X", "status": "pending"})
    entry = load_mirror_entry(p)
    assert entry.issue is None
    assert entry.promoted_in is None
    assert entry.wontfix_reason is None


def test_update_status_preserves_unrelated_frontmatter_fields(tmp_path: Path) -> None:
    """Updating status shouldn't drop fields like `source` or `name`."""
    p = tmp_path / "x.md"
    _write(
        p,
        {
            "source": "feedback_x.md",
            "name": "Original name",
            "description": "desc",
            "status": "pending",
            "issue": None,
            "promoted_in": None,
            "created": "2026-04-01",
        },
    )
    update_status(p, status="promoted", promoted_in="commit_abc123")
    entry = load_mirror_entry(p)
    assert entry.name == "Original name"
    assert entry.source == "feedback_x.md"
    assert entry.promoted_in == "commit_abc123"
