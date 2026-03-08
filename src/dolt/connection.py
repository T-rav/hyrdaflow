"""Manages Dolt sql-server process and MySQL connection."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import mysql.connector


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
    """Manages a Dolt sql-server child process and MySQL connection."""

    def __init__(self, dolt_dir: Path, *, port: int = 3307) -> None:
        self.dolt_dir = dolt_dir
        self.port = port
        self._server_proc: subprocess.Popen | None = None  # type: ignore[type-arg]
        self._conn: mysql.connector.MySQLConnection | None = None  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Init repo, start server, apply schema, seed singleton rows."""
        self._init_repo()
        self._start_server()
        self._ensure_schema()
        self._ensure_singleton_rows()

    def close(self) -> None:
        """Close connection and terminate server."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
        if self._server_proc is not None:
            try:
                self._server_proc.terminate()
                self._server_proc.wait(timeout=5)
            except Exception:
                pass
            self._server_proc = None

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
            cwd=self.dolt_dir,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"dolt init failed (rc={result.returncode}): {result.stderr.strip()}"
            )

    def _start_server(self) -> None:
        """Start ``dolt sql-server``, wait for connection, create database."""
        self._server_proc = subprocess.Popen(
            [
                "dolt",
                "sql-server",
                "--port",
                str(self.port),
                "--host",
                "127.0.0.1",
            ],
            cwd=self.dolt_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Wait for the server to accept connections.
        last_err: Exception | None = None
        for _ in range(30):
            try:
                conn = mysql.connector.connect(
                    host="127.0.0.1",
                    port=self.port,
                    user="root",
                )
                # Create the hydraflow database if it doesn't exist.
                cur = conn.cursor()
                cur.execute("CREATE DATABASE IF NOT EXISTS hydraflow")
                cur.close()
                conn.close()
                break
            except Exception as exc:
                last_err = exc
                time.sleep(0.5)
        else:
            raise RuntimeError(
                f"Could not connect to Dolt server after 30 retries: {last_err}"
            )

        # Now connect to the hydraflow database with autocommit.
        self._conn = mysql.connector.connect(
            host="127.0.0.1",
            port=self.port,
            user="root",
            database="hydraflow",
            autocommit=True,
        )

    def _ensure_schema(self) -> None:
        """Read and execute the initial schema migration."""
        if not _SCHEMA_PATH.exists():
            return
        sql = _SCHEMA_PATH.read_text()
        cur = self.cursor()
        for statement in sql.split(";"):
            statement = statement.strip()
            if statement:
                cur.execute(statement)
        cur.close()

    def _ensure_singleton_rows(self) -> None:
        """Insert default singleton rows if missing."""
        cur = self.cursor()
        for table in _SINGLETON_TABLES:
            cur.execute(f"INSERT IGNORE INTO {table} (id) VALUES (1)")  # noqa: S608
        cur.close()

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def cursor(self) -> mysql.connector.cursor.MySQLCursor:
        """Return a cursor, reconnecting if needed."""
        if self._conn is None or not self._conn.is_connected():
            self._conn = mysql.connector.connect(
                host="127.0.0.1",
                port=self.port,
                user="root",
                database="hydraflow",
                autocommit=True,
            )
        return self._conn.cursor()

    def fetchone(
        self, query: str, params: tuple | None = None  # type: ignore[type-arg]
    ) -> tuple | None:  # type: ignore[type-arg]
        """Execute *query* and return a single row."""
        cur = self.cursor()
        cur.execute(query, params or ())
        row = cur.fetchone()
        cur.close()
        return row

    def fetchall(
        self, query: str, params: tuple | None = None  # type: ignore[type-arg]
    ) -> list[tuple]:  # type: ignore[type-arg]
        """Execute *query* and return all rows."""
        cur = self.cursor()
        cur.execute(query, params or ())
        rows = cur.fetchall()
        cur.close()
        return rows

    def execute(
        self, query: str, params: tuple | None = None  # type: ignore[type-arg]
    ) -> None:
        """Execute a write query."""
        cur = self.cursor()
        cur.execute(query, params or ())
        cur.close()

    # ------------------------------------------------------------------
    # Dolt version-control helpers
    # ------------------------------------------------------------------

    def commit(self, message: str) -> None:
        """Stage all changes and create a Dolt commit."""
        self.execute("CALL DOLT_ADD('-A')")
        self.execute("CALL DOLT_COMMIT(%s)", (message,))

    def tag(self, tag_name: str, message: str) -> None:
        """Create a Dolt tag."""
        self.execute("CALL DOLT_TAG(%s, %s)", (tag_name, message))

    def diff(
        self, from_ref: str, to_ref: str, table: str
    ) -> list[tuple]:  # type: ignore[type-arg]
        """Return the diff between two refs for a table."""
        return self.fetchall(
            "SELECT * FROM DOLT_DIFF(%s, %s, %s)", (from_ref, to_ref, table)
        )
