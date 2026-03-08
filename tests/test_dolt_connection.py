"""Tests for dolt/connection.py — DoltConnection CLI-embedded mode."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dolt.connection import DoltConnection, _sql_escape

# ---------------------------------------------------------------------------
# _sql_escape
# ---------------------------------------------------------------------------


class TestSqlEscape:
    def test_none_returns_null(self) -> None:
        assert _sql_escape(None) == "NULL"

    def test_bool_true(self) -> None:
        assert _sql_escape(True) == "1"

    def test_bool_false(self) -> None:
        assert _sql_escape(False) == "0"

    def test_int(self) -> None:
        assert _sql_escape(42) == "42"

    def test_float(self) -> None:
        assert _sql_escape(3.14) == "3.14"

    def test_string_quoted(self) -> None:
        assert _sql_escape("hello") == "'hello'"

    def test_string_with_single_quotes_doubled(self) -> None:
        assert _sql_escape("it's") == "'it''s'"

    def test_string_with_backslashes_escaped(self) -> None:
        assert _sql_escape("a\\b") == "'a\\\\b'"


# ---------------------------------------------------------------------------
# _interpolate
# ---------------------------------------------------------------------------


class TestInterpolate:
    def test_single_param(self) -> None:
        result = DoltConnection._interpolate("SELECT * FROM t WHERE id = %s", (42,))
        assert result == "SELECT * FROM t WHERE id = 42"

    def test_multiple_params(self) -> None:
        result = DoltConnection._interpolate(
            "INSERT INTO t (a, b) VALUES (%s, %s)", ("hello", 5)
        )
        assert result == "INSERT INTO t (a, b) VALUES ('hello', 5)"

    def test_param_count_mismatch_raises(self) -> None:
        with pytest.raises(ValueError, match="Parameter count mismatch"):
            DoltConnection._interpolate("SELECT %s, %s", (1,))

    def test_none_param(self) -> None:
        result = DoltConnection._interpolate("UPDATE t SET x = %s", (None,))
        assert result == "UPDATE t SET x = NULL"


# ---------------------------------------------------------------------------
# _exec_sql timeout
# ---------------------------------------------------------------------------


class TestExecSqlTimeout:
    def test_timeout_raises_runtime_error(self, tmp_path: Path) -> None:
        """Subprocess timeout is caught and raised as RuntimeError."""
        conn = DoltConnection(tmp_path)
        with patch("dolt.connection.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="dolt sql", timeout=30)
            with pytest.raises(RuntimeError, match="timed out after 30s"):
                conn._exec_sql("SELECT 1")

    def test_custom_timeout_passed_to_subprocess(self, tmp_path: Path) -> None:
        """Custom timeout value is forwarded to subprocess.run."""
        conn = DoltConnection(tmp_path)
        with patch("dolt.connection.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="[]", stderr="")
            conn._exec_sql("SELECT 1", timeout=60)
            _, kwargs = mock_run.call_args
            assert kwargs["timeout"] == 60

    def test_default_timeout_is_30(self, tmp_path: Path) -> None:
        """Default timeout is 30 seconds."""
        conn = DoltConnection(tmp_path)
        with patch("dolt.connection.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="[]", stderr="")
            conn._exec_sql("SELECT 1")
            _, kwargs = mock_run.call_args
            assert kwargs["timeout"] == 30


# ---------------------------------------------------------------------------
# _exec_sql error handling
# ---------------------------------------------------------------------------


class TestExecSqlErrors:
    def test_nonzero_return_raises(self, tmp_path: Path) -> None:
        conn = DoltConnection(tmp_path)
        with patch("dolt.connection.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1, stdout="", stderr="table not found"
            )
            with pytest.raises(RuntimeError, match="table not found"):
                conn._exec_sql("SELECT * FROM nope")

    def test_nothing_to_commit_is_ignored(self, tmp_path: Path) -> None:
        conn = DoltConnection(tmp_path)
        with patch("dolt.connection.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1, stdout="", stderr="Nothing to commit"
            )
            result = conn._exec_sql("CALL DOLT_COMMIT('-m', 'test')")
            assert result == "[]"


# ---------------------------------------------------------------------------
# _query_rows JSON parse warning
# ---------------------------------------------------------------------------


class TestQueryRowsJsonParse:
    def test_invalid_json_logs_warning(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """Invalid JSON output logs a warning and returns empty list."""
        conn = DoltConnection(tmp_path)
        import logging

        with (
            patch.object(conn, "_exec_sql", return_value="not valid json"),
            caplog.at_level(logging.WARNING, logger="hydraflow.dolt.connection"),
        ):
            result = conn._query_rows("SELECT 1")
        assert result == []
        assert "Failed to parse Dolt JSON output" in caplog.text

    def test_valid_json_rows_returned(self, tmp_path: Path) -> None:
        """Valid JSON with rows key returns the rows."""
        conn = DoltConnection(tmp_path)
        import json

        payload = json.dumps({"rows": [{"id": 1, "name": "test"}]})
        with patch.object(conn, "_exec_sql", return_value=payload):
            result = conn._query_rows("SELECT * FROM t")
        assert result == [{"id": 1, "name": "test"}]

    def test_empty_output_returns_empty_list(self, tmp_path: Path) -> None:
        conn = DoltConnection(tmp_path)
        with patch.object(conn, "_exec_sql", return_value="  "):
            result = conn._query_rows("SELECT * FROM t")
        assert result == []


# ---------------------------------------------------------------------------
# _parse_select_columns
# ---------------------------------------------------------------------------


class TestParseSelectColumns:
    def test_simple_columns(self) -> None:
        cols = DoltConnection._parse_select_columns("SELECT id, name FROM users")
        assert cols == ["id", "name"]

    def test_star_returns_none(self) -> None:
        cols = DoltConnection._parse_select_columns("SELECT * FROM users")
        assert cols is None

    def test_aliased_column(self) -> None:
        cols = DoltConnection._parse_select_columns(
            "SELECT COUNT(*) AS total FROM users"
        )
        assert cols == ["total"]

    def test_non_select_returns_none(self) -> None:
        cols = DoltConnection._parse_select_columns("INSERT INTO users VALUES (1)")
        assert cols is None
