"""Repository classes for issue/PR tracking."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dolt.connection import DoltConnection


class IssueRepository:
    """CRUD on the ``issues`` table (issue_number, field, value)."""

    def __init__(self, db: DoltConnection) -> None:
        self.db = db

    def set_field(self, issue: int, field: str, value: str) -> None:
        """Upsert a field for an issue."""
        self.db.execute(
            "REPLACE INTO issues (issue_number, field, value) VALUES (%s, %s, %s)",
            (issue, field, value),
        )

    def get_field(self, issue: int, field: str) -> str | None:
        """Return the value of *field* for *issue*, or ``None``."""
        row = self.db.fetchone(
            "SELECT value FROM issues WHERE issue_number = %s AND field = %s",
            (issue, field),
        )
        return row[0] if row else None

    def remove_field(self, issue: int, field: str) -> None:
        """Delete a single field for an issue."""
        self.db.execute(
            "DELETE FROM issues WHERE issue_number = %s AND field = %s",
            (issue, field),
        )

    def get_all_issues(self) -> dict[int, dict[str, str]]:
        """Return all issues grouped by issue_number."""
        rows = self.db.fetchall("SELECT issue_number, field, value FROM issues")
        result: dict[int, dict[str, str]] = {}
        for issue_number, field, value in rows:
            result.setdefault(issue_number, {})[field] = value
        return result


class PRRepository:
    """CRUD on the ``prs`` table (pr_number, status)."""

    def __init__(self, db: DoltConnection) -> None:
        self.db = db

    def mark(self, pr: int, status: str) -> None:
        """Set or update the status of a PR."""
        self.db.execute(
            "REPLACE INTO prs (pr_number, status) VALUES (%s, %s)",
            (pr, status),
        )

    def get_status(self, pr: int) -> str | None:
        """Return the status of *pr*, or ``None``."""
        row = self.db.fetchone(
            "SELECT status FROM prs WHERE pr_number = %s", (pr,)
        )
        return row[0] if row else None

    def get_all(self) -> list[tuple[int, str]]:
        """Return all PR records as ``(pr_number, status)`` pairs."""
        return self.db.fetchall("SELECT pr_number, status FROM prs")


class BaselineAuditRepository:
    """CRUD on the ``baseline_audit`` table."""

    def __init__(self, db: DoltConnection) -> None:
        self.db = db

    def record_change(self, issue: int, record: dict) -> None:
        """Append an audit record for *issue*."""
        self.db.execute(
            "INSERT INTO baseline_audit (issue_number, record_json) VALUES (%s, %s)",
            (issue, json.dumps(record)),
        )

    def get_records(self, issue: int) -> list[dict]:
        """Return all audit records for *issue*."""
        rows = self.db.fetchall(
            "SELECT record_json FROM baseline_audit "
            "WHERE issue_number = %s ORDER BY id",
            (issue,),
        )
        return [json.loads(r[0]) for r in rows]

    def get_latest(self, issue: int) -> dict | None:
        """Return the most recent audit record for *issue*."""
        row = self.db.fetchone(
            "SELECT record_json FROM baseline_audit "
            "WHERE issue_number = %s ORDER BY id DESC LIMIT 1",
            (issue,),
        )
        return json.loads(row[0]) if row else None
