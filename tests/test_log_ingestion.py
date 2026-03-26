"""Tests for the log ingestion pipeline."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from log_ingestion import (
    KnownLogPattern,
    LogEntry,
    LogIngestionResult,
    LogPattern,
    detect_log_patterns,
    file_log_patterns,
    fingerprint_message,
    load_known_patterns,
    parse_log_file,
    parse_log_files,
    save_known_patterns,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(
    msg: str,
    level: str = "WARNING",
    logger_name: str = "hydraflow.test",
    ts: str = "2026-03-26T10:00:00+00:00",
    issue: int | None = None,
) -> LogEntry:
    return LogEntry(
        ts=ts,
        level=level,
        msg=msg,
        logger="hydraflow.test" if logger_name == "hydraflow.test" else logger_name,
        issue=issue,
    )


def _make_config(
    improve_label: list[str] | None = None, hitl_label: list[str] | None = None
) -> MagicMock:
    cfg = MagicMock()
    cfg.improve_label = improve_label or ["hydraflow-improve"]
    cfg.hitl_label = hitl_label or ["hydraflow-hitl"]
    return cfg


def _write_log_lines(path: Path, lines: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(ln) for ln in lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# TestFingerprintMessage
# ---------------------------------------------------------------------------


class TestFingerprintMessage:
    def test_numbers_replaced(self) -> None:
        assert fingerprint_message("issue 42") == "issue <N>"

    def test_quoted_strings_replaced_single(self) -> None:
        assert fingerprint_message("loaded 'config.py'") == "loaded <S>"

    def test_quoted_strings_replaced_double(self) -> None:
        assert fingerprint_message('loaded "config.py"') == "loaded <S>"

    def test_hex_hashes_replaced(self) -> None:
        assert fingerprint_message("hash abc123def456") == "hash <H>"

    def test_short_hex_not_replaced(self) -> None:
        # 7 chars — below the 8-char threshold
        result = fingerprint_message("value abc1234")
        assert "<H>" not in result

    def test_paths_replaced(self) -> None:
        assert fingerprint_message("/usr/local/bin") == "<P>"

    def test_combined_replacement(self) -> None:
        # Numbers are replaced before paths, so "issue-42" becomes "issue-<N>"
        # and the path regex stops at "<", leaving a trailing "<N>".
        result = fingerprint_message("Merged PR #101 on agent/issue-42")
        assert result == "Merged PR #<N> on agent<P><N>"

    def test_empty_string(self) -> None:
        assert fingerprint_message("") == ""

    def test_no_variables(self) -> None:
        msg = "Connection refused"
        assert fingerprint_message(msg) == msg

    def test_multiple_numbers(self) -> None:
        result = fingerprint_message("item 3 of 10 failed")
        assert result == "item <N> of <N> failed"


# ---------------------------------------------------------------------------
# TestParseLogFile
# ---------------------------------------------------------------------------


class TestParseLogFile:
    def test_parse_valid_entries(self, tmp_path: Path) -> None:
        log_file = tmp_path / "server.log"
        lines = [
            {
                "ts": "2026-03-26T10:00:00+00:00",
                "level": "WARNING",
                "msg": "test",
                "logger": "hydraflow.test",
            },
            {
                "ts": "2026-03-26T10:01:00+00:00",
                "level": "ERROR",
                "msg": "fail",
                "logger": "hydraflow.test",
            },
        ]
        _write_log_lines(log_file, lines)
        entries = parse_log_file(log_file)
        assert len(entries) == 2
        assert entries[0].level == "WARNING"
        assert entries[1].level == "ERROR"

    def test_skip_malformed_lines(self, tmp_path: Path) -> None:
        log_file = tmp_path / "server.log"
        log_file.write_text(
            '{"ts": "2026-03-26T10:00:00+00:00", "level": "WARNING", "msg": "ok", "logger": "hydraflow.test"}\n'
            "NOT JSON\n"
            '{"ts": "2026-03-26T10:01:00+00:00", "level": "ERROR", "msg": "also ok", "logger": "hydraflow.test"}\n',
            encoding="utf-8",
        )
        entries = parse_log_file(log_file)
        assert len(entries) == 2

    def test_filter_by_since(self, tmp_path: Path) -> None:
        log_file = tmp_path / "server.log"
        lines = [
            {
                "ts": "2026-03-26T09:00:00+00:00",
                "level": "WARNING",
                "msg": "old",
                "logger": "hydraflow.test",
            },
            {
                "ts": "2026-03-26T11:00:00+00:00",
                "level": "WARNING",
                "msg": "new",
                "logger": "hydraflow.test",
            },
        ]
        _write_log_lines(log_file, lines)
        since = datetime(2026, 3, 26, 10, 0, 0, tzinfo=UTC)
        entries = parse_log_file(log_file, since=since)
        assert len(entries) == 1
        assert entries[0].msg == "new"

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        entries = parse_log_file(tmp_path / "nonexistent.log")
        assert entries == []

    def test_optional_fields(self, tmp_path: Path) -> None:
        log_file = tmp_path / "server.log"
        log_file.write_text(
            '{"ts": "2026-03-26T10:00:00+00:00", "level": "WARNING", "msg": "msg", "logger": "hydraflow.test", "issue": 99, "phase": "implement"}\n',
            encoding="utf-8",
        )
        entries = parse_log_file(log_file)
        assert entries[0].issue == 99
        assert entries[0].phase == "implement"


# ---------------------------------------------------------------------------
# TestParseLogFiles (rotation-aware)
# ---------------------------------------------------------------------------


class TestParseLogFiles:
    def _make_log_dir(self, tmp_path: Path) -> Path:
        return tmp_path

    def test_reads_main_and_backups(self, tmp_path: Path) -> None:
        backup = tmp_path / "server.log.1"
        main = tmp_path / "server.log"
        _write_log_lines(
            backup,
            [
                {
                    "ts": "2026-03-26T08:00:00+00:00",
                    "level": "WARNING",
                    "msg": "old",
                    "logger": "h.t",
                },
            ],
        )
        _write_log_lines(
            main,
            [
                {
                    "ts": "2026-03-26T10:00:00+00:00",
                    "level": "WARNING",
                    "msg": "new",
                    "logger": "h.t",
                },
            ],
        )
        entries = parse_log_files(tmp_path, max_backups=1)
        assert len(entries) == 2

    def test_deduplicates_entries(self, tmp_path: Path) -> None:
        line = {
            "ts": "2026-03-26T10:00:00+00:00",
            "level": "WARNING",
            "msg": "dup",
            "logger": "h.t",
        }
        backup = tmp_path / "server.log.1"
        main = tmp_path / "server.log"
        _write_log_lines(backup, [line])
        _write_log_lines(main, [line])  # same entry in both files
        entries = parse_log_files(tmp_path, max_backups=1)
        assert len(entries) == 1

    def test_sorted_by_timestamp(self, tmp_path: Path) -> None:
        backup = tmp_path / "server.log.1"
        main = tmp_path / "server.log"
        _write_log_lines(
            backup,
            [
                {
                    "ts": "2026-03-26T12:00:00+00:00",
                    "level": "WARNING",
                    "msg": "z",
                    "logger": "h.t",
                },
            ],
        )
        _write_log_lines(
            main,
            [
                {
                    "ts": "2026-03-26T08:00:00+00:00",
                    "level": "WARNING",
                    "msg": "a",
                    "logger": "h.t",
                },
            ],
        )
        entries = parse_log_files(tmp_path, max_backups=1)
        assert entries[0].msg == "a"
        assert entries[1].msg == "z"

    def test_missing_backups_handled_gracefully(self, tmp_path: Path) -> None:
        main = tmp_path / "server.log"
        _write_log_lines(
            main,
            [
                {
                    "ts": "2026-03-26T10:00:00+00:00",
                    "level": "WARNING",
                    "msg": "ok",
                    "logger": "h.t",
                },
            ],
        )
        # No backup files exist — should not raise
        entries = parse_log_files(tmp_path, max_backups=5)
        assert len(entries) == 1

    def test_since_filter_applied(self, tmp_path: Path) -> None:
        main = tmp_path / "server.log"
        _write_log_lines(
            main,
            [
                {
                    "ts": "2026-03-26T08:00:00+00:00",
                    "level": "WARNING",
                    "msg": "old",
                    "logger": "h.t",
                },
                {
                    "ts": "2026-03-26T12:00:00+00:00",
                    "level": "WARNING",
                    "msg": "new",
                    "logger": "h.t",
                },
            ],
        )
        since = datetime(2026, 3, 26, 10, 0, 0, tzinfo=UTC)
        entries = parse_log_files(tmp_path, since=since)
        assert len(entries) == 1
        assert entries[0].msg == "new"


# ---------------------------------------------------------------------------
# TestDetectLogPatterns
# ---------------------------------------------------------------------------


class TestDetectLogPatterns:
    def _make_entries(
        self,
        msg: str,
        count: int,
        level: str = "WARNING",
        module: str = "hydraflow.test",
        issues: list[int] | None = None,
    ) -> list[LogEntry]:
        entries = []
        for i in range(count):
            ts = f"2026-03-26T{10 + i:02d}:00:00+00:00"
            entries.append(
                LogEntry(
                    ts=ts,
                    level=level,
                    msg=f"{msg} {i}",  # slightly different messages with same fingerprint
                    logger=module,
                    issue=issues[i] if issues and i < len(issues) else None,
                )
            )
        return entries

    def test_groups_by_fingerprint_and_module(self) -> None:
        entries = self._make_entries("Score failed for item 42", 5)
        patterns = detect_log_patterns(entries)
        assert len(patterns) == 1
        assert "Score failed for item" in patterns[0].fingerprint

    def test_respects_min_count(self) -> None:
        entries = self._make_entries("Rare error", 2)
        patterns = detect_log_patterns(entries, min_count=3)
        assert patterns == []

    def test_above_threshold_included(self) -> None:
        entries = self._make_entries("Frequent warning", 5)
        patterns = detect_log_patterns(entries, min_count=3)
        assert len(patterns) == 1
        assert patterns[0].count == 5

    def test_filters_below_min_level(self) -> None:
        entries = self._make_entries("Debug noise", 10, level="DEBUG")
        patterns = detect_log_patterns(entries, min_level="WARNING")
        assert patterns == []

    def test_includes_warning_and_above(self) -> None:
        entries = self._make_entries(
            "warn msg", 4, level="WARNING"
        ) + self._make_entries("err msg", 3, level="ERROR")
        patterns = detect_log_patterns(entries, min_level="WARNING", min_count=3)
        assert len(patterns) == 2

    def test_sorted_by_frequency_descending(self) -> None:
        entries = self._make_entries(
            "rare warning", 3, level="WARNING", module="hydraflow.a"
        ) + self._make_entries("common error", 7, level="ERROR", module="hydraflow.b")
        patterns = detect_log_patterns(entries, min_count=3)
        assert patterns[0].count > patterns[1].count

    def test_sample_messages_up_to_three(self) -> None:
        entries = self._make_entries("msg", 10)
        patterns = detect_log_patterns(entries, min_count=3)
        assert len(patterns[0].sample_messages) <= 3

    def test_sample_issues_collected(self) -> None:
        entries = self._make_entries("fail", 5, issues=[10, 20, 30, 40, 50])
        patterns = detect_log_patterns(entries, min_count=3)
        assert len(patterns[0].sample_issues) > 0
        assert all(isinstance(i, int) for i in patterns[0].sample_issues)

    def test_first_and_last_seen(self) -> None:
        entries = self._make_entries("err", 5)
        patterns = detect_log_patterns(entries, min_count=3)
        assert patterns[0].first_seen <= patterns[0].last_seen


# ---------------------------------------------------------------------------
# TestKnownPatterns
# ---------------------------------------------------------------------------


class TestKnownPatterns:
    def _make_known(
        self, fingerprint: str = "test <N>", module: str = "hydraflow.test"
    ) -> KnownLogPattern:
        return KnownLogPattern(
            fingerprint=fingerprint,
            source_module=module,
            filed_at="2026-03-26T10:00:00+00:00",
            issue_number=42,
            last_count=5,
            filed_count=5,
        )

    def test_round_trip(self, tmp_path: Path) -> None:
        patterns = {
            "hydraflow.test:test <N>": self._make_known(),
        }
        save_known_patterns(tmp_path, patterns)
        loaded = load_known_patterns(tmp_path)
        assert "hydraflow.test:test <N>" in loaded
        assert loaded["hydraflow.test:test <N>"].issue_number == 42

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        patterns = load_known_patterns(tmp_path / "nonexistent")
        assert patterns == {}

    def test_multiple_patterns_persist(self, tmp_path: Path) -> None:
        patterns = {
            "mod.a:fp <N>": self._make_known("fp <N>", "mod.a"),
            "mod.b:other <S>": self._make_known("other <S>", "mod.b"),
        }
        save_known_patterns(tmp_path, patterns)
        loaded = load_known_patterns(tmp_path)
        assert len(loaded) == 2

    def test_handles_malformed_jsonl_lines(self, tmp_path: Path) -> None:
        path = tmp_path / "log_patterns.jsonl"
        valid = self._make_known()
        path.write_text(
            "NOT JSON\n" + valid.model_dump_json() + "\n",
            encoding="utf-8",
        )
        loaded = load_known_patterns(tmp_path)
        # The valid line should load; the bad line is silently skipped
        assert len(loaded) == 1

    def test_save_creates_directory(self, tmp_path: Path) -> None:
        nested = tmp_path / "deep" / "dir"
        patterns = {"hydraflow.test:fp <N>": self._make_known()}
        save_known_patterns(nested, patterns)
        assert (nested / "log_patterns.jsonl").exists()


# ---------------------------------------------------------------------------
# TestFileLogPatterns
# ---------------------------------------------------------------------------


class TestFileLogPatterns:
    def _make_pattern(
        self,
        fingerprint: str = "Score failed for item <N>",
        module: str = "hydraflow.test",
        count: int = 5,
    ) -> LogPattern:
        return LogPattern(
            fingerprint=fingerprint,
            level="WARNING",
            source_module=module,
            count=count,
            sample_messages=["Score failed for item 1", "Score failed for item 2"],
            sample_issues=[10, 20],
            first_seen="2026-03-26T10:00:00+00:00",
            last_seen="2026-03-26T11:00:00+00:00",
        )

    @pytest.mark.asyncio
    async def test_files_novel_pattern(self) -> None:
        prs = AsyncMock()
        prs.create_issue = AsyncMock(return_value=100)
        config = _make_config()
        known: dict[str, KnownLogPattern] = {}

        pattern = self._make_pattern()
        result = await file_log_patterns([pattern], known, prs, config)

        prs.create_issue.assert_called_once()
        title, body, *_ = prs.create_issue.call_args[0]
        assert "[Memory]" in title
        assert "Score failed for item <N>" in title
        assert result.filed == 1
        assert result.escalated == 0
        assert result.total_patterns == 1
        assert "hydraflow.test:Score failed for item <N>" in known

    @pytest.mark.asyncio
    async def test_skips_known_pattern_below_escalation(self) -> None:
        prs = AsyncMock()
        prs.create_issue = AsyncMock(return_value=200)
        config = _make_config()
        pattern = self._make_pattern(count=6)
        key = f"{pattern.source_module}:{pattern.fingerprint}"
        known = {
            key: KnownLogPattern(
                fingerprint=pattern.fingerprint,
                source_module=pattern.source_module,
                filed_at="2026-03-26T09:00:00+00:00",
                issue_number=50,
                last_count=5,
                filed_count=5,
            )
        }

        result = await file_log_patterns([pattern], known, prs, config)

        prs.create_issue.assert_not_called()
        assert result.filed == 0
        assert result.escalated == 0
        # last_count should be updated
        assert known[key].last_count == 6

    @pytest.mark.asyncio
    async def test_escalates_3x_increase(self) -> None:
        prs = AsyncMock()
        prs.create_issue = AsyncMock(return_value=300)
        config = _make_config()
        pattern = self._make_pattern(count=15)
        key = f"{pattern.source_module}:{pattern.fingerprint}"
        known = {
            key: KnownLogPattern(
                fingerprint=pattern.fingerprint,
                source_module=pattern.source_module,
                filed_at="2026-03-26T09:00:00+00:00",
                issue_number=50,
                last_count=5,  # 15 >= 5 * 3 → escalate
                filed_count=5,
            )
        }

        result = await file_log_patterns([pattern], known, prs, config)

        prs.create_issue.assert_called_once()
        title = prs.create_issue.call_args[0][0]
        assert "[Health Monitor]" in title
        assert result.escalated == 1
        assert result.filed == 0
        # last_count still updated
        assert known[key].last_count == 15

    @pytest.mark.asyncio
    async def test_updates_last_count_on_known(self) -> None:
        prs = AsyncMock()
        prs.create_issue = AsyncMock(return_value=400)
        config = _make_config()
        pattern = self._make_pattern(count=8)
        key = f"{pattern.source_module}:{pattern.fingerprint}"
        known = {
            key: KnownLogPattern(
                fingerprint=pattern.fingerprint,
                source_module=pattern.source_module,
                filed_at="2026-03-26T09:00:00+00:00",
                issue_number=50,
                last_count=7,
                filed_count=5,
            )
        }
        await file_log_patterns([pattern], known, prs, config)
        assert known[key].last_count == 8

    @pytest.mark.asyncio
    async def test_handles_create_issue_failure_gracefully(self) -> None:
        prs = AsyncMock()
        prs.create_issue = AsyncMock(side_effect=RuntimeError("network error"))
        config = _make_config()
        known: dict[str, KnownLogPattern] = {}
        pattern = self._make_pattern()

        # Should not raise; novel pattern simply not persisted
        result = await file_log_patterns([pattern], known, prs, config)

        assert result.filed == 0
        assert known == {}

    @pytest.mark.asyncio
    async def test_create_issue_returns_zero_not_filed(self) -> None:
        prs = AsyncMock()
        prs.create_issue = AsyncMock(return_value=0)
        config = _make_config()
        known: dict[str, KnownLogPattern] = {}
        pattern = self._make_pattern()

        result = await file_log_patterns([pattern], known, prs, config)

        assert result.filed == 0
        assert known == {}

    @pytest.mark.asyncio
    async def test_total_patterns_always_set(self) -> None:
        prs = AsyncMock()
        prs.create_issue = AsyncMock(return_value=500)
        config = _make_config()
        known: dict[str, KnownLogPattern] = {}
        patterns = [self._make_pattern(f"fp <N> {i}", count=4) for i in range(5)]

        result = await file_log_patterns(patterns, known, prs, config)

        assert result.total_patterns == 5

    @pytest.mark.asyncio
    async def test_result_model(self) -> None:
        result = LogIngestionResult(filed=2, escalated=1, total_patterns=10)
        assert result.filed == 2
        assert result.escalated == 1
        assert result.total_patterns == 10
