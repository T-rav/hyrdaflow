"""Tests for the log ingestion pipeline."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from log_ingestion import (
    CrossProjectPattern,
    KnownLogPattern,
    LogEntry,
    LogIngestionResult,
    LogPattern,
    detect_cross_project_log_patterns,
    detect_log_patterns,
    enrich_patterns_with_events,
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
    hitl_label: list[str] | None = None,
) -> MagicMock:
    cfg = MagicMock()
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
    async def test_tracks_novel_pattern_for_dedup(self) -> None:
        """Novel patterns are recorded in known_patterns for dedup.

        Tribal-memory filing was removed in the tribal-memory rollout
        (2026-04-07); novel log patterns no longer call file_memory_suggestion
        but are still tracked so the same pattern is not re-detected forever.
        """
        config = _make_config()
        known: dict[str, KnownLogPattern] = {}
        pattern = self._make_pattern()

        result = await file_log_patterns([pattern], known, config)

        assert result.filed == 1
        assert result.escalated == 0
        assert result.total_patterns == 1
        assert "hydraflow.test:Score failed for item <N>" in known
        assert known["hydraflow.test:Score failed for item <N>"].issue_number == 0

    @pytest.mark.asyncio
    async def test_skips_known_pattern_below_escalation(self) -> None:
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

        result = await file_log_patterns([pattern], known, config)

        assert result.filed == 0
        assert result.escalated == 0
        # last_count should be updated
        assert known[key].last_count == 6

    @pytest.mark.asyncio
    async def test_escalates_3x_increase(self) -> None:
        """Escalating patterns write to hitl_recommendations.jsonl."""
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

        result = await file_log_patterns([pattern], known, config)

        assert result.escalated == 1
        assert result.filed == 0
        # last_count still updated
        assert known[key].last_count == 15

    @pytest.mark.asyncio
    async def test_updates_last_count_on_known(self) -> None:
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
        await file_log_patterns([pattern], known, config)
        assert known[key].last_count == 8

    # Note: test_handles_memory_filing_failure_gracefully and
    # test_novel_pattern_filed_without_prs were removed in the tribal-memory
    # rollout (2026-04-07) — file_log_patterns no longer calls file_memory_suggestion,
    # so there is no filing failure path to test. Dedup tracking is covered by
    # test_tracks_novel_pattern_for_dedup above.

    @pytest.mark.asyncio
    async def test_total_patterns_always_set(self) -> None:
        from unittest.mock import AsyncMock as _AsyncMock
        from unittest.mock import patch

        config = _make_config()
        known: dict[str, KnownLogPattern] = {}
        patterns = [self._make_pattern(f"fp <N> {i}", count=4) for i in range(5)]

        mock_file_mem = _AsyncMock()
        with patch("phase_utils.file_memory_suggestion", mock_file_mem):
            result = await file_log_patterns(patterns, known, config)

        assert result.total_patterns == 5

    @pytest.mark.asyncio
    async def test_result_model(self) -> None:
        result = LogIngestionResult(filed=2, escalated=1, total_patterns=10)
        assert result.filed == 2
        assert result.escalated == 1
        assert result.total_patterns == 10

    @pytest.mark.asyncio
    async def test_prs_none_does_not_raise(self) -> None:
        """Novel patterns are filed to JSONL without any prs dependency."""
        from unittest.mock import AsyncMock as _AsyncMock
        from unittest.mock import patch

        config = _make_config()
        known: dict[str, KnownLogPattern] = {}
        pattern = self._make_pattern()

        mock_file_mem = _AsyncMock()
        with patch("phase_utils.file_memory_suggestion", mock_file_mem):
            result = await file_log_patterns([pattern], known, config)

        assert result.filed == 1
        assert result.escalated == 0
        assert result.total_patterns == 1
        assert "hydraflow.test:Score failed for item <N>" in known

    @pytest.mark.asyncio
    async def test_prs_none_known_pattern_no_escalation(self) -> None:
        """Escalating patterns write to JSONL regardless of filing count."""
        config = _make_config()
        pattern = self._make_pattern(count=15)
        key = f"{pattern.source_module}:{pattern.fingerprint}"
        known = {
            key: KnownLogPattern(
                fingerprint=pattern.fingerprint,
                source_module=pattern.source_module,
                filed_at="2026-03-26T09:00:00+00:00",
                issue_number=50,
                last_count=5,
                filed_count=5,  # 15 >= 5*3 → escalates to JSONL
            )
        }

        result = await file_log_patterns([pattern], known, config)

        assert result.escalated == 1
        assert result.filed == 0
        # last_count still updated
        assert known[key].last_count == 15

    @pytest.mark.asyncio
    async def test_escalation_uses_filed_count_baseline(self) -> None:
        """Escalation checks pattern.count >= known.filed_count * 3 (not last_count)."""
        config = _make_config()
        pattern = self._make_pattern(count=15)
        key = f"{pattern.source_module}:{pattern.fingerprint}"
        # filed_count=5 → threshold=15 → count=15 → escalates
        # last_count=100 → would NOT escalate under old last_count logic
        known = {
            key: KnownLogPattern(
                fingerprint=pattern.fingerprint,
                source_module=pattern.source_module,
                filed_at="2026-03-26T09:00:00+00:00",
                issue_number=50,
                last_count=100,
                filed_count=5,
            )
        }

        result = await file_log_patterns([pattern], known, config)

        assert result.escalated == 1

    @pytest.mark.asyncio
    async def test_sentry_breadcrumb_called_for_novel_pattern(self) -> None:
        """Sentry breadcrumb is added when a novel pattern is detected."""
        from unittest.mock import AsyncMock as _AsyncMock
        from unittest.mock import MagicMock, patch

        config = _make_config()
        known: dict[str, KnownLogPattern] = {}
        pattern = self._make_pattern()

        mock_sentry = MagicMock()
        mock_file_mem = _AsyncMock()
        with (
            patch.dict("sys.modules", {"sentry_sdk": mock_sentry}),
            patch("phase_utils.file_memory_suggestion", mock_file_mem),
        ):
            await file_log_patterns([pattern], known, config)

        mock_sentry.add_breadcrumb.assert_called_once()
        call_kwargs = mock_sentry.add_breadcrumb.call_args[1]
        assert call_kwargs["category"] == "log_ingestion.novel"
        assert "level" in call_kwargs

    @pytest.mark.asyncio
    async def test_sentry_capture_message_called_on_escalation(self) -> None:
        """Sentry capture_message is called when a pattern escalates."""
        from unittest.mock import MagicMock, patch

        config = _make_config()
        pattern = self._make_pattern(count=15)
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

        mock_sentry = MagicMock()
        with patch.dict("sys.modules", {"sentry_sdk": mock_sentry}):
            await file_log_patterns([pattern], known, config)

        mock_sentry.capture_message.assert_called_once()
        args = mock_sentry.capture_message.call_args
        assert "escalating" in args[0][0].lower()
        assert args[1]["level"] == "warning"


# ---------------------------------------------------------------------------
# TestEnrichPatternsWithEvents
# ---------------------------------------------------------------------------


class TestEnrichPatternsWithEvents:
    def _make_pattern(self, issues: list[int] | None = None) -> LogPattern:
        return LogPattern(
            fingerprint="fp <N>",
            level="WARNING",
            source_module="hydraflow.test",
            count=5,
            sample_messages=["msg 1"],
            sample_issues=issues or [],
            first_seen="2026-03-26T10:00:00+00:00",
            last_seen="2026-03-26T11:00:00+00:00",
        )

    def test_adds_phase_context_from_matching_events(self) -> None:
        pattern = self._make_pattern(issues=[42])
        events = [
            {
                "type": "phase_change",
                "data": {"issue": 42, "phase": "implement", "status": "running"},
            }
        ]
        enrich_patterns_with_events([pattern], events)
        assert pattern.phase_context == ["issue #42: implement (running)"]

    def test_no_enrichment_when_no_matching_issues(self) -> None:
        pattern = self._make_pattern(issues=[99])
        events = [
            {
                "type": "phase_change",
                "data": {"issue": 1, "phase": "plan"},
            }
        ]
        enrich_patterns_with_events([pattern], events)
        assert pattern.phase_context == []

    def test_no_enrichment_when_pattern_has_no_sample_issues(self) -> None:
        pattern = self._make_pattern(issues=[])
        events = [
            {
                "type": "phase_change",
                "data": {"issue": 10, "phase": "plan"},
            }
        ]
        enrich_patterns_with_events([pattern], events)
        assert pattern.phase_context == []

    def test_caps_phase_context_at_five(self) -> None:
        # 3 issues × 2 events each = 6 potential entries → capped at 5
        pattern = self._make_pattern(issues=[1, 2, 3])
        events = []
        for issue_id in [1, 2, 3]:
            for i in range(2):
                events.append(
                    {
                        "type": "phase_change",
                        "data": {
                            "issue": issue_id,
                            "phase": f"phase_{i}",
                            "status": "done",
                        },
                    }
                )
        enrich_patterns_with_events([pattern], events)
        assert len(pattern.phase_context) <= 5

    def test_handles_empty_event_history_gracefully(self) -> None:
        pattern = self._make_pattern(issues=[10])
        enrich_patterns_with_events([pattern], [])
        assert pattern.phase_context == []

    def test_ignores_non_phase_event_types(self) -> None:
        pattern = self._make_pattern(issues=[42])
        events = [{"type": "some_other_event", "data": {"issue": 42, "phase": "plan"}}]
        enrich_patterns_with_events([pattern], events)
        assert pattern.phase_context == []

    def test_worker_update_events_included(self) -> None:
        pattern = self._make_pattern(issues=[7])
        events = [{"type": "worker_update", "data": {"issue": 7, "phase": "review"}}]
        enrich_patterns_with_events([pattern], events)
        assert len(pattern.phase_context) == 1
        assert "issue #7: review" in pattern.phase_context[0]

    def test_status_omitted_when_empty(self) -> None:
        pattern = self._make_pattern(issues=[5])
        events = [{"type": "phase_change", "data": {"issue": 5, "phase": "triage"}}]
        enrich_patterns_with_events([pattern], events)
        assert pattern.phase_context == ["issue #5: triage"]
        assert "(" not in pattern.phase_context[0]

    def test_deduplicates_identical_context_strings(self) -> None:
        pattern = self._make_pattern(issues=[3])
        # Same event twice — should not produce duplicate entries
        event = {"type": "phase_change", "data": {"issue": 3, "phase": "plan"}}
        enrich_patterns_with_events([pattern], [event, event])
        assert pattern.phase_context.count("issue #3: plan") == 1


# ---------------------------------------------------------------------------
# TestCrossProjectLogPatterns
# ---------------------------------------------------------------------------


def _make_known_pattern(
    fingerprint: str,
    module: str = "hydraflow.test",
    last_count: int = 5,
) -> KnownLogPattern:
    return KnownLogPattern(
        fingerprint=fingerprint,
        source_module=module,
        filed_at="2026-03-26T10:00:00+00:00",
        issue_number=1,
        last_count=last_count,
        filed_count=last_count,
    )


class TestCrossProjectLogPatterns:
    def test_detects_pattern_in_two_projects(self) -> None:
        key = "hydraflow.test:fp <N>"
        project_patterns = {
            "project-a": {key: _make_known_pattern("fp <N>")},
            "project-b": {key: _make_known_pattern("fp <N>")},
        }
        results = detect_cross_project_log_patterns(project_patterns)
        assert len(results) == 1
        assert set(results[0].projects) == {"project-a", "project-b"}

    def test_ignores_pattern_in_only_one_project(self) -> None:
        key = "hydraflow.test:fp <N>"
        project_patterns = {
            "project-a": {key: _make_known_pattern("fp <N>")},
        }
        results = detect_cross_project_log_patterns(project_patterns)
        assert results == []

    def test_respects_min_projects_parameter(self) -> None:
        key = "hydraflow.test:fp <N>"
        project_patterns = {
            "a": {key: _make_known_pattern("fp <N>")},
            "b": {key: _make_known_pattern("fp <N>")},
        }
        # Require 3 projects — should return nothing
        results = detect_cross_project_log_patterns(project_patterns, min_projects=3)
        assert results == []

    def test_total_count_sums_across_projects(self) -> None:
        key = "hydraflow.test:fp <N>"
        project_patterns = {
            "a": {key: _make_known_pattern("fp <N>", last_count=10)},
            "b": {key: _make_known_pattern("fp <N>", last_count=7)},
        }
        results = detect_cross_project_log_patterns(project_patterns)
        assert results[0].total_count == 17

    def test_sorted_by_project_count_descending(self) -> None:
        key1 = "mod:fp1 <N>"
        key2 = "mod:fp2 <N>"
        project_patterns = {
            "a": {
                key1: _make_known_pattern("fp1 <N>", "mod"),
                key2: _make_known_pattern("fp2 <N>", "mod"),
            },
            "b": {
                key1: _make_known_pattern("fp1 <N>", "mod"),
                key2: _make_known_pattern("fp2 <N>", "mod"),
            },
            "c": {
                key1: _make_known_pattern("fp1 <N>", "mod"),
            },
        }
        # key1 appears in 3 projects; key2 appears in 2 projects
        results = detect_cross_project_log_patterns(project_patterns)
        assert len(results) == 2
        assert len(results[0].projects) >= len(results[1].projects)
        assert results[0].fingerprint == "fp1 <N>"

    def test_handles_empty_input(self) -> None:
        results = detect_cross_project_log_patterns({})
        assert results == []

    def test_parses_module_and_fingerprint_from_key(self) -> None:
        key = "hydraflow.worker:conn refused <N>"
        project_patterns = {
            "x": {key: _make_known_pattern("conn refused <N>", "hydraflow.worker")},
            "y": {key: _make_known_pattern("conn refused <N>", "hydraflow.worker")},
        }
        results = detect_cross_project_log_patterns(project_patterns)
        assert results[0].source_module == "hydraflow.worker"
        assert results[0].fingerprint == "conn refused <N>"

    def test_returns_cross_project_pattern_dataclass(self) -> None:
        key = "mod:fp <N>"
        project_patterns = {
            "a": {key: _make_known_pattern("fp <N>", "mod")},
            "b": {key: _make_known_pattern("fp <N>", "mod")},
        }
        results = detect_cross_project_log_patterns(project_patterns)
        assert isinstance(results[0], CrossProjectPattern)
