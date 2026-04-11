"""Embedded Dolt backend for HydraFlow state persistence.

Stores the full ``StateData`` JSON document in a local ``.dolt`` repository,
giving versioned state with time-travel, diff, and branch capabilities —
without running a separate database server.

Requires the ``dolt`` CLI to be installed (``brew install dolt`` or
https://docs.dolthub.com/introduction/installation).
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess  # nosec B404 — required for dolt CLI interaction
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger("hydraflow.dolt")

# Path to the migration SQL file applied on first init
_SCHEMA_FILE = (
    Path(__file__).resolve().parent.parent
    / "migrations"
    / "dolt"
    / "001_initial_schema.sql"
)


class DoltBackend:
    """Embedded Dolt state backend.

    Manages a ``.dolt`` repo at ``dolt_dir`` and provides read/write
    operations for state data.  No Dolt server process is needed — all
    operations use the ``dolt sql -q`` CLI.
    """

    def __init__(self, dolt_dir: Path) -> None:
        self._dir = dolt_dir
        self._dolt = shutil.which("dolt")
        if not self._dolt:
            msg = "dolt CLI not found — install via 'brew install dolt' or https://docs.dolthub.com"
            raise FileNotFoundError(msg)
        self._ensure_repo()

    def _run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        """Run a dolt CLI command in the repo directory."""
        cmd = [self._dolt, *args]
        result = subprocess.run(  # nosec B603 — dolt CLI path resolved via shutil.which
            cmd,
            cwd=str(self._dir),
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if check and result.returncode != 0:
            logger.error("dolt %s failed: %s", args[0], result.stderr)
            result.check_returncode()
        return result

    def _sql(self, query: str) -> str:
        """Execute a SQL query and return stdout."""
        result = self._run("sql", "-q", query, "-r", "json")
        return result.stdout

    def _sql_exec(self, query: str) -> None:
        """Execute a SQL statement (no result needed)."""
        self._run("sql", "-q", query)

    def _ensure_repo(self) -> None:
        """Initialize the Dolt repo and apply schema migrations if needed."""
        if not (self._dir / ".dolt").is_dir():
            self._dir.mkdir(parents=True, exist_ok=True)
            # Set identity before init (required by dolt)
            self._run(
                "config", "--global", "--add", "user.name", "HydraFlow", check=False
            )
            self._run(
                "config",
                "--global",
                "--add",
                "user.email",
                "hydraflow@local",
                check=False,
            )
            self._run("init")
            logger.info("Initialized Dolt repo at %s", self._dir)

        # Apply schema from migration file
        if _SCHEMA_FILE.is_file():
            schema_sql = _SCHEMA_FILE.read_text()
            # Strip comment lines before splitting on semicolons
            lines = [
                ln for ln in schema_sql.splitlines() if not ln.strip().startswith("--")
            ]
            clean_sql = "\n".join(lines)
            for raw_stmt in clean_sql.split(";"):
                stmt = raw_stmt.strip()
                if stmt:
                    self._sql_exec(stmt + ";")

        # Stage and commit schema if new
        self._run("add", ".")
        result = self._run("status", check=False)
        if "nothing to commit" not in result.stdout:
            self._run("commit", "-m", "Initialize schema")
            logger.info("Dolt schema initialized")

    # --- State read/write ---

    def load_state(self) -> dict[str, object] | None:
        """Load the state JSON document. Returns ``None`` if no state stored."""
        try:
            raw = self._sql("SELECT data FROM state WHERE id = 1;")
            rows = json.loads(raw)
            if not rows or not rows.get("rows"):
                return None
            data_str = rows["rows"][0]["data"]
            if isinstance(data_str, str):
                return json.loads(data_str)
            return data_str
        except (
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            json.JSONDecodeError,
            KeyError,
            IndexError,
        ):
            logger.warning("Failed to load state from Dolt", exc_info=True)
            return None

    def save_state(self, data: str) -> None:
        """Save the state JSON document (upsert).

        Uses a temp SQL file for large payloads to avoid CLI argument limits.
        """
        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        escaped = data.replace("\\", "\\\\").replace("'", "''")
        sql = f"REPLACE INTO state (id, data, updated_at) VALUES (1, '{escaped}', '{now}');"

        # Write SQL to temp file and execute via source
        sql_file = self._dir / ".tmp_state.sql"
        try:
            sql_file.write_text(sql)
            self._run("sql", "--file", str(sql_file))
        finally:
            sql_file.unlink(missing_ok=True)

    def commit(self, message: str = "state update") -> None:
        """Stage all changes and create a Dolt commit."""
        self._run("add", ".")
        result = self._run("status", check=False)
        if "nothing to commit" not in result.stdout:
            self._run("commit", "-m", message)

    # --- Session read/write ---

    def save_session(self, session_id: str, repo: str, data: str, status: str) -> None:
        """Upsert a session record."""
        escaped_data = data.replace("\\", "\\\\").replace("'", "''")
        escaped_id = session_id.replace("'", "''")
        escaped_repo = repo.replace("'", "''")
        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        self._sql_exec(
            f"REPLACE INTO sessions (session_id, repo, data, started_at, status) "
            f"VALUES ('{escaped_id}', '{escaped_repo}', '{escaped_data}', '{now}', '{status}');"
        )

    def load_sessions(self, repo: str | None = None, limit: int = 50) -> list[dict]:
        """Load recent sessions, newest first."""
        escaped_repo = repo.replace("'", "''") if repo else ""
        where = f"WHERE repo = '{escaped_repo}'" if repo else ""
        try:
            raw = self._sql(
                f"SELECT data FROM sessions {where} ORDER BY started_at DESC LIMIT {limit};"  # nosec B608
            )
            rows = json.loads(raw)
            results = []
            for row in rows.get("rows", []):
                d = row.get("data", "")
                if isinstance(d, str):
                    results.append(json.loads(d))
                else:
                    results.append(d)
            return results
        except (
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            json.JSONDecodeError,
        ):
            logger.warning("Failed to load sessions from Dolt", exc_info=True)
            return []

    def get_session(self, session_id: str) -> dict[str, object] | None:
        """Load a single session by ID."""
        escaped = session_id.replace("'", "''")
        try:
            raw = self._sql(
                f"SELECT data FROM sessions WHERE session_id = '{escaped}';"  # nosec B608
            )
            rows = json.loads(raw)
            if not rows or not rows.get("rows"):
                return None
            d = rows["rows"][0]["data"]
            return json.loads(d) if isinstance(d, str) else d
        except (
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            json.JSONDecodeError,
            KeyError,
            IndexError,
        ):
            return None

    def delete_session(self, session_id: str) -> bool:
        """Delete a session. Returns True if a row was deleted."""
        escaped = session_id.replace("'", "''")
        try:
            self._sql_exec(f"DELETE FROM sessions WHERE session_id = '{escaped}';")  # nosec B608
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return False

    # --- Dedup sets (replaces JSON array files) ---

    def get_dedup_set(self, set_name: str) -> set[str]:
        """Load a dedup set (e.g. 'proposed_categories', 'filed_patterns')."""
        try:
            raw = self._sql(
                f"SELECT value FROM dedup_sets WHERE set_name = '{set_name}';"  # nosec B608
            )
            rows = json.loads(raw)
            return {row["value"] for row in rows.get("rows", [])}
        except (
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            json.JSONDecodeError,
        ):
            return set()

    def add_to_dedup_set(self, set_name: str, value: str) -> None:
        """Add a value to a dedup set."""
        escaped = value.replace("'", "''")
        self._sql_exec(
            f"INSERT IGNORE INTO dedup_sets (set_name, value) "
            f"VALUES ('{set_name}', '{escaped}');"
        )

    def set_dedup_set(self, set_name: str, values: set[str]) -> None:
        """Replace all values in a dedup set."""
        self._sql_exec(f"DELETE FROM dedup_sets WHERE set_name = '{set_name}';")  # nosec B608
        for v in values:
            self.add_to_dedup_set(set_name, v)

    # --- History / time-travel ---

    def log(self, limit: int = 10) -> list[dict]:
        """Return recent Dolt commits."""
        try:
            raw = self._sql(
                f"SELECT commit_hash, committer, message, date "  # nosec B608
                f"FROM dolt_log LIMIT {limit};"
            )
            return json.loads(raw).get("rows", [])
        except (
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            json.JSONDecodeError,
        ):
            return []
