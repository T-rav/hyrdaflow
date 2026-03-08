"""Repositories for active issues, epics, releases, and pending reports."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dolt.connection import DoltConnection


class ActiveIssueRepository:
    """Tracks active issue numbers."""

    def __init__(self, db: DoltConnection) -> None:
        self.db = db

    def add(self, issue_number: int) -> None:
        """Mark an issue as active."""
        self.db.execute(
            "INSERT IGNORE INTO active_issues (issue_number) VALUES (%s)",
            (issue_number,),
        )

    def remove(self, issue_number: int) -> None:
        """Remove an issue from the active set."""
        self.db.execute(
            "DELETE FROM active_issues WHERE issue_number = %s",
            (issue_number,),
        )

    def get_all(self) -> list[int]:
        """Return all active issue numbers."""
        rows = self.db.fetchall("SELECT issue_number FROM active_issues")
        return [r[0] for r in rows]

    def is_active(self, issue_number: int) -> bool:
        """Check whether an issue is active."""
        row = self.db.fetchone(
            "SELECT 1 FROM active_issues WHERE issue_number = %s",
            (issue_number,),
        )
        return row is not None


class EpicRepository:
    """CRUD for the ``epic_states`` table."""

    def __init__(self, db: DoltConnection) -> None:
        self.db = db

    def upsert(self, epic_id: str, state: dict) -> None:
        """Insert or replace an epic state."""
        self.db.execute(
            "REPLACE INTO epic_states (epic_id, state_json) VALUES (%s, %s)",
            (epic_id, json.dumps(state)),
        )

    def get(self, epic_id: str) -> dict | None:
        """Return the state for *epic_id*, or ``None``."""
        row = self.db.fetchone(
            "SELECT state_json FROM epic_states WHERE epic_id = %s",
            (epic_id,),
        )
        return json.loads(row[0]) if row else None

    def get_all(self) -> dict[str, dict]:
        """Return all epic states."""
        rows = self.db.fetchall("SELECT epic_id, state_json FROM epic_states")
        return {r[0]: json.loads(r[1]) for r in rows}

    def delete(self, epic_id: str) -> None:
        """Remove an epic state."""
        self.db.execute(
            "DELETE FROM epic_states WHERE epic_id = %s", (epic_id,)
        )


class ReleaseRepository:
    """CRUD for the ``releases`` table."""

    def __init__(self, db: DoltConnection) -> None:
        self.db = db

    def create(self, release_id: str, data: dict) -> None:
        """Insert a new release."""
        self.db.execute(
            "INSERT INTO releases (release_id, data_json) VALUES (%s, %s)",
            (release_id, json.dumps(data)),
        )

    def get(self, release_id: str) -> dict | None:
        """Return a release record, or ``None``."""
        row = self.db.fetchone(
            "SELECT data_json FROM releases WHERE release_id = %s",
            (release_id,),
        )
        return json.loads(row[0]) if row else None

    def get_all(self) -> list[dict[str, Any]]:
        """Return all releases."""
        rows = self.db.fetchall("SELECT release_id, data_json FROM releases")
        return [
            {"release_id": r[0], **json.loads(r[1])} for r in rows
        ]

    def delete(self, release_id: str) -> None:
        """Remove a release."""
        self.db.execute(
            "DELETE FROM releases WHERE release_id = %s", (release_id,)
        )


class ReportRepository:
    """Queue for the ``pending_reports`` table."""

    def __init__(self, db: DoltConnection) -> None:
        self.db = db

    def enqueue(self, report: dict) -> None:
        """Add a report to the queue."""
        self.db.execute(
            "INSERT INTO pending_reports (report_json) VALUES (%s)",
            (json.dumps(report),),
        )

    def dequeue(self, limit: int = 10) -> list[dict[str, Any]]:
        """Fetch and remove up to *limit* pending reports."""
        rows = self.db.fetchall(
            "SELECT id, report_json FROM pending_reports "
            "ORDER BY id LIMIT %s",
            (limit,),
        )
        if rows:
            ids = [r[0] for r in rows]
            placeholders = ", ".join(["%s"] * len(ids))
            self.db.execute(
                f"DELETE FROM pending_reports WHERE id IN ({placeholders})",
                tuple(ids),
            )
        return [
            {"id": r[0], "report": json.loads(r[1])} for r in rows
        ]

    def count(self) -> int:
        """Return the number of pending reports."""
        row = self.db.fetchone("SELECT COUNT(*) FROM pending_reports")
        return row[0] if row else 0
