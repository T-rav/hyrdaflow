"""Tests for scripts/migrate_wiki_to_git.py.

Covers the parser (topic-file → list of entry dicts) and the round-trip
migration (old layout dir → per-entry files with frontmatter). See
docs/git-backed-wiki-design.md §Migration.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Make scripts/ importable for tests.
_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _topic_file_content(title: str, entries: list[dict[str, object]]) -> str:
    """Reproduce the on-disk format from src/repo_wiki.py:_write_topic_page."""
    lines = [f"# {title}\n"]
    for e in entries:
        lines.append(f"\n## {e['title']}\n")
        lines.append(f"{e['content']}\n")
        if e.get("source_issue") is not None:
            lines.append(f"_Source: #{e['source_issue']} ({e['source_type']})_\n")
        lines.append(f"\n```json:entry\n{json.dumps(e)}\n```\n")
    return "\n".join(lines)


class TestParseTopicFile:
    def test_extracts_json_entries(self, tmp_path: Path) -> None:
        from migrate_wiki_to_git import parse_topic_file

        topic = tmp_path / "patterns.md"
        topic.write_text(
            _topic_file_content(
                "Patterns",
                [
                    {
                        "title": "Use slots",
                        "content": "body A",
                        "source_issue": 101,
                        "source_type": "plan",
                    },
                    {
                        "title": "Circular imports",
                        "content": "body B",
                        "source_issue": 102,
                        "source_type": "review",
                    },
                ],
            )
        )

        entries = parse_topic_file(topic)
        assert len(entries) == 2
        assert entries[0]["title"] == "Use slots"
        assert entries[0]["source_issue"] == 101
        assert entries[0]["source_type"] == "plan"
        assert entries[1]["title"] == "Circular imports"
        assert entries[1]["source_type"] == "review"

    def test_handles_null_source_issue_from_compiled_entries(
        self, tmp_path: Path
    ) -> None:
        """Synthesized (compiled) entries have source_issue=null; must not crash."""
        from migrate_wiki_to_git import parse_topic_file

        topic = tmp_path / "patterns.md"
        topic.write_text(
            _topic_file_content(
                "Patterns",
                [
                    {
                        "title": "Compiled rollup",
                        "content": "synthesized body",
                        "source_issue": None,
                        "source_type": "compiled",
                    }
                ],
            )
        )

        entries = parse_topic_file(topic)
        assert len(entries) == 1
        assert entries[0]["source_issue"] is None
        assert entries[0]["source_type"] == "compiled"

    def test_handles_empty_topic(self, tmp_path: Path) -> None:
        from migrate_wiki_to_git import parse_topic_file

        topic = tmp_path / "patterns.md"
        topic.write_text("# Patterns\n\n_No entries yet._\n")

        assert parse_topic_file(topic) == []

    def test_falls_back_to_header_parsing_when_json_missing(
        self, tmp_path: Path
    ) -> None:
        """If somehow the ```json:entry block is absent, parser still
        extracts title/body/source from the section structure."""
        from migrate_wiki_to_git import parse_topic_file

        topic = tmp_path / "patterns.md"
        topic.write_text(
            "# Patterns\n\n## Orphan entry\n\norphan body\n\n_Source: #99 (plan)_\n"
        )

        entries = parse_topic_file(topic)
        assert len(entries) == 1
        assert entries[0]["title"] == "Orphan entry"
        assert entries[0]["source_issue"] == 99
        assert entries[0]["source_type"] == "plan"


class TestMigrateRepo:
    def test_round_trip(self, tmp_path: Path) -> None:
        from migrate_wiki_to_git import migrate_repo

        src = tmp_path / "src" / "owner" / "repo"
        src.mkdir(parents=True)
        (src / "patterns.md").write_text(
            _topic_file_content(
                "Patterns",
                [
                    {
                        "title": "Entry one",
                        "content": "body one",
                        "source_issue": 10,
                        "source_type": "plan",
                    },
                    {
                        "title": "Entry two",
                        "content": "body two",
                        "source_issue": 11,
                        "source_type": "review",
                    },
                ],
            )
        )
        (src / "gotchas.md").write_text(
            _topic_file_content(
                "Gotchas",
                [
                    {
                        "title": "Foot gun",
                        "content": "watch out",
                        "source_issue": 12,
                        "source_type": "plan",
                    }
                ],
            )
        )

        dst = tmp_path / "dst" / "owner" / "repo"
        migrate_repo(src, dst)

        patterns = sorted((dst / "patterns").glob("*.md"))
        gotchas = sorted((dst / "gotchas").glob("*.md"))
        assert len(patterns) == 2
        assert len(gotchas) == 1
        assert (dst / "index.md").exists()

        first = patterns[0].read_text()
        assert "source_issue: 10" in first
        assert "source_phase: plan" in first
        assert "# Entry one" in first
        assert "status: active" in first

    def test_compiled_entry_maps_to_synthesis_phase(self, tmp_path: Path) -> None:
        from migrate_wiki_to_git import migrate_repo

        src = tmp_path / "src" / "owner" / "repo"
        src.mkdir(parents=True)
        (src / "patterns.md").write_text(
            _topic_file_content(
                "Patterns",
                [
                    {
                        "title": "Synthesis",
                        "content": "synth body",
                        "source_issue": None,
                        "source_type": "compiled",
                    }
                ],
            )
        )

        dst = tmp_path / "dst" / "owner" / "repo"
        migrate_repo(src, dst)

        entry_file = next((dst / "patterns").glob("*.md"))
        text = entry_file.read_text()
        assert "source_phase: synthesis" in text
        # source_issue=None should render as "unknown" in the filename.
        assert "issue-unknown" in entry_file.name

    def test_splits_log_jsonl_by_issue_when_records_carry_issue_number(
        self, tmp_path: Path
    ) -> None:
        """Forward-looking path: post-Phase-3 records will carry issue_number."""
        from migrate_wiki_to_git import migrate_repo

        src = tmp_path / "src" / "owner" / "repo"
        src.mkdir(parents=True)
        (src / "log.jsonl").write_text(
            "\n".join(
                [
                    json.dumps(
                        {"issue_number": 42, "phase": "plan", "action": "ingest"}
                    ),
                    json.dumps(
                        {"issue_number": 99, "phase": "review", "action": "ingest"}
                    ),
                    json.dumps(
                        {"issue_number": 42, "phase": "review", "action": "ingest"}
                    ),
                ]
            )
            + "\n"
        )

        dst = tmp_path / "dst" / "owner" / "repo"
        migrate_repo(src, dst)

        log_42 = (dst / "log" / "42.jsonl").read_text().strip().splitlines()
        log_99 = (dst / "log" / "99.jsonl").read_text().strip().splitlines()
        assert len(log_42) == 2
        assert len(log_99) == 1
        assert json.loads(log_42[0])["phase"] == "plan"
        assert json.loads(log_99[0])["phase"] == "review"

    def test_legacy_log_records_without_issue_number_go_to_legacy_jsonl(
        self, tmp_path: Path
    ) -> None:
        """Real-world path: pre-Phase-3 _append_log never wrote issue_number,
        so migrated records all fall through to ``legacy.jsonl``.
        """
        from migrate_wiki_to_git import migrate_repo

        src = tmp_path / "src" / "owner" / "repo"
        src.mkdir(parents=True)
        (src / "log.jsonl").write_text(
            "\n".join(
                [
                    # Matches the actual legacy shape produced by
                    # src/repo_wiki.py:_append_log (op + details only).
                    json.dumps({"op": "ingest", "details": {"entries_added": 3}}),
                    json.dumps({"op": "lint", "details": {"stale_entries": 2}}),
                ]
            )
            + "\n"
        )

        dst = tmp_path / "dst" / "owner" / "repo"
        migrate_repo(src, dst)

        legacy = (dst / "log" / "legacy.jsonl").read_text().strip().splitlines()
        assert len(legacy) == 2
        # No per-issue files should have been created.
        assert not list((dst / "log").glob("[0-9]*.jsonl"))
