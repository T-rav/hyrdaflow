"""Dolt database connection using CLI-embedded mode (no server required)."""

from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger("hydraflow.dolt.connection")

_SINGLETON_TABLES = (
    "lifetime_stats",
    "session_counters",
    "memory_state",
    "manifest_state",
    "metrics_state",
    "active_crate",
)

_SCHEMA_PATH = (
    Path(__file__).parent.parent / "migrations_data" / "dolt" / "001_initial_schema.sql"
)


class DoltConnection:
    """Embedded Dolt connection using ``dolt sql`` CLI — no server required.

    All queries run via ``dolt sql -q`` subprocess calls against the local
    Dolt repository directory. This is simpler, faster to start, and works
    without port management or MySQL client libraries.
    """

    def __init__(self, dolt_dir: Path, *, port: int = 3307) -> None:
        self.dolt_dir = dolt_dir
        # port is accepted for API compat but unused in CLI mode
        self.port = port

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Init repo, apply schema, seed singleton rows."""
        self._init_repo()
        self._ensure_schema()
        self._ensure_singleton_rows()

    def close(self) -> None:
        """No-op — CLI mode has no persistent connection."""

    # ------------------------------------------------------------------
    # Internal setup
    # ------------------------------------------------------------------

    def _init_repo(self) -> None:
        """Run ``dolt init`` if ``.dolt`` doesn't exist."""
        dolt_meta = self.dolt_dir / ".dolt"
        if dolt_meta.exists():
            return
        self.dolt_dir.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ["dolt", "init"],
            check=False, cwd=self.dolt_dir,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"dolt init failed (rc={result.returncode}): {result.stderr.strip()}"
            )
        logger.info("Initialised Dolt repo at %s", self.dolt_dir)

    def _ensure_schema(self) -> None:
        """Read and execute the initial schema migration."""
        if not _SCHEMA_PATH.exists():
            return
        sql = _SCHEMA_PATH.read_text()
        for statement in sql.split(";"):
            stmt = statement.strip()
            if stmt:
                self._exec_sql(stmt)

    def _ensure_singleton_rows(self) -> None:
        """Insert default singleton rows if missing."""
        for table in _SINGLETON_TABLES:
            self._exec_sql(f"INSERT IGNORE INTO {table} (id) VALUES (1)")

    # ------------------------------------------------------------------
    # Low-level SQL execution
    # ------------------------------------------------------------------

    def _exec_sql(
        self, query: str, params: tuple[Any, ...] | None = None, *, timeout: int = 30
    ) -> str:
        """Execute SQL via ``dolt sql -q`` and return raw stdout.

        Parameters are interpolated safely using Python string formatting
        with proper escaping for SQL values.
        """
        final_query = self._interpolate(query, params) if params else query
        try:
            result = subprocess.run(
                ["dolt", "sql", "-q", final_query, "-r", "json"],
                check=False, cwd=self.dolt_dir,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"dolt sql timed out after {timeout}s\nQuery: {final_query}"
            ) from exc
        if result.returncode != 0:
            stderr = result.stderr.strip()
            # Ignore "nothing to commit" errors
            if "nothing to commit" in stderr.lower():
                return "[]"
            raise RuntimeError(f"dolt sql failed: {stderr}\nQuery: {final_query}")
        return result.stdout

    @staticmethod
    def _interpolate(query: str, params: tuple[Any, ...]) -> str:
        """Replace %s placeholders with properly escaped SQL values."""
        parts = query.split("%s")
        if len(parts) - 1 != len(params):
            raise ValueError(
                f"Parameter count mismatch: {len(parts) - 1} placeholders, "
                f"{len(params)} params"
            )
        result = parts[0]
        for i, param in enumerate(params):
            result += _sql_escape(param) + parts[i + 1]
        return result

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def fetchone(
        self, query: str, params: tuple[Any, ...] | None = None
    ) -> tuple[Any, ...] | None:
        """Execute *query* and return a single row as a tuple, or None."""
        rows = self._query_rows(query, params)
        if not rows:
            return None
        row = rows[0]
        col_order = self._parse_select_columns(query)
        return self._row_to_tuple(row, col_order)

    def fetchall(
        self, query: str, params: tuple[Any, ...] | None = None
    ) -> list[tuple[Any, ...]]:
        """Execute *query* and return all rows as list of tuples."""
        rows = self._query_rows(query, params)
        col_order = self._parse_select_columns(query)
        return [self._row_to_tuple(r, col_order) for r in rows]

    def fetchall_dicts(
        self, query: str, params: tuple[Any, ...] | None = None
    ) -> list[dict[str, Any]]:
        """Execute *query* and return all rows as list of dicts."""
        return self._query_rows(query, params)

    def execute(
        self, query: str, params: tuple[Any, ...] | None = None
    ) -> None:
        """Execute a write query (INSERT, UPDATE, DELETE)."""
        self._exec_sql(query, params)

    def cursor(self) -> DoltCLICursor:
        """Return a cursor-like object for compat with code expecting cursors."""
        return DoltCLICursor(self)

    @staticmethod
    def _parse_select_columns(query: str) -> list[str] | None:
        """Parse column names from a SELECT query to preserve ordering.

        Returns a list of column names if the query is a simple SELECT,
        or None for ``SELECT *`` / unparseable queries.
        """
        m = re.match(r"\s*SELECT\s+(.+?)\s+FROM\s+", query, re.IGNORECASE | re.DOTALL)
        if not m:
            return None
        col_expr = m.group(1).strip()
        if col_expr == "*":
            return None
        # Split on commas, strip whitespace, handle aliased columns
        cols = []
        for part in col_expr.split(","):
            part = part.strip()
            if not part:
                continue
            # Handle "expr AS alias" — use the alias
            alias_match = re.search(r"\bAS\s+(\w+)\s*$", part, re.IGNORECASE)
            if alias_match:
                cols.append(alias_match.group(1))
            else:
                # Take the last word (handles "table.column")
                cols.append(part.split(".")[-1].strip())
        return cols if cols else None

    @staticmethod
    def _row_to_tuple(row: dict[str, Any], col_order: list[str] | None) -> tuple[Any, ...]:
        """Convert a dict row to a tuple respecting *col_order*."""
        if col_order:
            return tuple(row.get(c) for c in col_order)
        return tuple(row.values())

    def _query_rows(
        self, query: str, params: tuple[Any, ...] | None = None
    ) -> list[dict[str, Any]]:
        """Execute a SELECT and parse JSON output into list of dicts."""
        raw = self._exec_sql(query, params)
        if not raw.strip():
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Failed to parse Dolt JSON output: %s", raw[:200])
            return []
        # dolt sql -r json returns {"rows": [...]} for SELECT queries
        if isinstance(data, dict) and "rows" in data:
            return data["rows"]
        if isinstance(data, list):
            return data
        return []

    # ------------------------------------------------------------------
    # Dolt version-control helpers
    # ------------------------------------------------------------------

    def commit(self, message: str) -> None:
        """Stage all changes and create a Dolt commit."""
        self._exec_sql("CALL DOLT_ADD('-A')")
        try:
            self._exec_sql(f"CALL DOLT_COMMIT('-m', {_sql_escape(message)})")
        except RuntimeError as e:
            if "nothing to commit" not in str(e).lower():
                raise

    def tag(self, tag_name: str, message: str) -> None:
        """Create a Dolt tag."""
        self._exec_sql(
            f"CALL DOLT_TAG({_sql_escape(tag_name)}, '-m', {_sql_escape(message)})"
        )

    def diff(
        self, from_ref: str, to_ref: str, table: str
    ) -> list[dict[str, Any]]:
        """Return the diff between two refs for a table."""
        return self._query_rows(
            "SELECT * FROM DOLT_DIFF(%s, %s, %s)", (from_ref, to_ref, table)
        )


class DoltCLICursor:
    """Minimal cursor-like wrapper for DoltConnection CLI mode.

    Supports execute/fetchone/fetchall/close for compat with code
    that was written for mysql.connector cursors.
    """

    def __init__(self, conn: DoltConnection) -> None:
        self._conn = conn
        self._last_rows: list[dict[str, Any]] = []
        self.description: list[tuple[str, ...]] | None = None

    def execute(self, query: str, params: tuple[Any, ...] | None = None) -> None:
        raw = self._conn._exec_sql(query, params)
        if not raw.strip():
            self._last_rows = []
            self.description = None
            return
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            self._last_rows = []
            self.description = None
            return
        if isinstance(data, dict) and "rows" in data:
            self._last_rows = data["rows"]
        elif isinstance(data, list):
            self._last_rows = data
        else:
            self._last_rows = []
        if self._last_rows:
            self.description = [(k,) for k in self._last_rows[0].keys()]
        else:
            self.description = None

    def fetchone(self) -> tuple[Any, ...] | None:
        if not self._last_rows:
            return None
        row = self._last_rows.pop(0)
        return tuple(row.values())

    def fetchall(self) -> list[tuple[Any, ...]]:
        rows = [tuple(r.values()) for r in self._last_rows]
        self._last_rows = []
        return rows

    def close(self) -> None:
        self._last_rows = []
        self.description = None


def _sql_escape(value: Any) -> str:
    """Escape a Python value for safe inclusion in a SQL string."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int | float):
        return str(value)
    s = str(value)
    # Escape single quotes by doubling them
    s = s.replace("'", "''")
    # Escape backslashes
    s = s.replace("\\", "\\\\")
    return f"'{s}'"
