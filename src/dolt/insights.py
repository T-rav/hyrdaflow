"""Repositories for review records, harness failures, retrospectives, and curated manifest."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dolt.connection import DoltConnection


class ReviewRecordRepository:
    """Append/query the ``review_records`` table."""

    def __init__(self, db: DoltConnection) -> None:
        self.db = db

    def append(self, record: dict) -> None:
        """Insert a new review record."""
        self.db.execute(
            "INSERT INTO review_records (data_json) VALUES (%s)",
            (json.dumps(record),),
        )

    def query(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return recent review records."""
        rows = self.db.fetchall(
            "SELECT id, data_json, timestamp "
            "FROM review_records ORDER BY id DESC LIMIT %s",
            (limit,),
        )
        return [
            {
                "id": r[0],
                "record": json.loads(r[1]) if r[1] else {},
                "created_at": r[2],
            }
            for r in rows
        ]


class HarnessFailureRepository:
    """Append/query the ``harness_failures`` table."""

    def __init__(self, db: DoltConnection) -> None:
        self.db = db

    def append(self, failure: dict) -> None:
        """Insert a new harness failure record."""
        self.db.execute(
            "INSERT INTO harness_failures (data_json) VALUES (%s)",
            (json.dumps(failure),),
        )

    def query(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return recent harness failures."""
        rows = self.db.fetchall(
            "SELECT id, data_json, timestamp "
            "FROM harness_failures ORDER BY id DESC LIMIT %s",
            (limit,),
        )
        return [
            {
                "id": r[0],
                "failure": json.loads(r[1]) if r[1] else {},
                "created_at": r[2],
            }
            for r in rows
        ]


class RetrospectiveRepository:
    """Append/query the ``retrospectives`` table."""

    def __init__(self, db: DoltConnection) -> None:
        self.db = db

    def append(self, retrospective: dict) -> None:
        """Insert a new retrospective."""
        self.db.execute(
            "INSERT INTO retrospectives (data_json) VALUES (%s)",
            (json.dumps(retrospective),),
        )

    def query(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return recent retrospectives."""
        rows = self.db.fetchall(
            "SELECT id, data_json, timestamp "
            "FROM retrospectives ORDER BY id DESC LIMIT %s",
            (limit,),
        )
        return [
            {
                "id": r[0],
                "retrospective": json.loads(r[1]) if r[1] else {},
                "created_at": r[2],
            }
            for r in rows
        ]


class CuratedManifestRepository:
    """CRUD on the ``curated_manifest`` table."""

    def __init__(self, db: DoltConnection) -> None:
        self.db = db

    def upsert(self, key: str, entry: dict) -> None:
        """Insert or replace a manifest entry."""
        self.db.execute(
            "REPLACE INTO curated_manifest (manifest_key, entry_json) VALUES (%s, %s)",
            (key, json.dumps(entry)),
        )

    def get(self, key: str) -> dict | None:
        """Return a manifest entry, or ``None``."""
        row = self.db.fetchone(
            "SELECT entry_json FROM curated_manifest WHERE manifest_key = %s",
            (key,),
        )
        return json.loads(row[0]) if row else None

    def get_all(self) -> dict[str, dict]:
        """Return the full manifest as a dict."""
        rows = self.db.fetchall(
            "SELECT manifest_key, entry_json FROM curated_manifest"
        )
        return {r[0]: json.loads(r[1]) for r in rows}

    def delete(self, key: str) -> None:
        """Remove a manifest entry."""
        self.db.execute(
            "DELETE FROM curated_manifest WHERE manifest_key = %s", (key,)
        )
